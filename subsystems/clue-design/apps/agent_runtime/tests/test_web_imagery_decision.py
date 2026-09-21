"""D4 — the web lane must DECIDE about imagery, the way the scene lane does.

The scene director declares an imagery choice (kit asset ids / generate /
deliberately none) in its ART DIRECTION block on every create round, and its
reviewer checks the render against that declaration. The web lane had neither,
while its skills carried half a dozen "omit rather than decorate", "at most one
hero image", "restraint" rules and not one rule requiring imagery. With no
forcing step and a one-sided thumb on the scale, "no imagery" is where the
author lands by omission — and nothing downstream notices.

These tests pin the forcing step into the three role prompts and the reviewer's
checklist. They assert the DISCIPLINE (a decision is required, it reaches both
subagents, the reviewer can report its absence), not the exact prose.
"""

from __future__ import annotations

from lumen_agent.prompts_web import (
    build_web_author_prompt,
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
)
from test_web_skill_family import read_required_skill_reference


def _director(**kwargs) -> str:
    defaults = {
        "doc_title": "Acme",
        "has_existing_content": False,
        "brand_card": "{}",
        "review_cap": 2,
        "author_cap": 2,
    }
    defaults.update(kwargs)
    return build_web_orchestrator_prompt(**defaults)


# --- the director must decide -------------------------------------------------


def test_the_director_must_make_an_explicit_imagery_decision() -> None:
    prompt = _director()
    assert "IMAGERY" in prompt
    # All three outcomes are nameable — "none" stays legitimate, it just has to
    # be chosen rather than defaulted into.
    lowered = prompt.lower()
    assert "generate" in lowered
    assert "deliberately none" in lowered


def test_the_director_must_look_at_the_inventory_before_deciding() -> None:
    """The scene lane's rule: you cannot choose imagery you have not looked at."""
    prompt = _director()
    assert "search_assets" in prompt
    assert "BEFORE deciding" in prompt


def test_a_deliberate_none_must_carry_a_reason() -> None:
    prompt = _director()
    assert "WHY" in prompt


def test_the_imagery_decision_reaches_both_subagents() -> None:
    """Same guarantee the brand anchor already has: the decision is carried into
    the author's brief AND the reviewer's, not left in the director's head."""
    prompt = _director()
    imagery_section = prompt.split("IMAGERY", 1)[1]
    assert "author" in imagery_section and "reviewer" in imagery_section
    # And the reviewer delegation step says so again where it is acted on.
    assert "imagery decision" in prompt


def test_the_brand_logo_is_never_the_thing_that_gets_omitted() -> None:
    """The founder's complaint was not only about generated art: the page came
    back without the brand's REAL logo."""
    assert "logo" in _director().lower()
    assert "logo" in build_web_author_prompt(
        brand_card="{}", theme_token_names="primary"
    ).lower()


# --- the author must execute and report it ------------------------------------


def test_the_author_is_told_to_carry_out_the_decision_and_report_it() -> None:
    prompt = build_web_author_prompt(brand_card="{}", theme_token_names="primary")
    assert "IMAGERY DECISION" in prompt
    report = prompt.split("Report back to the director", 1)[1]
    assert "imagery decision" in report.lower()


def test_the_author_is_told_what_a_placeholder_result_means() -> None:
    """`mode: "placeholder"` is a failed generation sitting in the page as a grey
    box — the author is the only party that can catch it before the render."""
    prompt = build_web_author_prompt(brand_card="{}", theme_token_names="primary")
    assert "placeholder" in prompt
    assert "mode" in prompt


# --- the reviewer must be able to report its absence ---------------------------


def test_the_reviewer_can_report_brand_generic_imagery() -> None:
    prompt = build_web_reviewer_prompt()
    assert "imagery" in prompt.lower()
    assert "brand-generic" in prompt


def test_the_reviewer_distinguishes_deliberate_restraint_from_bareness(tmp_path) -> None:
    """The one thing this must not become: a rule that says every page needs a
    picture. Text-forward brands are real."""
    skill = " ".join(read_required_skill_reference(
        tmp_path, "review-website", "fidelity and behavior checks",
    ).split())
    assert "## Imagery — the decision check" in skill
    assert "text-forward" in skill
    assert "do not score restraint as failure or bareness as restraint" in skill


def test_the_review_checklist_treats_a_missing_brand_mark_as_blocking(tmp_path) -> None:
    skill = read_required_skill_reference(
        tmp_path, "review-website", "fidelity and behavior checks",
    )
    imagery = skill.split("## Imagery — the decision check", 1)[1].split("\n## ", 1)[0]
    assert "No logo anywhere is blocking" in imagery


def test_the_reviewer_prompt_still_composes_with_a_brief_and_an_account() -> None:
    """The imagery block must not disturb the slice-4 brief interpolation or the
    account personalization line."""
    prompt = build_web_reviewer_prompt(has_account=True, brief="BRIEF BODY")
    assert "BRIEF BODY" in prompt
    assert "1:1 account page" in prompt
    assert "brand-generic" in prompt
