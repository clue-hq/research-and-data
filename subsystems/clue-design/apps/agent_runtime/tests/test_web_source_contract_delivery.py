"""The fidelity contract must reach fresh-project roles without a model file read.

These are delivery regressions, not assertions about generated visual quality.
"""

from pathlib import Path

import pytest
from lumen_agent import prompts_web


def prompt(role):
    if role == "author":
        return prompts_web.build_web_author_prompt(brand_card="{}", theme_token_names="brand")
    if role == "reviewer":
        return prompts_web.build_web_reviewer_prompt(has_account=False)
    kwargs = {"doc_title": "New project", "has_existing_content": False, "brand_card": "{}"}
    if role == "solo":
        return prompts_web.build_web_solo_prompt(**kwargs, theme_token_names="brand")
    return prompts_web.build_web_orchestrator_prompt(**kwargs, author_cap=2, review_cap=2)


@pytest.mark.parametrize("role", ["solo", "author", "director", "reviewer"])
def test_fresh_project_receives_complete_shared_source_contract(role):
    source = (
        Path(__file__).resolve().parents[1]
        / "knowledge_docs/skills/create-website/references/source-format-contract.md"
    )
    assert source.is_file(), "Selected source preservation still depends on optional skill reads"
    body = source.read_text().strip()
    actual = prompt(role)
    assert actual.count(body) == 1
    # Source ownership is visible in the actual model payload; no project body is supplied.
    assert "create-website/references/source-format-contract.md" in actual


@pytest.mark.parametrize("role", ["solo", "author", "director", "reviewer"])
def test_revised_skill_reaches_every_role_without_module_reload(role, monkeypatch, tmp_path):
    source = tmp_path / "contract.md"
    source.write_text("# Contract revision one\nSelected source remains authoritative.")
    monkeypatch.setattr(prompts_web, "WEB_SOURCE_CONTRACT_PATH", source)
    assert source.read_text() in prompt(role)
    source.write_text("# Contract revision two\nReview current source roles.")
    actual = prompt(role)
    assert source.read_text() in actual
    assert "Contract revision one" not in actual


@pytest.mark.parametrize("role", ["solo", "author", "director", "reviewer"])
def test_missing_shared_skill_cannot_silently_build_a_partial_prompt(role, monkeypatch, tmp_path):
    monkeypatch.setattr(prompts_web, "WEB_SOURCE_CONTRACT_PATH", tmp_path / "missing.md")
    with pytest.raises(RuntimeError, match="website source contract"):
        prompt(role)


@pytest.mark.parametrize("role", ["solo", "author", "director"])
def test_role_prompt_does_not_countermand_finished_copy_or_identity_contract(role):
    actual = prompt(role)
    assert "never draft the page's" not in actual
    assert "draft the page's prose or markup in your reasoning" not in actual
    # Account-card branches must follow the same default as a new no-card project.
    if role == "author":
        actual = prompts_web.build_web_author_prompt(
            brand_card="{}", theme_token_names="brand", account_card="target"
        )
    else:
        kwargs = {
            "doc_title": "New project",
            "has_existing_content": False,
            "brand_card": "{}",
            "account_card": "target",
        }
        actual = (
            prompts_web.build_web_solo_prompt(**kwargs, theme_token_names="brand")
            if role == "solo"
            else prompts_web.build_web_orchestrator_prompt(**kwargs, author_cap=2, review_cap=2)
        )
    assert "typically the campaign header's co-brand slot" not in actual


@pytest.mark.parametrize("role", ["solo", "author"])
def test_unbound_copy_keeps_exact_text_route_without_promising_new_slots(role):
    kwargs = {"brand_card": "{}", "theme_token_names": "brand", "account_card": "target"}
    actual = (
        prompts_web.build_web_solo_prompt(
            **kwargs, doc_title="New project", has_existing_content=False
        )
        if role == "solo"
        else prompts_web.build_web_author_prompt(**kwargs)
    )
    assert "text_edits_json" in actual
    assert "come back as new slots" not in actual
    assert "texts and links come back as rebindable slots" not in actual


def test_solo_composition_summary_allows_supported_interaction_reconstruction():
    actual = prompt("solo")
    # The repeated lane summary must agree with the earlier construction ladder.
    summary = actual.split("- TWO COMPOSING LANES:", 1)[1].split("- `author_web_page`", 1)[0]
    assert "supported interactive states" in summary
