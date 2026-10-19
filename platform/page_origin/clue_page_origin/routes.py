"""The origin's routes (spec §5.2).

GET/HEAD only; the edge gate runs before every route but ``/healthz``.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from clue_design.publishes import PublishAssetMismatch, check_publish_asset, delivery_csp
from clue_page_origin.edge import EdgeGate
from clue_page_origin.reads import PageReads

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,71}$")
ASSET_NAME = re.compile(r"^([0-9a-f]{64})\.(js|css|html)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

NOT_FOUND_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="robots" content="noindex"><title>Not found</title></head>'
    "<body><h1>404</h1><p>No published page at this address.</p></body></html>"
)
# FastAPI's APIRoute (unlike Starlette's plain Route) does NOT add HEAD alongside GET, so
# every route declares it: the origin answers GET and HEAD, and nothing else (spec §5.2).
_GET_HEAD = ["GET", "HEAD"]
_IMMUTABLE = "public, max-age=31536000, immutable"
_SHORT = "public, max-age=60, must-revalidate"


def _not_found() -> HTMLResponse:
    return HTMLResponse(
        NOT_FOUND_HTML,
        status_code=404,
        headers={
            "X-Robots-Tag": "noindex",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def _page_headers(
    digest: str, *, noindex: bool, delivery: str = "web", script_hashes: tuple[str, ...] = ()
) -> dict[str, str]:
    headers = {
        "Cache-Control": _SHORT,
        "ETag": f'"sha256-{digest}"',
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": delivery_csp(delivery=delivery, script_hashes=script_hashes),
    }
    if noindex:
        headers["X-Robots-Tag"] = "noindex"
    return headers


def _asset_headers(digest: str) -> dict[str, str]:
    return {
        "Cache-Control": _IMMUTABLE,
        "ETag": f'"sha256-{digest}"',
        "X-Content-Type-Options": "nosniff",
    }


def build_router(reads: PageReads, gate: EdgeGate) -> APIRouter:
    router = APIRouter()

    async def workspace(request: Request) -> str | None:
        return await reads.workspace_for_hostname(gate.public_host(request))

    async def _miss(workspace_id: str) -> Response:
        fallback = await reads.fallback_url(workspace_id)
        if fallback:
            return RedirectResponse(fallback, status_code=302)
        return _not_found()

    @router.api_route("/healthz", methods=_GET_HEAD)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.api_route("/", methods=_GET_HEAD)
    async def root(workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None:
            return _not_found()
        return await _miss(workspace_id)

    @router.api_route("/favicon.ico", methods=_GET_HEAD)
    async def favicon(workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None:
            return Response(status_code=404)
        found = await reads.favicon(workspace_id)
        if found is None:
            return Response(status_code=404)
        media_type, data = found
        return Response(
            content=data, media_type=media_type, headers={"Cache-Control": "public, max-age=300"}
        )

    @router.api_route("/p-assets/{asset_name}", methods=_GET_HEAD)
    async def publish_asset(
        asset_name: str, workspace_id: str | None = Depends(workspace)
    ) -> Response:
        match = ASSET_NAME.fullmatch(asset_name)
        if workspace_id is None or match is None:
            return Response(status_code=404)
        digest, extension = match.groups()
        found = await reads.publish_asset(workspace_id, digest)
        if found is None:
            return Response(status_code=404)
        media_type, data = found
        try:
            served_type = check_publish_asset(
                data=data, media_type=media_type, digest=digest, extension=extension
            )
        except PublishAssetMismatch:
            return Response(status_code=404)
        return Response(content=data, media_type=served_type, headers=_asset_headers(digest))

    @router.api_route("/asset-store/{digest}", methods=_GET_HEAD)
    async def asset_store(digest: str, workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None or not SHA256.fullmatch(digest):
            return Response(status_code=404)
        found = await reads.public_blob(digest)
        if found is None:
            return Response(status_code=404)
        media_type, data = found
        return Response(content=data, media_type=media_type, headers=_asset_headers(digest))

    @router.api_route("/{slug}/manifest.json", methods=_GET_HEAD)
    async def manifest(slug: str, workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None or not SLUG.fullmatch(slug):
            return _not_found()
        publish = await reads.active_publish(workspace_id, slug)
        if publish is None:
            return await _miss(workspace_id)
        return Response(
            content=publish.manifest_json,
            media_type="application/json",
            headers=_page_headers(
                publish.manifest_digest,
                noindex=publish.noindex,
                delivery=publish.delivery,
                script_hashes=publish.script_hashes,
            ),
        )

    @router.api_route("/{slug}", methods=_GET_HEAD)
    async def page(slug: str, workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None or not SLUG.fullmatch(slug):
            return _not_found()
        publish = await reads.active_publish(workspace_id, slug)
        if publish is None:
            return await _miss(workspace_id)
        return HTMLResponse(
            publish.html,
            headers=_page_headers(
                publish.html_digest,
                noindex=publish.noindex,
                delivery=publish.delivery,
                script_hashes=publish.script_hashes,
            ),
        )

    # F5 multipage: published pages link to each other root-relatively as ``/{slug}{route}``.
    # Declared after ``/{slug}/manifest.json`` so the manifest keeps winning (first match).
    @router.api_route("/{slug}/{route:path}", methods=_GET_HEAD)
    async def route_page(
        slug: str, route: str, workspace_id: str | None = Depends(workspace)
    ) -> Response:
        normalised = "/" + route.strip("/")
        if normalised == "/":
            return await page(slug, workspace_id)
        if workspace_id is None or not SLUG.fullmatch(slug):
            return _not_found()
        served = await reads.active_page(workspace_id, slug, normalised)
        if served is None:
            return await _miss(workspace_id)
        return HTMLResponse(
            served.html,
            headers=_page_headers(
                served.html_digest,
                noindex=served.noindex,
                delivery=served.delivery,
                script_hashes=served.script_hashes,
            ),
        )

    return router
