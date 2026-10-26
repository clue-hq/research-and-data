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

from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import JsonValue, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.exceptions import HTTPException as StarletteHTTPException

from clue_agents import DomainObjectRef
from clue_api.agent_gate import (
    KIND_CRM_WRITE_PERMISSION,
    KIND_DIRECTIVE_CONFIRMATION,
    KIND_ICP_CONFIRMATION,
    KIND_PRODUCT_SELECTION,
    KIND_PRODUCT_SET_SELECTION,
    AgentGateRow,
    GateAlreadyAnswered,
    get_gate,
    insert_gate_answer,
)
from clue_api.agent_turn_submission import (
    AGENT_REPLY_EXPECTED,
    AGENT_REPLY_NONE,
    SubmissionConflict,
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    submission_attachment_refs,
    submission_context_refs,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.discovery_store import active_discoveries_for_threads, request_discovery_stop
from clue_api.arv2.icp_confirmation import (
    IcpConfirmationStale,
    confirm_icp_document,
    current_icp_document,
    pin_project_icp,
)
from clue_api.arv2.logo_resolution import brandfetch_logo_url
from clue_api.auth_tool_context import tool_context_for_principal
from clue_api.auth_wiring import PrincipalDependency, principal_from_request
from clue_api.chat.attachments import (
    AttachmentReferenceError,
    ValidatedAttachment,
    validated_attachment_refs,
)
from clue_api.chat.composer_context import (
    PRESENTED_REF_TYPES,
    PROJECT_CONVERSATION_AGENT_PROFILE_ID,
    ComposerContextEntity,
    ContextReferenceError,
    context_ref_presentations,
    list_composer_context_entities,
    model_display_name,
    prepare_composer_context_entities,
    project_conversation_model_id,
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
from clue_api.chat.mention_directory import build_mention_directory, search_mention_directory
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
    AttachmentRefRequest,
    ComposerContextEntityWire,
    CreateBlankProjectRequest,
    CreateThreadRequest,
    DesignArtifactAccountWire,
    DesignArtifactListItemWire,
    DesignArtifactListResponse,
    DesignArtifactResponse,
    DesignArtifactWire,
    GateListResponse,
    GateResponseRequest,
    HomeBrandWire,
    HomeComposerCapabilitiesWire,
    HomeProjectRequest,
    HomeResponse,
    HomeWire,
    MentionDirectoryResponse,
    MentionDirectoryWire,
    MentionSearchResponse,
    MentionSearchWire,
    MessageListResponse,
    PageMeta,
    PrepareComposerContextRequest,
    PreparedComposerContextResponse,
    PreparedComposerContextWire,
    ProjectActivityWire,
    ProjectBootstrapProjectWire,
    ProjectBootstrapResponse,
    ProjectBootstrapThreadWire,
    ProjectBootstrapWire,
    ProjectDirectoryItemResponse,
    ProjectDirectoryItemWire,
    ProjectDirectoryResponse,
    ProjectShellResponse,
    ProjectShellWire,
    ResearchTaskListResponse,
    SetProjectArchivedRequest,
    SidebarConversationWire,
    SidebarPageMeta,
    SidebarProjectsResponse,
    SidebarProjectWire,
    SubmitTurnRequest,
    ThreadListResponse,
    ThreadResponse,
    TurnAcceptedResponse,
    TurnAcceptedWire,
    UpdateProjectRequest,
    UpdateThreadRequest,
    gate_response_message,
    gate_wire,
    message_list_response,
    research_task_wire,
    thread_discovery_wire,
    thread_href,
    thread_speaker_wire,
    thread_wire,
    thread_wire_from_references,
)
from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_api.conversation_capture import persist_user_turn, project_client_entity_id
from clue_api.crm import write_answer as crm_write_answer
from clue_api.design_leg_wiring import (
    design_document_card_fields,
    design_legs_for_threads,
    project_design_documents,
    wire_kind,
)
from clue_api.stage0_icp_gate import IcpGateSubjectError, exact_icp_gate_subject
from clue_api.stage0_project_scope import resolve_stage0_project_scope_for_project
from clue_api.thread_store import create_thread, get_thread, thread_id_for_operation
from clue_api.transactional_account_launch import TransactionalToolInvokerFactory
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
    DEFAULT_PROJECT_DIRECTORY_PAGE_SIZE,
    DEFAULT_PROJECT_SIDEBAR_PAGE_SIZE,
    DEFAULT_THREAD_MESSAGE_PAGE_SIZE,
    DEFAULT_THREAD_PAGE_SIZE,
    MAX_PROJECT_DIRECTORY_PAGE_SIZE,
    MAX_PROJECT_SIDEBAR_PAGE_SIZE,
    MAX_THREAD_MESSAGE_PAGE_SIZE,
    MAX_THREAD_PAGE_SIZE,
    InvalidCursorError,
    ProjectDirectoryItemView,
    open_gate_kinds_for_threads,
    project_directory_item,
    project_directory_page,
    project_sidebar_page,
    thread_gates,
    thread_messages,
    thread_research_tasks,
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
    UNTITLED_PROJECT_NAME,
    confirm_project_product_set,
    create_project,
    current_project_product_set,
    get_brand,
    get_project,
    get_project_for_workspace,
    list_brands_for_workspace,
)
from clue_storage import StorageBackend, StorageError, content_address
from clue_toolbelt import IdempotencyConflict, PreconditionFailed, ToolInvoker

if TYPE_CHECKING:  # the refresher's module imports this package's neighbours; type only
    from clue_api.project_library_refresh import ProjectLibraryRefresher

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
    "project_archived": (409, "PROJECT_ARCHIVED"),
    "project_running": (409, "PROJECT_RUNNING"),
    # A system project is a scope anchor the directory never shows, so its refusal has to read
    # like a missing row on this surface — naming it would disclose a project the human never
    # filed. The tool's own reason code stays ``project_system`` for the journal.
    "project_system": (404, "PROJECT_NOT_FOUND"),
    "project_draft": (409, "PROJECT_DRAFT"),
    "project_title_reserved": (422, "PROJECT_TITLE_RESERVED"),
    "brand_not_found": (404, "BRAND_NOT_FOUND"),
}

_HOME_PROJECT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-home-project-bootstrap")
_HOME_SUGGESTIONS = (
    "Find target accounts for our new campaign",
    "Research the buying committee for a target account",
    "Plan a personalized ABM campaign",
)


def _framed(*parts: str) -> str:
    return "".join(f"{len(part)}:{part}" for part in parts)


def _design_artifact_list_item(
    project_id: str, document: Mapping[str, Any], *, settings: Settings | None = None
) -> DesignArtifactListItemWire:
    """One gallery row, carrying only what the document itself records.

    G-H (founder ruling 2026-08-20): the client used to guess a card's channel
    and size — every design artifact claimed to be a 1080x1080 LinkedIn ad.
    Neither is a safe default ("we are not necessarily always making ads"), so
    the document's own artifact type and page size ride the wire and a document
    that records neither yields ``None`` for both. A card then says nothing
    rather than something false; its name is its identity.

    Spec 2026-09-19 §3.8: the document's account rides along too, in the artifacts
    page's own shape, and stays ``None`` when the document names no account.
    """

    fields = design_document_card_fields(document)
    account = (
        DesignArtifactAccountWire(
            id=str(document["account_id"]),
            name=str(document["account_name"]),
            domain=document["account_domain"],
            logo_path=(
                brandfetch_logo_url(
                    str(document["account_domain"]), client_id=settings.brandfetch_client_id
                )
                if settings is not None and document.get("account_domain")
                else None
            ),
            account_entity_id=(
                None
                if document["account_entity_id"] is None
                else str(document["account_entity_id"])
            ),
        )
        if document.get("account_id") is not None
        else None
    )
    return DesignArtifactListItemWire(
        id=str(document["id"]),
        project_id=project_id,
        document_id=str(document["id"]),
        kind=fields["kind"],
        title=str(document["title"]),
        status=str(document["status"]),
        current_version_id=str(document["current_version"]),
        created_at=document["created_at"].isoformat(),
        updated_at=document["updated_at"].isoformat(),
        origin_thread_id=str(document["origin_thread_id"]),
        artifact_type=fields["artifact_type"],
        width_px=fields["width_px"],
        height_px=fields["height_px"],
        account=account,
    )


def _home_project_id(*, workspace_id: str, idempotency_key: str) -> str:
    """The one project identity a workspace-scoped Home act may create."""

    return (
        "prj_"
        + uuid5(
            _HOME_PROJECT_NAMESPACE,
            _framed(workspace_id, idempotency_key),
        ).hex
    )


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


def _is_knowledge_document_gate(gate: AgentGateRow) -> bool:
    """Whether this ICP gate's subject is a knowledge document (``@2``) or a draft spec (``@1``).

    The snapshot is immutable, so the shape a gate was opened with is the shape it is answered in
    forever: an ``@1`` gate written before ARV2 onboarding O6 carries no ``subject_kind`` at all
    and keeps the ``icp_spec`` path unchanged.
    """

    return gate.subject_snapshot.get("subject_kind") == "brand_knowledge_document"


def _crm_selected(response: GateResponseRequest) -> list[UUID]:
    """The ticked changes of a CRM write card answer, each once, in the order ticked."""
    chosen = response.crm_write.selected_write_ids if response.crm_write is not None else []
    return list(dict.fromkeys(chosen))


def _crm_always_allow(response: GateResponseRequest) -> list[str]:
    """The "Always allow" choices of a CRM write card answer, each once."""
    chosen = response.crm_write.always_allow if response.crm_write is not None else []
    return list(dict.fromkeys(scope.strip() for scope in chosen))


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
    # The label follows the configured model (HEAD_OF_ABM_AGENT_MODEL), never a fixed name.
    model_id = project_conversation_model_id()
    name = model_display_name(model_id)
    return (
        AgentProfileOptionWire(
            id=PROJECT_CONVERSATION_AGENT_PROFILE_ID,
            label=name,
            short_label=name,
            description=f"Clue's governed {name} conversation profile",
            model_id=model_id,
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
        account_id=entity.account_id,
        account_name=entity.account_name,
    )


async def _validated_submission_context(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: tuple[Any, ...],
    design_leg_document_ids: tuple[str, ...] = (),
    storage: StorageBackend | None = None,
    project_id: str | None = None,
) -> tuple[DomainObjectRef, ...]:
    requested = tuple(
        DomainObjectRef(
            workspace_id=workspace_id,
            object_type=ref.object_type,
            object_id=ref.object_id,
            version=ref.version,
            note=ref.note,
        )
        for ref in refs
    )
    try:
        return await validated_context_refs(
            conn,
            workspace_id=workspace_id,
            refs=requested,
            design_leg_document_ids=design_leg_document_ids,
            storage=storage,
            project_id=project_id,
        )
    except ContextReferenceError as exc:
        if exc.code == "CONTEXT_REF_LIMIT_EXCEEDED":
            status_code = 422
        elif exc.code == "CAPABILITY_UNAVAILABLE":
            status_code = 503
        elif exc.code == "CONTEXT_REF_NOT_FOUND":
            status_code = 404
        else:
            status_code = 409
        raise _refuse(
            status_code=status_code,
            code=exc.code,
            message=exc.message,
        ) from exc


async def _validated_submission_attachments(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[AttachmentRefRequest],
    settings: Settings,
    storage: StorageBackend | None,
) -> tuple[ValidatedAttachment, ...]:
    """Prove a turn's attachment receipts, or refuse the turn. Never a partial acceptance."""

    if refs and storage is None:
        raise _refuse(
            status_code=503,
            code="CAPABILITY_UNAVAILABLE",
            message="this deployment has no artifact storage for attachments",
        )
    try:
        return await validated_attachment_refs(
            conn,
            workspace_id=workspace_id,
            refs=refs,
            settings=settings,
        )
    except AttachmentReferenceError as exc:
        status_code = {
            "ATTACHMENT_NOT_FOUND": 404,
            "ATTACHMENT_LIMIT_EXCEEDED": 422,
            "ATTACHMENT_DUPLICATE": 422,
        }.get(exc.code, 409)
        raise _refuse(status_code=status_code, code=exc.code, message=exc.message) from exc


def _composer_capabilities(*, storage_available: bool) -> HomeComposerCapabilitiesWire:
    """Attachments are offered exactly when this deployment can durably hold their bytes."""

    return HomeComposerCapabilitiesWire(
        context_refs=True,
        attachments=storage_available,
        agent_profile_selection=True,
    )


def _bound_connection_factory(conn: AsyncConnection) -> ConnFactory:
    """Adapt the route's open transaction to the standard connection-factory seam."""

    @asynccontextmanager
    async def bound() -> AsyncIterator[AsyncConnection]:
        yield conn

    return bound


def build_chat_router(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    tool_invoker: ToolInvoker,
    storage: StorageBackend | None = None,
    transactional_tool_invoker_factory: TransactionalToolInvokerFactory | None = None,
    project_library: ProjectLibraryRefresher | None = None,
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
        invoker: ToolInvoker | None = None,
        invocation_conn_factory: ConnFactory | None = None,
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
            conn_factory=(
                invocation_conn_factory if invocation_conn_factory is not None else conn_factory
            ),
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
            result = await (invoker if invoker is not None else tool_invoker).invoke(
                name, body, ctx, idempotency_key=idempotency_key
            )
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

    async def _directory_items(
        workspace_id: str, views: Sequence[ProjectDirectoryItemView]
    ) -> tuple[ProjectDirectoryItemWire, ...]:
        """Dress a page of directory rows with their live conversation activity.

        Two queries for the whole page, not two per card: the directory read already carried each
        project's active thread ids, so the badges are counted over one gate read and one
        running-turn read for the page.
        """

        thread_ids = tuple(t for view in views for t in view.thread_ids)
        open_gates = await open_gate_kinds_for_threads(
            workspace_id=workspace_id,
            thread_ids=thread_ids,
            conn_factory=conn_factory,
        )
        busy = await threads_running(
            workspace_id=workspace_id,
            thread_ids=thread_ids,
            conn_factory=conn_factory,
        )
        return tuple(
            ProjectDirectoryItemWire(
                id=view.project_id,
                title=view.title,
                description=view.description,
                href=f"/projects/{view.project_id}",
                status=view.status,
                pinned=view.pinned,
                brand_id=view.brand_id,
                product_id=view.product_id,
                created_at=view.created_at.isoformat(),
                updated_at=view.updated_at.isoformat(),
                archived_at=(None if view.archived_at is None else view.archived_at.isoformat()),
                activity=ProjectActivityWire(
                    chats=view.chat_count,
                    running=sum(1 for t in view.thread_ids if t in busy),
                    needs_input=sum(1 for t in view.thread_ids if open_gates.get(t)),
                ),
            )
            for view in views
        )

    async def _directory_item_or_404(
        workspace_id: str, project_id: str
    ) -> ProjectDirectoryItemWire:
        """The one directory row, or the same not-found sentence the tools use.

        The read applies the directory's lens, so a system anchor, a draft, and another tenant's
        project are all 404 here — a caller cannot reach by id what the listing hides.
        """

        view = await project_directory_item(
            workspace_id=workspace_id, project_id=project_id, conn_factory=conn_factory
        )
        if view is None:
            raise _refuse(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="no such project in this workspace",
            )
        return (await _directory_items(workspace_id, (view,)))[0]

    # --- Home bootstrap ------------------------------------------------------------------------

    @router.get("/home")
    async def home_route(who: PrincipalDep) -> HomeResponse:
        """Return only the real, workspace-scoped inputs the Home composer may use.

        Context entries come from Lane C's governed workspace reads. The one advertised profile is
        the promoted Head-of-ABM Grok 4.6 profile; attachments are offered exactly when this
        deployment composed an artifact store to hold the uploaded bytes.
        """

        _require(who, PERMISSION_PROJECT_READ)
        async with conn_factory() as conn:
            brands = await list_brands_for_workspace(conn, who.workspace_id)
            context_entities = await list_composer_context_entities(
                conn,
                settings=settings,
                workspace_id=who.workspace_id,
            )
        return HomeResponse(
            data=HomeWire(
                brands=tuple(HomeBrandWire(id=brand.brand_id, name=brand.name) for brand in brands),
                default_brand_id=brands[0].brand_id if len(brands) == 1 else None,
                context_entities=tuple(_context_entity_wire(entity) for entity in context_entities),
                agent_profiles=_agent_profile_options(),
                default_agent_profile_id=PROJECT_CONVERSATION_AGENT_PROFILE_ID,
                composer_capabilities=_composer_capabilities(storage_available=storage is not None),
                suggestions=_HOME_SUGGESTIONS,
            )
        )

    # --- @-mention directory (2026-10-05) -------------------------------------------------------

    @router.get("/mention-directory", response_model=None)
    async def mention_directory_route(
        who: PrincipalDep,
        if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
        project_id: Annotated[str | None, Query()] = None,
    ) -> Response | MentionDirectoryResponse:
        """Every account and committee contact the @ tagger may offer, names and ids only.

        The browser loads it once per session and re-checks it with ``If-None-Match``: a
        matching ETag is a bodiless 304. ``project_id`` puts that project's accounts first.
        """

        _require(who, PERMISSION_PROJECT_READ)
        async with conn_factory() as conn:
            if project_id is not None:
                project = await get_project_for_workspace(
                    conn, workspace_id=who.workspace_id, project_id=project_id
                )
                if project is None or project.kind == "system":
                    raise _refuse(
                        status_code=404,
                        code="PROJECT_NOT_FOUND",
                        message="no such project in this workspace",
                    )
            directory = await build_mention_directory(
                conn,
                workspace_id=who.workspace_id,
                project_id=project_id,
                settings=settings,
                max_entries=settings.mention_directory_max_entries,
            )
        headers = {"ETag": directory.etag, "Cache-Control": "private, no-cache"}
        if if_none_match is not None and directory.etag in {
            tag.strip() for tag in if_none_match.split(",")
        }:
            return Response(status_code=304, headers=headers)
        body = MentionDirectoryResponse(
            data=MentionDirectoryWire(
                entities=tuple(_context_entity_wire(entity) for entity in directory.entities),
                complete=directory.complete,
            )
        )
        return Response(
            content=body.model_dump_json(),
            media_type="application/json",
            headers=headers,
        )

    @router.get("/mention-directory/search")
    async def mention_directory_search_route(
        who: PrincipalDep,
        q: Annotated[str, Query(min_length=2, max_length=60)],
    ) -> MentionSearchResponse:
        """Server search, for workspaces whose directory is too large to load whole."""

        _require(who, PERMISSION_PROJECT_READ)
        async with conn_factory() as conn:
            found = await search_mention_directory(
                conn, workspace_id=who.workspace_id, query=q, settings=settings
            )
        return MentionSearchResponse(
            data=MentionSearchWire(entities=tuple(_context_entity_wire(entity) for entity in found))
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
                    storage=storage,
                )
                attachments = await _validated_submission_attachments(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=body.attachment_refs,
                    settings=settings,
                    storage=storage,
                )

                project = await get_project(conn, project_id)
                if project is None:
                    project = await create_project(
                        conn,
                        project_id=project_id,
                        workspace_id=who.workspace_id,
                        brand_id=body.brand_id,
                        name=UNTITLED_PROJECT_NAME,
                        status="active",
                    )
                elif (
                    project.workspace_id != who.workspace_id
                    or project.brand_id != body.brand_id
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
                    title=None,
                    created_by_user_id=who.user_id,
                    created_via_membership_id=who.membership_id,
                )
                # The title is no longer part of the replay identity: it is born null, generated
                # after the first completed turn, and may have been renamed by hand since (spec
                # 2026-09-18-conversation-naming-design §4.6). The message digest on the
                # submission is what proves the request is the same.
                if thread.project_id != project_id:
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
                    existing_attachments = await submission_attachment_refs(
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
                        or tuple(item.upload_id for item in existing_attachments)
                        != tuple(ref.upload_id for ref in body.attachment_refs)
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
                            attachment_refs=attachments,
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
                        title=thread.title,
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

    # Registered before ``GET /projects/{project_id}``: Starlette matches in registration order,
    # so a literal path that a parametrised sibling would also match has to come first (the
    # ``/projects/sidebar`` route below already relies on this).
    @router.get("/projects")
    async def project_directory_route(
        who: PrincipalDep,
        status: Annotated[Literal["active", "archived"], Query()] = "active",
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_PROJECT_DIRECTORY_PAGE_SIZE),
        ] = DEFAULT_PROJECT_DIRECTORY_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
    ) -> ProjectDirectoryResponse:
        """One keyset page of this workspace's marketing projects, pinned first."""

        _require(who, PERMISSION_PROJECT_READ)
        try:
            page = await project_directory_page(
                workspace_id=who.workspace_id,
                status=status,
                limit=limit,
                cursor=cursor,
                conn_factory=conn_factory,
            )
        except InvalidCursorError as exc:
            raise _refuse(status_code=422, code="INVALID_CURSOR", message=str(exc)) from exc
        return ProjectDirectoryResponse(
            data=await _directory_items(who.workspace_id, page.items),
            meta=SidebarPageMeta(next_cursor=page.next_cursor),
        )

    @router.post("/projects/blank", status_code=201)
    async def create_blank_project_route(
        body: CreateBlankProjectRequest,
        who: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ProjectDirectoryItemResponse:
        """Create an empty project the human named, with no thread and no turn.

        The Idempotency-Key is **required**, as it is for the Home bootstrap: the project id is
        derived from it, so a retried create returns the same project instead of a second one.
        """

        _require(who, PERMISSION_PROJECT_WRITE)
        if not idempotency_key or not idempotency_key.strip():
            raise _refuse(
                status_code=400,
                code="IDEMPOTENCY_KEY_REQUIRED",
                message="creating a project requires an Idempotency-Key header",
            )
        key = idempotency_key.strip()
        project_id = (
            "prj_" + uuid5(_HOME_PROJECT_NAMESPACE, f"{who.workspace_id}:blank:{key}").hex[:24]
        )
        references = await _invoke(
            "create_project",
            {
                "project_id": project_id,
                "brand_id": body.brand_id,
                "title": body.title,
                "description": body.description,
            },
            who=who,
            idempotency_key=f"blank-project:{key}",
        )
        return ProjectDirectoryItemResponse(
            data=await _directory_item_or_404(who.workspace_id, str(references["id"]))
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
                    pinned=project.pinned,
                    updated_at=project.updated_at.isoformat(),
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

    @router.get("/projects/{project_id}/design-artifacts")
    async def design_artifact_list_route(
        project_id: str,
        who: PrincipalDep,
    ) -> DesignArtifactListResponse:
        """The project's design-artifact feed — the gallery's list read (leg-derived v1).

        The document row carries a workspace, not a project, so the project binding is the
        design **leg**: the documents named by the legs of this project's threads. A
        document no leg names belongs to no project and is not listed (the ratified v1
        gap). Like the single-artifact sibling below, the project and the documents are
        workspace-scoped fail-closed reads, and the artifact id IS the design-document id.

        Kind-aware since AD2.1: web documents and scene (ad) documents both list, each
        carrying its own ``kind`` — the same mapping the single-artifact read applies.
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
            documents = await project_design_documents(
                conn,
                workspace_id=who.workspace_id,
                project_id=project_id,
            )
        return DesignArtifactListResponse(
            data=tuple(
                _design_artifact_list_item(project_id, document, settings=settings)
                for document in documents
            )
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
                kind=wire_kind(str(document["doc_kind"])),
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
                    settings=settings,
                    workspace_id=who.workspace_id,
                )
            )
        # A system project is the invisible per-brand scope anchor, not a project the human filed:
        # the directory never lists it, so the shell must not serve it either.
        if project is None or project.kind == "system":
            raise _refuse(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="no such project in this workspace",
            )
        return ProjectShellResponse(
            data=ProjectShellWire(
                id=project.project_id,
                title=project.name,
                description=project.description,
                brand_id=project.brand_id,
                product_id=project.product_id,
                status=project.status,
                pinned=project.pinned,
                created_at=project.created_at.isoformat(),
                updated_at=project.updated_at.isoformat(),
                archived_at=(
                    None if project.archived_at is None else project.archived_at.isoformat()
                ),
                context_entities=tuple(_context_entity_wire(entity) for entity in context_entities),
                agent_profiles=_agent_profile_options(),
                default_agent_profile_id=PROJECT_CONVERSATION_AGENT_PROFILE_ID,
                composer_capabilities=_composer_capabilities(storage_available=storage is not None),
            )
        )

    @router.patch("/projects/{project_id}")
    async def update_project_route(
        project_id: str,
        body: UpdateProjectRequest,
        who: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ProjectDirectoryItemResponse:
        """Rename, re-describe and/or pin one project.

        Two independent governed mutations dispatched from one body, the way
        ``update_thread_route`` does it: any label edit — title, objective, or both — is one
        ``update_project_details@1`` call, and the pin toggle is always its own
        ``set_project_pinned@1`` call. They cannot share one call, because pinning an archived
        project is allowed and relabelling one is not.

        The route dispatches; it decides nothing. Every refusal here is the tool's:
        ``update_project_details@1`` is what refuses ``project_archived`` (409) and
        ``project_system`` (a 404 on this surface), and no status is inspected in this function.
        The one read it does make is the current directory row, because a title-only edit must
        keep the objective the human wrote and a description-only edit must keep the title —
        ``update_project_details@1`` takes both labels together, so whichever one the body omits
        has to be supplied from the row. ``_directory_item_or_404`` applies the directory's lens,
        so that read also 404s a system anchor, a draft, or another tenant's project.

        ``rename_project@1`` stays registered for replay and for the sidebar's contract history;
        this surface no longer calls it.
        """

        _require(who, PERMISSION_PROJECT_WRITE)
        if body.title is not None or body.description is not None:
            current = await _directory_item_or_404(who.workspace_id, project_id)
            await _invoke(
                "update_project_details",
                {
                    "project_id": project_id,
                    "title": body.title if body.title is not None else current.title,
                    "description": (
                        body.description if body.description is not None else current.description
                    ),
                },
                who=who,
                idempotency_key=(None if idempotency_key is None else f"{idempotency_key}:details"),
            )
        if body.pinned is not None:
            await _invoke(
                "set_project_pinned",
                {"project_id": project_id, "pinned": body.pinned},
                who=who,
                idempotency_key=(None if idempotency_key is None else f"{idempotency_key}:pinned"),
            )
        return ProjectDirectoryItemResponse(
            data=await _directory_item_or_404(who.workspace_id, project_id)
        )

    @router.post("/projects/{project_id}/archive")
    async def set_project_archived_route(
        project_id: str,
        body: SetProjectArchivedRequest,
        who: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ProjectDirectoryItemResponse:
        """Archive a project or restore it. Reversible, and never a delete."""

        _require(who, PERMISSION_PROJECT_WRITE)
        await _invoke(
            "set_project_archived",
            {"project_id": project_id, "archived": body.archived},
            who=who,
            idempotency_key=idempotency_key,
        )
        return ProjectDirectoryItemResponse(
            data=await _directory_item_or_404(who.workspace_id, project_id)
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
                    note=ref.note,
                )
                for ref in body.context_refs
            )
            try:
                prepared = await prepare_composer_context_entities(
                    conn,
                    settings=settings,
                    workspace_id=who.workspace_id,
                    refs=requested,
                    project_id=project_id,
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
        # The fourth: the discovery holding a thread (spec 2026-09-30 §5), so the composer can say
        # why the thread is busy and offer Stop while the run still searches.
        async with conn_factory() as conn:
            discoveries = await active_discoveries_for_threads(
                conn, workspace_id=who.workspace_id, thread_ids=thread_ids
            )
        return ThreadListResponse(
            data=tuple(
                thread_wire(
                    item,
                    open_gate_kinds=open_gates.get(item.thread_id, ()),
                    running=item.thread_id in busy,
                    speaker=thread_speaker_wire(open_legs.get(item.thread_id)),
                    discovery=thread_discovery_wire(discoveries.get(item.thread_id)),
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

    # --- discovery Stop (spec 2026-09-30 §4) ------------------------------------------------

    @router.post("/projects/{project_id}/discovery-runs/{run_id}/stop")
    async def stop_discovery_run_route(
        project_id: str,
        run_id: UUID,
        who: PrincipalDep,
    ) -> dict[str, JsonValue]:
        """Record a human's Stop on this project's running discovery.

        The request is recorded, not performed: the discovery driver reads it between steps,
        cancels its current search, keeps what it already verified and ends the run ``stopped``
        through its normal end (the wake turn, then the release). Pressing it again changes
        nothing. A run that is not this workspace's and this project's is not found.
        """

        _require(who, PERMISSION_THREAD_WRITE)
        async with conn_factory() as conn:
            run = await request_discovery_stop(
                conn, workspace_id=who.workspace_id, project_id=project_id, run_id=run_id
            )
        if run is None:
            raise _refuse(
                status_code=404,
                code="DISCOVERY_RUN_NOT_FOUND",
                message="no such discovery run in this project",
            )
        return {
            "data": {
                "run_id": str(run.run_id),
                "stop_requested": run.stop_requested_at is not None,
            }
        }

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
        all_refs = tuple(ref for item in page.items for ref in item.refs)
        has_presented = any(ref.object_type in PRESENTED_REF_TYPES for ref in all_refs)
        if include is None and not has_presented:
            return message_list_response(page, thread_id=thread_id)
        async with conn_factory() as conn:
            presentations = await context_ref_presentations(
                conn,
                workspace_id=who.workspace_id,
                refs=all_refs,
                storage=storage,
            )
            bodies = None
            if include is not None:
                assert storage is not None  # guarded above: artifacts exists iff storage does
                bodies = await hydrate_message_bodies(
                    conn,
                    storage=storage,
                    workspace_id=who.workspace_id,
                    references=tuple(
                        (item.body_artifact_key, item.body_sha256) for item in page.items
                    ),
                )
        return message_list_response(
            page,
            thread_id=thread_id,
            bodies=bodies,
            ref_presentations=presentations,
        )

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

    @router.get("/projects/{project_id}/threads/{thread_id}/research-tasks")
    async def list_research_tasks_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
    ) -> ResearchTaskListResponse:
        """Every research run this thread launched, counted off its jobs, right now.

        The turn's SSE stream emits one ``task`` snapshot at turn close and then ends — but the
        fleet works for minutes afterwards, so without this the progress card is frozen at the last
        frame. This is what a live card polls: the same task shape the stream emitted (it is built
        by the same :func:`~clue_api.chat.turn_parts.task_part_from_run`, so the two merge as one
        card), plus the ``revision`` the transcript reducer merges on and the per-field progress
        inside the accounts still running.

        **Unpaginated, and never a not-found for a thread that launched nothing.** The list is
        bounded by the number of runs a conversation authorized, and the card asks *every* thread —
        so "no launches" has to be an empty list. A 404 here would make the poller treat an
        ordinary conversation as a broken one.

        Scoped exactly like its neighbours: a thread in another project or another workspace is
        **not found**, never forbidden, because a 403 would confirm to somebody who cannot see it
        that it exists.
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
        views = await thread_research_tasks(
            workspace_id=who.workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            conn_factory=conn_factory,
        )
        return ResearchTaskListResponse(
            tasks=tuple(research_task_wire(view, workspace_id=who.workspace_id) for view in views)
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
            KIND_CRM_WRITE_PERMISSION,
            KIND_DIRECTIVE_CONFIRMATION,
            KIND_ICP_CONFIRMATION,
            KIND_PRODUCT_SELECTION,
            KIND_PRODUCT_SET_SELECTION,
        }:
            raise _refuse(
                status_code=422,
                code="GATE_KIND_UNSUPPORTED",
                message=f"this surface cannot answer a {view.gate.kind} gate",
            )
        if response.crm_write is not None and view.gate.kind != KIND_CRM_WRITE_PERMISSION:
            raise _refuse(
                status_code=422,
                code="GATE_CRM_WRITE_UNEXPECTED",
                message="only a CRM write permission card takes ticked changes",
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
        # valid turn of their own still may not answer somebody else's gate. The one exception is
        # a CRM write permission card, which any member of the workspace answers (R-6.8); the
        # principal is a member here by construction, holding ``gate.respond``.
        if (
            view.gate.addressee_user_id != who.user_id
            and view.gate.kind != KIND_CRM_WRITE_PERMISSION
        ):
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
            if (
                response.selected_product_id is not None
                or response.selected_product_ids is not None
            ):
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
            if view.answer is None and _is_knowledge_document_gate(view.gate):
                # ARV2 onboarding O6: the subject is a `brand_knowledge_document`, so the check is
                # "is the brand's current ICP document for this key still the exact one the human
                # was shown?" — same document, same bytes. A newer proposal published at that path
                # since the gate opened is precisely what must refuse.
                snapshot = view.gate.subject_snapshot
                assert storage is not None  # the submit route exists only when storage does
                brand_id = snapshot.get("brand_id")
                icp_key = snapshot.get("icp_key")
                if not isinstance(brand_id, str) or not isinstance(icp_key, str):
                    raise _refuse(
                        status_code=409,
                        code="GATE_SUBJECT_STALE",
                        message="the durable gate does not name a canonical ICP document",
                    )
                current = await current_icp_document(
                    conn,
                    storage,
                    workspace_id=who.workspace_id,
                    brand_id=brand_id,
                    icp_key=icp_key,
                    # Same scope the gate was opened in, so a project-local variant revalidates
                    # against itself rather than against the brand's document at that path.
                    project_id=project_id,
                )
                if (
                    current is None
                    or str(current.document_id) != snapshot.get("document_id")
                    or current.artifact_sha256 != snapshot.get("artifact_sha256")
                ):
                    raise _refuse(
                        status_code=409,
                        code="GATE_SUBJECT_STALE",
                        message="the current ICP document differs from the reviewed one",
                    )
            elif view.answer is None:
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
            if response.selected_product_ids is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_UNEXPECTED",
                    message="this question takes one product, not a set",
                )
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
        elif view.gate.kind == KIND_CRM_WRITE_PERMISSION:
            if (
                response.revision_request is not None
                or response.selected_product_id is not None
                or response.selected_product_ids is not None
            ):
                raise _refuse(
                    status_code=422,
                    code="GATE_ANSWER_UNEXPECTED",
                    message="a CRM write card is answered with its ticked changes only",
                )
            # A retried click of the same answering turn replays without re-proving: its proposal
            # has moved on (queued or declined) by its own answer.
            if view.answer is None:
                try:
                    await crm_write_answer.check_answer(
                        conn,
                        view.gate,
                        decision=response.decision,
                        selected_write_ids=_crm_selected(response),
                        always_allow=_crm_always_allow(response),
                        answered_by_user_id=who.user_id,
                    )
                except crm_write_answer.CrmAnswerRefused as exc:
                    raise _refuse(
                        status_code=exc.status_code, code=exc.code, message=str(exc)
                    ) from exc
        elif view.gate.kind == KIND_PRODUCT_SET_SELECTION:
            # A project targets a SET of products (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3, ruling
            # P1). The same rules as the single-valued gate, applied per element, plus the one this
            # shape adds: the same product cannot be chosen twice.
            if response.selected_product_id is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_UNEXPECTED",
                    message="this question takes a set of products, not one",
                )
            # The durable answer for this kind carries its choices and nothing else (the answer
            # trigger enforces it), so there is nowhere to record revision text.
            if response.revision_request is not None:
                raise _refuse(
                    status_code=422,
                    code="GATE_REVISION_REQUEST_UNEXPECTED",
                    message="a product-set question does not accept revision text",
                )
            chosen = list(response.selected_product_ids or ())
            if response.decision == "approved" and not chosen:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_REQUIRED",
                    message="select at least one product from the presented catalog",
                )
            if response.decision != "approved" and chosen:
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_UNEXPECTED",
                    message="a rejected or revised product question does not accept a choice",
                )
            if len(set(chosen)) != len(chosen):
                raise _refuse(
                    status_code=422,
                    code="GATE_PRODUCT_DUPLICATE",
                    message="a product can only be chosen once",
                )
            # An archived candidate is *presented* (the human may be looking at a set that
            # includes it) but cannot be chosen, so the allowed set is narrower than the snapshot.
            snapshot_products = view.gate.subject_snapshot.get("products")
            selectable = (
                {
                    str(item["product_id"])
                    for item in snapshot_products
                    if isinstance(item, dict)
                    and isinstance(item.get("product_id"), str)
                    and item.get("status") != "archived"
                }
                if isinstance(snapshot_products, list)
                else set()
            )
            if not set(chosen) <= selectable:
                raise _refuse(
                    status_code=409,
                    code="GATE_PRODUCT_STALE",
                    message="a chosen product was not selectable in the presented catalog",
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
            if (
                response.selected_product_id is not None
                or response.selected_product_ids is not None
            ):
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
            # Set when this request pins this project's ICP below. The pin changes which version
            # the library serves at ``audience/icp-<key>.md``, so the tree is refreshed once the
            # transaction that wrote the pin has committed. A replayed answer pins nothing and
            # returns from inside the transaction, so it refreshes nothing either.
            pinned_project_icp = False
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
                requested_context_refs = tuple(
                    DomainObjectRef(
                        workspace_id=who.workspace_id,
                        object_type=ref.object_type,
                        object_id=ref.object_id,
                        version=ref.version,
                        note=ref.note,
                    )
                    for ref in body.context_refs
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
                # A CRM write card's answer also tells the agent, in words, what was allowed. The
                # sentence is derived from the immutable card, so a retry captures the same bytes.
                if gate is not None and gate.kind == KIND_CRM_WRITE_PERMISSION:
                    crm_response = _gate_response(body)
                    message = gate_response_message(
                        crm_response,
                        crm_write_summary=await crm_write_answer.answer_summary(
                            conn,
                            gate,
                            decision=crm_response.decision,
                            selected_write_ids=_crm_selected(crm_response),
                            always_allow=_crm_always_allow(crm_response),
                        ),
                    )
                    digest = content_address(message.encode())
                # R-11.3/R-11.6: answering a CRM write card starts no agent turn. Allow hands the
                # changes to the background sender, whose own wake turn reports the results; Don't
                # allow reaches the agent as a context line on its next turn. The answer is still
                # recorded as a submission — the receipt the gate answer points at and the anchor a
                # retried click replays on — marked as one the agent never replies to.
                agent_reply: Literal["expected", "none"] = (
                    AGENT_REPLY_NONE
                    if gate is not None and gate.kind == KIND_CRM_WRITE_PERMISSION
                    else AGENT_REPLY_EXPECTED
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
                    existing_attachments = await submission_attachment_refs(
                        conn,
                        workspace_id=who.workspace_id,
                        turn_id=turn_id,
                    )
                    if (
                        existing.message_sha256 != digest
                        or existing.agent_profile_id != agent_profile_id
                        or existing_context_refs != requested_context_refs
                        or tuple(item.upload_id for item in existing_attachments)
                        != tuple(ref.upload_id for ref in body.attachment_refs)
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
                            agent_reply=(
                                AGENT_REPLY_NONE
                                if existing.agent_reply == AGENT_REPLY_NONE
                                else AGENT_REPLY_EXPECTED
                            ),
                        )
                    )
                # Mutable domain state is checked only for a NEW submission. An
                # idempotent replay above is proved from its immutable receipt,
                # so a design document advancing after acceptance cannot make
                # the accepted turn unreplayable.
                #
                # Spec §3.7: one leg holds many documents, so the composer's design tags are
                # validated against the leg's whole SET. A leg born before the join table was
                # written falls back to its own pinned document.
                design_leg_document_ids: tuple[str, ...] = ()
                if open_leg is not None:
                    design_leg_document_ids = tuple(
                        str(row["document_id"])
                        for row in await design_leg_dal.list_leg_documents(
                            conn,
                            workspace_id=who.workspace_id,
                            leg_id=str(open_leg["id"]),
                        )
                    )
                    if not design_leg_document_ids and open_leg.get("document_id"):
                        design_leg_document_ids = (str(open_leg["document_id"]),)
                context_refs = await _validated_submission_context(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=body.context_refs,
                    design_leg_document_ids=design_leg_document_ids,
                    storage=storage,
                    project_id=project_id,
                )
                attachments = await _validated_submission_attachments(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=body.attachment_refs,
                    settings=settings,
                    storage=storage,
                )
                # Founder ruling 2026-08-19 (Slice B): on a budget-controls-disabled deployment,
                # approving a directive-confirmation gate atomically confirms AND launches via
                # ``launch_selected_account_research@1``. That tool's account authority is the
                # approving turn's durable context refs, so the capture records the exact account
                # set the gate froze at open — the approval click genuinely references those
                # accounts. Injected only when the turn carries no refs of its own, and only for
                # the approval decision this authority serves; decided before the replay read so
                # a retried approval replays against identical refs.
                if (
                    gate is not None
                    and gate.kind == KIND_DIRECTIVE_CONFIRMATION
                    and gate.subject_snapshot.get("subject_kind") != "discovery_configuration"
                    and not settings.budget_controls_enabled
                    and not context_refs
                    and body.gate_response is not None
                    and _gate_response(body).decision == "approved"
                ):
                    snapshot_account_ids = gate.subject_snapshot.get("account_entity_ids")
                    if isinstance(snapshot_account_ids, list):
                        context_refs = tuple(
                            DomainObjectRef(
                                workspace_id=who.workspace_id,
                                object_type="account",
                                object_id=str(value),
                                version=None,
                            )
                            for value in snapshot_account_ids
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
                    allow_empty_reference_turn=bool(context_refs),
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
                        attachment_refs=attachments,
                        agent_profile_id=agent_profile_id,
                        # P3.1: the design-leg clarification echo (None on non-design turns;
                        # the Home bootstrap path never carries one — a first turn has no
                        # previous design turn).
                        previous_turn_outcome=body.previous_turn_outcome,
                        agent_reply=agent_reply,
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
                    # A set-valued answer names its choices in the payload — the single
                    # ``selected_option_ref`` column cannot hold a set, and the answer trigger
                    # refuses one on this kind.
                    if gate.kind == KIND_PRODUCT_SET_SELECTION:
                        decision_payload: dict[str, JsonValue] = (
                            {"selected_option_refs": list(response.selected_product_ids)}
                            if response.selected_product_ids is not None
                            else {}
                        )
                        selected_option_ref = None
                    elif gate.kind == KIND_CRM_WRITE_PERMISSION:
                        # The answer trigger takes exactly these two arrays for an approval and
                        # nothing for a refusal.
                        decision_payload = (
                            {
                                "selected_write_ids": [
                                    str(write_id) for write_id in _crm_selected(response)
                                ],
                                "always_allow": list(_crm_always_allow(response)),
                            }
                            if response.decision == "approved"
                            else {}
                        )
                        selected_option_ref = None
                    else:
                        decision_payload = (
                            {"revision_request": response.revision_request}
                            if response.revision_request is not None
                            else {}
                        )
                        selected_option_ref = response.selected_product_id
                    try:
                        await insert_gate_answer(
                            conn,
                            gate_id=gate.gate_id,
                            workspace_id=who.workspace_id,
                            turn_id=turn_id,
                            action_ref=action_ref,
                            decision=response.decision,
                            expected_subject_sha256=response.expected_subject_sha256,
                            decision_payload=decision_payload,
                            selected_option_ref=selected_option_ref,
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
                        #
                        # Founder ruling 2026-08-19 (Slice B): with budget controls DISABLED, the
                        # approval of a directive-confirmation gate is one atomic act — confirm
                        # AND launch — through ``launch_selected_account_research@1``, whose own
                        # resolve re-derives the human receipt from this turn, requires the exact
                        # gate-frozen account set (captured above as this turn's context refs),
                        # confirms the draft, computes the estimate server-side, and launches.
                        # Budget-controls-enabled deployments keep the confirm-only gate
                        # unchanged; the tool itself refuses the direct path there.
                        directive_gate = gate.kind == KIND_DIRECTIVE_CONFIRMATION
                        atomic_launch = directive_gate and not settings.budget_controls_enabled
                        if atomic_launch:
                            tool_name = "launch_selected_account_research"
                            tool_body: dict[str, Any] = {
                                "project_run_id": str(gate.subject_snapshot["project_run_id"]),
                                "research_directive_id": str(
                                    gate.subject_snapshot["research_directive_id"]
                                ),
                                "account_entity_ids": [ref.object_id for ref in context_refs],
                                "source_turn_ref": action_ref,
                            }
                        else:
                            tool_name = (
                                "confirm_account_research_directive"
                                if directive_gate
                                else "confirm_project_product"
                            )
                            tool_body = (
                                {
                                    "directive_id": str(
                                        gate.subject_snapshot["research_directive_id"]
                                    ),
                                    "expected_sha256": gate.expected_subject_sha256,
                                }
                                if directive_gate
                                else {
                                    "project_id": project_id,
                                    "product_id": str(response.selected_product_id),
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
                            # The budget-disabled approval is one database act. Its narrow
                            # request-scoped invoker binds the launch tool, journal, directive
                            # confirmation, fleet rows, and queue offer to this exact transaction.
                            # Other gate tools keep using the process toolbelt unchanged.
                            invoker=(
                                transactional_tool_invoker_factory(_bound_connection_factory(conn))
                                if atomic_launch and transactional_tool_invoker_factory is not None
                                else None
                            ),
                            invocation_conn_factory=(
                                _bound_connection_factory(conn)
                                if atomic_launch and transactional_tool_invoker_factory is not None
                                else None
                            ),
                        )
                    elif gate.kind == KIND_CRM_WRITE_PERMISSION:
                        # Same transaction as the immutable answer: Allow queues the ticked changes,
                        # grants each "Always allow" and offers the write executor; Don't allow
                        # declines the whole proposal. Either both commit or neither does.
                        await crm_write_answer.apply_answer(
                            conn,
                            gate,
                            decision=response.decision,
                            selected_write_ids=_crm_selected(response),
                            always_allow=_crm_always_allow(response),
                            answered_by_user_id=who.user_id,
                        )
                    elif (
                        gate.kind == KIND_PRODUCT_SET_SELECTION and response.decision == "approved"
                    ):
                        # Human-only and tool-free: confirming a set is one spine write with
                        # server-derived authority (workspace, project, the answering gate and the
                        # ambient user), in the same transaction as the immutable answer. Either
                        # both effects commit or neither does.
                        if (
                            await confirm_project_product_set(
                                conn,
                                workspace_id=who.workspace_id,
                                project_id=project_id,
                                product_ids=list(response.selected_product_ids or ()),
                                gate_id=gate.gate_id,
                                confirmed_by_user_id=who.user_id,
                            )
                            is None
                        ):
                            raise _refuse(
                                status_code=409,
                                code="GATE_SUBJECT_STALE",
                                message=(
                                    "a chosen product no longer belongs to this project's brand"
                                ),
                            )
                    elif (
                        gate.kind == KIND_ICP_CONFIRMATION
                        and response.decision == "approved"
                        and _is_knowledge_document_gate(gate)
                    ):
                        # ARV2 onboarding O6: approving a knowledge-document ICP mints the
                        # `confirmed` version of that same document path — human-only and
                        # tool-free, with server-derived authority (the workspace, the project,
                        # the ambient user and the gate's own digest), in the same transaction as
                        # the immutable answer. Either both effects commit or neither does.
                        assert storage is not None  # the submit route exists only when storage does
                        snapshot = gate.subject_snapshot
                        brand_id = str(snapshot["brand_id"])
                        subject = await current_icp_document(
                            conn,
                            storage,
                            workspace_id=who.workspace_id,
                            brand_id=brand_id,
                            icp_key=str(snapshot["icp_key"]),
                            project_id=project_id,
                        )
                        product_set = await current_project_product_set(
                            conn,
                            workspace_id=who.workspace_id,
                            project_id=project_id,
                        )
                        try:
                            if subject is None:
                                raise IcpConfirmationStale(
                                    "the reviewed ICP document is no longer readable"
                                )
                            selection_version = (
                                None if product_set is None else product_set.selection_version
                            )
                            confirmed = await confirm_icp_document(
                                conn,
                                storage,
                                workspace_id=who.workspace_id,
                                brand_id=brand_id,
                                project_id=project_id,
                                proposed=subject,
                                expected_sha256=gate.expected_subject_sha256,
                                confirmed_by_user_id=who.user_id,
                                product_selection_version=selection_version,
                            )
                            # Founder rulings 2026-09-10: the approval is also the moment this
                            # project pins its ICP. Same transaction as the confirmed version and
                            # the immutable answer — a project can never end up having confirmed a
                            # document it does not pin, or pinning one nobody approved. A replayed
                            # approval finds its own document already pinned and writes nothing.
                            await pin_project_icp(
                                conn,
                                workspace_id=who.workspace_id,
                                project_id=project_id,
                                brand_id=brand_id,
                                document=confirmed,
                                product_selection_version=selection_version,
                                pinned_by_user_id=who.user_id,
                            )
                            pinned_project_icp = True
                        except IcpConfirmationStale as exc:
                            raise _refuse(
                                status_code=409,
                                code="GATE_SUBJECT_STALE",
                                message=str(exc),
                            ) from exc
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
                #
                # A submission the agent never replies to is no turn, so it announces none: an
                # open chat would otherwise attach a stream that never ends.
                if agent_reply == AGENT_REPLY_EXPECTED:
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
            # After the commit, never inside it: the library's compile takes this project's row
            # lock. Best-effort by contract — an approval that confirmed and pinned must not
            # report failure because its rendering could not be written.
            if pinned_project_icp and project_library is not None:
                await project_library.refresh(workspace_id=who.workspace_id, project_id=project_id)
            return TurnAcceptedResponse(
                data=TurnAcceptedWire(
                    turn_id=str(submission.turn_id),
                    thread_id=thread_id,
                    requested_at=submission.requested_at.isoformat(),
                    replayed=False,
                    routed_to=routed_to,
                    agent_reply=agent_reply,
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
    transactional_tool_invoker_factory: TransactionalToolInvokerFactory | None = None,
    project_library: ProjectLibraryRefresher | None = None,
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
            transactional_tool_invoker_factory=transactional_tool_invoker_factory,
            project_library=project_library,
        )
    )
