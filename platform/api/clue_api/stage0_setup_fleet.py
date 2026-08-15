"""Detached fleet ownership for the FI-4 Stage-0 setup driver (C6).

The HTTP route captures the website bytes and enqueues only durable references. A fleet worker
rehydrates the provisioned scope, invokes one recon lane, and requeues the same task until the two
legacy lanes are terminal. No browser token, URL, or page body enters ``fleet_task.payload_json``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text

from clue_api.client_context_binding import bind_workspace_client
from clue_config import Settings, stage0_policy_from_settings
from clue_core import EntityId, OnboardingInputId, ReconRunId, RunId, operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_fleet import (
    DbWorkQueue,
    FleetTaskKind,
    WorkContext,
    WorkId,
    WorkQueue,
    WorkResult,
)
from clue_obs import get_logger
from clue_research.claimstore import record_run_lineage
from clue_research.stage0 import (
    ClientInput,
    ReconLaneStatus,
    prepare_client_kb_run,
    recon_dedupe_hash,
    start_recon,
    transition_recon_lane,
)
from clue_toolbelt import PreconditionFailed, ToolContext, ToolInvoker

log = get_logger("clue_api.stage0_setup_fleet")

TERMINAL_RECON_LANE_STATUSES = frozenset({"completed", "failed"})


@dataclass(frozen=True, slots=True)
class ProvisioningScope:
    brand_id: str
    company_website: str
    workspace_name: str


class OfficialSiteCrawlEnqueuer(Protocol):
    async def enqueue(self, *, workspace_id: str, recon_run_id: UUID) -> bool: ...


class Stage0ReconEnqueuer(Protocol):
    async def enqueue(
        self,
        *,
        workspace_id: str,
        onboarding_input_id: OnboardingInputId,
        website_digest: str,
        attempt: int,
    ) -> bool: ...


def website_digest(website: str) -> str:
    """Hash exact captured website bytes; deliberately do not case-fold."""

    return hashlib.sha256(website.strip().encode("utf-8")).hexdigest()


def iteration_operation_id(workspace_id: str, digest: str, attempt: int, iteration: int) -> Any:
    return operation_id_from_key(workspace_id, f"stage0-setup:{digest}:a{attempt}:i{iteration}")


def attempt_input_id(workspace_id: str, digest: str, attempt: int) -> OnboardingInputId:
    derived = operation_id_from_key(workspace_id, f"stage0-setup-input:{digest}:a{attempt}")
    return OnboardingInputId(UUID(str(derived)))


class DbStage0ReconEnqueuer:
    """Idempotently offer one captured onboarding attempt to the detached fleet."""

    def __init__(self, queue: WorkQueue | None = None) -> None:
        self._queue = queue if queue is not None else DbWorkQueue()

    async def enqueue(
        self,
        *,
        workspace_id: str,
        onboarding_input_id: OnboardingInputId,
        website_digest: str,
        attempt: int,
    ) -> bool:
        candidate = iteration_operation_id(workspace_id, website_digest, attempt, 0)
        return await self._queue.enqueue(
            kind=FleetTaskKind.STAGE0_RECON,
            work_id=WorkId(UUID(str(candidate))),
            dedup_key=f"stage0-recon:{onboarding_input_id}",
            priority=-200,
            payload={
                "workspace_id": workspace_id,
                "onboarding_input_id": str(onboarding_input_id),
                "website_digest": website_digest,
                "attempt": attempt,
            },
            reopen_terminal=True,
        )


class Stage0ReconWorkHandler:
    """Drive legacy lanes in shadow mode or bootstrap the authoritative crawl cutover."""

    kind = FleetTaskKind.STAGE0_RECON

    def __init__(
        self,
        *,
        tool_invoker: ToolInvoker,
        conn_factory: ConnFactory = transaction,
        crawl_enqueuer: OfficialSiteCrawlEnqueuer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._tool_invoker = tool_invoker
        self._conn_factory = conn_factory
        self._crawl_enqueuer = crawl_enqueuer
        self._settings = settings
        if (
            settings is not None
            and settings.stage0_official_site_crawl_mode == "authoritative"
            and crawl_enqueuer is None
        ):
            raise ValueError("authoritative Stage-0 recon requires the durable crawl enqueuer")

    async def handle(self, context: WorkContext) -> WorkResult:
        workspace_id, onboarding_input_id, digest, attempt = self._payload(context.payload)
        expected_work_id = UUID(str(iteration_operation_id(workspace_id, digest, attempt, 0)))
        if UUID(str(context.work_id)) != expected_work_id:
            raise ValueError("Stage-0 task work id disagrees with its deterministic attempt")
        scope = await self._scope(workspace_id, onboarding_input_id)
        if website_digest(scope.company_website) != digest:
            raise ValueError("Stage-0 task website digest no longer matches captured scope")
        if context.stop_requested.is_set() or context.lease_lost.is_set():
            return WorkResult(outcome="stopped", references={}, requeue=True)

        if (
            self._settings is not None
            and self._settings.stage0_official_site_crawl_mode == "authoritative"
        ):
            return await self._bootstrap_authoritative(
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
                expected_work_id=expected_work_id,
                scope=scope,
            )

        iteration = await self._next_iteration(workspace_id, expected_work_id)
        operation_id = iteration_operation_id(workspace_id, digest, attempt, iteration)
        body: dict[str, Any] = {
            "brand_id": scope.brand_id,
            "name": scope.workspace_name,
            "website": scope.company_website,
            "onboarding_input_ids": [str(onboarding_input_id)],
        }
        try:
            result = await self._tool_invoker.invoke(
                "start_recon",
                body,
                ToolContext(
                    workspace_id=workspace_id,
                    actor="human",
                    conn_factory=self._conn_factory,
                    operation_id=operation_id,
                ),
            )
        except PreconditionFailed as error:
            log.error(
                "stage0_setup.recon_refused",
                workspace_id=workspace_id,
                reason_codes=list(error.reason_codes),
            )
            return WorkResult(
                outcome="refused",
                references={"reason_codes": list(error.reason_codes)},
            )

        references = dict(result.references)
        recon_run_raw = references.get("recon_run_id")
        if recon_run_raw is None:
            raise ValueError("start_recon returned no recon_run_id")
        recon_run_id = UUID(str(recon_run_raw))
        client_entity_raw = references.get("client_entity_id")
        if client_entity_raw is not None:
            async with self._conn_factory() as conn:
                binding = await bind_workspace_client(
                    conn,
                    workspace_id=workspace_id,
                    client_entity_id=EntityId(UUID(str(client_entity_raw))),
                    source_recon_run_id=ReconRunId(recon_run_id),
                )
            log.info(
                "stage0_setup.client_bound",
                workspace_id=workspace_id,
                recon_run_id=str(recon_run_id),
                client_entity_id=str(binding.client_entity_id),
                execution_owner="fleet",
            )
        fast = str(references.get("fast_status", ""))
        background = str(references.get("background_status", ""))
        log.info(
            "stage0_setup.recon_lane_driven",
            workspace_id=workspace_id,
            recon_run_id=str(recon_run_id),
            fast_status=fast,
            background_status=background,
            attempt=attempt,
            iteration=iteration,
            replayed=result.replayed,
            execution_owner="fleet",
        )
        if fast == "completed" and self._crawl_enqueuer is not None:
            await self._crawl_enqueuer.enqueue(
                workspace_id=workspace_id,
                recon_run_id=recon_run_id,
            )
        if fast == "failed":
            return WorkResult(
                outcome="fast_failed",
                references={"recon_run_id": str(recon_run_id)},
            )
        terminal = fast in TERMINAL_RECON_LANE_STATUSES and (
            background in TERMINAL_RECON_LANE_STATUSES
        )
        return WorkResult(
            outcome="completed" if terminal else "lane_committed",
            references={
                "recon_run_id": str(recon_run_id),
                "fast_status": fast,
                "background_status": background,
            },
            requeue=not terminal,
        )

    async def _bootstrap_authoritative(
        self,
        *,
        workspace_id: str,
        onboarding_input_id: OnboardingInputId,
        expected_work_id: UUID,
        scope: ProvisioningScope,
    ) -> WorkResult:
        """Create durable recon lineage without invoking the legacy URL resolver."""

        assert self._settings is not None
        assert self._crawl_enqueuer is not None
        policy = stage0_policy_from_settings(self._settings)
        async with self._conn_factory() as conn:
            recon = await start_recon(
                conn,
                workspace_id=workspace_id,
                brand_id=scope.brand_id,
                dedupe_hash=recon_dedupe_hash(
                    workspace_id=workspace_id,
                    brand_id=scope.brand_id,
                    product_id=None,
                    identity=scope.company_website,
                ),
                onboarding_input_ids=(onboarding_input_id,),
                fast_budget_cents=policy.fast_budget_cents,
                background_budget_cents=policy.background_budget_cents,
                dedupe_ttl_seconds=policy.recon_dedupe_ttl_seconds,
                recon_run_id=ReconRunId(expected_work_id),
            )
            if recon.client_entity_id is None:
                client_entity_id = await prepare_client_kb_run(
                    conn,
                    ClientInput(name=scope.workspace_name, website=scope.company_website),
                    workspace_id=workspace_id,
                    run_id=RunId(recon.fast_run_id),
                )
            else:
                client_entity_id = EntityId(recon.client_entity_id)
                await record_run_lineage(
                    conn,
                    run_id=RunId(recon.fast_run_id),
                    workspace_id=workspace_id,
                    kind="stage0",
                )
            binding = await bind_workspace_client(
                conn,
                workspace_id=workspace_id,
                client_entity_id=client_entity_id,
                source_recon_run_id=recon.id,
            )
            await record_run_lineage(
                conn,
                run_id=RunId(recon.background_run_id),
                workspace_id=workspace_id,
                kind="stage0",
            )
            if recon.fast_status is ReconLaneStatus.QUEUED:
                recon = await transition_recon_lane(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=workspace_id,
                    lane="fast",
                    status=ReconLaneStatus.RUNNING,
                    client_entity_id=client_entity_id,
                )
            elif recon.client_entity_id != client_entity_id:
                raise ValueError("authoritative recon client identity changed during replay")

        log.info(
            "stage0_setup.client_bound",
            workspace_id=workspace_id,
            recon_run_id=str(recon.id),
            client_entity_id=str(binding.client_entity_id),
            execution_owner="fleet",
        )

        enqueued = await self._crawl_enqueuer.enqueue(
            workspace_id=workspace_id,
            recon_run_id=UUID(str(recon.id)),
        )
        log.info(
            "stage0_setup.authoritative_crawl_enqueued",
            workspace_id=workspace_id,
            recon_run_id=str(recon.id),
            enqueued=enqueued,
            execution_owner="fleet",
        )
        return WorkResult(
            outcome="authoritative_crawl_enqueued",
            references={
                "recon_run_id": str(recon.id),
                "fast_status": recon.fast_status.value,
                "background_status": recon.background_status.value,
                "crawl_enqueued": enqueued,
            },
        )

    async def _scope(
        self, workspace_id: str, onboarding_input_id: OnboardingInputId
    ) -> ProvisioningScope:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT p.brand_id, p.company_website, w.name AS workspace_name
                            FROM self_serve_provisioning AS p
                            JOIN workspace AS w ON w.workspace_id = p.workspace_id
                            JOIN onboarding_input AS input
                              ON input.id = :onboarding_input_id
                             AND input.workspace_id = p.workspace_id
                             AND input.brand_id = p.brand_id
                             AND input.kind = 'website'
                            WHERE p.workspace_id = :workspace_id
                              AND p.company_website IS NOT NULL
                            """
                        ),
                        {
                            "workspace_id": workspace_id,
                            "onboarding_input_id": onboarding_input_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ValueError("Stage-0 task cannot rehydrate its workspace-scoped website input")
        return ProvisioningScope(
            brand_id=row["brand_id"],
            company_website=row["company_website"],
            workspace_name=row["workspace_name"],
        )

    async def _next_iteration(self, workspace_id: str, recon_run_id: UUID) -> int:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT fast_status, background_status
                            FROM recon_run
                            WHERE id = :recon_run_id AND workspace_id = :workspace_id
                            """
                        ),
                        {"recon_run_id": recon_run_id, "workspace_id": workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return 0
        if row["fast_status"] not in TERMINAL_RECON_LANE_STATUSES:
            return 0
        if row["background_status"] not in TERMINAL_RECON_LANE_STATUSES:
            return 1
        return 2

    @staticmethod
    def _payload(payload: dict[str, JsonValue]) -> tuple[str, OnboardingInputId, str, int]:
        workspace_id = payload.get("workspace_id")
        onboarding_input_id = payload.get("onboarding_input_id")
        digest = payload.get("website_digest")
        attempt = payload.get("attempt")
        if (
            not isinstance(workspace_id, str)
            or not isinstance(onboarding_input_id, str)
            or not isinstance(digest, str)
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 0
        ):
            raise ValueError("invalid Stage-0 recon task payload")
        return workspace_id, OnboardingInputId(UUID(onboarding_input_id)), digest, attempt


__all__ = [
    "DbStage0ReconEnqueuer",
    "OfficialSiteCrawlEnqueuer",
    "ProvisioningScope",
    "Stage0ReconEnqueuer",
    "Stage0ReconWorkHandler",
    "attempt_input_id",
    "iteration_operation_id",
    "website_digest",
]
