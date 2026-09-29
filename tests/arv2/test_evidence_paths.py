"""Readable evidence names and current resource pins."""

import json

from clue_agents import AgentRole
from clue_api.arv2.evidence_paths import SOURCE_PATH, source_path
from clue_api.arv2.quality_catalog import load_quality_resources
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_storage.fs import FsStorage
from tests.arv2.test_account_exa_brief import scope


def test_names_are_safe_distinct_and_stable_without_a_new_alias_store():
    row = {
        "revision": 17,
        "kind": "web_snapshot",
        "metadata": {"title": "../../Hiring — Café / leadership"},
    }
    path = source_path(row)
    assert path == "/evidence/0017-hiring-cafe-leadership.json"
    assert SOURCE_PATH.fullmatch(path)
    assert source_path({**row, "revision": 18}) != path
    assert (
        source_path({**row, "metadata": {}, "source_url": "https://example.test/jobs?token=secret"})
        == "/evidence/0017-example-test-jobs.json"
    )
    assert (
        source_path({**row, "metadata": {}, "source_url": None})
        == "/evidence/0017-web-snapshot.json"
    )


def test_revision14_pins_path_tools_and_readable_navigation(tmp_path):
    tools = quality_tools(scope(14), FsStorage(tmp_path), purge=False)
    for person in (False, True):
        profiles = quality_profiles(tools, version=14, person=person)
        for role in (
            AgentRole.ACCOUNT_RESEARCH,
            AgentRole.RESEARCH_CLAIMS,
            AgentRole.RESEARCH_NARRATIVE,
        ):
            profile = profiles.resolve(role)
            assert profile.profile.version in ("v14", "v14-person")
            assert "/evidence/index.json" in profile.prompt_body
            assert any(
                s.ref.name == "governed-evidence" and s.ref.version == "v3" for s in profile.skills
            )
            for tool in profile.profile.tools:
                if tool.name in (
                    "record_research_finding",
                    "search_evidence",
                    "record_research_disposition",
                ):
                    assert tool.version == "2"
    assert (
        json.loads(load_quality_resources("arv2-account", version=15).profile.body)[
            "recipe_version"
        ]
        == 15
    )
