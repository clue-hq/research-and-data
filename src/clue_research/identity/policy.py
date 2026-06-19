"""Resolution policy — the scorer/candidate-gen knobs as versioned data (M2.2).

"Policy is data, not code" (conventions §2): the matcher's feature weights, candidate-set bound,
and blocking thresholds live in a versioned :class:`ResolutionPolicy`, swappable per entity_type /
vertical **without a code change** — exactly mirroring how the claim-store's ``MergePolicy`` carries
the merge knobs. ``resolve`` reads a policy instance; swapping the ``version`` (or any weight)
changes behaviour with no edit to the engine.

The default weights encode the architecture's central conservatism (substrate §2 — *never silently
collapse two real companies*): the **strong-key features (domain / registry) hold a reserved weight
budget**, so a match with no confirmed strong key cannot reach the ``≥0.95`` auto-merge band — only
a *deterministic* strong-key hit (score ``1.0``, M2.2 stage 1) or an explicit strong-key match can.
This makes "fuzzy name+geo alone routes to human review, never auto-merge" a property of the data,
not a special case in the code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_research.identity.embedding import DEFAULT_MODEL_VERSION
from clue_research.identity.normalize import NORMALIZER_VERSION


class ScorerWeights(BaseModel):
    """Per-feature weights for the pairwise match scorer (sum to 1.0).

    The two *strong-key* features (``domain_agreement`` + ``registry_agreement``) form the reserved
    budget that a fuzzy-only match can never earn — keeping name+geo+alias matches below the
    auto-merge band by construction (the "never silently collapse" rule as data).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name_cosine: float = Field(default=0.35, ge=0.0, le=1.0)
    name_token_jaccard: float = Field(default=0.25, ge=0.0, le=1.0)
    geo_agreement: float = Field(default=0.15, ge=0.0, le=1.0)
    alias_overlap: float = Field(default=0.10, ge=0.0, le=1.0)
    domain_agreement: float = Field(default=0.10, ge=0.0, le=1.0)  # strong-key budget
    registry_agreement: float = Field(default=0.05, ge=0.0, le=1.0)  # strong-key budget

    @model_validator(mode="after")
    def _check_sum(self) -> ScorerWeights:
        total = (
            self.name_cosine
            + self.name_token_jaccard
            + self.geo_agreement
            + self.alias_overlap
            + self.domain_agreement
            + self.registry_agreement
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"scorer weights must sum to 1.0 (got {total})")
        return self

    @property
    def strong_key_budget(self) -> float:
        """The weight a fuzzy-only match cannot earn — the headroom below auto-merge."""
        return self.domain_agreement + self.registry_agreement


class ResolutionPolicy(BaseModel):
    """Versioned resolution policy (conventions §2 — policy is data). Swap a weight / threshold /
    the ``version`` and the matcher's behaviour changes with no code edit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    # The normalizer ruleset + embedder model this policy was tuned against (recorded so a
    # re-normalization / re-embed is an explicit, auditable config event, not a silent drift).
    normalizer_version: int = NORMALIZER_VERSION
    model_version: str = DEFAULT_MODEL_VERSION
    # Candidate-set bound (top-K) and blocking thresholds.
    top_k: int = Field(default=10, ge=1, le=1000)
    trigram_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    weights: ScorerWeights = ScorerWeights()


DEFAULT_RESOLUTION_POLICY = ResolutionPolicy()


class DispositionPolicy(BaseModel):
    """Versioned disposition bands (M2.3) — the auto-merge / review / new-entity thresholds as data.

    Substrate §2: high-confidence (≈≥0.95) auto-merges; the mid-band routes to human review; below
    the low threshold a fresh ``candidate`` entity is admitted. The thresholds are config, so tuning
    auto-merge aggressiveness (e.g. a more conservative posture in a higher-risk vertical, D8) is a
    data change, not a code change — and a borderline pair moves between auto-merge and review by a
    ``version`` bump alone. By M2.2's construction a fuzzy-only match caps at 0.85, so with the
    default 0.95 ceiling only a *deterministic* strong-key hit (score 1.0) ever auto-merges.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    auto_merge_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    review_low_threshold: float = Field(default=0.70, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_band_order(self) -> DispositionPolicy:
        if self.review_low_threshold > self.auto_merge_threshold:
            raise ValueError(
                "review_low_threshold must be <= auto_merge_threshold "
                f"(got {self.review_low_threshold} > {self.auto_merge_threshold})"
            )
        return self


DEFAULT_DISPOSITION_POLICY = DispositionPolicy()


def max_fuzzy_score(resolution: ResolutionPolicy) -> float:
    """The highest match score a candidate with **no confirmed strong key** can reach — the
    strong-key weight budget is unearnable in the probabilistic path (M2.2)."""
    return round(1.0 - resolution.weights.strong_key_budget, 6)


def assert_fuzzy_cannot_auto_merge(
    resolution: ResolutionPolicy = DEFAULT_RESOLUTION_POLICY,
    disposition: DispositionPolicy = DEFAULT_DISPOSITION_POLICY,
) -> None:
    """Bind the architecture's invariant to the data (substrate §2 — never silently collapse two
    real companies): a strong-key-free fuzzy match must NOT be able to reach the auto-merge band, so
    only a *deterministic* strong-key hit (score 1.0) auto-merges. Raises on a policy combination
    that would let fuzzy auto-merge — call it after loading both policies (a config gate), instead
    of trusting the prose. ``max_fuzzy_score`` must stay strictly below ``auto_merge_threshold``.
    """
    ceiling = max_fuzzy_score(resolution)
    if ceiling >= disposition.auto_merge_threshold:
        raise ValueError(
            "policy misconfiguration: a strong-key-free match can reach the auto-merge band "
            f"(max fuzzy {ceiling} >= auto_merge_threshold {disposition.auto_merge_threshold}); "
            "raise the strong-key weight budget (domain+registry) or the auto_merge_threshold"
        )


class ReusePolicy(BaseModel):
    """Versioned cross-tenant reuse classification (M2.5) — which claims are public-footprint
    (shared, amortized across clients) vs tenant-private (substrate §2). **Policy is data**: adding
    a vertical pack's public fields, or tightening a client's posture (D3), is a config change
    behind the classifier seam — no caller hardcodes the boundary.

    Defaults follow substrate §2: ``core.*`` / ``account.*`` firmographic / technographic / funding
    facts are public-footprint; ``crm_import`` facts, contact / personal / facet data, and
    ``account.resonance.*`` (client/ICP-shaped consumption) are tenant-private. Setting
    ``enabled=False`` is the **safe-degradation** switch — the classifier then marks *every* claim
    tenant-private, so cross-tenant reuse is off and isolation holds by construction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    enabled: bool = True  # False ⇒ everything tenant-private (disable reuse, safe degradation)
    # Field-key namespace prefixes whose claims are tenant-private (personal / client-shaped):
    # contacts/personal, the resonance layer, and per-client/ICP scoring outputs (fit/intent
    # scores are computed against one client's ICP — substrate §2/§9, M2.5 criterion).
    tenant_private_prefixes: tuple[str, ...] = (
        "contact.",
        "account.resonance.",
        "account.scoring.",
    )
    # Extraction methods whose claims are inherently tenant-private (CRM-imported = client data).
    tenant_private_methods: tuple[str, ...] = ("crm_import",)


DEFAULT_REUSE_POLICY = ReusePolicy()
