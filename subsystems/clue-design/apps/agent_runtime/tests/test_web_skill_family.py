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
    "plan-design",
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
    "web-decision-material",
    "web-contact-personalization",
    "web-product-story",
)


def read_required_skill_reference(tmp_path, skill, label, *, before="Read ", after="."):
    """Follow an explicit read instruction in the real materialized skill.

    This checks availability at the skill boundary, not whether a model follows
    the instruction. A reference merely present elsewhere in the tree cannot pass.
    """
    config = SimpleNamespace(workspace_root=tmp_path)
    materialize_agent_workspace(config)
    assert skill in dict(_materialized_skill_index(config))
    entry = tmp_path / ".deepagent" / "skills" / skill / "SKILL.md"
    text = entry.read_text()
    matches = re.findall(r"\[" + re.escape(label) + r"\]\(([^)]+)\)", text)
    assert len(matches) == 1, (skill, label)
    link = matches[0]
    assert f"{before}[{label}]({link}){after}" in text
    target = (entry.parent / link).resolve()
    assert target.is_relative_to(tmp_path / ".deepagent" / "skills")
    relative = target.relative_to(tmp_path / ".deepagent" / "skills")
    assert target.read_bytes() == (ROOT / "skills" / relative).read_bytes()
    assert target.read_bytes() == (tmp_path / "knowledge_docs" / "skills" / relative).read_bytes()
    return target.read_text()


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


def test_rich_product_controls_have_a_delivered_native_reconstruction_guide(tmp_path):
    read_required_skill_reference(
        tmp_path, "web-motion-fidelity", "rich card controls",
        before="read ", after=" before flattening it to a static section.",
    )


def test_account_argument_guide_is_required_and_delivered_with_the_skill(tmp_path):
    read_required_skill_reference(
        tmp_path,
        "web-account-personalization",
        "account argument",
        before="Read ",
        after=" before selecting sections or rewriting an account page.",
    )


def test_account_review_loads_the_same_argument_contract_as_the_author(tmp_path):
    """Review must receive the source/decision map, not just a personalization label.

    This proves progressive delivery through review's real entrypoint; model
    compliance and persuasive rendered copy need separate behavioral evidence.
    """
    reviewed = read_required_skill_reference(
        tmp_path,
        "review-website",
        "account argument",
        before="read ",
        after=" and compare its decision map with the visitor-visible page.",
    )
    authored = read_required_skill_reference(
        tmp_path,
        "web-account-personalization",
        "account argument",
        before="Read ",
        after=" before selecting sections or rewriting an account page.",
    )
    assert reviewed == authored


def test_requested_page_directions_and_copy_brief_are_delivered(tmp_path):
    """The working guides must be reachable from the actual progressive entrypoints."""
    read_required_skill_reference(
        tmp_path, "campaign-landing-page", "distinct page directions",
        before="read ", after=" before composing the first page.",
    )
    read_required_skill_reference(
        tmp_path, "conversion-copywriting", "website copy brief",
        before="read ", after=" before filling section slots.",
    )


@pytest.mark.parametrize("skill,label", [
    ("web-decision-material", "worked decision exhibit"),
    ("web-contact-personalization", "worked contact brief"),
    ("campaign-landing-page", "action selection"),
])
def test_decision_guides_reach_the_materialized_agent(tmp_path, skill, label):
    read_required_skill_reference(tmp_path, skill, label)


def test_materialized_planning_does_not_override_native_research_or_campaign_scope(tmp_path):
    """Catch the legacy instructions that contradicted the account workflow at runtime."""
    materialize_agent_workspace(SimpleNamespace(workspace_root=tmp_path))
    plan = (tmp_path / ".deepagent/skills/plan-design/SKILL.md").read_text()
    recipe = (tmp_path / "knowledge_docs/knowledge/web/landing-page.md").read_text()
    assert "scoped account/contact" in plan
    assert "deliberately absent for now" not in plan
    assert "will eventually arrive" not in plan
    assert "Every claim on the page traces to the brief or the library" not in plan
    assert "Required section order" not in recipe
    assert "one generated product image" not in recipe


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
    for skill in ("web-decision-material", "web-contact-personalization", "web-product-story"):
        assert skill in prompt
    assert "Re-reading a skill\n   mid-build is a defect" not in prompt
    assert "CHROME IS THE CAMPAIGN SHELLS, never" not in prompt
