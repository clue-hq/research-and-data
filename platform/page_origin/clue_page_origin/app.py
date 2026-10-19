"""App factory. ``lifespan`` is injected so tests build the app with fakes and no database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI, Request, Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from clue_page_origin.edge import BadPublicHost, EdgeGate, EdgeRefused
from clue_page_origin.reads import PageReads
from clue_page_origin.routes import build_router

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_page_origin_app(
    *, reads: PageReads, gate: EdgeGate, lifespan: Lifespan | None = None
) -> FastAPI:
    app = FastAPI(
        title="Clue public page origin",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def _get_head_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in ("GET", "HEAD"):
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        return await call_next(request)

    @app.exception_handler(EdgeRefused)
    async def _refused(_request: Request, _exc: EdgeRefused) -> Response:
        return Response(status_code=403)

    @app.exception_handler(BadPublicHost)
    async def _bad_host(_request: Request, _exc: BadPublicHost) -> Response:
        return Response(status_code=400)

    app.include_router(build_router(reads, gate))
    # A live page and its runtime are hundreds of KB, so the origin gzips what a client asks for
    # gzipped (the edge passes the encoding through). The weak-ETag step sits outside gzip so it
    # sees the encoded response.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(_WeakEtagWhenEncoded)
    return app


class _WeakEtagWhenEncoded:
    """A gzipped response is another representation of the same content, so its ETag is weak."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_weak(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if any(name.lower() == b"content-encoding" for name, _ in headers):
                    headers = [
                        (name, _weak(value) if name.lower() == b"etag" else value)
                        for name, value in headers
                    ]
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_weak)


def _weak(etag: bytes) -> bytes:
    return etag if etag.startswith(b"W/") else b"W/" + etag
