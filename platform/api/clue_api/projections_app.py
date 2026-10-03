"""The B4 read-side HTTP surface (PB-B4 slice 3) — projections, the tool route, manifest ops, SSE.

The composition-root FastAPI app that serves the ``clue_projections`` read views, the single typed
**write path** (the slice-2 toolbelt over ``POST /tools/{name}`` with A9 idempotency at the HTTP
edge), the manifest **ops** (pause/adjust mapped to the run machine — everything else refused 422),
and the treaty **SSE** stream (``Last-Event-ID`` replay, ``stream.hello`` / ``stream.reset``,
single-use stream tokens). Built in the ``handoff_app`` style: thin routes over injected
collaborators, a workspace/actor auth seam swapped via ``dependency_overrides``, schema-versioned
DTOs.

Everything the surface *reads* comes from ``clue_projections`` (pure, MVCC-only); everything it
*writes* — tool invocations (the toolbelt runner), the ``run_event`` outbox (via the drive path, not
here), the single-use ``stream_token`` — is composition-root machinery. The auth seam is the same
``X-Workspace-Id`` tenant header as the handoff API (production swaps real service-auth of the same
shape); the actor (``X-Actor``: human|agent, REQ-20) is stamped on every tool invocation span.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

import clue_obs
from clue_agents import AgentProfileRegistry
from clue_api.auth_tool_context import tool_context_for_principal
from clue_api.auth_wiring import (
    REQUEST_ID_HEADER,
    authenticated_route_resolvers,
    install_auth_wiring,
    principal_from_request,
    request_id_for,
)
from clue_api.brand_kit_ingestion import build_brand_kit_ingestion_trigger
from clue_api.chat import PrincipalResolver, chat_workspace_resolver, install_chat_surface
from clue_api.chat.stream import install_chat_stream_surface
from clue_api.frontend_read import (
    frontend_read_workspace_resolver,
    install_frontend_read_surface,
)
from clue_api.ingestion_tools import (
    build_ingestion_router,
)
from clue_api.ingestion_tools import (
    header_actor_resolver as ingestion_header_actor_resolver,
)
from clue_api.ingestion_tools import (
    header_workspace_resolver as ingestion_header_workspace_resolver,
)
from clue_api.onboarding_routes import (
    DbOnboardingEnqueuer,
    create_onboarding_router,
    onboarding_workspace_resolver,
)
from clue_api.production_metrics import production_metrics_lifespan
from clue_api.production_tracing import production_tracing_lifespan
from clue_api.research_view_api import (
    build_research_view_router,
    research_actor_resolver,
    research_workspace_resolver,
)
from clue_api.research_view_owner_refs import ProductionOwnerReferenceResolver
from clue_api.stage0_setup import create_stage0_setup_router, setup_workspace_resolver
from clue_api.stage0_setup_fleet import DbStage0ReconEnqueuer, Stage0ReconEnqueuer
from clue_api.stream_tokens import consume_stream_token, mint_stream_token
from clue_api.transactional_account_launch import TransactionalToolInvokerFactory
from clue_auth import MembershipStateChanged, PrincipalService
from clue_config import Secrets, Settings, load_settings
from clue_core import (
    EntityId,
    EvidenceAccessService,
    ProjectRunId,
    ReadinessDecisionId,
    ReconRunId,
    ResearchViewComposer,
    RunId,
    new_operation_id,
    operation_id_from_key,
)
from clue_core.ingestion import IngestionJobId
from clue_core.proposals import ProposalStatus
from clue_db import ConnFactory, db_lifespan, transaction
from clue_execution import DbRunEventReader, OperationConflict, ToolAuthorityStateChanged
from clue_execution.run_events import list_run_events
from clue_fleet import DbWorkQueue
from clue_obs import bound_context
from clue_obs.otel import TracingRuntime, bind_and_annotate
from clue_projections import (
    DEFAULT_TURN_PAGE_SIZE,
    MANIFEST_OP_TOOLS,
    MAX_TURN_PAGE_SIZE,
    PROJECTIONS_SCHEMA_VERSION,
    CostFilters,
    InvalidCursorError,
    account_progress,
    agent_progress,
    agent_route,
    agent_telemetry,
    agent_turn,
    agent_turns_for_project,
    cost_report,
    field_proposals,
    ingestion_status,
    plan_replay,
    recon_brief,
    research_attempt_history,
    research_coverage,
    run_manifest,
    run_overview,
    run_readiness,
    source_proposals,
    stage0_progress,
    stage0_readiness,
    validate_manifest_op,
)
from clue_research.durable.project_run import get_project_run
from clue_research.narrative import ResearchViewSnapshotService
from clue_research.review import ObservabilitySurface
from clue_storage import StorageBackend
from clue_toolbelt import (
    Actor,
    IdempotencyConflict,
    PreconditionFailed,
    ToolContext,
    ToolInvoker,
    ToolResult,
    UnknownTool,
)

if TYPE_CHECKING:  # the refresher's module imports this package's neighbours; type only
    from clue_api.frontend_read.project_memory import MemoryWriteFactory
    from clue_api.project_library_refresh import ProjectLibraryRefresher

# Served on every projection/tool response so a consumer can confirm the shape it negotiated.
PROJECTIONS_SCHEMA_HEADER = "X-Projections-Schema-Version"

WorkspaceResolver = Callable[..., str | Awaitable[str]]
ActorResolver = Callable[..., Actor | Awaitable[Actor]]


def header_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    """The default tenant/auth seam: derive ``workspace_id`` from ``X-Workspace-Id`` (``401`` if
    absent). Production swaps real service-auth of the same ``-> workspace_id`` shape via
    ``dependency_overrides``; the routes never change."""
    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    # Lane 3 slice 2: the header tenant seam. ``bind_and_annotate`` (not a plain bind): the
    # instrumentor's server span opened before any route dependency ran, so the span that is
    # already open needs the workspace written onto it, not just bound for what comes after.
    bind_and_annotate(workspace_id=x_workspace_id)
    return x_workspace_id


def header_actor_resolver(
    x_actor: Annotated[str | None, Header(alias="X-Actor")] = None,
) -> Actor:
    """The actor seam (REQ-20): ``X-Actor`` is ``human`` (default) or ``agent`` — stamped on every
    tool invocation span so a write is attributable and human/agent parity is observable. Any other
    value is a ``422`` (a typo'd actor never silently defaults)."""
    if x_actor is None or x_actor == "human":
        return "human"
    if x_actor == "agent":
        return "agent"
    raise HTTPException(status_code=422, detail="X-Actor must be 'human' or 'agent'")


# Module-level Annotated aliases (FastAPI resolves the stringified annotations against module
# globals — a closure-local alias would be mistaken for a query param; the handoff_app idiom).
WorkspaceDep = Annotated[str, Depends(header_workspace_resolver)]
ActorDep = Annotated[Actor, Depends(header_actor_resolver)]


class ToolInvokeResponse(BaseModel):
    """The ``POST /tools/{name}`` response envelope: the tool's :class:`ToolResult` + the schema
    version. ``replayed`` distinguishes a fresh execution from an idempotent replay (D6)."""

    schema_version: str
    result: ToolResult


class MintTokenResponse(BaseModel):
    """The ``POST …/stream_token`` response — the opaque single-use SSE stream token."""

    schema_version: str
    stream_token: str


class ManifestOpRequest(BaseModel):
    """A ``PATCH …/manifest`` op: ``op`` is one of the accepted manifest ops
    (:data:`~clue_projections.MANIFEST_OP_TOOLS`); ``budget_cap_cents`` is required for ``adjust``.
    Any other ``op`` is refused ``422`` (D7 — ops accepted only where the machine has real
    semantics)."""

    op: str
    budget_cap_cents: int | None = None


def _sse_frame(*, event: str, data: dict[str, Any], seq: int | None = None) -> str:
    """Format one SSE frame: ``id:`` (the seq, for ``Last-Event-ID`` tracking) + ``event:`` (the
    topic) + ``data:`` (compact JSON), terminated by a blank line."""
    lines: list[str] = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'), default=str)}")
    return "\n".join(lines) + "\n\n"


def create_projections_router(
    *,
    surface: ObservabilitySurface,
    tool_invoker: ToolInvoker,
    settings: Settings,
    conn_factory: ConnFactory,
    sse_poll_interval_s: float,
    sse_live_tail: bool,
    agent_registry: AgentProfileRegistry | None = None,
) -> APIRouter:
    """Build the projection + tool + SSE :class:`APIRouter` over the injected collaborators. The
    auth/actor seams are the module-level :data:`WorkspaceDep` / :data:`ActorDep` deps (swapped via
    ``dependency_overrides``)."""
    router = APIRouter()

    # -- read projections (clue_projections; MVCC-only) --

    if agent_registry is not None:

        @router.get("/agent/registry")
        async def get_agent_registry(workspace_id: WorkspaceDep) -> dict[str, Any]:
            del workspace_id  # auth is required even though the active catalog is process-wide.
            return {
                "schema_version": PROJECTIONS_SCHEMA_VERSION,
                "registry": agent_registry.projection().model_dump(mode="json"),
            }

    @router.get("/agent/projects/{project_id}/turns")
    async def get_agent_project_turns(
        project_id: str,
        workspace_id: WorkspaceDep,
        limit: Annotated[int, Query(ge=1, le=MAX_TURN_PAGE_SIZE)] = DEFAULT_TURN_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        # FI-1 defect L6: this listing had no LIMIT/cursor. ``turns`` keeps its element shape; the
        # page now stops, and ``next_cursor`` (``null`` on the last page) carries the keyset.
        try:
            page = await agent_turns_for_project(
                workspace_id=workspace_id,
                project_id=project_id,
                limit=limit,
                cursor=cursor,
                conn_factory=conn_factory,
            )
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "turns": [item.model_dump(mode="json") for item in page.items],
            "next_cursor": page.next_cursor,
        }

    @router.get("/agent/turns/{turn_id}")
    async def get_agent_turn(turn_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await agent_turn(
            workspace_id=workspace_id,
            turn_id=turn_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such agent turn")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "turn": view.model_dump(mode="json"),
        }

    @router.get("/agent/turns/{turn_id}/progress")
    async def get_agent_progress(turn_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await agent_progress(
            workspace_id=workspace_id,
            turn_id=turn_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such agent turn")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "progress": view.model_dump(mode="json"),
        }

    @router.get("/agent/turns/{turn_id}/telemetry")
    async def get_agent_telemetry(turn_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await agent_telemetry(
            workspace_id=workspace_id,
            turn_id=turn_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such agent turn")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "telemetry": view.model_dump(mode="json"),
        }

    @router.get("/agent/routes/{surface_name}/{subject_id}")
    async def get_agent_route(
        surface_name: str,
        subject_id: str,
        workspace_id: WorkspaceDep,
    ) -> dict[str, Any]:
        if surface_name not in {"stage0", "account_research"}:
            raise HTTPException(status_code=422, detail="unknown agent runtime surface")
        view = await agent_route(
            workspace_id=workspace_id,
            surface=surface_name,
            subject_id=subject_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such agent route")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "route": view.model_dump(mode="json"),
        }

    # -- cost (lane 3 slice 1): the two ledgers summed once each, workspace-scoped --

    @router.get("/cost/report")
    async def get_cost_report(
        workspace_id: WorkspaceDep,
        project_id: str | None = None,
        project_run_id: str | None = None,
        job_id: UUID | None = None,
        thread_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        # The filters are built first so a naive ``since``/``until`` is refused (``CostFilters``
        # takes ``AwareDatetime``) before the window comparison — comparing a naive to an aware
        # datetime raises, and a half-aware window must be a 422 like any other bad input.
        try:
            filters = CostFilters(
                project_id=project_id,
                project_run_id=project_run_id,
                job_id=job_id,
                thread_id=thread_id,
                since=since,
                until=until,
            )
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if (
            filters.since is not None
            and filters.until is not None
            and filters.since >= filters.until
        ):
            raise HTTPException(status_code=422, detail="since must be before until")
        report = await cost_report(
            workspace_id=workspace_id, filters=filters, conn_factory=conn_factory
        )
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "report": report.model_dump(mode="json"),
        }

    @router.get("/project_runs/{project_run_id}/overview")
    async def get_overview(project_run_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await run_overview(
            surface=surface,
            conn_factory=conn_factory,
            project_run_id=ProjectRunId(project_run_id),
            workspace_id=workspace_id,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such project run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "overview": view.model_dump(mode="json"),
        }

    @router.get("/project_runs/{project_run_id}/accounts/{account_id}/progress")
    async def get_account_progress(
        project_run_id: UUID, account_id: UUID, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        view = await account_progress(
            conn_factory=conn_factory,
            project_run_id=ProjectRunId(project_run_id),
            workspace_id=workspace_id,
            account_entity_id=EntityId(account_id),
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such account in this run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "progress": view.model_dump(mode="json"),
        }

    @router.get("/project_runs/{project_run_id}/manifest")
    async def get_manifest(project_run_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await run_manifest(
            conn_factory=conn_factory,
            project_run_id=ProjectRunId(project_run_id),
            workspace_id=workspace_id,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such project run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "manifest": view.model_dump(mode="json"),
        }

    @router.get("/project_runs/{project_run_id}/readiness")
    async def get_readiness(project_run_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await run_readiness(
            surface=surface,
            conn_factory=conn_factory,
            project_run_id=ProjectRunId(project_run_id),
            workspace_id=workspace_id,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such project run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "readiness": view.model_dump(mode="json"),
        }

    @router.get("/research_coverage/{run_id}")
    async def get_research_coverage(
        run_id: UUID,
        workspace_id: WorkspaceDep,
        project_run_id: Annotated[UUID | None, Query()] = None,
        entity_id: Annotated[UUID | None, Query()] = None,
    ) -> dict[str, Any]:
        view = await research_coverage(
            conn_factory=conn_factory,
            workspace_id=workspace_id,
            run_id=RunId(run_id),
            project_run_id=(ProjectRunId(project_run_id) if project_run_id is not None else None),
            entity_id=EntityId(entity_id) if entity_id is not None else None,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no research coverage for this run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "research_coverage": view.model_dump(mode="json"),
        }

    @router.get("/stage0/recon/{recon_run_id}/brief")
    async def get_recon_brief(recon_run_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await recon_brief(
            recon_run_id=ReconRunId(recon_run_id),
            workspace_id=workspace_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such recon run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "recon_brief": view.model_dump(mode="json"),
        }

    @router.get("/stage0/recon/{recon_run_id}/progress")
    async def get_stage0_progress(recon_run_id: UUID, workspace_id: WorkspaceDep) -> dict[str, Any]:
        view = await stage0_progress(
            recon_run_id=ReconRunId(recon_run_id),
            workspace_id=workspace_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such recon run")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "stage0_progress": view.model_dump(mode="json"),
        }

    @router.get("/stage0/readiness/{readiness_decision_id}")
    async def get_stage0_readiness(
        readiness_decision_id: UUID, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        view = await stage0_readiness(
            readiness_decision_id=ReadinessDecisionId(readiness_decision_id),
            workspace_id=workspace_id,
            conn_factory=conn_factory,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such readiness decision")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "stage0_readiness": view.model_dump(mode="json"),
        }

    @router.get("/research_attempt_history/{run_id}/{entity_id}/{field_key}")
    async def get_research_attempt_history(
        run_id: UUID,
        entity_id: UUID,
        field_key: str,
        workspace_id: WorkspaceDep,
    ) -> dict[str, Any]:
        view = await research_attempt_history(
            conn_factory=conn_factory,
            workspace_id=workspace_id,
            run_id=RunId(run_id),
            entity_id=EntityId(entity_id),
            field_key=field_key,
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no research attempts for this field")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "research_attempt_history": view.model_dump(mode="json"),
        }

    @router.get("/field_proposals")
    async def get_field_proposals(
        workspace_id: WorkspaceDep,
        brand_id: Annotated[str | None, Query()] = None,
        status: Annotated[ProposalStatus | None, Query()] = None,
    ) -> dict[str, Any]:
        views = await field_proposals(
            conn_factory=conn_factory,
            workspace_id=workspace_id,
            brand_id=brand_id,
            status=status,
        )
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "field_proposals": [view.model_dump(mode="json") for view in views],
        }

    @router.get("/source_proposals")
    async def get_source_proposals(
        workspace_id: WorkspaceDep,
        brand_id: Annotated[str | None, Query()] = None,
        status: Annotated[ProposalStatus | None, Query()] = None,
    ) -> dict[str, Any]:
        views = await source_proposals(
            conn_factory=conn_factory,
            workspace_id=workspace_id,
            brand_id=brand_id,
            status=status,
        )
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "source_proposals": [view.model_dump(mode="json") for view in views],
        }

    @router.get("/ingestion_status/{ingestion_job_id}")
    async def get_ingestion_status(
        ingestion_job_id: UUID, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        view = await ingestion_status(
            conn_factory=conn_factory,
            workspace_id=workspace_id,
            ingestion_job_id=IngestionJobId(ingestion_job_id),
        )
        if view is None:
            raise HTTPException(status_code=404, detail="no such ingestion job")
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "ingestion_status": view.model_dump(mode="json"),
        }

    # -- the tool-invocation route (the single typed write path; A9 idempotency at HTTP) --

    async def _invoke(
        name: str,
        body: dict[str, Any],
        *,
        request: Request,
        workspace_id: str,
        actor: Actor,
        quality_mode: str | None,
        idempotency_key: str | None,
    ) -> ToolResult:
        operation_id = (
            operation_id_from_key(workspace_id, f"tool:{name}:{idempotency_key}")
            if idempotency_key is not None
            else new_operation_id()
        )
        principal = principal_from_request(request)
        if principal is not None:
            if name.startswith(("launch_", "run_deep_")):
                principal.require("research.launch")
            elif name.startswith(("confirm_", "approve_", "override_", "decide_")):
                principal.require("research.approve_spend")
            elif name.startswith("estimate_"):
                principal.require("research.estimate")
            elif not name.startswith(("read_", "get_")):
                principal.require("thread.write")
            ctx = tool_context_for_principal(
                principal,
                conn_factory=conn_factory,
                operation_id=operation_id,
                quality_mode=quality_mode,
            )
        else:
            ctx = ToolContext(
                workspace_id=workspace_id,
                actor=actor,
                conn_factory=conn_factory,
                operation_id=operation_id,
                quality_mode=quality_mode,
            )
        try:
            return await tool_invoker.invoke(
                name,
                body,
                ctx,
                idempotency_key=idempotency_key,
            )
        except UnknownTool as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        except PreconditionFailed as exc:
            # 422 with the machine-readable reason codes (pre-mortem #2 — a loud typed refusal, the
            # out-of-order-matrix assertion surface), never a silent-empty success.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "precondition_failed",
                    "reason_codes": list(exc.reason_codes),
                    "failures": [
                        {"reason_code": f.reason_code, "message": f.message} for f in exc.failures
                    ],
                },
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_conflict", "reason": exc.reason, "key": exc.key},
            ) from exc
        except OperationConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_conflict", "reason": "operation"},
            ) from exc
        except ToolAuthorityStateChanged as exc:
            raise MembershipStateChanged(
                "workspace membership changed before the tool effect was journaled"
            ) from exc

    @router.post("/tools/{name}")
    async def post_tool(
        request: Request,
        name: str,
        body: dict[str, Any],
        workspace_id: WorkspaceDep,
        actor: ActorDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        quality_mode: Annotated[str | None, Header(alias="X-Quality-Mode")] = None,
    ) -> ToolInvokeResponse:
        result = await _invoke(
            name,
            body,
            request=request,
            workspace_id=workspace_id,
            actor=actor,
            quality_mode=quality_mode,
            idempotency_key=idempotency_key,
        )
        return ToolInvokeResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, result=result)

    # -- manifest ops (pause/adjust mapped to the run machine via the toolbelt; else 422) --

    @router.patch("/project_runs/{project_run_id}/manifest")
    async def patch_manifest(
        request: Request,
        project_run_id: UUID,
        op_request: ManifestOpRequest,
        workspace_id: WorkspaceDep,
        actor: ActorDep,
    ) -> ToolInvokeResponse:
        reason = validate_manifest_op(op_request.op)
        if reason is not None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unsupported_manifest_op",
                    "reason": reason,
                    "accepted_ops": sorted(MANIFEST_OP_TOOLS),
                },
            )
        tool_name = MANIFEST_OP_TOOLS[op_request.op]
        tool_body: dict[str, Any] = {"project_run_id": str(project_run_id)}
        if op_request.op == "adjust":
            if op_request.budget_cap_cents is None:
                # The op IS supported — the request is missing its parameter (review F9b: a
                # missing-param case must not wear the unsupported-op taxonomy).
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "invalid_params",
                        "reason": "missing_budget_cap_cents",
                        "accepted_params": ["budget_cap_cents"],
                    },
                )
            tool_body["budget_cap_cents"] = op_request.budget_cap_cents
        result = await _invoke(
            tool_name,
            tool_body,
            request=request,
            workspace_id=workspace_id,
            actor=actor,
            quality_mode=None,
            idempotency_key=None,
        )
        return ToolInvokeResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, result=result)

    # -- SSE: mint a single-use token, then open the stream --

    @router.post("/project_runs/{project_run_id}/stream_token")
    async def post_stream_token(
        project_run_id: UUID, workspace_id: WorkspaceDep
    ) -> MintTokenResponse:
        run_id = ProjectRunId(project_run_id)
        async with conn_factory() as conn:
            # Review F7: refuse an absent or cross-tenant run at mint time (404, indistinguishable
            # from absent — the same posture as every projection route), so an authenticated header
            # can't hold open unbounded live-tails against arbitrary ids.
            run = await get_project_run(conn, run_id)
            if run is None or run.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="no such project run")
            token = await mint_stream_token(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                ttl_s=settings.sse_stream_token_ttl_s,
            )
        return MintTokenResponse(schema_version=PROJECTIONS_SCHEMA_VERSION, stream_token=str(token))

    @router.get("/project_runs/{project_run_id}/events")
    async def get_events(
        project_run_id: UUID,
        workspace_id: WorkspaceDep,
        stream_token: Annotated[str, Query()],
        last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        last_event_id_query: Annotated[int | None, Query(alias="last_event_id")] = None,
    ) -> StreamingResponse:
        run_id = ProjectRunId(project_run_id)
        # Consume the single-use token up-front (a used/expired/cross-tenant/wrong-run token → 401,
        # no leak). Run-bound (review F2): a token opens only the stream it was minted for.
        try:
            token_uuid = UUID(stream_token)
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(status_code=401, detail="invalid stream token") from exc
        async with conn_factory() as conn:
            ok = await consume_stream_token(
                conn, token=token_uuid, workspace_id=workspace_id, run_id=run_id
            )
        if not ok:
            raise HTTPException(status_code=401, detail="invalid or already-used stream token")

        # Last-Event-ID: a parseable header (EventSource reconnect) wins; the query cursor is the
        # fallback — including when the header is garbage (review F8: an unparseable header must
        # not discard an already-parsed query cursor).
        cursor: int | None = last_event_id_query
        if last_event_id_header is not None:
            with contextlib.suppress(ValueError):
                cursor = int(last_event_id_header)

        async def _stream() -> AsyncIterator[str]:
            yield _sse_frame(event="stream.hello", data={"run_id": str(run_id)})
            async with conn_factory() as conn:
                plan = await plan_replay(
                    # The concrete reader is built HERE and injected (D8): the planner lives in
                    # clue_core and clue_projections may not import the clue_execution DAL.
                    DbRunEventReader(conn, workspace_id=workspace_id, run_id=run_id),
                    last_event_id=cursor,
                    horizon_s=settings.sse_replay_horizon_s,
                    limit=settings.sse_replay_page_limit,
                )
            if plan.reset:
                yield _sse_frame(event="stream.reset", data={"reason": "cursor_older_than_horizon"})
            # The tail floor is the plan's EFFECTIVE cursor (review F1): on reset it is 0, never
            # the consumer's bogus cursor — which would silently match nothing forever.
            last_seq = plan.effective_cursor
            for ev in plan.backlog:
                yield _sse_frame(event=ev.topic, data=ev.payload, seq=ev.seq)
                last_seq = ev.seq
            if not sse_live_tail:
                return
            # Live tail: poll the outbox for new events until the client disconnects (the ASGI
            # server cancels this generator on disconnect). Deliberately unbounded in production.
            while True:
                await asyncio.sleep(sse_poll_interval_s)
                async with conn_factory() as conn:
                    new = await list_run_events(
                        conn, workspace_id=workspace_id, run_id=run_id, after_seq=last_seq
                    )
                for ev in new:
                    yield _sse_frame(event=ev.topic, data=ev.payload, seq=ev.seq)
                    last_seq = ev.seq

        return StreamingResponse(_stream(), media_type="text/event-stream")

    return router


@asynccontextmanager
async def _projections_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Production lifespan: configure logging once, open the DB engine for the app's lifetime."""
    clue_obs.setup()
    async with (
        production_tracing_lifespan(getattr(_app.state, "tracing", None)),
        production_metrics_lifespan(
            _app.state.settings,
            service_name="clue-projections-api",
        ),
        db_lifespan(),
    ):
        startup_check = getattr(_app.state, "startup_check", None)
        if startup_check is not None:
            await startup_check()
        try:
            yield
        finally:
            auth_closer = getattr(_app.state, "auth_closer", None)
            if auth_closer is not None:
                await auth_closer()
            library_closer = getattr(_app.state, "project_library_closer", None)
            if library_closer is not None:
                library_closer()
            from clue_storage import close_shared_s3_clients

            await close_shared_s3_clients()


def create_projections_app(
    *,
    surface: ObservabilitySurface,
    tool_invoker: ToolInvoker,
    settings: Settings | None = None,
    conn_factory: ConnFactory = transaction,
    workspace_resolver: WorkspaceResolver | None = None,
    actor_resolver: ActorResolver | None = None,
    ingestion_storage: StorageBackend | None = None,
    sse_poll_interval_s: float = 1.0,
    sse_live_tail: bool = True,
    manage_db_lifespan: bool = True,
    agent_registry: AgentProfileRegistry | None = None,
    research_view_composer: ResearchViewComposer | None = None,
    research_view_snapshots: ResearchViewSnapshotService | None = None,
    research_view_evidence_access: EvidenceAccessService | None = None,
    research_view_owner_references: ProductionOwnerReferenceResolver | None = None,
    startup_check: Callable[[], Awaitable[None]] | None = None,
    discovery_webhook_router: APIRouter | None = None,
    chat_principal_resolver: PrincipalResolver | None = None,
    chat_stream_live_tail: bool = True,
    auth_service: PrincipalService | None = None,
    auth_closer: Callable[[], Awaitable[None]] | None = None,
    contact_email_lookup: Any | None = None,
    stage0_recon_enqueuer: Stage0ReconEnqueuer | None = None,
    transactional_tool_invoker_factory: TransactionalToolInvokerFactory | None = None,
    project_library: ProjectLibraryRefresher | None = None,
    project_library_closer: Callable[[], None] | None = None,
    tracing: TracingRuntime | None = None,
    memory_write_factory: MemoryWriteFactory | None = None,
) -> FastAPI:
    """Construct the B4 read-side FastAPI app (projections + tool route + manifest ops + SSE).

    ``surface`` / ``tool_invoker`` are the injected M13.4 observability surface and the mandatory
    C5.1 journaled invocation boundary. ``conn_factory`` is the connection seam every projection
    read + tool precondition + stream-token write uses (tests bind a savepoint-scoped factory).
    ``workspace_resolver`` / ``actor_resolver`` swap the auth seams via ``dependency_overrides``.
    ``auth_service`` is Lane B's authenticated principal chain; when present it governs the chat
    surface's identity (and, absent explicit resolvers, the other surfaces' workspace/actor seams).
    ``chat_principal_resolver`` injects a deterministic test/development ``RequestPrincipal``
    instead; without either, the chat surface may only run under ``local_header`` auth mode, and
    supplying both is refused at composition rather than resolved silently.
    ``sse_live_tail=False`` makes the SSE stream replay-then-close (deterministic for tests);
    production leaves it ``True`` (an open live stream). ``chat_stream_live_tail`` is the same
    switch for FI Lane D D3's turn stream.

    ``project_library`` is the project-library refresher the two surfaces that write a project's
    settled state call once their transaction commits — the human's project-document PUT and the
    ICP-confirmation pin. It is ``None`` on a deployment with no agent-workspace root, and both
    hooks are then no-ops. ``project_library_closer`` releases the workspace factory that
    refresher was built over; this process owns one only for that purpose, so it is closed with
    the other shutdown closers rather than left to process exit.

    ``tracing`` is the process's tracer runtime; when given and the settings ask for it, the app
    is instrumented at construction.

    ``memory_write_factory`` binds the project home's memory panel to the scoped-memory write
    seam. It is ``None`` on a deployment that composes no model gateway (reconciliation needs a
    judge), and the memory writes then refuse ``MEMORY_UNAVAILABLE`` while the list still
    serves."""
    resolved = settings if settings is not None else load_settings()
    if resolved.auth_environment == "production" and auth_service is None:
        raise RuntimeError("production projections require the authenticated principal service")
    app = FastAPI(
        title="Clue-HQ platform — projections + toolbelt + SSE",
        version=PROJECTIONS_SCHEMA_VERSION,
        lifespan=_projections_lifespan if manage_db_lifespan else None,
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness for Railway's health check, the uptime monitors and the boot smoke test
        (first deployment spec §9.5). Touches no database or Redis; needs no auth or workspace."""
        return {"status": "ok"}

    app.state.startup_check = startup_check
    app.state.auth_closer = auth_closer
    app.state.project_library_closer = project_library_closer
    app.state.settings = resolved
    app.state.tracing = tracing
    if tracing is not None and resolved.otel_instrument_fastapi:
        # Lane 3 slice 2: server spans. At construction on purpose — Starlette refuses new
        # middleware once the app has started.
        tracing.instrument_app(app)

    # Review F3: actually serve the declared schema header on EVERY response (JSON routes and the
    # SSE stream alike — response headers precede the streamed body), so a consumer can confirm the
    # shape it negotiated without parsing a body.
    @app.middleware("http")
    async def _schema_version_header(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers[PROJECTIONS_SCHEMA_HEADER] = PROJECTIONS_SCHEMA_VERSION
        return response

    @app.middleware("http")
    async def _request_context(request: Any, call_next: Any) -> Any:
        """Bind the request id for the whole request (log lines, span attributes, Sentry tags)
        and echo it. The frontend-read envelope middleware, when it runs first, has already
        minted one on ``request.state``; a safe incoming ``X-Request-Id`` is kept; else new."""
        existing = getattr(request.state, "request_id", None)
        request_id = existing if isinstance(existing, str) else request_id_for(request)
        request.state.request_id = request_id
        with bound_context(request_id=request_id):
            # The FastAPI instrumentor wraps ``build_middleware_stack``, so its server span is
            # OUTSIDE every HTTP middleware — it had already opened when this one ran, and the
            # start-of-span context copy missed the id. Annotate the open span too, as the tenant
            # seams do. ``bound_context`` still owns the scope: the binding is undone on exit.
            bind_and_annotate(request_id=request_id)
            response = await call_next(request)
        response.headers.setdefault(REQUEST_ID_HEADER, request_id)
        return response

    # FI-2 slice 1: the `/frontend/v1` read surface — its own router, error envelope, request id,
    # and the process's CORS policy. Both halves are default-off (flag / empty origins), so an
    # unconfigured deployment is byte-identical to the pre-FI-2 app.
    # ``Secrets()`` is read ONCE, here, and reaches exactly one consumer: the D3 display seam's
    # runner (the only thing under `/frontend/v1` that spends money). A deployment with no key —
    # every test app included — composes a seam that cannot generate, so the read surface stays a
    # pure projection instead of refusing to start.
    runtime_secrets = Secrets()
    install_frontend_read_surface(
        app,
        settings=resolved,
        conn_factory=conn_factory,
        evidence_storage=ingestion_storage,
        contact_email_lookup=contact_email_lookup,
        secrets=runtime_secrets,
        project_library=project_library,
        memory_write_factory=memory_write_factory,
        # The display seam schedules page writes on the fleet instead of writing them on the
        # request — the same default work queue the onboarding enqueuer and the persona request
        # service already use in this process.
        work_queue=DbWorkQueue(),
    )
    if auth_service is not None:
        from clue_auth.providers.clerk_api import ClerkApi

        clerk_secret = runtime_secrets.auth_clerk_secret_key
        # The provision route (workspace-creating write) mounts only behind its default-off
        # flag, matching the rollout discipline of every neighbouring surface.
        install_auth_wiring(
            app,
            service=auth_service,
            conn_factory=conn_factory,
            provision_enabled=resolved.self_serve_provisioning_enabled,
            clerk_api=ClerkApi(clerk_secret.get_secret_value()) if clerk_secret else None,
            pages_system_suffix=resolved.pages_system_suffix,
            # The workspace switcher's company logo (Brandfetch's embed-only Logo API).
            brandfetch_client_id=resolved.brandfetch_client_id,
        )
        if workspace_resolver is None and actor_resolver is None:
            workspace_resolver, actor_resolver = authenticated_route_resolvers(auth_service)

    # FI Lane D D0: the `/api/v1` chat surface — REQ-21's thread shell. Default-off flag; enabled
    # outside local_header auth mode it demands a real Lane B principal (either the authenticated
    # service below, or an injected resolver) and refuses to start without one. Supplying both is
    # a contradiction the installer refuses outright.
    install_chat_surface(
        app,
        settings=resolved,
        conn_factory=conn_factory,
        tool_invoker=tool_invoker,
        principal_resolver=chat_principal_resolver,
        auth_service=auth_service,
        # D2's turn submission captures the user's bytes as a durable artifact before enqueueing.
        # The same backend the ingestion surface already uses; nothing model-shaped is added here.
        storage=ingestion_storage,
        transactional_tool_invoker_factory=transactional_tool_invoker_factory,
        project_library=project_library,
    )

    # FI Lane D D3: the turn stream (attach/stop/retry/hydrated cold load), behind the same
    # default-off flag and governed by the same principal resolver the chat surface installed.
    install_chat_stream_surface(
        app,
        settings=resolved,
        conn_factory=conn_factory,
        storage=ingestion_storage,
        live_tail=chat_stream_live_tail,
    )

    if workspace_resolver is not None:
        app.dependency_overrides[header_workspace_resolver] = workspace_resolver
        app.dependency_overrides[ingestion_header_workspace_resolver] = workspace_resolver
        app.dependency_overrides[research_workspace_resolver] = workspace_resolver
        app.dependency_overrides[frontend_read_workspace_resolver] = workspace_resolver
        app.dependency_overrides[chat_workspace_resolver] = workspace_resolver
        app.dependency_overrides[setup_workspace_resolver] = workspace_resolver
        app.dependency_overrides[onboarding_workspace_resolver] = workspace_resolver
    if actor_resolver is not None:
        app.dependency_overrides[header_actor_resolver] = actor_resolver
        app.dependency_overrides[ingestion_header_actor_resolver] = actor_resolver
        app.dependency_overrides[research_actor_resolver] = actor_resolver
    app.include_router(
        create_projections_router(
            surface=surface,
            tool_invoker=tool_invoker,
            settings=resolved,
            conn_factory=conn_factory,
            sse_poll_interval_s=sse_poll_interval_s,
            sse_live_tail=sse_live_tail,
            agent_registry=agent_registry,
        )
    )
    if ingestion_storage is not None:
        app.include_router(
            build_ingestion_router(
                tool_invoker=tool_invoker,
                storage=ingestion_storage,
                conn_factory=conn_factory,
            )
        )
    # FI-4 slice 2: the onboarding workspace-setup composition (capture → onboarding_input →
    # recon driver + the lane-truth read). Rides the same default-off flag as the provisioning
    # route it continues; needs the storage backend for capture-before-use.
    # 2026-09-12: the old recon is its own switch (ledger A4); provisioning no longer implies it.
    if resolved.legacy_stage0_recon_enabled and ingestion_storage is not None:
        app.include_router(
            create_stage0_setup_router(
                tool_invoker=tool_invoker,
                conn_factory=conn_factory,
                storage=ingestion_storage,
                recon_enqueuer=(
                    stage0_recon_enqueuer
                    if stage0_recon_enqueuer is not None
                    else DbStage0ReconEnqueuer()
                ),
                # Brand-kit slice 2: None unless CLUE_DESIGN_API_BASE_URL names the design API,
                # in which case first-time onboarding also enqueues one draft brand-kit
                # ingestion of the captured website.
                brand_kit_ingestion=build_brand_kit_ingestion_trigger(
                    settings=resolved, conn_factory=conn_factory
                ),
            )
        )
    # ARV2 Track O (O3): the onboarding run surface — POST records the run and hands it to the
    # fleet, GET polls the run and its steps. Default-off; nothing but the row insert and the
    # enqueue happens on this loop.
    if resolved.onboarding_v2_enabled:
        app.include_router(
            create_onboarding_router(
                conn_factory=conn_factory,
                enqueuer=DbOnboardingEnqueuer(),
                # Same posture as the Stage-0 mount: None unless CLUE_DESIGN_API_BASE_URL names
                # the design API, in which case onboarding also seeds one draft brand kit.
                brand_kit_ingestion=build_brand_kit_ingestion_trigger(
                    settings=resolved, conn_factory=conn_factory
                ),
            )
        )
    if discovery_webhook_router is not None:
        app.include_router(discovery_webhook_router)
    research_components = (
        research_view_composer,
        research_view_snapshots,
        research_view_evidence_access,
    )
    c7_http_enabled = any(
        (
            resolved.c7_research_view_read_enabled,
            resolved.c7_snapshot_compose_enabled,
            resolved.c7_recheck_enabled,
            resolved.c7_evidence_actions_enabled,
            resolved.c7_legacy_dossier_alias_enabled,
        )
    )
    if resolved.c7_legacy_dossier_alias_enabled and not (
        resolved.c7_research_view_read_enabled or resolved.c7_snapshot_compose_enabled
    ):
        raise ValueError(
            "the legacy dossier alias requires canonical C7 read or snapshot composition"
        )
    if c7_http_enabled and not all(component is not None for component in research_components):
        raise ValueError(
            "an enabled C7 HTTP capability requires the production composer, "
            "snapshot service, and evidence-access service"
        )
    if resolved.c7_research_view_read_enabled and research_view_owner_references is None:
        raise ValueError("enabled C7 reads require authenticated owner-reference batch resolution")
    if any(component is not None for component in research_components):
        if not all(component is not None for component in research_components):
            raise ValueError(
                "research-view serving requires composer, snapshot service, and evidence access"
            )
        assert research_view_composer is not None
        assert research_view_snapshots is not None
        assert research_view_evidence_access is not None
        app.include_router(
            build_research_view_router(
                composer=research_view_composer,
                snapshots=research_view_snapshots,
                evidence_access=research_view_evidence_access,
                tool_invoker=tool_invoker,
                conn_factory=conn_factory,
                settings=resolved,
                owner_references=research_view_owner_references,
            )
        )
    return app
