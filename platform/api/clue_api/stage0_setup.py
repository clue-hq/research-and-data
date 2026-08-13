"""FI-4 slice 2 — the workspace-setup composition over Stage-0 recon (ratified D-4).

One narrow, flag-gated surface for the onboarding "setting up your workspace" screen:

``POST /stage0/setup``
    Requires ``research.launch`` on the authenticated path (recon is SPEND; a viewer must
    not be able to trigger it). Captures the provisioned company website as a real B2
    artifact (capture-before-use), records the durable ``onboarding_input`` (kind
    ``website``, actor ``human``), and fires the recon driver. Returns 202; truth lives in
    durable rows.

``GET /stage0/setup/current``
    Serves lane-level truth resolved through the self-serve provisioning record. The status
    vocabulary is honest end to end: ``starting`` (the submission is durably captured but no
    recon row is visible yet — covering both the driver warm-up and the fast lane's single
    enclosing transaction), ``running``/``complete``/``failed`` from the durable lane rows,
    ``none`` (nothing requested), ``unavailable`` (no provisioning record). ``complete``
    additionally carries ``fast_client_kb_version`` and ``fact_count`` so a lane that ran
    but derived nothing is distinguishable from real coverage (review BE-M5). FI-4 slice 3
    adds honest granularity on top: ``fields`` is the per-field state reverse profiling
    actually reached (reduced last-writer-wins from the ``stage0.recon.field`` events, in
    Client-KB baseline order), and ``{fast,background}_budget_exhausted`` say whether a
    lane "completed" by finishing or by hitting its cap — ``None`` until that lane's
    terminal event exists, never a guessed ``False``.

Identity/replay model (review BE-B1/BE-B2):

* ``attempt`` = the durable count of prior FAILED-fast recon runs for this
  ``(workspace, website)`` — retrying after a failure deterministically mints a new attempt,
  while an idle re-POST replays the current one.
* Each driver iteration uses its own operation id
  (``stage0-setup:{digest}:a{attempt}:i{k}``). The production ``ToolInvoker`` journals per
  operation id and REPLAYS a completed one without calling the tool, so a shared id across
  iterations would make the D-4c kicker a no-op; distinct ids make iteration k>0 a fresh
  invocation that the tool resolves onto the same run via live-dedupe and then drives the
  next queued lane. A journal replay of a cached iteration is benign: the driver reads the
  lane references and only continues while a lane is non-terminal.
* A failed fast lane releases its dedupe slot (``transition_recon_lane``), so the next
  attempt's fresh ids create a genuinely new run instead of replaying the failure.
* The website digest deliberately does NOT casefold (the tool's own dedupe hash does): the
  digest must equal the captured artifact bytes' identity, or a case-only website edit would
  trip the capture drift guard (review BE-M8). A case-variant retry simply becomes a new
  capture + attempt whose recon the tool dedupe-shares.

DSAR note (review BE-M7): the captured artifact blob necessarily holds the submitted URL —
that residual is recorded in ``erase_platform_user``'s docstring/backlog. This surface no
longer copies the URL into ``onboarding_input.source_ref`` (append-only, un-redactable).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_tool_context import tool_context_for_principal
from clue_api.auth_wiring import principal_from_request
from clue_core import (
    OnboardingInputId,
    OnboardingInputKind,
    ProjectRunId,
    ReconRunId,
    operation_id_from_key,
)
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_projections import PROJECTIONS_SCHEMA_VERSION, recon_brief, stage0_progress
from clue_research.durable import (
    RECON_FIELD_PROGRESS_KIND,
    RECON_TRANSITION_KIND,
    list_run_events,
)
from clue_research.stage0 import (
    CLIENT_BASELINE_FIELDS,
    ReconLaneStatus,
    recon_dedupe_hash,
    submit_onboarding_input,
)
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


class SetupFieldState(BaseModel):
    """One Client-KB field's latest reported state, from the recon lane that reported it."""

    field_key: str
    lane: str
    status: str


class SetupStatusResponse(BaseModel):
    """Lane-level truth for the setting-up screen; ``complete`` == the fast lane finished
    (the release-into-the-app signal) — the background lane keeps running behind it."""

    schema_version: str
    status: Literal["unavailable", "none", "starting", "running", "complete", "failed"]
    recon_run_id: str | None = None
    fast_status: str | None = None
    background_status: str | None = None
    company_website: str | None = None
    # Coverage honesty (review BE-M5): a completed lane that derived zero facts is
    # distinguishable from real coverage. None until the fast lane completes.
    fast_client_kb_version: int | None = None
    fact_count: int | None = None
    # FI-4 slice 3: real per-field motion — what reverse profiling actually reached, in
    # Client-KB baseline order. Empty until the running lane emits its first field.
    fields: list[SetupFieldState] = []
    # None while a lane has not reached a terminal COMPLETED state (or for a run that
    # predates the flag): "we do not know yet", never a fabricated False.
    fast_budget_exhausted: bool | None = None
    background_budget_exhausted: bool | None = None


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
    # Best-effort same-process duplicate-driver suppression; the durable model (per-attempt
    # deterministic ids + the tool's advisory locks) is the real safety net across processes.
    driving_workspaces: set[str] = set()

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
        # No casefold: must match the captured bytes exactly (module docstring, BE-M8).
        return hashlib.sha256(website.strip().encode("utf-8")).hexdigest()

    def _dedupe(workspace_id: str, scope: _ProvisioningScope) -> str:
        return recon_dedupe_hash(
            workspace_id=workspace_id,
            brand_id=scope.brand_id,
            product_id=None,
            identity=scope.company_website,
        )

    async def _failed_attempt_count(workspace_id: str, dedupe_hash: str) -> int:
        async with conn_factory() as conn:
            return int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM recon_run "
                            "WHERE workspace_id = :workspace_id "
                            "AND dedupe_hash = :dedupe_hash AND fast_status = 'failed'"
                        ),
                        {"workspace_id": workspace_id, "dedupe_hash": dedupe_hash},
                    )
                ).scalar_one()
            )

    def _iteration_operation_id(
        workspace_id: str, digest: str, attempt: int, iteration: int
    ) -> Any:
        return operation_id_from_key(workspace_id, f"stage0-setup:{digest}:a{attempt}:i{iteration}")

    def _attempt_input_id(workspace_id: str, digest: str, attempt: int) -> OnboardingInputId:
        derived = operation_id_from_key(workspace_id, f"stage0-setup-input:{digest}:a{attempt}")
        return OnboardingInputId(UUID(str(derived)))

    async def _drive_recon(
        *,
        workspace_id: str,
        scope: _ProvisioningScope,
        attempt: int,
        onboarding_input_id: OnboardingInputId,
        principal: Any,
    ) -> None:
        """Invoke start_recon with per-iteration operation ids until both lanes are
        terminal or the fast lane fails (never auto-retry a failed lane — retry is a
        human decision that mints a new attempt)."""
        digest = _website_digest(scope.company_website)
        body: dict[str, Any] = {
            "brand_id": scope.brand_id,
            "name": scope.workspace_name,
            "website": scope.company_website,
            "onboarding_input_ids": [str(onboarding_input_id)],
        }
        if workspace_id in driving_workspaces:
            return
        driving_workspaces.add(workspace_id)
        try:
            for iteration in range(_MAX_DRIVER_INVOCATIONS):
                operation_id = _iteration_operation_id(workspace_id, digest, attempt, iteration)
                if principal is not None:
                    ctx = tool_context_for_principal(
                        principal, conn_factory=conn_factory, operation_id=operation_id
                    )
                else:
                    ctx = ToolContext(
                        workspace_id=workspace_id,
                        actor="human",
                        conn_factory=conn_factory,
                        operation_id=operation_id,
                    )
                try:
                    result = await tool_invoker.invoke("start_recon", body, ctx)
                except PreconditionFailed as error:
                    # Refused before spend (scrape composition absent — impossible in a
                    # correctly built process since the binder rides the same flag as
                    # these routes; loud for hand-rolled compositions).
                    log.error(
                        "stage0_setup.recon_refused",
                        workspace_id=workspace_id,
                        reason_codes=list(error.reason_codes),
                    )
                    return
                except Exception:  # noqa: BLE001 — one iteration must not kill the driver
                    # Most likely a journal-attempt race with a concurrent driver; the
                    # survivor keeps driving. Continue: the next iteration has its own id.
                    log.exception(
                        "stage0_setup.recon_iteration_failed",
                        workspace_id=workspace_id,
                        iteration=iteration,
                    )
                    continue
                references = dict(result.references)
                fast = str(references.get("fast_status", ""))
                background = str(references.get("background_status", ""))
                log.info(
                    "stage0_setup.recon_lane_driven",
                    workspace_id=workspace_id,
                    recon_run_id=str(references.get("recon_run_id", "")),
                    fast_status=fast,
                    background_status=background,
                    attempt=attempt,
                    iteration=iteration,
                    replayed=result.replayed,
                )
                if fast == "failed":
                    return
                if fast in _TERMINAL_LANE_STATUSES and background in _TERMINAL_LANE_STATUSES:
                    return
        finally:
            driving_workspaces.discard(workspace_id)

    @router.post("/stage0/setup", response_model=SetupStartResponse, status_code=202)
    async def start_setup(request: Request, workspace_id: WorkspaceDep) -> SetupStartResponse:
        principal = principal_from_request(request)
        if principal is not None:
            # Recon is SPEND: same authority bar as the launch-tool family (review BE-M3).
            principal.require("research.launch")
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
        attempt = await _failed_attempt_count(workspace_id, _dedupe(workspace_id, scope))
        onboarding_input_id = _attempt_input_id(workspace_id, digest, attempt)
        # Capture-before-use: bytes first, capture record second, spend last. The captured
        # bytes ARE the digest's pre-image, so identity and content cannot disagree.
        captured = scope.company_website.strip().encode("utf-8")
        ref = await artifacts.persist_body(
            workspace_id=workspace_id,
            data=captured,
            media_type="text/plain",
        )
        try:
            async with conn_factory() as conn:
                await submit_onboarding_input(
                    conn,
                    workspace_id=workspace_id,
                    brand_id=scope.brand_id,
                    kind=OnboardingInputKind.WEBSITE,
                    artifact_key=ref.artifact_key,
                    content_sha256=ref.sha256,
                    actor="human",
                    # No source_ref copy of the URL: append-only rows cannot be redacted
                    # on DSAR erasure (module docstring).
                    source_ref=None,
                    onboarding_input_id=onboarding_input_id,
                )
        except ValueError as error:
            # The capture replay drift guard must surface as a typed conflict, never a 500.
            raise HTTPException(
                status_code=409,
                detail={"error": "setup_capture_conflict", "reason": str(error)},
            ) from error
        # !! THE RECON LANE RUNS ON THIS WEB PROCESS'S OWN EVENT LOOP, AND IT BLOCKS IT. !!
        #
        # `_drive_recon` awaits `start_recon`, whose waterfall calls `resolver.resolve`
        # SYNCHRONOUSLY, and the slice-3 claim extractor's `LLMGateway.complete` is a sync,
        # network-bound call. Nothing yields to the loop for its duration, so **every other
        # request served by this process — including this screen's own 1.5s setup polls — waits**.
        # The multiplier is one completion per Client-KB field: the eleven-field fast walk is
        # eleven serialized blocking calls, and the background lane walks them again.
        #
        # Tolerable today only because the extractor's gate is closed by default: it needs both
        # `CLUE_SELF_SERVE_PROVISIONING_ENABLED` (these routes) and a real `OPENROUTER_API_KEY`
        # (without one the HTTP root composes the empty extractor and no completion happens at
        # all). **This must be fixed before that pair is true in a shared web process** — either
        # drive recon on the fleet (the binder is already composed there) or put an
        # `asyncio.to_thread` hop at the waterfall's resolver call. Recorded with an owner in the
        # repo-root CLAUDE.md backlog, tag `[slice3×stage0]`.
        task = asyncio.create_task(
            _drive_recon(
                workspace_id=workspace_id,
                scope=scope,
                attempt=attempt,
                onboarding_input_id=onboarding_input_id,
                principal=principal,
            )
        )
        driver_tasks.add(task)
        task.add_done_callback(driver_tasks.discard)
        return SetupStartResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, status="started")

    async def _field_truth(
        workspace_id: str, recon_run_id: UUID
    ) -> tuple[list[SetupFieldState], dict[str, bool]]:
        """Reduce the recon run's progress events into per-field state + per-lane budget truth.

        The events are an at-least-once outbox, so both reductions are last-writer-wins by
        ``seq``: a field's terminal status supersedes its ``started``, and the newest COMPLETED
        transition per lane carries that lane's budget verdict. A lane's own field row wins over
        an earlier lane's for the same field — the background lane re-derives what the capped
        fast lane reached, and the later answer is the truer one.

        One page suffices by construction: a recon run emits at most two field events per
        baseline field per lane plus four transitions (~40), an order of magnitude under
        ``list_run_events``' 1000-row page."""
        async with conn_factory() as conn:
            events = await list_run_events(
                conn,
                workspace_id=workspace_id,
                run_id=ProjectRunId(recon_run_id),
            )
        latest_field: dict[str, tuple[int, str, str]] = {}
        latest_budget: dict[str, tuple[int, bool]] = {}
        for event in events:
            payload = event.payload
            kind = payload.get("kind")
            if kind == RECON_FIELD_PROGRESS_KIND:
                field_key = str(payload.get("field_key", ""))
                seen = latest_field.get(field_key)
                if field_key and (seen is None or seen[0] < event.seq):
                    latest_field[field_key] = (
                        event.seq,
                        str(payload.get("lane", "")),
                        str(payload.get("status", "")),
                    )
            # The emitter writes ``status.value`` of the same enum, so read the enum rather than
            # a literal that could drift away from it silently.
            elif kind == RECON_TRANSITION_KIND and (
                payload.get("status") == ReconLaneStatus.COMPLETED.value
            ):
                exhausted = payload.get("budget_exhausted")
                lane = str(payload.get("lane", ""))
                held = latest_budget.get(lane)
                # Both reductions compare on seq rather than trusting arrival order, so
                # neither depends on how `list_run_events` happens to sort its page.
                if isinstance(exhausted, bool) and (held is None or held[0] < event.seq):
                    latest_budget[lane] = (event.seq, exhausted)
        budgets = {lane: value for lane, (_, value) in latest_budget.items()}
        order = {key: index for index, key in enumerate(CLIENT_BASELINE_FIELDS)}
        fields = [
            SetupFieldState(field_key=field_key, lane=lane, status=status)
            for field_key, (_, lane, status) in sorted(
                latest_field.items(),
                # Baseline order is the order the screen shows them in; anything outside the
                # baseline (a future pack field) sorts after it, alphabetically.
                key=lambda item: (order.get(item[0], len(order)), item[0]),
            )
        ]
        return fields, budgets

    async def _serve_lane_truth(
        workspace_id: str, scope: _ProvisioningScope, recon_run_id: Any
    ) -> SetupStatusResponse | None:
        view = await stage0_progress(
            recon_run_id=ReconRunId(recon_run_id),
            workspace_id=workspace_id,
            conn_factory=conn_factory,
        )
        if view is None:
            return None
        if view.fast_status == "failed":
            status: Literal["running", "complete", "failed"] = "failed"
        elif view.fast_status == "completed":
            status = "complete"
        else:
            status = "running"
        fact_count: int | None = None
        if view.fast_client_kb_version is not None:
            brief = await recon_brief(
                recon_run_id=ReconRunId(recon_run_id),
                workspace_id=workspace_id,
                conn_factory=conn_factory,
            )
            if brief is not None:
                fact_count = len(brief.facts)
        fields, budgets = await _field_truth(workspace_id, UUID(view.recon_run_id))
        return SetupStatusResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION,
            status=status,
            recon_run_id=str(view.recon_run_id),
            fast_status=view.fast_status,
            background_status=view.background_status,
            company_website=scope.company_website,
            fast_client_kb_version=view.fast_client_kb_version,
            fact_count=fact_count,
            fields=fields,
            fast_budget_exhausted=budgets.get("fast"),
            background_budget_exhausted=budgets.get("background"),
        )

    @router.get("/stage0/setup/current", response_model=SetupStatusResponse)
    async def current_setup(workspace_id: WorkspaceDep) -> SetupStatusResponse:
        scope = await _provisioning_scope(workspace_id)
        if scope is None:
            return SetupStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION, status="unavailable"
            )
        digest = _website_digest(scope.company_website)
        dedupe = _dedupe(workspace_id, scope)
        attempt = await _failed_attempt_count(workspace_id, dedupe)
        # 1) The current attempt's own run (its id is iteration 0's operation id).
        candidate_id = _iteration_operation_id(workspace_id, digest, attempt, 0)
        served = await _serve_lane_truth(workspace_id, scope, candidate_id)
        if served is not None:
            return served
        # 2) The current attempt is captured but its run is not yet visible (driver warm-up
        #    or the fast lane's single enclosing transaction): honest "starting".
        async with conn_factory() as conn:
            captured = (
                await conn.execute(
                    text("SELECT 1 FROM onboarding_input WHERE id = :id"),
                    {"id": _attempt_input_id(workspace_id, digest, attempt)},
                )
            ).scalar_one_or_none()
            # 3) Any other run for this identity (a prior attempt's failure awaiting a
            #    retry decision, a dedupe-shared run started elsewhere, or a pre-wave row).
            latest_id = (
                None
                if captured is not None
                else (
                    await conn.execute(
                        text(
                            "SELECT id FROM recon_run "
                            "WHERE workspace_id = :workspace_id AND dedupe_hash = :dedupe_hash "
                            "ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"workspace_id": workspace_id, "dedupe_hash": dedupe},
                    )
                ).scalar_one_or_none()
            )
        # The reads below take their own connection, so they must run outside the block above:
        # a single-connection factory would otherwise wait on a connection it already holds.
        if captured is not None:
            # "starting" is where the fast lane spends its whole life (its recon_run row is
            # invisible until that one transaction commits), so the per-field events —
            # committed autonomously under the same candidate id — are the only motion there
            # is to show for it.
            fields, budgets = await _field_truth(workspace_id, UUID(str(candidate_id)))
            return SetupStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION,
                status="starting",
                company_website=scope.company_website,
                fields=fields,
                fast_budget_exhausted=budgets.get("fast"),
                background_budget_exhausted=budgets.get("background"),
            )
        if latest_id is not None:
            served = await _serve_lane_truth(workspace_id, scope, latest_id)
            if served is not None:
                return served
        return SetupStatusResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION,
            status="none",
            company_website=scope.company_website,
        )

    return router


__all__ = ["create_stage0_setup_router", "setup_workspace_resolver"]
