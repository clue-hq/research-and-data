"""Task 6 — the active page and the four page tools on `LumenWebTools`.

The substrate learned that a document has N pages: the engine gained
`add_page`/`remove_page` ops, and these tools are how the website deepagent
reaches them. Every refusal here must leave the document exactly as it was.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools, has_existing_content

REPO_ROOT = Path(__file__).resolve().parents[3]


def _tools(tmp_path: Path) -> LumenWebTools:
    from lumen_api.core import CoreClient

    config = replace(AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root")
    seed = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_site", "Site", None)["web_doc"]
    return LumenWebTools(config, "Build a microsite", initial_web_doc=seed)


def test_add_page_switches_the_active_page_and_lands_in_the_ledger(tmp_path):
    tools = _tools(tmp_path)
    out = json.loads(tools.add_page("pricing", "Pricing", "/pricing"))
    assert out["status"] == "ok" and out["active_page"] == "pricing"
    assert tools.page_id == "pricing"
    assert [p["route"] for p in tools.web_doc["pages"]] == ["/", "/pricing"]
    assert tools.operations_ledger[-1]["kind"] == "add_page"
    listing = json.loads(tools.list_pages())
    assert listing["active_page"] == "pricing" and len(listing["pages"]) == 2


def test_add_page_refuses_a_bad_route_in_plain_words(tmp_path):
    tools = _tools(tmp_path)
    out = json.loads(tools.add_page("x", "X", "/Bad Route"))
    assert out["status"] != "ok"
    assert "lowercase" in json.dumps(out)
    assert len(tools.web_doc["pages"]) == 1 and tools.operations_ledger == []


def test_switch_page_resets_the_round_budget_and_previews(tmp_path):
    tools = _tools(tmp_path)
    tools.add_page("pricing", "Pricing", "/pricing")
    tools._mutations_since_render = 9
    tools._preview_by_width = {1440: tmp_path / "fake.png"}
    out = json.loads(tools.switch_page("home"))
    assert out["status"] == "ok" and tools.page_id == "home"
    assert tools._mutations_since_render == 0 and tools._preview_by_width == {}
    bad = json.loads(tools.switch_page("nope"))
    assert bad["status"] != "ok" and "pricing" in json.dumps(bad)


def test_remove_page_moves_the_active_page_and_keeps_the_last_one(tmp_path):
    tools = _tools(tmp_path)
    tools.add_page("pricing", "Pricing", "/pricing")
    assert json.loads(tools.remove_page("pricing"))["status"] == "ok"
    assert tools.page_id == "home"
    last = json.loads(tools.remove_page("home"))
    assert last["status"] != "ok" and len(tools.web_doc["pages"]) == 1


def test_has_existing_content_without_a_page_means_any_page(tmp_path):
    tools = _tools(tmp_path)
    tools.add_page("pricing", "Pricing", "/pricing")
    assert has_existing_content(tools.web_doc) is False
    page = tools.web_doc["pages"][1]
    page["nodes"]["sec"] = {"id": "sec", "kind": "section", "classes": "", "children": []}
    page["nodes"][page["root"]]["children"] = ["sec"]
    assert has_existing_content(tools.web_doc) is True
    assert has_existing_content(tools.web_doc, "home") is False


def test_every_skill_frontmatter_parses_as_yaml():
    """The skills loader is `yaml.safe_load` and it SKIPS a skill whose
    frontmatter does not parse (deepagents `middleware/skills.py`), so an
    unquoted colon in a `description:` makes a whole skill invisible to the
    agent with nothing but a log line to say so."""
    import yaml

    skills_dir = REPO_ROOT / "apps/agent_runtime/knowledge_docs/skills"
    for skill in sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()):
        front = (skill / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        meta = yaml.safe_load(front)
        assert isinstance(meta, dict), skill.name
        assert meta["name"] == skill.name


def test_orchestrator_prompt_teaches_one_brief_per_page():
    from lumen_agent.prompts_web import build_web_orchestrator_prompt

    text = build_web_orchestrator_prompt(
        doc_title="Site",
        has_existing_content=False,
        brand_card="",
        review_cap=6,
        author_cap=4,
        account_card=None,
        page_routes=["/", "/pricing"],
    )
    assert "ONE AUTHOR BRIEF PER PAGE" in text
    assert "add_page" in text and "switch_page" in text
    assert "/pricing" in text
