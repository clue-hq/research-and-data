"""FI-4 slice 2 — the workspace-setup composition over Stage-0 recon (ratified D-4).

One narrow, flag-gated surface for the onboarding "setting up your workspace" screen:

``POST /stage0/setup``
    Captures the provisioned company website as a real B2 artifact (capture-before-use, the
    same primitive as :mod:`clue_api.conversation_capture`), records the durable
    ``onboarding_input`` (kind ``website``, actor ``human``), and fires the recon driver —
    a background task that invokes the governed ``start_recon`` tool with a deterministic
    operation id, then re-invokes it once per remaining lane (the ratified D-4c post-fast
    kicker: one ``start_recon`` invocation drives exactly one queued lane to a terminal
    state, so fast → background is two invocations, no fleet change). Returns 202
    immediately; truth lives in the durable ``recon_run`` row.

``GET /stage0/setup/current``
    Resolves the caller workspace's current recon through the self-serve provisioning
    record (workspace → brand → website → dedupe hash → latest ``recon_run``) and serves
    lane-level truth from the same rows the ratified ``/stage0/recon/{id}/progress``
    projection reads. The screen's state transitions therefore map 1:1 to durable lane
    states — REQ-08's no-fake-progress floor at lane granularity (slice 3 adds per-field
    events).

Deliberate limits, recorded: the driver is process-local — if the process dies mid-lane the
recon row keeps its last durable state and a repeated ``POST /stage0/setup`` (deterministic
operation ids → tool replay) resumes driving; every id is derived from
``(workspace, sha256(website))`` so retries and double-clicks are replays, never second runs.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Annotated, Any, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import OnboardingInputId, OnboardingInputKind, ReconRunId, operation_id_from_key
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_projections import PROJECTIONS_SCHEMA_VERSION, stage0_progress
from clue_research.stage0 import recon_dedupe_hash, submit_onboarding_input
from clue_storage import StorageBackend
from clue_toolbelt import PreconditionFailed, ToolContext, ToolInvoker

log = get_logger("clue_api.stage0_setup")

#: One invocation drives one queued lane; fast + background is two, plus one slack replay.
_MAX_DRIVER_INVOCATIONS = 3

_TERMINAL_LANE_STATUSES = {"completed", "failed"}


def setup_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    """This surface's tenant seam; production overrides it with the authenticated resolver."""
    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


# Module-level alias: FastAPI resolves stringified annotations against module globals — a
# closure-local alias would be mistaken for a query parameter (the projections_app idiom).
WorkspaceDep = Annotated[str, Depends(setup_workspace_resolver)]


class SetupStartResponse(BaseModel):
    schema_version: str
    status: Literal["started"]


class SetupStatusResponse(BaseModel):
    """Lane-level truth for the setting-up screen; ``complete`` == the fast lane finished
    (the release-into-the-app signal) — the background lane keeps running behind it."""

    schema_version: str
    status: Literal["unavailable", "none", "running", "complete", "failed"]
    recon_run_id: str | None = None
    fast_status: str | None = None
    background_status: str | None = None
    company_website: str | None = None


class _ProvisioningScope(BaseModel):
    brand_id: str
    company_website: str
    workspace_name: str


def create_stage0_setup_router(
    *,
    tool_invoker: ToolInvoker,
    conn_factory: ConnFactory,
    storage: StorageBackend,
) -> APIRouter:
    router = APIRouter(tags=["stage0-setup"])
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    driver_tasks: set[asyncio.Task[None]] = set()

    async def _provisioning_scope(workspace_id: str) -> _ProvisioningScope | None:
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT p.brand_id, p.company_website, w.name AS workspace_name "
                            "FROM self_serve_provisioning p "
                            "JOIN workspace w ON w.workspace_id = p.workspace_id "
                            "WHERE p.workspace_id = :workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None or row["company_website"] is None:
            return None
        return _ProvisioningScope(
            brand_id=row["brand_id"],
            company_website=row["company_website"],
            workspace_name=row["workspace_name"],
        )

    def _website_digest(website: str) -> str:
        return hashlib.sha256(website.strip().casefold().encode("utf-8")).hexdigest()

    async def _drive_recon(
        *,
        workspace_id: str,
        scope: _ProvisioningScope,
        onboarding_input_id: OnboardingInputId,
    ) -> None:
        """Invoke start_recon until both lanes are terminal (bounded; the D-4c kicker)."""
        digest = _website_digest(scope.company_website)
        body: dict[str, Any] = {
            "brand_id": scope.brand_id,
            "name": scope.workspace_name,
            "website": scope.company_website,
            "onboarding_input_ids": [str(onboarding_input_id)],
        }
        operation_id = operation_id_from_key(workspace_id, f"stage0-setup:{digest}")
        try:
            for _ in range(_MAX_DRIVER_INVOCATIONS):
                ctx = ToolContext(
                    workspace_id=workspace_id,
                    actor="human",
                    conn_factory=conn_factory,
                    operation_id=operation_id,
                )
                result = await tool_invoker.invoke("start_recon", body, ctx)
                references = dict(result.references)
                fast = str(references.get("fast_status", ""))
                background = str(references.get("background_status", ""))
                log.info(
                    "stage0_setup.recon_lane_driven",
                    workspace_id=workspace_id,
                    recon_run_id=str(references.get("recon_run_id", "")),
                    fast_status=fast,
                    background_status=background,
                )
                if fast in _TERMINAL_LANE_STATUSES and background in _TERMINAL_LANE_STATUSES:
                    return
        except PreconditionFailed as error:
            # Refused before spend (e.g. the scrape composition is absent). The recon row may
            # not exist; GET current then reports "none" and a retried POST re-fires cleanly.
            log.error(
                "stage0_setup.recon_refused",
                workspace_id=workspace_id,
                reason_codes=list(error.reason_codes),
            )
        except Exception:  # noqa: BLE001 — a background driver must never die silently
            log.exception("stage0_setup.recon_driver_failed", workspace_id=workspace_id)

    @router.post("/stage0/setup", response_model=SetupStartResponse, status_code=202)
    async def start_setup(workspace_id: WorkspaceDep) -> SetupStartResponse:
        scope = await _provisioning_scope(workspace_id)
        if scope is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "setup_unavailable",
                    "reason": "no self-serve provisioning record with a company website "
                    "exists for this workspace",
                },
            )
        digest = _website_digest(scope.company_website)
        operation_id = operation_id_from_key(workspace_id, f"stage0-setup:{digest}")
        onboarding_input_id = OnboardingInputId(
            uuid5(UUID(str(operation_id)), "stage0-setup-website")
        )
        # Capture-before-use: bytes first, capture record second, spend last (the platform
        # contract; same ordering as conversation capture). Replays are ON CONFLICT no-ops.
        ref = await artifacts.persist_body(
            workspace_id=workspace_id,
            data=scope.company_website.encode("utf-8"),
            media_type="text/plain",
        )
        async with conn_factory() as conn:
            await submit_onboarding_input(
                conn,
                workspace_id=workspace_id,
                brand_id=scope.brand_id,
                kind=OnboardingInputKind.WEBSITE,
                artifact_key=ref.artifact_key,
                content_sha256=ref.sha256,
                actor="human",
                source_ref=scope.company_website,
                onboarding_input_id=onboarding_input_id,
            )
        task = asyncio.create_task(
            _drive_recon(
                workspace_id=workspace_id,
                scope=scope,
                onboarding_input_id=onboarding_input_id,
            )
        )
        driver_tasks.add(task)
        task.add_done_callback(driver_tasks.discard)
        return SetupStartResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, status="started")

    @router.get("/stage0/setup/current", response_model=SetupStatusResponse)
    async def current_setup(workspace_id: WorkspaceDep) -> SetupStatusResponse:
        scope = await _provisioning_scope(workspace_id)
        if scope is None:
            return SetupStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION, status="unavailable"
            )
        dedupe = recon_dedupe_hash(
            workspace_id=workspace_id,
            brand_id=scope.brand_id,
            product_id=None,
            identity=scope.company_website,
        )
        async with conn_factory() as conn:
            recon_run_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM recon_run "
                        "WHERE workspace_id = :workspace_id AND dedupe_hash = :dedupe_hash "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"workspace_id": workspace_id, "dedupe_hash": dedupe},
                )
            ).scalar_one_or_none()
        if recon_run_id is None:
            return SetupStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION,
                status="none",
                company_website=scope.company_website,
            )
        view = await stage0_progress(
            recon_run_id=ReconRunId(recon_run_id),
            workspace_id=workspace_id,
            conn_factory=conn_factory,
        )
        if view is None:
            return SetupStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION,
                status="none",
                company_website=scope.company_website,
            )
        if view.fast_status == "failed":
            status: Literal["running", "complete", "failed"] = "failed"
        elif view.fast_status == "completed":
            status = "complete"
        else:
            status = "running"
        return SetupStatusResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION,
            status=status,
            recon_run_id=str(view.recon_run_id),
            fast_status=view.fast_status,
            background_status=view.background_status,
            company_website=scope.company_website,
        )

    return router


__all__ = ["create_stage0_setup_router", "setup_workspace_resolver"]
