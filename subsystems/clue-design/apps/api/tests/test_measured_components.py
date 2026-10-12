"""MeasuredComponents@1 (Wave 2 A9, Task X5): the measured recipes, their place on the kit, and the
kit sections kept across every re-validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from lumen_api.brand_kit_sections import KIT_SECTIONS_OUTSIDE_ENGINE, carry_kit_sections
from lumen_ingestion.brief import kit_token_names
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.measured_components import MeasuredComponentsRefused, validate_measured_components
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens
from lumen_ingestion.pipeline import _attach_measured_components

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]
HARVEST = json.loads((TESTS / "fixtures" / "capture" / "style_states.harvest.json").read_text())
CSS = (TESTS / "fixtures" / "capture" / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
#: Garner's kit without `brief` and `grammar_audit` (tracked; Task X4).
GARNER = TESTS / "fixtures" / "ingestion" / "garner_kit.json"


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
    assert KIT_SECTIONS_OUTSIDE_ENGINE == ("brief", "grammar_audit", "measured_components")
    assert validated == {"id": "k", "tokens": {"colors": {}}}, "the engine's result is not mutated"


def test_site_kit_fixture_kits_are_current() -> None:
    spec = importlib.util.spec_from_file_location("fixtures", ROOT / "scripts" / "build_site_kit_brand_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not module.BRANDS.exists():
        pytest.skip(f"the spike's brand export is not in this checkout ({module.BRANDS}, gitignored); "
                    "the fixture kits are regenerated from it")
    for name, text in module.build_all().items():
        committed = (module.KITS_DIR / name).read_text()
        assert committed == text, f"{name} is stale: run scripts/build_site_kit_brand_fixtures.py"
