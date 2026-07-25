"""``core.BudgetTracker`` — the shared envelope + running-spend arithmetic.

The tracker consolidates the manual budget threading the 2026-07-03 survey found (waterfall walk,
planner halt, aspect-worker per-field cap, Stage-0 field loop, facet-grant reservation, the two
stopping rules). Its two boundary predicates are deliberately distinct and each must match the
behavior the call sites had before the consolidation, exactly at the cap:

* ``would_exceed`` is **strict** (``>``) — an exact-fit spend is allowed (waterfall / planner).
* ``exhausted`` is **inclusive** (``>=``) — at the cap the walk stops (Stage-0 / aspect worker).
"""

from __future__ import annotations

from decimal import Decimal

from clue_core import BudgetTracker


def test_unbounded_never_exceeds_or_exhausts() -> None:
    budget = BudgetTracker(envelope_cents=None)
    budget.spend(Decimal(1_000_000))
    assert budget.would_exceed(Decimal(1_000_000)) is False
    assert budget.exhausted is False
    assert budget.remaining_cents is None
    assert budget.spent_cents == Decimal(1_000_000)


def test_spend_accumulates_exact_decimal() -> None:
    budget = BudgetTracker(envelope_cents=Decimal(100))
    budget.spend(Decimal("0.1"))
    budget.spend(Decimal("0.2"))
    assert budget.spent_cents == Decimal("0.3")  # exact — no float rounding
    assert budget.remaining_cents == Decimal("99.7")


def test_would_exceed_is_strict_exact_fit_allowed() -> None:
    # The waterfall / planner boundary: a step landing exactly on the envelope is allowed.
    budget = BudgetTracker(envelope_cents=Decimal(100))
    budget.spend(Decimal(60))
    assert budget.would_exceed(Decimal(40)) is False  # exact fit
    assert budget.would_exceed(Decimal(41)) is True
    budget.spend(Decimal(40))  # spent == envelope
    assert budget.would_exceed(Decimal(0)) is False  # strict: at the cap, zero more is fine
    assert budget.would_exceed(Decimal("0.01")) is True


def test_exhausted_is_inclusive_at_the_cap() -> None:
    # The Stage-0 / aspect-worker boundary: at the cap (spent == envelope) the walk stops.
    budget = BudgetTracker(envelope_cents=Decimal(100))
    budget.spend(Decimal(99))
    assert budget.exhausted is False
    budget.spend(Decimal(1))
    assert budget.exhausted is True
    assert budget.remaining_cents == Decimal(0)


def test_seeded_prior_spend_bounds_the_whole_thread() -> None:
    # The waterfall's ``cost_so_far`` seeding: the envelope bounds prior + this call's spend, and
    # this call's own spend is the delta off the seed.
    seed = Decimal(60)
    budget = BudgetTracker(envelope_cents=Decimal(100), spent_cents=seed)
    assert budget.would_exceed(Decimal(41)) is True
    assert budget.would_exceed(Decimal(40)) is False
    budget.spend(Decimal(25))
    assert budget.spent_cents - seed == Decimal(25)  # this call's spend only


def test_overshot_tracker_reports_unclamped_negative_remaining() -> None:
    # A tracker seeded past its envelope: exhausted fires; remaining is unclamped (callers check
    # ``exhausted`` first — the clamped client-facing figure is BurnDown, not the tracker).
    budget = BudgetTracker(envelope_cents=Decimal(100), spent_cents=Decimal(150))
    assert budget.exhausted is True
    assert budget.remaining_cents == Decimal(-50)


def test_zero_spend_reservation_is_a_no_op() -> None:
    # The facet-grant path: a grant with no estimate reserves nothing (spend(0)).
    budget = BudgetTracker(envelope_cents=Decimal(100))
    budget.spend(Decimal(0))
    assert budget.spent_cents == Decimal(0)
    assert budget.remaining_cents == Decimal(100)
