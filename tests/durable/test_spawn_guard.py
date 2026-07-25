"""Pure tests for the hard runtime guard (M7.2) — no DB.

``SpawnGuard`` is the single chokepoint every facet spawn passes through. These assert each denial
reason and the check order (eligibility → depth → count → budget), so the hard cap holds regardless
of what a worker asks for.
"""

from __future__ import annotations

from decimal import Decimal

from clue_config import RecursionPolicy, TierRecursionCaps
from clue_research.durable import SpawnDenyReason, SpawnGuard

_POLICY = RecursionPolicy(
    by_tier={
        "top": TierRecursionCaps(max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=2),
        "low": TierRecursionCaps(max_depth=0, max_aspect_workers=4, max_facet_workers_per_aspect=0),
    }
)
_GUARD = SpawnGuard(_POLICY)


def test_allows_eligible_within_depth_and_count() -> None:
    d = _GUARD.may_spawn(
        parent_aspect="account.resonance", depth=1, current_facet_count=0, tier="top"
    )
    assert d.allowed and d.reason is None


def test_denies_non_eligible_aspect() -> None:
    d = _GUARD.may_spawn(parent_aspect="account", depth=1, current_facet_count=0, tier="top")
    assert not d.allowed and d.reason is SpawnDenyReason.NOT_ELIGIBLE


def test_denies_when_depth_exceeds_tier_max() -> None:
    # low tier has max_depth=0 → a depth-1 facet is over the limit (no facets ever at low tier).
    d = _GUARD.may_spawn(
        parent_aspect="account.resonance", depth=1, current_facet_count=0, tier="low"
    )
    assert not d.allowed and d.reason is SpawnDenyReason.DEPTH_EXCEEDED
    # top tier allows depth 2 but not 3.
    assert (
        _GUARD.may_spawn(
            parent_aspect="contact.facet", depth=3, current_facet_count=0, tier="top"
        ).reason
        is SpawnDenyReason.DEPTH_EXCEEDED
    )


def test_denies_when_per_aspect_count_reached() -> None:
    # top tier facet cap is 2 → the 3rd (count already 2) is denied.
    d = _GUARD.may_spawn(parent_aspect="contact.facet", depth=1, current_facet_count=2, tier="top")
    assert not d.allowed and d.reason is SpawnDenyReason.COUNT_EXCEEDED


def test_denies_for_budget_even_when_caps_allow() -> None:
    # within depth + count, but the remaining envelope is exhausted / too small.
    spent = _GUARD.may_spawn(
        parent_aspect="account.resonance",
        depth=1,
        current_facet_count=0,
        tier="top",
        remaining_budget_cents=Decimal(0),
    )
    assert not spent.allowed and spent.reason is SpawnDenyReason.BUDGET

    too_pricey = _GUARD.may_spawn(
        parent_aspect="account.resonance",
        depth=1,
        current_facet_count=0,
        tier="top",
        remaining_budget_cents=Decimal("5"),
        estimated_cost_cents=Decimal("9"),
    )
    assert not too_pricey.allowed and too_pricey.reason is SpawnDenyReason.BUDGET

    # a spawn that fits the remaining budget is allowed.
    fits = _GUARD.may_spawn(
        parent_aspect="account.resonance",
        depth=1,
        current_facet_count=0,
        tier="top",
        remaining_budget_cents=Decimal("20"),
        estimated_cost_cents=Decimal("9"),
    )
    assert fits.allowed


def test_eligibility_is_checked_before_depth() -> None:
    # a non-eligible aspect at an over-limit depth reports eligibility first (the binding reason).
    d = _GUARD.may_spawn(parent_aspect="account", depth=5, current_facet_count=99, tier="low")
    assert d.reason is SpawnDenyReason.NOT_ELIGIBLE
