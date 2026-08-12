"""The `/frontend/v1` router foundation: flag gate, workspace scoping, error envelope, CORS.

Everything here is installed by :func:`install_frontend_read_surface` from the projections
composition root:

* **The scoped router** (:func:`build_frontend_read_router`) — where every slice-1 endpoint
  (Tasks 2–4) lives. Empty unless ``settings.frontend_read_enabled``, so a disabled deployment 404s
  these paths exactly as it does today. Workspace scoping is **structural**: the router carries
  ``dependencies=[Depends(frontend_read_workspace_resolver)]``, so a route cannot forget the tenant
  header — following the per-surface resolver + ``dependency_overrides`` pattern the projections and
  ingestion surfaces already use.
* **The probe router** (:func:`build_frontend_read_probe_router`) — ``GET /frontend/v1/health``,
  deliberately *outside* the scoped router because a liveness probe carries no tenant header. Its
  only job is to make the flag gate observable before the real endpoints exist.
* **The error envelope** — FI-1's ``{"error": {"code", "message", "requestId"}}``, the shape
  `apps/frontend/docs/api-contracts/accounts.md` already documents. Handlers are **path-scoped** to
  :data:`FRONTEND_READ_PREFIX` and delegate every other path back to the framework default, so the
  B4 projection routes keep their ``{"detail": …}`` shape. The envelope remains installed when the
  feature flag is off: routes are still absent/404, but an operator can correlate that configuration
  failure by request id instead of receiving an opaque framework response.
* **CORS** — standard ``CORSMiddleware``, added only when ``settings.frontend_cors_allow_origins``
  is non-empty. Empty is the default and adds no middleware at all, so a same-origin/Next-proxy
  deployment is byte-identical to today.

**Why the unhandled-500 envelope lives in middleware, not only in the exception handler.** Starlette
routes an ``Exception`` handler to ``ServerErrorMiddleware``, which sits *outside* every user
middleware — including CORS. An envelope produced there would reach a cross-origin browser without
``Access-Control-Allow-Origin`` and be discarded, so the frontend would see an opaque network error
instead of the code and request id it needs to report. The in-prefix 500 is therefore produced by
:func:`install_frontend_read_surface`'s own middleware, which is installed *inside* the CORS layer;
the app-level handler stays as the outer backstop for anything that escapes it (an error raised
inside CORS itself, or in the middleware's own error path).

The request id is a fresh ``uuid4().hex`` per in-scope request, echoed in the
:data:`REQUEST_ID_HEADER` response header (exposed through CORS) and carried in every enveloped
error body — so a frontend bug report names a value that appears in both.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as default_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from clue_config import Settings
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_storage import StorageBackend

log = get_logger("clue_api.frontend_read")

# Every route this package serves lives under this prefix; the error handlers and the envelope
# middleware scope themselves by it, so nothing outside it changes shape.
FRONTEND_READ_PREFIX = "/frontend/v1"

# Echoed on every response this surface produces (success and error alike), and named in
# ``expose_headers`` so a cross-origin browser can actually read it.
REQUEST_ID_HEADER = "X-Request-Id"

# Slice 1 is a read surface: a browser needs no cross-origin write verb here. Widening this is a
# deliberate later decision, not an accident of the initial config.
# Browser mutations also go through the same-origin BFF. Keeping cross-origin CORS read-only avoids
# accidentally widening unrelated write routes mounted on this shared FastAPI process.
CORS_ALLOW_METHODS = ["GET", "OPTIONS"]

# Status → FI-1 error code. Deliberately explicit rather than ``HTTPStatus(...).name``: the frontend
# contract treats these as a stable vocabulary, and 422's HTTPStatus name was renamed upstream.
_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


def _status_code_name(status_code: int) -> str:
    known = _STATUS_CODES.get(status_code)
    if known is not None:
        return known
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return "ERROR"


def _status_phrase(status_code: int) -> str:
    """The standard reason phrase, guarded — a non-standard status must not make the *handler*
    raise (which would escalate a plain 4xx into a 500)."""

    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "error"


def _in_scope(request: Request) -> bool:
    """True for the prefix itself and its children only — never for a path that merely starts with
    the same characters (``/frontend/v10/...`` is a different surface)."""

    path = request.url.path
    return path == FRONTEND_READ_PREFIX or path.startswith(f"{FRONTEND_READ_PREFIX}/")


def frontend_read_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    """This surface's tenant seam: derive ``workspace_id`` from ``X-Workspace-Id`` (``401`` if
    absent). Its own function (not a shared import) so the composition root can swap real service
    auth of the same ``-> workspace_id`` shape through ``dependency_overrides`` per surface — the
    pattern ``projections_app.header_workspace_resolver`` and
    ``ingestion_tools.header_workspace_resolver`` already follow."""

    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


#: How an endpoint *receives* the workspace the router already enforces. The router-level
#: ``dependencies=[…]`` guarantees the header is present; FastAPI caches the resolver per request,
#: so declaring it again here costs nothing and cannot diverge from the enforced value.
WorkspaceDep = Annotated[str, Depends(frontend_read_workspace_resolver)]


def request_id(request: Request) -> str:
    """The request's id — the middleware's value, or one generated on first read.

    Generating on demand keeps the handlers correct even for a request the middleware never saw
    (an error raised outside the middleware stack); body and header then still agree, because both
    are built from this one call.
    """

    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str):
        return existing
    generated = uuid4().hex
    request.state.request_id = generated
    return generated


def error_envelope(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    """Build the FI-1 envelope response, with the request id in both the body and the header."""

    resolved = request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "requestId": resolved}},
        headers={REQUEST_ID_HEADER: resolved},
    )


def _envelope_parts(exc: StarletteHTTPException) -> tuple[str, str]:
    """Derive ``(code, message)`` from an ``HTTPException``.

    A ``detail`` dict carrying an explicit ``code`` wins — that is how a slice-1 endpoint emits a
    domain code such as ``ACCOUNT_NOT_FOUND`` without every route re-implementing the envelope.
    Anything else falls back to the status vocabulary with the detail as the message.
    """

    detail: Any = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        message = detail.get("message")
        return detail["code"], message if isinstance(message, str) and message else str(exc.detail)
    default_code = _status_code_name(exc.status_code)
    if isinstance(detail, str) and detail:
        return default_code, detail
    return default_code, _status_phrase(exc.status_code)


def _validation_message(exc: RequestValidationError) -> str:
    """A compact, non-leaking summary of the failing inputs (locations + reasons, never values)."""

    parts: list[str] = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
        parts.append(
            f"{location}: {error.get('msg', 'invalid')}"
            if location
            else str(error.get("msg", "invalid"))
        )
    return "; ".join(parts) if parts else "request validation failed"


def build_frontend_read_router(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    evidence_storage: StorageBackend | None = None,
    contact_email_lookup: Any | None = None,
) -> APIRouter:
    """Build the workspace-scoped `/frontend/v1` router — **empty** unless the flag is on.

    Every slice-1 endpoint (Tasks 2–4) registers here and inherits the workspace dependency, so
    tenant scoping cannot be forgotten route-by-route. ``conn_factory`` is the connection seam those
    readers bind to.
    """

    router = APIRouter(
        prefix=FRONTEND_READ_PREFIX,
        tags=["frontend-read"],
        dependencies=[Depends(frontend_read_workspace_resolver)],
    )
    if not settings.frontend_read_enabled:
        return router
    # Imported here, not at module scope: the endpoint modules import ``WorkspaceDep`` from this
    # one, so a top-level import would be circular.
    from clue_api.frontend_read.account_activity import register_account_activity_routes
    from clue_api.frontend_read.account_detail import register_account_detail_routes
    from clue_api.frontend_read.accounts_list import register_accounts_list_routes
    from clue_api.frontend_read.bulk_actions import register_bulk_action_routes
    from clue_api.frontend_read.contacts import register_contact_routes

    allow_local_mutations = (
        settings.projections_auth_mode == "local_header" and not settings.auth_enabled
    )
    register_accounts_list_routes(router, conn_factory=conn_factory)
    # Static ``/accounts/bulk-*`` paths must be registered before the Account/Contact UUID routes,
    # otherwise Starlette would match a capability segment as ``{account_id}`` and return a 422.
    register_bulk_action_routes(
        router,
        conn_factory=conn_factory,
        contact_email_lookup=contact_email_lookup,
        allow_local_mutations=allow_local_mutations,
        chat_available=settings.chat_enabled,
    )
    register_account_activity_routes(router, conn_factory=conn_factory)
    register_account_detail_routes(
        router, conn_factory=conn_factory, evidence_storage=evidence_storage
    )
    register_contact_routes(
        router,
        conn_factory=conn_factory,
        evidence_storage=evidence_storage,
        contact_email_lookup=contact_email_lookup,
        allow_local_mutations=allow_local_mutations,
    )
    return router


def build_frontend_read_probe_router(*, settings: Settings) -> APIRouter:
    """Build the unscoped probe router — **empty** unless ``settings.frontend_read_enabled``.

    Separate from the scoped router on purpose: a liveness probe carries no tenant header, so it
    must not inherit the workspace dependency.
    """

    router = APIRouter(prefix=FRONTEND_READ_PREFIX, tags=["frontend-read"])
    if not settings.frontend_read_enabled:
        return router

    @router.get("/health")
    async def get_health() -> dict[str, str]:
        """Liveness of *this* router, not the process (the app's own probes are untouched).

        Its only job today is to make the flag gate observable: absent when off, 200 when on.
        """

        return {"status": "ok"}

    return router


def install_frontend_read_surface(
    app: FastAPI,
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    evidence_storage: StorageBackend | None = None,
    contact_email_lookup: Any | None = None,
) -> None:
    """Mount enabled routers and always own errors under the reserved frontend-read prefix.

    The flag controls route availability only. Even while it is off, the prefix returns the stable
    error envelope and request id so the frontend can distinguish configuration from an empty
    workspace. Every handler delegates off-prefix unchanged. CORS is installed independently of the
    router flag and is added **last** so it wraps the envelope middleware.
    """

    if settings.frontend_read_enabled:
        app.include_router(build_frontend_read_probe_router(settings=settings))
        app.include_router(
            build_frontend_read_router(
                settings=settings,
                conn_factory=conn_factory,
                evidence_storage=evidence_storage,
                contact_email_lookup=contact_email_lookup,
            )
        )

    @app.middleware("http")
    async def _frontend_read_envelope(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Stamp the request id and envelope in-prefix crashes inside the CORS layer."""

        if not _in_scope(request):
            return await call_next(request)
        resolved = request_id(request)
        try:
            response = await call_next(request)
        except Exception:
            # Swallowed on purpose: ``ServerErrorMiddleware`` would answer outside CORS. The
            # traceback is logged here so nothing is lost by not re-raising.
            log.exception(
                "frontend_read.unhandled_error",
                path=request.url.path,
                request_id=resolved,
            )
            return error_envelope(
                request,
                status_code=500,
                code="INTERNAL_ERROR",
                message="internal server error",
            )
        response.headers.setdefault(REQUEST_ID_HEADER, resolved)
        return response

    async def _http_exception_handler(request: Request, exc: Exception) -> Response:
        http_exc = cast(StarletteHTTPException, exc)
        if not _in_scope(request):
            return await default_http_exception_handler(request, http_exc)
        code, message = _envelope_parts(http_exc)
        return error_envelope(request, status_code=http_exc.status_code, code=code, message=message)

    async def _validation_exception_handler(request: Request, exc: Exception) -> Response:
        validation_exc = cast(RequestValidationError, exc)
        if not _in_scope(request):
            return await default_validation_exception_handler(request, validation_exc)
        return error_envelope(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message=_validation_message(validation_exc),
        )

    async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        """Outer backstop for in-prefix failures that escape the envelope middleware."""

        if not _in_scope(request):
            raise exc
        return error_envelope(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="internal server error",
        )

    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    # Added last so it is the outermost user middleware: it must wrap the envelope middleware, and
    # answer a preflight before anything else sees it.
    if settings.frontend_cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.frontend_cors_allow_origins),
            allow_credentials=True,
            allow_methods=CORS_ALLOW_METHODS,
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )
