"""The public ORIGIN a published site is served from: ``{handle}.<suffix>/{slug}{route}``.

``public_address.py`` decides where a site *is* (Task 12) and the workspace handle says which
label goes in front of the wildcard suffix (Task 14). This module is the half that actually
ANSWERS that hostname: a small ASGI app mounted behind a Starlette ``Host`` route, which reads
the handle out of the matched host, resolves it to a workspace, and then calls the very same
serving bodies the interim ``/w/{workspace}/p/{slug}`` routes call. There is one publish read,
one 404 page and one CSP in the API; this app changes the ADDRESS, never the answer.

**The custom-domain seam.** Resolution is one indexed lookup on ``design_workspace_handle.handle``
today; a later ``design_custom_domain(host, workspace_id, verified_at)`` table plugs into the SAME
resolver — it becomes "handle table, then custom-domain table" — and nothing else here changes.

Two properties this app is responsible for, both fail-closed:

* **An unknown handle is a 404, never somebody else's site.** The resolver returns ``None`` and
  the visitor gets the published-site 404 page. The repository the caller builds for a resolved
  workspace is the ``ensure_workspace=False`` one, so no anonymous GET can mint a tenant row.
* **A site's own bytes are same-origin with its pages.** Published HTML references
  ``/p-assets/{digest}.{ext}`` and ``/asset-store/{digest}`` root-relatively (in host mode the
  publish-asset prefix is bare — ``PublicSiteAddress.asset_base``), so both routes live here too
  or the site loads unstyled.

Mounting is conditional on ``LUMEN_PUBLIC_PAGES_HOST_SUFFIX``, read ONCE when the app is built:
a ``Host`` pattern is compiled into the route table, so changing the suffix needs a restart —
the same contract as every other env in this API. Blank (the default) mounts nothing at all and
the interim path scheme serves, exactly as before this module existed.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

__all__ = ["PUBLISH_NOT_FOUND_HTML", "build_public_pages_app"]


#: The one 404 body every public serving path returns — the host app and the interim routes.
PUBLISH_NOT_FOUND_HTML = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<title>Not found</title></head><body><h1>404</h1>"
    "<p>No published page at this address.</p></body></html>"
)


class SitePageServer(Protocol):
    """The publish-row read that renders one route of one site (``main._serve_site_page``)."""

    def __call__(
        self,
        *,
        workspace_id: str,
        handle: str,
        slug: str,
        route: str,
        request_base_url: str,
    ) -> Response: ...


def _handle_of(request: Request) -> Optional[str]:
    """The handle Starlette's ``Host`` route matched out of the request's ``Host`` header.

    ``Host.matches`` merges its host params into ``scope["path_params"]``, and ``Route.matches``
    merges (rather than replaces) on the way into the endpoint, so the handle is still there
    beside the route's own ``slug``/``route`` params.
    """
    handle = request.path_params.get("handle")
    if isinstance(handle, str) and handle.strip():
        return handle.strip().lower()
    return None


def build_public_pages_app(
    *,
    resolve_workspace_for_handle: Callable[[str], Optional[str]],
    serve_site_page: SitePageServer,
    serve_publish_manifest: Callable[[str, str], Response],
    serve_publish_asset: Callable[[str, str], Response],
    serve_asset_store: Callable[[str], Response],
) -> FastAPI:
    """The app behind ``Host("{handle}.<suffix>")``.

    Every collaborator is injected because they are all closures over the API's composition root
    (its storage backend, its repository factory, its engine cache) — this app owns the ADDRESS
    SPACE and nothing else, which is what keeps the custom-domain seam a one-function change.
    """

    # No docs, no schema: this app faces the open internet, and its only readers are browsers
    # loading a published page.
    app = FastAPI(
        title="Published sites (public host)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(StarletteHTTPException)
    def public_http_error(_request: Request, error: StarletteHTTPException) -> Response:
        """A visitor gets the site 404 page, never an API error envelope."""
        if error.status_code == 404:
            return HTMLResponse(content=PUBLISH_NOT_FOUND_HTML, status_code=404)
        return Response(status_code=error.status_code)

    def _workspace(request: Request) -> Optional[str]:
        handle = _handle_of(request)
        if handle is None:
            return None
        return resolve_workspace_for_handle(handle)

    @app.get("/p-assets/{asset_name}")
    def public_publish_asset(asset_name: str, request: Request) -> Response:
        workspace_id = _workspace(request)
        if workspace_id is None:
            return HTMLResponse(content=PUBLISH_NOT_FOUND_HTML, status_code=404)
        return serve_publish_asset(workspace_id, asset_name)

    @app.get("/asset-store/{digest}")
    def public_asset_store(digest: str) -> Response:
        # Content-addressed and deliberately workspace-unscoped (ruling R-D4-7), exactly as on
        # the interim origin: the published page's images and @font-face bytes come from here.
        return serve_asset_store(digest)

    # DECLARED BEFORE `/{slug}` and the catch-all: `{slug}/{route:path}` also matches
    # `/{slug}/manifest.json`, and FastAPI matches in declaration order.
    @app.get("/{slug}/manifest.json")
    def public_manifest(slug: str, request: Request) -> Response:
        workspace_id = _workspace(request)
        if workspace_id is None:
            return HTMLResponse(content=PUBLISH_NOT_FOUND_HTML, status_code=404)
        return serve_publish_manifest(workspace_id, slug)

    @app.get("/{slug}")
    def public_site_root(slug: str, request: Request) -> Response:
        return _page(slug, "/", request)

    @app.get("/{slug}/{route:path}")
    def public_site_page(slug: str, route: str, request: Request) -> Response:
        # A trailing slash is the same page (a static host would serve the folder index), and an
        # empty path is the site root — the interim route's normalization, unchanged.
        return _page(slug, "/" + route.strip("/"), request)

    def _page(slug: str, route: str, request: Request) -> Response:
        workspace_id = _workspace(request)
        handle = _handle_of(request)
        if workspace_id is None or handle is None:
            return HTMLResponse(content=PUBLISH_NOT_FOUND_HTML, status_code=404)
        return serve_site_page(
            workspace_id=workspace_id,
            handle=handle,
            slug=slug,
            route=route,
            request_base_url=str(request.base_url).rstrip("/"),
        )

    return app
