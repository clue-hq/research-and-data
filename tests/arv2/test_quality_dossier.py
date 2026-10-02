"""Reporting contract stays separate from person research and from acquired evidence."""

import json

from clue_agents import AgentRole
from clue_api.arv2.quality_catalog import load_quality_resources
from clue_api.arv2.quality_dossier import source_inventory, uses_account_dossier
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_storage.fs import FsStorage
from tests.arv2.test_account_exa_brief import scope


def test_dossier_resources_are_pinned_account_only_with_same_tools(tmp_path):
    tools = quality_tools(scope(13), FsStorage(tmp_path), purge=False)
    new = quality_profiles(tools, version=13)
    old = quality_profiles(tools, version=12)
    account = new.resolve(AgentRole.ACCOUNT_RESEARCH)
    assert account.profile.version == "v13"
    assert account.profile.tools == old.resolve(AgentRole.ACCOUNT_RESEARCH).profile.tools
    assert "before writing claims" in account.prompt_body
    assert (
        "automatically" in next(s for s in account.skills if s.ref.name == "account-dossier").body
    )
    for role in (AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE):
        assert new.resolve(role) == old.resolve(role)
    assert quality_profiles(tools, version=13, person=True).resolve(AgentRole.ACCOUNT_RESEARCH) == (
        quality_profiles(tools, version=12, person=True).resolve(AgentRole.ACCOUNT_RESEARCH)
    )
    assert (
        json.loads(load_quality_resources("arv2-account", version=13).profile.body)[
            "recipe_version"
        ]
        == 13
    )
    assert uses_account_dossier(scope(13))
    assert not uses_account_dossier(scope(12))
    assert not uses_account_dossier(scope(13, person=True))


def test_inventory_does_not_equate_retrieval_with_reading_or_invent_source_links():
    report = (
        "[Known](https://example.test/source). More: "
        "https://example.test/unfetched. /evidence/0002-web-snapshot.json"
    )
    inventory = source_inventory(
        report,
        [
            {
                "source_id": "s1",
                "revision": 1,
                "kind": "web_snapshot",
                "source_url": "https://example.test/source",
                "available": True,
            },
            {
                "source_id": "s2",
                "revision": 2,
                "kind": "web_snapshot",
                "source_url": None,
                "available": True,
            },
            {
                "source_id": "s3",
                "revision": 3,
                "kind": "web_snapshot",
                "source_url": "https://example.test/extra",
                "available": True,
            },
        ],
    )
    assert [s["citation_match"] for s in inventory["sources"]] == ["url", "path", None]
    assert inventory["unmatched_cited_urls"] == ["https://example.test/unfetched"]
    assert "not proof of reading" in inventory["interpretation"]
