"""Builders that turn a stored Puck site into something people see: the gallery thumbnail (Task
18), the publish package (Task 20), and the ZIP and PDF exports (Task 22). Every one renders
through ``site_render.render_site`` (agent code only inside the hardened page) and cleans the
result with ``site_sanitize.sanitize_site_html`` before anything sees it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from clue_design.publishes import delivery_csp

from . import web_export, web_pdf
from .database import NotFoundError
from .design_store import CustodyState
from .public_address import PublicSiteAddress
from .site_doc_validate import SiteDocumentInvalid, check_site_document
from .site_render import (
    RenderedPage,
    SectionModule,
    capture_site_screenshot,
    pinned_modules,
    render_site,
    site_page_html,
)
from .site_sanitize import sanitize_site_html
from .web_pdf import inline_asset_store_refs

JsonObject = dict[str, Any]

#: The gallery card's own 4:3, captured at half scale (724×543 output) — web_thumbnail_png's frame.
THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT, THUMBNAIL_SCALE = 1448, 1086, 0.5


def site_thumbnail_png(
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    node_bin: str = "node",
) -> bytes:
    """The top of the site's home page as the gallery card shows it."""
    render = render_site(document["scene"], brand, sections, base_path="", routes=["/"], node_bin=node_bin)
    home = render.pages[0]
    inlined, _missing = inline_asset_store_refs(site_page_html(home, render.css), blobs.read_blob)
    return capture_site_screenshot(
        RenderedPage(route=home.route, html=inlined),
        "",
        width=THUMBNAIL_WIDTH,
        height=THUMBNAIL_HEIGHT,
        full_page=False,
        scale=THUMBNAIL_SCALE,
    )


SITE_DELIVERY = "site"
#: Founder ruling Q5 (2026-10-12): retiring sections is out of scope for sites, so a section retired
#: after the page used it still publishes (WebDoc's posture); a draft one never released, or one the
#: registry lacks, does not.
_PUBLISHABLE_CLONE_STATUSES = frozenset({"approved", "deprecated"})
#: The marketer reads these verbatim (the web editor shows a refusal's message as is,
#: apps/frontend/src/features/design-editor/engine/webDocuments.ts:2073), so they never say "clone"
#: or show an id. Founder-approved wording, 2026-10-12.
_SECTION_NOT_IN_LIBRARY = (
    "This page uses a section that isn't in your brand's library. "
    "Ask the agent to replace it, then publish again."
)


def _section_not_approved(label: str | None) -> str:
    named = f': "{label}"' if label else ""
    return f"This page uses a section that isn't approved yet{named}. Approve your brand kit, then publish again."


_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
_CSP_FILE_DIRECTIVES = frozenset({"style-src", "img-src", "font-src", "media-src"})


class SitePublishRefused(Exception):
    """A site that may not be published as it stands, with a stable ``site_publish.*`` code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clone_ids(site: JsonObject) -> list[str]:
    found: list[str] = []
    for page in (site.get("pages") or {}).values():
        for item in (page or {}).get("content") or []:
            if item.get("type") == "ClonedSection":
                fragment_id = str((item.get("props") or {}).get("fragmentId") or "")
                if fragment_id and fragment_id not in found:
                    found.append(fragment_id)
    return found


def check_clone_pins(site: JsonObject, brand: JsonObject, fragment_status: Callable[[str], str | None]) -> None:
    """Ruling 2026-10-11: clone pins are validated at publish, not on every save."""
    for fragment_id in _clone_ids(site):
        status = fragment_status(fragment_id)
        clone = (brand.get("clones") or {}).get(fragment_id)
        if status is None or clone is None:
            raise SitePublishRefused("site_publish.clone_unresolved", _SECTION_NOT_IN_LIBRARY)
        if status not in _PUBLISHABLE_CLONE_STATUSES:
            label = str(clone.get("label") or "").strip() or None
            raise SitePublishRefused("site_publish.clone_not_approved", _section_not_approved(label))


def gated_brand(brand: JsonObject, repo: Any, blobs: Any) -> tuple[JsonObject, Any]:
    """The brand with its fonts replaced by the licence gate's faces (``web_export._gather_fonts``,
    the gate every WebDoc publish uses): a family whose licence does not allow embedding is not
    shipped, and each shipped face is the WOFF2 the gate registered."""
    gate = web_export._gather_fonts(brand.get("kit"), repo, blobs)
    fonts = [{"family": face.family, "weight": face.weight, "style": face.style, "file": f"/asset-store/{face.digest}"} for face in gate.faces]
    return {**brand, "fonts": fonts}, gate


def site_delivery_csp(*, meta: bool, static_bundle: bool = False) -> str:
    """The site policy; ``static_bundle`` adds ``file:`` where the export ZIP loads its own files
    from disk (an opaque origin that ``'self'`` does not match), as web_export._delivery_csp does."""
    policy = delivery_csp(meta=meta, delivery=SITE_DELIVERY)
    if not static_bundle:
        return policy
    return "; ".join(
        directive + " file:" if directive.split(" ", 1)[0] in _CSP_FILE_DIRECTIVES else directive
        for directive in policy.split("; ")
    )


def _page_title(site: JsonObject, route: str) -> str:
    root = ((site.get("pages") or {}).get(route) or {}).get("root") or {}
    return str((root.get("props") or {}).get("title") or site.get("title") or "")


def _site_page_head(*, title: str, description: str, og_image: str | None, noindex: bool) -> str:
    """Our own head for a published page (founder question Q2, recommendation (a)). Added AFTER
    the cleaner runs, so nothing here is ever stripped."""
    head = '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    head += web_export._seo_snippet(title=title, description=description, og_image=og_image)
    head += '<link rel="icon" href="/favicon.ico">\n'
    if noindex:
        head += web_export.ROBOTS_NOINDEX_META + "\n"
    return head


def build_site_publish_package(
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    slug: str,
    site_address: PublicSiteAddress,
    default_description: str | None = None,
    default_social_preview_sha256: str | None = None,
    noindex: bool = False,
    node_bin: str = "node",
    fragment_status: Callable[[str], str | None] | None = None,
) -> web_export.PublishPackage:
    """One immutable publish package for a Puck site, same shape as the WebDoc one.

    Order: the modules the site pins (missing or stale refuses, ``render.section_module_missing``),
    the clone pins, the licence-gated fonts, the contract checks, the hardened render at the site's
    own path, the cleaner over each whole page, our head, the manifest (``delivery: "site"``, an
    empty ``custom_components``), and the CSP meta + manifest back-reference. Every URL it mints is
    root-relative except ``og:image``, as on the web path."""
    site = document["scene"]
    pinned_modules(site, sections)
    status = fragment_status or (lambda fragment_id: (repo.find_web_fragment(fragment_id) or {}).get("status"))
    check_clone_pins(site, brand, status)
    brand, gate = gated_brand(brand, repo, blobs)
    errors = check_site_document(site, document_id=str(document["id"]), brand=brand, sections=sections, blobs=blobs, node_bin=node_bin)
    if errors:
        raise SiteDocumentInvalid(errors)
    render = render_site(site, brand, sections, base_path=site_address.link_path, node_bin=node_bin)
    origin = site_address.origin.rstrip("/")
    og_image = f"{origin}/asset-store/{default_social_preview_sha256}" if default_social_preview_sha256 else None
    warnings = [*gate.warnings, *render.warnings]
    staged: list[tuple[str, str]] = []
    for page in render.pages:
        cleaned = sanitize_site_html(site_page_html(page, render.css)).html
        head = _site_page_head(title=_page_title(site, page.route), description=default_description or "", og_image=og_image, noindex=noindex)
        staged.append((page.route, web_export._inject_before_head_close(cleaned, head)))
    digests = list(dict.fromkeys(digest for _route, html in staged for digest in _ASSET_REF.findall(html)))
    states = blobs.custody_states(digests) if digests else {}
    unreadable = [digest for digest in digests if states.get(digest) is not CustodyState.READABLE]
    warnings += [f"image or font {digest[:12]} is not readable: the published page will serve a 404 where it goes" for digest in unreadable]
    manifest: JsonObject = {
        "schema_version": 2,
        "kind": "publish",
        "delivery": SITE_DELIVERY,
        "document_id": document["id"],
        "doc_version": document["current_version"],
        "page_id": "/",
        "pages": [{"page_id": route, "route": route, "html_digest": web_export._sha256(html)} for route, html in staged],
        "runtime": {"platform_version": 2, "custom_component_contract_version": None},
        "custom_components": {},
        "fragments": {"ids": _clone_ids(site), "missing": [], "asset_digests": digests, "missing_asset_digests": unreadable},
        "agent_sections": dict(site.get("agent_sections") or {}),
        "asset_digests": [],
        "warnings": warnings,
        **web_export._font_manifest_entries(gate),
        "slug": slug,
        "canonical_url": site_address.page_url("/"),
        **({"robots": "noindex"} if noindex else {}),
    }
    manifest_digest = web_export._sha256(web_export._canonical_json(manifest))
    manifest_head = (
        '<meta http-equiv="Content-Security-Policy" content="'
        f'{web_export._escape_attr(site_delivery_csp(meta=True))}">\n'
        f'<meta name="lumen-publish-manifest-digest" content="{manifest_digest}">\n'
        '<link rel="lumen-publish-manifest" href="'
        f'{web_export._escape_attr(f"{site_address.site_path}/manifest.json")}">\n'
    )
    pages: list[web_export.PublishedPage] = []
    for route, html in staged:
        final = web_export._inject_before_head_close(html, manifest_head)
        pages.append(web_export.PublishedPage(page_id=route, route=route, html=final, html_digest=web_export._sha256(final)))
    served = next(page for page in pages if page.route == "/")
    package_digest = web_export._sha256(
        web_export._canonical_json(
            {"manifest_digest": manifest_digest, "page_html_digests": sorted(page.html_digest for page in pages), "asset_digests": []}
        )
    )
    return web_export.PublishPackage(
        html=served.html,
        manifest=manifest,
        assets={},
        package_digest=package_digest,
        manifest_digest=manifest_digest,
        html_digest=served.html_digest,
        runtime_version=None,
        warnings=warnings,
        pages=pages,
    )


_EXTENSION_BY_MEDIA = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "image/avif": "avif", "image/svg+xml": "svg", "video/mp4": "mp4",
    "font/woff2": "woff2", "font/woff": "woff", "font/ttf": "ttf", "font/otf": "otf",
}


def _export_head() -> str:
    return (
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{web_export._escape_attr(site_delivery_csp(meta=True, static_bundle=True))}">\n'
    )


def build_site_export_bundle(
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    generated_at: str,
    node_bin: str = "node",
) -> web_export.ExportBundle:
    """A self-contained static copy of the site: one folder per page, every stored byte it names
    under assets/, links in folder form, the site policy with ``file:`` for its own files."""
    site = document["scene"]
    brand, gate = gated_brand(brand, repo, blobs)
    render = render_site(site, brand, sections, base_path="", node_bin=node_bin)
    routes = [page.route for page in render.pages]
    files: dict[str, bytes] = {}
    warnings = [*gate.warnings, *render.warnings]
    copied: dict[str, str | None] = {}

    def asset_path(digest: str) -> str | None:
        if digest not in copied:
            try:
                media_type, data = blobs.read_blob(digest)
            except NotFoundError:
                copied[digest] = None
                warnings.append(f"image or font {digest[:12]} is missing from the asset store; the export keeps its reference")
            else:
                path = f"assets/{digest}.{_EXTENSION_BY_MEDIA.get(media_type.split(';')[0].strip(), 'bin')}"
                files[path] = data
                copied[digest] = path
        return copied[digest]

    pages: list[JsonObject] = []
    for page in render.pages:
        html = web_export.rewrite_zip_links(sanitize_site_html(site_page_html(page, render.css)).html, routes)
        prefix = web_export._relative_prefix(page.route)

        def repoint(match: "re.Match[str]", prefix: str = prefix) -> str:
            path = asset_path(match.group(1))
            return f"{prefix}{path}" if path else match.group(0)

        html = web_export._inject_before_head_close(_ASSET_REF.sub(repoint, html), _export_head())
        path = web_export._zip_page_path(page.route)
        files[path] = html.encode("utf-8")
        pages.append({"route": page.route, "path": path})
    files["manifest.json"] = json.dumps(
        {
            "schema_version": 1,
            "kind": "export",
            "delivery": SITE_DELIVERY,
            "document_id": document["id"],
            "doc_version": document["current_version"],
            "generated_at": generated_at,
            "pages": pages,
            "assets": sorted(path for path in copied.values() if path),
            "warnings": warnings,
            **web_export._font_manifest_entries(gate),
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return web_export.ExportBundle(files=files, warnings=warnings)


def build_site_pdf(
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    brand: JsonObject,
    sections: Sequence[SectionModule],
    node_bin: str = "node",
) -> bytes:
    """Every page of the site printed at the tablet layout, in route order (web_pdf's posture)."""
    brand, _gate = gated_brand(brand, repo, blobs)
    render = render_site(document["scene"], brand, sections, base_path="", node_bin=node_bin)
    cache: dict[str, str | None] = {}
    htmls: list[str] = []
    for page in render.pages:
        cleaned = sanitize_site_html(site_page_html(page, render.css)).html
        inlined, _missing = inline_asset_store_refs(cleaned, blobs.read_blob, cache=cache)
        htmls.append(inlined)
    return web_pdf.render_pages_pdf(htmls, runtime=None, hardened=True)
