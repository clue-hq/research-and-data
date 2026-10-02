"""App factory. ``lifespan`` is injected so tests build the app with fakes and no database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI, Request, Response

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
    return app
