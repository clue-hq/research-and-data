"""The bounded-recursion runtime guard (M7.2) — the single chokepoint for facet sub-worker spawns.

Doc C §3: the two-level fan-out (orchestrator → aspect workers → facet sub-workers) is real research
power, but ungoverned it is the prototype's "spawn excessive subagents" blowout. The cap is enforced
in **two** places, as the architecture insists: *soft* in the worker's instructions (the runtime
hands each worker its depth/cap budget via ``AspectContext.params``, model-visible), and *hard* here
— :class:`SpawnGuard` is the one path the per-account graph (M7.1) calls before spawning any facet
sub-worker, so "be thorough" can never translate into unbounded spawn regardless of what the model
asked for. A spawn the guard denies is a no-op + a logged ``cap_hit``, never a run failure.

The dial values are *data, not code*: :class:`~clue_config.RecursionPolicy` is versioned,
per-ICP/pack-overridable config (conventions §2). Retuning per-tier depth/worker numbers (Doc C §8)
is a config bump — this guard's logic does not change. Budget denial is delegated: a spawn within
the depth/count caps may still be denied because the per-account budget envelope (M7.5) is spent.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from clue_config import RecursionPolicy
from clue_core import CostCents


class SpawnDenyReason(StrEnum):
    """Why a facet sub-worker spawn was denied (the ``cap_hit`` reason). All are *governed*
    outcomes, not errors: the run continues with the parent aspect marked partial."""

    NOT_ELIGIBLE = "not_eligible"  # the parent aspect's field-class may not recurse at all
    DEPTH_EXCEEDED = "depth_exceeded"  # the facet would exceed the tier's max_depth
    COUNT_EXCEEDED = "count_exceeded"  # the per-aspect facet-worker cap is already reached
    BUDGET = "budget"  # within depth/count caps, but the budget envelope (M7.5) is exhausted


class SpawnDecision(BaseModel):
    """The guard's verdict on one prospective facet spawn (M7.2). ``allowed`` is the bare
    ``may_spawn -> bool`` the spec names; ``reason`` carries the ``cap_hit`` cause for telemetry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: SpawnDenyReason | None = None


class SpawnGuard:
    """The single runtime chokepoint for facet sub-worker spawns (M7.2).

    Constructed once per graph from a :class:`RecursionPolicy`; the per-account graph calls
    :meth:`may_spawn` before *every* facet spawn. Because it is the only spawn path, the hard caps
    hold even when a worker (the model) asks for more — the spec's "hard runtime limit" half of the
    dual enforcement. Pure and stateless: the same inputs always yield the same decision."""

    def __init__(self, policy: RecursionPolicy) -> None:
        self.policy = policy

    def may_spawn(
        self,
        *,
        parent_aspect: str,
        depth: int,
        current_facet_count: int,
        tier: str,
        remaining_budget_cents: CostCents | None = None,
        estimated_cost_cents: CostCents | None = None,
    ) -> SpawnDecision:
        """Decide whether a parent aspect may spawn one more facet sub-worker.

        ``depth`` is the depth the *facet* would run at (parent depth + 1); ``current_facet_count``
        is how many facets this aspect has already been granted. Checked in order — eligibility,
        depth, count, budget — so the ``cap_hit`` reason names the binding constraint:

        * the parent aspect's class must be recursion-eligible (``account.resonance`` etc.);
        * the facet depth must not exceed the tier's ``max_depth`` (``max_depth=0`` ⇒ no facets);
        * the per-aspect facet count must be below ``max_facet_workers_per_aspect``;
        * if a ``remaining_budget_cents`` is supplied (the M7.5 envelope), the spawn's est. cost
          must fit — a within-caps spawn can still be denied for budget (Doc C §3 per-entity cap).
        """
        if not self.policy.is_eligible(parent_aspect):
            return SpawnDecision(allowed=False, reason=SpawnDenyReason.NOT_ELIGIBLE)

        caps = self.policy.caps_for(tier)
        if depth > caps.max_depth:
            return SpawnDecision(allowed=False, reason=SpawnDenyReason.DEPTH_EXCEEDED)
        if current_facet_count >= caps.max_facet_workers_per_aspect:
            return SpawnDecision(allowed=False, reason=SpawnDenyReason.COUNT_EXCEEDED)

        if remaining_budget_cents is not None:
            cost = estimated_cost_cents if estimated_cost_cents is not None else Decimal(0)
            if remaining_budget_cents <= 0 or cost > remaining_budget_cents:
                return SpawnDecision(allowed=False, reason=SpawnDenyReason.BUDGET)

        return SpawnDecision(allowed=True)
