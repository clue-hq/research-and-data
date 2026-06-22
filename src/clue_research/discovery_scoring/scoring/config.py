"""Pass-A scoring configuration (M6.3) — policy as data, not code (conventions §2 / D7).

The deterministic knobs of the Pass-A scoring engine, kept as a swappable config object (mirroring
M6.1's :class:`DiscoveryConfig`) so the economics (D7) and the deterministic-first invariant are
tunable without touching the engine. The *scoring weights* live in the ICP's ``ScoringRubric``
(M3.4) — this is only the engine's run-shape policy.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScoringConfig(BaseModel):
    """Run-shape policy for the Pass-A scoring engine.

    ``max_source_tier`` is the **deterministic-first guard** (substrate §5a, Doc C §1): Pass A fills
    scoring fields via tiers 1–3 only — *no tier-4 / LLM synthesis*. The engine strips any source
    above this tier from each scoring field's ``tier_plan`` before driving the waterfall, so a
    tier-4 source bound for the deep pass can never be invoked at Pass A even if a field's plan
    lists one. ``3`` is the spec invariant; it is config so a stricter run (e.g. tier-1-only) needs
    no code change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_source_tier: int = Field(default=3, ge=1, le=3)


DEFAULT_SCORING_CONFIG = ScoringConfig()
