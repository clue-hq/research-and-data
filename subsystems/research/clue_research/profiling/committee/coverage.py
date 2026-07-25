"""Committee coverage confidence (M8.3) — a trust statement, never a completeness guarantee.

Open-ended discovery cannot prove it found everyone (conventions §5, Doc C §7); committee discovery
reports an *estimated* coverage band of the account's buying committee plus the **named people-
channels it did not search**, rather than implying the committee is exhaustive. This is the contact-
axis analogue of M6's coverage report, one level down and lighter (a committee is a handful of
people, not an open account universe), and M8-owned (M6's estimator is unimportable here).

The estimate uses the same saturation-occupancy intuition as M6: sampling from an unknown
population, the marginal new-admit yield (distinct admits per candidate seen) falls as the committee
saturates. A high yield means we are still finding new people (low coverage); a low yield means
redundancy dominates (high coverage). The point estimate is capped by a ceiling — we never claim
100%.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from clue_core import UnitInterval
from clue_research.profiling.committee.stopping import CommitteeStopReason

# Never claim we found the whole committee, however saturated the sampling looks (conventions §5).
_COVERAGE_CEILING = 0.95
# Half-width of the reported band around the point estimate (sampling uncertainty).
_BAND_HALF_WIDTH = 0.15


class CommitteeCoverageConfidence(StrEnum):
    """How much to trust the committee coverage estimate."""

    NONE = "none"  # nothing admitted — no basis to estimate
    LOW = "low"  # cut off (budget) while still productive, or barely any signal
    MODERATE = "moderate"  # partial saturation, or sources exhausted with channels still unsearched
    HIGH = "high"  # genuinely saturated (marginal-yield rule fired) and few channels left


class CommitteeCoverage(BaseModel):
    """The committee coverage estimate: a band + the searched/unsearched people-channels + a
    completeness-free framing line (Doc C §7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    estimate_low: UnitInterval
    estimate_high: UnitInterval
    estimate_point: UnitInterval
    confidence: CommitteeCoverageConfidence
    channels_searched: tuple[str, ...] = ()
    channels_not_searched: tuple[str, ...] = ()
    stopping_reason: CommitteeStopReason
    candidates_seen: int = 0
    admitted: int = 0
    framing: str = ""


def _coverage_from_marginal_yield(marginal_yield: float) -> float:
    """Saturation-occupancy coverage from the marginal new-admit yield (bisection).

    Models distinct-found ``D = N(1 - e^{-C/N})`` over an unknown population ``N`` after ``C``
    captures; ``marginal_yield = D/C = (1 - e^{-x})/x`` with ``x = C/N``. Solve for ``x`` and return
    coverage ``= 1 - e^{-x}``. Yield ≥ 1 (no redundancy yet) → 0 coverage; ≤ 0 (fully redundant) →
    1 coverage. Capped by :data:`_COVERAGE_CEILING`."""
    if marginal_yield >= 1.0:
        return 0.0
    if marginal_yield <= 0.0:
        return _COVERAGE_CEILING
    lo, hi = 1e-9, 50.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        # g(x) = (1 - e^-x)/x is monotonically decreasing in x.
        g = (1.0 - math.exp(-mid)) / mid
        if g > marginal_yield:
            lo = mid
        else:
            hi = mid
    coverage = 1.0 - math.exp(-(lo + hi) / 2.0)
    return min(coverage, _COVERAGE_CEILING)


def _confidence(
    stopping_reason: CommitteeStopReason, admitted: int, n_unsearched: int
) -> CommitteeCoverageConfidence:
    if admitted <= 0:
        return CommitteeCoverageConfidence.NONE
    if stopping_reason is CommitteeStopReason.BUDGET_CAP:
        return CommitteeCoverageConfidence.LOW  # cut off while possibly still productive
    if stopping_reason is CommitteeStopReason.MARGINAL_YIELD:
        # Genuinely saturated — high only if we are not leaving many channels unsearched.
        return (
            CommitteeCoverageConfidence.HIGH
            if n_unsearched == 0
            else CommitteeCoverageConfidence.MODERATE
        )
    # EXHAUSTED: bounded by which channels exist.
    return (
        CommitteeCoverageConfidence.MODERATE
        if n_unsearched == 0
        else CommitteeCoverageConfidence.LOW
    )


def estimate_committee_coverage(
    *,
    channels_searched: Sequence[str],
    all_channels: Sequence[str],
    stopping_reason: CommitteeStopReason,
    candidates_seen: int,
    admitted: int,
) -> CommitteeCoverage:
    """Estimate committee coverage + name the unsearched people-channels (Doc C §7).

    ``all_channels`` is every people-channel the registry could consult (the universe); the
    unsearched set is that minus what was searched. The framing line states an estimate, never an
    exhaustiveness claim."""
    searched = tuple(dict.fromkeys(channels_searched))  # de-dup, preserve order
    searched_set = set(searched)
    unsearched = tuple(c for c in dict.fromkeys(all_channels) if c not in searched_set)

    if admitted <= 0 or candidates_seen <= 0:
        point = 0.0
    else:
        marginal_yield = admitted / candidates_seen
        point = _coverage_from_marginal_yield(marginal_yield)

    low = max(0.0, point - _BAND_HALF_WIDTH)
    high = min(1.0, point + _BAND_HALF_WIDTH)
    confidence = _confidence(stopping_reason, admitted, len(unsearched))

    unsearched_note = (
        f"; {len(unsearched)} people-channel(s) not searched ({', '.join(unsearched)})"
        if unsearched
        else ""
    )
    framing = (
        f"Estimated ~{low:.0%}–{high:.0%} of the account's buying committee identified via "
        f"{len(searched)} people-source(s) ({admitted} member(s) admitted); not a completeness "
        f"guarantee{unsearched_note}."
    )

    return CommitteeCoverage(
        estimate_low=low,
        estimate_high=high,
        estimate_point=point,
        confidence=confidence,
        channels_searched=searched,
        channels_not_searched=unsearched,
        stopping_reason=stopping_reason,
        candidates_seen=candidates_seen,
        admitted=admitted,
        framing=framing,
    )
