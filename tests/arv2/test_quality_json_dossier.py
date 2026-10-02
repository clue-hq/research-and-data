"""New researcher profiles own JSON formation; old run pins remain reproducible."""

import json
import re

import pytest

from clue_agents import AgentRole
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION, load_quality_resources
from clue_api.arv2.quality_json_dossier import SaveSectionInput
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from tests.arv2.test_dossier_json import finding


@pytest.mark.parametrize("person", [False, True])
def test_current_profiles_own_formation_without_claim_delegation(person):
    registry = quality_tools(None, None, purge=False)
    resolved = quality_profiles(registry, version=CURRENT_RECIPE_VERSION, person=person).resolve(
        AgentRole.ACCOUNT_RESEARCH
    )
    profile = resolved.profile
    names = {t.name for t in profile.tools}
    assert {"save_dossier_section", "validate_dossier", "finish_dossier"} <= names
    assert {"begin_dossier_revision", "discard_dossier_revision"} <= names
    assert "record_research_finding" not in names
    assert "record_research_disposition" not in names
    assert AgentRole.RESEARCH_CLAIMS not in profile.delegation_roles
    assert not profile.delegation_roles
    assert "acquire_research_evidence" in names
    assert CURRENT_RECIPE_VERSION == 24
    bundle = load_quality_resources("person" if person else "account")
    manifest = json.loads(bundle.profile.body)
    assert manifest["recipe_version"] == CURRENT_RECIPE_VERSION
    recipe = next(
        json.loads(r.body)
        for r in bundle.skills
        if r.ref.endswith(f"recipe-v{CURRENT_RECIPE_VERSION}.json")
    )
    allowed = recipe["graph"]["nodes"][1]["dynamic_tool_allowlist"]
    assert all(
        n + "@1" in allowed
        for n in (
            "save_dossier_section",
            "update_dossier_findings",
            "validate_dossier",
            "finish_dossier",
            "begin_dossier_revision",
            "discard_dossier_revision",
        )
    )
    assert "record_research_disposition" not in json.dumps(recipe)
    # All explicitly named skill paths must be mounted by the selected profile.
    mounted = {skill.materialized_path.removeprefix(".deepagent/") for skill in profile.skills}
    resources = {
        path.removeprefix(".deepagent/"): content.decode()
        for path, content in resolved.resource_snapshot.materialized_entries()
    }
    for path, body in resources.items():
        if path in mounted or path.startswith(
            f"prompts/quality-{'person' if person else 'account'}-research/"
        ):
            assert set(re.findall(r"/\.deepagent/(skills/[^\s`]+?/SKILL\.md)", body)) <= mounted
    selected = {skill.resource.name: skill.resource.version for skill in profile.skills}
    assert selected["person-dossier" if person else "account-dossier"] == ("v5" if person else "v9")
    assert (
        selected["claim-ready-person-dossier" if person else "claim-ready-account-dossier"] == "v3"
    )
    if not person:
        assert selected["person-research-briefing"] == "v4"
    old_parent = (
        quality_profiles(registry, version=16, person=person)
        .resolve(AgentRole.ACCOUNT_RESEARCH)
        .profile
    )
    assert "begin_dossier_revision" not in {t.name for t in old_parent.tools}
    load_quality_resources("account", version=16)
    historical = (
        quality_profiles(registry, version=15, person=person)
        .resolve(AgentRole.ACCOUNT_RESEARCH)
        .profile
    )
    assert AgentRole.RESEARCH_CLAIMS in historical.delegation_roles
    load_quality_resources("account", version=15)


def test_save_schema_preserves_trial_contract_and_refuses_unknown_fields():
    entry = finding()
    parsed = SaveSectionInput(section="Voice", findings=[entry])
    assert parsed.findings[0].finding == entry["finding"]
    with pytest.raises(ValueError):
        SaveSectionInput(section="Voice", findings=[{**entry, "silently_dropped": True}])


def test_current_research_roles_can_read_but_not_modify_spilled_receipts():
    tools = quality_tools(None, None, purge=False)
    for person in (False, True):
        registry = quality_profiles(tools, version=19, person=person)
        for role in (
            AgentRole.ACCOUNT_RESEARCH,
            AgentRole.RESEARCH_CLAIMS,
            AgentRole.RESEARCH_NARRATIVE,
        ):
            workspace = registry.resolve(role).profile.workspace
            assert "reads" in workspace.readable_prefixes
            assert "reads" not in workspace.writable_prefixes
    for version in range(2, 20):
        load_quality_resources("account", version=version)
