"""Typed config-schema placeholders — *defaulted, read by no engine yet* (M0.4).

"Policy is data, not code" (conventions §2) covers more than the jurisdiction switch. The other
"policy is data" surfaces each need a *shared shape* so later milestones bind to one definition
rather than inventing their own config blob:

* :class:`MergePolicy` — merge/`current_value` params (M1).
* :class:`ScoringRubric` — fit/intent weights (M3 compiles, M6 scores).
* :class:`SourceProfile` — per-pack source profiles + source-intelligence reweighting knobs (M4).
* :class:`ConfidenceThresholds` — the trust-tiered waterfall's per-field-class stop knob (M4.1).
* :class:`SourcePlanPolicy` — how deep the M4.6 source plan reaches (tier scope + deep-research
  preference).
* :class:`BudgetCaps` — tier/budget caps + the per-campaign hard cap (M7 / Doc C §5).
* :class:`FreshnessTtls` — field-level freshness TTLs (M1 merge / M9 verification).

Most ship with sensible defaults and **validate on load** (out-of-range caps/weights raise) but are
read by no engine yet — they reserve the seam, and the owning milestone fills in behavior. Two are
*live*: :class:`ConfidenceThresholds` (the waterfall's stop bar) and :class:`SourcePlanPolicy` (the
planner's tier reach) are read per-run by the M8 deep workers through the layered config — the
client/ICP-facing toggle for "raise the bar / consult deep research more eagerly" with no code edit.
The shape never moves.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core import (
    DEFAULT_NUMERIC_ABS_TOLERANCE,
    DEFAULT_NUMERIC_REL_TOLERANCE,
    DEFAULT_SEMANTIC_JACCARD_THRESHOLD,
    CostCents,
    FieldClass,
    UnitInterval,
)


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
    # The mode-aware conflict-equality tolerances ([M9.2×M1.2]). Default from the shared ``core``
    # constants so this M0.4 seam stays aligned with ``claimstore.MergePolicy`` and
    # ``verification.CorroborationPolicy`` (a no-DB drift guard asserts all three layers match).
    numeric_rel_tolerance: float = Field(default=DEFAULT_NUMERIC_REL_TOLERANCE, ge=0.0)
    numeric_abs_tolerance: float = Field(default=DEFAULT_NUMERIC_ABS_TOLERANCE, ge=0.0)
    semantic_jaccard_threshold: float = Field(
        default=DEFAULT_SEMANTIC_JACCARD_THRESHOLD, ge=0.0, le=1.0
    )


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


# Starting priors (D7 — defaults to confirm against real campaigns, not hardcoded policy):
# deterministic/official facts demand a high bar; fuzzy synthesized signals (resonance, personal
# hooks) clear at a lower one (locked decision #1 example: "firmographic 0.8, fuzzy resonance 0.6").
_CONFIDENCE_DEFAULTS: dict[FieldClass, float] = {
    FieldClass.CORE: 0.8,
    FieldClass.ACCOUNT: 0.75,
    FieldClass.ACCOUNT_RESONANCE: 0.6,
    FieldClass.CONTACT: 0.75,
    FieldClass.CONTACT_FACET: 0.6,
    FieldClass.PACK: 0.75,
}


class ConfidenceThresholds(BaseModel):
    """Per-field-class confidence thresholds — the waterfall's stop knob (M4.1, locked decision #1).

    The trust-tiered waterfall stops at the first claim whose ``confidence`` clears the field's
    threshold (substrate §4). Locked decision #1: that threshold is **versioned config keyed by
    field-class** (deterministic firmographic fields demand a high bar; fuzzy resonance/facet a
    lower one) — it is **NOT** on ``FieldDef`` / the field table / the plan hash, so swapping a
    threshold is a config change, never a field-row migration or a code edit. Raising the bar is the
    indirect lever on deep research: the higher tiers "succeed" less often, so the waterfall reaches
    the tier-4 synthesis products more often (paired with :class:`SourcePlanPolicy`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    # Fallback for any field-class not explicitly listed.
    default: UnitInterval = 0.7
    by_field_class: dict[FieldClass, UnitInterval] = Field(
        default_factory=lambda: dict(_CONFIDENCE_DEFAULTS)
    )

    def for_field_class(self, field_class: FieldClass) -> float:
        """The confidence a claim must clear to stop the waterfall for this field-class."""
        return self.by_field_class.get(field_class, self.default)


DEFAULT_CONFIDENCE_THRESHOLDS = ConfidenceThresholds()


class SourcePlanPolicy(BaseModel):
    """Client/ICP-facing source-planner policy — how deep the source plan reaches (M4.6).

    Two knobs over the config-bounded Source Planner. Neither changes *what* the planner may
    propose — that stays the allowed set (source-profile ∩ registry); they only set how far down the
    trust tiers a plan spans and whether the tier-4 deep-research products are guaranteed a seat:

    * ``tier_scope`` — the inclusive upper bound on trust tiers the plan includes (``None`` = all
      tiers). Lowering it to ``3`` keeps the cheap, high-trust band and excludes the tier-4 open-web
      synthesis products (``exa_deep`` / ``parallel_task``) — the cost dial.
    * ``prefer_deep_sources`` — guarantees the tier-4 deep-research products are *in scope* even
      when ``tier_scope`` would otherwise exclude them. It does **not** reorder the trust tiers
      (tier-4 still runs last, after 1–3, and stays least-trusted — the anti-fabrication discipline
      holds); it only widens the band so deep research is consulted when the top tiers miss.

    Both are versioned, layered config (overridable per client/ICP) — the policy-as-data toggle for
    "consult deep research more eagerly at a given time" without a code change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    tier_scope: int | None = Field(default=None, ge=1, le=4)
    prefer_deep_sources: bool = False

    def effective_max_tier(self, override: int | None = None) -> int | None:
        """The inclusive max trust tier a plan should span, after resolving the policy.

        ``override`` (a worker / call-site's explicit ``tier_scope``) wins when set; otherwise the
        policy's ``tier_scope`` applies. When ``prefer_deep_sources`` is on, the bound is *widened*
        to include tier 4 (``None`` already spans every tier, so it is left as-is) — never narrowed,
        so the toggle can only add deep research, never silently drop a configured tier.
        """
        base = override if override is not None else self.tier_scope
        if not self.prefer_deep_sources or base is None:
            return base
        return max(base, 4)


DEFAULT_SOURCE_PLAN_POLICY = SourcePlanPolicy()


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
    # The per-account deep cap for a tier with no specific ``per_account_cap_cents`` entry — the
    # conservative fallback (mirrors :class:`RecursionPolicy.default_caps`). ``None`` == an unlisted
    # tier has *no* per-account cap (the per-campaign cap stays the hard backstop). The M7.5 budget
    # engine reads :meth:`per_account_cap_for` so any tier — listed or not — resolves to one number.
    default_per_account_cap_cents: CostCents | None = None
    # Per-contact cap for deep committee/contact profiling (highest per-entity cost band, Doc C §5).
    # RESERVED — not yet enforced by the M7.5 engine: deep contact/committee runs (modes M3/M4) are
    # M8, and there is no per-contact run row to attach a distinct band to at M7. Until M8 adds a
    # contact-scoped check, per-entity contact spend is governed by the per-account cap + the
    # per-campaign hard cap (the backstop). M8 wires the contact band off this field.
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

    def per_account_cap_for(self, tier: str) -> CostCents | None:
        """The per-account deep cap for ``tier`` — its specific :attr:`per_account_cap_cents` band,
        else :attr:`default_per_account_cap_cents` (the conservative fallback). ``None`` means no
        per-account cap applies to this tier (the M7.5 engine then leaves per-account spend
        un-denied and relies on the per-campaign hard cap as the backstop)."""
        return self.per_account_cap_cents.get(tier, self.default_per_account_cap_cents)


class TierRecursionCaps(BaseModel):
    """The bounded-recursion caps for one tier (M7.2 / Doc C §3).

    Three dials govern the per-account fan-out for accounts in this tier: ``max_depth`` (0 = no
    facet sub-workers, 1 = one level, 2 = the full two-level dive), ``max_aspect_workers`` (the
    level-1 breadth — how many aspect clusters fan out at once), and
    ``max_facet_workers_per_aspect`` (the level-2 breadth — facets an eligible aspect may spawn).
    Top tier gets depth 2;
    lower tiers get one level or none (Doc C §3). The concrete numbers are deferred until real cost
    data exists (Doc C §8) — these are safe, conservative defaults the dial ships with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_depth: int = Field(default=0, ge=0, le=2)
    max_aspect_workers: int = Field(default=4, ge=0)
    max_facet_workers_per_aspect: int = Field(default=0, ge=0)


class RecursionPolicy(BaseModel):
    """The bounded recursion knob (M7.2 / Doc C §3) — *policy as data*, per-ICP/pack-overridable.

    The two-level fan-out (orchestrator → aspect workers → facet sub-workers) is real research
    power, but ungoverned it is the prototype's "spawn excessive subagents" blowout. This caps depth
    and worker-count **per tier** and restricts which field-classes may recurse at all (the richest
    aspects — ``account.resonance.*``, ``contact.facet.*``), so "be thorough" can never mean
    unbounded spawn. The dial lives entirely in versioned config: retuning the per-tier numbers
    (Doc C §8) is a config bump, never a code change. The M7.2 ``SpawnGuard`` reads this as the
    single runtime chokepoint. Conservative defaults: top tier depth 2, high depth 1, any unlisted
    tier depth 0 (no recursion — the safe floor).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    by_tier: dict[str, TierRecursionCaps] = Field(
        default_factory=lambda: {
            "top": TierRecursionCaps(
                max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=4
            ),
            "high": TierRecursionCaps(
                max_depth=1, max_aspect_workers=6, max_facet_workers_per_aspect=3
            ),
        }
    )
    # Caps for a tier with no specific entry — the conservative floor: no facet recursion at all.
    default_caps: TierRecursionCaps = TierRecursionCaps(
        max_depth=0, max_aspect_workers=4, max_facet_workers_per_aspect=0
    )
    # Field-class *prefixes* whose aspects may spawn facet sub-workers (the richest, Doc C §2/§3).
    # Matched by prefix (see :meth:`is_eligible`): an aspect equal to a listed class OR nested under
    # it (``account.resonance.culture`` under ``account.resonance``) is eligible. An aspect whose
    # class is not listed never recurses, regardless of depth budget.
    eligible_classes: tuple[str, ...] = ("account.resonance", "contact.facet")

    def caps_for(self, tier: str) -> TierRecursionCaps:
        """The recursion caps for ``tier`` — its specific entry, or the conservative default."""
        return self.by_tier.get(tier, self.default_caps)

    def is_eligible(self, aspect: str) -> bool:
        """Whether an aspect may spawn facet sub-workers — i.e. its key is a recursion-eligible
        field-class (or nests under one). A non-eligible aspect is denied recursion at the guard."""
        return any(aspect == cls or aspect.startswith(cls + ".") for cls in self.eligible_classes)


class DeepPhaseConfig(BaseModel):
    """The DEEP-phase fan-out bounds + cost dial (M8A) — *policy as data* (Doc C §3/§5).

    The concrete expression of the cost dial (*fan-out-per-account × accounts-per-pass*): how many
    committee members are profiled per account, how many contacts run at once within an account, how
    many accounts run in parallel, and the per-contact budget-admission knobs. Versioned + per-ICP
    overridable alongside :class:`BudgetCaps` / :class:`RecursionPolicy`; changing the dial is a
    config edit, never a code change.

    M8A.1 (the per-account orchestrator) reads ``committee_size_cap`` + ``max_contacts_in_flight``;
    the ``per_contact_*`` budget knobs + ``max_parallel_accounts`` are the fixed interface M8A.3
    (fan-out budget admission) and M8A.2 (the scheduler's accounts-per-pass) consume — defined once
    here so the downstream issues build against the trunk's shape rather than inventing their own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Max admitted committee members profiled per account (the level-1 fan-out): the rest are
    # truncated, mirroring the graph's ``max_aspect_workers`` cap. Coverage-confidence, not
    # completeness (Doc C §3).
    committee_size_cap: int = Field(default=8, ge=1)
    # Intra-account contact concurrency — how many ``profile_contact`` run at once for one account.
    max_contacts_in_flight: int = Field(default=3, ge=1)
    # Accounts-per-pass — the deep scheduler's parallelism cap (M8A.2 binds it to ``max_parallel``).
    max_parallel_accounts: int = Field(default=4, ge=1)
    # Per-contact pre-spend estimate the budget-admission gate (M8A.3) projects before each contact.
    per_contact_estimate_cents: CostCents = Decimal(50)
    # Per-contact spend sub-envelope carved from the account envelope at admission (M8A.3).
    per_contact_cap_cents: CostCents = Decimal(200)


class FreshnessTtls(BaseModel):
    """Field-level freshness TTLs (M1 merge / M9 verification).

    The merge view (substrate §1) only considers a claim that satisfies its field's freshness
    TTL; verification (M9) ages claims out. Field-level TTLs default by field-class here and are
    overridable per field-key. (Personal-claim retention TTLs proper live on the policy — Doc D
    §4 — :class:`~clue_config.policy.RetentionTtls`.)
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


class VerificationHealthThresholds(BaseModel):
    """Alert floors for the M13.4 verification-health panel (Doc C §6 — the early-warning surface).

    The panel reports three rates — tier-4 faithfulness pass share (M9.3), strong identity-binding
    share (M9.4 / Doc D), and the M9.2 corroboration pass rate — and *flags* one when it drops below
    its floor, signalling a possible model/resolver regression. The floors are *policy-as-data*
    (conventions §2): per-client/ICP tunable config, not a code constant, so a stricter client can
    raise them without a code change. Each is a share in ``[0, 1]``; a metric with no observations
    (zero denominator) never alerts (there is nothing to be unhealthy about yet).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    faithfulness_pass_floor: float = Field(default=0.8, ge=0.0, le=1.0)
    strong_binding_floor: float = Field(default=0.5, ge=0.0, le=1.0)
    corroboration_pass_floor: float = Field(default=0.5, ge=0.0, le=1.0)
