from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from lumen_ingestion import normalize_evidence
from lumen_ingestion.capture.pdf import (
    PdfExtraction,
    extract_pdf_evidence,
    strip_subset_prefix,
    weight_from_suffix,
)
from lumen_ingestion.capture.pdf_vision import (
    NullPdfVision,
    PageForVision,
    PdfVisionResult,
)
from lumen_api.core import CoreClient

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "ingestion"
    / "insight_health_brand_kit.pdf"
)


def _noop(stage: str, progress: float) -> None:
    return None


class _StubCore:
    """Records ingest_asset calls; matches CoreClient.ingest_asset kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "asset": {"record": {"id": kwargs["asset_id"]}}}


def _extract(vision=None) -> tuple[PdfExtraction, _StubCore]:
    stub = _StubCore()
    data = FIXTURE.read_bytes()
    with tempfile.TemporaryDirectory() as store:
        extraction = extract_pdf_evidence(
            data,
            "insight_health_brand_kit.pdf",
            core=stub,
            store_root=store,
            reporter=_noop,
            vision=vision,
        )
    return extraction, stub


# --------------------------------------------------------------------------- #
# Import hygiene (§5.9) — `import lumen_ingestion.capture` pulls no fitz/PIL
# --------------------------------------------------------------------------- #


def test_import_pulls_no_pdf_deps() -> None:
    import subprocess
    import sys

    script = (
        "import sys, lumen_ingestion.capture as _; "
        "bad = [m for m in ('fitz','pymupdf','PIL','playwright') if m in sys.modules]; "
        "assert not bad, bad; print('clean')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


# --------------------------------------------------------------------------- #
# 1. Exact palette (the DoD)
# --------------------------------------------------------------------------- #

EXPECTED_PALETTE = {
    "Mint Green": "#12EAB1",
    "Cold Blue": "#00E3E1",
    "Soft Indigo": "#8080F9",
    "Off White": "#F5F5F5",
    "Ash Black": "#1D1C1D",
    "Mint Green Dark": "#0FD39F",
    "Light Grey": "#E3E5E4",
}


def test_exact_palette() -> None:
    extraction, _ = _extract()
    named = {c.name: c.value for c in extraction.evidence.colors if c.name and c.theme == "light"}
    for name, hex_value in EXPECTED_PALETTE.items():
        assert named.get(name) == hex_value, (name, named.get(name))

    # First palette color (reading order) leads → accent + weight 5.0.
    first = extraction.evidence.colors[0]
    assert first.name == "Mint Green"
    assert "accent" in first.role_hints
    assert first.weight == 5.0


# --------------------------------------------------------------------------- #
# 2. Fonts
# --------------------------------------------------------------------------- #


def test_fonts_aeonik_no_faces_weights() -> None:
    extraction, _ = _extract()
    fonts = extraction.evidence.fonts
    assert fonts, "expected at least one font"
    family = fonts[0]
    assert family.family == "Aeonik"
    assert family.faces == []  # embedded subsets not extractable → LUMI0230 downstream

    weights = {t.weight for t in extraction.evidence.type_samples if t.weight}
    assert 400 in weights and 600 in weights

    # The real PDF carries no "TRIAL" in its (Type3, unnamed) fonts → no hint.
    assert family.license_hint is None


# --------------------------------------------------------------------------- #
# 3. Rules
# --------------------------------------------------------------------------- #


def test_rules_donts_combinations_clearspace() -> None:
    extraction, _ = _extract()
    rules = extraction.evidence.rules
    donts = [r for r in rules if r.kind == "dont"]
    combinations = [r for r in rules if r.kind == "combination"]
    clearspace = [r for r in rules if r.kind == "clearspace"]

    assert len(donts) >= 4
    assert len(combinations) >= 1
    assert len(clearspace) == 1

    # The Off White / Ash Black combination sentence is captured.
    assert any("Off White" in r.text and "Ash Black" in r.text for r in combinations)
    # Clearspace text is the body "safe zone" sentence, not a header artifact.
    assert "brand identity guidelines" not in clearspace[0].text.lower()


# --------------------------------------------------------------------------- #
# 4. Logos — reversed dark candidate + dark page-bg evidence + caps
# --------------------------------------------------------------------------- #


def test_logos_reversed_and_dark_theme() -> None:
    extraction, _ = _extract()
    logos = extraction.evidence.logos
    colors = extraction.evidence.colors

    reversed_variants = [l for l in logos if l.color_mode_hint == "reversed"]
    assert reversed_variants, "expected at least one reversed logo candidate"
    assert all(l.background_hint is not None for l in reversed_variants)
    # Dark background_hint is genuinely dark.
    for l in reversed_variants:
        r = int(l.background_hint[1:3], 16)
        assert r < 80

    # A theme="dark" page-bg ColorEvidence exists.
    dark_bg = [c for c in colors if c.theme == "dark" and "page-bg" in c.role_hints]
    assert dark_bg

    # A light full_color primary candidate is present.
    assert any(l.color_mode_hint == "full_color" for l in logos)

    # Caps: ≤ 6 total logos, ≤ 2 variants per LOGO page.
    assert len(logos) <= 6
    per_page: dict[str, int] = {}
    for l in logos:
        per_page[l.pointer.locator.split(" :: ")[0]] = (
            per_page.get(l.pointer.locator.split(" :: ")[0], 0) + 1
        )
    assert all(count <= 2 for count in per_page.values())


# --------------------------------------------------------------------------- #
# 5. DONTS-page images excluded from ImageEvidence
# --------------------------------------------------------------------------- #


def test_donts_images_excluded() -> None:
    extraction, _ = _extract()
    images = extraction.evidence.images
    # Page 11 (DONTS) carries 7 counter-example rasters; none may surface.
    assert all("page 11" not in im.pointer.locator for im in images)
    # The usage-example photos (page 19) DO surface as photo evidence.
    assert images
    assert all(im.kind_hint == "photo" for im in images)


# --------------------------------------------------------------------------- #
# 6. Narrative
# --------------------------------------------------------------------------- #


def test_narrative_brand_name() -> None:
    extraction, _ = _extract()
    narrative = extraction.evidence.narrative
    # camel-case wordmark "InsightHealth" from the running header → "Insight Health".
    assert narrative.brand_name == "Insight Health"
    assert any(f.startswith("reference_pdf:") for f in narrative.summary_facts)


# --------------------------------------------------------------------------- #
# Reference asset + source dict
# --------------------------------------------------------------------------- #


def test_reference_asset_ingested() -> None:
    extraction, stub = _extract()
    assert extraction.reference_asset_id.startswith("asset_ing_")
    assert extraction.page_count == 19

    ref_calls = [c for c in stub.calls if c.get("tags") == ["brand-ingestion", "reference-pdf"]]
    assert len(ref_calls) == 1
    assert ref_calls[0]["kind"] == "document"
    assert ref_calls[0]["asset_id"] == extraction.reference_asset_id

    source = extraction.evidence.source
    assert source["kind"] == "uploaded_pdf"
    assert source["asset_id"] == extraction.reference_asset_id
    assert source["confidence"] == 0.75


# --------------------------------------------------------------------------- #
# 7. Full round-trip (DoD) — real helper
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.environ.get("LUMEN_CORE_HELPER"),
    reason="requires the cargo helper (LUMEN_CORE_HELPER)",
)
def test_roundtrip_validates_against_engine() -> None:
    extraction, _ = _extract()
    result = normalize_evidence(
        extraction.evidence,
        brand_kit_id="brand_kit_ing_pdf",
        name="Insight Health",
        created_at="2026-07-05",
    )
    engine = CoreClient()
    validated = engine.validate_brand_kit(result.brand_kit, product_ready=False)
    assert validated.get("ok") is True

    summary = engine.summarize_brand_kit(result.brand_kit)
    assert summary.get("ok") is True

    # Dark colorway captured from the dark lockup panels.
    assert result.ingestion_report["dark_colorway"] == "captured"
    # Font files not sourced (PDF path) → LUMI0230-class diagnostic.
    assert any(d["code"] == "LUMI0230" for d in result.diagnostics)


# --------------------------------------------------------------------------- #
# 8. Vision merge — scripted stub adds a rule + renames a color; hex untouched
# --------------------------------------------------------------------------- #


class _ScriptedVision:
    """Adds a rule + renames the unnamed dark color, and (illegally) tries to
    alter a deterministic hex — the alter must be ignored."""

    def __init__(self) -> None:
        self.seen_pages = 0

    def review(self, pages: list[PageForVision]) -> PdfVisionResult | None:
        self.seen_pages = len(pages)
        return PdfVisionResult(
            extra_rules=[{"kind": "tone", "text": "calm, precise, clinical"}],
            color_names={"#474747": "Panel Ink", "#1A1A1A": "Panel Ink"},
            tone=["trustworthy"],
        )


def test_vision_merge_additive_only() -> None:
    extraction, _ = _extract(vision=_ScriptedVision())
    ev = extraction.evidence

    # Deterministic palette hex values are untouched.
    named = {c.name: c.value for c in ev.colors if c.name and c.theme == "light"}
    for name, hex_value in EXPECTED_PALETTE.items():
        assert named.get(name) == hex_value

    # The scripted rule was added.
    assert any(r.kind == "tone" and "calm" in r.text.lower() for r in ev.rules)
    assert any(r.kind == "tone" and r.text == "trustworthy" for r in ev.rules)


def test_vision_cannot_alter_hex() -> None:
    class _MaliciousVision:
        def review(self, pages):
            # color_names maps hex→name only; there is no hex-mutation channel.
            # Assert the deterministic hex survives regardless.
            return PdfVisionResult(color_names={"#12EAB1": "Renamed Mint"})

    extraction, _ = _extract(vision=_MaliciousVision())
    mint = [c for c in extraction.evidence.colors if c.value == "#12EAB1"]
    assert mint, "the exact mint hex must survive"
    # The named palette color already had a name → vision does not overwrite it.
    assert mint[0].name == "Mint Green"


def test_null_vision_default() -> None:
    extraction, _ = _extract(vision=NullPdfVision())
    # No vision-sourced rules when the null impl is used.
    assert not any(r.pointer.locator.startswith("vision") for r in extraction.evidence.rules)


# --------------------------------------------------------------------------- #
# Unit primitives — synthetic PDF built in-test with fitz
# --------------------------------------------------------------------------- #


def _tiny_palette_pdf() -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page(width=600, height=400)  # cover (page 1 is always COVER)
    page = doc.new_page(width=600, height=400)
    page.insert_text((50, 60), "Color palette", fontsize=24)
    # inline rgb form (agreement) — matches the printed hex
    page.insert_text((50, 120), "Ocean Blue", fontsize=18)
    page.insert_text((50, 150), "HEX: #1188CC", fontsize=12)
    page.insert_text((50, 170), "R: 17 G: 136 B: 204", fontsize=12)
    # a disagreeing pair (hex wins, LUMI0601)
    page.insert_text((300, 120), "Warm Red", fontsize=18)
    page.insert_text((300, 150), "HEX: #CC2200", fontsize=12)
    page.insert_text((300, 170), "R: 200 G: 0 B: 0", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def test_hex_rgb_agreement_and_disagreement() -> None:
    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        extraction = extract_pdf_evidence(
            _tiny_palette_pdf(), "tiny.pdf", core=stub, store_root=store, reporter=_noop
        )
    named = {c.name: c.value for c in extraction.evidence.colors}
    assert named.get("Ocean Blue") == "#1188CC"
    # disagreement: hex #CC2200 vs rgb #C80000 → trust hex + warning
    assert named.get("Warm Red") == "#CC2200"
    assert any(d["code"] == "LUMI0601" for d in extraction.diagnostics)


def test_name_association_multiline() -> None:
    import fitz

    doc = fitz.open()
    doc.new_page(width=600, height=400)  # cover
    page = doc.new_page(width=600, height=400)
    page.insert_text((50, 60), "Colors", fontsize=24)
    page.insert_text((50, 120), "Deep", fontsize=18)
    page.insert_text((50, 145), "Teal", fontsize=18)
    page.insert_text((50, 175), "HEX: #0F766E", fontsize=12)
    page.insert_text((50, 200), "Second Swatch", fontsize=18)
    page.insert_text((50, 225), "HEX: #123456", fontsize=12)
    data = doc.tobytes()
    doc.close()
    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        extraction = extract_pdf_evidence(
            data, "multi.pdf", core=stub, store_root=store, reporter=_noop
        )
    named = {c.name: c.value for c in extraction.evidence.colors}
    # "Deep" + "Teal" joined across two lines.
    assert named.get("Deep Teal") == "#0F766E"
    assert named.get("Second Swatch") == "#123456"


def test_subset_prefix_stripping() -> None:
    assert strip_subset_prefix("ABCDEF+Aeonik-Regular") == "Aeonik-Regular"
    assert strip_subset_prefix("Aeonik-SemiBold") == "Aeonik-SemiBold"
    assert strip_subset_prefix("AeonikTRIAL-Bold") == "AeonikTRIAL-Bold"


def test_weight_suffix_map() -> None:
    assert weight_from_suffix("Thin") == 100
    assert weight_from_suffix("Light") == 300
    assert weight_from_suffix("Regular") == 400
    assert weight_from_suffix("Medium") == 500
    assert weight_from_suffix("SemiBold") == 600
    assert weight_from_suffix("Semi-bold") == 600
    assert weight_from_suffix("Bold") == 700
    assert weight_from_suffix("Black") == 900
    assert weight_from_suffix("Nonsense") == 400
