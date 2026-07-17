"""M7.5 pre-run estimate — the pure projection math (:func:`project_spend`), no DB, no store.

Doc C §5: *"~N discovered → ~M go deep → est \\$X."* These tests pin the decomposition (Pass A on
all accounts + Pass B on the tier-cutoff share, nested tiers priced at the per-tier cap), the
uniform-score deep-fraction model, the re-estimate-after-adjust behaviour, and the defensive
handling of degenerate cutoffs.
"""

from __future__ import annotations

from decimal import Decimal

from clue_config import BudgetCaps
from clue_research.durable.budget import project_spend

# A representative policy: Pass A 2c/account; top tier $5/account, high tier $2/account.
_POLICY = BudgetCaps(
    pass_a_cap_cents_per_account=Decimal("2"),
    per_account_cap_cents={"top": Decimal("500"), "high": Decimal("200")},
)


def test_decomposition_pass_a_plus_nested_pass_b() -> None:
    # 1000 discovered; top cutoff 0.9 → 10% (100 accts) at $5; high cutoff 0.7 → 30% at-or-above,
    # minus the 10% already counted as top = 20% (200 accts) at $2 (nested, counted at top tier).
    est = project_spend(_POLICY, discovered_count=1000, tier_cutoffs={"top": 0.9, "high": 0.7})
    assert est.discovered_count == 1000
    assert est.projected_deep_count == 300  # 100 top + 200 high
    pass_a = 1000 * 2
    pass_b = 100 * 500 + 200 * 200  # 50000 + 40000
    assert est.estimated_cost_cents == Decimal(pass_a + pass_b)  # 92000
    # cost_per_account is the per-deep-account Pass-B average (the fan-out dial), not blended.
    assert est.cost_per_account_cents == Decimal(pass_b) / Decimal(300)


def test_no_cutoffs_projects_pass_a_only() -> None:
    # Without tier cutoffs nothing goes deep — only the cheap Pass-A sweep is projected.
    est = project_spend(_POLICY, discovered_count=500, tier_cutoffs=None)
    assert est.projected_deep_count == 0
    assert est.estimated_cost_cents == Decimal(500 * 2)
    assert est.cost_per_account_cents == Decimal(0)


def test_reestimate_after_tightening_cutoffs_lowers_spend() -> None:
    # Tightening the cutoffs (higher thresholds → fewer go deep) must lower the projection — the
    # "re-estimating after a cutoff adjust reflects the new projection" acceptance criterion.
    loose = project_spend(_POLICY, discovered_count=1000, tier_cutoffs={"top": 0.8, "high": 0.6})
    tight = project_spend(_POLICY, discovered_count=1000, tier_cutoffs={"top": 0.95, "high": 0.85})
    assert tight.projected_deep_count < loose.projected_deep_count
    assert tight.estimated_cost_cents < loose.estimated_cost_cents


def test_tier_without_a_band_counts_but_adds_no_pass_b_cost() -> None:
    # A cutoff tier with no per-account band (and no default) goes deep in the *count* but cannot be
    # priced — it adds 0 to Pass B (documented: per_account_cap_for returns None → no cost).
    est = project_spend(_POLICY, discovered_count=100, tier_cutoffs={"mid": 0.5})
    assert est.projected_deep_count == 50  # 1 - 0.5 = 0.5 share
    assert est.estimated_cost_cents == Decimal(100 * 2)  # Pass A only; "mid" has no band


def test_default_per_account_cap_prices_unlisted_tiers() -> None:
    # default_per_account_cap_cents is the fallback band for a tier with no specific entry.
    policy = BudgetCaps(
        pass_a_cap_cents_per_account=Decimal("1"),
        per_account_cap_cents={"top": Decimal("500")},
        default_per_account_cap_cents=Decimal("100"),
    )
    est = project_spend(policy, discovered_count=100, tier_cutoffs={"top": 0.9, "mid": 0.5})
    # top: 10 accts @ 500; mid: (0.5 - 0.1)=0.4 → 40 accts @ default 100.
    assert est.projected_deep_count == 50
    assert est.estimated_cost_cents == Decimal(100 * 1 + 10 * 500 + 40 * 100)


def test_degenerate_cutoffs_are_clamped() -> None:
    # cutoff >= 1 → no accounts above it; cutoff <= 0 → all accounts. Clamped, never a negative.
    over = project_spend(_POLICY, discovered_count=100, tier_cutoffs={"top": 1.5})
    assert over.projected_deep_count == 0
    under = project_spend(
        _POLICY, discovered_count=100, tier_cutoffs={"top": -0.2}
    )  # all 100 go deep at top
    assert under.projected_deep_count == 100
    assert under.estimated_cost_cents == Decimal(100 * 2 + 100 * 500)


def test_non_numeric_and_non_finite_cutoffs_dropped() -> None:
    # The cutoffs are client input (carried as JSON): bool / NaN / inf are dropped defensively so a
    # malformed value never crashes or skews the projection (mirrors CampaignRun._to_float_cutoffs).
    est = project_spend(
        _POLICY,
        discovered_count=100,
        tier_cutoffs={"top": 0.9, "bad": float("nan"), "flag": True, "inf": float("inf")},  # type: ignore[dict-item]
    )
    assert est.projected_deep_count == 10  # only "top" survives


def test_zero_discovered_is_zero_spend() -> None:
    est = project_spend(_POLICY, discovered_count=0, tier_cutoffs={"top": 0.8})
    assert est.discovered_count == 0
    assert est.projected_deep_count == 0
    assert est.estimated_cost_cents == Decimal(0)


def test_negative_discovered_floored_to_zero() -> None:
    est = project_spend(_POLICY, discovered_count=-5, tier_cutoffs={"top": 0.8})
    assert est.discovered_count == 0
    assert est.estimated_cost_cents == Decimal(0)


def test_confidence_signals_the_modelling_assumption() -> None:
    # The uniform-score assumption is surfaced, not hidden: confidence = the Estimate default (0.5).
    est = project_spend(_POLICY, discovered_count=10, tier_cutoffs={"top": 0.8})
    assert est.confidence == 0.5


def test_per_tier_counts_sum_to_the_rounded_total_share() -> None:
    # Cumulative-boundary rounding: per-tier marginals must sum to round(n * total-deep-share), not
    # drift above it the way independently-rounded marginals would. n=7, cutoffs {top:0.5,high:0.25}
    # → total deep share 0.75 → round(7*0.75)=round(5.25)=5 (NOT 4+2=6 from per-tier rounding).
    est = project_spend(
        BudgetCaps(
            pass_a_cap_cents_per_account=Decimal("0"),
            per_account_cap_cents={"top": Decimal("100"), "high": Decimal("100")},
        ),
        discovered_count=7,
        tier_cutoffs={"top": 0.5, "high": 0.25},
    )
    assert est.projected_deep_count == 5
    # priced once per account at 100 → 5 * 100 (the marginals 4 + 1 sum to 5, no inflation)
    assert est.estimated_cost_cents == Decimal(5 * 100)
