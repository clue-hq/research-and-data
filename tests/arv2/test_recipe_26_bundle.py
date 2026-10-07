"""Recipe 26 pins the phase-1 waste-removal tools; recipe 25 stays byte-identical.

docs/superpowers/plans/2026-10-07-research-cost-phase1.md Task 9.
"""

import yaml

from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION, load_quality_resources
from clue_api.arv2.quality_json_dossier import SaveDossierSectionToolV2
from clue_api.arv2.quality_provider_tools import AcquireResearchToolV2
from clue_toolbelt.envelope import _schema_sha256

V2 = {"save_dossier_section", "update_dossier_findings", "acquire_research_evidence"}


def _profiles(version):
    bundle = load_quality_resources("arv2-account", version=version)
    return {
        r.ref.split(":", 1)[1]: yaml.safe_load(r.body)
        for r in bundle.skills
        if r.ref.endswith("profile.yaml") and "research/v" in r.ref
    }


def test_recipe_26_loads_hash_verified_and_pins_the_v2_tools():
    assert CURRENT_RECIPE_VERSION == 26
    profiles = _profiles(26)
    assert set(profiles) == {
        "profiles/quality-account-research/v26/profile.yaml",
        "profiles/quality-person-research/v26-person/profile.yaml",
    }
    for profile in profiles.values():
        tools = {t["name"]: t for t in profile["tools"]}
        assert {name: tools[name]["version"] for name in V2} == dict.fromkeys(V2, "2")
        save = tools["save_dossier_section"]
        assert save["input_schema_sha256"] == _schema_sha256(SaveDossierSectionToolV2.input_model)
        acquire = tools["acquire_research_evidence"]
        assert acquire["output_schema_sha256"] == _schema_sha256(AcquireResearchToolV2.output_model)


def test_recipe_26_allows_the_v2_tool_addresses_only():
    bundle = load_quality_resources("arv2-account", version=26)
    recipe = next(r for r in bundle.skills if r.ref.endswith("recipe-v26.json"))
    for name in V2:
        assert f"{name}@2" in recipe.body and f"{name}@1" not in recipe.body


def test_recipe_25_still_loads_byte_identical():
    assert set(_profiles(25)) == {
        "profiles/quality-account-research/v25/profile.yaml",
        "profiles/quality-person-research/v25-person/profile.yaml",
    }
