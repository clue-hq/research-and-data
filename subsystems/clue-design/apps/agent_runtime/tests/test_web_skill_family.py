"""Packaging and dispatch contracts, not model behavior or visual-quality assertions."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from lumen_agent import prompts_web
from lumen_agent.harness import _materialized_skill_index
from lumen_agent.materialize import materialize_agent_workspace

ROOT = Path(__file__).resolve().parents[1] / "knowledge_docs"
SKILLS = (
    "web-source-readiness",
    "create-website",
    "repair-cloned-sections",
    "web-media-composition",
    "web-motion-fidelity",
    "web-account-personalization",
    "campaign-landing-page",
    "conversion-copywriting",
    "edit-website",
    "review-website",
    "campaign-page-workflow",
)


def test_every_family_is_discoverable_and_nested_references_survive_materialization(tmp_path):
    config = SimpleNamespace(workspace_root=tmp_path)
    materialize_agent_workspace(config)
    indexed = dict(_materialized_skill_index(config))
    for name in SKILLS:
        assert indexed[name]
        source = ROOT / "skills" / name
        for original in source.rglob("*.md"):
            relative = original.relative_to(ROOT / "skills")
            delivered = tmp_path / ".deepagent" / "skills" / relative
            assert delivered.read_bytes() == original.read_bytes()
            for link in re.findall(r"\]\(([^)]+)\)", delivered.read_text()):
                if "://" not in link and not link.startswith("#"):
                    target = (delivered.parent / link.split("#", 1)[0]).resolve()
                    assert target.is_file(), (name, link)
                    assert target.is_relative_to(tmp_path), (name, link)
    assert (tmp_path / "knowledge_docs/knowledge/web/skill-families.md").is_file()


@pytest.mark.parametrize("role", ["orchestrator", "author", "reviewer", "solo"])
def test_runtime_prompts_receive_the_same_conditional_family_router(role):
    if role == "orchestrator":
        prompt = prompts_web.build_web_orchestrator_prompt(
            doc_title="Fixture",
            has_existing_content=True,
            brand_card="{}",
            author_cap=2,
            review_cap=2,
            account_card="{}",
        )
    elif role == "author":
        prompt = prompts_web.build_web_author_prompt(
            brand_card="{}", theme_token_names="brand", account_card="{}"
        )
    elif role == "reviewer":
        prompt = prompts_web.build_web_reviewer_prompt(has_account=True)
    else:
        prompt = prompts_web.build_web_solo_prompt(
            doc_title="Fixture",
            has_existing_content=True,
            brand_card="{}",
            theme_token_names="brand",
            account_card="{}",
        )
    assert prompts_web.WEB_SKILL_ROUTING in prompt
    assert "For a scoped change: edit-website first" in prompt
    assert "Re-reading a skill\n   mid-build is a defect" not in prompt
    assert "CHROME IS THE CAMPAIGN SHELLS, never" not in prompt
