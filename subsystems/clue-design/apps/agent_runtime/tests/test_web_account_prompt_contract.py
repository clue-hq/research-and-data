"""Regress the prompt branches that cut native account evidence off from design.

These checks inspect the actual role payload, including the no-card path used by
name-only chat briefs. They guard routing/contradictions, not model output quality;
native runs must separately demonstrate evidence-led copy and safe missing data.
"""

from __future__ import annotations

import pytest
from lumen_agent.prompts_web import (
    build_web_author_prompt,
    build_web_orchestrator_prompt,
    build_web_solo_prompt,
)


def _prompt(role: str, account_card: str | None) -> str:
    common = {"brand_card": "SELLER", "account_card": account_card}
    if role == "author":
        return build_web_author_prompt(**common, theme_token_names="primary ink")
    common.update(doc_title="Campaign page", has_existing_content=False)
    if role == "director":
        return build_web_orchestrator_prompt(**common, review_cap=2, author_cap=3)
    return build_web_solo_prompt(**common, theme_token_names="primary ink")


@pytest.mark.parametrize("role", ["director", "author", "solo"])
@pytest.mark.parametrize("account_card", [None, "ACCOUNT CARD"])
def test_account_evidence_routing_does_not_depend_on_an_account_card(role, account_card):
    """A named brief without a card must still route to scoped reads/skill guidance."""
    prompt = _prompt(role, account_card)
    assert "web-account-personalization" in prompt
    assert "read_project_accounts" in prompt
    assert "read_account_research" in prompt
    assert "read_claims" in prompt
    assert "only when exposed on your role" in prompt
    assert "overview_not_written" in prompt
    assert "do not launch research or discovery" in prompt
    assert "source/claim IDs" in prompt


@pytest.mark.parametrize("role", ["director", "author", "solo"])
def test_account_card_does_not_override_evidence_or_force_a_reusable_template(role):
    """The card-present branch used to contradict the shared account skill."""
    prompt = _prompt(role, "ACCOUNT CARD")
    assert "only account facts from the card" not in prompt
    assert "Facts about them come from the card" not in prompt
    assert "account appears as name + logo only" not in prompt
    assert "THE PAGE IS A TEMPLATE, NOT ONE ACCOUNT'S PAGE" not in prompt
    assert "changing a name/logo does not re-ground an account-specific argument" in prompt
    # Template and visual ownership mechanics must survive the removal of the forced mode.
    assert "{{account.logo}}" in prompt
    assert "bind_account_logo" in prompt
    assert "never adopted" in prompt


@pytest.mark.parametrize("role", ["director", "author", "solo"])
def test_logo_binding_needs_an_actual_account_not_just_a_named_brief(role):
    prompt = _prompt(role, "ACCOUNT CARD")
    assert "Without that step the mark dies with the turn" not in prompt
    assert "real mapped account ID" in prompt
    assert "registered logo asset" in prompt
