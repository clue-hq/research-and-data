"""The site turn's capabilities (Lane B): what the runtime may call back into while it runs.

The runtime never reads the database or imports a renderer's internals; it calls these four
objects through the protocols in `lumen_agent/site/inputs.py`:
- PlatformSiteRenderer — Lane A's hardened headless-Chromium renderer (Contract 3);
- DurableSiteAssetPort — this workspace's blobs, and generated images into the library (Task 10);
- DurableSiteVersionPort — the document's saved versions (Task 12);
- DurableSiteSectionPort — compile, read the props schema, store and record a section (Task 15).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .site_kit_cli import compile_section_source
from .toolbelt.site_documents import replace_site_payload
from .web_export import compile_tailwind_css

__all__ = [
    "SCHEMA_UNREADABLE",
    "DurableSiteAssetPort",
    "DurableSiteSectionPort",
    "DurableSiteVersionPort",
    "PlatformSiteRenderer",
    "SiteAssetError",
    "SitePersistOutcome",
    "SiteRenderPortError",
]


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
    is what the agent should see.

    ``live`` (publishing live sites, phase 1: the workspace is on ``LUMEN_SITE_LIVE_WORKSPACES``):
    each page is rendered live and remembered with its modules by the sha256 of its html, and a
    screenshot of a remembered page is the page after it has come alive — JavaScript on, network
    still blocked (``site_live.live_preview_document``), with the refs in its page data inlined too."""

    def __init__(self, read_blob: Any = None, *, live: bool = False) -> None:
        self.read_blob = read_blob
        self.live = live
        self._inlined: dict = {}
        self._live_pages: dict[str, tuple[Any, list[Any]]] = {}

    def render(self, site: dict, brand: dict, sections: list, *, route: str) -> tuple[str, str, list[str]]:
        from . import site_render

        modules = [
            site_render.SectionModule(name=s.name, digest=s.digest, module_js=s.module_js, css=s.css, props_schema=s.props_schema)
            for s in sections
        ]
        # base_path "" leaves /route links as written: the site is drawn as if served at its root
        # ("/" would turn /analysis into the protocol-relative //analysis).
        result = site_render.render_site(site, brand, modules, base_path="", routes=[route], live=self.live)
        page = next((item for item in result.pages if item.route == route), None)
        if page is None:
            raise SiteRenderPortError("render.failed", f"the renderer returned no page {route}")
        if self.live:
            self._live_pages[hashlib.sha256(page.html.encode("utf-8")).hexdigest()] = (page, modules)
        return page.html, result.css, list(result.warnings)

    def screenshot(self, html: str, css: str, *, width: int, section_only: bool = False) -> bytes:
        from . import site_render

        remembered = self._live_pages.get(hashlib.sha256(html.encode("utf-8")).hexdigest()) if self.live else None
        data = remembered[0].data if remembered is not None else None
        if self.read_blob is not None:
            from .web_pdf import inline_asset_store_refs

            html, _missing = inline_asset_store_refs(html, self.read_blob, cache=self._inlined)
            css, _missing = inline_asset_store_refs(css, self.read_blob, cache=self._inlined)
            if data is not None:
                text, _missing = inline_asset_store_refs(json.dumps(data), self.read_blob, cache=self._inlined)
                data = json.loads(text)
        live_document = None
        if remembered is not None:
            from .site_live import live_preview_document, live_runtime

            live_page = site_render.RenderedPage(route=remembered[0].route, html=html, data=data)
            live_document = live_preview_document(live_page, css, remembered[1], live_runtime())
        return site_render.capture_site_screenshot(
            site_render.RenderedPage(route="/", html=html), css, width=width, full_page=True,
            # A shell-less scratch site's one section sits alone inside site-kit's .brand-root (the
            # theme gives it no min-height), so an element shot of it is the section, cut to size.
            clip_selector=".brand-root" if section_only else None,
            live_document=live_document,
        )


class SiteAssetError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class DurableSiteAssetPort:
    """SiteAssetPort over this workspace's design blobs and its asset library."""

    def __init__(self, *, blobs: Any, cache_dir: Any, core: Any, invocations: Any, run_id: str) -> None:
        self.blobs = blobs
        self.cache_dir = Path(cache_dir)
        self.core = core
        self.invocations = invocations
        self.run_id = run_id

    def read(self, digest: str) -> tuple[str, bytes]:
        return self.blobs.read_blob(digest)

    def exists(self, digest: str) -> bool:
        from .design_store import CustodyState

        return self.blobs.custody_states([digest]).get(digest) is CustodyState.READABLE

    def register_generated(
        self, *, image_bytes: bytes, mime_type: str, prompt: str, model: str | None,
        license: dict | None, provenance: dict,
    ) -> dict:
        """Ingest, give durable custody, and register an AI-generated library asset (the web lane's
        `_generate_image_record` source shape, and the account-logo binder's custody discipline)."""

        from clue_design.storage import SOURCE_KEY_ASSET

        from .asset_custody import register_engine_write

        asset_id = f"asset_gen_{uuid4().hex}"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        ingest = self.core.ingest_asset(
            store_root=str(self.cache_dir),
            bytes_base64=base64.b64encode(image_bytes).decode("ascii"),
            asset_id=asset_id,
            label=prompt[:200],
            declared_mime_type=mime_type,
            kind="raster_image",
            license=license,
            provenance=provenance,
            source={"kind": "generated", "request_id": asset_id, "model": model},
            raise_on_error=False,
        )
        if not ingest.get("ok"):
            raise SiteAssetError("site_asset.ingest_failed", str((ingest.get("error") or {}).get("message") or "unknown"))
        record = copy.deepcopy((ingest.get("asset") or {}).get("record") or {})
        register_engine_write(self.blobs, self.cache_dir, source_key=SOURCE_KEY_ASSET, record=record)
        digest = str(((record.get("media") or {}).get("digest") or {}).get("value") or "")
        if not digest or not self.exists(digest):
            raise SiteAssetError("site_asset.bytes_unavailable", f"no durable bytes for {asset_id}")
        self.invocations.invoke(
            "design_register_asset_record", {"record": record},
            workspace_id=self.blobs.workspace_id, actor="agent", actor_id=self.run_id,
        )
        return {"asset_id": str(record.get("id") or asset_id), "digest": digest, "file": f"/asset-store/{digest}"}


@dataclass(frozen=True)
class SitePersistOutcome:
    """What the governed site write did with one request's site."""

    #: ``fenced``: the attempt no longer holds its run, so nothing was saved (and it must not
    #: report as the run). ``already_saved``: an earlier attempt of this run saved the site, so
    #: this one wrote nothing; the turn reports that earlier save as its own (``run_site_agent_turn``).
    status: Literal["saved", "conflicted", "refused", "fenced", "already_saved"]
    #: The new version when saved; the stored version when conflicted; None otherwise.
    version: int | None
    detail: str | None = None


class DurableSiteVersionPort:
    """SiteVersionPort over the document's edit history (Contract 2: one envelope per save or
    request, each a whole-site snapshot)."""

    def __init__(self, store: Any, document_id: str) -> None:
        self.store = store
        self.document_id = document_id

    def list_versions(self, limit: int) -> list[dict]:
        rows = self.store.list_envelopes(self.document_id, limit=limit, newest_first=True)
        return [
            {"version": int(row["base_revision"]) + 1, "actor": (row.get("actor") or {}).get("kind"),
             "intent": row.get("intent"), "created_at": row.get("created_at")}
            for row in rows
            if replace_site_payload(row.get("operations")) is not None
        ]

    def site_at(self, version: int) -> dict | None:
        for row in self.store.list_envelopes(self.document_id, newest_first=True):
            if int(row["base_revision"]) + 1 == int(version):
                site = replace_site_payload(row.get("operations"))
                return copy.deepcopy(site) if site is not None else None
        return None


#: T13 (founder-approved text): the one error write_section shows when the hardened render page
#: could not read the module's props schema. {message} is the render page's own reason.
SCHEMA_UNREADABLE = (
    "the section could not be loaded to read its props ({code}: {message}); check that it exports "
    "`schema` (a zod object with `id` and `surface`) and `render`"
)


class DurableSiteSectionPort:
    """SiteSectionPort (Contract 4): check and bundle in Node (the module never runs here), build its
    CSS the way the renderer builds a site's (Tailwind over the text, with the brand's theme), then
    record it through the governed design_record_site_section, which reads the props schema in Lane
    A's hardened render page. Check errors come back as a list to fix; a toolchain that cannot
    answer raises (write_section turns that into "the check crashed"). ``interactive``: the
    workspace's sites publish live, so its sections are checked in the interactive mode."""

    def __init__(
        self, *, store: Any, invocations: Any, run_id: str, brand: dict, node_bin: str = "node", interactive: bool = False
    ) -> None:
        self.store = store
        self.invocations = invocations
        self.run_id = run_id
        self.brand = brand
        self.node_bin = node_bin
        self.interactive = interactive

    def compile(self, *, name: str, source: str) -> dict:
        from lumen_agent.site.inputs import SiteSection

        from .toolbelt.site_sections import SiteSectionRefused

        answer = compile_section_source(name=name, source=source, brand=self.brand, interactive=self.interactive)
        if not answer.get("ok"):
            return {"ok": False, "errors": [str(error) for error in answer.get("errors") or []]}
        module_js = str(answer["moduleJs"])
        css = compile_tailwind_css(source, '@import "tailwindcss";\n' + str(answer.get("tailwindTheme") or ""), self.node_bin)
        try:
            result = self.invocations.invoke(
                "design_record_site_section",
                {"name": name, "source": source, "module_js": module_js, "css": css},
                workspace_id=self.store.workspace_id,
                actor="agent",
                actor_id=self.run_id,
            )
        except SiteSectionRefused as refused:
            return {"ok": False, "errors": [SCHEMA_UNREADABLE.format(code=refused.code, message=refused.message)]}
        digest = str(result.references["digest"])
        (row,) = self.store.get_site_sections([digest])
        return {
            "ok": True,
            "section": SiteSection(name=name, digest=digest, props_schema=row["props_schema"], module_js=module_js, css=css),
        }
