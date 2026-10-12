"""The site turn's capabilities (Lane B): what the runtime may call back into while it runs.

The runtime never reads the database or imports a renderer's internals; it calls these four
objects through the protocols in `lumen_agent/site/inputs.py`:
- PlatformSiteRenderer — Lane A's hardened headless-Chromium renderer (Contract 3);
- DurableSiteAssetPort — this workspace's blobs, and generated images into the library (Task 10);
- DurableSiteVersionPort — the document's saved versions (Task 12);
- DurableSiteSectionPort — compile, read the props schema, store and record a section (Task 15).
"""

from __future__ import annotations

from typing import Any

__all__ = ["PlatformSiteRenderer", "SiteRenderPortError"]


class SiteRenderPortError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class PlatformSiteRenderer:
    """SiteRenderPort over `lumen_api.site_render` (Lane A, Contract 3). Agent sections are only
    ever imported inside Lane A's hardened render page.

    ``read_blob(digest) -> (media_type, bytes)`` is the workspace's blob read: Lane A's screenshot
    runs with JavaScript off and the network blocked, so every ``/asset-store/<sha256>`` in the page
    and its CSS is inlined as a ``data:`` URI first (``web_pdf.inline_asset_store_refs``, the PDF
    export's own helper). A digest the workspace cannot serve is left as is and shows broken, which
    is what the agent should see."""

    def __init__(self, read_blob: Any = None) -> None:
        self.read_blob = read_blob
        self._inlined: dict = {}

    def render(self, site: dict, brand: dict, sections: list, *, route: str) -> tuple[str, str, list[str]]:
        from . import site_render

        modules = [
            site_render.SectionModule(name=s.name, digest=s.digest, module_js=s.module_js, css=s.css, props_schema=s.props_schema)
            for s in sections
        ]
        # base_path "" leaves /route links as written: the site is drawn as if served at its root
        # ("/" would turn /analysis into the protocol-relative //analysis).
        result = site_render.render_site(site, brand, modules, base_path="", routes=[route])
        page = next((item for item in result.pages if item.route == route), None)
        if page is None:
            raise SiteRenderPortError("render.failed", f"the renderer returned no page {route}")
        return page.html, result.css, list(result.warnings)

    def screenshot(self, html: str, css: str, *, width: int) -> bytes:
        from . import site_render

        if self.read_blob is not None:
            from .web_pdf import inline_asset_store_refs

            html, _missing = inline_asset_store_refs(html, self.read_blob, cache=self._inlined)
            css, _missing = inline_asset_store_refs(css, self.read_blob, cache=self._inlined)
        return site_render.capture_site_screenshot(site_render.RenderedPage(route="/", html=html), css, width=width, full_page=True)
