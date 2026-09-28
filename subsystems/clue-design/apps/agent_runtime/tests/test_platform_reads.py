"""The platform's reads as the design agent sees them (design note 2026-09-19).

Three tools over an injected, duck-typed ``reads`` object, and the seller's pinned knowledge
written into ``workspace/seller/`` once per pin. Nothing here imports the platform: the fake
below is the whole contract the design runtime knows about.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.platform_reads import make_platform_read_tools, write_seller_knowledge
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.workspace import scaffold_workspace, workspace_root


class _ReadError(RuntimeError):
    """Stands in for the platform's ``DesignPlatformReadError``: ``str()`` IS the code."""


class _Reads:
    def __init__(self, research_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.sha: str | None = "abc123"
        self.documents = (
            SimpleNamespace(
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body_text="# Acme\nWe do X.",
            ),
            SimpleNamespace(
                path="product/catalog.md",
                kind="product-catalog",
                version=1,
                status="ready",
                body_text="# Products\n- p1",
            ),
        )
        self.seller_error: Exception | None = None
        self._research_error = research_error or _ReadError("read_failed")

    def read_project_accounts(self, **kw):
        self.calls.append(("accounts", kw))
        return {"total": 1, "accounts": [{"canonical_name": "Premier"}]}

    def read_account_research(self, **kw):
        self.calls.append(("research", kw))
        raise self._research_error

    def read_claims(self, **kw):
        self.calls.append(("claims", kw))
        return {"claims": [], "prefixes": []}

    def web_search(self, **kw):
        self.calls.append(("search", kw))
        return {
            "answer": "Acme's summit is in May.",
            "results": [],
            "rendered": "Acme's summit is in May.\n",
        }

    def seller_knowledge(self):
        if self.seller_error is not None:
            raise self.seller_error
        return SimpleNamespace(
            documents_sha256=self.sha,
            documents=self.documents,
            confirmed_icp_path="audience/icp-x.md",
            product_set={"selection_version": 1, "product_ids": ["p1"]},
        )


def _tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> LumenDesignTools:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    from dataclasses import replace

    config = runtime_config(tmp_path)
    if overrides:
        config = replace(config, **overrides)
    return LumenDesignTools(config, "Make a square ad for Premier")


def _events(tools: LumenDesignTools) -> list[dict]:
    path = tools.turn_dir / "trace.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_tools_return_json_and_errors_as_strings_and_record(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    accounts, research, claims, search = make_platform_read_tools(tools, reads)

    assert [accounts.name, research.name, claims.name] == [
        "read_project_accounts",
        "read_account_research",
        "read_claims",
    ]
    assert json.loads(accounts.invoke({"query": "prem"}))["total"] == 1
    assert json.loads(research.invoke({"account_entity_id": "x"})) == {"error": "read_failed"}
    assert json.loads(claims.invoke({"entity_id": "acct_1"})) == {"claims": [], "prefixes": []}
    assert reads.calls[0] == ("accounts", {"query": "prem", "offset": 0})
    assert reads.calls[1] == (
        "research",
        {"account_entity_id": "x", "section": "overview", "field_prefix": None, "offset": 0},
    )

    assert search.name == "web_search"
    assert json.loads(search.invoke({"query": "acme summit 2026"}))["rendered"].startswith("Acme")
    assert reads.calls[-1] == (
        "search",
        {
            "query": "acme summit 2026",
            "num_results": 10,
            "include_domains": None,
            "exclude_domains": None,
            "start_published_date": None,
            "end_published_date": None,
        },
    )

    events = [event for event in _events(tools) if event["event"] == "platform_read"]
    assert [event["payload"]["ok"] for event in events] == [True, False, True, True]
    assert events[1]["payload"]["code"] == "read_failed"
    assert events[1]["payload"]["tool"] == "read_account_research"


def test_a_governed_refusal_reaches_the_agent_as_its_reason_codes(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads(research_error=_ReadError("refused:overview_not_written,account_not_researched"))
    _, research, _, _ = make_platform_read_tools(tools, reads)

    assert json.loads(research.invoke({"account_entity_id": "x"})) == {
        "error": "refused",
        "reasons": ["overview_not_written", "account_not_researched"],
    }
    event = [event for event in _events(tools) if event["event"] == "platform_read"][-1]
    assert event["payload"]["ok"] is False
    assert event["payload"]["code"] == "refused:overview_not_written,account_not_researched"


def test_a_refused_search_reaches_the_agent_as_its_reason_code(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    reads.web_search = lambda **kw: (_ for _ in ()).throw(_ReadError("refused:exa_not_configured"))
    *_, search = make_platform_read_tools(tools, reads)
    assert json.loads(search.invoke({"query": "acme"})) == {
        "error": "refused",
        "reasons": ["exa_not_configured"],
    }


def test_seller_files_are_written_once_per_pin(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    workspace = workspace_root(tools)
    workspace.mkdir(parents=True, exist_ok=True)

    assert write_seller_knowledge(workspace, reads, record=tools.record) is True
    assert (workspace / "seller" / "company" / "overview.md").read_text().startswith("# Acme")
    index = (workspace / "seller" / "index.md").read_text()
    assert "product/catalog.md" in index
    assert "audience/icp-x.md" in index
    assert "selection version 1" in index
    assert (workspace / "seller" / ".pin").read_text() == "abc123"

    assert write_seller_knowledge(workspace, reads, record=tools.record) is False
    reads.sha = "def456"
    assert write_seller_knowledge(workspace, reads, record=tools.record) is True
    assert (workspace / "seller" / ".pin").read_text() == "def456"

    written = [event for event in _events(tools) if event["event"] == "seller_knowledge_written"]
    assert [event["payload"]["documents"] for event in written] == [2, 2]


def test_a_retired_document_leaves_no_stale_file_behind(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    workspace = workspace_root(tools)
    workspace.mkdir(parents=True, exist_ok=True)
    assert write_seller_knowledge(workspace, reads, record=tools.record) is True

    reads.documents = reads.documents[:1]
    reads.sha = "def456"
    assert write_seller_knowledge(workspace, reads, record=tools.record) is True
    assert not (workspace / "seller" / "product" / "catalog.md").exists()
    assert (workspace / "seller" / "company" / "overview.md").is_file()


@pytest.mark.parametrize(
    "path", ["../escape.md", "/etc/passwd", "company/../../escape.md", "", "."]
)
def test_a_document_path_that_climbs_or_is_absolute_is_never_written(
    tmp_path, monkeypatch, path
) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    reads.documents = (
        SimpleNamespace(
            path=path, kind="company-overview", version=1, status="ready", body_text="ESCAPED"
        ),
    )
    workspace = workspace_root(tools)
    workspace.mkdir(parents=True, exist_ok=True)

    assert write_seller_knowledge(workspace, reads, record=tools.record) is True
    assert not any(
        candidate.is_file() and candidate.read_text(errors="ignore") == "ESCAPED"
        for candidate in tmp_path.rglob("*")
    )


def test_empty_seller_knowledge_writes_nothing(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    reads.documents = ()
    workspace = workspace_root(tools)
    workspace.mkdir(parents=True, exist_ok=True)

    assert write_seller_knowledge(workspace, reads, record=tools.record) is False
    assert not (workspace / "seller").exists()

    reads.documents = _Reads().documents
    reads.sha = None
    assert write_seller_knowledge(workspace, reads, record=tools.record) is False
    assert not (workspace / "seller").exists()


def test_an_unavailable_seller_read_is_recorded_and_never_raised(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    reads.seller_error = _ReadError("loop_unavailable")
    workspace = workspace_root(tools)
    workspace.mkdir(parents=True, exist_ok=True)

    assert write_seller_knowledge(workspace, reads, record=tools.record) is False
    unavailable = [
        event for event in _events(tools) if event["event"] == "seller_knowledge_unavailable"
    ]
    assert unavailable[-1]["payload"]["code"] == "loop_unavailable"


def test_scaffold_writes_the_seller_tree_only_when_the_platform_injected_reads(
    tmp_path, monkeypatch
) -> None:
    reads = _Reads()
    with_reads = _tools(tmp_path / "with", monkeypatch, platform_reads=reads)
    scaffold_workspace(with_reads, "Make a square ad for Premier")
    assert (workspace_root(with_reads) / "seller" / "index.md").is_file()

    without = _tools(tmp_path / "without", monkeypatch)
    scaffold_workspace(without, "Make a square ad")
    assert not (workspace_root(without) / "seller").exists()


def test_the_scene_tools_skill_and_the_web_prompt_teach_web_search_as_the_last_resort() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / "knowledge_docs/views/scene/skills/tools/SKILL.md").read_text(encoding="utf-8")
    prompts = (root / "lumen_agent/prompts.py").read_text(encoding="utf-8")
    assert "## Web search" in skill
    assert "`web_search`" in skill and "comes after the account reads" in skill
    assert prompts.count("web_search is the last resort") == 2
