"""MeasuredComponents@1 (Wave 2 A9, Task X5): the measured recipes, their place on the kit, and the
kit sections kept across every re-validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from lumen_api.brand_kit_sections import KIT_SECTIONS_OUTSIDE_ENGINE, carry_kit_sections
from lumen_ingestion import BrandEvidence, normalize_evidence
from lumen_ingestion.brief import kit_token_names
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import MotionEvidence
from lumen_ingestion.measured_components import MeasuredComponentsRefused, validate_measured_components
from lumen_ingestion.normalizer.bands import BandSurface
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens
from lumen_ingestion.normalizer.geometry import MEASURED_CONFIDENCE
from lumen_ingestion.pipeline import _attach_measured_components

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
CSS = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
#: Garner's kit without `brief` and `grammar_audit` (tracked; Task X4).
GARNER = TESTS / "fixtures" / "ingestion" / "garner_kit.json"
#: A real evidence bundle (Insight Health's site) for running `normalize_evidence` itself.
INSIGHT = TESTS / "fixtures" / "ingestion" / "evidence_website_insight.json"


def _fixtures_script():
    spec = importlib.util.spec_from_file_location("fixtures", ROOT / "scripts" / "build_site_kit_brand_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _band_tokens(kit: dict) -> dict:
    return {p: e for p, e in kit["tokens"]["colors"].items() if p.startswith(("surface.band.", "text.band."))}


def _minted() -> tuple[dict, dict]:
    kit = json.loads(GARNER.read_text())
    parsed = parse_geometry(HARVEST, page_url="https://fixture.test/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=CSS)])
    return kit, mint_component_tokens(kit, parsed.styles, motion).section


def test_the_minted_section_validates_and_every_name_resolves_in_the_kit() -> None:
    kit, section = _minted()
    checked = validate_measured_components(section, token_names=kit_token_names(kit))
    solid = next(s for s in checked["styles"] if s["component"] == "button" and s["variant"] == "solid.047464")
    assert solid["rest"]["case"] in kit_token_names(kit), "style tokens are names the token law knows"
    assert checked["schema_version"] == 1 and checked["source"] == "website:https://fixture.test/"
    assert {s["component"] for s in checked["styles"]} >= {"button", "link", "nav_link", "card"}
    assert checked["motion"]["animations"] == ["motion.animation.pulse"]


def test_a_name_the_kit_does_not_carry_refuses_the_whole_section() -> None:
    kit, section = _minted()
    section["styles"][0]["rest"]["fill"] = "button.ghost-ffffff.fill"
    with pytest.raises(MeasuredComponentsRefused, match="button.ghost-ffffff.fill"):
        validate_measured_components(section, token_names=kit_token_names(kit))


def test_a_slot_outside_the_vocabulary_is_refused() -> None:
    kit, section = _minted()
    section["styles"][0]["rest"]["background"] = "surface.brand"
    with pytest.raises(MeasuredComponentsRefused):
        validate_measured_components(section, token_names=kit_token_names(kit))


def test_a_style_is_named_by_its_look_never_by_its_rank() -> None:
    """Founder Q-A9-6: `solid.047464` (and `solid.047464.d36e` beside a same-coloured twin) are
    names; an old kit's `solid.2` never appears in a measured section."""
    kit, section = _minted()
    assert {s["variant"] for s in section["styles"] if s["component"] == "button"} == {
        "outline.0d2b25", "solid.047464", "solid.0a4a8a", "solid.28241e", "solid.7c4cff",
    }
    section["styles"][0]["variant"] = "solid.047464.d36e"
    validate_measured_components(section, token_names=kit_token_names(kit))
    section["styles"][0]["variant"] = "solid.2"
    with pytest.raises(MeasuredComponentsRefused):
        validate_measured_components(section, token_names=kit_token_names(kit))


def test_the_pipeline_attaches_the_section_or_says_why_not() -> None:
    kit, section = _minted()
    diagnostics: list[dict] = []
    attached = _attach_measured_components(kit, section, diagnostics)
    assert attached["measured_components"]["styles"] and diagnostics == []
    broken = json.loads(json.dumps(section))
    broken["styles"][0]["rest"]["fill"] = "nope.fill"
    kept = _attach_measured_components(kit, broken, diagnostics)
    assert "measured_components" not in kept
    assert [d["code"] for d in diagnostics] == ["LUMI0608"]
    assert _attach_measured_components(kit, None, []) is kit


def test_kit_sections_outside_the_engine_are_carried_onto_the_validated_kit() -> None:
    stored = {"id": "k", "tokens": {}, "brief": {"schema_version": 1}, "grammar_audit": {"schema_version": 1},
              "measured_components": {"schema_version": 1}, "other": 1}
    validated = {"id": "k", "tokens": {"colors": {}}}
    carried = carry_kit_sections(stored, validated)
    assert carried == {"id": "k", "tokens": {"colors": {}}, "brief": {"schema_version": 1},
                       "grammar_audit": {"schema_version": 1}, "measured_components": {"schema_version": 1}}
    assert KIT_SECTIONS_OUTSIDE_ENGINE == ("brief", "grammar_audit", "measured_components", "responsive_type")
    assert validated == {"id": "k", "tokens": {"colors": {}}}, "the engine's result is not mutated"


def test_site_kit_fixture_kits_are_current() -> None:
    module = _fixtures_script()
    if not module.BRANDS.exists():
        pytest.skip(f"the spike's brand export is not in this checkout ({module.BRANDS}, gitignored); "
                    "the fixture kits are regenerated from it")
    kits = module.build_all()
    for name, text in kits.items():
        committed = (module.KITS_DIR / name).read_text()
        assert committed == text, f"{name} is stale: run scripts/build_site_kit_brand_fixtures.py"
    assert module.BRAND_PAGE_FIXTURE.read_text() == module.build_brand_page(kits), (
        "brand-kit.measured.json is stale: run scripts/build_site_kit_brand_fixtures.py"
    )


def test_the_fixture_band_step_adds_exactly_what_ingestion_adds() -> None:
    """probe.minted stands in for a kit ingestion made, so the script's band step adds what
    `normalize_evidence`'s band block adds for the same bands: the REAL block, run over a real evidence
    bundle with and without the probe's band sequence. Styles and motion are left out of both runs:
    ingestion mints them after the bands, and the script's band step runs before its minting too."""
    script = _fixtures_script()
    evidence = BrandEvidence.model_validate(json.loads(INSIGHT.read_text()))
    geometry = parse_geometry(HARVEST, page_url="https://fixture.test/").evidence()

    def normalized(sequence: list) -> dict:
        bare = geometry.model_copy(update={"background_sequence": sequence, "styles": [], "motion": MotionEvidence()})
        return normalize_evidence(
            evidence.model_copy(update={"geometry": bare}),
            brand_kit_id="brand_kit_band_parity", version=1, name="Band parity", created_at="2026-10-13",
        ).brand_kit

    ingested, without_bands = normalized(list(geometry.background_sequence)), normalized([])
    fixture = json.loads(json.dumps(without_bands))
    script._add_bands(fixture, list(geometry.background_sequence))
    assert fixture["tokens"]["colors"] == ingested["tokens"]["colors"]
    assert fixture["constraints"]["contrast_pairs"] == ingested["constraints"]["contrast_pairs"]
    # Both of `_band_ink`'s branches ran: a token holds #FFFFFF, and nothing holds #111111.
    assert set(_band_tokens(ingested)) == {"surface.band.ffffff", "surface.band.014036", "text.band.ffffff"}
    assert {"foreground": "text.inverse", "background": "surface.band.014036", "min_ratio": 4.5} in fixture["constraints"]["contrast_pairs"]


def test_probe_minted_carries_the_ink_ingestion_mints_on_its_light_band() -> None:
    """Over the Garner kit no colour token holds #111111, the text measured on the probe's white
    bands, so that band's ink is `text.band.ffffff`, minted as `_band_ink` mints it; #FFFFFF on the
    forest band is text.inverse."""
    script = _fixtures_script()
    kit = json.loads(GARNER.read_text())
    script._add_bands(kit, parse_geometry(HARVEST, page_url="https://fixture.test/").background_sequence)
    ink = kit["tokens"]["colors"]["text.band.ffffff"]
    assert ink["value"] == {"default": {"kind": "hex", "value": "#111111"}, "modes": {}}
    assert (ink["role"], ink["description"]) == ("text", "text measured on that section background")
    assert "text on section background" in ink["provenance"]["source"]
    assert ink["provenance"]["confidence"] == MEASURED_CONFIDENCE
    assert kit["constraints"]["contrast_pairs"][-2:] == [
        {"foreground": "text.band.ffffff", "background": "surface.band.ffffff", "min_ratio": 4.5},
        {"foreground": "text.inverse", "background": "surface.band.014036", "min_ratio": 4.5},
    ]
    committed = json.loads((script.KITS_DIR / "probe.minted.json").read_text())
    assert _band_tokens(committed) == _band_tokens(kit)
    assert committed["constraints"]["contrast_pairs"][-2:] == kit["constraints"]["contrast_pairs"][-2:]


def test_a_translucent_token_never_holds_a_band_ink_in_the_fixture_step() -> None:
    """The ink match is exact, alpha included, as in `normalizer._band_ink`: `#FAF5E680` is not the
    opaque `#FAF5E6` measured on a band, so the band gets its own `text.band.<hex>`."""
    script = _fixtures_script()
    band = BandSurface(
        path="surface.band.28241e", hex="#28241E", description="section background (1 band, 600px)",
        provenance="website:https://synthetic.example/ :: section background (sections 0)", ink_hex="#FAF5E6",
    )

    def holding(value: str) -> dict:
        return {"text.cream": {"value": {"default": {"kind": "hex", "value": value}, "modes": {}}}}

    assert script._band_ink(holding("#FAF5E680"), band) == "text.band.28241e"
    assert script._band_ink(holding("#FAF5E6"), band) == "text.cream"
    assert script._band_ink(holding("#FAF5E6FF"), band) == "text.cream"


def test_the_kit_read_serves_measured_components_and_style_tokens_whole() -> None:
    """The Brand page reads `GET /brand-kits/{id}` (Task X6); its DTO passes the stored kit through."""
    from lumen_api.dto import brand_kit_detail_dto

    kit, section = _minted()
    kit["measured_components"] = section
    record = {
        "brand_kit_id": kit["id"], "version": 1, "name": kit["name"], "approval_status": "draft",
        "brand_kit": kit, "brand_summary": {}, "diagnostics": [], "created_at": None, "updated_at": None,
    }
    served = brand_kit_detail_dto(record)["brand_kit_json"]
    assert served["measured_components"] == section
    assert served["tokens"]["styles"] and served["tokens"]["styles"] == kit["tokens"]["styles"]
