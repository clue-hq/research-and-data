"""The coverage-confidence result + input shapes (M6.5 / ENG-150).

Coverage is a **trust statement**, not a completeness guarantee (Doc C §7): "estimated ~X–Y% of the
addressable account set found via the channels searched" plus *the channels not yet searched*. These
types carry that statement and its evidence — never a bare number:

* :class:`ChannelObservation` is the pure estimator's per-channel input (records the channel
  returned, the post-dedup *new* candidates it contributed, its errors/cost) — read either from the
  in-memory :class:`~clue_research.discovery_scoring.discovery.ChannelYield` or from the durable
  ``source_yield`` telemetry, so the estimation method is decoupled from where the counts live.
* :class:`ChannelCurvePoint` is one point of the diminishing new-candidate (marginal-yield) curve —
  the per-channel saturation evidence behind the estimate.
* :class:`UnsearchedChannel` is one account-scope channel the source registry *could* cover but this
  run did **not** query — a named, actionable coverage gap (Doc C §7: "name the unsearched
  channels").
* :class:`CoverageBand` is the estimate itself — a band (``low``..``high``) with a qualitative
  ``confidence``, **never** a false-precision point (acceptance: "a band, not a single number").
* :class:`CoverageReport` is the per-run object the M6.4 checkpoint + M13 observability read; the
  estimation ``method`` tag on the band makes the estimator swappable behind the seam (D7).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, model_validator

from clue_research.core import CostCents, RunId, UnitInterval
from clue_research.discovery_scoring.discovery import StoppingReason

NonNegInt = Annotated[int, Ge(0)]


class CoverageConfidence(StrEnum):
    """How much trust to place in the coverage estimate (a qualitative label over the band).

    ``NONE`` — nothing was searched / no records returned, so there is no saturation signal at all.
    ``LOW`` — the run was cut off (budget/round cap) while still finding new candidates, so the true
    addressable set is likely much larger than what was found (recommend raising the budget).
    ``MODERATE`` — a partial saturation signal. ``HIGH`` — the search genuinely saturated (marginal
    yield fell away on its own) over the channels searched."""

    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class ChannelObservation(BaseModel):
    """One channel's yield counters for a run — the pure estimator's per-channel input.

    ``records_returned`` is every raw record the channel returned (captures, pre-dedup);
    ``new_candidates`` is how many survived the run's in-stream dedup (the channel's *fresh* yield —
    a distinct company no earlier channel/round had surfaced). Their relationship across channels
    is the saturation signal: ``Σ new_candidates`` = distinct found, ``Σ records_returned`` = total
    captures, and the gap between them is the redundancy (recaptures) the estimate reads.
    Sourced from either the in-memory ``ChannelYield`` or the durable ``source_yield`` row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    records_returned: NonNegInt = 0
    new_candidates: NonNegInt = 0
    errors: NonNegInt = 0
    cost_cents: CostCents = Decimal(0)


class ChannelCurvePoint(BaseModel):
    """One point of the per-channel diminishing new-candidate curve (the marginal-yield evidence).

    ``redundant`` = ``records_returned - new_candidates`` (recaptures: records that were
    already-found companies); ``marginal_yield`` = ``new_candidates / records_returned`` (``0`` when
    returned nothing) — a channel's own fresh-yield rate, the curve that *diminishes* as the search
    saturates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    records_returned: NonNegInt
    new_candidates: NonNegInt
    redundant: NonNegInt
    marginal_yield: UnitInterval
    errors: NonNegInt = 0
    cost_cents: CostCents = Decimal(0)


class UnsearchedChannel(BaseModel):
    """An account-scope channel in the source registry that this run did **not** query — a named,
    actionable coverage gap (Doc C §7). ``geo_coverage`` (empty = global) lets the client see which
    region/segment querying it would add."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    tier: int
    geo_coverage: tuple[str, ...] = ()


class CoverageBand(BaseModel):
    """The coverage estimate as a band — never a false-precision point (acceptance §1).

    ``low``..``high`` is the estimated fraction of the addressable account set found *over the
    channels searched*; ``point`` is the central saturation estimate; ``confidence`` is the
    qualitative trust label; ``method`` tags the estimation model so it can be swapped behind the
    seam (D7: saturation → capture-recapture → learned) without changing the report shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    low: UnitInterval
    high: UnitInterval
    point: UnitInterval
    confidence: CoverageConfidence
    method: str = "saturation_occupancy_v1"

    @model_validator(mode="after")
    def _check_ordering(self) -> CoverageBand:
        if not self.low <= self.point <= self.high:
            raise ValueError(
                f"coverage band must satisfy low <= point <= high "
                f"(got low={self.low}, point={self.point}, high={self.high})"
            )
        return self

    def as_percent(self) -> str:
        """Render the band as ``~X–Y%`` (or ``~X%`` when the rounded bounds coincide) for the
        client-facing copy — the honest "estimated ~X–Y% found via these channels" phrasing."""
        lo, hi = round(self.low * 100), round(self.high * 100)
        return f"~{lo}%" if lo == hi else f"~{lo}–{hi}%"


class CoverageReport(BaseModel):
    """The per-run coverage-confidence report (Doc C §7) — read by the M6.4 checkpoint + M13.

    Frames coverage honestly: ``coverage_estimate_band`` (estimate, not guarantee),
    ``channels_searched`` / ``channels_not_searched`` (what was and was not queried),
    ``per_channel_new_candidate_curve`` (the saturation evidence), and ``stopping_reason`` (so a
    budget-cap stop with high marginal yield reads as low confidence + "raise budget", distinct from
    a genuine marginal-yield-exhausted stop). ``admitted`` / ``needs_review`` / ``rejected`` carry
    the M6.2 admitted-vs-seen context. ``framing`` is the one-line, completeness-free statement.
    Computed read-only from run telemetry — writes no claims and gates nothing (replaceability)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    coverage_estimate_band: CoverageBand
    channels_searched: tuple[str, ...]
    channels_not_searched: tuple[UnsearchedChannel, ...]
    per_channel_new_candidate_curve: tuple[ChannelCurvePoint, ...]
    stopping_reason: StoppingReason
    total_records: NonNegInt
    distinct_candidates: NonNegInt
    admitted: int | None = None
    needs_review: int | None = None
    rejected: int | None = None
    geo_gaps: tuple[str, ...] = ()
    recommendation: str | None = None
    framing: str = ""


__all__ = [
    "CoverageConfidence",
    "ChannelObservation",
    "ChannelCurvePoint",
    "UnsearchedChannel",
    "CoverageBand",
    "CoverageReport",
]
