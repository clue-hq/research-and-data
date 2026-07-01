"""The layered config models — defaults, overlays, and the merged :class:`Config` (M0.4).

The loader (``loader.py``) merges three layers in precedence order — **defaults → per-client →
per-ICP/per-campaign** — each layer *versioned* so a config change is auditable (mirroring
versioned ICP specs, staged-flow §2). This module defines:

* :class:`ConfigOverlay` — a *sparse* layer: every field optional, so an override sets only what
  it changes and inherits the rest. The per-client and per-ICP layers are overlays.
* :class:`Config` — the *dense*, fully-resolved, validated object the engine receives. Every
  field is present (defaulted). This is what :func:`clue_research.config.get_config` returns.

Both carry a :class:`ConfigVersion` so "which config produced this run" is queryable. The policy
sub-tree (:class:`~clue_research.config.policy.JurisdictionPolicy`) is folded into ``Config`` and
also surfaced directly by :func:`clue_research.config.get_policy`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clue_research.config.gateway import GatewayConfig
from clue_research.config.policy import JurisdictionPolicy
from clue_research.config.schema import (
    BudgetCaps,
    ConfidenceThresholds,
    FreshnessTtls,
    MergePolicy,
    RecursionPolicy,
    ScoringRubric,
    SourcePlanPolicy,
    SourceProfile,
    VerificationHealthThresholds,
)


class ConfigVersion(BaseModel):
    """Provenance of one config layer — *which* layer, at *what* version (staged-flow §2).

    Versioning every layer makes a config change auditable: the merged :class:`Config` records
    the version of each contributing layer so a run can be reproduced and "why did scoring change"
    is answerable from data, not memory.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: str  # "defaults" | "client" | "icp"
    version: int = 1
    label: str | None = None  # optional human label, e.g. "2026-Q2 conservative"


class ConfigOverlay(BaseModel):
    """A sparse override layer (per-client or per-ICP). Every field is optional.

    Unset fields inherit from the layer beneath. A whole sub-tree (policy, scoring, budgets…) is
    replaced if present and inherited if absent — a partial sub-tree merge is intentionally *not*
    supported at M0 (it would make "which version produced this value" ambiguous); a layer that
    wants to change one knob supplies the whole sub-object. The loader records the overlay's
    :class:`ConfigVersion`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: ConfigVersion | None = None
    policy: JurisdictionPolicy | None = None
    merge_policy: MergePolicy | None = None
    scoring_rubric: ScoringRubric | None = None
    source_profiles: tuple[SourceProfile, ...] | None = None
    confidence_thresholds: ConfidenceThresholds | None = None
    source_plan_policy: SourcePlanPolicy | None = None
    budget_caps: BudgetCaps | None = None
    recursion_policy: RecursionPolicy | None = None
    freshness_ttls: FreshnessTtls | None = None
    gateway: GatewayConfig | None = None
    verification_health_thresholds: VerificationHealthThresholds | None = None
    # M13.4/D7 — whether the cost & progress ObservabilitySurface is exposed to the client. A
    # top-level scalar (not a sub-tree) so a client can flip *just* this flag without re-supplying a
    # whole sub-object (ConfigOverlay has no partial sub-tree merge).
    observability_client_facing: bool | None = None


class Config(BaseModel):
    """The fully-resolved, validated config the engine is injected with (M0.4 seam).

    Returned by :func:`clue_research.config.get_config`. Every "policy is data" surface is present
    and defaulted; ``applied_versions`` records the version of each layer that contributed, in
    precedence order, so the config is auditable and reproducible.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str
    icp_id: str | None = None
    policy: JurisdictionPolicy = JurisdictionPolicy()
    merge_policy: MergePolicy = MergePolicy()
    scoring_rubric: ScoringRubric = ScoringRubric()
    source_profiles: tuple[SourceProfile, ...] = ()
    # The waterfall's per-field-class stop bar and the planner's tier reach — read per-run by the
    # M8 deep workers (the two *live* policy-as-data source knobs; the rest here is still a seam).
    confidence_thresholds: ConfidenceThresholds = ConfidenceThresholds()
    source_plan_policy: SourcePlanPolicy = SourcePlanPolicy()
    budget_caps: BudgetCaps = BudgetCaps()
    recursion_policy: RecursionPolicy = RecursionPolicy()
    freshness_ttls: FreshnessTtls = FreshnessTtls()
    gateway: GatewayConfig = GatewayConfig()
    verification_health_thresholds: VerificationHealthThresholds = VerificationHealthThresholds()
    # M13.4/D7 — whether the cost & progress ObservabilitySurface read projections are exposed to
    # the
    # client (cost pass-through) vs. kept as an internal control. Defaults to the recommended
    # client-facing posture (Doc C §5). A *visibility* toggle only — the surface computes the same
    # projections either way; gating happens at the api/portal boundary, never as two code paths.
    observability_client_facing: bool = True
    # The layer versions that produced this object, base-first (defaults → client → icp).
    applied_versions: tuple[ConfigVersion, ...] = Field(default_factory=tuple)
