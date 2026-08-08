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

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from clue_api.chat.principal import (
    PERMISSION_THREAD_READ,
    PERMISSION_THREAD_WRITE,
    PrincipalResolver,
    RequestPrincipal,
    build_dev_principal_resolver,
)
from clue_api.chat.schemas import (
    CreateThreadRequest,
    MessageListResponse,
    PageMeta,
    ThreadListResponse,
    ThreadResponse,
    UpdateThreadRequest,
    message_list_response,
    thread_wire,
    thread_wire_from_references,
)
from clue_config import Settings
from clue_core import operation_id_from_key
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_projections import (
    DEFAULT_THREAD_MESSAGE_PAGE_SIZE,
    DEFAULT_THREAD_PAGE_SIZE,
    MAX_THREAD_MESSAGE_PAGE_SIZE,
    MAX_THREAD_PAGE_SIZE,
    InvalidCursorError,
    thread_messages,
    threads_for_project,
)
from clue_toolbelt import IdempotencyConflict, PreconditionFailed, ToolContext, ToolInvoker

log = get_logger("clue_api.chat")

__all__ = [
    "CHAT_PREFIX",
    "REQUEST_ID_HEADER",
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
}


def _status_code_name(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "ERROR")


def _refuse(*, status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def build_chat_router(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    tool_invoker: ToolInvoker,
) -> APIRouter:
    """Build the workspace-scoped chat router. Empty unless ``settings.chat_enabled``.

    The principal arrives through the module-level :func:`chat_principal_resolver` dependency,
    which :func:`install_chat_surface` overrides — so a router built without one refuses every
    request 401 rather than serving anybody.
    """

    router = APIRouter(prefix=CHAT_PREFIX, tags=["chat"], route_class=_EnvelopeRoute)
    if not settings.chat_enabled:
        return router

    def _require(who: RequestPrincipal, permission: str) -> None:
        if not who.allows(permission):
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
    ) -> dict[str, Any]:
        """Invoke one governed thread tool and return its references.

        ``actor_id`` is the principal's internal ``platform_user.user_id`` — ambient, never a
        request field. ``operation_id`` is derived from the caller's ``Idempotency-Key`` when there
        is one, so a retried create lands on the same thread instead of a second one.
        """

        ctx = ToolContext(
            workspace_id=who.workspace_id,
            actor="human",
            conn_factory=conn_factory,
            operation_id=operation_id_from_key(
                who.workspace_id, f"chat:{name}:{idempotency_key or uuid4().hex}"
            ),
            actor_id=who.user_id,
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
        return ThreadListResponse(
            data=tuple(thread_wire(item) for item in page.items),
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
    ) -> MessageListResponse:
        _require(who, PERMISSION_THREAD_READ)
        del project_id
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
        return message_list_response(page, thread_id=thread_id)

    return router


def install_chat_surface(
    app: FastAPI,
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    tool_invoker: ToolInvoker,
    principal_resolver: PrincipalResolver | None = None,
) -> None:
    """Mount the chat router when ``settings.chat_enabled``; otherwise do nothing at all.

    Raises :class:`~clue_api.chat.principal.ProductionPrincipalRequired` when the surface is
    enabled outside ``local_header`` auth mode without an injected resolver — a process that would
    serve chat traffic under a development identity must fail to start, not at first request.
    """

    if not settings.chat_enabled:
        return
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
        )
    )
