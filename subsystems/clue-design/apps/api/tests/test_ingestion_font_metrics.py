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
    ensure_type_size_ramp,
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


# --------------------------------------------------------------------------- #
# ensure_type_size_ramp: republish-time re-normalization (the ramp gap)
# --------------------------------------------------------------------------- #


def test_ensure_ramp_backfills_a_kit_missing_type_size() -> None:
    """A legacy kit produced before the ramp normalizer has empty numbers and
    dies preflight LUMB0301. ensure_type_size_ramp bakes the full 13-step ramp
    in — the identity ramp when no font metrics are present."""
    kit = {"tokens": {"numbers": {}}, "assets": {"fonts": {}}}
    changed = ensure_type_size_ramp(kit)
    assert changed is True
    numbers = kit["tokens"]["numbers"]
    assert set(TYPE_SIZE_REFERENCE_RAMP) <= set(numbers)
    md = numbers["type.size.md"]
    assert md["role"] == "font_size"
    assert md["value"]["default"] == {"kind": "number", "unit": "px", "value": 16.0}
    assert md["value"]["modes"] == {}
    assert "type-size-ramp" in md["provenance"]["source"]


def test_ensure_ramp_is_idempotent_byte_identical() -> None:
    """A kit that already carries the up-to-date ramp republishes byte-for-byte:
    a second ensure call reports no change and leaves the tokens untouched."""
    import copy

    kit = {"tokens": {"numbers": {}}, "assets": {"fonts": {}}}
    assert ensure_type_size_ramp(kit) is True
    snapshot = copy.deepcopy(kit["tokens"]["numbers"])
    assert ensure_type_size_ramp(kit) is False
    assert kit["tokens"]["numbers"] == snapshot


def test_ensure_ramp_matches_normalizer_output_exactly() -> None:
    """The republish path must emit the SAME token entries the normalizer bakes
    at ingestion — one vocabulary, one shape. Compare against a real
    normalize_evidence pass so drift in either producer trips this test."""
    import json

    from lumen_ingestion import BrandEvidence, normalize_evidence

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "ingestion"
        / "evidence_minimal.json"
    )
    evidence = BrandEvidence.model_validate(json.loads(fixture.read_text()))
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_ramp_test",
        name="Ramp Test",
        created_at="2026-07-10T00:00:00Z",
    )
    normalizer_ramp = {
        path: entry
        for path, entry in result.brand_kit["tokens"]["numbers"].items()
        if path.startswith("type.size.")
    }

    kit = {"tokens": {"numbers": {}}, "assets": {"fonts": {}}}
    ensure_type_size_ramp(kit)
    republish_ramp = {
        path: entry
        for path, entry in kit["tokens"]["numbers"].items()
        if path.startswith("type.size.")
    }
    assert republish_ramp == normalizer_ramp


def test_ensure_ramp_reads_the_kits_own_font_metrics() -> None:
    """When the kit carries measured font metrics, the factor comes from the
    heading font's x-height ratio (fonts.brand) — same source the normalizer
    uses. A small x-height scales the ramp up, just like build_type_size_ramp."""
    kit = {
        "tokens": {"numbers": {}},
        "assets": {
            "fonts": {"brand": {"family": "Small X", "metrics": {"x_height_ratio": 0.44}}}
        },
    }
    ensure_type_size_ramp(kit)
    md = kit["tokens"]["numbers"]["type.size.md"]["value"]["default"]["value"]
    expected, _ = build_type_size_ramp(0.44)
    assert md == expected["type.size.md"]["value"]
    assert md > 16.0  # compensated upward
