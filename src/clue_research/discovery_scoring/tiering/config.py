"""Tiering + checkpoint configuration (M6.4) — policy as data, not code (conventions §2 / D7).

The cost-economics knobs of the tier checkpoint, kept as a swappable config object (mirroring
M6.1's :class:`DiscoveryConfig` / M6.3's :class:`ScoringConfig`) so the per-tier Pass-B budget bands
(D7) are tuned per client/ICP/pack without touching the engine. The *tier cutoffs* themselves live
in the ICP's ``ScoringRubric.tier_cutoffs`` (M3.4) and are adjustable by the human at the checkpoint
— this config is only the engine's cost-estimate shape.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from clue_research.core import CostCents, UnitInterval


class TieringConfig(BaseModel):
    """Cost-estimate policy for the tier checkpoint.

    ``pass_b_bands_cents`` maps a **tier label** to its per-account Pass-B (deep research) cost band
    in cents (Doc C §5: "Pass B — dollars/account; depth scales with tier"). A tier *absent* from
    the map — e.g. the rubric's ``fallback_tier`` (``"untiered"``) or a low tier — is **not
    deep-eligible**: it contributes zero projected spend and zero projected-deep accounts, which is
    exactly the two-pass discipline ("Pass B runs only on high tiers"). The keys must match the
    rubric's :class:`~clue_research.icp.rubric.TierBand` labels; defaults cover the common
    ``high``/``medium`` vocabulary and are *starting points to confirm against real campaign cost
    data* (D7, Doc C §8) — versioned config, never hardcoded policy. ``estimate_confidence`` is the
    band the pre-run estimate is reported with (an estimate, never false-precision).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pass_b_bands_cents: dict[str, CostCents] = Field(
        default_factory=lambda: {"high": Decimal(500), "medium": Decimal(200)}
    )
    estimate_confidence: UnitInterval = 0.5

    def band_cents(self, tier: str) -> CostCents:
        """The per-account Pass-B cost band for ``tier`` — zero (not deep-eligible) if unmapped."""
        return self.pass_b_bands_cents.get(tier, Decimal(0))


DEFAULT_TIERING_CONFIG = TieringConfig()
