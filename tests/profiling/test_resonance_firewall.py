"""M8.2 AC6 — the resonance sensitivity firewall (pure, no DB).

Account resonance is account-level, not personal: a resonance value must never smuggle a *named
individual's special-category attribute* (that belongs to ``contact.facet.*`` / M10). The firewall
fires only when a named individual co-occurs with a special-category term — an account-scoped
mention of morale/health-benefits with no named person passes (the safe, non-over-blocking shape).
"""

from __future__ import annotations

from pydantic import JsonValue

from clue_research.core import (
    ExtractionMethod,
    ResearchMode,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.profiling import resonance_firewall_ok


def _resonance_claim(value: JsonValue, *, span: str | None = None):
    return account_claim(
        entity_id=new_entity_id(),
        field_key="account.resonance.employee_sentiment",
        value_json=value,
        source_tier=3,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://glassdoor.example/acme",
        evidence_span=span,
    )


def test_clean_account_sentiment_passes() -> None:
    claim = _resonance_claim(
        {"label": "negative", "summary": "employees frustrated about compensation and workload"},
        span="Reviews cite low morale and slow promotions.",
    )
    assert resonance_firewall_ok(claim)


def test_account_level_health_mention_without_individual_passes() -> None:
    # A special-category *term* with no named individual is an account-level statement — allowed.
    claim = _resonance_claim(
        {"label": "mixed", "summary": "staff value the strong health insurance benefits"},
    )
    assert resonance_firewall_ok(claim)


def test_named_individual_without_special_category_passes() -> None:
    claim = _resonance_claim(
        {"label": "positive", "summary": "CEO Jane Doe is widely respected for transparency"},
    )
    assert resonance_firewall_ok(claim)


def test_named_individual_special_category_in_value_is_rejected() -> None:
    claim = _resonance_claim(
        {
            "label": "mixed",
            "summary": "morale dipped after CEO Jane Doe disclosed a cancer diagnosis",
        },
    )
    assert not resonance_firewall_ok(claim)


def test_named_individual_special_category_in_evidence_is_rejected() -> None:
    claim = _resonance_claim(
        {"label": "neutral", "summary": "culture is private"},
        span="Dr. Smith's religious activism shaped the firm's stance.",
    )
    assert not resonance_firewall_ok(claim)


def test_possessive_name_with_politics_is_rejected() -> None:
    claim = _resonance_claim(
        {"label": "mixed", "summary": "Jane Doe's union membership drew internal debate"},
    )
    assert not resonance_firewall_ok(claim)
