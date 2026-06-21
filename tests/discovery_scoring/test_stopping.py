"""M6.1 (ENG-128) — the discovery stopping rule, in isolation (pure, no IO)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.discovery_scoring.discovery.stopping import (
    StoppingReason,
    StoppingRule,
    marginal_yield,
)


def test_marginal_yield_math() -> None:
    assert marginal_yield(3, 10) == 0.3
    assert marginal_yield(0, 0) == 0.0  # a degenerate window shows no yield, never divides by zero
    assert marginal_yield(5, 5) == 1.0


def test_window_not_full_does_not_trip_marginal_yield() -> None:
    rule = StoppingRule(window_size=3, marginal_yield_threshold=0.9, budget_cap_cents=None)
    rule.record_round(new_candidates=0, records_seen=10, cost_cents=Decimal(0))  # 0% yield
    rule.record_round(new_candidates=0, records_seen=10, cost_cents=Decimal(0))
    # only two rounds recorded; the window (size 3) is not yet full → keep going
    assert rule.reason() is None


def test_marginal_yield_fires_once_window_full_and_below_threshold() -> None:
    rule = StoppingRule(window_size=2, marginal_yield_threshold=0.5, budget_cap_cents=None)
    rule.record_round(new_candidates=0, records_seen=10, cost_cents=Decimal(0))
    rule.record_round(new_candidates=1, records_seen=10, cost_cents=Decimal(0))
    # window full, yield = 1/20 = 0.05 < 0.5 → stop on saturation
    assert rule.reason() is StoppingReason.MARGINAL_YIELD


def test_high_yield_keeps_going() -> None:
    rule = StoppingRule(window_size=2, marginal_yield_threshold=0.3, budget_cap_cents=None)
    rule.record_round(new_candidates=8, records_seen=10, cost_cents=Decimal(0))
    rule.record_round(new_candidates=9, records_seen=10, cost_cents=Decimal(0))
    assert rule.reason() is None  # 17/20 = 0.85 ≥ 0.3


def test_budget_cap_fires_immediately_and_overrides_yield() -> None:
    rule = StoppingRule(window_size=2, marginal_yield_threshold=0.0, budget_cap_cents=Decimal(10))
    rule.record_round(
        new_candidates=5, records_seen=5, cost_cents=Decimal(10)
    )  # high yield, at cap
    # budget is checked before the window-full marginal-yield check, and fires even on round 1
    assert rule.reason() is StoppingReason.BUDGET_CAP
    assert rule.spent_cents == Decimal(10)


def test_no_budget_cap_never_fires_on_cost() -> None:
    rule = StoppingRule(window_size=1, marginal_yield_threshold=0.0, budget_cap_cents=None)
    rule.record_round(new_candidates=1, records_seen=1, cost_cents=Decimal(10_000))
    assert not rule.budget_exceeded()
    assert rule.reason() is None  # threshold 0.0 + a non-empty yield ⇒ never the marginal stop


def test_window_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="window_size"):
        StoppingRule(window_size=0, marginal_yield_threshold=0.5, budget_cap_cents=None)
