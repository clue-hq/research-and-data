"""Coverage-estimator configuration (M6.5) — policy as data, not code (conventions §2 / D7).

The estimator's calibration knobs, kept as a swappable config object (mirroring M6.1's
:class:`DiscoveryConfig` / M6.4's :class:`TieringConfig`). The estimation method and its confidence
calibration are explicitly config-driven and "improve once real campaign-size data exists" (D7), so
the band width, the stopping-reason confidence penalties, and the productivity threshold are tuned —
per client / ICP / pack — without touching the engine. Defaults are deliberately conservative
starting points to confirm against real campaigns, not policy.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clue_research.discovery_scoring.discovery import StoppingReason


class CoverageConfig(BaseModel):
    """Calibration policy for the saturation coverage estimator.

    The band half-width is ``clamp(band_width_scale / sqrt(total_records), band_width_min,
    band_width_max)`` plus a per-``stopping_reason`` penalty: a run cut off by a cost/round cap is
    *more* uncertain than one that saturated on its own (the marginal-yield curve was still
    descending), so its band is wider. ``productive_yield_threshold`` is the aggregate new-candidate
    rate above which the search was still "finding new companies" — the signal that distinguishes a
    low-confidence budget-cap stop (raise the budget) from a genuine saturation stop.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Band half-width from sampling uncertainty: wider when fewer records were seen, tighter as the
    # capture count grows. Scale / sqrt(total_records), clamped to a sane floor and ceiling.
    band_width_scale: float = Field(default=0.6, ge=0.0)
    band_width_min: float = Field(default=0.04, ge=0.0, le=1.0)
    band_width_max: float = Field(default=0.25, ge=0.0, le=1.0)
    # Extra band half-width per stopping reason. Only a MARGINAL_YIELD stop is genuine saturation
    # evidence (the new-candidate rate fell away on its own) → no penalty. Every other reason is a
    # *cut-off* of some kind and is more uncertain: EXHAUSTED = the planned query set drained (may
    # have been too small — not saturation); BUDGET_CAP / ROUND_CAP = a cost/safety stop. Keys are
    # StoppingReason values; an unlisted reason contributes no penalty.
    stopping_penalties: dict[str, float] = Field(
        default_factory=lambda: {
            StoppingReason.MARGINAL_YIELD.value: 0.0,
            StoppingReason.EXHAUSTED.value: 0.06,
            StoppingReason.BUDGET_CAP.value: 0.12,
            StoppingReason.ROUND_CAP.value: 0.12,
        }
    )
    # The occupancy point is the band's centre; the band is deliberately asymmetric and leans DOWN
    # (the saturation model overstates coverage under non-uniform sampling), so the downside
    # half-width is the wider multiple of the base width.
    downside_multiple: float = Field(default=2.0, ge=0.0)
    upside_multiple: float = Field(default=1.0, ge=0.0)
    # Aggregate new-candidate rate (distinct / captures) above which the run was still productive
    # (a cut-off here means low coverage confidence + "raise the budget").
    productive_yield_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    # Coverage point estimate at/above which a *saturated* stop reads as HIGH confidence.
    high_coverage_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # The estimate is **capped strictly below 1.0**: open-ended discovery can never prove it found
    # everyone (Doc C §7), so the band structurally never asserts completeness — there is always a
    # residual long-tail the searched channels could have missed. The ``le=0.99`` ceiling makes this
    # a TYPE invariant, not just a default: no config can push the band to a rendered "~100%"
    # (``round(0.99*100) == 99``), so a policy swap can never make the report claim completeness.
    coverage_ceiling: float = Field(default=0.95, gt=0.0, le=0.99)

    def stopping_penalty(self, reason: StoppingReason) -> float:
        """The band-width penalty for ``reason`` — ``0`` if the reason carries none."""
        return self.stopping_penalties.get(reason.value, 0.0)


DEFAULT_COVERAGE_CONFIG = CoverageConfig()


__all__ = ["CoverageConfig", "DEFAULT_COVERAGE_CONFIG"]
