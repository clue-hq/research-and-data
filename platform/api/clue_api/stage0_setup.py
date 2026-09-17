"""FI-4 slice 2 — the workspace-setup composition over Stage-0 recon (ratified D-4).

One narrow, flag-gated surface for the onboarding "setting up your workspace" screen:

``POST /stage0/setup``
    Requires ``research.launch`` on the authenticated path (recon is SPEND; a viewer must
    not be able to trigger it). Captures the provisioned company website as a real B2
    artifact (capture-before-use), records the durable ``onboarding_input`` (kind
    ``website``, actor ``human``), and fires the recon driver. Returns 202; truth lives in
    durable rows. Brand-kit slice 2 hangs one more thing off the same captured website: a
    single, idempotent, fail-soft brand-kit website ingestion for the workspace
    (:mod:`clue_api.brand_kit_ingestion`) — first-time-only by construction, because only the
    self-serve provisioning scope reaches this route.

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
    the explicit onboarding-checklist order), and
    ``{fast,background}_budget_exhausted`` say whether a lane "completed" by finishing or by
    hitting its cap — ``None`` until that lane's
    terminal event exists, never a guessed ``False``. Brand-kit slice 3 adds
    ``brand_kit_ingestion``: the workspace's newest design ingestion job (``{job_id, status}``,
    or ``None`` when it has none), read through the ``clue_design`` DAL port and served raw —
    the onboarding checklist maps it onto its own row vocabulary, so no derivation happens here.

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
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_tool_context import tool_context_for_principal
from clue_api.auth_wiring import principal_from_request
from clue_api.brand_kit_ingestion import BrandKitIngestionTrigger, read_newest_ingestion_job
from clue_api.stage0_setup_fleet import (
    ProvisioningScope,
    Stage0ReconEnqueuer,
    attempt_input_id,
    iteration_operation_id,
    website_digest,
)
from clue_core import (
    RECON_FIELD_PROGRESS_KIND,
    RECON_TRANSITION_KIND,
    OnboardingInputId,
    OnboardingInputKind,
    ProjectRunId,
    ReconRunId,
)
from clue_db import ConnFactory
from clue_execution.run_events import list_run_events
from clue_obs import get_logger
from clue_projections import PROJECTIONS_SCHEMA_VERSION, recon_brief, stage0_progress
from clue_research.official_site import (
    OfficialSiteProgressView,
    PostgresOfficialSiteOperations,
)
from clue_research.stage0 import (
    CLIENT_ONBOARDING_FIELDS,
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


class SetupOfficialSiteProgress(BaseModel):
    """Additive C8 row/event truth; intentionally excludes URLs, bodies, and receipts."""

    schema_version: str
    crawl_run_id: str
    run_status: str
    phase: str | None = None
    message: str
    states: list[str]
    queued: int
    leased: int
    provider_active: int
    reconciliation_pending: int
    persistence_pending: int
    fetched: int
    total_pages: int
    snapshots: int
    fetch_spend_unknown: int
    extraction_active: int
    extraction_materialized: int
    extraction_empty: int
    extraction_failed: int
    extraction_spend_unknown: int
    recovery_required: bool
    partial: bool
    completed: bool
    last_event_seq: int | None = None
    last_event_kind: str | None = None


class SetupBrandKitIngestion(BaseModel):
    """The workspace's newest design brand-kit ingestion job — job truth, nothing derived.

    Deliberately two fields: the onboarding checklist's "Creating brand kit" row maps this onto
    its three-state vocabulary on the client (brand-kit slice 3), and a server-side row status
    would put presentation policy in the backend. ``status`` is the ``design_ingestion_status``
    enum as stored (``queued|running|succeeded|failed``), served as-is.
    """

    job_id: str
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
    # FI-4 slice 3: real per-field motion for the eleven-field onboarding checklist. Company
    # navigation knowledge such as client.product_catalog is intentionally not a checklist row.
    fields: list[SetupFieldState] = []
    # None while a lane has not reached a terminal COMPLETED state (or for a run that
    # predates the flag): "we do not know yet", never a fabricated False.
    fast_budget_exhausted: bool | None = None
    background_budget_exhausted: bool | None = None
    # C8 is nullable/additive: old clients ignore it; no crawl row is honest null.
    official_site: SetupOfficialSiteProgress | None = None
    # Brand-kit slice 3: the workspace's newest brand-kit ingestion job (slice 2 fires exactly one
    # at first-time setup). None = no job row at all — never a fabricated "queued" the checklist
    # would spin on. Served in EVERY branch, so the client never has to ask why the key vanished.
    brand_kit_ingestion: SetupBrandKitIngestion | None = None


def _setup_official_site(
    view: OfficialSiteProgressView | None,
) -> SetupOfficialSiteProgress | None:
    if view is None:
        return None
    return SetupOfficialSiteProgress(
        schema_version=view.schema_version,
        crawl_run_id=str(view.crawl_run_id),
        run_status=view.run_status.value,
        phase=view.phase.value if view.phase is not None else None,
        message=view.message,
        states=[state.value for state in view.states],
        queued=view.queued + view.retry_wait,
        leased=view.leased,
        provider_active=view.provider_active,
        reconciliation_pending=view.reconciliation_pending,
        persistence_pending=view.persistence_pending,
        fetched=view.fetched,
        total_pages=view.total_pages,
        snapshots=view.snapshots,
        fetch_spend_unknown=view.fetch_spend_unknown,
        extraction_active=view.extraction_active + view.extraction_prepared,
        extraction_materialized=view.extraction_materialized,
        extraction_empty=view.extraction_empty,
        extraction_failed=view.extraction_failed,
        extraction_spend_unknown=view.extraction_spend_unknown,
        recovery_required=view.recovery_required,
        partial=view.partial,
        completed=view.completed,
        last_event_seq=view.last_event_seq,
        last_event_kind=(view.last_event_kind.value if view.last_event_kind is not None else None),
    )


def create_stage0_setup_router(
    *,
    tool_invoker: ToolInvoker,
    conn_factory: ConnFactory,
    storage: StorageBackend,
    recon_enqueuer: Stage0ReconEnqueuer | None = None,
    brand_kit_ingestion: BrandKitIngestionTrigger | None = None,
) -> APIRouter:
    router = APIRouter(tags=["stage0-setup"])
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    official_site_operations = PostgresOfficialSiteOperations(conn_factory=conn_factory)
    driver_tasks: set[asyncio.Task[None]] = set()
    # Best-effort same-process duplicate-driver suppression; the durable model (per-attempt
    # deterministic ids + the tool's advisory locks) is the real safety net across processes.
    driving_workspaces: set[str] = set()

    async def _provisioning_scope(workspace_id: str) -> ProvisioningScope | None:
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
        return ProvisioningScope(
            brand_id=row["brand_id"],
            company_website=row["company_website"],
            workspace_name=row["workspace_name"],
        )

    def _dedupe(workspace_id: str, scope: ProvisioningScope) -> str:
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

    async def _drive_recon(
        *,
        workspace_id: str,
        scope: ProvisioningScope,
        attempt: int,
        onboarding_input_id: OnboardingInputId,
        principal: Any,
    ) -> None:
        """Invoke start_recon with per-iteration operation ids until both lanes are
        terminal or the fast lane fails (never auto-retry a failed lane — retry is a
        human decision that mints a new attempt)."""
        digest = website_digest(scope.company_website)
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
                operation_id = iteration_operation_id(workspace_id, digest, attempt, iteration)
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
        digest = website_digest(scope.company_website)
        attempt = await _failed_attempt_count(workspace_id, _dedupe(workspace_id, scope))
        onboarding_input_id = attempt_input_id(workspace_id, digest, attempt)
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
        if recon_enqueuer is not None:
            # Production C6 path: return after the durable enqueue. The fleet rehydrates every
            # input and owns all network/model work; no browser credential enters the queue.
            await recon_enqueuer.enqueue(
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
                website_digest=digest,
                attempt=attempt,
            )
        else:
            # Focused router tests may still inject the pre-C6 in-process driver. The production
            # application always supplies ``DbStage0ReconEnqueuer`` (guarded by composition tests).
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
        if brand_kit_ingestion is not None:
            # Brand-kit slice 2: the captured website also seeds the client's DRAFT brand kit,
            # once, for the whole workspace. First-time-only is structural rather than flagged —
            # this line is only reachable through the self-serve provisioning scope resolved
            # above, so a workspace born any other way never gets an auto-fired ingestion.
            #
            # It runs AFTER the recon dispatch, not before: recon is the onboarding screen's
            # actual work, and a slow or unreachable design API must not delay it by even the
            # enqueue's timeout. ``ensure`` never raises (fail-soft), so nothing below the
            # capture step can be broken by the design service being down — the next setup
            # replay re-attempts while no job row exists.
            await brand_kit_ingestion.ensure(
                workspace_id=workspace_id, website=scope.company_website
            )
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
        onboarding field per lane plus four transitions (~50), an order of magnitude under
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
                if field_key not in CLIENT_ONBOARDING_FIELDS:
                    continue
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
        order = {key: index for index, key in enumerate(CLIENT_ONBOARDING_FIELDS)}
        fields = [
            SetupFieldState(field_key=field_key, lane=lane, status=status)
            for field_key, (_, lane, status) in sorted(
                latest_field.items(),
                key=lambda item: order[item[0]],
            )
        ]
        return fields, budgets

    async def _brand_kit_job(workspace_id: str) -> SetupBrandKitIngestion | None:
        """The workspace's newest brand-kit ingestion job, or None when it has none.

        One workspace-keyed read, shared with ``GET /onboarding/current`` through
        :func:`clue_api.brand_kit_ingestion.read_newest_ingestion_job` — both setting-up
        surfaces read the same job the same way, so neither can drift. The setting-up screen
        polls this route ~1.5s, so nothing is derived here and nothing joins: the design tables
        are read exactly once per poll, alongside the recon reads.
        """
        job = await read_newest_ingestion_job(conn_factory, workspace_id=workspace_id)
        if job is None:
            return None
        job_id, status = job
        return SetupBrandKitIngestion(job_id=job_id, status=status)

    async def _serve_lane_truth(
        workspace_id: str,
        scope: ProvisioningScope,
        recon_run_id: Any,
        brand_kit: SetupBrandKitIngestion | None,
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
        official_site = await official_site_operations.read_progress_for_recon(
            workspace_id=workspace_id,
            recon_run_id=UUID(view.recon_run_id),
        )
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
            official_site=_setup_official_site(official_site),
            brand_kit_ingestion=brand_kit,
        )

    @router.get("/stage0/setup/current", response_model=SetupStatusResponse)
    async def current_setup(workspace_id: WorkspaceDep) -> SetupStatusResponse:
        # Read once, before the branching: the brand-kit ingestion is workspace-scoped work that
        # is independent of any recon run, so every branch below answers the same question about
        # it — including "unavailable", where a job can exist without a provisioning record.
        brand_kit = await _brand_kit_job(workspace_id)
        scope = await _provisioning_scope(workspace_id)
        if scope is None:
            return SetupStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION,
                status="unavailable",
                brand_kit_ingestion=brand_kit,
            )
        digest = website_digest(scope.company_website)
        dedupe = _dedupe(workspace_id, scope)
        attempt = await _failed_attempt_count(workspace_id, dedupe)
        # 1) The current attempt's own run (its id is iteration 0's operation id).
        candidate_id = iteration_operation_id(workspace_id, digest, attempt, 0)
        served = await _serve_lane_truth(workspace_id, scope, candidate_id, brand_kit)
        if served is not None:
            return served
        # 2) The current attempt is captured but its run is not yet visible (driver warm-up
        #    or the fast lane's single enclosing transaction): honest "starting".
        async with conn_factory() as conn:
            captured = (
                await conn.execute(
                    text("SELECT 1 FROM onboarding_input WHERE id = :id"),
                    {"id": attempt_input_id(workspace_id, digest, attempt)},
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
                brand_kit_ingestion=brand_kit,
            )
        if latest_id is not None:
            served = await _serve_lane_truth(workspace_id, scope, latest_id, brand_kit)
            if served is not None:
                return served
        return SetupStatusResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION,
            status="none",
            company_website=scope.company_website,
            brand_kit_ingestion=brand_kit,
        )

    return router


__all__ = ["create_stage0_setup_router", "setup_workspace_resolver"]
