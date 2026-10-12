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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .toolbelt.site_documents import replace_site_payload

__all__ = [
    "DurableSiteAssetPort",
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

    status: Literal["saved", "conflicted", "refused"]
    #: The new version when saved; the stored version when conflicted; None when refused.
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
