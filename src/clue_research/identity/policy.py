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
