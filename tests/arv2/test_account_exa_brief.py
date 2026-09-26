"""Offline request/retention contracts; these do not certify live research quality."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from clue_agents import AgentRole
from clue_api.arv2.account_exa_brief import account_exa_arguments, uses_account_exa_brief
from clue_api.arv2.account_research_catalog import bundle_pin
from clue_api.arv2.account_research_tools import (
    AccountResearchDeepArgs,
    _research_deep,
    build_account_tools,
    build_person_tools,
)
from clue_api.arv2.exa_client import deep_reasoning_body, read_deep_report
from clue_api.arv2.quality_acquisition import exa_source_texts
from clue_api.arv2.quality_catalog import load_quality_resources
from clue_api.arv2.research_operations import fingerprint
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_config import Settings
from clue_storage.fs import FsStorage
from tests.arv2.test_account_research_tools import CHARTER, PERSON_SCOPE, SCOPE, _runtime


def scope(version=7, *, person=False):
    return replace(
        PERSON_SCOPE if person else SCOPE,
        catalog_version="v4",
        input_refs={"quality_recipe_version": version},
    )


def test_new_account_request_is_exact_and_participates_in_operation_identity(monkeypatch):
    runtime, clients, _, _ = _runtime(scope())
    recorded = []

    async def operate(provider, kind, request, hop):
        recorded.append(request)
        result = hop(None)
        return SimpleNamespace(operation_id=uuid4(), artifact_key="retained-raw"), {
            "output": {"content": result.report_text},
            "results": [],
        }

    monkeypatch.setattr(runtime, "operate", operate)
    args = AccountResearchDeepArgs(
        charter=CHARTER, additional_queries=["Probook operations", "Probook leaders"]
    )
    result = asyncio.run(_research_deep(runtime, args))
    kwargs = clients.exa_client.deep_calls[0].copy()
    kwargs.pop("label")
    assert recorded == [deep_reasoning_body(**kwargs)]
    assert recorded[0]["query"] == CHARTER  # No context compiler or repeated appendix.
    assert recorded[0]["additionalQueries"] == args.additional_queries
    assert recorded[0]["numResults"] == 40
    assert recorded[0]["contents"] == {"highlights": True, "extras": {"links": 1}}
    assert recorded[0]["outputSchema"] == {"type": "text"}
    assert "ALREADY ESTABLISHED" not in recorded[0]["query"]
    assert "One assertion per sentence" not in recorded[0]["systemPrompt"]
    assert result["report"] == clients.exa_client.deep_report
    assert result["source_artifact_key"] == "retained-raw"
    for changed in [
        {"additionalQueries": ["Probook financing"]},
        {"contents": {"text": True}},
        {"systemPrompt": "another revision"},
    ]:
        assert fingerprint(recorded[0]) != fingerprint({**recorded[0], **changed})


@pytest.mark.parametrize(
    "version,person,enabled", [(7, False, True), (6, False, False), (7, True, False)]
)
def test_only_new_account_jobs_expose_new_arguments(version, person, enabled):
    subject = scope(version, person=person)
    runtime, _, _, _ = _runtime(subject)
    tools = build_person_tools(runtime) if person else build_account_tools(runtime)
    schema = (
        next(t for t in tools if t.name == "research_deep").get_input_schema().model_json_schema()
    )
    assert uses_account_exa_brief(subject) == enabled
    assert ("additional_queries" in schema["properties"]) == enabled
    assert ("probes" in schema["properties"]) != enabled
    assert schema["properties"]["num_results"]["default"] == (40 if enabled else 20)
    assert schema["properties"]["num_results"]["maximum"] == (40 if enabled else 25)


def test_agent_charter_is_preserved_and_empty_queries_are_omitted():
    args = account_exa_arguments(
        charter=CHARTER + "Who owns operations?", additional_queries=[], num_results=40
    )
    assert args["query"].count("Who owns operations?") == 1
    assert "additionalQueries" not in deep_reasoning_body(**args)


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"output": {"content": "# Report\nSource-linked prose"}}, "# Report\nSource-linked prose"),
        ({"output": "# Bare report"}, "# Bare report"),
        ({"output": {"content": {"report": {"value": "Structured report"}}}}, "Structured report"),
        ({"output": {"content": '{"report": "Encoded report"}'}}, "Encoded report"),
        ({"output": {"grounding": {}}}, None),
        ({"output": {"content": {"products": []}}}, None),
        ({}, None),
    ],
)
def test_saved_text_and_structured_report_shapes(body, expected):
    assert read_deep_report(body, text_output=True) == expected
    if expected and expected.startswith("#"):
        assert read_deep_report(body) is None  # Legacy structured-only callers remain unchanged.


def test_source_excerpts_keep_original_positions_without_becoming_full_pages():
    result = {"highlights": ["First excerpt", None, "", "Later excerpt"]}
    assert exa_source_texts(result) == [
        ("highlights/0", "First excerpt"),
        ("highlights/3", "Later excerpt"),
    ]
    assert exa_source_texts({**result, "text": "Full page"})[0] == ("text", "Full page")
    assert exa_source_texts({"highlights": "malformed"}) == []


def test_new_pins_preserve_historical_profiles_and_scope_person_tools(tmp_path):
    assert Settings(arv2_research_catalog_version="v4").arv2_research_catalog_version == "v4"
    bundle = load_quality_resources("arv2-account", version=15)
    assert json.loads(bundle.profile.body)["recipe_version"] == 15
    for version in (6, 7, 8, 9, 10):
        old = load_quality_resources("arv2-account", version=version)
        assert load_quality_resources("arv2-account", expected_pin=bundle_pin(old)) == old
    registry = quality_tools(scope(), FsStorage(tmp_path), purge=False)
    account_profiles = quality_profiles(registry, version=7)
    person_profiles = quality_profiles(registry, version=7, person=True)
    assert account_profiles.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == "v7"
    assert person_profiles.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == "v6"
    for role in (AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE):
        assert account_profiles.resolve(role).profile.version == "v6"
    account = quality_profiles(registry, version=10).resolve(AgentRole.ACCOUNT_RESEARCH)
    person = quality_profiles(registry, version=10, person=True).resolve(AgentRole.ACCOUNT_RESEARCH)
    assert account.profile.version == "v10"
    assert "read the person-research-briefing skill" in account.prompt_body
    assert "delegation in research_brief" in account.prompt_body
    assert person.profile.version == "v9-person"
    assert person.prompt_body == person_profiles.resolve(AgentRole.ACCOUNT_RESEARCH).prompt_body
    assert not any(pin.name.startswith("nominate_") for pin in person.profile.tools)
    assert any(pin.resource.name == "person-research-briefing" for pin in account.profile.skills)


def test_client_default_contents_are_unchanged_and_explicit_contents_are_copied():
    args = {"system_prompt": "system", "query": "query", "output_schema": {"type": "text"}}
    assert deep_reasoning_body(**args)["contents"] == {"text": {"maxCharacters": 10000}}
    contents = {"highlights": True, "extras": {"links": 1}}
    body = deep_reasoning_body(**args, contents=contents)
    contents["extras"]["links"] = 2
    assert body["contents"]["extras"]["links"] == 1
