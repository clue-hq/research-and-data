"""Uploaded-asset analysis (§2): raw files → ``BrandEvidence``.

``analyze_uploads`` sniffs each file by magic bytes, analyses rasters with
Pillow (dims, transparency, dominant colors, hue count) and SVGs by attribute
regex (no rasterization), classifies each deterministically, ingests every file
content-addressed into the asset store, and assembles a ``BrandEvidence`` bundle
with logos, images, and upload-sourced color evidence.

Pillow is lazy-imported inside the raster path so ``import`` of this module (and
its callers) never pulls PIL until an actual raster is analysed. Color parsing
reuses ``parse.py``'s ``parse_color_value`` (same package, no cycle).
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ..colorspace import hex_to_oklch
from ..evidence import (
    BrandEvidence,
    ColorEvidence,
    EvidencePointer,
    ImageEvidence,
    LogoEvidence,
    NarrativeEvidence,
)
from .parse import parse_color_value

MAX_FILES = 100
INGEST_MAX_BYTES = 15 * 1024 * 1024


@dataclass
class UploadFileInput:
    filename: str
    content_type: str | None
    data: bytes


@dataclass
class _Analyzed:
    """Per-file analysis result (internal)."""

    asset_id: str
    filename: str
    classification: str  # logo | icon | illustration | photo | screenshot
    mime: str
    is_svg: bool
    width: int | None
    height: int | None
    transparency: bool | None
    dominant_colors: list[str] = field(default_factory=list)
    color_mode_hint: str | None = None
    usage_hint: str | None = None
    background_hint: str | None = None


def _pointer(filename: str) -> EvidencePointer:
    return EvidencePointer(source="upload", locator=f"upload :: {filename}")


# --- magic-byte sniffing --------------------------------------------------------


def sniff_mime(data: bytes) -> str | None:
    """Return the accepted mime for ``data`` by magic bytes, or None if the file
    is not a supported image type (PNG/JPEG/WebP/SVG)."""
    if data[:8].startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff" or data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if _looks_like_svg(data):
        return "image/svg+xml"
    return None


def _looks_like_svg(data: bytes) -> bool:
    head = data[:512]
    try:
        text = head.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return False
    # Strip a leading BOM/whitespace, an XML declaration, DOCTYPE, and comments,
    # then look for the opening <svg tag near the top.
    stripped = text.lstrip("﻿ \t\r\n")
    stripped = re.sub(r"^<\?xml[^>]*\?>", "", stripped)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"<!DOCTYPE[^>]*>", "", stripped, flags=re.IGNORECASE)
    return "<svg" in stripped.lower()


# --- SVG color + dims (no rasterization) ----------------------------------------

_SVG_COLOR_ATTR_RE = re.compile(
    r"(?:fill|stroke|stop-color)\s*[:=]\s*['\"]?\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))",
    re.IGNORECASE,
)
_SVG_STYLE_COLOR_RE = re.compile(
    r"(?:fill|stroke|stop-color)\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))",
    re.IGNORECASE,
)
_SVG_WIDTH_RE = re.compile(r"<svg\b[^>]*\bwidth\s*=\s*['\"]([\d.]+)", re.IGNORECASE)
_SVG_HEIGHT_RE = re.compile(r"<svg\b[^>]*\bheight\s*=\s*['\"]([\d.]+)", re.IGNORECASE)
_SVG_VIEWBOX_RE = re.compile(
    r"<svg\b[^>]*\bviewBox\s*=\s*['\"]\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)",
    re.IGNORECASE,
)


def _svg_colors(text: str) -> list[str]:
    colors: list[str] = []
    seen: set[str] = set()
    for match in _SVG_COLOR_ATTR_RE.finditer(text):
        raw = match.group(1)
        hex_value = parse_color_value(raw, {})
        if hex_value and hex_value not in seen:
            seen.add(hex_value)
            colors.append(hex_value)
    for match in _SVG_STYLE_COLOR_RE.finditer(text):
        raw = match.group(1)
        hex_value = parse_color_value(raw, {})
        if hex_value and hex_value not in seen:
            seen.add(hex_value)
            colors.append(hex_value)
    return colors[:6]


def _svg_dims(text: str) -> tuple[int | None, int | None]:
    width = _SVG_WIDTH_RE.search(text)
    height = _SVG_HEIGHT_RE.search(text)
    if width and height:
        return int(float(width.group(1))), int(float(height.group(1)))
    viewbox = _SVG_VIEWBOX_RE.search(text)
    if viewbox:
        return int(float(viewbox.group(1))), int(float(viewbox.group(2)))
    return None, None


# --- raster analysis (Pillow, lazy) ---------------------------------------------


def _analyze_raster(data: bytes) -> dict:
    from io import BytesIO

    from PIL import Image  # lazy: only the raster path needs Pillow

    with Image.open(BytesIO(data)) as img:
        img.load()
        width, height = img.size
        mode = img.mode
        dpi = img.info.get("dpi")
        has_alpha = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info)
        transparency = False
        min_alpha = 255
        rgba = img.convert("RGBA")
        if has_alpha:
            alpha = rgba.getchannel("A")
            min_alpha = alpha.getextrema()[0]
            transparency = min_alpha < 250

        dominant = _dominant_colors(rgba)
        opaque_mean_l = _opaque_mean_lightness(rgba)

    return {
        "width": int(width),
        "height": int(height),
        "mode": mode,
        "dpi": dpi,
        "transparency": bool(transparency),
        "dominant_colors": dominant,
        "opaque_mean_l": opaque_mean_l,
    }


def _dominant_colors(rgba) -> list[str]:
    """Dominant colors: thumbnail ≤128px, composite over white, quantize
    adaptive-8, keep palette entries with pixel share ≥ 4%, cap 6."""
    from PIL import Image

    thumb = rgba.copy()
    thumb.thumbnail((128, 128))
    # Composite over white so alpha regions don't skew clustering (matches the
    # website cluster compositing convention).
    background = Image.new("RGBA", thumb.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(background, thumb).convert("RGB")
    quantized = composited.quantize(colors=8, method=Image.Quantize.FASTOCTREE)
    palette = quantized.getpalette() or []
    color_counts = quantized.getcolors() or []  # list[(count, palette_index)]
    total = sum(count for count, _ in color_counts) or 1
    entries: list[tuple[int, str]] = []
    for count, index in color_counts:
        share = count / total
        if share < 0.04:
            continue
        r = palette[index * 3]
        g = palette[index * 3 + 1]
        b = palette[index * 3 + 2]
        hex_value = "#%02X%02X%02X" % (r, g, b)
        entries.append((count, hex_value))
    entries.sort(key=lambda item: item[0], reverse=True)
    return [hex_value for _, hex_value in entries[:6]]


def _opaque_mean_lightness(rgba) -> float | None:
    """Mean OKLCH L over opaque pixels of a small thumbnail, or None if fully
    transparent."""
    thumb = rgba.copy()
    thumb.thumbnail((64, 64))
    pixels = list(thumb.getdata())
    total_l = 0.0
    count = 0
    for r, g, b, a in pixels:
        if a < 128:
            continue
        hex_value = "#%02X%02X%02X" % (r, g, b)
        total_l += hex_to_oklch(hex_value)[0]
        count += 1
    if count == 0:
        return None
    return total_l / count


def _distinct_hue_count(colors: list[str]) -> int:
    """Distinct OKLCH hue buckets (30°) over colors with chroma ≥ 0.07."""
    buckets: set[int] = set()
    for hex_value in colors:
        _l, c, h = hex_to_oklch(hex_value)
        if c < 0.07:
            continue
        buckets.add(int(h // 30))
    return len(buckets)


# --- classification -------------------------------------------------------------


def _classify(
    *,
    filename: str,
    mime: str,
    is_svg: bool,
    width: int | None,
    height: int | None,
    transparency: bool | None,
    dominant_colors: list[str],
) -> str:
    lower = filename.lower()
    # Rule 1: filename says logo — including the lockup vocabulary (wordmarks
    # are naturally wide, so they must not fall through to the aspect gate).
    if any(hint in lower for hint in ("logo", "wordmark", "brandmark", "lockup")):
        return "logo"

    # Rule 2: SVG.
    if is_svg:
        if "icon" in lower:
            return "icon"
        if width and height:
            ratio = width / height if height else 1.0
            if width <= 128 and height <= 128:
                return "icon"
            # Wide lockups (wordmark + mark) commonly run up to ~5:1.
            if 0.2 <= ratio <= 5.0:
                return "logo"
            return "illustration"
        return "logo"

    dom_count = len(dominant_colors)
    dims = [d for d in (width, height) if d is not None]
    min_dim = min(dims) if dims else None

    # Rule 3: transparent, few colors, not huge → logo.
    if transparency and dom_count <= 6 and min_dim is not None and min_dim <= 800:
        return "logo"

    # Rule 4: JPEG, or opaque + large + many colors → photo.
    if mime == "image/jpeg" or (
        not transparency and min_dim is not None and min_dim >= 800 and dom_count >= 6
    ):
        return "photo"

    # Rule 5: else illustration (screenshot by filename).
    if "screenshot" in lower or "screen" in lower:
        return "screenshot"
    return "illustration"


def _logo_hints(
    *,
    filename: str = "",
    width: int | None,
    height: int | None,
    dominant_colors: list[str],
    opaque_mean_l: float | None,
) -> tuple[str, str, str | None]:
    """Return (color_mode_hint, usage_hint, background_hint) for a logo."""
    color_mode = "full_color"
    background_hint = None
    if opaque_mean_l is not None and opaque_mean_l > 0.82:
        color_mode = "reversed"
        background_hint = "#121212"
    elif _distinct_hue_count(dominant_colors) <= 1 and all(
        hex_to_oklch(c)[1] < 0.07 for c in dominant_colors
    ):
        color_mode = "one_color"

    usage_hint = "primary"
    if "wordmark" in filename.lower():
        usage_hint = "wordmark"
    else:
        dims = [d for d in (width, height) if d is not None]
        min_dim = min(dims) if dims else None
        if width and height:
            ratio = width / height if height else 1.0
            if 0.8 <= ratio <= 1.25 and min_dim is not None and min_dim <= 512:
                usage_hint = "mark"
    return color_mode, usage_hint, background_hint


# --- ingest ---------------------------------------------------------------------


def _asset_id(data: bytes) -> str:
    return f"asset_ing_{hashlib.sha256(data).hexdigest()[:16]}"


def _ingest(
    file: UploadFileInput,
    mime: str,
    classification: str,
    *,
    core: Any,
    store_root: str,
) -> str:
    asset_id = _asset_id(file.data)
    now = datetime.now(timezone.utc).isoformat()
    core.ingest_asset(
        store_root=store_root,
        bytes_base64=base64.b64encode(file.data).decode("ascii"),
        asset_id=asset_id,
        label=file.filename,
        declared_mime_type=mime,
        filename=file.filename,
        kind=None,
        provenance={
            "created_by": "lumen_ingestion",
            "created_at": now,
            "source_label": "upload",
            "confidence": 0.8,
            "notes": [],
        },
        source={"kind": "manual", "label": file.filename},
        tags=["brand-ingestion", "upload", classification],
        max_bytes=INGEST_MAX_BYTES,
        raise_on_error=False,
    )
    return asset_id


# --- top-level ------------------------------------------------------------------


def analyze_uploads(
    files: list[UploadFileInput],
    *,
    core: Any,
    store_root: str,
    reporter: Callable[[str, float], None],
) -> tuple[BrandEvidence, list[dict]]:
    """Analyse uploaded files into a ``BrandEvidence`` bundle + diagnostics.

    Unsupported files (magic sniff fails) are skipped with a LUMI0701 warning;
    beyond 100 files are skipped with LUMI0702. If nothing survives, raises
    ``ValueError`` (the job then fails with a clear message).
    """
    diagnostics: list[dict] = []
    reporter("Analyzing your files…", 0.55)

    accepted: list[UploadFileInput] = files
    if len(files) > MAX_FILES:
        diagnostics.append(
            {
                "code": "LUMI0702",
                "severity": "warning",
                "message": f"too many files; analysing first {MAX_FILES}, skipped {len(files) - MAX_FILES}",
            }
        )
        accepted = files[:MAX_FILES]

    analyzed: list[_Analyzed] = []
    for file in accepted:
        mime = sniff_mime(file.data)
        if mime is None:
            diagnostics.append(
                {
                    "code": "LUMI0701",
                    "severity": "warning",
                    "message": f"unsupported file skipped: {file.filename}",
                }
            )
            continue
        analyzed.append(_analyze_one(file, mime, core=core, store_root=store_root))

    if not analyzed:
        raise ValueError("no supported image files in upload batch")

    reporter("Reading your colors…", 0.65)
    logos = [a for a in analyzed if a.classification == "logo"]
    images = [a for a in analyzed if a.classification != "logo"]

    logo_evidence = [
        LogoEvidence(
            asset_id=a.asset_id,
            color_mode_hint=a.color_mode_hint,  # type: ignore[arg-type]
            usage_hint=a.usage_hint,  # type: ignore[arg-type]
            width=float(a.width) if a.width else None,
            height=float(a.height) if a.height else None,
            background_hint=a.background_hint,
            pointer=_pointer(a.filename),
        )
        for a in logos
    ]

    image_evidence = [
        ImageEvidence(
            asset_id=a.asset_id,
            width=a.width,
            height=a.height,
            transparency=a.transparency,
            dominant_colors=a.dominant_colors,
            kind_hint=_image_kind_hint(a.classification),  # type: ignore[arg-type]
            pointer=_pointer(a.filename),
        )
        for a in images
    ]

    # Color evidence: logo/icon/illustration palettes only (photo palettes are
    # scene noise). Weight 2.0, hint "accent", theme light.
    colors: list[ColorEvidence] = []
    for a in analyzed:
        if a.classification not in ("logo", "icon", "illustration"):
            continue
        for hex_value in a.dominant_colors:
            colors.append(
                ColorEvidence(
                    value=hex_value,
                    weight=2.0,
                    theme="light",
                    role_hints=["accent"],
                    name=None,
                    pointer=_pointer(a.filename),
                )
            )

    source = _build_source(analyzed)

    evidence = BrandEvidence(
        source=source,
        colors=colors,
        logos=logo_evidence,
        images=image_evidence,
        narrative=NarrativeEvidence(brand_name=None),
    )
    return evidence, diagnostics


def _analyze_one(
    file: UploadFileInput, mime: str, *, core: Any, store_root: str
) -> _Analyzed:
    is_svg = mime == "image/svg+xml"
    width: int | None
    height: int | None
    transparency: bool | None
    dominant: list[str]
    color_mode_hint: str | None = None
    usage_hint: str | None = None
    background_hint: str | None = None

    if is_svg:
        text = file.data.decode("utf-8", errors="ignore")
        width, height = _svg_dims(text)
        dominant = _svg_colors(text)
        transparency = None
        classification = _classify(
            filename=file.filename,
            mime=mime,
            is_svg=True,
            width=width,
            height=height,
            transparency=None,
            dominant_colors=dominant,
        )
    else:
        info = _analyze_raster(file.data)
        width = info["width"]
        height = info["height"]
        transparency = info["transparency"]
        dominant = info["dominant_colors"]
        classification = _classify(
            filename=file.filename,
            mime=mime,
            is_svg=False,
            width=width,
            height=height,
            transparency=transparency,
            dominant_colors=dominant,
        )

    if classification == "logo":
        color_mode_hint, usage_hint, background_hint = _logo_hints(
            filename=file.filename,
            width=width,
            height=height,
            dominant_colors=dominant,
            opaque_mean_l=None if is_svg else info["opaque_mean_l"],
        )

    asset_id = _ingest(file, mime, classification, core=core, store_root=store_root)
    return _Analyzed(
        asset_id=asset_id,
        filename=file.filename,
        classification=classification,
        mime=mime,
        is_svg=is_svg,
        width=width,
        height=height,
        transparency=transparency,
        dominant_colors=dominant,
        color_mode_hint=color_mode_hint,
        usage_hint=usage_hint,
        background_hint=background_hint,
    )


def _image_kind_hint(classification: str) -> str:
    # ImageEvidence.kind_hint ∈ {photo, illustration, screenshot, icon, og_image}
    if classification in ("photo", "illustration", "screenshot", "icon"):
        return classification
    return "illustration"


def _build_source(analyzed: list[_Analyzed]) -> dict:
    all_logos = all(a.classification == "logo" for a in analyzed)
    first = analyzed[0]
    if all_logos:
        return {
            "kind": "logo_file",
            "asset_id": first.asset_id,
            "filename": first.filename,
            "confidence": 0.8,
        }
    return {
        "kind": "style_guide_image",
        "asset_id": first.asset_id,
        "filename": first.filename,
        "confidence": 0.7,
    }
