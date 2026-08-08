"""The `/frontend/v1` router foundation: flag gate, FI-1 error envelope, request id, CORS.

Three separable pieces, all installed by :func:`install_frontend_read_surface` from the projections
composition root:

* **The router** (:func:`build_frontend_read_router`) — empty unless the
  ``settings.frontend_read_enabled`` flag is on, so a disabled deployment 404s these paths exactly
  as it does today. Task 1 registers only
  ``GET /frontend/v1/health`` (the gate is testable before the real endpoints exist).
* **The error envelope** — FI-1's ``{"error": {"code", "message", "requestId"}}``, the shape
  `apps/frontend/docs/api-contracts/accounts.md` already documents. FastAPI exception handlers are
  app-level, so each handler is **path-scoped** to :data:`FRONTEND_READ_PREFIX` and delegates every
  other path back to the framework default (the B4 projection routes keep their ``{"detail": …}``
  shape, and an unhandled error outside this router still propagates untouched).
* **CORS** — standard ``CORSMiddleware``, added only when ``settings.frontend_cors_allow_origins``
  is non-empty. Empty is the default and adds no middleware at all, so a same-origin/Next-proxy
  deployment is byte-identical to today.

The request id is a fresh ``uuid4().hex`` per request, stamped on the request state by a
prefix-scoped middleware, echoed in the :data:`REQUEST_ID_HEADER` response header, and carried in
every enveloped error body — so a frontend bug report names a value that appears in both.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request, Response
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

# Every route this package serves lives under this prefix; the error handlers and the request-id
# middleware scope themselves by it, so nothing outside the router changes shape.
FRONTEND_READ_PREFIX = "/frontend/v1"

# Echoed on every response this router produces (success and error alike).
REQUEST_ID_HEADER = "X-Request-Id"

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


def _in_scope(request: Request) -> bool:
    return request.url.path.startswith(FRONTEND_READ_PREFIX)


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
    return default_code, HTTPStatus(exc.status_code).phrase


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


def build_frontend_read_router(*, settings: Settings, conn_factory: ConnFactory) -> APIRouter:
    """Build the `/frontend/v1` router — **empty** unless ``settings.frontend_read_enabled``.

    ``conn_factory`` is the connection seam every slice-1 read will use (Tasks 2–4); Task 1's
    health probe needs no DB, so it is accepted and held, not exercised.
    """

    router = APIRouter(prefix=FRONTEND_READ_PREFIX, tags=["frontend-read"])
    if not settings.frontend_read_enabled:
        return router

    del conn_factory  # Tasks 2-4 bind their readers to it; the health probe touches no DB.

    @router.get("/health")
    async def get_health() -> dict[str, str]:
        """Liveness of *this* router, not the process (the app's own probes are untouched).

        Its only job today is to make the flag gate observable: absent when off, 200 when on.
        """

        return {"status": "ok"}

    return router


def install_frontend_read_surface(
    app: FastAPI, *, settings: Settings, conn_factory: ConnFactory
) -> None:
    """Mount the router and, when it is enabled, its request-id middleware + error handlers.

    CORS is installed independently of the router flag: it is a transport concern of the whole
    process, and a deployment may need it for the existing projection routes too. Both remain inert
    by default (flag off, origins empty).
    """

    if settings.frontend_cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.frontend_cors_allow_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )

    if not settings.frontend_read_enabled:
        return

    app.include_router(build_frontend_read_router(settings=settings, conn_factory=conn_factory))

    @app.middleware("http")
    async def _frontend_read_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _in_scope(request):
            return await call_next(request)
        resolved = request_id(request)
        response = await call_next(request)
        response.headers.setdefault(REQUEST_ID_HEADER, resolved)
        return response

    async def _http_exception_handler(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, StarletteHTTPException)
        if not _in_scope(request):
            return await default_http_exception_handler(request, exc)
        code, message = _envelope_parts(exc)
        return error_envelope(request, status_code=exc.status_code, code=code, message=message)

    async def _validation_exception_handler(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, RequestValidationError)
        if not _in_scope(request):
            return await default_validation_exception_handler(request, exc)
        return error_envelope(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message=_validation_message(exc),
        )

    async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        # Outside the router this handler must be transparent: re-raising leaves Starlette's
        # ServerErrorMiddleware behaviour (and the test client's ``raise_server_exceptions``)
        # exactly as it was before this surface existed.
        if not _in_scope(request):
            raise exc
        # The cause is never echoed to a browser; it is already logged/traced by the process.
        return error_envelope(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="internal server error",
        )

    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
