"""Account source handoff: complete pagination and source provenance, no report-only view."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from clue_agents import AgentRole
from clue_api.arv2 import quality_source_navigation as nav
from clue_api.quality_research_wiring import quality_profiles, quality_tools
from clue_storage.fs import FsStorage
from tests.arv2.test_account_exa_brief import scope


def test_navigation_preserves_url_and_excerpt_locator_without_exposing_erased_metadata():
    source = str(uuid4())
    result = nav.source_navigation(
        [
            {
                "source_id": source,
                "revision": 1,
                "available": True,
                "kind": "web_snapshot",
                "source_url": "https://example.test/bdr",
                "origin_locator": "results/17/highlights/0",
                "metadata": {"title": "BDR", "content_kind": "highlight"},
            },
            {"source_id": str(uuid4()), "available": False},
        ]
    )
    assert result["unavailable_source_count"] == 1
    assert result["sources"] == [
        {
            "source_id": source,
            "path": "/evidence/0001-bdr.json",
            "kind": "web_snapshot",
            "url": "https://example.test/bdr",
            "origin_locator": "results/17/highlights/0",
            "title": "BDR",
            "content_kind": "highlight",
            "published_at": None,
        }
    ]


def test_operation_navigation_consumes_every_page_using_same_grant_and_operation(monkeypatch):
    operation = uuid4()
    grant = SimpleNamespace()
    calls = []

    async def listing(conn, actual_grant, *, after, limit, operation_id):
        assert actual_grant is grant and operation_id == operation
        calls.append(after)
        return {
            "sources": [
                {
                    "source_id": str(uuid4()),
                    "available": True,
                    "kind": "research_report",
                    "revision": after + 1,
                    "origin_locator": "output.content",
                }
            ],
            "next_after": 101 if after == 0 else None,
        }

    monkeypatch.setattr(nav, "list_sources", listing)
    result = asyncio.run(nav.operation_source_navigation(None, grant, operation))
    assert calls == [0, 101]
    assert len(result["sources"]) == 2


def test_revision_eight_changes_only_account_instructions(tmp_path):
    registry = quality_tools(scope(8), FsStorage(tmp_path), purge=False)
    profiles = quality_profiles(registry, version=8)
    account = profiles.resolve(AgentRole.ACCOUNT_RESEARCH)
    assert account.profile.version == "v8"
    assert "source_navigation" in account.prompt_body
    assert any(s.ref.name == "account-dossier" and s.ref.version == "v2" for s in account.skills)
    assert (
        quality_profiles(registry, version=7).resolve(AgentRole.ACCOUNT_RESEARCH).profile.version
        == "v7"
    )
    for role in (AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE):
        assert profiles.resolve(role).profile.version == "v6"
    assert (
        quality_profiles(registry, version=8, person=True)
        .resolve(AgentRole.ACCOUNT_RESEARCH)
        .profile.version
        == "v6"
    )
