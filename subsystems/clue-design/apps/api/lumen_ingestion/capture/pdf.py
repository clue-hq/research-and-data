"""Brand-guidelines PDF → ``BrandEvidence`` extraction (slice 2, §2).

pymupdf (fitz) covers text, fonts, embedded rasters, and page rendering; Pillow
handles panel cropping for vector logos. Both are lazy-imported INSIDE functions
so ``import lumen_ingestion.capture`` never pulls them.

The extraction is deterministic. An optional ``PdfVisionAssist`` may ADD rules,
color names, logo-variant hints, page reclassifications, and tone/imagery notes;
it may never mutate an extracted hex value (§3 merge policy).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..evidence import (
    BrandEvidence,
    ColorEvidence,
    EvidencePointer,
    FontEvidence,
    ImageEvidence,
    LogoEvidence,
    NarrativeEvidence,
    RuleEvidence,
    TypeSample,
)
from .pdf_vision import NullPdfVision, PageForVision, PdfVisionAssist, PdfVisionResult

# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #


@dataclass
class PdfExtraction:
    evidence: BrandEvidence
    diagnostics: list[dict]
    reference_asset_id: str
    page_count: int


# Page kinds (deterministic classification).
COVER = "cover"
PALETTE = "palette"
SHADES = "shades"
COMBINATIONS = "combinations"
LOGO = "logo"
LOGOTYPE = "logotype"
LOGOMARK = "logomark"
CLEARSPACE = "clearspace"
DONTS = "donts"
TYPOGRAPHY = "typography"
OTHER = "other"

_LOGO_KINDS = {LOGO, LOGOTYPE, LOGOMARK}

# HEX: prefix or a bare #; the value itself is 6 hex digits.
_HEX_RE = re.compile(r"(?:HEX:?\s*|#)#?([0-9A-Fa-f]{6})\b")
# Inline rgb triplet (kept for guideline PDFs that print R: 18 G: 234 B: 177).
_RGB_INLINE_RE = re.compile(
    r"R:?\s*(\d{1,3})\s*G:?\s*(\d{1,3})\s*B:?\s*(\d{1,3})", re.IGNORECASE
)
_CMYK_RE = re.compile(
    r"C:?\s*(\d{1,3})\s*M:?\s*(\d{1,3})\s*Y:?\s*(\d{1,3})\s*K:?\s*(\d{1,3})", re.IGNORECASE
)
_PANTONE_RE = re.compile(r"PANTONE\s+(\S+)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(pt|px|mm)", re.IGNORECASE)

_HEADER_ARTIFACTS = {
    "version",
    "hex",
    "r",
    "g",
    "b",
    "insighthealth brand identity guidelines",
}

_WEIGHT_SUFFIXES = {
    "thin": 100,
    "extralight": 200,
    "ultralight": 200,
    "light": 300,
    "regular": 400,
    "book": 400,
    "medium": 500,
    "semibold": 600,
    "semi-bold": 600,
    "demibold": 600,
    "bold": 700,
    "extrabold": 800,
    "black": 900,
    "heavy": 900,
}


def _pointer(locator: str) -> EvidencePointer:
    return EvidencePointer(source="pdf", locator=locator)


def _norm(text: str) -> str:
    return text.strip().lower()


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def extract_pdf_evidence(
    pdf_bytes: bytes,
    filename: str,
    *,
    core: Any,
    store_root: str,
    reporter: Callable[[str, float], None],
    vision: PdfVisionAssist | None = None,
) -> PdfExtraction:
    import fitz  # lazy

    vision = vision or NullPdfVision()
    diagnostics: list[dict] = []

    reporter("Reading your brand guidelines…", 0.05)

    reference_asset_id = _ingest_reference_pdf(
        pdf_bytes, filename, core=core, store_root=store_root
    )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = [_read_page(doc, i) for i in range(doc.page_count)]
        page_count = doc.page_count

        # Empty/failed text layer diagnostics (§6: LUMI0606).
        empty_pages = [p for p in pages if not p.text.strip()]
        for p in empty_pages:
            diagnostics.append(
                {
                    "code": "LUMI0606",
                    "severity": "warning",
                    "message": f"empty or failed text layer on page {p.number}",
                }
            )
        if pages and len(empty_pages) == len(pages):
            diagnostics.append(
                {
                    "code": "LUMI0606",
                    "severity": "error",
                    "message": "scanned/image-only PDF not supported in v1 — vision path required",
                }
            )
            raise PdfExtractionError(
                "scanned/image-only PDF not supported in v1 — vision path required"
            )

        # Classify each page.
        for p in pages:
            p.kind, fell_back = _classify(p)
            if fell_back:
                diagnostics.append(
                    {
                        "code": "LUMI0605",
                        "severity": "info",
                        "message": f"page {p.number} classification fell back to '{p.kind}'",
                    }
                )

        # ---- Colors ----
        reporter("Extracting your colors…", 0.25)
        colors, color_diags = _extract_colors(pages)
        diagnostics.extend(color_diags)

        # ---- Logos (+ dark page-bg color evidence) ----
        reporter("Collecting your logos…", 0.45)
        logos, images, dark_colors, logo_diags = _extract_logos_and_images(
            doc, pages, core=core, store_root=store_root, filename=filename
        )
        diagnostics.extend(logo_diags)
        colors.extend(dark_colors)

        # ---- Typography ----
        reporter("Matching your typography…", 0.60)
        fonts, type_samples = _extract_typography(pages)

        # ---- Rules ----
        rules = _extract_rules(pages)

        # ---- Narrative ----
        narrative = _build_narrative(pages, filename, reference_asset_id)

        # ---- Vision assist (additive; re-validated) ----
        vision_result = _run_vision(doc, pages, logos, reporter, vision)
        if vision_result is not None:
            _merge_vision(
                vision_result,
                pages=pages,
                colors=colors,
                logos=logos,
                rules=rules,
                narrative=narrative,
            )
        vision_diags = getattr(vision, "diagnostics", None)
        if vision_diags:
            diagnostics.extend(vision_diags)
    finally:
        doc.close()

    source = {
        "kind": "uploaded_pdf",
        "asset_id": reference_asset_id,
        "filename": filename,
        "confidence": 0.75,
    }

    evidence = BrandEvidence(
        source=source,
        colors=colors,
        type_samples=type_samples,
        fonts=fonts,
        logos=logos,
        images=images,
        rules=rules,
        narrative=narrative,
    )

    return PdfExtraction(
        evidence=evidence,
        diagnostics=diagnostics,
        reference_asset_id=reference_asset_id,
        page_count=page_count,
    )


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot yield any usable evidence (all pages empty)."""


# --------------------------------------------------------------------------- #
# Page model
# --------------------------------------------------------------------------- #


@dataclass
class _Span:
    text: str
    size: float
    font: str
    x: float
    y: float


@dataclass
class _Page:
    number: int  # 1-based
    width: float
    height: float
    text: str
    lines: list[str]
    spans: list[_Span]
    heading: str
    image_count: int
    kind: str = OTHER


def _read_page(doc, index: int) -> _Page:
    page = doc[index]
    text = page.get_text("text")
    lines = [ln for ln in text.split("\n")]
    rect = page.rect
    spans: list[_Span] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "")
                if not t.strip():
                    continue
                bbox = span.get("bbox", (0, 0, 0, 0))
                spans.append(
                    _Span(
                        text=t,
                        size=float(span.get("size", 0.0)),
                        font=str(span.get("font", "")),
                        x=float(bbox[0]),
                        y=float(bbox[1]),
                    )
                )
    heading = _heading_from_spans(spans, rect.height)
    return _Page(
        number=index + 1,
        width=float(rect.width),
        height=float(rect.height),
        text=text,
        lines=lines,
        spans=spans,
        heading=heading,
        image_count=len(page.get_images(full=True)),
    )


def _heading_from_spans(spans: list[_Span], height: float) -> str:
    top = [s for s in spans if s.y <= height * 0.40]
    pool = top or spans
    if not pool:
        return ""
    return max(pool, key=lambda s: s.size).text.strip()


# --------------------------------------------------------------------------- #
# Classification (§2.1)
# --------------------------------------------------------------------------- #


def _is_toc_page(page: _Page) -> bool:
    return "table of content" in _norm(page.heading) or "table of content" in _norm(page.text)


def _classify(page: _Page) -> tuple[str, bool]:
    if page.number == 1:
        return COVER, False
    if _is_toc_page(page):
        return OTHER, False

    heading = _norm(page.heading)
    hex_count = len(_HEX_RE.findall(page.text))

    # Heading-driven classification (most specific first). Insight's running
    # header ("Colors", "Logo design", …) leaks into the top-40% heading pick on
    # some pages, so the heading match is intentionally forgiving.
    if ("color palette" in heading or "colors" in heading or "color" in heading) and hex_count >= 2:
        return PALETTE, False
    if "shade" in heading:
        return SHADES, False
    if "combination" in heading or "combinaton" in heading:
        return COMBINATIONS, False
    if "logomark" in heading or "logo mark" in heading:
        return LOGOMARK, False
    if "logotype" in heading:
        return LOGOTYPE, False
    if "clear space" in heading or "clearspace" in heading:
        return CLEARSPACE, False
    if "don" in heading and "logo don" in heading:  # "Logo Don't ts"
        return DONTS, False
    if "logo" in heading:
        return LOGO, False
    if "typography" in heading or "typeface" in heading or "weight" in heading:
        return TYPOGRAPHY, False

    # Text-driven fallbacks — only for the specific, unambiguous marker pages
    # whose heading was lost to a running-header artifact.
    text = _norm(page.text)
    if hex_count >= 2:
        return PALETTE, True
    # Shades page: the running-header "Colors" wins the heading; identify it by
    # the repeated opacity-step rows (80% / 60% / 40% / 20%).
    if text.count("%") >= 4 and "shade" in text:
        return SHADES, True
    if text.count("80%") and text.count("60%") and text.count("40%") and text.count("20%"):
        return SHADES, True

    return OTHER, False


# --------------------------------------------------------------------------- #
# Colors (§2.2) — text layer; the DoD centerpiece
# --------------------------------------------------------------------------- #


_NAME_STOP_WORDS = {"color palette", "colors", "color", "palette"}


def _is_name_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 28:
        return False
    low = s.lower()
    if low in _HEADER_ARTIFACTS or low in _NAME_STOP_WORDS:
        return False
    if low.startswith("hex"):
        return False
    if re.fullmatch(r"[rgb]:?", low):
        return False
    if _RGB_INLINE_RE.search(s) or _CMYK_RE.search(s):
        return False
    if re.fullmatch(r"[\d.]+%?", s):
        return False
    if _HEX_RE.search(s):
        return False
    # names are word-ish (letters + spaces), title-cased-ish
    if not re.search(r"[A-Za-z]", s):
        return False
    return True


def _extract_colors(pages: list[_Page]) -> tuple[list[ColorEvidence], list[dict]]:
    colors: list[ColorEvidence] = []
    diags: list[dict] = []
    first_palette_seen = False

    for page in pages:
        if page.kind != PALETTE:
            continue
        lines = page.lines
        # Walk lines; each "HEX: #xxxxxx" anchors one color. Name = the
        # consecutive name-ish lines immediately above it (joined). RGB triplet
        # follows positionally (R:/G:/B: labels then three integers) OR inline.
        for i, line in enumerate(lines):
            m = _HEX_RE.search(line)
            if not m or not re.search(r"HEX|#", line, re.IGNORECASE):
                continue
            hex_value = "#" + m.group(1).upper()

            # Name: gather name-ish lines directly above (e.g. "Mint Green" + "Dark").
            name_parts: list[str] = []
            j = i - 1
            while j >= 0 and _is_name_line(lines[j]):
                name_parts.insert(0, lines[j].strip())
                j -= 1
                if len(name_parts) >= 3:
                    break
            name = " ".join(name_parts) if name_parts else None

            # RGB: inline on the same/next lines, else positional labels+values.
            rgb = _rgb_after(lines, i)

            role_hints: list[str] = []
            if name:
                role_hints.append(f"named:{name}")
            # lightness-based hint
            hint = _lightness_hint(hex_value, name)
            if hint:
                role_hints.append(hint)

            # First palette color leads → accent, weight 5.0.
            if not first_palette_seen:
                first_palette_seen = True
                weight = 5.0
                if "accent" not in role_hints:
                    role_hints.append("accent")
            else:
                weight = 4.0

            # hex/rgb agreement check.
            if rgb is not None:
                rgb_hex = "#%02X%02X%02X" % rgb
                if rgb_hex != hex_value:
                    diags.append(
                        {
                            "code": "LUMI0601",
                            "severity": "warning",
                            "message": (
                                f"hex/rgb disagreement for {name or hex_value} "
                                f"(hex {hex_value} vs rgb {rgb_hex}) — trusting hex"
                            ),
                        }
                    )

            # CMYK / Pantone hints attached to the nearest color.
            window = "\n".join(lines[i : i + 8])
            cm = _CMYK_RE.search(window)
            if cm:
                role_hints.append("cmyk:" + ",".join(cm.groups()))
            pm = _PANTONE_RE.search(window)
            if pm:
                role_hints.append("pantone:" + pm.group(1))

            colors.append(
                ColorEvidence(
                    value=hex_value,
                    weight=weight,
                    theme="light",
                    role_hints=role_hints,
                    name=name,
                    pointer=_pointer(f"page {page.number} :: {name or hex_value}"),
                )
            )

    return colors, diags


def _rgb_after(lines: list[str], hex_index: int) -> Optional[tuple[int, int, int]]:
    # inline first: "R: 18 G: 234 B: 177" somewhere near the hex line.
    for k in range(hex_index, min(hex_index + 3, len(lines))):
        m = _RGB_INLINE_RE.search(lines[k])
        if m:
            return tuple(int(x) for x in m.groups())  # type: ignore[return-value]
    # positional: R:/G:/B: labels then the next three integer-only lines.
    labels = 0
    ints: list[int] = []
    for k in range(hex_index + 1, min(hex_index + 10, len(lines))):
        s = lines[k].strip()
        if re.fullmatch(r"[RGB]:?", s, re.IGNORECASE):
            labels += 1
            continue
        if re.fullmatch(r"\d{1,3}", s):
            ints.append(int(s))
            if len(ints) == 3:
                break
        elif ints:
            break
    if labels >= 2 and len(ints) == 3:
        return ints[0], ints[1], ints[2]
    return None


def _lightness_hint(hex_value: str, name: str | None) -> str | None:
    low = (name or "").lower()
    r, g, b = int(hex_value[1:3], 16), int(hex_value[3:5], 16), int(hex_value[5:7], 16)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    if "white" in low or lum > 0.93:
        return "page-bg"
    if "black" in low or lum < 0.25:
        return "body-text"
    return "accent"


# --------------------------------------------------------------------------- #
# Logos + images + dark page-bg colors (§2.4)
# --------------------------------------------------------------------------- #

_MAX_VARIANTS_PER_PAGE = 2
_MAX_LOGO_TOTAL = 6
_MAX_IMAGES = 8


def _usage_for_kind(kind: str) -> str:
    if kind == LOGOMARK:
        return "mark"
    if kind == LOGOTYPE:
        return "wordmark"
    return "primary"


def _extract_logos_and_images(
    doc, pages: list[_Page], *, core: Any, store_root: str, filename: str
):
    import fitz  # lazy

    logos: list[LogoEvidence] = []
    images: list[ImageEvidence] = []
    dark_colors: list[ColorEvidence] = []
    diags: list[dict] = []

    kind_by_number = {p.number: p.kind for p in pages}

    # 1) Embedded raster XObjects on LOGO/COVER pages → logo candidates.
    logo_total = 0
    for page in pages:
        if page.kind not in _LOGO_KINDS and page.kind != COVER:
            continue
        if logo_total >= _MAX_LOGO_TOTAL:
            break
        raster = doc[page.number - 1]
        for img in raster.get_images(full=True):
            if logo_total >= _MAX_LOGO_TOTAL:
                break
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception:
                continue
            short = min(pix.width, pix.height)
            if short < 64:
                continue
            png = _pix_png_bytes(pix)
            asset_id = _ingest_png(
                png, core=core, store_root=store_root, label=f"{filename}-logo-p{page.number}"
            )
            logos.append(
                LogoEvidence(
                    asset_id=asset_id,
                    color_mode_hint="full_color",
                    usage_hint=_usage_for_kind(page.kind),
                    width=float(pix.width),
                    height=float(pix.height),
                    pointer=_pointer(f"page {page.number} :: embedded logo"),
                )
            )
            logo_total += 1

    # 2) Vector logos → render LOGO pages at 2× and crop dark/light demo panels.
    for page in pages:
        if page.kind not in _LOGO_KINDS:
            continue
        if logo_total >= _MAX_LOGO_TOTAL:
            break
        rendered = doc[page.number - 1]
        pix = rendered.get_pixmap(matrix=fitz.Matrix(2, 2))
        panels = _detect_panels(pix)
        variants_here = 0
        for panel in panels:
            if variants_here >= _MAX_VARIANTS_PER_PAGE or logo_total >= _MAX_LOGO_TOTAL:
                break
            crop_png, w, h, dominant = panel
            is_dark = panel_is_dark(dominant)
            asset_id = _ingest_png(
                crop_png,
                core=core,
                store_root=store_root,
                label=f"{filename}-logo-p{page.number}-{'dark' if is_dark else 'light'}",
            )
            if is_dark:
                logos.append(
                    LogoEvidence(
                        asset_id=asset_id,
                        color_mode_hint="reversed",
                        usage_hint=_usage_for_kind(page.kind),
                        width=float(w),
                        height=float(h),
                        background_hint=dominant,
                        pointer=_pointer(f"page {page.number} :: dark panel"),
                    )
                )
                dark_colors.append(
                    ColorEvidence(
                        value=dominant,
                        weight=3.0,
                        theme="dark",
                        role_hints=["page-bg"],
                        pointer=_pointer(f"page {page.number} :: dark panel bg"),
                    )
                )
            else:
                logos.append(
                    LogoEvidence(
                        asset_id=asset_id,
                        color_mode_hint="full_color",
                        usage_hint=_usage_for_kind(page.kind),
                        width=float(w),
                        height=float(h),
                        background_hint=dominant,
                        pointer=_pointer(f"page {page.number} :: light panel"),
                    )
                )
            variants_here += 1
            logo_total += 1

    if not logos:
        diags.append(
            {
                "code": "LUMI0602",
                "severity": "warning",
                "message": "logo appears vector-only and panel detection failed — upload logo files separately",
            }
        )

    # 3) Non-logo embedded images ≥ 200px → photo ImageEvidence (skip DONTS pages).
    image_total = 0
    capped = False
    for page in pages:
        if page.kind == DONTS:
            continue
        if page.kind in _LOGO_KINDS or page.kind == COVER:
            continue
        raster = doc[page.number - 1]
        for img in raster.get_images(full=True):
            if image_total >= _MAX_IMAGES:
                capped = True
                break
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception:
                continue
            if min(pix.width, pix.height) < 200:
                continue
            png = _pix_png_bytes(pix)
            asset_id = _ingest_png(
                png, core=core, store_root=store_root, label=f"{filename}-image-p{page.number}"
            )
            images.append(
                ImageEvidence(
                    asset_id=asset_id,
                    width=pix.width,
                    height=pix.height,
                    kind_hint="photo",
                    pointer=_pointer(f"page {page.number} :: embedded image"),
                )
            )
            image_total += 1
        if capped:
            break
    if capped:
        diags.append(
            {
                "code": "LUMI0603",
                "severity": "info",
                "message": f"image evidence capped at {_MAX_IMAGES}",
            }
        )

    return logos, images, dark_colors, diags


def _pix_png_bytes(pix) -> bytes:
    import fitz  # lazy

    if pix.alpha or pix.n > 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("png")


def _detect_panels(pix):
    """Find the largest contiguous DARK and LIGHT vertical bands in the bottom
    region of a rendered logo page. Returns [(png_bytes, w, h, dominant_hex)].

    Insight's logo pages split the demo lockup into a 50/50 light|dark panel in
    the lower half; we scan columns for a dark band and a light band, crop each
    with a 2% inset, and report the dominant hex of each.
    """
    from PIL import Image

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    W, H = img.size
    # Panels live in the lower ~55% of the page.
    band_top = int(H * 0.45)
    band = img.crop((0, band_top, W, H))
    bw, bh = band.size

    cols = 80
    step = max(1, bw // cols)
    lums: list[float] = []
    for cx in range(0, bw, step):
        strip = band.crop((cx, 0, min(cx + step, bw), bh)).resize((1, 1))
        r, g, b = strip.getpixel((0, 0))
        lums.append((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0)

    dark_run = _longest_run(lums, lambda v: v < 0.30)
    light_run = _longest_run(lums, lambda v: v > 0.70)

    results = []
    for run, need_frac in ((light_run, 0.15), (dark_run, 0.15)):
        if run is None:
            continue
        start, end = run  # indices into lums
        if (end - start + 1) / len(lums) < need_frac:
            continue
        px0 = int(start * step)
        px1 = int(min((end + 1) * step, bw))
        # 2% inset
        inset_x = int((px1 - px0) * 0.02)
        inset_y = int(bh * 0.02)
        crop = band.crop((px0 + inset_x, inset_y, px1 - inset_x, bh - inset_y))
        cw, ch = crop.size
        if cw < 32 or ch < 32:
            continue
        dominant = _dominant_hex(crop)
        results.append((_pil_png_bytes(crop), cw, ch, dominant))
    return results


def _longest_run(values, predicate):
    best = None
    best_len = 0
    start = None
    for i, v in enumerate(values):
        if predicate(v):
            if start is None:
                start = i
        else:
            if start is not None:
                length = i - start
                if length > best_len:
                    best_len = length
                    best = (start, i - 1)
                start = None
    if start is not None:
        length = len(values) - start
        if length > best_len:
            best = (start, len(values) - 1)
    return best


def _dominant_hex(img) -> str:
    # The demo logo sits centered on a flat panel with rounded corners; the
    # panel background is best estimated from a ring just inside the edges
    # (inside the rounded rect, away from both the mark and the page). Take the
    # most common quantized sample so a reversed/light logo doesn't skew it.
    small = img.resize((20, 20))
    px = small.load()
    ring: list[tuple[int, int, int]] = []
    for t in range(3, 17):
        ring.append(px[t, 3])   # top edge
        ring.append(px[t, 16])  # bottom edge
        ring.append(px[3, t])   # left edge
        ring.append(px[16, t])  # right edge
    counts: dict[tuple[int, int, int], int] = {}
    for c in ring:
        key = (c[0] // 16 * 16, c[1] // 16 * 16, c[2] // 16 * 16)
        counts[key] = counts.get(key, 0) + 1
    best_key = max(counts, key=lambda k: counts[k])
    members = [c for c in ring if (c[0] // 16 * 16, c[1] // 16 * 16, c[2] // 16 * 16) == best_key]
    r = sum(c[0] for c in members) // len(members)
    g = sum(c[1] for c in members) // len(members)
    b = sum(c[2] for c in members) // len(members)
    return "#%02X%02X%02X" % (r, g, b)


def panel_is_dark(hex_value: str) -> bool:
    r, g, b = int(hex_value[1:3], 16), int(hex_value[3:5], 16), int(hex_value[5:7], 16)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0 < 0.30


def _pil_png_bytes(img) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Typography (§2.3)
# --------------------------------------------------------------------------- #

_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")


def strip_subset_prefix(name: str) -> str:
    return _SUBSET_PREFIX_RE.sub("", name)


def weight_from_suffix(suffix: str) -> int:
    return _WEIGHT_SUFFIXES.get(suffix.strip().lower().replace(" ", ""), 400)


def _family_from_font_basename(basename: str) -> tuple[str, int]:
    name = strip_subset_prefix(basename)
    if "-" in name:
        family, suffix = name.split("-", 1)
    else:
        family, suffix = name, ""
    return family, weight_from_suffix(suffix)


def _extract_typography(pages: list[_Page]):
    fonts: list[FontEvidence] = []
    type_samples: list[TypeSample] = []

    # Insight's fonts are Type3 with empty basefonts, so page.get_fonts() yields
    # nothing usable; the family is taken from the typography specimen text.
    # (For guideline PDFs with real font subsets the specimen text still names
    # the family, so a single text-first path covers both.)

    # Family from the typography page text: the specimen name (e.g. "AEONIK").
    text_family = _family_from_typography_text(pages)

    weights_present: set[int] = set()
    license_hint: str | None = None

    for page in pages:
        if page.kind != TYPOGRAPHY:
            continue
        low = page.text.lower()
        for label, wt in _WEIGHT_SUFFIXES.items():
            if label in low:
                weights_present.add(wt)
        if "trial" in low:
            license_hint = "trial-filename"

    # Determine role hint from span sizes across content pages.
    heading_family, body_family = _roles_from_spans(pages, text_family)

    if text_family:
        # Ensure at least regular + specimen weights present.
        if not weights_present:
            weights_present = {400}
        role = "heading" if heading_family == text_family else "unknown"
        if body_family == text_family and heading_family == text_family:
            role = "heading"
        fonts.append(
            FontEvidence(
                family=text_family,
                role_hint=role,  # type: ignore[arg-type]
                faces=[],
                license_hint=license_hint,
                pointer=_pointer("typography page :: specimen"),
            )
        )

    # WEIGHTS-page specimen labels → pdf-heading / pdf-body type samples.
    for page in pages:
        if page.kind != TYPOGRAPHY:
            continue
        low = page.text.lower()
        if "semi-bold" in low or "semibold" in low:
            type_samples.append(
                TypeSample(
                    label="pdf-heading",
                    family=text_family,
                    weight=600,
                    pointer=_pointer(f"page {page.number} :: weights"),
                )
            )
        if "regular" in low:
            type_samples.append(
                TypeSample(
                    label="pdf-body",
                    family=text_family,
                    weight=400,
                    pointer=_pointer(f"page {page.number} :: weights"),
                )
            )

    # Span-derived samples: heading span → pdf-heading, body spans → pdf-body.
    for page in pages:
        if page.kind in (COVER, PALETTE, SHADES):
            continue
        content_spans = [s for s in page.spans if s.size > 0]
        if not content_spans:
            continue
        heading_span = max(content_spans, key=lambda s: s.size)
        body_spans = [s for s in content_spans if s.size < 20]
        if heading_span.size >= 20:
            type_samples.append(
                TypeSample(
                    label="pdf-heading",
                    family=text_family,
                    size_px=round(heading_span.size * 96 / 72, 1),
                    pointer=_pointer(f"page {page.number} :: heading span"),
                )
            )
        if body_spans:
            sizes = sorted(s.size for s in body_spans)
            median = sizes[len(sizes) // 2]
            type_samples.append(
                TypeSample(
                    label="pdf-body",
                    family=text_family,
                    size_px=round(median * 96 / 72, 1),
                    pointer=_pointer(f"page {page.number} :: body span"),
                )
            )

    return fonts, type_samples


_TYPE_HEADER_WORDS = {"typeface", "weights", "typography", "regular", "semi-bold", "semibold", "bold"}


def _family_from_typography_text(pages: list[_Page]) -> str | None:
    # The typeface page shows the family name in a very large specimen span
    # (Insight: "AEONIK" at 217pt). Scan ALL typography pages and pick the
    # largest specimen span that is not a section header/weight word.
    best: tuple[float, str] | None = None
    for page in pages:
        if page.kind != TYPOGRAPHY:
            continue
        for span in page.spans:
            if span.size < 40:
                continue
            name = re.sub(r"[^A-Za-z ].*$", "", span.text.strip()).strip()
            if not name or name.lower() in _TYPE_HEADER_WORDS:
                continue
            if best is None or span.size > best[0]:
                best = (span.size, name)
    if best:
        return best[1].title()
    # Fallback: a capitalized single-word specimen in the raw text.
    for page in pages:
        if page.kind != TYPOGRAPHY:
            continue
        for line in page.lines:
            s = line.strip()
            if re.fullmatch(r"[A-Z]{4,}", s) and s.lower() not in _TYPE_HEADER_WORDS:
                return s.title()
    return None


def _roles_from_spans(pages: list[_Page], family: str | None):
    # With a single detected family, both roles map to it.
    return family, family


# --------------------------------------------------------------------------- #
# Rules (§2.2 combinations / §2.5)
# --------------------------------------------------------------------------- #


def _split_sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!])\s+", flat)
    return [p.strip() for p in parts if p.strip()]


def _extract_rules(pages: list[_Page]) -> list[RuleEvidence]:
    rules: list[RuleEvidence] = []

    for page in pages:
        loc = f"page {page.number}"
        if page.kind == SHADES:
            rules.append(
                RuleEvidence(
                    kind="combination",
                    text="shade system: 80/60/40/20% opacity steps of brand colors",
                    numeric_value=None,
                    pointer=_pointer(f"{loc} :: shades"),
                )
            )
        elif page.kind == COMBINATIONS:
            for sentence in _split_sentences(page.text):
                low = sentence.lower()
                if "should be displayed" in low:
                    rules.append(
                        RuleEvidence(
                            kind="combination",
                            text=sentence,
                            pointer=_pointer(f"{loc} :: combination"),
                        )
                    )
                elif low.startswith("don") or "don't use" in low or "dont use" in low:
                    rules.append(
                        RuleEvidence(
                            kind="dont",
                            text=sentence,
                            pointer=_pointer(f"{loc} :: dont"),
                        )
                    )
        elif page.kind == CLEARSPACE:
            # Prefer the "safe zone" body sentence; the "clear space" heading
            # sentence is a running-header artifact, so fall back to it only.
            chosen: str | None = None
            fallback: str | None = None
            for sentence in _split_sentences(page.text):
                low = sentence.lower()
                if "safe zone" in low:
                    chosen = sentence
                    break
                if "clear space" in low and fallback is None and "brand identity guidelines" not in low:
                    fallback = sentence
            picked = chosen or fallback
            if picked:
                num = _NUMBER_RE.search(picked)
                rules.append(
                    RuleEvidence(
                        kind="clearspace",
                        text=picked,
                        numeric_value=float(num.group(1)) if num else None,
                        pointer=_pointer(f"{loc} :: clearspace"),
                    )
                )
        elif page.kind == DONTS:
            for line in page.lines:
                s = re.sub(r"\s+", " ", line).strip()
                if _looks_like_dont(s):
                    rules.append(
                        RuleEvidence(
                            kind="dont",
                            text=s,
                            pointer=_pointer(f"{loc} :: dont"),
                        )
                    )

        # Any page: min size.
        low = page.text.lower()
        if "minimum size" in low or "min size" in low:
            num = _NUMBER_RE.search(page.text)
            if num:
                rules.append(
                    RuleEvidence(
                        kind="min_size",
                        text="minimum size",
                        numeric_value=float(num.group(1)),
                        pointer=_pointer(f"{loc} :: min_size"),
                    )
                )

    return rules


def _looks_like_dont(line: str) -> bool:
    # Insight's text layer garbles "Don't" as "Donˇt t" / "Don t"; match the
    # leading "Don" that begins a caption line.
    low = line.lower()
    return low.startswith("don") and len(line) > 8 and "logo don" not in low


# --------------------------------------------------------------------------- #
# Narrative (§2.6)
# --------------------------------------------------------------------------- #

_COVER_BOILERPLATE = {"brand", "identity", "guidelines", "brand identity", "brand identity guidelines"}


def _split_camel(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).strip()


def _brand_name(pages: list[_Page], filename: str) -> str | None:
    # The cover's largest span is boilerplate ("Brand Identity"/"guidelines");
    # the real wordmark ("InsightHealth") lives in the running header of content
    # pages. Prefer that, split camel-case → "Insight Health".
    for page in pages:
        for span in page.spans:
            low = span.text.strip().lower()
            if "brand identity guidelines" in low:
                wordmark = span.text.strip().split("Brand Identity")[0].strip()
                if wordmark:
                    return _split_camel(wordmark)
    # Fallback: largest non-boilerplate cover span.
    cover = next((p for p in pages if p.kind == COVER), None)
    if cover:
        candidates = [
            s for s in cover.spans if s.text.strip().lower() not in _COVER_BOILERPLATE
        ]
        candidates = [s for s in candidates if len(s.text.strip()) <= 40]
        if candidates:
            return _split_camel(max(candidates, key=lambda s: s.size).text.strip())
    stem = filename.rsplit("/", 1)[-1]
    stem = re.sub(r"\.pdf$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem.title() or None


def _build_narrative(pages: list[_Page], filename: str, reference_asset_id: str) -> NarrativeEvidence:
    brand_name = _brand_name(pages, filename)

    summary_facts: list[str] = [f"reference_pdf:{reference_asset_id}"]
    for page in pages:
        low = _norm(page.heading)
        if any(k in low for k in ("introduction", "about", "aim", "vision")):
            for sentence in _split_sentences(page.text):
                if len(sentence) > 40 and len(sentence) <= 300:
                    summary_facts.append(sentence)
                if len(summary_facts) >= 4:  # reference + up to 3 paragraphs
                    break
        if len(summary_facts) >= 4:
            break

    excerpt = "\n".join(p.text for p in pages)[:3000]

    return NarrativeEvidence(
        brand_name=brand_name,
        summary_facts=summary_facts,
        text_excerpt=excerpt,
    )


# --------------------------------------------------------------------------- #
# Vision merge (§3) — additive, never mutates hex
# --------------------------------------------------------------------------- #


def _run_vision(doc, pages, logos, reporter, vision) -> PdfVisionResult | None:
    if isinstance(vision, NullPdfVision):
        return None
    import base64

    import fitz  # lazy

    reporter("Studying the guidelines…", 0.70)
    payload: list[PageForVision] = []
    for page in pages:
        raster = doc[page.number - 1]
        pix = raster.get_pixmap(matrix=fitz.Matrix(1, 1))
        png_b64 = base64.b64encode(_pix_png_bytes(pix)).decode("ascii")
        payload.append(
            PageForVision(
                page_number=page.number,
                kind_guess=page.kind,
                png_b64=png_b64,
                text=page.text,
            )
        )
    return vision.review(payload)


def _merge_vision(
    result: PdfVisionResult,
    *,
    pages: list[_Page],
    colors: list[ColorEvidence],
    logos: list[LogoEvidence],
    rules: list[RuleEvidence],
    narrative: NarrativeEvidence,
) -> None:
    # Page reclassification (metadata only — does not remove evidence).
    by_number = {p.number: p for p in pages}
    for num, kind in result.page_kinds.items():
        if num in by_number:
            by_number[num].kind = kind

    # Color names for still-unnamed palette colors — NEVER touches value.
    for color in colors:
        if color.name:
            continue
        proposed = result.color_names.get(color.value) or result.color_names.get(
            color.value.upper()
        )
        if proposed:
            color.name = proposed
            hint = f"named:{proposed}"
            if hint not in color.role_hints:
                color.role_hints.append(hint)

    # Extra rules (added, deterministically shaped).
    for raw in result.extra_rules:
        kind = raw.get("kind")
        text = raw.get("text")
        if not kind or not text:
            continue
        try:
            rules.append(
                RuleEvidence(
                    kind=kind,
                    text=str(text),
                    numeric_value=(
                        float(raw["numeric_value"])
                        if raw.get("numeric_value") is not None
                        else None
                    ),
                    pointer=_pointer("vision :: extra rule"),
                )
            )
        except Exception:
            continue

    # Logo variant hints for assets we actually extracted.
    logos_by_id = {l.asset_id: l for l in logos}
    for asset_id, hint in result.logo_variant_hints.items():
        logo = logos_by_id.get(asset_id)
        if not logo:
            continue
        mode = hint.get("color_mode")
        usage = hint.get("usage")
        if mode in {"full_color", "one_color", "reversed", "dark", "light"}:
            logo.color_mode_hint = mode  # type: ignore[assignment]
        if usage in {"primary", "mark", "wordmark"}:
            logo.usage_hint = usage  # type: ignore[assignment]

    # Tone → rules; imagery notes → rules; both additive.
    for tone in result.tone:
        rules.append(
            RuleEvidence(kind="tone", text=str(tone), pointer=_pointer("vision :: tone"))
        )
    for note in result.imagery_notes:
        rules.append(
            RuleEvidence(kind="imagery", text=str(note), pointer=_pointer("vision :: imagery"))
        )


# --------------------------------------------------------------------------- #
# Asset ingest helpers
# --------------------------------------------------------------------------- #


def _ingest_reference_pdf(pdf_bytes: bytes, filename: str, *, core: Any, store_root: str) -> str:
    import base64

    sha = hashlib.sha256(pdf_bytes).hexdigest()
    asset_id = f"asset_ing_{sha[:16]}"
    core.ingest_asset(
        store_root=store_root,
        bytes_base64=base64.b64encode(pdf_bytes).decode("ascii"),
        asset_id=asset_id,
        label=filename,
        declared_mime_type="application/pdf",
        filename=filename,
        kind="document",
        provenance={
            "created_by": "lumen_ingestion",
            "created_at": None,
            "source_label": "uploaded_pdf",
            "confidence": 0.75,
            "notes": [],
        },
        source={"kind": "manual", "label": filename},
        tags=["brand-ingestion", "reference-pdf"],
        max_bytes=64 * 1024 * 1024,
        raise_on_error=False,
    )
    return asset_id


def _ingest_png(png_bytes: bytes, *, core: Any, store_root: str, label: str) -> str:
    import base64

    sha = hashlib.sha256(png_bytes).hexdigest()
    asset_id = f"asset_ing_{sha[:16]}"
    core.ingest_asset(
        store_root=store_root,
        bytes_base64=base64.b64encode(png_bytes).decode("ascii"),
        asset_id=asset_id,
        label=label,
        declared_mime_type="image/png",
        filename=f"{label}.png",
        kind=None,
        provenance={
            "created_by": "lumen_ingestion",
            "created_at": None,
            "source_label": "uploaded_pdf",
            "confidence": 0.75,
            "notes": [],
        },
        source={"kind": "manual", "label": label},
        tags=["brand-ingestion", "image"],
        max_bytes=15 * 1024 * 1024,
        raise_on_error=False,
    )
    return asset_id
