"""Pre-run campaign cost estimate for a confirmed ICP (M5.2 → Doc C §5).

At confirm, before any discovery/scoring spend, the client is shown "~N accounts → ~M go deep →
~$X" (Doc C §5). The **authoritative** estimate is M7's ``BudgetEngine.estimate`` (it runs against a
real discovered count); M5.2 has no discovered count yet, so it surfaces a **pre-discovery prior**
computed from versioned cost-dial config (policy-as-data — conventions §2; D7), with a low
``confidence`` to mark it a forecast, not a commitment. When M7's real ``BudgetEngine`` is injected
at the composition root it returns the same frozen :class:`~clue_core.execution.Estimate`
unchanged — this is the placeholder behind that seam, not a second cost model.

The cost dial is *fan-out-per-account × accounts-per-pass* (Doc C §5): a cheap deterministic Pass A
over every discovered account, then expensive deep research on the high-tier fraction only.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_core import CostCents, Estimate, UnitInterval

# Cost-dial priors as config (D7 — starting bands to confirm against real campaigns, not hardcoded
# policy). Cents are exact Decimal (the DB numeric / M7 hard-cap contract).
_DEFAULT_PROJECTED_ACCOUNTS = 500  # expected ICP-fit accounts a campaign discovers (a prior)
_DEFAULT_DEEP_FRACTION = 0.2  # fraction that clears tiering and goes deep (Pass B)
_DEFAULT_DISCOVERY_CENTS = Decimal("5")  # per discovered candidate (existence/identity)
_DEFAULT_SCORING_CENTS = Decimal("1")  # Pass A per account (cheap deterministic proxies)
_DEFAULT_DEEP_CENTS = Decimal("500")  # Pass B per deep account (bounded fan-out)
_DEFAULT_CONFIDENCE: UnitInterval = 0.3  # low: a pre-discovery prior


class EstimateInputs(BaseModel):
    """The cost-dial priors a pre-run estimate is computed from (versioned config; D7). Defaults are
    the Doc C §5 starting bands; a caller (or, later, M7's config) overrides any of them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projected_account_count: int = _DEFAULT_PROJECTED_ACCOUNTS
    deep_fraction: UnitInterval = _DEFAULT_DEEP_FRACTION
    discovery_cents_per_account: CostCents = _DEFAULT_DISCOVERY_CENTS
    scoring_cents_per_account: CostCents = _DEFAULT_SCORING_CENTS
    deep_cents_per_account: CostCents = _DEFAULT_DEEP_CENTS
    confidence: UnitInterval = _DEFAULT_CONFIDENCE


def estimate_campaign(inputs: EstimateInputs | None = None) -> Estimate:
    """Project a campaign's cost from cost-dial priors → the frozen :class:`Estimate` (Doc C §5).

    ``estimated = discovered × (discovery + scoring) + deep × deep_cost`` where
    ``deep = round(discovered × deep_fraction)`` — the two-pass economics made legible. Pure and
    deterministic (no clock, no IO); the same ``inputs`` always yield the same estimate."""
    cfg = inputs if inputs is not None else EstimateInputs()
    discovered = max(cfg.projected_account_count, 0)
    deep = round(discovered * cfg.deep_fraction)
    shallow_cost = discovered * (cfg.discovery_cents_per_account + cfg.scoring_cents_per_account)
    deep_cost = deep * cfg.deep_cents_per_account
    estimated = shallow_cost + deep_cost
    per_account = (estimated / discovered) if discovered > 0 else Decimal(0)
    return Estimate(
        discovered_count=discovered,
        projected_deep_count=deep,
        estimated_cost_cents=estimated,
        cost_per_account_cents=per_account,
        confidence=cfg.confidence,
    )
