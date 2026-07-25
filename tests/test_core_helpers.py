"""M0.2 acceptance: value_json (de)serialization and the trust-tier ordering helper."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from clue_core import (
    TIER_ORDER,
    Claim,
    ExtractionMethod,
    by_tier_ascending,
    decode_jsonb,
    decode_jsonb_scalar,
    first_confident_claim,
    parse_cost_cents,
    parse_value_json,
    reference_time,
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


def test_decode_jsonb_passes_decoded_and_parses_raw() -> None:
    # asyncpg returns structured jsonb already decoded -> an object/array/None passes through as-is
    assert decode_jsonb({"a": 1}) == {"a": 1}
    assert decode_jsonb([1, 2]) == [1, 2]
    assert decode_jsonb(None) is None
    # a str/bytes round-trip is parsed; the widened guard now covers bytearray too
    assert decode_jsonb('{"a": 1}') == {"a": 1}
    assert decode_jsonb(b"[1, 2]") == [1, 2]
    assert decode_jsonb(bytearray(b'{"a": 1}')) == {"a": 1}


def test_decode_jsonb_scalar_never_reparses_a_decoded_scalar() -> None:
    # A bare-scalar column (claim.value_json): a decoded "robotics" IS the value, not JSON text, so
    # it must pass through untouched — decode_jsonb would reject the bare word as invalid JSON.
    assert decode_jsonb_scalar("robotics") == "robotics"
    assert decode_jsonb_scalar(42) == 42
    assert decode_jsonb_scalar({"a": 1}) == {"a": 1}
    assert decode_jsonb_scalar(None) is None
    # only a raw bytes/bytearray round-trip is parsed
    assert decode_jsonb_scalar(b'"robotics"') == "robotics"
    assert decode_jsonb_scalar(bytearray(b"42")) == 42


def test_reference_time_prefers_observed_then_collected(
    make_account: Callable[..., Claim],
) -> None:
    # The one shared fold (M9.5 DRY consolidation) the merge view, the freshness engine, and the
    # lawful-basis retention deadline all measure a claim's age from.
    observed = datetime(2026, 1, 1, tzinfo=UTC)
    with_observed = make_account(observed_at=observed)
    assert reference_time(with_observed) == observed
    without_observed = make_account()
    assert reference_time(without_observed) == without_observed.collected_at


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


def test_parse_cost_cents_accepts_finite_non_negative() -> None:
    # str / int / float all coerce to an exact (non-float-rounded) Decimal.
    assert parse_cost_cents("150000") == Decimal("150000")
    assert parse_cost_cents(100) == Decimal("100")
    assert parse_cost_cents(1.5) == Decimal("1.5")
    assert parse_cost_cents("0") == Decimal("0")


def test_parse_cost_cents_rejects_dangerous_values() -> None:
    # The whole point of the strict parser: a hostile/malformed budget input can never enter a
    # budget calculation as a real number. A negative would *inflate* remaining budget (a silent
    # per-entity-cap evasion) and a NaN would crash the ordering comparison in the spawn-budget
    # check — both must coerce to None so the caller treats them as "no estimate / no cap".
    for bad in (None, "NaN", "nan", "Infinity", "inf", "-inf", "-5", -5, "notanumber", [1], True):
        assert parse_cost_cents(bad) is None
