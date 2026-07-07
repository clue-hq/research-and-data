"""K4 rung 2: measured font metrics + the reference-normalized type.size ramp.

The vocabulary contract: the styles compiler emits a 13-step `type.size.*`
ramp into every kit it produces; the ingestion normalizer must do the same —
with values x-height-normalized against the platform reference font so "7xl"
LOOKS the same size in any brand font.
"""

from __future__ import annotations

from pathlib import Path

from lumen_ingestion.normalizer.font_metrics import (
    TYPE_SIZE_REFERENCE_RAMP,
    build_type_size_ramp,
    extract_font_metrics,
    reference_x_ratio,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"


def test_reference_ramp_matches_the_styles_compiler_table() -> None:
    """Names AND reference values are the cross-producer contract (probed from
    compile_styles_brand_kit on 2026-07-07). If the styles compiler's table
    changes, this must change with it — one vocabulary, two producers."""
    assert set(TYPE_SIZE_REFERENCE_RAMP) == {
        "type.size.xs", "type.size.sm", "type.size.md", "type.size.lg",
        "type.size.xl", "type.size.2xl", "type.size.3xl", "type.size.4xl",
        "type.size.5xl", "type.size.6xl", "type.size.7xl", "type.size.8xl",
        "type.size.9xl",
    }
    assert TYPE_SIZE_REFERENCE_RAMP["type.size.md"] == 16.0
    assert TYPE_SIZE_REFERENCE_RAMP["type.size.7xl"] == 80.0


def test_extract_metrics_from_inter_regular() -> None:
    metrics = extract_font_metrics(INTER.read_bytes())
    assert metrics is not None
    assert metrics["units_per_em"] > 0
    # Inter's x-height ratio is ~0.53; accept a small band so a font-file
    # refresh doesn't break the suite spuriously.
    assert 0.45 <= metrics["x_height_ratio"] <= 0.6
    assert "ascender_ratio" in metrics and "descender_ratio" in metrics


def test_unparseable_bytes_yield_none() -> None:
    assert extract_font_metrics(b"\xde\xad\xbe\xef") is None


def test_identity_ramp_when_brand_ratio_unmeasurable() -> None:
    values, source = build_type_size_ramp(None)
    assert values["type.size.md"]["value"] == 16.0
    assert values["type.size.7xl"]["value"] == 80.0
    assert "no measurable brand x-height" in source


def test_reference_font_gets_the_identity_ramp() -> None:
    """A brand font with the reference's own x-ratio must not be adjusted."""
    values, _ = build_type_size_ramp(reference_x_ratio())
    assert values["type.size.md"]["value"] == 16.0


def test_small_x_height_font_scales_up_snapped_and_clamped() -> None:
    """A Garamond-ish brand font (x-ratio ~0.44) reads smaller at equal pt —
    the ramp compensates upward, snapped to 0.5 and factor-clamped to +20%."""
    values, source = build_type_size_ramp(0.44)
    md = values["type.size.md"]["value"]
    assert md > 16.0
    assert md == round(md * 2) / 2  # snapped
    assert md <= 16.0 * 1.2 + 0.25  # factor clamp honored
    assert "x-height-normalized" in source
    # floor: nothing below print legibility even for extreme inputs
    tiny, _ = build_type_size_ramp(10.0)  # absurd ratio → min factor clamp
    assert min(v["value"] for v in tiny.values()) >= 6.0


def test_trial_otf_subset_still_measures() -> None:
    """The scraped Aeonik TRIAL faces are 69-glyph CFF subsets — the metrics
    pass must still produce ratios for exactly this real-world shape (OS/2 or
    the lowercase-x glyph-bounds fallback)."""
    store = REPO_ROOT / "apps/api/asset-store/sha256"
    face = store / "c0" / "c09e726740622256402284da157dde60297dc8c0bf4ee991ce44f06e78698cbc"
    if not face.exists():
        return  # store not populated in this checkout; covered live
    metrics = extract_font_metrics(face.read_bytes())
    assert metrics is not None
    assert metrics.get("x_height_ratio", 0) > 0
