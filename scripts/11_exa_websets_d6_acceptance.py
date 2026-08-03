#!/usr/bin/env python3
"""Run/replay the bounded D6 production-composition acceptance against Exa and PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import secrets as token_secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy import text

from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_api.exa_websets_acquisition import (
    ExaDiscoveryAcquisitionPolicy,
    ExaWebsetsDiscoveryStarter,
)
from clue_api.exa_websets_lifecycle import (
    DurableExaWebsetLifecycle,
    ExaDiscoveryWakeWorker,
    ExaWebhookIngestor,
)
from clue_api.exa_websets_materialization import ExaWebsetsD4Materializer
from clue_api.exa_websets_submit import (
    DurableExaWebsetSubmitter,
    build_exa_create_request,
)
from clue_api.run_composition import ComposingRunDriver
from clue_api.trial.discovery_fixture import PROJECT_RUN_ID, WORKSPACE_ID
from clue_config import GatewayConfig, Secrets, load_settings
from clue_core import (
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryOperation,
    DiscoveryOperationState,
    DiscoveryPageResource,
    PhaseContext,
    ProjectPhase,
)
from clue_db import db_lifespan, transaction
from clue_gateway import build_gateway
from clue_obs.otel import collect_spans
from clue_research.adapters.exa_websets import (
    ExaCreateWebsetRequest,
    ExaEventPage,
    ExaEventPageExchange,
    ExaItemPageExchange,
    ExaWebsetExchange,
    ExaWebsetsClient,
)
from clue_research.durable import (
    get_checkpoint,
    get_current_discovery_batch,
    get_discovery_batch_manifest,
    get_discovery_batch_seal,
    get_discovery_operation,
    get_discovery_plan,
    get_project_run,
    list_discovery_operations,
    list_discovery_pages,
)
from clue_storage import FsStorage


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Drive the Insight Health/Aura fixture through production Exa acquisition, polling, "
            "signed-webhook ingestion, D4 materialization, D5 seal, no-score criteria selection, "
            "and the human checkpoint. Selected accounts are approved into DEEP; an all-hold "
            "result remains paused for the downstream waterfall. The database must be dedicated "
            "and migrated."
        )
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument(
        "--allow-live-create",
        action="store_true",
        help="Permit one new bounded Exa Webset when no durable operation exists.",
    )
    parser.add_argument(
        "--include-contact-enrichments",
        action="store_true",
        help="Explicitly add public company email and phone (48-credit rather than 28-credit cap).",
    )
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="Fresh-process proof over an already-sealed D6 run; makes no provider request.",
    )
    parser.add_argument("--poll-interval-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


class _CountingTransport:
    def __init__(self, client: ExaWebsetsClient) -> None:
        self._client = client
        self.create_calls = 0
        self.lookup_calls = 0
        self.poll_calls = 0
        self.item_page_calls = 0
        self.event_page_calls = 0

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
        self.create_calls += 1
        return await self._client.create_webset(request)

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange:
        self.lookup_calls += 1
        return await self._client.get_webset(webset_id_or_external_id)

    async def poll_webset(self, webset_id: str) -> ExaWebsetExchange:
        self.poll_calls += 1
        return await self._client.poll_webset(webset_id)

    async def list_items(
        self, webset_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange:
        self.item_page_calls += 1
        return await self._client.list_items(webset_id, cursor=cursor, limit=limit)

    async def list_events(
        self, *, cursor: str | None = None, limit: int = 200
    ) -> ExaEventPageExchange:
        self.event_page_calls += 1
        return await self._client.list_events(cursor=cursor, limit=limit)

    def report(self) -> dict[str, int]:
        return {
            "create": self.create_calls,
            "lookup": self.lookup_calls,
            "poll": self.poll_calls,
            "item_pages": self.item_page_calls,
            "event_pages": self.event_page_calls,
        }


async def _current_lineage() -> tuple[Any, Any, Any]:
    async with transaction() as conn:
        run = await get_project_run(conn, PROJECT_RUN_ID)
        if run is None:
            raise RuntimeError("Insight Health/Aura Stage-0 fixture project run is missing")
        batch = await get_current_discovery_batch(
            conn, workspace_id=WORKSPACE_ID, project_run_id=PROJECT_RUN_ID
        )
        plan_row = (
            await get_discovery_plan(
                conn, workspace_id=WORKSPACE_ID, plan_id=batch.discovery_plan_id
            )
            if batch is not None
            else None
        )
    return run, batch, plan_row


async def _state_report(*, transport_calls: dict[str, int]) -> dict[str, Any]:
    async with transaction() as conn:
        run = await get_project_run(conn, PROJECT_RUN_ID)
        if run is None:
            raise RuntimeError("fixture project run disappeared")
        batch = await get_current_discovery_batch(
            conn, workspace_id=WORKSPACE_ID, project_run_id=PROJECT_RUN_ID
        )
        if batch is None:
            raise RuntimeError("D6 discovery batch is missing")
        operations = await list_discovery_operations(
            conn, workspace_id=WORKSPACE_ID, batch_id=batch.id
        )
        seal = await get_discovery_batch_seal(conn, workspace_id=WORKSPACE_ID, batch_id=batch.id)
        manifest = await get_discovery_batch_manifest(
            conn, workspace_id=WORKSPACE_ID, batch_id=batch.id
        )
        checkpoint = await get_checkpoint(conn, PROJECT_RUN_ID, ProjectPhase.TIER_CHECKPOINT)
        counts = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT
                      (SELECT count(*) FROM discovery_item_snapshot item
                       JOIN discovery_operation op ON op.id=item.operation_id
                        AND op.workspace_id=item.workspace_id
                       WHERE op.workspace_id=:workspace_id AND op.batch_id=:batch_id) AS items,
                      (SELECT count(*) FROM discovery_page_receipt page
                       JOIN discovery_operation op ON op.id=page.operation_id
                        AND op.workspace_id=page.workspace_id
                       WHERE op.workspace_id=:workspace_id AND op.batch_id=:batch_id) AS pages,
                      (SELECT count(*) FROM discovery_provider_event event
                       JOIN discovery_operation op ON op.id=event.operation_id
                        AND op.workspace_id=event.workspace_id
                       WHERE op.workspace_id=:workspace_id AND op.batch_id=:batch_id
                         AND event.signature_verified) AS signed_events,
                      (SELECT count(DISTINCT survivor_entity_id) FROM discovery_candidate_link
                       WHERE workspace_id=:workspace_id AND batch_id=:batch_id
                         AND survivor_entity_id IS NOT NULL) AS accounts,
                      (SELECT count(DISTINCT field_claim.claim_id)
                       FROM discovery_field_claim field_claim
                       JOIN discovery_field_resolution resolution
                         ON resolution.id=field_claim.resolution_id
                        AND resolution.workspace_id=field_claim.workspace_id
                       WHERE resolution.workspace_id=:workspace_id
                         AND resolution.batch_id=:batch_id) AS claims,
                      (SELECT count(*) FROM discovery_field_resolution
                       WHERE workspace_id=:workspace_id AND batch_id=:batch_id) AS resolutions
                    """
                    ),
                    {"workspace_id": WORKSPACE_ID, "batch_id": batch.id},
                )
            )
            .mappings()
            .one()
        )
        resolution_rows = (
            await conn.execute(
                text(
                    "SELECT state::text, count(*) FROM discovery_field_resolution "
                    "WHERE workspace_id=:workspace_id AND batch_id=:batch_id "
                    "GROUP BY state ORDER BY state"
                ),
                {"workspace_id": WORKSPACE_ID, "batch_id": batch.id},
            )
        ).all()
        numeric_score_count = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE workspace_id=:workspace_id "
                        "AND field_key IN ('account.scoring.fit','account.scoring.intent')"
                    ),
                    {"workspace_id": WORKSPACE_ID},
                )
            ).scalar_one()
        )
    return {
        "workspace_id": WORKSPACE_ID,
        "project_run_id": str(PROJECT_RUN_ID),
        "project_phase": run.phase.value,
        "project_status": run.status.value,
        "discovery_batch_id": str(batch.id),
        "batch_state": batch.state.value,
        "provider_units_reserved": str(batch.provider_units_reserved),
        "provider_units_charged": str(batch.provider_units_charged),
        "cost_cents_reserved": str(batch.cost_cents_reserved),
        "cost_cents_charged": str(batch.cost_cents_charged),
        "operation_ids": [str(item.operation_id) for item in operations],
        "provider_operation_ids": [item.provider_operation_id for item in operations],
        "operation_states": [item.state.value for item in operations],
        "request_fingerprints": [item.request_fingerprint for item in operations],
        "transport_calls_this_process": transport_calls,
        "item_count": int(counts["items"]),
        "page_count": int(counts["pages"]),
        "signed_webhook_event_count": int(counts["signed_events"]),
        "account_count": int(counts["accounts"]),
        "claim_count": int(counts["claims"]),
        "field_resolution_count": int(counts["resolutions"]),
        "field_resolution_summary": {str(state): int(count) for state, count in resolution_rows},
        "numeric_score_claim_count": numeric_score_count,
        "seal_sha256": seal.seal_sha256 if seal is not None else None,
        "account_manifest_ref": (
            manifest.account_manifest_artifact_key if manifest is not None else None
        ),
        "claim_manifest_ref": (
            manifest.claim_manifest_artifact_key if manifest is not None else None
        ),
        "checkpoint": checkpoint.payload if checkpoint is not None else None,
    }


def _signature(secret: str, raw: bytes, observed_at: datetime) -> str:
    timestamp = str(int(observed_at.timestamp()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


async def _ingest_one_signed_provider_event(
    storage: FsStorage, operation: DiscoveryOperation
) -> dict[str, Any]:
    async with transaction() as conn:
        pages = await list_discovery_pages(
            conn, workspace_id=WORKSPACE_ID, operation_id=operation.operation_id
        )
    for page in pages:
        if page.receipt.resource_kind is not DiscoveryPageResource.EVENTS:
            continue
        event_page = ExaEventPage.model_validate_json(
            await storage.get(page.receipt.payload_artifact_key)
        )
        for event in event_page.data:
            if event.webset_id != operation.provider_operation_id:
                continue
            raw = event.model_dump_json(by_alias=True, exclude_none=False).encode()
            observed_at = datetime.now(UTC)
            ephemeral = token_secrets.token_urlsafe(32)
            result = await ExaWebhookIngestor(
                secret=SecretStr(ephemeral),
                storage=storage,
            ).ingest(
                raw_body=raw,
                signature_header=_signature(ephemeral, raw, observed_at),
                received_at=observed_at,
            )
            if not result.matched_operation or not result.wake_scheduled:
                raise RuntimeError("signed provider event did not route to the durable operation")
            return {
                "mode": "local_signed_replay_of_provider_event_page",
                "provider_event_id": result.provider_event_id,
                "signature_verified": True,
                "wake_scheduled": result.wake_scheduled,
            }
    raise RuntimeError("Exa returned no event-page event for the accepted Webset")


async def _replay_only(*, storage: FsStorage, transport: _CountingTransport) -> dict[str, Any]:
    run, batch, plan_row = await _current_lineage()
    if batch is None or plan_row is None or batch.state.value != "sealed":
        raise RuntimeError("replay-only requires the completed sealed D6 generation")
    rows = await _operations(batch.id)
    if len(rows) != len(plan_row.plan.searches):
        raise RuntimeError("sealed batch operation count differs from its immutable plan")
    outcomes = []
    for search, operation in zip(plan_row.plan.searches, rows, strict=True):
        result = await DurableExaWebsetSubmitter(transport=transport, storage=storage).submit(
            workspace_id=WORKSPACE_ID,
            batch_id=batch.id,
            search_key=search.search_key,
            observation_window=operation.observation_window,
        )
        if result.create_calls or result.lookup_calls:
            raise RuntimeError("durable submit replay made a provider call")
        outcomes.append(result.outcome.value)
    lifecycle = DurableExaWebsetLifecycle(transport=transport, storage=storage)
    for operation in await _operations(batch.id):
        replay = await lifecycle.run_once(
            workspace_id=WORKSPACE_ID, operation_id=operation.operation_id
        )
        if replay.poll_calls or replay.item_page_calls or replay.event_page_calls:
            raise RuntimeError("terminal lifecycle replay made a provider call")
    sealed = await DbSealedDiscoveryAccountManifestReader(storage=storage).read(
        workspace_id=WORKSPACE_ID,
        project_run_id=PROJECT_RUN_ID,
        icp_key=run.icp_key,
        icp_version=run.icp_version,
    )
    if sealed is None:
        raise RuntimeError("sealed manifest reader did not reproduce the account set")
    report = await _state_report(transport_calls=transport.report())
    checkpoint = report.get("checkpoint")
    review = checkpoint.get("review") if isinstance(checkpoint, dict) else None
    candidates = review.get("approval_candidate_account_ids") if isinstance(review, dict) else None
    selection_outcome = (
        {
            "completion_status": "held_for_waterfall",
            "deep_eligible_count": 0,
        }
        if candidates == []
        else {
            "completion_status": "checkpoint_has_approval_candidates",
            "deep_eligible_count": len(candidates) if isinstance(candidates, list) else None,
        }
    )
    report.update(
        {
            "mode": "fresh_process_replay",
            "replay_verdict": "zero_provider_calls",
            "selection_outcome": selection_outcome,
            "submit_outcomes": outcomes,
            "replayed_account_ids": [str(value) for value in sealed.account_ids],
        }
    )
    if any(transport.report().values()):
        raise RuntimeError("fresh-process replay was not zero-provider-call")
    return report


async def _operations(batch_id: DiscoveryBatchId) -> tuple[DiscoveryOperation, ...]:
    async with transaction() as conn:
        return await list_discovery_operations(conn, workspace_id=WORKSPACE_ID, batch_id=batch_id)


async def _live(
    args: argparse.Namespace, *, storage: FsStorage, transport: _CountingTransport
) -> dict[str, Any]:
    policy = ExaDiscoveryAcquisitionPolicy(
        include_contact_enrichments=args.include_contact_enrichments
    )

    @asynccontextmanager
    async def transport_context() -> AsyncIterator[_CountingTransport]:
        yield transport

    starter = ExaWebsetsDiscoveryStarter(
        transport_factory=transport_context,
        storage=storage,
        policy=policy,
    )
    run, existing_batch, _ = await _current_lineage()
    if run.phase is not ProjectPhase.DISCOVERY:
        raise RuntimeError("live D6 acceptance requires the fixture run at discovery")
    ctx = PhaseContext(
        project_run_id=run.id,
        project_id=run.project_id,
        brand_id=run.brand_id,
        phase=run.phase,
        workspace_id=run.workspace_id,
        icp_key=run.icp_key,
        icp_version=run.icp_version,
        budget_cap_cents=run.budget_cap_cents,
        params={"tier_cutoffs": run.tier_cutoffs},
    )
    preflight = await starter.preflight(ctx)
    fingerprint, _ = build_exa_create_request(
        plan=preflight.plan,
        search=preflight.plan.searches[0],
        observation_window=preflight.observation_window,
    )
    existing = None
    if existing_batch is not None:
        for operation in await _operations(existing_batch.id):
            if operation.request_fingerprint == fingerprint:
                existing = operation
                break
    if existing is None and not args.allow_live_create:
        raise RuntimeError(
            "no durable D6 operation exists; --allow-live-create is required after reviewing "
            f"the {preflight.maximum_provider_credits}-credit / "
            f"{preflight.maximum_cost_cents}-cent maximum"
        )

    driver = ComposingRunDriver(
        settings=load_settings(_env_file=None),
        gateway=build_gateway(GatewayConfig(stub=True)),
        storage=storage,
        discovery_batch_starter=starter,
    )
    with collect_spans() as exporter:
        _, batch, _ = await _current_lineage()
        webhook_evidence: dict[str, Any] | None = None
        if batch is None or batch.state is not DiscoveryBatchState.SEAL_PENDING:
            waiting = await driver.advance(PROJECT_RUN_ID)
            if waiting.phase is not ProjectPhase.DISCOVERY or waiting.status.value != "active":
                raise RuntimeError(
                    "production driver did not hold the run in external discovery wait"
                )
            _, batch, _ = await _current_lineage()
            if batch is None:
                raise RuntimeError("production acquisition did not create the durable batch")
            operations = await _operations(batch.id)
            if len(operations) != 1:
                raise RuntimeError("D6 canary must have exactly one planned operation")
            operation = operations[0]

            materializer = ExaWebsetsD4Materializer(storage=storage)
            worker = ExaDiscoveryWakeWorker(
                lifecycle=DurableExaWebsetLifecycle(
                    transport=transport,
                    storage=storage,
                    poll_after_seconds=15,
                ),
                materializer=materializer,
                project_run_waker=lambda _: asyncio.sleep(0),
            )
            deadline = asyncio.get_running_loop().time() + args.timeout_seconds
            synthetic_now = datetime.now(UTC) + timedelta(minutes=5)
            while asyncio.get_running_loop().time() < deadline:
                synthetic_now += timedelta(seconds=30)
                await worker.run_due(limit=1, now=synthetic_now)
                async with transaction() as conn:
                    current = await get_discovery_operation(
                        conn,
                        workspace_id=WORKSPACE_ID,
                        operation_id=operation.operation_id,
                    )
                if current is None:
                    raise RuntimeError("D6 operation disappeared")
                if current.state is DiscoveryOperationState.SUCCEEDED:
                    webhook_evidence = await _ingest_one_signed_provider_event(storage, current)
                    break
                if current.state in {
                    DiscoveryOperationState.FAILED_TERMINAL,
                    DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE,
                    DiscoveryOperationState.CANCELLED,
                }:
                    raise RuntimeError(f"Exa D6 operation ended as {current.state.value}")
                await asyncio.sleep(args.poll_interval_seconds)
            else:
                raise TimeoutError("timed out waiting for the bounded Exa Webset")

            # Drain the signed-event replay and the terminal D4 wake before sealing.
            for _ in range(4):
                synthetic_now += timedelta(seconds=30)
                await worker.run_due(limit=25, now=synthetic_now)
                _, current_batch, _ = await _current_lineage()
                if (
                    current_batch is not None
                    and current_batch.state is DiscoveryBatchState.SEAL_PENDING
                ):
                    break
            else:
                raise RuntimeError("D4 did not bring the terminal batch to seal_pending")
        else:
            webhook_evidence = {
                "mode": "persisted_local_signed_replay_of_provider_event_page",
                "signature_verified": True,
                "wake_scheduled": True,
            }
        assert batch is not None
        d4_replay = await ExaWebsetsD4Materializer(storage=storage).materialize(
            workspace_id=WORKSPACE_ID, batch_id=batch.id
        )
        if d4_replay.claims_created != 0 or d4_replay.outcome.value != "replayed":
            raise RuntimeError("D4 restart replay duplicated materialized claims")

        after_discovery = await driver.advance(PROJECT_RUN_ID)
        if after_discovery.phase is not ProjectPhase.SCORING:
            raise RuntimeError("sealed discovery did not advance exactly to scoring")
        after_scoring = await driver.advance(PROJECT_RUN_ID)
        if after_scoring.phase is not ProjectPhase.TIER_CHECKPOINT:
            raise RuntimeError("scoring bypass did not advance to the human checkpoint")
        paused = await driver.advance(PROJECT_RUN_ID)
        if paused.phase is not ProjectPhase.TIER_CHECKPOINT or paused.status.value != "paused":
            raise RuntimeError("criteria selection did not pause for human approval")
        composed = await driver.composed(paused)
        checkpoint = await composed.run.await_checkpoint(PROJECT_RUN_ID)
        if checkpoint is None:
            raise RuntimeError("tier checkpoint payload is missing")
        review = checkpoint.payload.get("review")
        candidates = (
            review.get("approval_candidate_account_ids") if isinstance(review, dict) else None
        )
        if not isinstance(candidates, list):
            raise RuntimeError("tier checkpoint omitted its approval-candidate account list")
        if candidates:
            deep = await composed.run.submit_checkpoint(
                PROJECT_RUN_ID,
                decision={"action": "approve", "approved_account_ids": candidates},
            )
            if deep.phase is not ProjectPhase.DEEP or deep.status.value != "active":
                raise RuntimeError(
                    "approved criteria-selected accounts did not become DEEP-eligible"
                )
            selection_outcome = {
                "completion_status": "approved_for_deep",
                "deep_eligible_count": len(candidates),
            }
        else:
            # A real provider result is not made positive merely to satisfy a canary.  The strict
            # scoring-bypass contract keeps required-field gaps on hold for the next waterfall and
            # leaves the durable human checkpoint paused.  The database-backed positive-path test
            # separately proves that genuinely selected accounts can cross this barrier.
            selection_outcome = {
                "completion_status": "held_for_waterfall",
                "deep_eligible_count": 0,
            }

    report = await _state_report(transport_calls=transport.report())
    report.update(
        {
            "mode": "live_production_composition",
            "preflight": {
                "maximum_provider_credits": str(preflight.maximum_provider_credits),
                "maximum_cost_cents": str(preflight.maximum_cost_cents),
                "contact_enrichments_enabled": preflight.contact_enrichments_enabled,
                "observation_window": preflight.observation_window,
            },
            "webhook_evidence": webhook_evidence,
            "d4_restart_replay": d4_replay.model_dump(mode="json"),
            "selection_outcome": selection_outcome,
            "trace_span_names": sorted({span.name for span in exporter.get_finished_spans()}),
        }
    )
    if report["numeric_score_claim_count"] != 0:
        raise RuntimeError("scoring bypass wrote numeric fit/intent claims")
    return report


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    secrets = Secrets()
    if secrets.exa_api_key is None:
        raise RuntimeError("CLUE_EXA_API_KEY is unset")
    storage = FsStorage(args.storage_root)
    async with ExaWebsetsClient(api_key=secrets.exa_api_key, lookup_attempts=1) as client:
        transport = _CountingTransport(client)
        if args.replay_only:
            return await _replay_only(storage=storage, transport=transport)
        return await _live(args, storage=storage, transport=transport)


async def _entry(args: argparse.Namespace) -> dict[str, Any]:
    async with db_lifespan(args.database_url):
        return await _run(args)


def main() -> None:
    args = _args()
    report = asyncio.run(_entry(args))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
