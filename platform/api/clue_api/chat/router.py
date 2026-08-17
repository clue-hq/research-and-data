"""The `/api/v1` chat router: REQ-21 thread CRUD and the cold-load transcript reads.

Installed from the projections composition root by :func:`install_chat_surface`, entirely behind
``settings.chat_enabled`` (default off): a disabled deployment never registers a route and 404s
these paths exactly as it does today.

**Every mutation goes through the toolbelt.** The three write endpoints do not touch
``agent_thread`` — they invoke ``create_thread@1`` / ``rename_thread@1`` / ``set_thread_pinned@1``
/ ``archive_thread@1`` through the injected :class:`~clue_toolbelt.ToolInvoker`, because Doc A
makes the toolbelt the only write path and because that is what buys the C5.1 journal and A9
idempotency. A tool's typed ``PreconditionFailed`` becomes a 404/409 with its stable reason code
in the envelope; it never becomes a 500.

**Errors are enveloped per route, not per app.** ``frontend_read`` already owns app-level
``StarletteHTTPException`` / ``RequestValidationError`` / ``Exception`` handlers, and FastAPI keeps
one handler per exception class — installing a second set here would silently replace that lane's
envelope. So this surface wraps its own endpoints (:class:`_EnvelopeRoute`) instead: the shape is
the same FI-1 ``{"error": {"code", "message", "requestId"}}`` with an ``X-Request-Id`` header, and
nothing outside this router changes behaviour.

**CORS is deliberately untouched.** This surface serves the same-origin/Next-proxy deployment the
founder ratified. Cross-origin ``POST``/``PATCH`` widening is Lane D **D2**'s item per the
demarcation registry §2.2, and doing it here would mean editing another lane's middleware.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Coroutine
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.exceptions import HTTPException as StarletteHTTPException

from clue_agents import DomainObjectRef
from clue_api.agent_gate import (
    KIND_DIRECTIVE_CONFIRMATION,
    KIND_ICP_CONFIRMATION,
    KIND_PRODUCT_SELECTION,
    AgentGateRow,
    GateAlreadyAnswered,
    get_gate,
    insert_gate_answer,
)
from clue_api.agent_turn_submission import (
    SubmissionConflict,
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    submission_context_refs,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_tool_context import tool_context_for_principal
from clue_api.auth_wiring import PrincipalDependency, principal_from_request
from clue_api.chat.composer_context import (
    PROJECT_CONVERSATION_AGENT_PROFILE_ID,
    PROJECT_CONVERSATION_MODEL_ID,
    ComposerContextEntity,
    ContextReferenceError,
    list_composer_context_entities,
    prepare_composer_context_entities,
    validated_context_refs,
)
from clue_api.chat.context_refs import TurnContextRefsResponse, context_refs_response
from clue_api.chat.inspector import (
    INSPECTOR_TABS,
    InspectorCapabilityResponse,
    InspectorCapabilityWire,
    InspectorContextResponse,
    InspectorPlanResponse,
    InspectorRoundsResponse,
    InspectorToolsResponse,
    context_response,
    plan_response,
    rounds_response,
    tools_response,
)
from clue_api.chat.message_bodies import hydrate_message_bodies
from clue_api.chat.principal import (
    PERMISSION_GATE_RESPOND,
    PERMISSION_PROJECT_READ,
    PERMISSION_PROJECT_WRITE,
    PERMISSION_THREAD_READ,
    PERMISSION_THREAD_WRITE,
    PrincipalResolver,
    ProductionPrincipalRequired,
    RequestPrincipal,
    build_dev_principal_resolver,
)
from clue_api.chat.schemas import (
    AgentProfileOptionWire,
    ComposerContextEntityWire,
    CreateThreadRequest,
    DesignArtifactResponse,
    DesignArtifactWire,
    GateListResponse,
    GateResponseRequest,
    HomeBrandWire,
    HomeComposerCapabilitiesWire,
    HomeProjectRequest,
    HomeResponse,
    HomeWire,
    MessageListResponse,
    PageMeta,
    PrepareComposerContextRequest,
    PreparedComposerContextResponse,
    PreparedComposerContextWire,
    ProjectBootstrapProjectWire,
    ProjectBootstrapResponse,
    ProjectBootstrapThreadWire,
    ProjectBootstrapWire,
    ProjectShellResponse,
    ProjectShellWire,
    SidebarConversationWire,
    SidebarPageMeta,
    SidebarProjectsResponse,
    SidebarProjectWire,
    SubmitTurnRequest,
    ThreadListResponse,
    ThreadResponse,
    TurnAcceptedResponse,
    TurnAcceptedWire,
    UpdateThreadRequest,
    gate_response_message,
    gate_wire,
    message_list_response,
    thread_href,
    thread_speaker_wire,
    thread_wire,
    thread_wire_from_references,
)
from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_api.conversation_capture import persist_user_turn, project_client_entity_id
from clue_api.design_leg_wiring import design_legs_for_threads
from clue_api.stage0_icp_gate import IcpGateSubjectError, exact_icp_gate_subject
from clue_api.stage0_project_scope import resolve_stage0_project_scope_for_project
from clue_api.thread_store import create_thread, get_thread, thread_id_for_operation
from clue_api.turn_action import derive_turn_action_ref
from clue_auth import Permission, PrincipalError, PrincipalService
from clue_config import Settings
from clue_core import OperationId, operation_id_from_key
from clue_db import ConnFactory
from clue_design import legs as design_leg_dal
from clue_design.documents import get_document as get_design_document
from clue_design.errors import DesignNotFoundError
from clue_obs import get_logger
from clue_projections import (
    DEFAULT_PROJECT_SIDEBAR_PAGE_SIZE,
    DEFAULT_THREAD_MESSAGE_PAGE_SIZE,
    DEFAULT_THREAD_PAGE_SIZE,
    MAX_PROJECT_SIDEBAR_PAGE_SIZE,
    MAX_THREAD_MESSAGE_PAGE_SIZE,
    MAX_THREAD_PAGE_SIZE,
    InvalidCursorError,
    open_gate_kinds_for_threads,
    project_sidebar_page,
    thread_gates,
    thread_messages,
    threads_for_project,
    threads_running,
    turn_context_receipt,
    turn_exists,
    turn_model_rounds,
    turn_plan_receipt,
    turn_status_ledger,
    turn_tool_calls,
)
from clue_research.icp import activate_icp_version
from clue_spine import (
    create_project,
    get_brand,
    get_project,
    get_project_for_workspace,
    list_brands_for_workspace,
)
from clue_storage import StorageBackend, StorageError, content_address
from clue_toolbelt import IdempotencyConflict, PreconditionFailed, ToolInvoker

log = get_logger("clue_api.chat")

__all__ = [
    "CHAT_PREFIX",
    "REQUEST_ID_HEADER",
    "bind_authenticated_principal",
    "bind_principal_resolver",
    "build_chat_router",
    "chat_principal_resolver",
    "chat_workspace_resolver",
    "install_chat_surface",
]

#: Every route this package serves lives under this prefix — the path the frontend's authored
#: contract names, so the Next.js proxy forwards without rewriting.
CHAT_PREFIX = "/api/v1"

REQUEST_ID_HEADER = "X-Request-Id"

#: Tool reason code → (HTTP status, envelope code). A refusal this surface has not classified
#: becomes a 422 with its own reason code, never an unlabelled 500.
_REASON_STATUS: dict[str, tuple[int, str]] = {
    "project_not_found": (404, "PROJECT_NOT_FOUND"),
    "thread_not_found": (404, "THREAD_NOT_FOUND"),
    "thread_archived": (409, "THREAD_ARCHIVED"),
}

_HOME_PROJECT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-home-project-bootstrap")
_UNTITLED_PROJECT = "Untitled project"
_HOME_SUGGESTIONS = (
    "Find target accounts for our new campaign",
    "Research the buying committee for a target account",
    "Plan a personalized ABM campaign",
)


def _framed(*parts: str) -> str:
    return "".join(f"{len(part)}:{part}" for part in parts)


def _home_project_id(*, workspace_id: str, idempotency_key: str) -> str:
    """The one project identity a workspace-scoped Home act may create."""

    return (
        "prj_"
        + uuid5(
            _HOME_PROJECT_NAMESPACE,
            _framed(workspace_id, idempotency_key),
        ).hex
    )


def _first_thread_title(message: str) -> str:
    """Apply R0's exact Unicode-whitespace and 80-code-point title rule."""

    normalized = re.sub(r"\s+", " ", message.strip())
    if len(normalized) <= 80:
        return normalized
    prefix = normalized[:79]
    boundary = prefix.rfind(" ")
    if boundary > 0:
        prefix = prefix[:boundary]
    return prefix + "…"


def chat_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    """This surface's tenant *selector*.

    A selector is not authority (Lane B ruling 6): the principal resolver still has to prove an
    active membership for whatever workspace arrives here. Its own function, so the composition
    root can swap real service auth of the same ``-> workspace_id`` shape per surface through
    ``dependency_overrides`` — the pattern ``projections_app`` and ``ingestion_tools`` follow.
    """

    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


WorkspaceDep = Annotated[str, Depends(chat_workspace_resolver)]


def chat_principal_resolver(workspace_id: WorkspaceDep) -> RequestPrincipal:
    """The principal seam — **module-level on purpose**, and deny-by-default.

    Module-level because FastAPI resolves this file's stringified annotations against module
    globals: a closure-local ``Annotated`` alias is silently mistaken for a query parameter (the
    same trap ``projections_app`` documents at its own dependency aliases). Deny-by-default because
    an unconfigured surface must refuse rather than invent an identity; :func:`install_chat_surface`
    replaces it via ``dependency_overrides`` with either Lane B's authorizer or — under the
    local/test guard only — the development resolver.
    """

    del workspace_id
    raise _refuse(
        status_code=401,
        code="AUTHENTICATION_REQUIRED",
        message="the chat surface has no principal resolver installed",
    )


PrincipalDep = Annotated[RequestPrincipal, Depends(chat_principal_resolver)]


def bind_principal_resolver(resolver: PrincipalResolver) -> Callable[..., RequestPrincipal]:
    """Adapt an injected resolver into the FastAPI dependency the routes declare.

    The workspace re-check is structural rather than trusting: an authorizer that answered about a
    *different* workspace than the request selected must never have its answer applied here
    (Lane B ruling 6 — selection is not authority).
    """

    def resolve(workspace_id: WorkspaceDep) -> RequestPrincipal:
        principal = resolver(workspace_id)
        if principal.workspace_id != workspace_id:
            raise _refuse(
                status_code=403,
                code="WORKSPACE_FORBIDDEN",
                message="the authorized workspace differs from the requested workspace",
            )
        return principal

    return resolve


def bind_authenticated_principal(
    service: PrincipalService,
    *,
    permission: Permission = PERMISSION_PROJECT_READ,
) -> Callable[..., Awaitable[RequestPrincipal]]:
    """Adapt **Lane B's real chain** into the same FastAPI dependency the routes declare.

    This is the B2 join: the provider session is validated, mapped through ``auth_identity`` to a
    ``platform_user``, and checked against an active ``workspace_membership`` for the *selected*
    workspace before any route body runs. Nothing about the routes changes — they still declare
    :func:`chat_principal_resolver` — which is the whole point of having kept the seam.

    ``permission`` is the floor for *entering* the surface, not the authority for what a route
    does: every endpoint re-checks its own permission against ``principal.permissions`` (contract
    §3.5, "every backend request … re-checks the required permission").

    Two details earn their lines:

    * **Cache coherence.** Lane B's :class:`~clue_api.auth_wiring.PrincipalDependency` stores the
      principal it resolved on ``request.state``. When the composition root has also pointed this
      surface's workspace seam at Lane B's authenticated resolver, that work is already done by the
      time this dependency runs, so it is reused instead of authenticating and reading Postgres a
      second time for the same request.
    * **The workspace re-check survives.** A reused principal is still compared against the
      selector this surface resolved, exactly as the injected path is (ruling 6).
    """

    dependency = PrincipalDependency(service, permission=permission)

    async def resolve(request: Request, workspace_id: WorkspaceDep) -> RequestPrincipal:
        cached = principal_from_request(request)
        principal = cached if cached is not None else await dependency(request, workspace_id)
        if principal.workspace_id != workspace_id:
            raise _refuse(
                status_code=403,
                code="WORKSPACE_FORBIDDEN",
                message="the authorized workspace differs from the requested workspace",
            )
        return principal

    return resolve


def _request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str):
        return existing
    generated = uuid4().hex
    request.state.request_id = generated
    return generated


def _envelope(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    resolved = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "requestId": resolved}},
        headers={REQUEST_ID_HEADER: resolved},
    )


def _validation_message(exc: ValidationError | RequestValidationError) -> str:
    """A compact, non-leaking summary: locations and reasons, never submitted values."""

    parts: list[str] = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
        reason = str(error.get("msg", "invalid"))
        parts.append(f"{location}: {reason}" if location else reason)
    return "; ".join(parts) if parts else "request validation failed"


class _EnvelopeRoute(APIRoute):
    """Wrap this router's handlers so every outcome is the FI-1 envelope.

    Route-scoped on purpose — see the module docstring: app-level handlers are already owned by
    another lane's surface and FastAPI keeps only one per exception class.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            resolved = _request_id(request)
            try:
                response = await original(request)
            except StarletteHTTPException as exc:
                detail = exc.detail
                code = (
                    detail["code"]
                    if isinstance(detail, dict) and isinstance(detail.get("code"), str)
                    else _status_code_name(exc.status_code)
                )
                message = (
                    str(detail.get("message"))
                    if isinstance(detail, dict) and detail.get("message")
                    else (str(detail) if isinstance(detail, str) else code.lower())
                )
                return _envelope(request, status_code=exc.status_code, code=code, message=message)
            except PrincipalError as exc:
                # Lane B's authentication/authorization refusals already carry the contract §6 code
                # and status (AUTHENTICATION_REQUIRED / SESSION_INVALID /
                # IDENTITY_NOT_PROVISIONED / USER_DISABLED / WORKSPACE_FORBIDDEN /
                # PERMISSION_DENIED / MEMBERSHIP_STATE_CHANGED).
                # They are raised inside dependency resolution, which happens *inside* the route
                # handler — so without this clause the generic catch below would turn a correct 403
                # into a 500 and the client could not tell "no access" from "we broke".
                return _envelope(
                    request,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                )
            except (RequestValidationError, ValidationError) as exc:
                # ``RequestValidationError`` is the request-body/query failure (an unknown field,
                # a bad type); the pydantic one is a response-model failure. Both are 422 with a
                # location-and-reason summary that never echoes the submitted value back.
                return _envelope(
                    request,
                    status_code=422,
                    code="VALIDATION_ERROR",
                    message=_validation_message(exc),
                )
            except StorageError:
                # A missing individual blob is translated by the bounded hydrator into
                # ``artifact_missing``. Reaching here means the backend itself could not perform
                # the read/write, so do not mislabel a wider outage as permanent message loss.
                log.exception(
                    "chat.artifact_storage_unavailable",
                    path=request.url.path,
                    request_id=resolved,
                )
                return _envelope(
                    request,
                    status_code=503,
                    code="ARTIFACT_STORAGE_UNAVAILABLE",
                    message="artifact storage is temporarily unavailable",
                )
            except Exception:
                # Swallowed deliberately: the traceback is logged with the request id the client
                # is told, and the client gets a code it can report rather than an opaque failure.
                log.exception("chat.unhandled_error", path=request.url.path, request_id=resolved)
                return _envelope(
                    request,
                    status_code=500,
                    code="INTERNAL_ERROR",
                    message="internal server error",
                )
            response.headers.setdefault(REQUEST_ID_HEADER, resolved)
            return response

        return handler


_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _status_code_name(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "ERROR")


def _refuse(*, status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _gate_response(body: SubmitTurnRequest) -> GateResponseRequest:
    """Narrow the mutually-exclusive body once, where the type checker can see it.

    ``SubmitTurnRequest`` guarantees exactly one of the two fields, but that guarantee lives in a
    validator, so every read still has to prove it. Doing it here keeps the route free of repeated
    ``assert``s and makes the impossible branch a loud error rather than an ``Optional`` leaking
    into the capture path.
    """

    if body.gate_response is None:  # pragma: no cover - the validator forbids it
        raise _refuse(
            status_code=422,
            code="VALIDATION_ERROR",
            message="supply exactly one of message or gate_response",
        )
    return body.gate_response


def _agent_profile_options() -> tuple[AgentProfileOptionWire, ...]:
    return (
        AgentProfileOptionWire(
            id=PROJECT_CONVERSATION_AGENT_PROFILE_ID,
            label="GPT-5.6 Terra",
            short_label="GPT-5.6 Terra",
            description="Clue's governed GPT-5.6 Terra conversation profile",
            model_id=PROJECT_CONVERSATION_MODEL_ID,
        ),
    )


def _selected_agent_profile_id(requested: str | None) -> str:
    selected = requested or PROJECT_CONVERSATION_AGENT_PROFILE_ID
    if selected != PROJECT_CONVERSATION_AGENT_PROFILE_ID:
        raise _refuse(
            status_code=409,
            code="AGENT_PROFILE_UNAVAILABLE",
            message="the selected agent profile is not available for project conversations",
        )
    return selected


def _context_entity_wire(entity: ComposerContextEntity) -> ComposerContextEntityWire:
    return ComposerContextEntityWire(
        object_type=entity.object_type,
        object_id=entity.object_id,
        label=entity.label,
        secondary_label=entity.secondary_label,
        image_url=entity.image_url,
        version=entity.version,
    )


async def _validated_submission_context(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: tuple[Any, ...],
) -> tuple[DomainObjectRef, ...]:
    requested = tuple(
        DomainObjectRef(
            workspace_id=workspace_id,
            object_type=ref.object_type,
            object_id=ref.object_id,
            version=ref.version,
        )
        for ref in refs
    )
    try:
        return await validated_context_refs(
            conn,
            workspace_id=workspace_id,
            refs=requested,
        )
    except ContextReferenceError as exc:
        raise _refuse(
            status_code=404 if exc.code == "CONTEXT_REF_NOT_FOUND" else 409,
            code=exc.code,
            message=exc.message,
        ) from exc


def _composer_capabilities() -> HomeComposerCapabilitiesWire:
    return HomeComposerCapabilitiesWire(
        context_refs=True,
        attachments=False,
        agent_profile_selection=True,
    )


def build_chat_router(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    tool_invoker: ToolInvoker,
    storage: StorageBackend | None = None,
) -> APIRouter:
    """Build the workspace-scoped chat router. Empty unless ``settings.chat_enabled``.

    The principal arrives through the module-level :func:`chat_principal_resolver` dependency,
    which :func:`install_chat_surface` overrides — so a router built without one refuses every
    request 401 rather than serving anybody.

    ``storage`` is the artifact backend the turn-submission route captures the user's bytes into.
    Without it that one route is **not registered** (the thread shell still serves), because a
    surface that accepted turns it could not durably capture would be accepting them into nothing.
    Note what this parameter is *not*: nothing model-shaped. A gateway, a model provider, or a
    toolbelt composed with either has no place in this process (§3-P3) — the turn is executed by
    the fleet worker, and :mod:`tests.api.test_lane_d2_http_gateway_isolation` is the guard.
    """

    router = APIRouter(prefix=CHAT_PREFIX, tags=["chat"], route_class=_EnvelopeRoute)
    if not settings.chat_enabled:
        return router
    artifacts = (
        None
        if storage is None
        else DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    )

    def _require(who: RequestPrincipal, permission: Permission) -> None:
        if permission not in who.permissions:
            raise _refuse(
                status_code=403,
                code="PERMISSION_DENIED",
                message=f"the active membership lacks {permission}",
            )

    async def _invoke(
        name: str,
        body: dict[str, Any],
        *,
        who: RequestPrincipal,
        idempotency_key: str | None,
        action_ref: str | None = None,
        operation_id: OperationId | None = None,
    ) -> dict[str, Any]:
        """Invoke one governed tool and return its references.

        ``actor_id`` is the principal's internal ``platform_user.user_id`` — ambient, never a
        request field. ``operation_id`` is derived from the caller's ``Idempotency-Key`` when there
        is one, so a retried create lands on the same thread instead of a second one.

        ``action_ref`` is the *human receipt* a gated tool needs (charter §3-P2): the canonical
        ``turn-action:`` reference for the turn this request has just persisted. It is supplied here
        and never accepted from the client — the two together are what let a human-only tool run
        outside the model surface with authority the server derived. A caller that passes an
        ``operation_id`` gets replay identity of its own choosing, which the gate path uses so a
        retried approval replays the same confirmation instead of colliding with it.

        The context is built by **Lane B's own** :func:`tool_context_for_principal` rather than by
        hand. That is the B4 join: it stamps ``principal_kind='human'`` and the
        ``membership_id`` alongside the user id, which is precisely what
        :func:`clue_api.auth_tool_context.require_human_authority` demands of every receipt-bearing
        human-only tool (``confirm_account_research_directive@2`` among them). A hand-built context
        without those two fields is the *legacy* shape, and a legacy context can never satisfy a
        gate that requires an action reference.
        """

        ctx = tool_context_for_principal(
            who,
            conn_factory=conn_factory,
            operation_id=(
                operation_id
                if operation_id is not None
                else operation_id_from_key(
                    who.workspace_id, f"chat:{name}:{idempotency_key or uuid4().hex}"
                )
            ),
            action_ref=action_ref,
        )
        try:
            result = await tool_invoker.invoke(name, body, ctx, idempotency_key=idempotency_key)
        except PreconditionFailed as exc:
            first = exc.failures[0]
            status_code, code = _REASON_STATUS.get(first.reason_code, (422, "PRECONDITION_FAILED"))
            raise _refuse(
                status_code=status_code,
                code=code if first.reason_code in _REASON_STATUS else first.reason_code.upper(),
                message=first.message,
            ) from exc
        except IdempotencyConflict as exc:
            raise _refuse(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                message="this idempotency key was already used with a different request",
            ) from exc
        return dict(result.references)

    # --- Home bootstrap ------------------------------------------------------------------------

    @router.get("/home")
    async def home_route(who: PrincipalDep) -> HomeResponse:
        """Return only the real, workspace-scoped inputs the Home composer may use.

        Context entries come from Lane C's governed workspace reads. The one advertised profile is
        the promoted Head-of-ABM GPT-5.6 Terra profile; attachments remain unavailable because no
        durable upload-receipt endpoint exists yet.
        """

        _require(who, PERMISSION_PROJECT_READ)
        async with conn_factory() as conn:
            brands = await list_brands_for_workspace(conn, who.workspace_id)
            context_entities = await list_composer_context_entities(
                conn,
                workspace_id=who.workspace_id,
            )
        return HomeResponse(
            data=HomeWire(
                brands=tuple(HomeBrandWire(id=brand.brand_id, name=brand.name) for brand in brands),
                default_brand_id=brands[0].brand_id if len(brands) == 1 else None,
                context_entities=tuple(_context_entity_wire(entity) for entity in context_entities),
                agent_profiles=_agent_profile_options(),
                default_agent_profile_id=PROJECT_CONVERSATION_AGENT_PROFILE_ID,
                composer_capabilities=_composer_capabilities(),
                suggestions=_HOME_SUGGESTIONS,
            )
        )

    if artifacts is not None:

        @router.post("/projects", status_code=201)
        async def bootstrap_project_route(
            body: HomeProjectRequest,
            who: PrincipalDep,
            response: Response,
            idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        ) -> ProjectBootstrapResponse:
            """Atomically create a project and accept its first platform-Deep-Agent turn.

            The HTTP process only captures and queues. It never resolves a model or invokes the
            agent runtime; the same Lane-D fleet dispatcher used by an existing project observes
            the committed submission afterwards.
            """

            _require(who, PERMISSION_PROJECT_WRITE)
            _require(who, PERMISSION_THREAD_WRITE)
            if not idempotency_key or not idempotency_key.strip():
                raise _refuse(
                    status_code=400,
                    code="IDEMPOTENCY_KEY_REQUIRED",
                    message="creating a project requires an Idempotency-Key header",
                )
            if body.attachment_refs:
                raise _refuse(
                    status_code=409,
                    code="CAPABILITY_UNAVAILABLE",
                    message="this deployment does not accept attachments",
                )
            agent_profile_id = _selected_agent_profile_id(body.agent_profile_id)

            key = idempotency_key.strip()
            project_id = _home_project_id(workspace_id=who.workspace_id, idempotency_key=key)
            operation_id = operation_id_from_key(
                who.workspace_id,
                f"home-project-bootstrap:{key}",
            )
            thread_id = thread_id_for_operation(
                workspace_id=who.workspace_id,
                operation_id=operation_id,
            )
            turn_id = turn_id_for_submission(
                workspace_id=who.workspace_id,
                thread_id=thread_id,
                idempotency_key=key,
            )
            title = _first_thread_title(body.message)
            digest = content_address(body.message.encode())

            async with conn_factory() as conn:
                # One logical Home act owns one transaction-wide lock. It serializes concurrent
                # retries before either can observe a half-created project/thread pair.
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": f"home-project-bootstrap:{who.workspace_id}:{key}"},
                )
                brand = await get_brand(
                    conn,
                    workspace_id=who.workspace_id,
                    brand_id=body.brand_id,
                )
                if brand is None:
                    raise _refuse(
                        status_code=404,
                        code="BRAND_NOT_FOUND",
                        message="no such brand in this workspace",
                    )
                context_refs = await _validated_submission_context(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=body.context_refs,
                )

                project = await get_project(conn, project_id)
                if project is None:
                    project = await create_project(
                        conn,
                        project_id=project_id,
                        workspace_id=who.workspace_id,
                        brand_id=body.brand_id,
                        name=_UNTITLED_PROJECT,
                        status="active",
                    )
                elif (
                    project.workspace_id != who.workspace_id
                    or project.brand_id != body.brand_id
                    or project.name != _UNTITLED_PROJECT
                    or project.status != "active"
                ):
                    raise _refuse(
                        status_code=409,
                        code="IDEMPOTENCY_CONFLICT",
                        message="this idempotency key was already used with a different request",
                    )

                thread = await create_thread(
                    conn,
                    thread_id=thread_id,
                    workspace_id=who.workspace_id,
                    project_id=project_id,
                    title=title,
                    created_by_user_id=who.user_id,
                    created_via_membership_id=who.membership_id,
                )
                if thread.project_id != project_id or thread.title != title:
                    raise _refuse(
                        status_code=409,
                        code="IDEMPOTENCY_CONFLICT",
                        message="this idempotency key was already used with a different request",
                    )

                existing = await get_submission(
                    conn,
                    workspace_id=who.workspace_id,
                    turn_id=turn_id,
                )
                replayed = existing is not None
                if existing is not None:
                    existing_context_refs = await submission_context_refs(
                        conn,
                        workspace_id=who.workspace_id,
                        turn_id=turn_id,
                    )
                    if (
                        existing.project_id != project_id
                        or existing.thread_id != thread_id
                        or existing.message_sha256 != digest
                        or existing.agent_profile_id != agent_profile_id
                        or existing_context_refs != context_refs
                    ):
                        raise _refuse(
                            status_code=409,
                            code="IDEMPOTENCY_CONFLICT",
                            message=(
                                "this idempotency key was already used with a different request"
                            ),
                        )
                    submission = existing
                    # Heal a prior post-commit delivery failure without making another task.
                    await dispatch_next_thread_turn(
                        conn,
                        workspace_id=who.workspace_id,
                        thread_id=thread_id,
                    )
                else:
                    captured = await persist_user_turn(
                        conn,
                        artifacts=artifacts,
                        workspace_id=who.workspace_id,
                        brand_id=project.brand_id,
                        product_id=project.product_id,
                        project_id=project_id,
                        turn_id=turn_id,
                        message=body.message,
                        client_entity_id=await project_client_entity_id(
                            conn,
                            workspace_id=who.workspace_id,
                            project_id=project_id,
                        ),
                    )
                    try:
                        submission, _created = await insert_submission(
                            conn,
                            turn_id=turn_id,
                            workspace_id=who.workspace_id,
                            project_id=project_id,
                            thread_id=thread_id,
                            submitted_by_user_id=who.user_id,
                            submitted_via_membership_id=who.membership_id,
                            onboarding_input_id=captured.onboarding_input_id,
                            message_artifact_key=captured.artifact_ref.artifact_key,
                            message_sha256=captured.artifact_ref.sha256,
                            idempotency_key=key,
                            context_refs=context_refs,
                            agent_profile_id=agent_profile_id,
                        )
                    except SubmissionConflict as exc:
                        raise _refuse(
                            status_code=409,
                            code="IDEMPOTENCY_CONFLICT",
                            message=str(exc),
                        ) from exc
                    await emit_turn_event(
                        conn,
                        workspace_id=who.workspace_id,
                        project_id=project_id,
                        thread_id=thread_id,
                        turn_id=turn_id,
                        event_type=TurnEventType.TURN_ACCEPTED,
                        payload={
                            "requested_at": submission.requested_at.isoformat(),
                            "source": "home",
                            "kind": "message",
                        },
                    )
                    await dispatch_next_thread_turn(
                        conn,
                        workspace_id=who.workspace_id,
                        thread_id=thread_id,
                    )

            href = thread_href(project_id=project_id, thread_id=thread_id)
            if replayed:
                response.status_code = 200
            return ProjectBootstrapResponse(
                data=ProjectBootstrapWire(
                    project=ProjectBootstrapProjectWire(
                        id=project_id,
                        title=project.name,
                        brand_id=project.brand_id,
                        href=f"/projects/{project_id}",
                        created_at=project.created_at.isoformat(),
                    ),
                    thread=ProjectBootstrapThreadWire(
                        id=thread.id,
                        title=title,
                        href=href,
                        project_id=project_id,
                        created_at=thread.created_at.isoformat(),
                        updated_at=thread.updated_at.isoformat(),
                    ),
                    turn=TurnAcceptedWire(
                        turn_id=str(turn_id),
                        thread_id=thread_id,
                        requested_at=submission.requested_at.isoformat(),
                        replayed=replayed,
                    ),
                    href=href,
                )
            )

    @router.get("/projects/sidebar")
    async def project_sidebar_route(
        who: PrincipalDep,
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_PROJECT_SIDEBAR_PAGE_SIZE),
        ] = DEFAULT_PROJECT_SIDEBAR_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
    ) -> SidebarProjectsResponse:
        """Return the real project/thread hierarchy in a constant query count."""

        _require(who, PERMISSION_PROJECT_READ)
        _require(who, PERMISSION_THREAD_READ)
        try:
            page = await project_sidebar_page(
                workspace_id=who.workspace_id,
                limit=limit,
                cursor=cursor,
                conn_factory=conn_factory,
            )
        except InvalidCursorError as exc:
            raise _refuse(status_code=422, code="INVALID_CURSOR", message=str(exc)) from exc

        thread_ids = tuple(thread.thread_id for project in page.items for thread in project.threads)
        open_gates = await open_gate_kinds_for_threads(
            workspace_id=who.workspace_id,
            thread_ids=thread_ids,
            conn_factory=conn_factory,
        )
        busy = await threads_running(
            workspace_id=who.workspace_id,
            thread_ids=thread_ids,
            conn_factory=conn_factory,
        )
        return SidebarProjectsResponse(
            data=tuple(
                SidebarProjectWire(
                    id=project.project_id,
                    title=project.title,
                    href=f"/projects/{project.project_id}",
                    conversations=tuple(
                        SidebarConversationWire(
                            id=thread.thread_id,
                            title=thread.title,
                            href=thread_href(
                                project_id=project.project_id,
                                thread_id=thread.thread_id,
                            ),
                            status=thread_wire(
                                thread,
                                open_gate_kinds=open_gates.get(thread.thread_id, ()),
                                running=thread.thread_id in busy,
                            ).status,
                            pinned=thread.pinned,
                            updated_at=thread.updated_at.isoformat(),
                        )
                        for thread in project.threads
                    ),
                )
                for project in page.items
            ),
            meta=SidebarPageMeta(next_cursor=page.next_cursor),
        )

    @router.get("/projects/{project_id}/design-artifacts/{artifact_id}")
    async def design_artifact_route(
        project_id: str,
        artifact_id: str,
        who: PrincipalDep,
    ) -> DesignArtifactResponse:
        """W1.3 v1 read seam: resolve a platform artifact id to its design document.

        Design documents are not yet registered as platform artifacts, so the
        artifact id IS the design-document id (the founder-sanctioned v1
        fallback); both the project and the document are workspace-scoped
        fail-closed reads. See ``DesignArtifactWire`` for the recorded
        containment gap and follow-up.
        """

        _require(who, PERMISSION_PROJECT_READ)
        async with conn_factory() as conn:
            project = await get_project_for_workspace(
                conn,
                workspace_id=who.workspace_id,
                project_id=project_id,
            )
            if project is None:
                raise _refuse(
                    status_code=404,
                    code="PROJECT_NOT_FOUND",
                    message="no such project in this workspace",
                )
            try:
                document = await get_design_document(
                    conn,
                    workspace_id=who.workspace_id,
                    document_id=artifact_id,
                )
            except DesignNotFoundError:
                raise _refuse(
                    status_code=404,
                    code="ARTIFACT_NOT_FOUND",
                    message="no such design artifact in this workspace",
                ) from None
        return DesignArtifactResponse(
            data=DesignArtifactWire(
                id=artifact_id,
                project_id=project_id,
                document_id=artifact_id,
                kind="web" if document["doc_kind"] == "web" else "ad",
                title=str(document["title"]),
                status=str(document["status"]),
                current_version_id=str(document["current_version"]),
            )
        )

    @router.get("/projects/{project_id}")
    async def project_shell_route(
        project_id: str,
        who: PrincipalDep,
    ) -> ProjectShellResponse:
        """Return only durable project-shell data owned by this deployment."""

        _require(who, PERMISSION_PROJECT_READ)
        async with conn_factory() as conn:
            project = await get_project_for_workspace(
                conn,
                workspace_id=who.workspace_id,
                project_id=project_id,
            )
            context_entities = (
                ()
                if project is None
                else await list_composer_context_entities(
                    conn,
                    workspace_id=who.workspace_id,
                )
            )
        if project is None:
            raise _refuse(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="no such project in this workspace",
            )
        return ProjectShellResponse(
            data=ProjectShellWire(
                id=project.project_id,
                title=project.name,
                brand_id=project.brand_id,
                product_id=project.product_id,
                status=project.status,
                created_at=project.created_at.isoformat(),
                context_entities=tuple(_context_entity_wire(entity) for entity in context_entities),
                agent_profiles=_agent_profile_options(),
                default_agent_profile_id=PROJECT_CONVERSATION_AGENT_PROFILE_ID,
                composer_capabilities=_composer_capabilities(),
            )
        )

    @router.post("/projects/{project_id}/composer-context/prepare")
    async def prepare_project_composer_context_route(
        project_id: str,
        body: PrepareComposerContextRequest,
        who: PrincipalDep,
    ) -> PreparedComposerContextResponse:
        """Validate and hydrate one exact table selection before browser navigation.

        No draft, project membership, research operation, or other domain state is written here.
        The eventual turn submission revalidates the returned canonical references.
        """

        _require(who, PERMISSION_THREAD_WRITE)
        async with conn_factory() as conn:
            project = await get_project_for_workspace(
                conn,
                workspace_id=who.workspace_id,
                project_id=project_id,
            )
            if project is None:
                raise _refuse(
                    status_code=404,
                    code="PROJECT_NOT_FOUND",
                    message="no such project in this workspace",
                )
            if body.thread_id is not None:
                thread = await get_thread(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=body.thread_id,
                )
                if (
                    thread is None
                    or thread.workspace_id != who.workspace_id
                    or thread.project_id != project_id
                ):
                    raise _refuse(
                        status_code=404,
                        code="THREAD_NOT_FOUND",
                        message="no such thread in this project",
                    )
                if thread.status != "active":
                    raise _refuse(
                        status_code=409,
                        code="THREAD_ARCHIVED",
                        message="an archived thread accepts no new context",
                    )
            requested = tuple(
                DomainObjectRef(
                    workspace_id=who.workspace_id,
                    object_type=ref.object_type,
                    object_id=ref.object_id,
                    version=ref.version,
                )
                for ref in body.context_refs
            )
            try:
                prepared = await prepare_composer_context_entities(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=requested,
                )
            except ContextReferenceError as exc:
                raise _refuse(
                    status_code=404 if exc.code == "CONTEXT_REF_NOT_FOUND" else 409,
                    code=exc.code,
                    message=exc.message,
                ) from exc
        return PreparedComposerContextResponse(
            data=PreparedComposerContextWire(
                project_id=project_id,
                thread_id=body.thread_id,
                context_entities=tuple(_context_entity_wire(entity) for entity in prepared),
            )
        )

    # --- threads --------------------------------------------------------------------------------

    @router.post("/projects/{project_id}/threads", status_code=201)
    async def create_thread_route(
        project_id: str,
        body: CreateThreadRequest,
        who: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ThreadResponse:
        _require(who, PERMISSION_THREAD_WRITE)
        references = await _invoke(
            "create_thread",
            {"project_id": project_id, "title": body.title},
            who=who,
            idempotency_key=idempotency_key,
        )
        return ThreadResponse(data=thread_wire_from_references(references))

    @router.get("/projects/{project_id}/threads")
    async def list_threads_route(
        project_id: str,
        who: PrincipalDep,
        status: Annotated[str | None, Query(pattern="^(active|archived)$")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_THREAD_PAGE_SIZE)] = DEFAULT_THREAD_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
    ) -> ThreadListResponse:
        _require(who, PERMISSION_THREAD_READ)
        try:
            page = await threads_for_project(
                workspace_id=who.workspace_id,
                project_id=project_id,
                status=status,
                limit=limit,
                cursor=cursor,
                conn_factory=conn_factory,
            )
        except InvalidCursorError as exc:
            raise _refuse(status_code=422, code="INVALID_CURSOR", message=str(exc)) from exc
        # One anti-join for the whole page (FI Lane D D4): the sidebar's approval / needs-input
        # badge is derived from unanswered gates, and a per-row read would cost a query per
        # conversation to answer "is anyone waiting on me?".
        thread_ids = tuple(item.thread_id for item in page.items)
        open_gates = await open_gate_kinds_for_threads(
            workspace_id=who.workspace_id,
            thread_ids=thread_ids,
            conn_factory=conn_factory,
        )
        # The other half of the same badge (FI Lane D D3), and the other one-statement anti-join:
        # a thread is *running* when the submissions-union says it holds a turn that is queued or
        # executing. Queued counts — a turn submitted thirty seconds ago that no worker has claimed
        # yet is the conversation working, not the conversation idle — and it is only visible at
        # all because the union reads submissions, which is where a not-yet-executed turn lives.
        busy = await threads_running(
            workspace_id=who.workspace_id,
            thread_ids=thread_ids,
            conn_factory=conn_factory,
        )
        # P3.4's speaker projection, the third one-statement anti-join: a thread with an open
        # design leg is owned by Design until the leg closes, and the sidebar chip must say so
        # without inferring it from transcripts.
        open_legs = await design_legs_for_threads(
            conn_factory,
            workspace_id=who.workspace_id,
            thread_ids=thread_ids,
        )
        return ThreadListResponse(
            data=tuple(
                thread_wire(
                    item,
                    open_gate_kinds=open_gates.get(item.thread_id, ()),
                    running=item.thread_id in busy,
                    speaker=thread_speaker_wire(open_legs.get(item.thread_id)),
                )
                for item in page.items
            ),
            meta=PageMeta(next_cursor=page.next_cursor),
        )

    @router.patch("/projects/{project_id}/threads/{thread_id}")
    async def update_thread_route(
        project_id: str,
        thread_id: str,
        body: UpdateThreadRequest,
        who: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ThreadResponse:
        _require(who, PERMISSION_THREAD_WRITE)
        del project_id  # the thread id is workspace-unique; the path project is a routing detail
        references: dict[str, Any] = {}
        # Two independent governed mutations rather than one compound tool: the authored contract
        # allows either field alone, and a single "update" tool would have to encode "unset means
        # leave alone" in its schema — a shape a model reads wrong.
        if body.title is not None:
            references = await _invoke(
                "rename_thread",
                {"thread_id": thread_id, "title": body.title},
                who=who,
                idempotency_key=(None if idempotency_key is None else f"{idempotency_key}:title"),
            )
        if body.pinned is not None:
            references = await _invoke(
                "set_thread_pinned",
                {"thread_id": thread_id, "pinned": body.pinned},
                who=who,
                idempotency_key=(None if idempotency_key is None else f"{idempotency_key}:pinned"),
            )
        return ThreadResponse(data=thread_wire_from_references(references))

    @router.post("/projects/{project_id}/threads/{thread_id}/archive")
    async def archive_thread_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ThreadResponse:
        _require(who, PERMISSION_THREAD_WRITE)
        del project_id
        references = await _invoke(
            "archive_thread",
            {"thread_id": thread_id},
            who=who,
            idempotency_key=idempotency_key,
        )
        return ThreadResponse(data=thread_wire_from_references(references))

    # --- transcript cold load ---------------------------------------------------------------

    @router.get("/projects/{project_id}/threads/{thread_id}/messages")
    async def list_messages_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
        limit: Annotated[
            int, Query(ge=1, le=MAX_THREAD_MESSAGE_PAGE_SIZE)
        ] = DEFAULT_THREAD_MESSAGE_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
        include: Annotated[str | None, Query(pattern="^bodies$")] = None,
    ) -> MessageListResponse:
        """One page of the durable transcript; ``?include=bodies`` hydrates that page's bodies.

        Body-free stays the default (D0's decision): a message summary carries the *content
        address*, and the words are fetched deliberately. But a transcript cannot be rendered from
        addresses — a browser cannot issue one artifact fetch per message — so charter §3.6's cold
        load is this listing plus an explicit opt-in, hydrated server-side in one round trip.

        The opt-in is bounded three ways and stays that way: by the page (the pagination limit *is*
        the fan-out limit, so no request shape hydrates a whole thread), by a cumulative byte
        budget, and by media type. A body that cannot be served — erased, too large, not text —
        comes back ``null`` with a reason rather than an empty string that would render as a message
        nobody wrote. Without a storage backend the parameter is refused rather than silently
        ignored, because a surface that cannot read bytes must not pretend it did.
        """

        _require(who, PERMISSION_THREAD_READ)
        del project_id
        if include is not None and artifacts is None:
            raise _refuse(
                status_code=503,
                code="BODIES_UNAVAILABLE",
                message="this deployment has no artifact backend to hydrate message bodies",
            )
        try:
            page = await thread_messages(
                workspace_id=who.workspace_id,
                thread_id=thread_id,
                limit=limit,
                cursor=cursor,
                conn_factory=conn_factory,
            )
        except InvalidCursorError as exc:
            raise _refuse(status_code=422, code="INVALID_CURSOR", message=str(exc)) from exc
        if include is None:
            return message_list_response(page, thread_id=thread_id)
        assert storage is not None  # guarded above: ``artifacts`` exists iff ``storage`` does
        async with conn_factory() as conn:
            bodies = await hydrate_message_bodies(
                conn,
                storage=storage,
                workspace_id=who.workspace_id,
                references=tuple((item.body_artifact_key, item.body_sha256) for item in page.items),
            )
        return message_list_response(page, thread_id=thread_id, bodies=bodies)

    @router.get("/projects/{project_id}/threads/{thread_id}/gates")
    async def list_gates_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
    ) -> GateListResponse:
        """Every gate this thread has ever presented, oldest first, with its answer and launches.

        The read the approval card cannot work without. A gate is answered by echoing back exactly
        what was on the screen — ``POST …/turns`` refuses a ``gate_response`` whose
        ``expected_subject_sha256`` or ``expected_estimated_cost_cents`` differs from the immutable
        row — so a client that cannot read the durable gate can *show* a card and can never
        *answer* it. The stream's ``gate`` part signals that a card exists; this is where its
        answerable payload comes from.

        **Unpaginated on purpose.** A thread's gates are bounded by the number of directives its
        conversation drafted, the projection is one indexed anti-join over one thread, and a closed
        gate stays in history (§3.4) — so a cursor here would be machinery for a list that does not
        grow with the transcript. The message and thread reads, which do, keep theirs.

        Scoped exactly like every other thread read: a thread in another project or another
        workspace is **not found**, never forbidden, because a 403 would confirm to somebody who
        cannot see it that it exists.
        """

        _require(who, PERMISSION_THREAD_READ)
        async with conn_factory() as conn:
            thread = await get_thread(conn, workspace_id=who.workspace_id, thread_id=thread_id)
        if thread is None or thread.project_id != project_id:
            raise _refuse(
                status_code=404,
                code="THREAD_NOT_FOUND",
                message="no such thread in this project",
            )
        views = await thread_gates(
            workspace_id=who.workspace_id,
            thread_id=thread_id,
            conn_factory=conn_factory,
        )
        return GateListResponse(
            data=tuple(
                gate_wire(view, budget_controls_enabled=settings.budget_controls_enabled)
                for view in views
            )
        )

    # --- the dev-lens turn-context inspector (dev-only; never registered in production) ---------
    #
    # Registered only under ``settings.chat_dev_inspector_enabled``, which
    # ``Settings._refuse_dev_lens_in_production`` refuses at process construction in a production
    # deployment. So production-unreachability is structural twice over: the routes are absent, in
    # a process that would not have started with the flag set. There is no request-time check to
    # get wrong because there is no request-time state.
    #
    # Every one of them serves receipts the turn already wrote — no new table, no new column, no
    # write of any kind — and is scoped by the same ``thread.read`` permission and the same
    # 404-not-403 rule as its neighbours.

    async def _thread_or_404(*, who: RequestPrincipal, project_id: str, thread_id: str) -> None:
        """Prove this principal's workspace holds this thread in this project, or 404.

        Not 403: telling somebody who cannot see a thread that it exists is itself a disclosure.
        """

        async with conn_factory() as conn:
            thread = await get_thread(conn, workspace_id=who.workspace_id, thread_id=thread_id)
        if thread is None or thread.project_id != project_id:
            raise _refuse(
                status_code=404,
                code="THREAD_NOT_FOUND",
                message="no such thread in this project",
            )

    async def _inspected_turn(
        *, who: RequestPrincipal, project_id: str, thread_id: str, turn_id: UUID
    ) -> None:
        """The scope check every inspector read runs before touching a receipt."""

        _require(who, PERMISSION_THREAD_READ)
        await _thread_or_404(who=who, project_id=project_id, thread_id=thread_id)
        if not await turn_exists(
            workspace_id=who.workspace_id,
            thread_id=thread_id,
            turn_id=turn_id,
            conn_factory=conn_factory,
        ):
            raise _refuse(
                status_code=404,
                code="TURN_NOT_FOUND",
                message="no such turn in this thread",
            )

    @router.get("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/context-refs")
    async def turn_context_refs_route(
        project_id: str,
        thread_id: str,
        turn_id: UUID,
        who: PrincipalDep,
    ) -> TurnContextRefsResponse:
        """Exact persisted context pointers for operators and acceptance, never artifact bodies.

        Unlike the optional dev inspector, this is safe to register in production: its response
        type has no body/text/value/evidence/URL field and the route has no hydration switch.
        Before context assembly commits it returns a typed ``pending`` receipt rather than an
        invented empty bundle.
        """

        await _inspected_turn(
            who=who,
            project_id=project_id,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        return context_refs_response(
            turn_id=str(turn_id),
            receipt=await turn_context_receipt(
                workspace_id=who.workspace_id,
                turn_id=turn_id,
                conn_factory=conn_factory,
            ),
        )

    if settings.chat_dev_inspector_enabled:
        budget_bytes = settings.chat_dev_inspector_budget_bytes

        @router.get("/projects/{project_id}/threads/{thread_id}/inspector")
        async def inspector_capability_route(
            project_id: str,
            thread_id: str,
            who: PrincipalDep,
        ) -> InspectorCapabilityResponse:
            """The capability probe the drawer's affordance is rendered from.

            The frontend reads no environment variable to decide whether the inspector exists: it
            asks, and a deployment without the lens answers 404 because the route was never
            registered. One probe per thread, so a component never hardcodes a flag it cannot see
            the server change.
            """

            _require(who, PERMISSION_THREAD_READ)
            await _thread_or_404(who=who, project_id=project_id, thread_id=thread_id)
            return InspectorCapabilityResponse(
                data=InspectorCapabilityWire(
                    enabled=True,
                    tabs=INSPECTOR_TABS,
                    budget_bytes=budget_bytes,
                    bodies_available=storage is not None,
                )
            )

        @router.get("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/inspector/context")
        async def inspector_context_route(
            project_id: str,
            thread_id: str,
            turn_id: UUID,
            who: PrincipalDep,
        ) -> InspectorContextResponse:
            """Tab 1 — the seven-layer assembly receipt and the exact included bytes."""

            await _inspected_turn(
                who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id
            )
            receipt = await turn_context_receipt(
                workspace_id=who.workspace_id, turn_id=turn_id, conn_factory=conn_factory
            )
            async with conn_factory() as conn:
                return await context_response(
                    conn,
                    storage=storage,
                    workspace_id=who.workspace_id,
                    turn_id=str(turn_id),
                    receipt=receipt,
                    budget_bytes=budget_bytes,
                )

        @router.get("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/inspector/rounds")
        async def inspector_rounds_route(
            project_id: str,
            thread_id: str,
            turn_id: UUID,
            who: PrincipalDep,
        ) -> InspectorRoundsResponse:
            """Tab 2 — the governed model calls: model ids, tokens, cost, status, timing."""

            await _inspected_turn(
                who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id
            )
            return rounds_response(
                await turn_model_rounds(
                    workspace_id=who.workspace_id, turn_id=turn_id, conn_factory=conn_factory
                )
            )

        @router.get("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/inspector/plan")
        async def inspector_plan_route(
            project_id: str,
            thread_id: str,
            turn_id: UUID,
            who: PrincipalDep,
        ) -> InspectorPlanResponse:
            """Tab 3 — the authored plan, what validation admitted, and both verdict ledgers."""

            await _inspected_turn(
                who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id
            )
            plans = await turn_plan_receipt(
                workspace_id=who.workspace_id, turn_id=turn_id, conn_factory=conn_factory
            )
            events = await turn_status_ledger(
                workspace_id=who.workspace_id, turn_id=turn_id, conn_factory=conn_factory
            )
            async with conn_factory() as conn:
                return await plan_response(
                    conn,
                    storage=storage,
                    workspace_id=who.workspace_id,
                    turn_id=str(turn_id),
                    plans=plans,
                    turn_events=events,
                    budget_bytes=budget_bytes,
                )

        @router.get("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/inspector/tools")
        async def inspector_tools_route(
            project_id: str,
            thread_id: str,
            turn_id: UUID,
            who: PrincipalDep,
        ) -> InspectorToolsResponse:
            """Tab 4 — the admitted governed operations, their arguments and their receipts."""

            await _inspected_turn(
                who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id
            )
            calls = await turn_tool_calls(
                workspace_id=who.workspace_id, turn_id=turn_id, conn_factory=conn_factory
            )
            async with conn_factory() as conn:
                return await tools_response(
                    conn,
                    storage=storage,
                    workspace_id=who.workspace_id,
                    turn_id=str(turn_id),
                    calls=calls,
                    budget_bytes=budget_bytes,
                )

    # --- turn submission (D2) + the structured gate response (D4) ------------------------------

    async def _checked_gate(
        conn: AsyncConnection,
        response: GateResponseRequest,
        *,
        who: RequestPrincipal,
        project_id: str,
        thread_id: str,
        turn_id: UUID,
    ) -> AgentGateRow:
        """Prove this answer may be applied to this gate, or refuse with no side effects.

        Every check charter §5's adversarial matrix names lives here, and all of them run *before*
        anything is written. The advisory lock is taken first and is a **transaction** lock, so the
        "is it still unanswered?" read and the answer insert later in the same transaction are one
        atomic decision — two sessions clicking Approve at the same instant serialize, and the
        second finds the first's answer rather than racing past it.

        The one case that is not a refusal is the *same* turn answering again: that is a retried
        request, not a second decision, and the caller turns it into the idempotent replay.
        """

        try:
            gate_id = UUID(response.gate_id)
        except ValueError as exc:
            raise _refuse(
                status_code=422,
                code="GATE_ID_MALFORMED",
                message="a gate response must name one gate by its canonical identifier",
            ) from exc
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"agent-gate-answer:{who.workspace_id}:{gate_id}"},
        )
        view = await get_gate(conn, workspace_id=who.workspace_id, gate_id=gate_id)
        # A gate of another workspace, project, or thread is *not found* rather than forbidden:
        # a 403 would confirm it exists to somebody who cannot see it.
        if view is None or view.gate.project_id != project_id or view.gate.thread_id != thread_id:
            raise _refuse(
                status_code=404,
                code="GATE_NOT_FOUND",
                message="no such gate in this thread",
            )
        if view.gate.kind not in {
            KIND_DIRECTIVE_CONFIRMATION,
            KIND_ICP_CONFIRMATION,
            KIND_PRODUCT_SELECTION,
        }:
            raise _refuse(
                status_code=422,
                code="GATE_KIND_UNSUPPORTED",
                message=f"this surface cannot answer a {view.gate.kind} gate",
            )
        if not view.gate.snapshot_available:
            raise _refuse(
                status_code=410,
                code="GATE_SNAPSHOT_ERASED",
                message="this gate is unavailable because its reviewed subject was erased",
            )
        if response.decision not in view.gate.permitted_decisions:
            raise _refuse(
                status_code=422,
                code="GATE_DECISION_UNSUPPORTED",
                message="this decision was not offered by the durable gate",
            )
        # Addressee, not membership: a colleague with a perfectly valid session and a perfectly
        # valid turn of their own still may not answer somebody else's gate.
        if view.gate.addressee_user_id != who.user_id:
            raise _refuse(
                status_code=403,
                code="GATE_FORBIDDEN",
                message="this gate was addressed to somebody else",
            )
        if view.answer is not None and view.answer.turn_id != turn_id:
            raise _refuse(
                status_code=409,
                code="GATE_ALREADY_ANSWERED",
                message="this gate has already been answered",
            )
        # The two staleness checks. They are what make "Approve" mean the card that was on the
        # screen: a directive redrafted since, or an amount recomputed since, cannot be approved by
        # a click aimed at the previous one.
        if response.expected_subject_sha256 != view.gate.expected_subject_sha256:
            raise _refuse(
                status_code=409,
                code="GATE_SUBJECT_STALE",
                message="the reviewed subject revision differs from the current gate",
            )
        # FI pilot budget-controls: with the switch off the amount never reached the card, so the
        # client has no number to echo and this check could only refuse every approval. It is the
        # *courier* half of staleness; the digest check above is the load-bearing half and stays
        # armed in both modes, so a redrafted directive still cannot be approved by a stale click.
        if view.gate.kind == KIND_DIRECTIVE_CONFIRMATION:
            if (
                settings.budget_controls_enabled
                and response.expected_estimated_cost_cents != view.gate.max_spend_cents
            ):
                raise _refuse(
                    status_code=409,
                    code="GATE_AMOUNT_STALE",
                    message="the reviewed maximum spend differs from the current gate",
                )
        elif response.expected_estimated_cost_cents is not None:
            raise _refuse(
                status_code=422,
                code="GATE_AMOUNT_UNEXPECTED",
                message="this gate carries no spend amount",
            )

        if view.gate.kind == KIND_ICP_CONFIRMATION:
            if response.selected_product_id is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_UNEXPECTED",
                    message="an ICP confirmation does not accept a product choice",
                )
            if response.decision == "revised":
                if response.revision_request is None or not response.revision_request.strip():
                    raise _refuse(
                        status_code=422,
                        code="GATE_REVISION_REQUEST_REQUIRED",
                        message="revising an ICP requires the requested changes",
                    )
            elif response.revision_request is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_REVISION_REQUEST_UNEXPECTED",
                    message="revision_request is only valid for a revised ICP decision",
                )

            # A retry of the same answering turn is checked against its existing captured bytes
            # below. Its subject is active after an approval, so only a *new* answer revalidates the
            # still-draft snapshot before any receipt is written.
            if view.answer is None:
                scope = await resolve_stage0_project_scope_for_project(
                    conn,
                    workspace_id=who.workspace_id,
                    project_id=project_id,
                )
                try:
                    if scope is None:
                        raise IcpGateSubjectError(
                            "stage0_scope_not_found",
                            "the gate project no longer has a trusted Stage-0 scope",
                        )
                    icp_key = view.gate.subject_snapshot.get("icp_key")
                    version = view.gate.subject_snapshot.get("version")
                    if not isinstance(icp_key, str) or not isinstance(version, int):
                        raise IcpGateSubjectError(
                            "icp_gate_snapshot_invalid",
                            "the durable gate does not name a canonical ICP subject",
                        )
                    subject = await exact_icp_gate_subject(
                        conn,
                        scope=scope,
                        icp_key=icp_key,
                        icp_version=version,
                        require_project_synthesis=False,
                    )
                except IcpGateSubjectError as exc:
                    raise _refuse(
                        status_code=409,
                        code="GATE_SUBJECT_STALE",
                        message=str(exc),
                    ) from exc
                if (
                    subject.subject_ref != view.gate.subject_ref
                    or subject.spec.version != view.gate.subject_revision
                    or subject.snapshot != view.gate.subject_snapshot
                    or subject.sha256 != view.gate.expected_subject_sha256
                ):
                    raise _refuse(
                        status_code=409,
                        code="GATE_SUBJECT_STALE",
                        message="the persisted ICP draft differs from the reviewed snapshot",
                    )
        elif view.gate.kind == KIND_PRODUCT_SELECTION:
            if response.revision_request is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_REVISION_REQUEST_UNEXPECTED",
                    message="a product selection does not accept an ICP revision request",
                )
            products = view.gate.subject_snapshot.get("products")
            allowed = (
                {
                    str(item.get("product_id"))
                    for item in products
                    if isinstance(item, dict) and isinstance(item.get("product_id"), str)
                }
                if isinstance(products, list)
                else set()
            )
            if response.decision == "approved" and response.selected_product_id is None:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_REQUIRED",
                    message="select one product from the presented catalog",
                )
            if response.decision != "approved" and response.selected_product_id is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_UNEXPECTED",
                    message="a rejected or revised product question does not accept a choice",
                )
            if (
                response.selected_product_id is not None
                and response.selected_product_id not in allowed
            ):
                raise _refuse(
                    status_code=409,
                    code="GATE_PRODUCT_STALE",
                    message="the selected product was not in the presented catalog",
                )
        else:
            is_discovery_configuration = (
                view.gate.subject_snapshot.get("subject_kind") == "discovery_configuration"
            )
            if is_discovery_configuration and response.decision == "revised":
                if response.revision_request is None or not response.revision_request.strip():
                    raise _refuse(
                        status_code=422,
                        code="GATE_REVISION_REQUEST_REQUIRED",
                        message="revising discovery scope requires the requested changes",
                    )
            elif response.revision_request is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_REVISION_REQUEST_UNEXPECTED",
                    message=(
                        "revision_request is only valid for a revised discovery scope"
                        if is_discovery_configuration
                        else "an account-research directive does not accept revision text"
                    ),
                )
            if response.selected_product_id is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_UNEXPECTED",
                    message="a directive confirmation does not accept a product choice",
                )
        return view.gate

    if artifacts is not None:

        @router.post("/projects/{project_id}/threads/{thread_id}/turns", status_code=202)
        async def submit_turn_route(
            project_id: str,
            thread_id: str,
            body: SubmitTurnRequest,
            who: PrincipalDep,
            idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        ) -> TurnAcceptedResponse:
            """Accept one human turn — an ordinary message or a structured gate answer.

            This endpoint deliberately does **not** run the turn (ratified §6-D1). It writes what
            it can prove — the user's exact bytes, their capture record, and who submitted them —
            enqueues an ``AGENT_TURN`` task, and returns. The model never runs in this process, so
            a slow generation cannot occupy an HTTP worker and the launch tools the conversation
            will eventually reach stay composed only where they are governed.

            The ordering inside the transaction is the contract: capture, then record the
            submission, then offer the work. A crash anywhere before the enqueue leaves a captured
            message and no execution — recoverable and honest; a crash after leaves a queued turn
            whose identity is already durable.

            **The gate path (charter §3-P5(c)) adds three steps between those two**, and their
            order is the whole design:

            1. the gate is checked before a byte is written, so every refusal is side-effect free;
            2. the answer's canonical bytes are captured as *the turn's message*, so a decision is a
               visible transcript record and capture-before-effect holds exactly as it does for a
               sentence somebody typed;
            3. the once-only answer is recorded and — only for ``approved`` — the human-only
               ``confirm_account_research_directive@2`` runs with the ambient ``actor_id`` and the
               ``turn-action:`` receipt this request has just made durable.

            All of it is one transaction. A confirmation that cannot be applied therefore leaves no
            answer, no capture and no queued turn, instead of a gate burned by a transient failure;
            and because the confirmation's ``operation_id`` is derived from ``(gate, turn)``, a
            retry replays the same confirmation rather than colliding with it.
            """

            _require(who, PERMISSION_THREAD_WRITE)
            if body.gate_response is not None:
                # Answering a gate is its own authority in the contract's §3.5 floor: a member who
                # may write turns is not thereby a member who may close an approval. Checked here,
                # before the idempotency key is even read, so a member without it performs nothing.
                _require(who, PERMISSION_GATE_RESPOND)
            if not idempotency_key or not idempotency_key.strip():
                raise _refuse(
                    status_code=400,
                    code="IDEMPOTENCY_KEY_REQUIRED",
                    message="submitting a turn requires an Idempotency-Key header",
                )
            if body.attachment_refs:
                raise _refuse(
                    status_code=409,
                    code="CAPABILITY_UNAVAILABLE",
                    message="this deployment does not accept attachments",
                )
            agent_profile_id = _selected_agent_profile_id(body.agent_profile_id)
            turn_id = turn_id_for_submission(
                workspace_id=who.workspace_id,
                thread_id=thread_id,
                idempotency_key=idempotency_key,
            )
            # A gate response is captured as its canonical bytes: one act, one message, one digest.
            message = (
                body.message
                if body.message is not None
                else gate_response_message(_gate_response(body))
            )
            digest = content_address(message.encode())
            async with conn_factory() as conn:
                thread = await get_thread(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=thread_id,
                )
                # A thread in another project (or another workspace) is *not found*, not
                # forbidden: a 403 would confirm it exists to somebody who cannot see it.
                if thread is None or thread.project_id != project_id:
                    raise _refuse(
                        status_code=404,
                        code="THREAD_NOT_FOUND",
                        message="no such thread in this project",
                    )
                if thread.status != "active":
                    raise _refuse(
                        status_code=409,
                        code="THREAD_ARCHIVED",
                        message="an archived thread accepts no new turns",
                    )
                project = await get_project(conn, project_id)
                if project is None or project.workspace_id != who.workspace_id:
                    raise _refuse(
                        status_code=404,
                        code="PROJECT_NOT_FOUND",
                        message="no such project in this workspace",
                    )
                context_refs = await _validated_submission_context(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=body.context_refs,
                )
                # P3.4 accept-time visibility: which agent will receive this message. The same
                # one-row read the worker's routing rule performs, taken inside the accept
                # transaction so the 202 can label the pending turn truthfully.
                open_leg = await design_leg_dal.get_open_leg_for_thread(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=thread_id,
                )
                routed_to: Literal["head_of_abm", "design"] = (
                    "design" if open_leg is not None else "head_of_abm"
                )
                # The gate is proved before anything is written — including before the replay read,
                # so a stale or foreign answer never even reaches the capture path.
                gate = (
                    None
                    if body.gate_response is None
                    else await _checked_gate(
                        conn,
                        body.gate_response,
                        who=who,
                        project_id=project_id,
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                )
                # Replay is decided before anything is written: a retry must not persist a second
                # artifact, and a *different* message under a used key must be refused rather than
                # answered with the first one's turn.
                existing = await get_submission(
                    conn,
                    workspace_id=who.workspace_id,
                    turn_id=turn_id,
                )
                if existing is not None:
                    existing_context_refs = await submission_context_refs(
                        conn,
                        workspace_id=who.workspace_id,
                        turn_id=turn_id,
                    )
                    if (
                        existing.message_sha256 != digest
                        or existing.agent_profile_id != agent_profile_id
                        or existing_context_refs != context_refs
                    ):
                        raise _refuse(
                            status_code=409,
                            code="IDEMPOTENCY_CONFLICT",
                            message=(
                                "this idempotency key was already used for a different message"
                            ),
                        )
                    # Still offer the thread's next turn: this heals the rare case where the
                    # first attempt committed the submission and then failed to enqueue.
                    await dispatch_next_thread_turn(
                        conn,
                        workspace_id=who.workspace_id,
                        thread_id=thread_id,
                    )
                    return TurnAcceptedResponse(
                        data=TurnAcceptedWire(
                            turn_id=str(existing.turn_id),
                            thread_id=thread_id,
                            requested_at=existing.requested_at.isoformat(),
                            replayed=True,
                            routed_to=routed_to,
                        )
                    )
                # A gate answer must never become a design prompt (Part-III review finding C,
                # ratified 2026-08-14): while a leg is open, the D1 routing rule would deliver
                # these canonical bytes to the design agent as an instruction, and the gate flow
                # is semantically head-of-abm's — so the route refuses instead of misrouting.
                # Deliberately after the replay read: an answer accepted before the leg opened
                # stays an idempotent replay rather than a retry-visible 409.
                if body.gate_response is not None and open_leg is not None:
                    raise _refuse(
                        status_code=409,
                        code="DESIGN_LEG_OPEN",
                        message="finish the design session before answering this gate",
                    )
                captured = await persist_user_turn(
                    conn,
                    artifacts=artifacts,
                    workspace_id=who.workspace_id,
                    brand_id=project.brand_id,
                    product_id=project.product_id,
                    project_id=project_id,
                    turn_id=turn_id,
                    message=message,
                    client_entity_id=await project_client_entity_id(
                        conn,
                        workspace_id=who.workspace_id,
                        project_id=project_id,
                    ),
                )
                try:
                    submission, _created = await insert_submission(
                        conn,
                        turn_id=turn_id,
                        workspace_id=who.workspace_id,
                        project_id=project_id,
                        thread_id=thread_id,
                        # Ambient authority, never a request field: the principal Lane B
                        # authorized is the only thing that may claim to have submitted a turn.
                        submitted_by_user_id=who.user_id,
                        submitted_via_membership_id=who.membership_id,
                        onboarding_input_id=captured.onboarding_input_id,
                        message_artifact_key=captured.artifact_ref.artifact_key,
                        message_sha256=captured.artifact_ref.sha256,
                        idempotency_key=idempotency_key,
                        context_refs=context_refs,
                        agent_profile_id=agent_profile_id,
                        # P3.1: the design-leg clarification echo (None on non-design turns;
                        # the Home bootstrap path never carries one — a first turn has no
                        # previous design turn).
                        previous_turn_outcome=body.previous_turn_outcome,
                    )
                except SubmissionConflict as exc:
                    raise _refuse(
                        status_code=409,
                        code="IDEMPOTENCY_CONFLICT",
                        message=str(exc),
                    ) from exc
                if gate is not None:
                    response = _gate_response(body)
                    # The receipt is derived from the turn this request just made durable — the
                    # client never supplies it and never could (§3.5).
                    action_ref = derive_turn_action_ref(turn_id)
                    try:
                        await insert_gate_answer(
                            conn,
                            gate_id=gate.gate_id,
                            workspace_id=who.workspace_id,
                            turn_id=turn_id,
                            action_ref=action_ref,
                            decision=response.decision,
                            expected_subject_sha256=response.expected_subject_sha256,
                            decision_payload=(
                                {"revision_request": response.revision_request}
                                if response.revision_request is not None
                                else {}
                            ),
                            selected_option_ref=response.selected_product_id,
                            answered_by_user_id=who.user_id,
                        )
                    except GateAlreadyAnswered as exc:
                        # Only reachable when a concurrent session slipped between the lock and
                        # here; the insert-once primary key is the backstop the check above is not.
                        raise _refuse(
                            status_code=409,
                            code="GATE_ALREADY_ANSWERED",
                            message="this gate has already been answered",
                        ) from exc
                    is_discovery_configuration = (
                        gate.kind == KIND_DIRECTIVE_CONFIRMATION
                        and gate.subject_snapshot.get("subject_kind") == "discovery_configuration"
                    )
                    if response.decision == "approved" and (
                        gate.kind == KIND_PRODUCT_SELECTION
                        or (
                            gate.kind == KIND_DIRECTIVE_CONFIRMATION
                            and not is_discovery_configuration
                        )
                    ):
                        # Human-only, invoked outside the model surface with server-derived
                        # authority. Rejection and revision deliberately confirm nothing: they are
                        # durable records of a decision, and the agent answers them in its turn.
                        tool_name = (
                            "confirm_account_research_directive"
                            if gate.kind == KIND_DIRECTIVE_CONFIRMATION
                            else "confirm_project_product"
                        )
                        tool_body = (
                            {
                                "directive_id": str(gate.subject_snapshot["research_directive_id"]),
                                "expected_sha256": gate.expected_subject_sha256,
                            }
                            if gate.kind == KIND_DIRECTIVE_CONFIRMATION
                            else {
                                "project_id": project_id,
                                "product_id": response.selected_product_id,
                            }
                        )
                        await _invoke(
                            tool_name,
                            tool_body,
                            who=who,
                            idempotency_key=None,
                            action_ref=action_ref,
                            # Derived from (gate, turn) so a retried approval *replays* the same
                            # confirmation instead of being refused as a second one.
                            operation_id=operation_id_from_key(
                                who.workspace_id,
                                f"gate-answer:{gate.gate_id}:{turn_id}",
                            ),
                        )
                    elif gate.kind == KIND_ICP_CONFIRMATION and response.decision == "approved":
                        icp_key = gate.subject_snapshot["icp_key"]
                        version = gate.subject_snapshot["version"]
                        assert isinstance(icp_key, str) and isinstance(version, int)
                        # Same transaction as the immutable answer: either the exact reviewed
                        # draft becomes active and the receipt exists, or neither effect commits.
                        await activate_icp_version(
                            conn,
                            who.workspace_id,
                            icp_key,
                            version,
                        )
                # FI Lane D D3: announce acceptance where it actually happens. The platform
                # accepted this turn *here*, the moment its bytes, its capture record and its
                # submitter became durable — not later, in the worker that eventually claims it. So
                # a client attaching to the stream sees `turn.accepted` even while the turn waits
                # behind another one on the same thread. Emitting a frame is not running a turn:
                # this is an INSERT into a transport table, and the isolation guard still holds
                # (nothing model-shaped is reachable from here).
                #
                # It rides the same transaction as the capture and the submission, so the frame
                # cannot exist for a turn that does not, and the replay path above emits nothing —
                # a second POST under one idempotency key announces nothing new.
                await emit_turn_event(
                    conn,
                    workspace_id=who.workspace_id,
                    project_id=project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    event_type=TurnEventType.TURN_ACCEPTED,
                    payload={
                        "requested_at": submission.requested_at.isoformat(),
                        "source": "route",
                        "kind": "gate_response" if gate is not None else "message",
                    },
                )
                await dispatch_next_thread_turn(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=thread_id,
                )
            return TurnAcceptedResponse(
                data=TurnAcceptedWire(
                    turn_id=str(submission.turn_id),
                    thread_id=thread_id,
                    requested_at=submission.requested_at.isoformat(),
                    replayed=False,
                    routed_to=routed_to,
                )
            )

    return router


def install_chat_surface(
    app: FastAPI,
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    tool_invoker: ToolInvoker,
    principal_resolver: PrincipalResolver | None = None,
    auth_service: PrincipalService | None = None,
    storage: StorageBackend | None = None,
) -> None:
    """Mount the chat router when ``settings.chat_enabled``; otherwise do nothing at all.

    **Exactly one identity source, decided here and never at request time.** In precedence order:

    1. ``auth_service`` — Lane B's authenticated chain. This is production.
    2. ``principal_resolver`` — an injected/deterministic test principal (contract §9).
    3. the guarded development resolver, valid only in ``local_header`` auth mode.

    Wiring (1) and (2)/(3) together is a *configuration contradiction*, not a preference order to
    resolve silently: two identity sources means "who is this request?" has two answers and only
    the dependency-override ordering decides which one wins. So it raises
    :class:`~clue_api.chat.principal.ProductionPrincipalRequired` at composition — the same class
    raised when the surface is enabled outside ``local_header`` mode with no real principal at all.
    A process that would serve chat traffic under a development or ambiguous identity must fail to
    start, not at first request.
    """

    if not settings.chat_enabled:
        return
    if auth_service is not None and principal_resolver is not None:
        raise ProductionPrincipalRequired(
            "the chat surface was given both Lane B's authenticated principal service and an "
            "injected development/test principal resolver; wire exactly one"
        )
    if auth_service is not None:
        app.dependency_overrides[chat_principal_resolver] = bind_authenticated_principal(
            auth_service
        )
    else:
        resolver = (
            principal_resolver
            if principal_resolver is not None
            else build_dev_principal_resolver(settings)
        )
        app.dependency_overrides[chat_principal_resolver] = bind_principal_resolver(resolver)
    app.include_router(
        build_chat_router(
            settings=settings,
            conn_factory=conn_factory,
            tool_invoker=tool_invoker,
            storage=storage,
        )
    )
