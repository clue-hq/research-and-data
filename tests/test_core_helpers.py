"""M0.2 acceptance: value_json (de)serialization and the trust-tier ordering helper."""

from __future__ import annotations

from collections.abc import Callable

from clue_research.core import (
    TIER_ORDER,
    Claim,
    ExtractionMethod,
    by_tier_ascending,
    first_confident_claim,
    parse_value_json,
    serialize_value_json,
    to_value_json,
)


def test_value_json_round_trip() -> None:
    payload = {"amount_usd": 1_000_000, "round": "B", "investors": ["a", "b"], "lead": None}
    assert to_value_json(payload) == payload
    restored = parse_value_json(serialize_value_json(payload))
    assert restored == payload


def test_to_value_json_rejects_non_json() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        to_value_json({1, 2, 3})  # a set is not JSON


def test_tier_order_constant() -> None:
    assert TIER_ORDER == (1, 2, 3, 4)


def test_by_tier_ascending_orders_most_trusted_first(make_account: Callable[..., Claim]) -> None:
    t3 = make_account(source_tier=3, extraction_method=ExtractionMethod.SCRAPE)
    t1 = make_account(source_tier=1, extraction_method=ExtractionMethod.API)
    t4 = make_account(
        source_tier=4, extraction_method=ExtractionMethod.LLM_SYNTHESIS, evidence_span="x"
    )
    ordered = by_tier_ascending([t3, t1, t4])
    assert [c.source_tier for c in ordered] == [1, 3, 4]


def test_first_confident_claim_stops_at_first_hit(make_account: Callable[..., Claim]) -> None:
    t1_low = make_account(source_tier=1, extraction_method=ExtractionMethod.API, confidence=0.4)
    t2_high = make_account(
        source_tier=2, extraction_method=ExtractionMethod.SCRAPE, confidence=0.95
    )
    # tier-1 is most trusted but below threshold -> falls through to the tier-2 confident hit
    chosen = first_confident_claim([t2_high, t1_low], min_confidence=0.8)
    assert chosen is t2_high
    # with a low threshold, the most-trusted (tier-1) wins
    assert first_confident_claim([t2_high, t1_low], min_confidence=0.1) is t1_low
    # nothing clears a very high bar
    assert first_confident_claim([t1_low], min_confidence=0.99) is None
