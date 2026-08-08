"""Website-mode static export + publish build pipeline (P4).

Pure build functions with no FastAPI imports so they stay unit-testable. Two
entry points share one pipeline:

* ``build_export_bundle`` — a self-contained folder-in-a-zip: delivery render +
  license-gated embedded font files (relative ``fonts/…`` urls) + copied,
  extensioned image bytes (``assets/…``) + a statically compiled Tailwind
  ``site.css`` linked from the html + SEO metas + a ``manifest.json``.
* ``build_publish_html`` — a single self-contained html for same-origin serving:
  absolute ``/asset-store/{digest}`` asset + font urls (served by the digest
  route with ``Access-Control-Allow-Origin: *``), the compiled css INLINED in a
  ``<style>`` tag, SEO metas plus a canonical + og:url anchored at the public
  base.

The static Tailwind compile shells out to ``scripts/web_static_css.mjs`` (the
editor app's own v4 toolchain) so an exported page styles identically to the
canvas. A non-zero exit raises ``WebExportCompileError`` carrying stderr —
export fails honestly rather than shipping an unstyled zip.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .custom_component_runtime import (
    CustomComponentRuntimeError,
    build_custom_component_delivery_package,
    default_runtime_host_path,
    web_doc_uses_custom_components,
)

JsonObject = Dict[str, Any]

# apps/api/lumen_api/web_export.py -> parents[3] is the repo root (havana/),
# where scripts/web_static_css.mjs lives and the node compile must run.
REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_CSS_SCRIPT = "scripts/web_static_css.mjs"
PUBLISH_ASSET_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# The one page every website-mode doc renders (mirrors the render endpoint).
HOME_PAGE_ID = "home"

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


class WebExportError(Exception):
    """A website-mode build failed for a reason the caller should surface."""


class WebExportCompileError(WebExportError):
    """The static Tailwind compile (node) exited non-zero; ``stderr`` carries
    the toolchain's message so the endpoint can report it honestly."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.stderr = message


def persist_publish_assets(
    store_root: Path,
    assets: Dict[str, bytes],
    asset_records: Optional[List[JsonObject]] = None,
) -> None:
    """Persist immutable public delivery bytes under their verified digest."""

    root = Path(store_root) / "publish" / "sha256"
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
        destination = root / digest[:2] / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != data:
                raise WebExportError(
                    f"publish asset digest collision at {digest}"
                )
        else:
            temporary = destination.with_name(f".{digest}.tmp")
            temporary.write_bytes(data)
            temporary.replace(destination)
        record = records_by_digest.get(digest)
        if record is None:
            continue
        extension = record.get("extension")
        media_type = record.get("media_type")
        if extension not in {"js", "css", "html"} or not isinstance(
            media_type, str
        ):
            raise WebExportError(
                f"publish asset {digest} has invalid media metadata"
            )
        metadata = _canonical_json(
            {"extension": extension, "media_type": media_type}
        )
        metadata_path = destination.with_suffix(".meta.json")
        if metadata_path.exists():
            if metadata_path.read_bytes() != metadata:
                raise WebExportError(
                    f"publish asset {digest} media metadata changed"
                )
        else:
            temporary_metadata = metadata_path.with_name(
                f".{digest}.meta.tmp"
            )
            temporary_metadata.write_bytes(metadata)
            temporary_metadata.replace(metadata_path)


def resolve_publish_asset(
    store_root: Path, digest: str, extension: str
) -> Tuple[bytes, str]:
    """Read and integrity-check one public immutable publish asset."""

    if not PUBLISH_ASSET_PATTERN.fullmatch(digest):
        raise WebExportError("invalid publish asset digest")
    path = Path(store_root) / "publish" / "sha256" / digest[:2] / digest
    try:
        data = path.read_bytes()
    except OSError as error:
        raise WebExportError("publish asset is missing") from error
    if _sha256(data) != digest:
        raise WebExportError("publish asset failed its integrity check")
    try:
        metadata = json.loads(path.with_suffix(".meta.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise WebExportError("publish asset metadata is missing") from error
    if (
        not isinstance(metadata, dict)
        or metadata.get("extension") != extension
        or not isinstance(metadata.get("media_type"), str)
    ):
        raise WebExportError("publish asset media type does not match its URL")
    return data, metadata["media_type"]


@dataclass
class ExportBundle:
    """A ready-to-zip export: ``files`` maps zip-root-relative paths to bytes,
    ``warnings`` are non-fatal build notes (missing blobs, excluded fonts)."""

    files: Dict[str, bytes] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PublishPackage:
    """One deterministic immutable publish payload and its delivery assets."""

    html: str
    manifest: JsonObject
    assets: Dict[str, bytes]
    package_digest: str
    manifest_digest: str
    html_digest: str
    runtime_version: Optional[int]
    warnings: List[str] = field(default_factory=list)


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
    OFL-licensed, hence always embeddable)."""
    if not isinstance(license_obj, dict):
        return False
    if license_obj.get("embeddable"):
        return True
    name = license_obj.get("name")
    return isinstance(name, str) and name.startswith("OFL")


def _gather_fonts(
    brand_kit: Optional[JsonObject],
    repo: Any,
    store_root: str,
) -> Tuple[List[_FontFace], List[JsonObject], List[str]]:
    """Resolve the kit's embeddable font faces to bytes.

    Returns ``(faces, excluded, warnings)`` where ``faces`` are the included
    faces (deduped by digest), ``excluded`` is ``[{family, reason}]`` for
    license-blocked families, and ``warnings`` mirrors the exclusions (plus any
    missing-blob notes) for the top-level warning list.
    """
    fonts = ((brand_kit or {}).get("assets") or {}).get("fonts") or {}
    faces: List[_FontFace] = []
    excluded: List[JsonObject] = []
    warnings: List[str] = []
    seen: set[str] = set()
    store = Path(store_root)
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
            blob = store / "sha256" / digest[:2] / digest
            if not blob.is_file():
                warnings.append(
                    f"font face {digest[:12]} for family {family} skipped: "
                    "bytes missing from the asset store"
                )
                continue
            seen.add(digest)
            data = blob.read_bytes()
            faces.append(
                _FontFace(
                    digest=digest,
                    family=family,
                    weight=_valid_weight(face.get("weight")),
                    style=_valid_style(face.get("style")),
                    ext=_font_ext(data),
                    data=data,
                )
            )
    return faces, excluded, warnings


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


def _image_asset_ids(web_doc: JsonObject) -> List[str]:
    """Every distinct asset id referenced by an image node, across all pages,
    in first-seen order."""
    ids: List[str] = []
    seen: set[str] = set()
    for page in web_doc.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for node in _walk_nodes(page):
            if node.get("kind") == "image":
                asset_id = node.get("asset_id")
                if isinstance(asset_id, str) and asset_id and asset_id not in seen:
                    seen.add(asset_id)
                    ids.append(asset_id)
    return ids


def _image_ext(mime: Any) -> str:
    return _IMAGE_EXT_BY_MIME.get(mime, "bin")


@dataclass
class _ImageAsset:
    asset_id: str
    digest: str
    ext: str
    mime: Optional[str]


def _resolve_images(web_doc: JsonObject) -> List[_ImageAsset]:
    """The doc's image assets, resolved from the WebDoc's own assets map (the
    records carry ``media.digest.value`` + ``mime_type``)."""
    assets = web_doc.get("assets") or {}
    resolved: List[_ImageAsset] = []
    seen: set[str] = set()
    for asset_id in _image_asset_ids(web_doc):
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
            _ImageAsset(asset_id=asset_id, digest=digest, ext=_image_ext(mime), mime=mime)
        )
    return resolved


def _seo_description(web_doc: JsonObject, fallback: str) -> str:
    """The first body Text node's text in document order, tags stripped and
    whitespace collapsed, truncated on a clean word boundary; the doc title
    when there is no body copy."""
    page = _home_page(web_doc)
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


def _theme_tokens(core: Any, web_doc: JsonObject, brand_kit: Optional[JsonObject]) -> Dict[str, str]:
    """The compiled theme's token map — exactly the surface GET web/theme
    reads (web_validate -> web_theme.tokens)."""
    response = core.web_validate(web_doc, brand_kit)
    theme = response.get("web_theme") or {}
    tokens = theme.get("tokens") or {}
    return {str(name): str(value) for name, value in tokens.items()}


def _build_input_css(tokens: Dict[str, str]) -> str:
    lines = ['@import "tailwindcss";', "@theme {"]
    for name, value in tokens.items():
        lines.append(f"  --color-{name}: {value};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _compile_static_css(html: str, tokens: Dict[str, str], node_bin: str) -> str:
    """Run the editor's Tailwind v4 toolchain over ``html`` against the doc's
    ``@theme`` tokens. Raises ``WebExportCompileError`` (stderr attached) on a
    non-zero exit — never returns an empty/unstyled stylesheet silently."""
    input_css = _build_input_css(tokens)
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
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WebExportCompileError(f"static css compile failed to run: {error}") from error
        if result.returncode != 0:
            raise WebExportCompileError(
                (result.stderr or result.stdout or "").strip()
                or f"static css compile exited {result.returncode}"
            )
        return out_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry points                                                                #
# --------------------------------------------------------------------------- #


def _resolve_brand_kit(web_doc: JsonObject, database_path: Any) -> Optional[JsonObject]:
    # Lazy import to dodge the main <-> web_export circular; reuse the exact
    # resolver the render/theme endpoints use so export sees the same kit.
    from .main import resolve_web_turn_brand_kit

    brand_kit, _source, _assets, _fonts = resolve_web_turn_brand_kit(
        web_doc, database_path=database_path
    )
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
    custom_component_store_root: Path,
    asset_url_for: Any,
    deterministic_seed: str,
    embed_runtime_assets: bool,
    brand_kit: Optional[JsonObject],
) -> Any:
    web_doc = document["scene"]
    if not web_doc_uses_custom_components(web_doc, HOME_PAGE_ID):
        return build_custom_component_delivery_package(
            repo,
            custom_component_store_root,
            account_id=(
                document.get("account_id")
                if isinstance(document.get("account_id"), str)
                else None
            ),
            web_doc=web_doc,
            page_id=HOME_PAGE_ID,
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
            custom_component_store_root,
            account_id=(
                document.get("account_id")
                if isinstance(document.get("account_id"), str)
                else None
            ),
            web_doc=web_doc,
            page_id=HOME_PAGE_ID,
            theme=theme_response.get("web_theme"),
            override_variables=_delivery_override_variables(repo, document),
            runtime_host_path=default_runtime_host_path(),
            asset_url_for=asset_url_for,
            deterministic_seed=deterministic_seed,
            embed_runtime_assets=embed_runtime_assets,
        )
    except CustomComponentRuntimeError as error:
        raise WebExportError(f"{error.code}: {error}") from error


def _delivery_manifest(
    document: JsonObject,
    *,
    kind: str,
    custom_components: JsonObject,
    assets: Dict[str, bytes],
    warnings: List[str],
) -> JsonObject:
    return {
        "schema_version": 2,
        "kind": kind,
        "document_id": document["id"],
        "doc_version": document["current_version"],
        "page_id": HOME_PAGE_ID,
        "runtime": {
            "platform_version": 2,
            "custom_component_contract_version": custom_components.get(
                "runtime_contract_version"
            ),
        },
        "custom_components": custom_components,
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


def _delivery_csp(public_base: Optional[str] = None) -> str:
    origin = ""
    if public_base:
        parsed = urlsplit(public_base)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            origin = f" {parsed.scheme}://{parsed.netloc}"
    return (
        "default-src 'none'; "
        f"script-src 'unsafe-inline' data:{origin}; "
        f"style-src 'unsafe-inline'{origin}; "
        f"img-src data: blob:{origin}; "
        f"font-src data:{origin}; "
        "connect-src 'none'; object-src 'none'; worker-src 'none'; "
        "frame-src 'self' data: blob:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'self'"
    )


def build_export_bundle(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    store_root: str,
    database_path: Any,
    generated_at: str,
    node_bin: str = "node",
) -> ExportBundle:
    """Build a self-contained static-site zip for ``document`` (a WebDoc)."""
    web_doc = document["scene"]
    brand_kit = _resolve_brand_kit(web_doc, database_path)

    files: Dict[str, bytes] = {}
    warnings: List[str] = []
    deterministic_seed = (
        f"export:{document['id']}:{document['current_version']}:"
        f"{_sha256(_canonical_json(web_doc))}"
    )
    component_package = _custom_component_package(
        core,
        repo,
        document,
        custom_component_store_root=Path(store_root) / "custom-components",
        asset_url_for=(
            lambda digest, extension: (
                f"components/sha256/{digest}.{extension}"
            )
        ),
        deterministic_seed=deterministic_seed,
        embed_runtime_assets=True,
        brand_kit=brand_kit,
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
    faces, excluded, font_warnings = _gather_fonts(brand_kit, repo, store_root)
    warnings.extend(font_warnings)
    font_face_css = _font_face_css(
        faces, lambda face: f"fonts/{face.digest[:12]}.{face.ext}"
    )
    for face in faces:
        files[f"fonts/{face.digest[:12]}.{face.ext}"] = face.data

    # 2. Delivery render against relative asset urls.
    render = core.web_render(
        web_doc,
        HOME_PAGE_ID,
        mode="delivery",
        asset_base_url="assets",
        font_face_css=font_face_css,
        brand_kit=brand_kit,
        custom_component_runtimes=component_package.frames,
    )
    html = render.get("html") or ""

    # 3. Assets: copy referenced image bytes, rewrite the html to the
    #    extensioned path.
    images = _resolve_images(web_doc)
    exported_images: List[_ImageAsset] = []
    for image in images:
        blob = Path(store_root) / "sha256" / image.digest[:2] / image.digest
        if not blob.is_file():
            warnings.append(
                f"image asset {image.asset_id} ({image.digest[:12]}) skipped: "
                "bytes missing from the asset store"
            )
            continue
        files[f"assets/{image.digest}.{image.ext}"] = blob.read_bytes()
        html = html.replace(
            f"assets/{image.digest}", f"assets/{image.digest}.{image.ext}"
        )
        exported_images.append(image)

    # 4. Static CSS: compile against the doc theme, link it from the html.
    tokens = _theme_tokens(core, web_doc, brand_kit)
    site_css = _compile_static_css(html, tokens, node_bin)
    files["site.css"] = site_css.encode("utf-8")

    # 5. SEO metas + the stylesheet link, injected before </head>.
    og_image = (
        f"assets/{exported_images[0].digest}.{exported_images[0].ext}"
        if exported_images
        else None
    )
    head = _seo_snippet(
        title=document["title"],
        description=_seo_description(web_doc, document["title"]),
        og_image=og_image,
    )
    head += '<link rel="stylesheet" href="site.css">\n'
    head += (
        '<meta http-equiv="Content-Security-Policy" content="'
        f'{_escape_attr(_delivery_csp())}">\n'
    )
    head += '<link rel="lumen-component-manifest" href="components/manifest.json">\n'
    html = _inject_before_head_close(html, head)

    # 6. manifest.json — the file list is known now (index/manifest added last).
    file_names = sorted(list(files.keys()) + ["index.html", "manifest.json"])
    runtime_version = _runtime_version(html)
    delivery_manifest = _delivery_manifest(
        document,
        kind="export",
        custom_components=component_package.manifest,
        assets=component_package.assets,
        warnings=warnings,
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
        "font_families_included": sorted({face.family for face in faces}),
        "font_families_excluded": excluded,
        "warnings": warnings,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    files["index.html"] = html.encode("utf-8")
    return ExportBundle(files=files, warnings=warnings)


def build_publish_package(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    store_root: str,
    database_path: Any,
    slug: str,
    public_base: str,
    workspace_id: str,
    node_bin: str = "node",
) -> PublishPackage:
    """Build one immutable publish package for same-origin delivery.

    The outer HTML, custom-component artifact graph, trusted runtime host, CSS,
    server first frames, and generated per-node bootstrap modules are all
    pinned by digest. Runtime asset URLs are immutable and never resolve
    ``latest`` registry state.

    Every publish URL this package mints (canonical, og:url, the manifest link,
    the per-asset runtime URLs) is workspace-scoped under ``/w/{workspace_id}``:
    publish slugs became tenant-local at Part II D1 (O6), so a bare ``/p/{slug}``
    is ambiguous. This is the interim O6b scheme — Part-IV item 5 replaces it.
    The ``/asset-store`` URLs stay unprefixed: that route is not part of the
    public publish surface and is unchanged by O6b.
    """
    web_doc = document["scene"]
    brand_kit = _resolve_brand_kit(web_doc, database_path)
    warnings: List[str] = []
    base = public_base.rstrip("/")
    public_prefix = f"{base}/w/{workspace_id}"
    deterministic_seed = (
        f"publish:{document['id']}:{document['current_version']}:"
        f"{_sha256(_canonical_json(web_doc))}"
    )
    component_package = _custom_component_package(
        core,
        repo,
        document,
        custom_component_store_root=Path(store_root) / "custom-components",
        asset_url_for=(
            lambda digest, extension: (
                f"{public_prefix}/p-assets/{digest}.{extension}"
            )
        ),
        deterministic_seed=deterministic_seed,
        embed_runtime_assets=False,
        brand_kit=brand_kit,
    )

    # Fonts (license-gated) as absolute /asset-store urls; no files emitted.
    faces, _excluded, font_warnings = _gather_fonts(brand_kit, repo, store_root)
    warnings.extend(font_warnings)
    font_face_css = _font_face_css(
        faces, lambda face: f"/asset-store/{face.digest}"
    )

    # Delivery render against the absolute same-origin asset route.
    render = core.web_render(
        web_doc,
        HOME_PAGE_ID,
        mode="delivery",
        asset_base_url="/asset-store",
        font_face_css=font_face_css,
        brand_kit=brand_kit,
        custom_component_runtimes=component_package.frames,
    )
    html = render.get("html") or ""

    images = _resolve_images(web_doc)

    # Static CSS compiled and INLINED (no external stylesheet for a single-file
    # publish payload).
    tokens = _theme_tokens(core, web_doc, brand_kit)
    site_css = _compile_static_css(html, tokens, node_bin)

    og_image = f"{base}/asset-store/{images[0].digest}" if images else None
    head = _seo_snippet(
        title=document["title"],
        description=_seo_description(web_doc, document["title"]),
        og_image=og_image,
        canonical=f"{public_prefix}/p/{slug}",
        og_url=f"{public_prefix}/p/{slug}",
    )
    head += f'<style id="lumen-static-css">{site_css}</style>\n'
    publish_manifest = {
        **_delivery_manifest(
            document,
            kind="publish",
            custom_components=component_package.manifest,
            assets=component_package.assets,
            warnings=warnings,
        ),
        "slug": slug,
        "canonical_url": f"{public_prefix}/p/{slug}",
    }
    manifest_digest = _sha256(_canonical_json(publish_manifest))
    head += (
        '<meta http-equiv="Content-Security-Policy" content="'
        f'{_escape_attr(_delivery_csp(base))}">\n'
    )
    head += (
        '<meta name="lumen-publish-manifest-digest" content="'
        f'{manifest_digest}">\n'
    )
    head += (
        '<link rel="lumen-publish-manifest" href="'
        f'{_escape_attr(f"{public_prefix}/p/{slug}/manifest.json")}">\n'
    )
    html = _inject_before_head_close(html, head)
    html_digest = _sha256(html)
    package_digest = _sha256(
        _canonical_json(
            {
                "manifest_digest": manifest_digest,
                "html_digest": html_digest,
                "asset_digests": sorted(component_package.assets),
            }
        )
    )
    return PublishPackage(
        html=html,
        manifest=publish_manifest,
        assets=component_package.assets,
        package_digest=package_digest,
        manifest_digest=manifest_digest,
        html_digest=html_digest,
        runtime_version=_runtime_version(html),
        warnings=warnings,
    )


def build_publish_html(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    store_root: str,
    database_path: Any,
    slug: str,
    public_base: str,
    workspace_id: str,
    node_bin: str = "node",
) -> Tuple[str, Optional[int], List[str]]:
    """Compatibility wrapper for callers that only need the publish HTML."""

    package = build_publish_package(
        core,
        repo,
        document,
        store_root=store_root,
        database_path=database_path,
        slug=slug,
        public_base=public_base,
        workspace_id=workspace_id,
        node_bin=node_bin,
    )
    return package.html, package.runtime_version, package.warnings
