"""Production person request/profile contracts, with no paid calls or benchmark answers."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from clue_agents import AgentRole
from clue_api.arv2.account_research_catalog import bundle_pin
from clue_api.arv2.account_research_tools import (
    PersonResearchDeepArgs,
    _research_deep,
    build_person_tools,
)
from clue_api.arv2.exa_client import deep_reasoning_body
from clue_api.arv2.person_exa_brief import person_exa_arguments, uses_person_exa_brief
from clue_api.arv2.quality_catalog import ROOT, load_quality_resources
from clue_api.arv2.research_operations import fingerprint
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_storage.fs import FsStorage
from tests.arv2.test_account_exa_brief import scope
from tests.arv2.test_account_research_tools import _runtime


@pytest.mark.parametrize("revision", [10, 11])
def test_person_capability_matches_pinned_revision(revision):
    rt, *_ = _runtime(scope(revision, person=True))
    tool = next(t for t in build_person_tools(rt) if t.name == "research_deep")
    fields = tool.get_input_schema().model_json_schema()["properties"]
    assert ("highlights_query" in fields) == (revision == 11)
    assert ("additional_queries" in fields) == (revision == 11)
    assert ("probes" in fields) == (revision == 10)
    assert not uses_person_exa_brief(scope(revision))


def test_person_request_preserves_agent_assignment_and_full_wire_identity(monkeypatch):
    rt, *_ = _runtime(scope(11, person=True))
    seen = []

    async def operate(provider, kind, request, hop):
        seen.append((provider, kind, request))
        return SimpleNamespace(operation_id=uuid4(), artifact_key="original"), {
            "output": {"content": "# Person dossier"},
            "results": [],
        }

    monkeypatch.setattr(rt, "operate", operate)
    args = PersonResearchDeepArgs(
        charter="Investigate this selected person and their own public projects. " * 8,
        additional_queries=["Dana earlier employer interviews", "Dana public creative projects"],
        highlights_query="First-person motivation and recommendations",
        num_results=40,
    )
    result = asyncio.run(_research_deep(rt, args))
    wire = deep_reasoning_body(**person_exa_arguments(**args.model_dump()))
    assert seen == [("exa", "person_deep", wire)]
    assert wire["query"] == args.charter
    assert wire["additionalQueries"] == args.additional_queries
    assert wire["contents"] == {
        "text": {"maxCharacters": 10000},
        "highlights": {"maxCharacters": 2000, "query": args.highlights_query},
        "extras": {"links": 10, "imageLinks": 3},
    }
    assert wire["outputSchema"] == {"type": "text"}
    assert (
        wire["systemPrompt"]
        == (ROOT / "provider-requests/person-deep/v1/exa-system.md").read_text()
    )
    assert result["report"] == "# Person dossier" and result["result_ref"]
    changed = args.model_copy(update={"highlights_query": "Career transitions"})
    assert fingerprint(wire) != fingerprint(
        deep_reasoning_body(**person_exa_arguments(**changed.model_dump()))
    )
    plain = args.model_copy(update={"highlights_query": ""})
    assert "query" not in person_exa_arguments(**plain.model_dump())["contents"]["highlights"]


def test_promotion_changes_only_person_profile_and_preserves_exact_charter(tmp_path):
    bundle = load_quality_resources("arv2-person", version=13)
    assert json.loads(bundle.profile.body)["recipe_version"] == 13
    assert load_quality_resources("arv2-person", expected_pin=bundle_pin(bundle)) == bundle
    for revision in range(2, 12):
        old = load_quality_resources("arv2-person", version=revision)
        assert load_quality_resources("arv2-person", expected_pin=bundle_pin(old)) == old
    registry = quality_tools(scope(11, person=True), FsStorage(tmp_path), purge=False)
    person = quality_profiles(registry, version=11, person=True).resolve(AgentRole.ACCOUNT_RESEARCH)
    assert person.profile.version == "v11-person"
    assert not any(p.name.startswith("nominate_") for p in person.profile.tools)
    assert {p.ref.name for p in person.skills} == {
        "governed-evidence",
        "person-dossier",
        "person-depth-charter",
    }
    charter = next(s.body for s in person.skills if s.ref.name == "person-depth-charter")
    draft = Path("docs/superpowers/previews/2026-09-24-person-depth/charter.md").read_text()
    assert charter.endswith(draft)  # All agreed subquestions survive; not just headings.
    skill = next(s.body for s in person.skills if s.ref.name == "person-dossier")
    assert "/scratch/" not in skill and "in this trial" not in skill
    assert "source_review_path" in skill and "candidate_ref" in skill
    for role in (AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE):
        assert quality_profiles(registry, version=11, person=True).resolve(role).profile == (
            quality_profiles(registry, version=10, person=True).resolve(role).profile
        )
    assert quality_profiles(registry, version=11).resolve(AgentRole.ACCOUNT_RESEARCH).profile == (
        quality_profiles(registry, version=10).resolve(AgentRole.ACCOUNT_RESEARCH).profile
    )
