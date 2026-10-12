"""Website-mode static export + publish build pipeline (P4).

Pure build functions with no FastAPI imports so they stay unit-testable. Two
entry points share one pipeline:

* ``build_export_bundle`` — a self-contained folder-in-a-zip: delivery render +
  license-gated embedded font files (relative ``fonts/…`` urls) + copied,
  extensioned image bytes (``assets/…``) + a statically compiled Tailwind
  ``site.css`` linked from the html + SEO metas + a ``manifest.json``.
* ``build_publish_html`` — a single self-contained html for same-origin serving:
  root-relative ``/asset-store/{digest}`` asset + font urls (served by the digest
  route with ``Access-Control-Allow-Origin: *``), the compiled css INLINED in a
  ``<style>`` tag, and SEO metas that name no host — the page is host-independent
  so the same bytes serve from the system hostname and from any custom domain
  (custom-domain publishing §6.1).

The static Tailwind compile shells out to ``scripts/web_static_css.mjs`` (the
editor app's own v4 toolchain) so an exported page styles identically to the
canvas. A non-zero exit raises ``WebExportCompileError`` carrying stderr —
export fails honestly rather than shipping an unstyled zip.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import tinycss2
from tinycss2 import ast

from clue_design.publishes import PUBLISH_ASSET_MEDIA_TYPES, delivery_csp
from clue_design.storage import SOURCE_KEY_ASSET, SOURCE_KEY_PUBLISH_ASSET

from .asset_custody import read_asset_bytes
from .custom_component_runtime import (
    CustomComponentRuntimeError,
    build_custom_component_delivery_package,
    default_runtime_host_path,
    web_doc_uses_custom_components,
)
from .database import NotFoundError
from .design_store import CustodyState, DesignBlobStore
from .font_containers import (
    SFNT_MIME,
    FontContainerError,
    encode_woff2,
    sniff_font_container,
)
from .fragments.abm_page import unresolved_account_markers
from .fragments.render import (
    build_fragment_render_package_for_document,
    css_class_names,
    empty_fragment_render_package,
    fragment_class_collisions,
    fragment_css_sheet,
    fragment_render_map,
    web_doc_all_fragment_ids,
    web_doc_fragment_ids,
)
from .public_address import PublicSiteAddress

JsonObject = Dict[str, Any]

# apps/api/lumen_api/web_export.py -> parents[3] is the repo root (havana/),
# where scripts/web_static_css.mjs lives and the node compile must run.
REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_CSS_SCRIPT = "scripts/web_static_css.mjs"
PUBLISH_ASSET_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# The delivery-asset kinds a publish package can mint, and the ONE media type each one is
# served as (mirrors `_DeliveryAssetCatalog.add`'s call sites in custom_component_runtime), now
# imported from `clue_design.publishes` — the page origin serves these same assets and may not
# import `lumen_api`, so the extension↔media-type contract has ONE home (custom-domain
# publishing §6.2). `persist_publish_assets` refuses a record that disagrees with it, and the
# page origin's reader refuses to SERVE a blob whose recorded media type is not the one the
# requested extension names.
#
# Stored on a delivery asset the manifest does not describe: it is durable, but nothing can
# name an extension for it, so no publish URL will ever serve it.
UNSERVABLE_ASSET_MEDIA_TYPE = "application/octet-stream"

# The page id a legacy single-page WebDoc carries, and the id `_home_page` prefers when a
# document has one. Since F5 a document is a LIST of pages and the primary page is the one whose
# route is `/`, so this is no longer "the page a delivery build renders" — it is a compatibility
# anchor for documents that predate routes.
HOME_PAGE_ID = "home"

#: One `href="…"` attribute, for the internal-link rewrite below.
_HREF_ATTR = re.compile(r'href="([^"]*)"')


def _rewrite_hrefs(html: str, mapping: Dict[str, str]) -> str:
    """Replace `href="<key>"` with `href="<value>"` for EXACT key matches, and nothing else.

    Exactness is the whole safety property. A cloned band's `/careers`, a `/asset-store/<digest>`
    byte reference, an absolute `https://…` CTA and a `src=` attribute all pass through
    untouched, because the only thing this can rewrite is a value the document itself declared
    as one of its own routes.
    """
    if not mapping:
        return html

    def _sub(match: "re.Match[str]") -> str:
        replacement = mapping.get(match.group(1))
        return match.group(0) if replacement is None else f'href="{replacement}"'

    return _HREF_ATTR.sub(_sub, html)


def rewrite_site_links(html: str, routes: Sequence[str], site_path: str) -> str:
    """Point this document's own internal links at the address the SITE is served from (F5).

    A multi-page document's pages link to each other by ROUTE (`href="/pricing"`) — that is what
    the author wrote and what the editor navigates. The served site does not live at the root of
    an origin, though: it lives under ``/{slug}`` on the workspace's hostname, so a route left
    alone would walk the visitor off the site entirely. This rebases every link whose value is
    exactly one of ``routes``; route ``/`` becomes ``site_path`` itself, every other route becomes
    ``site_path + route``.

    Nothing else is touched — see :func:`_rewrite_hrefs`.
    """
    mapping = {
        route: (site_path if route == "/" else f"{site_path}{route}")
        for route in routes
        if isinstance(route, str) and route
    }
    return _rewrite_hrefs(html, mapping)


def _zip_page_path(route: str) -> str:
    """Where a page's html lands inside the export zip: `/` → ``index.html``, `/pricing` →
    ``pricing/index.html``. One folder per page, so a static host serves each route from its
    directory index."""
    trimmed = route.strip("/")
    return "index.html" if not trimmed else f"{trimmed}/index.html"


def rewrite_zip_links(html: str, routes: Sequence[str]) -> str:
    """The export zip's own form of :func:`rewrite_site_links`.

    The zip has no site path — it IS the site root — so a route rewrites to itself, in FOLDER
    form (`/pricing` → `/pricing/`), which is what makes a static host serve
    ``pricing/index.html`` for it. Route ``/`` stays ``/`` rather than becoming the empty string:
    an empty href means "this document", so from ``/pricing/`` it would be a link to itself
    instead of a link home.
    """
    mapping = {
        route: ("/" if route.strip("/") == "" else f"/{route.strip('/')}/")
        for route in routes
        if isinstance(route, str) and route
    }
    return _rewrite_hrefs(html, mapping)

# Clone-fidelity F4.3, ruling R25-4: the whole of the `noindex` publish option, as one line.
# CP2's ABM account pages are reachable by their explicit URL and by nothing else (they are
# absent from every navigation, because the campaign shells have no way out) — so they must also
# be absent from the index. Per page, never global.
ROBOTS_NOINDEX_META = '<meta name="robots" content="noindex">'

#: One anchor tag, for the escape-route audit below.
_ANCHOR_TAG = re.compile(r"<a\b[^>]*>", re.I)
_ANCHOR_HREF = re.compile(r'href\s*=\s*["\'](https?://[^"\']+)["\']', re.I)


def _escape_route_audit(html: str) -> List[str]:
    """Absolute off-page anchor destinations, minus the footer's legal links (F4 wave F-1c).

    An ABM page exists to hold one visitor on one argument, and the rubric makes any link
    beyond the CTA and the legal links BLOCKING — but the shape gate governs only the shells,
    so a cloned proof band's press links or a composed band's resource links reach the page
    ungated. This audit does not refuse (a clone's own anchors are somebody's real markup,
    D-F6's evidence); it makes the doors VISIBLE on the publish manifest so a human judges
    them instead of discovering them from analytics.
    """
    destinations: List[str] = []
    for tag in _ANCHOR_TAG.findall(html):
        if "lumen-shell-legal" in tag:
            continue
        href = _ANCHOR_HREF.search(tag)
        if href and href.group(1) not in destinations:
            destinations.append(href.group(1))
    return destinations

# SEO description budget.
DESCRIPTION_MAX = 155

# Font-file extension by leading magic bytes (design: wOF2/wOFF/OTTO, else ttf).
_FONT_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (b"wOF2", "woff2"),
    (b"wOFF", "woff"),
    (b"OTTO", "otf"),
)

# Image-file extension by the asset record's declared mime type.
_IMAGE_EXT_BY_MIME: Dict[str, str] = {
    "image/webp": "webp",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/svg+xml": "svg",
}

# Extension by media type for a byte a CLONED SECTION displays. Wider than the image table
# because a harvested section brings whatever the source site used — a GIF, an AVIF, a webfont
# behind an `@font-face` in its own CSS — and the type comes from the artifact row rather than
# from the document's asset record (a fragment's bytes have no document asset record at all).
# An unlisted type exports without an extension and says so: guessing one would make a static
# file server serve an image as something else.
_DELIVERY_EXT_BY_MIME: Dict[str, str] = {
    **_IMAGE_EXT_BY_MIME,
    "image/gif": "gif",
    "image/avif": "avif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "font/woff2": "woff2",
    "font/woff": "woff",
    "font/ttf": "ttf",
    "font/otf": "otf",
    "application/font-woff2": "woff2",
    "application/font-woff": "woff",
}


class WebExportError(Exception):
    """A website-mode build failed for a reason the caller should surface."""


class WebExportCompileError(WebExportError):
    """The static Tailwind compile (node) exited non-zero; ``stderr`` carries
    the toolchain's message so the endpoint can report it honestly."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.stderr = message


class WebExportToolchainMissing(WebExportCompileError):
    """The node toolchain the static compile shells out to is not installed here.

    A subclass rather than a flag, because the two failures need different words from whoever
    reports them: "the compile ran and rejected your CSS" is about the input, and "there is no
    compiler on this machine" is about the environment. A caller that only knows
    ``WebExportCompileError`` still catches it and is no worse off than before."""


class WebExportUnresolvedMarkers(WebExportError):
    """A publish was asked for a page that still shows its `{{account.…}}` markers (R25-7).

    Not a build failure — the build succeeded, and what it built is a TEMPLATE. So the caller
    maps it to a 422 naming the remedy (derive it for an account, publish the derived page)
    rather than to the 502 every other :class:`WebExportError` becomes.
    """

    def __init__(self, message: str, markers: Sequence[str]) -> None:
        super().__init__(message)
        self.markers = tuple(markers)


def persist_publish_assets(
    blobs: DesignBlobStore,
    assets: Dict[str, bytes],
    asset_records: Optional[List[JsonObject]] = None,
) -> None:
    """Persist immutable public delivery bytes under their verified digest.

    D4: the bytes land in platform storage (``{workspace}/design/{sha256}``) through the
    row-before-blob seam instead of the API-local ``publish/sha256/{ab}/{digest}`` tree, and
    the ``{digest}.meta.json`` sidecar is **gone** — its only payload was the media type, which
    is now a column on the ``artifact`` row (ruling R-D4-3). The digest verification the sidecar
    era did is unchanged, and content addressing makes a re-publish of the same package a no-op
    (one row, one blob) rather than a collision check.

    An asset with no manifest record is still stored, under an opaque media type: nothing can
    honestly claim its extension, so the page origin's asset reader will refuse to serve it —
    exactly what the missing sidecar used to do.
    """

    records_by_digest = {
        str(record.get("digest")): record
        for record in (asset_records or [])
        if isinstance(record, dict)
        and isinstance(record.get("digest"), str)
    }
    for digest, data in assets.items():
        if not PUBLISH_ASSET_PATTERN.fullmatch(digest):
            raise WebExportError(f"invalid publish asset digest {digest!r}")
        if _sha256(data) != digest:
            raise WebExportError(
                f"publish asset bytes do not match digest {digest}"
            )
        record = records_by_digest.get(digest)
        media_type = UNSERVABLE_ASSET_MEDIA_TYPE
        if record is not None:
            extension = record.get("extension")
            declared = record.get("media_type")
            if (
                extension not in PUBLISH_ASSET_MEDIA_TYPES
                or not isinstance(declared, str)
                or declared != PUBLISH_ASSET_MEDIA_TYPES[str(extension)]
            ):
                raise WebExportError(
                    f"publish asset {digest} has invalid media metadata"
                )
            media_type = declared
        blobs.register(
            data, media_type=media_type, source_key=SOURCE_KEY_PUBLISH_ASSET
        )


@dataclass
class ExportBundle:
    """A ready-to-zip export: ``files`` maps zip-root-relative paths to bytes,
    ``warnings`` are non-fatal build notes (missing blobs, excluded fonts)."""

    files: Dict[str, bytes] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PublishedPage:
    """One page of a published site: the route it serves at and the bytes served there."""

    page_id: str
    route: str
    html: str
    html_digest: str


@dataclass
class PublishPackage:
    """One deterministic immutable publish payload and its delivery assets.

    ``pages`` is the whole site (F5), in document order. ``html``/``html_digest`` stay the
    page served at ``/`` so that every pre-F5 caller — the publish row's denormalized html,
    ``build_publish_html``, the batch — keeps meaning exactly what it meant when a document
    had one page.
    """

    html: str
    manifest: JsonObject
    assets: Dict[str, bytes]
    package_digest: str
    manifest_digest: str
    html_digest: str
    runtime_version: Optional[int]
    warnings: List[str] = field(default_factory=list)
    pages: List[PublishedPage] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Font resolution (license-gated)                                             #
# --------------------------------------------------------------------------- #


@dataclass
class _FontFace:
    digest: str
    family: str
    weight: int
    style: str
    ext: str
    data: bytes


def _font_ext(data: bytes) -> str:
    for magic, ext in _FONT_MAGIC:
        if data[:4] == magic:
            return ext
    return "ttf"


def _valid_weight(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000:
        return value
    return 400


def _valid_style(value: Any) -> str:
    return value if value in ("normal", "italic") else "normal"


def _family_embeddable(license_obj: Any) -> bool:
    """A family's faces are embeddable when its license is explicitly
    embeddable OR its license name marks the OFL (the whole font library is
    OFL-licensed, hence always embeddable).

    ``basis`` (D-F2, a real ``FontLicense`` field since F1.5) says WHY a family
    may embed when the license ``name`` cannot — a workspace's own brand font
    carries ``basis: "platform-terms"`` beside ``embeddable: true``, and that
    pair passes here. It is deliberately NOT a third way to pass: a basis on a
    family whose license says ``embeddable: false`` still fails, because a
    stated rationale is not permission. The gate reads the basis so it can be
    REPORTED (:func:`font_license_basis` puts it in the manifest beside the
    included family) rather than so it can widen the door.
    """
    if not isinstance(license_obj, dict):
        return False
    if license_obj.get("embeddable"):
        return True
    name = license_obj.get("name")
    return isinstance(name, str) and name.startswith("OFL")


def font_license_basis(license_obj: Any) -> Optional[str]:
    """The stated basis for a family's embed permission, or ``None``.

    Absent on every kit written before F1.5 and on every font whose license name
    IS the answer (``OFL-1.1``), which is why an absent value is a fact rather
    than a defect.
    """
    if not isinstance(license_obj, dict):
        return None
    basis = license_obj.get("basis")
    return basis if isinstance(basis, str) and basis.strip() else None


class _FontGate(NamedTuple):
    """What the license gate decided, in one value both build paths report from.

    ``bases`` is ``[{family, basis}]`` for the included families that STATE a basis (D-F2): a
    workspace's own brand font embeds under ``platform-terms``, and the manifest naming that is
    what lets a reader see why a font whose license name is ``unknown`` shipped anyway.
    """

    faces: List[_FontFace]
    excluded: List[JsonObject]
    bases: List[JsonObject]
    warnings: List[str]


def _web_face_bytes(
    blobs: DesignBlobStore, digest: str, data: bytes
) -> Tuple[bytes, str, str, Optional[str]]:
    """``(bytes_to_ship, ext, digest_to_name, warning)`` for one face on a web page.

    Option A (2026-09-02) keeps every stored font as sfnt; a page wants the compressed wrapper
    back. The re-encode is byte-deterministic, so registering it content-addressed is idempotent
    across publishes, and the hosted page's ``/asset-store/{digest}`` then names the WOFF2 blob
    (that route serves any registered digest). Bytes that are not sfnt — a legacy face the
    backfill has not reached, or a test's fake payload — pass through untouched; an encode
    failure ships the sfnt with a warning rather than dropping the face.
    """
    if sniff_font_container(data) not in SFNT_MIME:
        return data, _font_ext(data), digest, None
    try:
        woff2 = encode_woff2(data)
    except FontContainerError as error:
        return (
            data,
            _font_ext(data),
            digest,
            f"font face {digest[:12]} shipped as {_font_ext(data)}: WOFF2 encode failed ({error})",
        )
    blobs.register(woff2, media_type="font/woff2", source_key=SOURCE_KEY_ASSET)
    return woff2, "woff2", hashlib.sha256(woff2).hexdigest(), None


def _gather_fonts(
    brand_kit: Optional[JsonObject],
    repo: Any,
    blobs: DesignBlobStore,
) -> _FontGate:
    """Resolve the kit's embeddable font faces to bytes.

    ``faces`` are the included faces (deduped by digest), ``excluded`` is
    ``[{family, reason}]`` for license-blocked families, ``bases`` names the
    stated embed basis of each included family that has one, and ``warnings``
    mirrors the exclusions (plus any missing-blob notes) for the top-level
    warning list.
    """
    fonts = ((brand_kit or {}).get("assets") or {}).get("fonts") or {}
    faces: List[_FontFace] = []
    excluded: List[JsonObject] = []
    bases: List[JsonObject] = []
    warnings: List[str] = []
    seen: set[str] = set()
    for font in fonts.values():
        if not isinstance(font, dict):
            continue
        family = font.get("family")
        if not (isinstance(family, str) and family.strip()):
            continue
        if not _family_embeddable(font.get("license")):
            excluded.append({"family": family, "reason": "license not embeddable"})
            warnings.append(
                f"font family {family} excluded from export: license not embeddable"
            )
            continue
        basis = font_license_basis(font.get("license"))
        if basis is not None and not any(entry["family"] == family for entry in bases):
            bases.append({"family": family, "basis": basis})
        for face in font.get("faces") or []:
            if not (isinstance(face, dict) and face.get("asset_id")):
                continue
            try:
                record = repo.require_asset_record(str(face["asset_id"]))
            except Exception:
                continue
            asset = record.get("asset") or record
            digest = ((asset.get("media") or {}).get("digest") or {}).get("value")
            if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
                continue
            if digest in seen:
                continue
            # D4: a pure-Python read — the face bytes go straight into the zip, so they come
            # from durable storage rather than a round trip through the engine cache.
            data = read_asset_bytes(blobs, digest)
            if data is None:
                warnings.append(
                    f"font face {digest[:12]} for family {family} skipped: "
                    "bytes missing from the asset store"
                )
                continue
            seen.add(digest)
            data, ext, shipped_digest, note = _web_face_bytes(blobs, digest, data)
            if note is not None:
                warnings.append(note)
            faces.append(
                _FontFace(
                    digest=shipped_digest,
                    family=family,
                    weight=_valid_weight(face.get("weight")),
                    style=_valid_style(face.get("style")),
                    ext=ext,
                    data=data,
                )
            )
    return _FontGate(faces=faces, excluded=excluded, bases=bases, warnings=warnings)


def _font_face_css(faces: List[_FontFace], url_for: Any) -> Optional[str]:
    if not faces:
        return None
    rules: List[str] = []
    for face in faces:
        rules.append(
            "@font-face{"
            f"font-family:{json.dumps(face.family)};"
            f"font-style:{face.style};font-weight:{face.weight};"
            "font-display:swap;"
            f"src:url({json.dumps(url_for(face))});"
            "}"
        )
    return "\n".join(rules)


# --------------------------------------------------------------------------- #
# Document scans (assets + SEO description)                                    #
# --------------------------------------------------------------------------- #


def _home_page(web_doc: JsonObject) -> JsonObject:
    pages = web_doc.get("pages") or []
    for page in pages:
        if isinstance(page, dict) and page.get("id") == HOME_PAGE_ID:
            return page
    return pages[0] if pages else {}


def _page_by_id(web_doc: JsonObject, page_id: str) -> JsonObject:
    for page in web_doc.get("pages") or []:
        if isinstance(page, dict) and page.get("id") == page_id:
            return page
    return {}


class _SitePage(NamedTuple):
    """One page a delivery build renders: its engine id and the route it serves at."""

    page_id: str
    route: str


def _site_pages(web_doc: JsonObject) -> List[_SitePage]:
    """Every page a delivery build renders, in document order (F5).

    The route is the page's own ``route`` field. A page that carries none is only tolerated in
    the FIRST position, where "no route" can only have meant ``/`` — that is the shape every
    pre-F5 document has, and reading it as ``/`` is what keeps a legacy publish byte-identical.
    A later page with no route is skipped rather than given an invented one: a route is the
    page's address, and guessing an address publishes a page at a URL nobody asked for.
    """
    pages: List[_SitePage] = []
    for index, page in enumerate(web_doc.get("pages") or []):
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        if not (isinstance(page_id, str) and page_id):
            continue
        route = page.get("route")
        if not (isinstance(route, str) and route.startswith("/")):
            if index != 0:
                continue
            route = "/"
        pages.append(_SitePage(page_id=page_id, route=route))
    if not pages:
        # A document with no usable page still has to produce one render, exactly as it did
        # before F5 — the engine answers for `home` and the delivery build serves it at `/`.
        return [_SitePage(page_id=HOME_PAGE_ID, route="/")]
    return pages


def _primary_page(pages: Sequence[_SitePage]) -> _SitePage:
    """The page a site's bare address serves: the one routed ``/``, else the first."""
    for page in pages:
        if page.route == "/":
            return page
    return pages[0]


def _walk_nodes(page: JsonObject):
    """Yield nodes of ``page`` in document order (preorder DFS from root)."""
    nodes = page.get("nodes") or {}
    root = page.get("root")
    stack = [root]
    guard = 0
    while stack:
        guard += 1
        if guard > 100_000:  # cycle guard; a valid doc never approaches this
            return
        node_id = stack.pop()
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        yield node
        children = node.get("children") or []
        # Push reversed so children are visited left-to-right.
        for child_id in reversed(children):
            stack.append(child_id)


def _node_asset_ids(node: JsonObject) -> List[Tuple[str, str]]:
    """``[(origin, asset_id)]`` for every registered document asset ONE node displays.

    The class of gap this closes (F1.5): the walk below used to ask only "is this an image
    node", so every other way a node names bytes was invisible to the export — the bytes never
    entered the zip and the delivered page painted nothing, silently.

    Three ways exist today, and they are enumerated here rather than at the call site so a
    fourth is added in one place:

    * ``image`` nodes — ``asset_id`` (the original walk).
    * ``section`` / ``container`` backgrounds — ``background.asset_id``, a typed field the
      engine renders as a CSS ``background-image``. This is the RECORDED background-image gap.
    * ``fragment`` nodes — an asset bound into an image slot (``{"asset": "<id>"}``), which is
      how an account's own logo reaches a cloned section.
    """
    found: List[Tuple[str, str]] = []
    kind = node.get("kind")
    if kind == "image":
        asset_id = node.get("asset_id")
        if isinstance(asset_id, str) and asset_id:
            found.append(("image", asset_id))
    background = node.get("background")
    if isinstance(background, dict):
        asset_id = background.get("asset_id")
        if isinstance(asset_id, str) and asset_id:
            found.append(("background", asset_id))
    if kind == "fragment":
        slots = node.get("slots")
        if isinstance(slots, dict):
            for value in slots.values():
                asset_id = value.get("asset") if isinstance(value, dict) else None
                if isinstance(asset_id, str) and asset_id:
                    found.append(("fragment_slot", asset_id))
    return found


def _document_asset_references(web_doc: JsonObject) -> List[Tuple[str, str]]:
    """``[(origin, asset_id)]`` across every page, document order, image nodes first.

    Image nodes lead so that widening the walk cannot reorder what an existing consumer sees
    first (``og:image``); everything after them is new territory.
    """
    found: List[Tuple[str, str]] = []
    for page in web_doc.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for node in _walk_nodes(page):
            found.extend(_node_asset_ids(node))
    return sorted(found, key=lambda entry: entry[0] != "image")


def _image_ext(mime: Any) -> str:
    return _IMAGE_EXT_BY_MIME.get(mime, "bin")


@dataclass
class _ImageAsset:
    asset_id: str
    digest: str
    ext: str
    mime: Optional[str]
    #: Why this asset ships: ``image`` / ``background`` / ``fragment_slot``.
    origin: str = "image"


def _resolve_images(web_doc: JsonObject) -> List[_ImageAsset]:
    """Every registered document asset the page displays, resolved from the WebDoc's own assets
    map (the records carry ``media.digest.value`` + ``mime_type``).

    Deduped by DIGEST, not by asset id: two records naming the same bytes are one file.
    """
    assets = web_doc.get("assets") or {}
    resolved: List[_ImageAsset] = []
    seen: set[str] = set()
    for origin, asset_id in _document_asset_references(web_doc):
        record = assets.get(asset_id)
        if not isinstance(record, dict):
            continue
        media = record.get("media") or {}
        digest = (media.get("digest") or {}).get("value")
        if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            continue
        if digest in seen:
            continue
        seen.add(digest)
        mime = media.get("mime_type")
        resolved.append(
            _ImageAsset(
                asset_id=asset_id,
                digest=digest,
                ext=_image_ext(mime),
                mime=mime,
                origin=origin,
            )
        )
    return resolved


# --------------------------------------------------------------------------- #
# Cloned sections (fragments) on the delivery paths                            #
# --------------------------------------------------------------------------- #


class _FragmentDelivery(NamedTuple):
    """Everything a delivery build needs to know about this page's cloned sections.

    Resolved ONCE per build and threaded into the render, the asset walk and the manifest, so
    the three cannot disagree about which artifacts the page means. The resolution itself is
    :func:`lumen_api.fragments.render.build_fragment_render_package` — the same call both
    preview paths make, deliberately not a second implementation, because a section that
    renders one way in the editor and another way in the zip is the failure this whole phase is
    about.
    """

    ids: List[str]
    package: JsonObject
    render_map: Dict[str, Any]
    css: Optional[str]
    #: Digests of the bytes the ARTIFACTS themselves display (their rehosted images and fonts).
    asset_digests: List[str]
    #: The subset of those whose bytes are no longer readable — filled by
    #: :func:`_sweep_fragment_asset_custody`, which BOTH delivery paths run.
    missing_asset_digests: List[str]
    missing: List[str]
    warnings: List[str]

    @property
    def manifest_entry(self) -> JsonObject:
        return {
            "ids": list(self.ids),
            "missing": list(self.missing),
            "asset_digests": list(self.asset_digests),
            "missing_asset_digests": list(self.missing_asset_digests),
        }


def _resolve_fragments(web_doc: JsonObject, blobs: DesignBlobStore) -> _FragmentDelivery:
    """Resolve this DOCUMENT's fragment artifacts for a delivery build.

    Fail-SOFT, exactly as the preview paths are: an id this workspace cannot resolve is named
    in ``missing`` (and in a warning that reaches the manifest) and the engine renders its
    placeholder. Refusing the export would make one dead pin cost the whole deliverable.

    F5: resolved once for every page, not once for ``home``. A render is still of one page —
    :func:`_page_fragment_view` narrows this package to the ids a given page actually pins —
    but the custody sweep, the asset copy and the manifest all answer for the whole site, and
    resolving each artifact once is what keeps them from disagreeing page to page.
    """
    ids = web_doc_all_fragment_ids(web_doc)
    if not ids:
        package = empty_fragment_render_package()
        return _FragmentDelivery(
            ids=[], package=package, render_map={}, css=None,
            asset_digests=[], missing_asset_digests=[], missing=[], warnings=[],
        )
    package = build_fragment_render_package_for_document(
        blobs.storage,
        workspace_id=blobs.workspace_id,
        web_doc=web_doc,
    )
    missing = [str(value) for value in package.get("missing") or []]
    digests: List[str] = []
    for fragment_id in ids:
        record = package.get("fragments", {}).get(fragment_id)
        if not isinstance(record, dict):
            continue
        for digest in record.get("asset_digests") or []:
            if isinstance(digest, str) and digest not in digests:
                digests.append(digest)
    warnings = [
        f"cloned section {fragment_id} could not be resolved: the page renders a placeholder"
        for fragment_id in missing
    ]
    return _FragmentDelivery(
        ids=ids,
        package=package,
        render_map=fragment_render_map(package, ids),
        css=fragment_css_sheet(package, ids),
        asset_digests=digests,
        missing_asset_digests=[],
        missing=missing,
        warnings=warnings,
    )


class _PageFragments(NamedTuple):
    """The document-wide fragment package, narrowed to ONE page's pins (F5)."""

    ids: List[str]
    render_map: Dict[str, Any]
    css: Optional[str]


def _page_fragment_view(
    fragments: _FragmentDelivery, web_doc: JsonObject, page_id: str
) -> _PageFragments:
    """What the engine is handed to render ``page_id``.

    Resolution is keyed on ``(workspace, fragment id)`` and never consults the page, so the
    document-wide package already holds every record this page needs — narrowing is a filter,
    never a second fetch. Narrowing matters because the fragment CSS rides in the page's OWN
    head: handing every page the whole site's sheets would ship a second page's cloned styles
    into the first one's cascade.
    """
    if not fragments.ids:
        return _PageFragments(ids=[], render_map={}, css=None)
    ids = web_doc_fragment_ids(web_doc, page_id)
    if not ids:
        return _PageFragments(ids=[], render_map={}, css=None)
    return _PageFragments(
        ids=ids,
        render_map=fragment_render_map(fragments.package, ids),
        css=fragment_css_sheet(fragments.package, ids),
    )


def _sweep_fragment_asset_custody(
    fragments: _FragmentDelivery, blobs: DesignBlobStore, *, consequence: str
) -> _FragmentDelivery:
    """Check that the bytes each cloned section names are still THERE, on both delivery paths.

    An artifact is immutable; the bytes it names are not immortal. A DSAR erasure, a purge, a
    backup restored without its object store — any of them leaves a fragment pointing at a
    digest that answers 404. The export path noticed only because it happens to READ every byte
    it copies; the publish path copies nothing, so it used to publish a page with a broken image
    and a manifest that looked clean. A clean manifest over a broken page is worse than a broken
    page, so the probe is explicit and shared, and the finding is identical on both sides.

    :meth:`DesignBlobStore.custody_states` is the right probe rather than a row check: the
    dangerous state is ``ROW_ONLY``, where the row claims custody the backend cannot honour and
    every row-level question answers "fine" while every byte route 404s.

    Neither path refuses. The section is otherwise sound, the rest of the page is a good
    deliverable, and the reference is left naming the digest route — which is the only honest
    thing left to point at. ``consequence`` is the one part that legitimately differs between
    the two builds, so it is the one part the caller supplies.
    """
    if not fragments.asset_digests:
        return fragments
    states = blobs.custody_states(fragments.asset_digests)
    missing = [
        digest
        for digest in fragments.asset_digests
        if states.get(digest) is not CustodyState.READABLE
    ]
    if not missing:
        return fragments
    return fragments._replace(
        missing_asset_digests=missing,
        warnings=[
            *fragments.warnings,
            *(
                f"cloned-section asset {digest[:12]} has no readable bytes in the asset "
                f"store; {consequence}"
                for digest in missing
            ),
        ],
    )


def _copy_fragment_assets(
    files: Dict[str, bytes],
    fragments: _FragmentDelivery,
    blobs: DesignBlobStore,
) -> Tuple[Dict[str, str], List[str]]:
    """Copy every byte the site's cloned sections display into the zip.

    Returns ``({digest: zip path}, warnings)``; the caller points each page's markup at those
    paths (a subpage prefixes them with its own ``../`` hop). The copy is done ONCE for the
    document, not once per page — the bytes are identical and the warnings would otherwise
    repeat for every page that happens to pin the same dead artifact.

    Missing bytes were already found and reported by :func:`_sweep_fragment_asset_custody`,
    which both delivery paths run — so a digest it named is skipped silently HERE rather than
    warned about twice, and the ``except`` below covers only the narrow race where a blob
    disappears between the sweep and this read (same outcome either way: no file, and the
    reference left naming the digest route).

    The media type comes from the artifact ROW rather than from a guess at the bytes — the
    digest route already serves these with that type — and an unrecognised one lands
    extension-less with a warning, because inventing ``.bin`` for an image would be a confident
    lie a static file server then acts on.
    """
    warnings: List[str] = []
    paths: Dict[str, str] = {}
    known_missing = set(fragments.missing_asset_digests)
    for digest in fragments.asset_digests:
        if digest in known_missing:
            continue
        try:
            media_type, data = blobs.read_blob(digest)
        except NotFoundError:
            warnings.append(
                f"cloned-section asset {digest[:12]} vanished between the custody sweep and "
                "the copy; the exported page keeps its /asset-store reference"
            )
            continue
        extension = _DELIVERY_EXT_BY_MIME.get(str(media_type).split(";")[0].strip())
        if extension is None:
            warnings.append(
                f"cloned-section asset {digest[:12]} stored with media type {media_type!r} "
                "has no known file extension; exported without one"
            )
        path = f"assets/{digest}.{extension}" if extension else f"assets/{digest}"
        files[path] = data
        paths[digest] = path
    return paths, warnings


def _point_at_copied_fragment_assets(
    html: str, paths: Dict[str, str], prefix: str
) -> str:
    """Repoint one page's `/asset-store/<digest>` references at the copies in the zip.

    An artifact's markup and CSS name their rehosted bytes as an ABSOLUTE `/asset-store/<digest>`
    path, which resolves against a filesystem root once the zip is unpacked. Both live in this
    one string (the fragment CSS rides in the head), so one pass covers both.
    """
    for digest, path in paths.items():
        html = html.replace(f"/asset-store/{digest}", f"{prefix}{path}")
    return html


def _fragment_cascade_warnings(
    fragments: _FragmentDelivery, site_css: str, ids: Optional[Sequence[str]] = None
) -> List[str]:
    """The cascade collision report, checked against the REAL compiled stylesheet.

    A preview can only compare a fragment's classes against the ones the document authors, and
    guess that the compiler will turn them into utilities. A delivery build does not have to
    guess: ``site.css`` has been compiled by this point, so "a live utility" means literally
    "a class this sheet declares". Same accepted risk, same warning-not-refusal posture — the
    strongest available form of the check.

    ``ids`` narrows the check to one page's pins (F5) — the compiled sheet is per page, so the
    collision question is per page too. Omitted, it asks about the whole document.
    """
    live = css_class_names(site_css)
    warnings: List[str] = []
    for fragment_id, classes in fragment_class_collisions(
        fragments.package, list(fragments.ids if ids is None else ids), live
    ):
        joined = ", ".join(classes)
        warnings.append(
            f"cloned section {fragment_id} styles {joined}, which the compiled site.css also "
            "declares; the compiled sheet is applied after the fragment CSS, so it wins and "
            "the cloned section loses those rules"
        )
    return warnings


def _seo_description(
    web_doc: JsonObject, fallback: str, page_id: Optional[str] = None
) -> str:
    """The first body Text node's text in document order, tags stripped and
    whitespace collapsed, truncated on a clean word boundary; the doc title
    when there is no body copy.

    ``page_id`` picks the page to read (F5) — a description is a property of the PAGE, so a
    pricing page must not be described by the home page's opening paragraph."""
    page = _page_by_id(web_doc, page_id) if page_id else _home_page(web_doc)
    for node in _walk_nodes(page):
        if node.get("kind") == "text" and node.get("variant") == "body":
            text = _collapse(_rich_text_plain(node.get("content")))
            if text:
                return _truncate(text, DESCRIPTION_MAX)
    return _truncate(_collapse(fallback), DESCRIPTION_MAX)


def _rich_text_plain(content: object) -> str:
    """Plain-text projection for canonical RichTextDocument JSON, with the
    previous inline-HTML string accepted only at this API boundary."""
    if isinstance(content, str):
        return _strip_tags(content)
    if not isinstance(content, dict):
        return ""
    parts: list[str] = []

    def append_blocks(blocks: object) -> None:
        if not isinstance(blocks, list):
            return
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            if block_index:
                parts.append("\n")
            append_inlines(block.get("children"))
            items = block.get("items")
            if isinstance(items, list):
                for item_index, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    if item_index:
                        parts.append("\n")
                    append_inlines(item.get("children"))
                    append_blocks(item.get("nested"))

    def append_inlines(inlines: object) -> None:
        if not isinstance(inlines, list):
            return
        for inline in inlines:
            if not isinstance(inline, dict):
                continue
            kind = inline.get("type")
            if kind == "text":
                parts.append(str(inline.get("text") or ""))
            elif kind == "variable":
                parts.append(str(inline.get("fallback") or ""))
            elif kind == "line_break":
                parts.append("\n")

    append_blocks(content.get("blocks"))
    return "".join(parts)


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    cut = value[:limit]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip()


# --------------------------------------------------------------------------- #
# HTML assembly helpers                                                        #
# --------------------------------------------------------------------------- #


def _escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _inject_before_head_close(html: str, snippet: str) -> str:
    """Insert ``snippet`` immediately before the first ``</head>`` (falling back
    to prepending when a doc somehow lacks a head — the render always emits
    one, so the fallback is defensive)."""
    needle = "</head>"
    index = html.find(needle)
    if index == -1:
        return snippet + html
    return html[:index] + snippet + html[index:]


def _seo_snippet(
    *,
    title: str,
    description: str,
    og_image: Optional[str],
    canonical: Optional[str] = None,
    og_url: Optional[str] = None,
) -> str:
    parts = [
        f'<meta name="description" content="{_escape_attr(description)}">\n',
        f'<meta property="og:title" content="{_escape_attr(title)}">\n',
        f'<meta property="og:description" content="{_escape_attr(description)}">\n',
    ]
    if og_image:
        parts.append(f'<meta property="og:image" content="{_escape_attr(og_image)}">\n')
    if canonical:
        parts.append(f'<link rel="canonical" href="{_escape_attr(canonical)}">\n')
    if og_url:
        parts.append(f'<meta property="og:url" content="{_escape_attr(og_url)}">\n')
    return "".join(parts)


def _runtime_version(html: str) -> Optional[int]:
    return 2 if "__lumenRuntimeV2" in html else None


# --------------------------------------------------------------------------- #
# Static Tailwind compile (node)                                              #
# --------------------------------------------------------------------------- #


class _CompiledTheme(NamedTuple):
    """The slice of the compiled theme the static compile needs: the color
    tokens, the brand-geometry variables, and the ``@utility`` rules for the
    geometry names Tailwind has no namespace for. All three are engine-owned
    (``theme.rs``) — nothing here hand-writes CSS the editor doesn't also get."""

    tokens: Dict[str, str]
    geometry: Dict[str, str]
    utility_css: str


def _theme_tokens(
    core: Any, web_doc: JsonObject, brand_kit: Optional[JsonObject]
) -> _CompiledTheme:
    """The compiled theme — exactly the surface GET web/theme reads
    (web_validate -> web_theme)."""
    response = core.web_validate(web_doc, brand_kit)
    theme = response.get("web_theme") or {}
    tokens = theme.get("tokens") or {}
    geometry = theme.get("geometry") or {}
    utility_css = theme.get("utility_css") or ""
    return _CompiledTheme(
        tokens={str(name): str(value) for name, value in tokens.items()},
        geometry={str(name): str(value) for name, value in geometry.items()},
        utility_css=str(utility_css),
    )


def _build_input_css(theme: _CompiledTheme) -> str:
    lines = ['@import "tailwindcss";', "@theme {"]
    for name, value in theme.tokens.items():
        lines.append(f"  --color-{name}: {value};")
    # Brand geometry rides in the same block; without it every geometry
    # utility silently no-ops on a published page while it works in the editor.
    for name, value in theme.geometry.items():
        lines.append(f"  --{name}: {value};")
    lines.append("}")
    css = "\n".join(lines) + "\n"
    # `@utility` is a top-level at-rule — it goes after the block.
    if theme.utility_css:
        css += theme.utility_css if theme.utility_css.endswith("\n") else theme.utility_css + "\n"
    return css


def _document_only_html(
    core: Any,
    web_doc: JsonObject,
    rendered: str,
    page_id: str = HOME_PAGE_ID,
    **render_kwargs: Any,
) -> str:
    """The page WITHOUT its cloned sections — the Tailwind scanner's input (clone-fidelity W7).

    A cloned fragment carries the class names of somebody else's site. The Tailwind compiler
    scans whatever html it is given and mints a utility for every class that looks like one, so
    scanning the delivered page makes the CLONE decide what the DOCUMENT's stylesheet contains:
    a source-site `hidden` or `mt-8` becomes a live utility that then applies to the document's
    own markup. A fragment is supposed to arrive with its styling sealed inside its own scoped
    sheet; this is the one place that seal leaked, and it leaked in the direction that is hardest
    to see, because the page still looks right until a document class happens to collide.

    So the scan runs over the document alone — the same render with no fragments and no fragment
    css — while the DELIVERED html is unchanged. It also makes `_fragment_cascade_warnings`
    honest: "a live utility" now means one the document really asked for, not one our own scan
    invented from the fragment we are checking.

    Falls back to the rendered page if the second render produces nothing, because a missing
    stylesheet is a worse failure than an over-broad one.

    **A page with no cloned sections is not re-rendered at all** (F3.4; the guard the F2 wave
    deferred). The second render exists only to take fragments OUT, so on a document that pins
    none it produces, by construction, the html already in hand — at the cost of a whole extra
    engine round trip on every export and publish of every ordinary page, which is most of them.
    Skipping it is not an optimisation of the scan's input; it is the same input, arrived at
    without asking twice.
    """
    if not web_doc_fragment_ids(web_doc, page_id):
        return rendered
    second = core.web_render(web_doc, page_id, fragments={}, fragment_css="", **render_kwargs)
    return (second.get("html") or "") or rendered


def require_static_css_toolchain(node_bin: str = "node") -> None:
    """Refuse, typed and by name, when the Tailwind compile cannot possibly run.

    The compile is a subprocess into the EDITOR app's own node toolchain
    (``scripts/web_static_css.mjs`` + ``apps/editor/node_modules/@tailwindcss/*``), which is a
    dependency no ``pyproject.toml`` can declare. Publish has always needed it and has always
    been run from a full checkout; F3.1 put it behind an agent tool call
    (:func:`compile_section_css`), where "node is not installed" is a plausible environment
    rather than a broken one.

    So the missing piece is named BEFORE anything is spent, and named specifically — "node is not
    on PATH" and "the editor's node_modules were never installed" are different problems with
    different fixes, and a caller that reports "compile failed" for both sends its operator
    looking in the wrong place.
    """
    if shutil.which(node_bin) is None:
        raise WebExportToolchainMissing(
            f"the static CSS compile needs node on PATH (looked for {node_bin!r}). "
            "Install node, or point the caller at a node binary."
        )
    script = REPO_ROOT / STATIC_CSS_SCRIPT
    if not script.is_file():
        raise WebExportToolchainMissing(
            f"the static CSS compile script is missing: {script}"
        )
    toolchain = REPO_ROOT / "apps/editor/node_modules/@tailwindcss/node"
    if not toolchain.is_dir():
        raise WebExportToolchainMissing(
            "the editor app's Tailwind toolchain is not installed "
            f"({toolchain} is absent). Run `npm install` in apps/editor."
        )


def compile_tailwind_css(html: str, input_css: str, node_bin: str, timeout_seconds: int = 120) -> str:
    """Run the editor's Tailwind v4 toolchain (``scripts/web_static_css.mjs``) over ``html``
    against ``input_css``. Raises ``WebExportCompileError`` (stderr attached) on a non-zero exit —
    never returns an empty/unstyled stylesheet silently. Shared by the WebDoc export below and the
    Puck site render (``lumen_api.site_render``); the scanner only ever READS the html as text."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        html_file = tmp_path / "page.html"
        input_file = tmp_path / "input.css"
        out_file = tmp_path / "site.css"
        html_file.write_text(html, encoding="utf-8")
        input_file.write_text(input_css, encoding="utf-8")
        try:
            result = subprocess.run(
                [node_bin, STATIC_CSS_SCRIPT, str(html_file), str(input_file), str(out_file)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WebExportCompileError(f"static css compile failed to run: {error}") from error
        if result.returncode != 0:
            raise WebExportCompileError(
                (result.stderr or result.stdout or "").strip()
                or f"static css compile exited {result.returncode}"
            )
        return out_file.read_text(encoding="utf-8")


def _compile_static_css(
    html: str, theme: _CompiledTheme, node_bin: str, timeout_seconds: int = 120
) -> str:
    """Run the editor's Tailwind v4 toolchain over ``html`` against the doc's ``@theme`` tokens.

    ``timeout_seconds`` defaults to the export's own long bound (a whole page's worth of markup,
    run as a build step nobody is waiting on). A caller compiling one SECTION inside a tool call
    passes something far shorter — see :func:`compile_section_css`."""
    return compile_tailwind_css(html, _build_input_css(theme), node_bin, timeout_seconds)


#: How long ONE section's utility compile may take before it is killed.
#:
#: Two orders of magnitude below the export's own 120 s, and deliberately: this runs inside an
#: agent tool call with a user waiting on the turn, over a single section rather than a whole
#: page (measured at ~0.07 s on the F3.1 walk's rung-3 band). The export's bound is right for a
#: build step nobody is watching; inheriting it here would mean a wedged node process holding a
#: turn open for two minutes.
SECTION_CSS_TIMEOUT_SECONDS = 20


def _portable_repair_custom_css(css: str) -> str:
    """Admit local, unlayered rules without pretending global CSS is isolated.

    Native IDs change per pin. Global font/property/page rules and layer order
    also have document-wide meaning the fragment scoper cannot preserve. Keep
    the typed section on refusal; do not silently drop one of its dependencies.
    Registered assets still pass the artifact builder's normal custody checks.
    """
    def refuse(reason: str) -> None:
        raise WebExportCompileError(f"reusable section custom CSS cannot preserve {reason}")

    def tokens(items: Any, *, selector: bool = False, animation: bool = False) -> None:
        for token in items:
            if isinstance(token, ast.ParseError):
                refuse("invalid CSS")
            if selector and isinstance(token, ast.HashToken) and token.is_identifier:
                refuse("ID selectors; use section-local classes")
            if selector and isinstance(token, ast.SquareBracketsBlock) and any(
                isinstance(t, ast.IdentToken)
                and t.lower_value in {"id", "aria-controls", "aria-labelledby"}
                for t in token.content
            ):
                refuse("ID attribute selectors; use section-local classes")
            if isinstance(token, ast.URLToken) and token.value.lstrip().startswith("#"):
                refuse("local URL targets that may change per pin")
            if isinstance(token, ast.FunctionBlock):
                if animation and token.lower_name in {"var", "env", "attr"}:
                    refuse("indirect animation names; keyframe identity must be explicit")
                if token.lower_name == "url" and any(
                    isinstance(t, ast.StringToken) and t.value.lstrip().startswith("#")
                    for t in token.arguments
                ):
                    refuse("local URL targets that may change per pin")
                tokens(token.arguments, selector=selector, animation=animation)
            elif hasattr(token, "content"):
                tokens(token.content, selector=selector, animation=animation)

    def rules(items: Any) -> None:
        for rule in items:
            if isinstance(rule, ast.QualifiedRule):
                tokens(rule.prelude, selector=True)
                declarations = tinycss2.parse_declaration_list(
                    rule.content, skip_comments=True, skip_whitespace=True,
                )
                for declaration in declarations:
                    if not isinstance(declaration, ast.Declaration):
                        refuse("nested or invalid declarations")
                    tokens(declaration.value, animation=declaration.lower_name in {
                        "animation", "animation-name", "-webkit-animation", "-webkit-animation-name",
                    })
            elif isinstance(rule, ast.AtRule):
                # Keyframes are renamed by the existing artifact scoper.
                if rule.lower_at_keyword not in {
                    "media", "supports", "container", "keyframes", "-webkit-keyframes",
                } or rule.content is None:
                    refuse(f"@{rule.lower_at_keyword} across document boundaries")
                tokens(rule.prelude, selector=True)
                rules(tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True,
                ))
            else:
                refuse("invalid or unsupported rules")

    rules(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
    return css


def compile_section_css(
    core: Any,
    web_doc: JsonObject,
    *,
    brand_kit: Optional[JsonObject],
    section_html: str,
    node_bin: str = "node",
    timeout_seconds: int = SECTION_CSS_TIMEOUT_SECONDS,
) -> str:
    """The utilities ONE rendered section needs, compiled against this document's own theme.

    The repair mint's other half (clone-fidelity F3.1, ruling D-F6). A repair is a fragment, and
    a fragment carries its own styling — which is not optional here, it is the only thing that
    makes the artifact work: :func:`_document_only_html` deliberately keeps every fragment OUT of
    the Tailwind scan (W7), so a repair minted with an empty stylesheet would render correctly in
    the editor (whose browser runtime scans the live DOM) and publish completely unstyled. That
    is the worst shape a bug can have, so the repair pays the compile at mint and ships sealed.

    The SAME toolchain the export uses, not a second one, so a repaired section styles identically
    to the page it was composed on. **That toolchain is node plus the editor app's own
    `node_modules`** — a dependency no Python package metadata can declare, which publish has
    always had because it is only ever run from a full checkout. F3.1 put it behind an agent tool
    call, so it is checked BY NAME first (:func:`require_static_css_toolchain` →
    :class:`WebExportToolchainMissing`) and bounded far tighter than the export's own compile.

    Raises :class:`WebExportCompileError` (or its ``WebExportToolchainMissing`` subclass) rather
    than returning an empty sheet — a repair that cannot be styled refuses, rather than minting an
    artifact that looks fine until somebody publishes it.
    """
    custom_css = _portable_repair_custom_css(str(web_doc.get("custom_css") or "").strip())
    require_static_css_toolchain(node_bin)
    utilities = _compile_static_css(
        section_html,
        _theme_tokens(core, web_doc, brand_kit),
        node_bin,
        timeout_seconds=timeout_seconds,
    )
    # A repair leaves the page that supplied its custom class rules. Keep those
    # accepted unlayered rules after the utilities. Layer-dependent ordering is
    # explicitly refused above. The artifact builder still validates URLs and
    # scopes the complete sheet;
    # this is not permission to replay source scripts or bypass asset custody.
    return utilities + "\n" + custom_css if custom_css else utilities


# --------------------------------------------------------------------------- #
# Entry points                                                                #
# --------------------------------------------------------------------------- #


def _resolve_brand_kit(
    web_doc: JsonObject, blobs: DesignBlobStore
) -> Optional[JsonObject]:
    # Lazy import to dodge the main <-> web_export circular; reuse the exact
    # resolver the render/theme endpoints use so export sees the same kit.
    from .main import resolve_web_turn_brand_kit

    brand_kit, _source, _assets, _fonts = resolve_web_turn_brand_kit(web_doc, blobs)
    return brand_kit


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _delivery_override_variables(repo: Any, document: JsonObject) -> Dict[str, str]:
    account_id = document.get("account_id")
    if not isinstance(account_id, str):
        return {}
    # Lazy import avoids a module-load cycle while preserving the exact
    # account-value semantics used by editor preview.
    from .main import account_values

    try:
        values, _records = account_values(repo.require_web_account(account_id), repo)
    except Exception:
        return {}
    return {
        str(key): str(value.get("value") or "")
        for key, value in values.items()
        if isinstance(key, str)
        and isinstance(value, dict)
        and value.get("kind") == "text"
    }


def _custom_component_package(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    blobs: DesignBlobStore,
    asset_url_for: Any,
    deterministic_seed: str,
    embed_runtime_assets: bool,
    brand_kit: Optional[JsonObject],
    page_id: str = HOME_PAGE_ID,
) -> Any:
    web_doc = document["scene"]
    if not web_doc_uses_custom_components(web_doc, page_id):
        return build_custom_component_delivery_package(
            repo,
            blobs,
            account_id=(
                document.get("account_id")
                if isinstance(document.get("account_id"), str)
                else None
            ),
            web_doc=web_doc,
            page_id=page_id,
            theme=None,
            override_variables={},
            runtime_host_path=default_runtime_host_path(),
            asset_url_for=asset_url_for,
            deterministic_seed=deterministic_seed,
            embed_runtime_assets=embed_runtime_assets,
        )
    theme_response = core.web_validate(web_doc, brand_kit)
    try:
        return build_custom_component_delivery_package(
            repo,
            blobs,
            account_id=(
                document.get("account_id")
                if isinstance(document.get("account_id"), str)
                else None
            ),
            web_doc=web_doc,
            page_id=page_id,
            theme=theme_response.get("web_theme"),
            override_variables=_delivery_override_variables(repo, document),
            runtime_host_path=default_runtime_host_path(),
            asset_url_for=asset_url_for,
            deterministic_seed=deterministic_seed,
            embed_runtime_assets=embed_runtime_assets,
        )
    except CustomComponentRuntimeError as error:
        raise WebExportError(f"{error.code}: {error}") from error


def _merge_custom_component_packages(packages: Sequence[Any]) -> Any:
    """One delivery package for a whole multi-page site (F5).

    A custom-component package is built per PAGE, because that is the unit the runtime
    assembles for — but the zip, the asset store and the manifest answer for the whole site, so
    the per-page packages are merged into one before any of them see it.

    The merge is by identity, never by concatenation: frames are keyed by node id, assets by
    content digest, artifacts by artifact id, asset records by digest (their ``roles`` unioned,
    since the same byte can be a bundle on one page and a dependency on another). A single-page
    document short-circuits to its one package, so a legacy publish is byte-identical to what
    it produced before this function existed.
    """
    if len(packages) == 1:
        return packages[0]
    from .custom_component_runtime import CustomComponentDeliveryPackage

    merged = CustomComponentDeliveryPackage()
    components: Dict[str, JsonObject] = {}
    artifacts: Dict[str, JsonObject] = {}
    asset_records: Dict[str, JsonObject] = {}
    runtime_host: Optional[JsonObject] = None
    has_runtime_host_key = False
    contract_version: Any = None
    for package in packages:
        merged.frames.update(package.frames)
        merged.assets.update(package.assets)
        manifest = package.manifest or {}
        contract_version = manifest.get("runtime_contract_version", contract_version)
        if "runtime_host" in manifest:
            has_runtime_host_key = True
            if manifest.get("runtime_host") is not None:
                runtime_host = manifest["runtime_host"]
        for record in manifest.get("components") or []:
            components.setdefault(str(record.get("node_id")), record)
        for record in manifest.get("artifacts") or []:
            artifacts.setdefault(str(record.get("artifact_id")), record)
        for record in manifest.get("assets") or []:
            digest = str(record.get("digest"))
            existing = asset_records.get(digest)
            if existing is None:
                asset_records[digest] = dict(record)
                asset_records[digest]["roles"] = sorted(record.get("roles") or [])
                continue
            existing["roles"] = sorted(
                set(existing.get("roles") or []) | set(record.get("roles") or [])
            )
    merged.manifest = {
        "schema_version": 1,
        "runtime_contract_version": contract_version,
        **({"runtime_host": runtime_host} if has_runtime_host_key else {}),
        "components": [components[key] for key in sorted(components)],
        "artifacts": [artifacts[key] for key in sorted(artifacts)],
        "assets": [asset_records[key] for key in sorted(asset_records)],
    }
    return merged


def _delivery_manifest(
    document: JsonObject,
    *,
    kind: str,
    custom_components: JsonObject,
    fragments: "_FragmentDelivery",
    assets: Dict[str, bytes],
    warnings: List[str],
    page_id: str = HOME_PAGE_ID,
    pages: Optional[Sequence[JsonObject]] = None,
) -> JsonObject:
    return {
        "schema_version": 2,
        "kind": kind,
        "document_id": document["id"],
        "doc_version": document["current_version"],
        # The page a bare site address serves. Kept for every pre-F5 reader; `pages` below is
        # the whole site.
        "page_id": page_id,
        # F5: every page this build produced, in document order, as
        # `{page_id, route, html_digest}`. On the EXPORT path that digest is the zip file's own
        # bytes. On the PUBLISH path it is the page's bytes before the two metas that quote the
        # manifest's own digest back into the head — a manifest cannot contain the digest of a
        # document that contains the manifest's digest, and the served bytes are bound instead
        # by `package_digest` (computed over the final page digests) and by the page rows.
        "pages": [dict(page) for page in (pages or [])],
        "runtime": {
            "platform_version": 2,
            "custom_component_contract_version": custom_components.get(
                "runtime_contract_version"
            ),
        },
        "custom_components": custom_components,
        # The cloned sections this page is built from, beside the custom components it is built
        # from — same question, same place to look. `missing` is listed rather than swallowed:
        # a pin that would not resolve rendered a placeholder, and the manifest is where a
        # reader finds out which one.
        "fragments": fragments.manifest_entry,
        "asset_digests": [
            {
                "algorithm": "sha256",
                "digest": digest,
                "byte_length": len(assets[digest]),
            }
            for digest in sorted(assets)
        ],
        "warnings": list(warnings),
    }


def _font_manifest_entries(gate: _FontGate) -> JsonObject:
    """The font block BOTH delivery manifests carry.

    One builder because the two paths must not disagree about what shipped. Before F1.5 the
    publish path discarded ``excluded`` outright (D-F2 obligation 3), so a family the license
    gate refused left no trace on the only artifact a publish keeps — a page silently rendered
    in a fallback font with nothing to read about why.
    """
    return {
        "font_families_included": sorted({face.family for face in gate.faces}),
        "font_families_excluded": list(gate.excluded),
        "font_embed_bases": list(gate.bases),
    }


def _delivery_csp(*, meta: bool = False, static_bundle: bool = False) -> str:
    """The published page's CSP. ``meta=True`` is the ``<meta http-equiv>`` shape.

    The served policy has one home, ``clue_design.publishes.delivery_csp`` (custom-domain
    publishing §6.2), shared with the page origin's header. Assets are same-origin by
    construction, so there is no origin allow-list: ``'self'`` covers ``/p-assets`` and
    ``/asset-store`` on whichever hostname served the page. The meta shape omits
    ``frame-ancestors``, which a meta CSP ignores by spec (walk criterion 4, final-review X7).

    ``static_bundle=True`` is the EXPORT ZIP's shape. A document opened from disk has an OPAQUE
    origin in Chromium, which ``'self'`` does not match, so the zip's own ``site.css``,
    ``assets/<digest>.<ext>`` and ``fonts/<digest>.woff2`` would be blocked by the page itself;
    the ``file:`` scheme source is appended to ``script-src``/``style-src``/``img-src``/
    ``font-src`` for exactly that. Everything genuinely remote stays refused:
    ``default-src``/``connect-src``/``object-src``/``worker-src``/``base-uri``/``form-action``
    are untouched, so the bundle can still reach nothing off its own disk.
    """
    policy = delivery_csp(meta=meta)
    if not static_bundle:
        return policy
    directives = []
    for directive in policy.split("; "):
        name = directive.split(" ", 1)[0]
        if name in {"script-src", "style-src", "img-src", "font-src"}:
            directive += " file:"
        directives.append(directive)
    return "; ".join(directives)


def _relative_prefix(route: str) -> str:
    """The `../` hop count that gets from a page's own folder back to the zip root.

    ``/`` lives at the root (``""``); ``/pricing`` lives one folder down (``"../"``). Shared
    bytes — assets, fonts, the component manifest — are written once at the root, so every page
    but the first has to reach up to them.
    """
    return "../" * len([segment for segment in route.strip("/").split("/") if segment])


def build_export_bundle(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    blobs: DesignBlobStore,
    generated_at: str,
    node_bin: str = "node",
) -> ExportBundle:
    """Build a self-contained static-site zip for ``document`` (a WebDoc).

    F5: EVERY page of the document is written — ``/`` as ``index.html``, every other route as
    ``<route>/index.html`` — so a static host serves the whole site from its directory indexes.
    The shared bytes (assets, fonts, component artifacts) stay at the zip root and each page
    reaches them through its own ``../`` prefix; the compiled stylesheet is per page, written
    beside the page it styles. A single-page document produces exactly the zip it always did.
    """
    web_doc = document["scene"]
    brand_kit = _resolve_brand_kit(web_doc, blobs)
    site_pages = _site_pages(web_doc)
    primary = _primary_page(site_pages)
    routes = [page.route for page in site_pages]

    files: Dict[str, bytes] = {}
    warnings: List[str] = []
    deterministic_seed = (
        f"export:{document['id']}:{document['current_version']}:"
        f"{_sha256(_canonical_json(web_doc))}"
    )
    component_package = _merge_custom_component_packages(
        [
            _custom_component_package(
                core,
                repo,
                document,
                blobs=blobs,
                asset_url_for=(
                    lambda digest, extension: (
                        f"components/sha256/{digest}.{extension}"
                    )
                ),
                deterministic_seed=deterministic_seed,
                embed_runtime_assets=True,
                brand_kit=brand_kit,
                page_id=page.page_id,
            )
            for page in site_pages
        ]
    )
    component_asset_records = {
        record["digest"]: record
        for record in component_package.manifest.get("assets", [])
        if isinstance(record, dict) and isinstance(record.get("digest"), str)
    }
    for digest, data in component_package.assets.items():
        extension = str(
            component_asset_records.get(digest, {}).get("extension") or "bin"
        )
        files[f"components/sha256/{digest}.{extension}"] = data
    files["components/manifest.json"] = (
        json.dumps(component_package.manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    # 1. Fonts (license-gated), embedded as relative fonts/<digest12>.<ext>.
    font_gate = _gather_fonts(brand_kit, repo, blobs)
    faces = font_gate.faces
    warnings.extend(font_gate.warnings)
    for face in faces:
        files[f"fonts/{face.digest[:12]}.{face.ext}"] = face.data

    # 2. Cloned sections resolved out of durable custody first, so the zip carries the real
    #    section rather than its placeholder — once for the whole document.
    fragments = _sweep_fragment_asset_custody(
        _resolve_fragments(web_doc, blobs),
        blobs,
        consequence=(
            "it is not in this zip, and the exported page keeps its /asset-store reference"
        ),
    )
    warnings.extend(fragments.warnings)
    fragment_asset_paths, fragment_copy_warnings = _copy_fragment_assets(
        files, fragments, blobs
    )
    warnings.extend(fragment_copy_warnings)

    # 3. Assets: copy referenced image bytes once; each page rewrites its own references to the
    #    extensioned path below.
    images = _resolve_images(web_doc)
    exported_images: List[_ImageAsset] = []
    for image in images:
        # D4: pure-Python read — the bytes are copied straight into the zip.
        data = read_asset_bytes(blobs, image.digest)
        if data is None:
            warnings.append(
                f"image asset {image.asset_id} ({image.digest[:12]}) skipped: "
                "bytes missing from the asset store"
            )
            continue
        files[f"assets/{image.digest}.{image.ext}"] = data
        exported_images.append(image)

    # The og:image stays the first IMAGE NODE's asset: which picture represents the site is a
    # document-level question, unchanged by the walk getting wider or the site getting pages.
    og_source = next(
        (image for image in exported_images if image.origin == "image"), None
    )
    compiled_theme = _theme_tokens(core, web_doc, brand_kit)

    # 4. One render, one compiled stylesheet and one html file per page.
    page_files: Dict[str, bytes] = {}
    manifest_pages: List[JsonObject] = []
    page_html: Dict[str, str] = {}
    unresolved_markers: List[str] = []
    for page in site_pages:
        prefix = _relative_prefix(page.route)
        page_fragments = _page_fragment_view(fragments, web_doc, page.page_id)
        render_kwargs = dict(
            mode="delivery",
            asset_base_url=f"{prefix}assets",
            font_face_css=_font_face_css(
                faces, lambda face: f"{prefix}fonts/{face.digest[:12]}.{face.ext}"
            ),
            brand_kit=brand_kit,
            custom_component_runtimes=component_package.frames,
        )
        render = core.web_render(
            web_doc,
            page.page_id,
            fragments=page_fragments.render_map,
            fragment_css=page_fragments.css,
            **render_kwargs,
        )
        html = render.get("html") or ""

        # R25-7, the export half of the split. Publishing an un-derived template is REFUSED (a
        # visitor would read the markers); exporting one is WARNED, loudly, on the manifest a
        # human is already opening. A zip is an inspection surface — refusing it would remove
        # the only way to look at a template's package, and the person holding the file can see
        # what it says. Named once per marker, not once per page that shows it.
        for marker in unresolved_account_markers(html):
            if marker not in unresolved_markers:
                unresolved_markers.append(marker)

        for image in exported_images:
            html = html.replace(
                f"assets/{image.digest}", f"assets/{image.digest}.{image.ext}"
            )
        html = _point_at_copied_fragment_assets(html, fragment_asset_paths, prefix)

        # Static CSS: compiled for THIS page and written beside it, so the link stays a plain
        # relative `site.css` whatever folder the page lives in.
        site_css = _compile_static_css(
            _document_only_html(core, web_doc, html, page.page_id, **render_kwargs),
            compiled_theme,
            node_bin,
        )
        css_path = "site.css" if not page.route.strip("/") else (
            f"{page.route.strip('/')}/site.css"
        )
        files[css_path] = site_css.encode("utf-8")
        # The cascade check, now that a REAL compiled sheet exists to check against.
        warnings.extend(
            _fragment_cascade_warnings(fragments, site_css, page_fragments.ids)
        )

        # SEO metas + the stylesheet link, injected before </head>.
        head = _seo_snippet(
            title=document["title"],
            description=_seo_description(web_doc, document["title"], page.page_id),
            og_image=(
                f"{prefix}assets/{og_source.digest}.{og_source.ext}"
                if og_source is not None
                else None
            ),
        )
        head += '<link rel="stylesheet" href="site.css">\n'
        # F4 wave item 7 (final-review NEW-1 — the noindex law's FIFTH surface): the export
        # bundle never read the durable flag, so a stamped ABM page exported and self-hosted was
        # indexable. The document's own `web_noindex` rides into the zip's head, on every page,
        # and the manifest says so, exactly as publish does.
        if document.get("web_noindex"):
            head += ROBOTS_NOINDEX_META + "\n"
        head += (
            '<meta http-equiv="Content-Security-Policy" content="'
            f'{_escape_attr(_delivery_csp(meta=True, static_bundle=True))}">\n'
        )
        head += (
            '<link rel="lumen-component-manifest" href="'
            f'{prefix}components/manifest.json">\n'
        )
        html = _inject_before_head_close(html, head)
        # The site's own internal links point at the folder a static host serves each route
        # from; everything else the page links to is left exactly as the author wrote it.
        html = rewrite_zip_links(html, routes)
        page_html[page.route] = html
        page_files[_zip_page_path(page.route)] = html.encode("utf-8")
        manifest_pages.append(
            {
                "page_id": page.page_id,
                "route": page.route,
                "html_digest": _sha256(html),
            }
        )

    for marker in unresolved_markers:
        warnings.append(
            f"the exported page still shows the account marker {marker}: this is a TEMPLATE, "
            "not one account's page. Derive it for an account and export the derived page."
        )
    if document.get("web_noindex"):
        warnings.append(
            "this document is stamped noindex (an ABM account page): every exported page "
            "carries the robots meta, and wherever this zip is hosted the page will ask not "
            "to be indexed. Clearing the stamp is an explicit act on the document, not an "
            "edit to this file."
        )

    # 5. manifest.json — the file list is known now (the pages and the manifest added last).
    file_names = sorted(list(files.keys()) + list(page_files.keys()) + ["manifest.json"])
    runtime_version = _runtime_version(page_html.get(primary.route, ""))
    delivery_manifest = _delivery_manifest(
        document,
        kind="export",
        custom_components=component_package.manifest,
        fragments=fragments,
        assets=component_package.assets,
        warnings=warnings,
        page_id=primary.page_id,
        pages=manifest_pages,
    )
    manifest = {
        **delivery_manifest,
        "generated_at": generated_at,
        "runtime": {
            **delivery_manifest["runtime"],
            "present": runtime_version is not None,
            "version": runtime_version,
        },
        "files": file_names,
        **_font_manifest_entries(font_gate),
        "warnings": warnings,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    files.update(page_files)
    return ExportBundle(files=files, warnings=warnings)


def build_publish_package(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    blobs: DesignBlobStore,
    slug: str,
    site_address: PublicSiteAddress,
    workspace_id: str,
    default_description: Optional[str] = None,
    default_social_preview_sha256: Optional[str] = None,
    node_bin: str = "node",
    noindex: bool = False,
    embed_runtime_assets: bool = False,
) -> PublishPackage:
    """Build one immutable publish package for same-origin delivery.

    The outer HTML, custom-component artifact graph, trusted runtime host, CSS,
    server first frames, and generated per-node bootstrap modules are all
    pinned by digest. Runtime asset URLs are immutable and never resolve
    ``latest`` registry state.

    Every URL this package mints is ROOT-RELATIVE — the published HTML names no
    host, so the same immutable bytes serve correctly from the workspace's system
    hostname and from any custom domain pointed at it: the per-asset runtime URLs
    (``/p-assets/{digest}.{ext}``), the ``/asset-store`` URLs, the manifest link
    (``/{slug}/manifest.json``) and the rebased internal links (``/{slug}{route}``).
    There is no canonical and no ``og:url`` (custom-domain publishing spec A6).
    The one exception is ``og:image``: unfurlers require an
    absolute URL, so it points at ``site_address.origin``, the always-live system
    hostname (custom-domain publishing §6.1), which stays reachable even after a
    custom domain is removed.

    ``site_address`` is where the site lives — built from the hostname registry by
    ``lumen_api.public_pages.site_address`` (reconciliation 2026-09-28). The manifest's
    ``canonical_url`` records its absolute root.

    ``default_description`` / ``default_social_preview_sha256`` are the WORKSPACE's page
    defaults (custom-domain publishing §4.2). They fill in, they never override: the
    description applies only when the page derives an empty one, and the social preview only
    when the site carries no image node, so a page that says something for itself keeps saying
    it after a workspace default is set.

    ``embed_runtime_assets`` inlines the custom-component runtime assets as ``data:`` URLs
    instead of referencing ``/p-assets/{digest}.{ext}``. Publishing leaves it off (the page
    origin serves those assets); the PDF export turns it on, because a document rendered with
    ``set_content`` has no origin for a root-relative ``/p-assets`` URL to resolve against.

    ``noindex`` (clone-fidelity F4.3, ruling R25-4) adds ONE line to the head:
    ``<meta name="robots" content="noindex">``. It is a per-page option and it
    defaults off. It applies to EVERY page of the site: a site is indexed or it is not, and a
    campaign page that is unreachable from any navigation does not become reachable because it
    is page three.

    F5: a document is a SITE. Every page is rendered, styled and headed on its own — its own
    description, its own compiled stylesheet — and the document's internal
    links are rebased onto the address the site is served from, so a link the author wrote as
    ``/pricing`` reaches the published pricing page instead of walking the visitor off the site.
    ``html`` remains the page served at ``/``, so every pre-F5 consumer is unchanged.
    """
    web_doc = document["scene"]
    brand_kit = _resolve_brand_kit(web_doc, blobs)
    site_pages = _site_pages(web_doc)
    primary = _primary_page(site_pages)
    routes = [page.route for page in site_pages]
    warnings: List[str] = []
    address = site_address
    #: The always-live system origin: the ONE absolute URL a page carries is `og:image` on it.
    origin = address.origin.rstrip("/")
    #: The site's path from the visitor's own origin — what an internal link has to become,
    #: and where the manifest back-reference hangs (`/{slug}/manifest.json`).
    link_site_path = address.link_path
    deterministic_seed = (
        f"publish:{document['id']}:{document['current_version']}:"
        f"{_sha256(_canonical_json(web_doc))}"
    )
    component_package = _merge_custom_component_packages(
        [
            _custom_component_package(
                core,
                repo,
                document,
                blobs=blobs,
                # Root-relative: the page origin serves `/p-assets` on whichever hostname
                # served the page, so the bytes name no host.
                asset_url_for=(
                    lambda digest, extension: f"/p-assets/{digest}.{extension}"
                ),
                deterministic_seed=deterministic_seed,
                embed_runtime_assets=embed_runtime_assets,
                brand_kit=brand_kit,
                page_id=page.page_id,
            )
            for page in site_pages
        ]
    )

    # Fonts (license-gated) as absolute /asset-store urls; no files emitted. The gate's
    # exclusions ride the manifest below — a publish keeps no other artifact to read them from.
    font_gate = _gather_fonts(brand_kit, repo, blobs)
    faces = font_gate.faces
    warnings.extend(font_gate.warnings)
    font_face_css = _font_face_css(
        faces, lambda face: f"/asset-store/{face.digest}"
    )

    # Delivery render against the absolute same-origin asset route. Cloned sections resolve out
    # of durable custody exactly as they do for the editor preview; their own bytes need no
    # copy here, because the artifact already names them as `/asset-store/<digest>` and that
    # route is the one public byte surface this page is served beside.
    fragments = _sweep_fragment_asset_custody(
        _resolve_fragments(web_doc, blobs),
        blobs,
        consequence="the published page will serve a 404 where that image or font goes",
    )
    warnings.extend(fragments.warnings)

    images = _resolve_images(web_doc)
    # As on the export path: the site's picture is an image node's asset, not a background
    # wash and not a cloned section's logo.
    og_source = next((image for image in images if image.origin == "image"), None)
    if og_source is not None:
        og_image = f"{origin}/asset-store/{og_source.digest}"
    elif default_social_preview_sha256:
        og_image = f"{origin}/asset-store/{default_social_preview_sha256}"
    else:
        og_image = None
    compiled_theme = _theme_tokens(core, web_doc, brand_kit)

    staged: List[Tuple[_SitePage, str]] = []
    unresolved_markers: List[str] = []
    escape_routes: List[str] = []
    for page in site_pages:
        page_fragments = _page_fragment_view(fragments, web_doc, page.page_id)
        render_kwargs = dict(
            mode="delivery",
            asset_base_url="/asset-store",
            font_face_css=font_face_css,
            brand_kit=brand_kit,
            custom_component_runtimes=component_package.frames,
        )
        render = core.web_render(
            web_doc,
            page.page_id,
            fragments=page_fragments.render_map,
            fragment_css=page_fragments.css,
            **render_kwargs,
        )
        html = render.get("html") or ""

        # FOUNDER RULING 2026-08-29 (verbatim law: no mechanical gates on the design path that
        # the founder did not order): the R25-7 unresolved-marker REFUSAL is demoted to a LOUD
        # WARNING. A publish always proceeds; the manifest says what the page still shows, and
        # deriving per account remains the way to substitute the markers.
        for marker in unresolved_account_markers(html):
            if marker not in unresolved_markers:
                unresolved_markers.append(marker)

        # Static CSS compiled and INLINED (no external stylesheet for a self-contained publish
        # payload) — per page, because a page's stylesheet is compiled from the classes that
        # page authors.
        site_css = _compile_static_css(
            _document_only_html(core, web_doc, html, page.page_id, **render_kwargs),
            compiled_theme,
            node_bin,
        )
        warnings.extend(
            _fragment_cascade_warnings(fragments, site_css, page_fragments.ids)
        )

        head = _seo_snippet(
            title=document["title"],
            description=(
                _seo_description(web_doc, document["title"], page.page_id)
                or (default_description or "")
            ),
            og_image=og_image,
            canonical=None,
            og_url=None,
        )
        head += '<link rel="icon" href="/favicon.ico">\n'
        if noindex:
            head += ROBOTS_NOINDEX_META + "\n"
            # F4 wave item 6 (the CP2 walk's F-1, the lite half): every off-page door on a
            # noindex site, said on the manifest. Listed, never refused — see the audit's
            # docstring for why. A link to one of this site's OWN routes is not a door out, so
            # the audit runs before the internal links are rebased and its own filter (absolute
            # destinations only) leaves them out.
            for destination in _escape_route_audit(html):
                if destination not in escape_routes:
                    escape_routes.append(destination)
        head += f'<style id="lumen-static-css">{site_css}</style>\n'
        html = _inject_before_head_close(html, head)
        # The site's own internal links now point at the address the site is served from.
        html = rewrite_site_links(html, routes, link_site_path)
        staged.append((page, html))

    for marker in unresolved_markers:
        warnings.append(
            f"this page still shows unsubstituted account markers ({marker}). "
            "Published as-is per standing founder ruling; derive it for an account when you "
            "want them personalized."
        )
    if escape_routes:
        warnings.append(
            "escape-route audit (noindex account page): this site links off itself to "
            + ", ".join(escape_routes)
            + " — the rubric allows only the CTA and the footer's legal links; judge "
            "each of these deliberately."
        )

    publish_manifest = {
        **_delivery_manifest(
            document,
            kind="publish",
            custom_components=component_package.manifest,
            fragments=fragments,
            assets=component_package.assets,
            warnings=warnings,
            page_id=primary.page_id,
            pages=[
                {
                    "page_id": page.page_id,
                    "route": page.route,
                    "html_digest": _sha256(html),
                }
                for page, html in staged
            ],
        ),
        **_font_manifest_entries(font_gate),
        "slug": slug,
        "canonical_url": address.page_url("/"),
        # Present ONLY when the page asked for it, so an ordinary publish's manifest — and
        # therefore its `manifest_digest`, and therefore its `package_digest` — is byte-identical
        # to what it was before the option existed.
        **({"robots": "noindex"} if noindex else {}),
    }
    manifest_digest = _sha256(_canonical_json(publish_manifest))
    # The manifest back-references, injected into every page once the manifest is final.
    manifest_head = (
        '<meta http-equiv="Content-Security-Policy" content="'
        f'{_escape_attr(_delivery_csp(meta=True))}">\n'
        '<meta name="lumen-publish-manifest-digest" content="'
        f'{manifest_digest}">\n'
        '<link rel="lumen-publish-manifest" href="'
        f'{_escape_attr(f"{address.site_path}/manifest.json")}">\n'
    )
    pages: List[PublishedPage] = []
    for page, html in staged:
        final_html = _inject_before_head_close(html, manifest_head)
        pages.append(
            PublishedPage(
                page_id=page.page_id,
                route=page.route,
                html=final_html,
                html_digest=_sha256(final_html),
            )
        )
    served = next((page for page in pages if page.route == "/"), pages[0])
    package_digest = _sha256(
        _canonical_json(
            {
                "manifest_digest": manifest_digest,
                "page_html_digests": sorted(page.html_digest for page in pages),
                "asset_digests": sorted(component_package.assets),
            }
        )
    )
    return PublishPackage(
        html=served.html,
        manifest=publish_manifest,
        assets=component_package.assets,
        package_digest=package_digest,
        manifest_digest=manifest_digest,
        html_digest=served.html_digest,
        runtime_version=_runtime_version(served.html),
        warnings=warnings,
        pages=pages,
    )


def build_publish_html(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    blobs: DesignBlobStore,
    slug: str,
    site_address: PublicSiteAddress,
    workspace_id: str,
    default_description: Optional[str] = None,
    default_social_preview_sha256: Optional[str] = None,
    node_bin: str = "node",
) -> Tuple[str, Optional[int], List[str]]:
    """Compatibility wrapper for callers that only need the publish HTML."""

    package = build_publish_package(
        core,
        repo,
        document,
        blobs=blobs,
        slug=slug,
        site_address=site_address,
        workspace_id=workspace_id,
        default_description=default_description,
        default_social_preview_sha256=default_social_preview_sha256,
        node_bin=node_bin,
    )
    return package.html, package.runtime_version, package.warnings
