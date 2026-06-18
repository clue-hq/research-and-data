"""Typed config-schema placeholders — *defaulted, read by no engine yet* (M0.4).

"Policy is data, not code" (conventions §2) covers more than the jurisdiction switch. The other
"policy is data" surfaces each need a *shared shape* so later milestones bind to one definition
rather than inventing their own config blob:

* :class:`MergePolicy` — merge/`current_value` params (M1).
* :class:`ScoringRubric` — fit/intent weights (M3 compiles, M6 scores).
* :class:`SourceProfile` — per-pack source profiles + source-intelligence reweighting knobs (M4).
* :class:`BudgetCaps` — tier/budget caps + the per-campaign hard cap (M7 / Doc C §5).
* :class:`FreshnessTtls` — field-level freshness TTLs (M1 merge / M9 verification).

These ship with sensible defaults and **validate on load** (out-of-range caps/weights raise), but
no engine reads them in M0 — they reserve the seam. The owning milestone fills in behavior; the
shape never moves.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_research.core import CostCents


class MergePolicy(BaseModel):
    """``current_value`` merge params (M1 owns the algorithm; substrate §1).

    The merge view is *pure deterministic policy, not an agent*: highest tier satisfying the
    field's freshness TTL → tie-break corroborations desc, confidence desc, collected_at desc →
    emit a conflict flag if two low-tier sources disagree. These knobs parameterize that policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Two sources at tier <= this threshold that disagree raise the conflict flag (substrate §1).
    conflict_tier_threshold: int = Field(default=2, ge=1, le=4)
    # A claim below this confidence is ignored by the merge even at a high tier.
    min_confidence_to_consider: float = Field(default=0.0, ge=0.0, le=1.0)
    # Corroborations needed before a tier-3 (third-party) claim outranks a stale tier-2.
    corroboration_floor: int = Field(default=1, ge=0)


class ScoringRubric(BaseModel):
    """Fit/intent scoring weights (M3 compiles into the ICP spec; M6 applies in Pass A scoring).

    Fit and intent are decomposed and each component links back to claims (overview §3); the
    weights are config so a client/ICP can retune scoring without a code change. Component weights
    are validated to sum to 1.0 (within tolerance) so a misconfigured rubric fails on load.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fit_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    intent_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    # Named sub-component weights inside fit/intent (e.g. {"firmographic": 0.6, ...}).
    fit_components: dict[str, float] = Field(default_factory=dict)
    intent_components: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_weights(self) -> ScoringRubric:
        if abs((self.fit_weight + self.intent_weight) - 1.0) > 1e-6:
            raise ValueError(
                f"fit_weight + intent_weight must sum to 1.0 "
                f"(got {self.fit_weight} + {self.intent_weight})"
            )
        for name, components in (("fit", self.fit_components), ("intent", self.intent_components)):
            if components and abs(sum(components.values()) - 1.0) > 1e-6:
                raise ValueError(f"{name}_components weights must sum to 1.0 when present")
            if any(w < 0.0 or w > 1.0 for w in components.values()):
                raise ValueError(f"{name}_components weights must each be in 0..1")
        return self


class SourceProfile(BaseModel):
    """Per-pack source profile + reweighting knobs (M4 / staged-flow §7).

    The source-intelligence layer learns which sources yield surviving claims and reweights
    (staged-flow §7e). M0 reserves the shape: a per-source weight map and the bounds the learning
    loop must respect. ``preferred_sources``/``blocked_sources`` let a client pin or exclude a
    provider without a code change (conventions §2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack: str = "core"  # the vertical pack this profile applies to (e.g. "healthcare")
    source_weights: dict[str, float] = Field(default_factory=dict)  # source_key -> weight (0..1)
    preferred_sources: tuple[str, ...] = ()
    blocked_sources: tuple[str, ...] = ()
    # Bounds the M4 learning loop must keep weights within (so reweighting can't zero a source out).
    min_source_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    max_source_weight: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_weight_bounds(self) -> SourceProfile:
        if self.min_source_weight > self.max_source_weight:
            raise ValueError("min_source_weight must be <= max_source_weight")
        out_of_range = {k: w for k, w in self.source_weights.items() if not 0.0 <= w <= 1.0}
        if out_of_range:
            raise ValueError(f"source_weights must be in 0..1; out of range: {out_of_range}")
        return self


class BudgetCaps(BaseModel):
    """Tier/budget caps + the per-campaign hard cap (M7 / Doc C §5).

    Doc C §5: the cost dial is *fan-out per account × accounts per pass*; the client sets a
    per-campaign hard cap and the run stops gracefully at a checkpoint when projected spend would
    exceed it. M0 reserves the shape (in ``CostCents`` — :class:`~decimal.Decimal`, exact for
    budget sums); M7 reads it. All caps validate as non-negative on load.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # The client-set per-campaign hard cap (the run halts at a checkpoint when projected spend
    # would exceed this). None == no cap configured yet (the client confirms it at run setup).
    per_campaign_hard_cap_cents: CostCents | None = None
    # Per-account caps, tiered (Doc C §5 budget bands). Keyed by tier label, e.g. "top"/"high".
    per_account_cap_cents: dict[str, CostCents] = Field(default_factory=dict)
    # Per-contact cap for deep committee/contact profiling (highest per-entity cost band).
    per_contact_cap_cents: CostCents | None = None
    # Pass A is deterministic-only and cheap; a low cents/account ceiling guards a runaway.
    pass_a_cap_cents_per_account: CostCents = Decimal("5")

    @model_validator(mode="after")
    def _check_caps_non_negative(self) -> BudgetCaps:
        # CostCents already enforces >= 0 at the field level; this guards the dict values too and
        # gives a fail-fast, named error for an out-of-range cap (acceptance criterion).
        for tier, cap in self.per_account_cap_cents.items():
            if cap < 0:
                raise ValueError(f"per_account_cap_cents[{tier!r}] must be >= 0 (got {cap})")
        return self


class FreshnessTtls(BaseModel):
    """Field-level freshness TTLs (M1 merge / M9 verification).

    The merge view (substrate §1) only considers a claim that satisfies its field's freshness
    TTL; verification (M9) ages claims out. Field-level TTLs default by field-class here and are
    overridable per field-key. (Personal-claim retention TTLs proper live on the policy — Doc D
    §4 — :class:`~clue_research.config.policy.RetentionTtls`.)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_ttl: timedelta = timedelta(days=365)
    by_field_class: dict[str, timedelta] = Field(
        default_factory=lambda: {
            "core": timedelta(days=365),
            "account": timedelta(days=180),
            "account.resonance": timedelta(days=90),
            "contact": timedelta(days=180),
            "contact.facet": timedelta(days=90),
        }
    )
    by_field_key: dict[str, timedelta] = Field(default_factory=dict)
