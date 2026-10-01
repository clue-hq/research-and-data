"""Discovery-first account resources and historical role pins; no live provider calls."""

import json
from dataclasses import replace

import pytest

from clue_agents import AgentRole
from clue_api.arv2.account_exa_brief import uses_account_discovery
from clue_api.arv2.account_research_catalog import bundle_pin
from clue_api.arv2.quality_catalog import ROOT, load_quality_resources
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_config import Settings
from clue_storage.fs import FsStorage
from tests.arv2.test_account_exa_brief import scope


def test_default_and_new_pins_select_discovery_account_without_changing_person_or_specialists(
    tmp_path,
):
    assert Settings(_env_file=None).arv2_research_catalog_version == "v4"
    bundle = load_quality_resources("arv2-account")
    manifest = json.loads(bundle.profile.body)
    # New runs use the newest recipe: every recipe file has been added in the commit that
    # promoted it, so a literal number here only goes stale on the next promotion.
    newest = max(int(path.stem.removeprefix("recipe-v")) for path in ROOT.glob("recipe-v*.json"))
    assert manifest["recipe_version"] == newest
    assert json.loads((ROOT / "recipe-v12.json").read_text())["version"] == 12
    for revision in range(2, 14):
        old = load_quality_resources("arv2-account", version=revision)
        assert load_quality_resources("arv2-account", expected_pin=bundle_pin(old)) == old
    tools = quality_tools(scope(12), FsStorage(tmp_path), purge=False)
    current = quality_profiles(tools, version=12)
    previous = quality_profiles(tools, version=11)
    account = current.resolve(AgentRole.ACCOUNT_RESEARCH)
    assert account.profile.version == "v12"
    assert previous.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == "v10"
    assert account.profile.prompt.version == "v10"
    skill = next(s for s in account.skills if s.ref.name == "account-dossier")
    assert skill.ref.version == "v3"
    assert "type=auto" in skill.body and "source_review_path" in skill.body
    assert "four or five" in skill.body and "committee limit" in skill.body
    assert "research_brief" in skill.body and "work-email" in skill.body
    for forbidden in (
        "/scratch/",
        "Zafran",
        "Premier",
        "Nick Fisher",
        "Vari Kaur",
        "Nooks",
        "Workato",
    ):
        assert forbidden not in account.prompt_body + skill.body
    for pin in account.profile.tools:
        assert pin in previous.resolve(AgentRole.ACCOUNT_RESEARCH).profile.tools
    for role in (AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE):
        assert current.resolve(role).profile == previous.resolve(role).profile
    assert quality_profiles(tools, version=12, person=True).resolve(AgentRole.ACCOUNT_RESEARCH) == (
        quality_profiles(tools, version=11, person=True).resolve(AgentRole.ACCOUNT_RESEARCH)
    )


@pytest.mark.parametrize(
    "version,person,expected", [(11, False, False), (12, False, True), (12, True, False)]
)
def test_full_source_handoff_is_revision_and_subject_scoped(version, person, expected):
    selected = scope(version, person=person)
    assert uses_account_discovery(selected) == expected
    assert not uses_account_discovery(replace(selected, catalog_version="v2"))
