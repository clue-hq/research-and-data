"""Ownership and scoped reference translation, without paid model calls."""

import json
from uuid import uuid4

import pytest

from clue_agents import AgentCatalogError, AgentRole
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION, load_quality_resources
from clue_api.arv2.quality_owned_narrative import NarrativeSentence, finding_map, resolve_sentence
from clue_api.quality_research_wiring import quality_profiles, quality_tools


def test_same_finding_name_resolves_separately_and_preserves_exact_text():
    person, account = uuid4(), uuid4()
    sentence = NarrativeSentence(
        text="A source says “keep my words.”",
        finding_ids=["F001"],
        account_finding_ids=["F001"],
        kind="qualified",
        qualifications=["Account context is separate"],
    )
    got = resolve_sentence(sentence, {"F001": person}, {"F001": account}, {person, account})
    assert got.text == sentence.text and got.claim_ids == (person, account)
    assert got.qualifications == sentence.qualifications and got.kind == sentence.kind
    with pytest.raises(ValueError, match="Unknown account_finding_ids"):
        resolve_sentence(sentence, {"F001": person}, {}, {person, account})
    with pytest.raises(ValueError, match="out-of-scope"):
        resolve_sentence(sentence, {"F001": person}, {"F001": account}, {person})
    with pytest.raises(ValueError, match="Complete finish_dossier"):
        finding_map({"receipt": {"complete": False}})
    assert finding_map(
        {"receipt": {"complete": True, "entries": [{"id": "F001", "claim_id": str(person)}]}}
    ) == {"F001": person}


@pytest.mark.parametrize("person", [False, True])
def test_new_researchers_leave_pages_to_the_writer_while_historical_pins_keep_theirs(person):
    tools = quality_tools(None, None, purge=False)
    current = quality_profiles(tools, version=CURRENT_RECIPE_VERSION, person=person)
    historical = quality_profiles(tools, version=19, person=person)
    new = current.resolve(AgentRole.ACCOUNT_RESEARCH)
    old = historical.resolve(AgentRole.ACCOUNT_RESEARCH)
    for specialist in (AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE):
        with pytest.raises(AgentCatalogError, match="has no active profile"):
            current.resolve(specialist)
        historical.resolve(specialist)
    assert not new.profile.delegation_roles
    assert AgentRole.RESEARCH_NARRATIVE in old.profile.delegation_roles
    names = {t.name for t in new.profile.tools}
    page_tools = {
        "read_narrative_inputs",
        "write_research_narrative",
        "read_research_page_inputs",
        "publish_research_page",
    }
    # From recipe 25 the researcher writes no pages; the driver's page writer does.
    assert "finish_dossier" in names and not page_tools & names
    assert "record_research_finding" not in names
    owning = quality_profiles(tools, version=24, person=person).resolve(AgentRole.ACCOUNT_RESEARCH)
    assert {"read_narrative_inputs", "write_research_narrative"} <= {
        t.name for t in owning.profile.tools
    }
    assert CURRENT_RECIPE_VERSION == 27
    manifest = json.loads(load_quality_resources("person" if person else "account").profile.body)
    assert manifest["recipe_version"] == CURRENT_RECIPE_VERSION
    for version in range(2, CURRENT_RECIPE_VERSION + 1):
        load_quality_resources("account", version=version)
