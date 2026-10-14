"""Builders that turn a stored Puck site into something people see: the gallery thumbnail (Task
18) and the publish package (Task 20). Both render through ``site_render.render_site`` (agent code
only inside the hardened page) and clean the result with ``site_sanitize.sanitize_site_html``
before anything sees it. A site has no ZIP or PDF export (founder ruling 2026-10-13: hosting on
the platform is the only delivery).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from typing import Any

from clue_design.publishes import PUBLISH_ASSET_MEDIA_TYPES, SITE_LIVE_DELIVERY, delivery_csp

from . import web_export
from .design_store import CustodyState
from .public_address import PublicSiteAddress
from .site_doc_validate import SiteDocumentInvalid, check_site_document
from .site_live import (
    import_map_element,
    import_map_json,
    live_page_html,
    live_runtime,
    script_hash,
)
from .site_render import (
    RenderedPage,
    SectionModule,
    capture_site_screenshot,
    pinned_modules,
    render_site,
    site_page_html,
)
from .site_sanitize import sanitize_site_html, site_html_problems
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


#: A live page is checked, never stripped (publishing live sites, phase 1): the browser's React must
#: find exactly what the server drew, so a page with anything the cleaner would remove is refused.
_UNSAFE_MARKUP = (
    "This page has something a live page can't carry (for example a frame or a script). "
    "Ask the agent to fix the section, then publish again."
)


def _section_not_approved(label: str | None) -> str:
    named = f': "{label}"' if label else ""
    return f"This page uses a section that isn't approved yet{named}. Approve your brand kit, then publish again."


_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")


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


def site_delivery_csp(*, meta: bool) -> str:
    """The site policy (``clue_design.publishes.delivery_csp`` for ``delivery="site"``)."""
    return delivery_csp(meta=meta, delivery=SITE_DELIVERY)


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


def _policy_before_import_map(html: str, import_map: str, manifest_head: str) -> str:
    """A live page with its CSP meta (and the manifest back-reference) immediately before its
    inline import map, so the meta policy covers every script on the page: a meta policy governs
    only what the parser meets after it. The import map is the last thing in the head
    (``site_live.live_page_html``), and nothing earlier can hold ``</head>`` (the site CSS has every
    ``</`` escaped), so the first match is the page's own."""
    tail = import_map_element(import_map) + "</head>"
    if tail not in html:
        raise ValueError("a live page lost its import map before the policy went in")
    return html.replace(tail, manifest_head + tail, 1)


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
    live: bool = False,
) -> web_export.PublishPackage:
    """One immutable publish package for a Puck site, same shape as the WebDoc one.

    Order: the modules the site pins (missing or stale refuses, ``render.section_module_missing``),
    the clone pins, the licence-gated fonts, the contract checks, the hardened render at the site's
    own path, the cleaner over each whole page, our head, the manifest (``delivery: "site"``, an
    empty ``custom_components``), and the CSP meta + manifest back-reference. Every URL it mints is
    root-relative except ``og:image``, as on the web path.

    ``live`` (publishing live sites, phase 1): the render also returns each page's data; each whole
    page is CHECKED with ``site_html_problems`` and refused (``site_publish.unsafe_markup``) when the
    cleaner would remove anything, never stripped; it gains the inline import map, its page data and
    the site runtime (``site_live.live_page_html``); the runtime, the three host shims and the pinned
    agent section modules ship as the package's ``.js`` assets; and it is served under the live policy
    (``delivery: "site_live"``, the import map allowed by its hash)."""
    site = document["scene"]
    modules = pinned_modules(site, sections)
    status = fragment_status or (lambda fragment_id: (repo.find_web_fragment(fragment_id) or {}).get("status"))
    check_clone_pins(site, brand, status)
    brand, gate = gated_brand(brand, repo, blobs)
    errors = check_site_document(site, document_id=str(document["id"]), brand=brand, sections=sections, blobs=blobs, node_bin=node_bin)
    if errors:
        raise SiteDocumentInvalid(errors)
    files: dict[str, bytes] = {}
    if live:
        runtime = live_runtime()
        runtime_digest = hashlib.sha256(runtime.runtime_js).hexdigest()
        files[runtime_digest] = runtime.runtime_js
        shim_urls: dict[str, str] = {}
        for specifier, data in runtime.shims.items():
            digest = hashlib.sha256(data).hexdigest()
            files[digest] = data
            shim_urls[specifier] = f"/p-assets/{digest}.js"
        for module in modules:
            files[module.digest] = module.module_js.encode("utf-8")
        section_urls = {module.name: f"/p-assets/{module.digest}.js" for module in modules}
        import_map = import_map_json(shim_urls)
        hashes = [script_hash(import_map)]
    render = render_site(site, brand, sections, base_path=site_address.link_path, node_bin=node_bin, live=live)
    origin = site_address.origin.rstrip("/")
    og_image = f"{origin}/asset-store/{default_social_preview_sha256}" if default_social_preview_sha256 else None
    warnings = [*gate.warnings, *render.warnings]
    staged: list[tuple[str, str]] = []
    for page in render.pages:
        head = _site_page_head(title=_page_title(site, page.route), description=default_description or "", og_image=og_image, noindex=noindex)
        if live:
            whole = site_page_html(page, render.css)
            if site_html_problems(whole):
                raise SitePublishRefused("site_publish.unsafe_markup", _UNSAFE_MARKUP)
            staged.append(
                (
                    page.route,
                    live_page_html(
                        web_export._inject_before_head_close(whole, head),
                        page.data,
                        section_urls=section_urls,
                        import_map=import_map,
                        runtime_url=f"/p-assets/{runtime_digest}.js",
                    ),
                )
            )
            continue
        cleaned = sanitize_site_html(site_page_html(page, render.css)).html
        staged.append((page.route, web_export._inject_before_head_close(cleaned, head)))
    digests = list(dict.fromkeys(digest for _route, html in staged for digest in _ASSET_REF.findall(html)))
    states = blobs.custody_states(digests) if digests else {}
    unreadable = [digest for digest in digests if states.get(digest) is not CustodyState.READABLE]
    warnings += [f"image or font {digest[:12]} is not readable: the published page will serve a 404 where it goes" for digest in unreadable]
    manifest: JsonObject = {
        "schema_version": 2,
        "kind": "publish",
        "delivery": SITE_LIVE_DELIVERY if live else SITE_DELIVERY,
        "document_id": document["id"],
        "doc_version": document["current_version"],
        "page_id": "/",
        "pages": [{"page_id": route, "route": route, "html_digest": web_export._sha256(html)} for route, html in staged],
        "runtime": {"platform_version": 2, "custom_component_contract_version": None},
        "custom_components": {},
        "fragments": {"ids": _clone_ids(site), "missing": [], "asset_digests": digests, "missing_asset_digests": unreadable},
        "agent_sections": dict(site.get("agent_sections") or {}),
        "asset_digests": sorted(files),
        "warnings": warnings,
        **web_export._font_manifest_entries(gate),
        "slug": slug,
        "canonical_url": site_address.page_url("/"),
        **({"robots": "noindex"} if noindex else {}),
    }
    if live:
        manifest["live"] = {
            "runtime": runtime_digest,
            "script_hashes": hashes,
            "assets": [{"digest": digest, "extension": "js", "media_type": PUBLISH_ASSET_MEDIA_TYPES["js"]} for digest in sorted(files)],
        }
    policy = delivery_csp(meta=True, delivery=SITE_LIVE_DELIVERY, script_hashes=hashes) if live else site_delivery_csp(meta=True)
    manifest_digest = web_export._sha256(web_export._canonical_json(manifest))
    manifest_head = (
        '<meta http-equiv="Content-Security-Policy" content="'
        f'{web_export._escape_attr(policy)}">\n'
        f'<meta name="lumen-publish-manifest-digest" content="{manifest_digest}">\n'
        '<link rel="lumen-publish-manifest" href="'
        f'{web_export._escape_attr(f"{site_address.site_path}/manifest.json")}">\n'
    )
    pages: list[web_export.PublishedPage] = []
    for route, html in staged:
        if live:
            final = _policy_before_import_map(html, import_map, manifest_head)
        else:
            final = web_export._inject_before_head_close(html, manifest_head)
        pages.append(web_export.PublishedPage(page_id=route, route=route, html=final, html_digest=web_export._sha256(final)))
    served = next(page for page in pages if page.route == "/")
    package_digest = web_export._sha256(
        web_export._canonical_json(
            {"manifest_digest": manifest_digest, "page_html_digests": sorted(page.html_digest for page in pages), "asset_digests": sorted(files)}
        )
    )
    return web_export.PublishPackage(
        html=served.html,
        manifest=manifest,
        assets=files,
        package_digest=package_digest,
        manifest_digest=manifest_digest,
        html_digest=served.html_digest,
        runtime_version=None,
        warnings=warnings,
        pages=pages,
    )
