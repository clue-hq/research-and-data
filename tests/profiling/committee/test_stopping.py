"""M8.3 committee bounded-discovery stopping rule (pure — no DB).

The walk must terminate: a marginal-yield drop over the window or a budget cap fires; a productive
single source is never cut off before the window fills.
"""

from __future__ import annotations

from decimal import Decimal

from clue_research.profiling.committee.stopping import (
    CommitteeStoppingConfig,
    CommitteeStoppingRule,
    CommitteeStopReason,
)


def test_budget_cap_fires_first() -> None:
    rule = CommitteeStoppingRule(budget_cap_cents=Decimal(10))
    rule.record(new_admits=3, candidates_seen=3, cost_cents=Decimal(12))
    assert rule.reason() is CommitteeStopReason.BUDGET_CAP


def test_marginal_yield_fires_when_window_unproductive() -> None:
    config = CommitteeStoppingConfig(window_size=1, marginal_yield_threshold=0.1)
    rule = CommitteeStoppingRule(config)
    # A redundant source: candidates seen but zero new admits → yield 0 < threshold → stop.
    rule.record(new_admits=0, candidates_seen=4, cost_cents=Decimal(0))
    assert rule.reason() is CommitteeStopReason.MARGINAL_YIELD


def test_productive_source_does_not_stop_before_window_fills() -> None:
    config = CommitteeStoppingConfig(window_size=2, marginal_yield_threshold=0.1)
    rule = CommitteeStoppingRule(config)
    rule.record(new_admits=3, candidates_seen=3, cost_cents=Decimal(1))
    # Only one consultation recorded; window (size 2) not full → keep going.
    assert rule.reason() is None


def test_window_yield_averages_recent_consultations() -> None:
    config = CommitteeStoppingConfig(window_size=2, marginal_yield_threshold=0.1)
    rule = CommitteeStoppingRule(config)
    rule.record(new_admits=3, candidates_seen=3, cost_cents=Decimal(1))  # productive
    rule.record(new_admits=0, candidates_seen=3, cost_cents=Decimal(1))  # redundant
    # window yield = 3 / 6 = 0.5 > 0.1 → still productive overall, keep going.
    assert rule.reason() is None
    rule.record(new_admits=0, candidates_seen=3, cost_cents=Decimal(1))  # redundant again
    # window now [(0,3),(0,3)] → yield 0 < 0.1 → stop.
    assert rule.reason() is CommitteeStopReason.MARGINAL_YIELD


def test_spent_accumulates() -> None:
    rule = CommitteeStoppingRule()
    rule.record(new_admits=1, candidates_seen=1, cost_cents=Decimal("2.5"))
    rule.record(new_admits=1, candidates_seen=1, cost_cents=Decimal("1.5"))
    assert rule.spent_cents == Decimal("4.0")
