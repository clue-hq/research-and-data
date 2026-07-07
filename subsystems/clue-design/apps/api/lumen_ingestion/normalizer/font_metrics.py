"""Perceptual type metrics: measured font ratios + the reference-normalized
type-size ramp (K4 rung 2).

Two fonts at the same pt size do not LOOK the same size — apparent size tracks
x-height. The platform's canonical ``type.size.*`` ramp (the styles compiler's
table) is defined in REFERENCE terms: the pt values as they read in the
platform reference font (Inter). At ingestion we measure the kit's real font
(fontTools over the stored bytes) and bake an adjusted ramp into the kit —
``adjusted = reference_pt × (reference_x_ratio / brand_x_ratio)`` — the same
compensation CSS ``font-size-adjust`` performs, done once at the producer so
every resolver (engine preflight, editor canvas, exports) inherits it as plain
numbers. No per-brand logic anywhere: bytes in, ratios out.

The measured metrics block also rides the kit (``fonts.*.metrics``, a
first-class engine field) for downstream consumers: copy-fit estimation
(avg-char-width), vertical-rhythm compensation, and evals asserting on
apparent size.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

JsonObject = dict[str, Any]

#: The styles compiler's platform ramp — the canonical `type.size.*`
#: vocabulary, in reference-font (Inter) terms. Names are the contract shared
#: by the knowledge docs, the DSL author, and both kit producers.
TYPE_SIZE_REFERENCE_RAMP: dict[str, float] = {
    "type.size.xs": 12.0,
    "type.size.sm": 14.0,
    "type.size.md": 16.0,
    "type.size.lg": 20.0,
    "type.size.xl": 24.0,
    "type.size.2xl": 32.0,
    "type.size.3xl": 36.0,
    "type.size.4xl": 40.0,
    "type.size.5xl": 48.0,
    "type.size.6xl": 64.0,
    "type.size.7xl": 80.0,
    "type.size.8xl": 96.0,
    "type.size.9xl": 128.0,
}

#: Inter-Regular's measured x-height ratio — the fallback when the repo font
#: file is unavailable at runtime (value verified against fonts/Inter-Regular
#: .ttf; recompute with `extract_font_metrics` if the reference font changes).
_REFERENCE_X_RATIO_FALLBACK = 0.536

#: An outlier font must not explode or collapse the ramp: the adjustment
#: factor is clamped to ±20%, and no step may fall below the print legibility
#: floor. Snapping keeps print-vendor-friendly quarter-point values.
_ADJUSTMENT_BAND = (0.8, 1.2)
_MIN_SIZE_PT = 6.0
_SNAP_STEP = 0.5

_reference_ratio_cache: Optional[float] = None


def extract_font_metrics(data: bytes) -> Optional[JsonObject]:
    """Measured metrics ratios for one font face, or None if the bytes do not
    parse. OS/2 x-height is cross-checked against the actual lowercase 'x'
    glyph bounds (some fonts lie in OS/2, some subsets omit it)."""
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(BytesIO(data), lazy=True)
        upm = float(font["head"].unitsPerEm)
        if upm <= 0:
            return None
        os2 = font["OS/2"] if "OS/2" in font else None
        hhea = font["hhea"] if "hhea" in font else None

        x_height = float(getattr(os2, "sxHeight", 0) or 0)
        if x_height <= 0:
            x_height = _glyph_x_height(font) or 0.0
        cap_height = float(getattr(os2, "sCapHeight", 0) or 0)
        avg_width = float(getattr(os2, "xAvgCharWidth", 0) or 0)

        metrics: JsonObject = {"units_per_em": upm}
        if x_height > 0:
            metrics["x_height_ratio"] = round(x_height / upm, 4)
        if cap_height > 0:
            metrics["cap_height_ratio"] = round(cap_height / upm, 4)
        if avg_width > 0:
            metrics["avg_char_width_ratio"] = round(avg_width / upm, 4)
        if hhea is not None:
            metrics["ascender_ratio"] = round(float(hhea.ascender) / upm, 4)
            metrics["descender_ratio"] = round(float(hhea.descender) / upm, 4)
            metrics["line_gap_ratio"] = round(float(hhea.lineGap) / upm, 4)
        return metrics
    except Exception:
        logger.debug("font metrics extraction failed", exc_info=True)
        return None


def _glyph_x_height(font: Any) -> Optional[float]:
    """The lowercase 'x' bounding-box height — format-agnostic (TTF glyf and
    OTF CFF both resolve through the glyph set + bounds pen)."""
    try:
        from fontTools.pens.boundsPen import BoundsPen

        cmap = font.getBestCmap()
        glyph_name = cmap.get(ord("x"))
        if not glyph_name:
            return None
        glyph_set = font.getGlyphSet()
        pen = BoundsPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
        if pen.bounds is None:
            return None
        (_, y_min, _, y_max) = pen.bounds
        return float(y_max - y_min)
    except Exception:
        return None


def reference_x_ratio() -> float:
    """The platform reference font's x-height ratio, measured from the repo's
    own Inter-Regular bytes (the same parity-contract file the renderers
    bundle) — constant fallback only if the file is unreachable."""
    global _reference_ratio_cache
    if _reference_ratio_cache is not None:
        return _reference_ratio_cache
    ratio = _REFERENCE_X_RATIO_FALLBACK
    try:
        repo_root = Path(__file__).resolve().parents[4]
        candidate = repo_root / "fonts" / "Inter-Regular.ttf"
        if candidate.exists():
            metrics = extract_font_metrics(candidate.read_bytes())
            measured = (metrics or {}).get("x_height_ratio")
            if isinstance(measured, float) and measured > 0:
                ratio = measured
    except Exception:
        pass
    _reference_ratio_cache = ratio
    return ratio


def build_type_size_ramp(
    brand_x_ratio: Optional[float],
) -> tuple[dict[str, JsonObject], str]:
    """The kit's `type.size.*` ramp as number-token values, x-height-normalized
    against the reference font when the brand ratio is measurable — identity
    (reference values verbatim) when it is not. Returns (values, provenance
    source string): the provenance names the factor so the adjustment is
    auditable in the kit JSON rather than invisible."""
    factor = 1.0
    if isinstance(brand_x_ratio, (int, float)) and brand_x_ratio > 0:
        raw = reference_x_ratio() / float(brand_x_ratio)
        factor = min(max(raw, _ADJUSTMENT_BAND[0]), _ADJUSTMENT_BAND[1])
    values: dict[str, JsonObject] = {}
    for name, reference_pt in TYPE_SIZE_REFERENCE_RAMP.items():
        adjusted = max(_MIN_SIZE_PT, reference_pt * factor)
        snapped = round(adjusted / _SNAP_STEP) * _SNAP_STEP
        values[name] = {"kind": "number", "unit": "px", "value": float(snapped)}
    if factor == 1.0:
        source = "derived:type-size-ramp (reference values; no measurable brand x-height)"
    else:
        source = (
            f"derived:type-size-ramp x-height-normalized "
            f"(factor {factor:.3f} = reference {reference_x_ratio():.3f} / brand {brand_x_ratio:.3f})"
        )
    return values, source
