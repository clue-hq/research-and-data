"""``POST /onboarding`` and ``GET /onboarding/current`` (ARV2-ONBOARDING-PLAN.md §3, §7; O3).

The route inserts the run row and enqueues the fleet job — nothing else runs on the web loop.
Every provider call, every document and every dollar belongs to the ``onboarding_run`` handler on
the detached fleet; this surface only records the intent and hands it over.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from clue_api.arv2.onboarding_driver import (
    ONBOARDING_DEDUP_PREFIX,
    IcpRef,
    onboarding_work_id,
)
from clue_api.arv2.onboarding_store import read_current_run
from clue_api.auth_wiring import principal_from_request
from clue_api.brand_kit_ingestion import BrandKitIngestionTrigger, read_newest_ingestion_job
from clue_api.workspace_ops.onboarding_plan import brand_kit_gaps, research_gaps
from clue_api.workspace_ops.onboarding_start import Preflight, normalize_domain, start_onboarding
from clue_api.workspace_ops.operators import OpsRefused
from clue_db import ConnFactory
from clue_fleet import FleetTaskKind
from clue_fleet.queue import DbWorkQueue, WorkQueue
from clue_obs import get_logger
from clue_projections import PROJECTIONS_SCHEMA_VERSION

__all__ = [
    "DbOnboardingEnqueuer",
    "OnboardingBrandKitIngestionView",
    "OnboardingEnqueuer",
    "create_onboarding_router",
    "onboarding_workspace_resolver",
]

log = get_logger("clue_api.onboarding_routes")

#: Ahead of Stage-0 recon (-200) is deliberate: an onboarding run is one human waiting on their
#: first knowledge base, so it claims before the ordinary background work but never ahead of the
#: provisioning lane that has to finish before this one can even be started.
ONBOARDING_TASK_PRIORITY = -150


def onboarding_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    """This surface's tenant seam; production overrides it with the authenticated resolver."""
    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


# Module-level alias: FastAPI resolves stringified annotations against module globals — a
# closure-local alias would be mistaken for a query parameter (the stage0_setup idiom).
WorkspaceDep = Annotated[str, Depends(onboarding_workspace_resolver)]


class OnboardingEnqueuer(Protocol):
    """Offering a run to the fleet — the one thing the route asks of the work plane.

    Only the whole-brand walk is the *route's* to offer; the personas run is offered by the tool
    that requests it (:mod:`clue_api.persona_request_tools`), through the same enqueuer.
    """

    async def enqueue(
        self,
        *,
        run_id: UUID,
        workspace_id: str,
        brand_id: str,
        company_domain: str,
        company_name: str,
    ) -> bool: ...


class DbOnboardingEnqueuer:
    """The production enqueuer: one ``onboarding_run`` task per run, idempotent on the run id.

    ``reopen_terminal=False`` on purpose — the run id is minted fresh per request, so there is no
    terminal row to revive, and refusing to reopen one means a replayed request can never restart
    a run that already finished (and already spent).
    """

    def __init__(self, queue: WorkQueue | None = None) -> None:
        self._queue = queue if queue is not None else DbWorkQueue()

    async def enqueue(
        self,
        *,
        run_id: UUID,
        workspace_id: str,
        brand_id: str,
        company_domain: str,
        company_name: str,
    ) -> bool:
        return await self._queue.enqueue(
            kind=FleetTaskKind.ONBOARDING_RUN,
            work_id=onboarding_work_id(run_id),
            dedup_key=f"{ONBOARDING_DEDUP_PREFIX}{run_id}",
            priority=ONBOARDING_TASK_PRIORITY,
            payload={
                "run_id": str(run_id),
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "company_domain": company_domain,
                "company_name": company_name,
            },
            reopen_terminal=False,
        )

    async def enqueue_customers(
        self,
        *,
        run_id: UUID,
        workspace_id: str,
        brand_id: str,
        company_domain: str,
        company_name: str,
    ) -> bool:
        """Offer the narrow customers run (spec 2026-10-16 §4.4): the same task kind, priority and
        dedup shape as :meth:`enqueue`; the payload's ``kind`` tells the handler which run."""
        return await self._queue.enqueue(
            kind=FleetTaskKind.ONBOARDING_RUN,
            work_id=onboarding_work_id(run_id),
            dedup_key=f"{ONBOARDING_DEDUP_PREFIX}{run_id}",
            priority=ONBOARDING_TASK_PRIORITY,
            payload={
                "run_id": str(run_id),
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "company_domain": company_domain,
                "company_name": company_name,
                "kind": "customers",
            },
            reopen_terminal=False,
        )

    async def enqueue_personas(
        self,
        *,
        run_id: UUID,
        workspace_id: str,
        brand_id: str,
        project_id: str,
        company_domain: str,
        company_name: str,
        icp: IcpRef,
    ) -> bool:
        """Offer the narrow personas run: the same task kind, priority and dedup shape.

        One kind of fleet task drives both runs, because both are "the onboarding lane doing
        something for this brand" and the handler that drives them is one handler — the payload's
        ``kind`` is what tells it which. The ICP rides the payload whole (its id, key, version,
        path and **scope**) because the run's subject is that exact document version, and a worker
        must not re-resolve "the project's current ICP" and quietly write personas for a profile
        the human never asked about.

        ``project_id`` is carried for the record rather than for the driver: the run row already
        names the asking project, and this makes the task itself readable without joining to it.
        """
        return await self._queue.enqueue(
            kind=FleetTaskKind.ONBOARDING_RUN,
            work_id=onboarding_work_id(run_id),
            dedup_key=f"{ONBOARDING_DEDUP_PREFIX}{run_id}",
            priority=ONBOARDING_TASK_PRIORITY,
            payload={
                "run_id": str(run_id),
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "project_id": project_id,
                "company_domain": company_domain,
                "company_name": company_name,
                "kind": "personas",
                "icp": {
                    "document_id": str(icp.document_id),
                    "icp_key": icp.icp_key,
                    "version": icp.version,
                    "path": icp.path,
                    "project_id": icp.project_id,
                },
            },
            reopen_terminal=False,
        )


class OnboardingStartRequest(BaseModel):
    company_domain: str = Field(min_length=1, max_length=253)
    company_name: str | None = Field(default=None, max_length=200)
    brand_id: str | None = None


class OnboardingStartResponse(BaseModel):
    schema_version: str
    run_id: str
    status: Literal["queued"]


class OnboardingStepView(BaseModel):
    """One step of the run. camelCase because §7 froze this wire shape for the poller."""

    kind: str
    subjectRef: str | None
    phase: str
    status: str
    startedAt: str | None
    finishedAt: str | None
    costUsd: str
    failureCode: str | None


class OnboardingBrandKitIngestionView(BaseModel):
    """The workspace's newest design brand-kit ingestion job — job truth, nothing derived.

    ``POST /onboarding`` fires that ingestion (``brand_kit_ingestion.ensure``), so the setting-up
    checklist has a "Creating brand kit" row to move; this is the read that moves it. ``status``
    is the ``design_ingestion_status`` enum as stored (``queued|running|succeeded|failed``),
    served as-is — the row's three-state mapping is the client's (the same division of labour as
    ``GET /stage0/setup/current``, which serves the identical shape).
    """

    jobId: str
    status: str


class OnboardingGapView(BaseModel):
    """One thing onboarding finished without (spec 2026-10-25 §5.2): a failed research or ICP
    step (its newest attempt, repairs included) or a brand-kit job's own gap. Additive; the
    setting-up screen ignores it until a screen is designed for it."""

    area: Literal["research", "brand_kit"]
    item: str
    code: str | None
    message: str | None


class OnboardingStatusResponse(BaseModel):
    """The §7 status read. ``status`` is ``"none"`` before the workspace has ever run one, so the
    poller can start before the first POST and never has to read a 404 as "not yet".

    ``brandKitIngestion`` is additive (§7 stays the frozen core): the workspace's newest design
    ingestion job, or ``None`` when it has none — never a fabricated "queued" the checklist would
    spin on forever. Served in EVERY branch, so a client never has to ask why the key vanished.
    """

    schema_version: str
    runId: str | None
    status: str
    steps: list[OnboardingStepView]
    costUsd: str
    brandKitIngestion: OnboardingBrandKitIngestionView | None = None
    gaps: list[OnboardingGapView] = Field(default_factory=list)


def create_onboarding_router(
    *,
    conn_factory: ConnFactory,
    enqueuer: OnboardingEnqueuer,
    brand_kit_ingestion: BrandKitIngestionTrigger | None = None,
    preflight: Preflight | None = None,
) -> APIRouter:
    """``preflight`` (spec 2026-10-25 §3.3, ruling D8) guards every start, the setting-up
    screen's included: a dead provider refuses with 503 ``providers_unavailable`` before any run
    exists. ``None`` (offline tests) starts without checking."""
    router = APIRouter(tags=["onboarding"])

    def _user_id(request: Request) -> str:
        """The human the run is charged to — ``onboarding_run.requested_by_user_id`` is a FK.

        The ``X-Test-User-Id`` header stands in only when no authenticated principal is present:
        the same fail-open-to-header seam the Stage-0 router uses for its workspace. Production
        always carries ``request.state.clue_principal``, so the header is never consulted there.
        """
        principal = principal_from_request(request)
        if principal is not None:
            # Onboarding is SPEND: the same authority bar as the launch-tool family.
            principal.require("research.launch")
            return principal.user_id
        header = request.headers.get("X-Test-User-Id")
        if not header:
            raise HTTPException(status_code=401, detail="no principal")
        return header

    @router.post("/onboarding", response_model=OnboardingStartResponse, status_code=202)
    async def start_onboarding_route(
        request: Request, body: OnboardingStartRequest, workspace_id: WorkspaceDep
    ) -> OnboardingStartResponse:
        if not normalize_domain(body.company_domain):
            raise HTTPException(status_code=422, detail="company_domain is blank")
        user_id = _user_id(request)
        try:
            run_id = await start_onboarding(
                conn_factory,
                workspace_id=workspace_id,
                domain=body.company_domain,
                brand_id=body.brand_id,
                company_name=body.company_name,
                requested_by_user_id=user_id,
                enqueuer=enqueuer,
                brand_kit_ingestion=brand_kit_ingestion,
                preflight=preflight,
            )
        except OpsRefused as refused:
            raise HTTPException(
                status_code=refused.status,
                detail={"error": refused.code, "reason": refused.message, **refused.detail},
            ) from refused
        return OnboardingStartResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION, run_id=str(run_id), status="queued"
        )

    @router.get("/onboarding/current", response_model=OnboardingStatusResponse)
    async def current_onboarding(workspace_id: WorkspaceDep) -> OnboardingStatusResponse:
        async with conn_factory() as conn:
            status = await read_current_run(conn, workspace_id=workspace_id)
            gaps = [
                OnboardingGapView(**gap)
                for gap in [
                    *await research_gaps(conn, workspace_id=workspace_id),
                    *await brand_kit_gaps(conn, workspace_id=workspace_id),
                ]
            ]
        # The same read the Stage-0 setup route serves, through the shared helper: the brand-kit
        # ingestion is separate work from the run, so it is read separately and never gated on
        # one existing.
        job = await read_newest_ingestion_job(conn_factory, workspace_id=workspace_id)
        brand_kit = (
            None if job is None else OnboardingBrandKitIngestionView(jobId=job[0], status=job[1])
        )
        # "Nothing yet" is a status, never a 404 — the poll starts before the first run exists.
        if status is None:
            return OnboardingStatusResponse(
                schema_version=PROJECTIONS_SCHEMA_VERSION,
                runId=None,
                status="none",
                steps=[],
                costUsd="0",
                brandKitIngestion=brand_kit,
                gaps=gaps,
            )
        return OnboardingStatusResponse(
            schema_version=PROJECTIONS_SCHEMA_VERSION,
            runId=str(status.run_id),
            status=status.status,
            steps=[
                OnboardingStepView(
                    kind=step.kind,
                    subjectRef=step.subject_ref,
                    phase=step.phase,
                    status=step.status,
                    startedAt=step.started_at.isoformat() if step.started_at else None,
                    finishedAt=step.finished_at.isoformat() if step.finished_at else None,
                    costUsd=str(step.cost_usd),
                    failureCode=step.failure_code,
                )
                for step in status.steps
            ],
            costUsd=str(status.cost_usd),
            brandKitIngestion=brand_kit,
            gaps=gaps,
        )

    return router
