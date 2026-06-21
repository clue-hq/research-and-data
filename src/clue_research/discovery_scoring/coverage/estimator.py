"""The coverage-confidence estimator (M6.5 / ENG-150) — the pure, deterministic estimation core.

Open-ended discovery can never *prove* completeness (Doc C §7), so this turns a stopped run's
per-channel yield counters into the honest alternative: an estimated coverage **band** over the
channels searched, plus the channels *not* searched. It is a **trust** statement, deliberately
separate from M6.1's **cost**-control stopping rule — coverage *reads* ``stopping_reason``, it never
controls stopping.

The estimation method (the saturation model below) sits entirely behind :func:`estimate_coverage`,
so it can be swapped (saturation → capture-recapture → a learned model) without changing any
consumer or the report shape (D7). The function is pure and deterministic for fixed inputs (a fixed
number of bisection steps), and writes nothing — coverage gates nothing.

**The saturation model.** With only the durable aggregate counts available — ``C`` total records
returned (captures) and ``D`` distinct companies found (``Σ`` post-dedup new candidates) — model
discovery as sampling from an addressable population of unknown size ``N``: after ``C`` captures the
expected number of distinct companies seen is ``D = N(1 - e^{-C/N})``. Writing ``m = D/C`` (the
aggregate new-candidate rate) and ``x = C/N``, this collapses to ``(1 - e^{-x})/x = m`` and the
coverage fraction ``D/N = 1 - e^{-x}``. So a low marginal yield (lots of recaptures) implies high
coverage, and ``m → 1`` (every record new — no saturation evidence) implies coverage → 0. The model
assumes near-uniform sampling, which real (clustered) channels violate *optimistically*, so the band
leans **down** from the point estimate (more downside room) — honest about the model's bias.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence

from clue_research.core import RunId
from clue_research.discovery_scoring.coverage.config import (
    DEFAULT_COVERAGE_CONFIG,
    CoverageConfig,
)
from clue_research.discovery_scoring.coverage.results import (
    ChannelCurvePoint,
    ChannelObservation,
    CoverageBand,
    CoverageConfidence,
    CoverageReport,
    UnsearchedChannel,
)
from clue_research.discovery_scoring.discovery import StoppingReason

# Only the marginal-yield rule is genuine saturation evidence (the new-candidate rate fell away on
# its own). EXHAUSTED means "the planned query set drained" — the plan may simply have been too
# small — so it is NOT saturation; a run can exhaust its queries while still finding lots of new
# candidates, which is a *low*-coverage, "widen the plan" situation, not a confident one.
_BISECTION_STEPS = 100  # interval shrinks by 2^-100 — far past float precision, deterministic


def _g(x: float) -> float:
    """``g(x) = (1 - e^{-x}) / x`` — the distinct-fraction-per-capture ratio; strictly decreasing
    from ``1`` (``x → 0``) to ``0`` (``x → ∞``)."""
    return (1.0 - math.exp(-x)) / x


def saturation_coverage(marginal_yield: float) -> float:
    """The occupancy coverage estimate ``1 - e^{-x}`` solving ``g(x) = marginal_yield``.

    ``marginal_yield >= 1`` (no redundancy) ⇒ no saturation evidence ⇒ ``0``; ``<= 0`` (fully
    saturated, degenerate) ⇒ ``1``. Otherwise bisect ``x`` (``g`` is monotonic, so the root is
    unique) over ``[~0, 60]`` — at ``x = 60`` coverage is ``1 - e^{-60} ≈ 1``, the clamp for a
    marginal yield below ``g(60) ≈ 1/60``. Deterministic: a fixed step count, no randomness."""
    if marginal_yield >= 1.0:
        return 0.0
    if marginal_yield <= 0.0:
        return 1.0
    lo, hi = 1e-12, 60.0
    if _g(hi) >= marginal_yield:  # marginal yield below the interval's min g ⇒ x beyond hi ⇒ ≈ full
        return 1.0 - math.exp(-hi)
    for _ in range(_BISECTION_STEPS):
        mid = 0.5 * (lo + hi)
        if _g(mid) > marginal_yield:  # g decreasing: g(mid) too high ⇒ root at a larger x
            lo = mid
        else:
            hi = mid
    return 1.0 - math.exp(-0.5 * (lo + hi))


def _clamp_unit(value: float) -> float:
    """Clamp to the ``[0, 1]`` unit interval."""
    return max(0.0, min(1.0, value))


def _aggregate(
    observations: Sequence[ChannelObservation],
) -> tuple[OrderedDict[str, ChannelObservation], int, int]:
    """Collapse observations to one per ``source_key`` (first-seen order; sum any duplicates) and
    return ``(by_key, total_records, distinct_candidates)``.

    Per channel, ``new_candidates`` is clamped to ``records_returned`` (a channel cannot contribute
    more *new* companies than records it returned) so a malformed counter can't inflate the found
    set. ``Σ`` the clamped new-candidate counts is the distinct companies found (the run's global
    in-stream dedup credits each distinct company as *new* exactly once)."""
    by_key: OrderedDict[str, ChannelObservation] = OrderedDict()
    for obs in observations:
        new = min(obs.new_candidates, obs.records_returned)
        clamped = obs.model_copy(update={"new_candidates": new})
        if obs.source_key in by_key:
            prev = by_key[obs.source_key]
            by_key[obs.source_key] = prev.model_copy(
                update={
                    "records_returned": prev.records_returned + clamped.records_returned,
                    "new_candidates": prev.new_candidates + clamped.new_candidates,
                    "errors": prev.errors + clamped.errors,
                    "cost_cents": prev.cost_cents + clamped.cost_cents,
                }
            )
        else:
            by_key[obs.source_key] = clamped
    total_records = sum(o.records_returned for o in by_key.values())
    distinct = sum(o.new_candidates for o in by_key.values())
    return by_key, total_records, distinct


def _curve(by_key: OrderedDict[str, ChannelObservation]) -> tuple[ChannelCurvePoint, ...]:
    """The per-channel diminishing new-candidate curve, in observation (search) order."""
    points: list[ChannelCurvePoint] = []
    for obs in by_key.values():
        returned = obs.records_returned
        yield_rate = obs.new_candidates / returned if returned > 0 else 0.0
        points.append(
            ChannelCurvePoint(
                source_key=obs.source_key,
                records_returned=returned,
                new_candidates=obs.new_candidates,
                redundant=returned - obs.new_candidates,
                marginal_yield=yield_rate,
                errors=obs.errors,
                cost_cents=obs.cost_cents,
            )
        )
    return tuple(points)


def _norm_geo(code: str) -> str:
    """Canonicalise a region code for comparison — strip + casefold — so an ICP filter ``"us"`` or
    ``" US "`` matches a registry ``"US"`` (mirrors ``identity.resolve._geo_country``). The ICP's
    ``icp_filters`` slot is free-form client data, so the two sides need not share a casing scheme;
    display values keep their original casing, only the *comparison* is normalised."""
    return code.strip().casefold()


def _geo_applicable(channel: UnsearchedChannel, geo_norms: frozenset[str]) -> bool:
    """Is ``channel`` applicable to the ICP's (normalised) target geos? No ICP geo constraint ⇒
    always; a global channel (empty ``geo_coverage``) ⇒ always; else its coverage must intersect the
    target geos (case-insensitively)."""
    if not geo_norms:
        return True
    if not channel.geo_coverage:
        return True
    return any(_norm_geo(g) in geo_norms for g in channel.geo_coverage)


def _band(
    *,
    distinct: int,
    total_records: int,
    marginal_yield: float,
    stopping_reason: StoppingReason,
    config: CoverageConfig,
) -> CoverageBand:
    """The coverage band (Doc C §7): an occupancy point estimate with an asymmetric, conservative
    uncertainty band and a qualitative confidence label.

    No captures at all (``total_records == 0``) ⇒ no saturation signal ⇒ a ``NONE`` band at zero.
    Note ``distinct == 0`` with ``total_records > 0`` is the *opposite* — every record was a re-find
    (``marginal_yield == 0``), the maximal-saturation case the occupancy model maps near the
    ceiling, not a no-signal case. Otherwise the point is the occupancy estimate; the half-width
    shrinks with
    the captures and widens for a cut-off stop; the band leans **down** (the model over-states
    coverage under non-uniform channel sampling), so the downside is wider than the upside."""
    if total_records <= 0:
        return CoverageBand(low=0.0, high=0.0, point=0.0, confidence=CoverageConfidence.NONE)

    # The point is capped below 1.0 (config.coverage_ceiling): open-ended discovery can never prove
    # completeness (Doc C §7), so the estimate structurally never claims "we found them all".
    point = min(saturation_coverage(marginal_yield), config.coverage_ceiling)
    sampling = config.band_width_scale / math.sqrt(total_records)
    half = min(max(sampling, config.band_width_min), config.band_width_max)
    half += config.stopping_penalty(stopping_reason)
    low = _clamp_unit(point - config.downside_multiple * half)
    high = min(_clamp_unit(point + config.upside_multiple * half), config.coverage_ceiling)
    point = _clamp_unit(point)

    saturated = stopping_reason is StoppingReason.MARGINAL_YIELD  # only the yield rule = saturation
    still_productive = marginal_yield >= config.productive_yield_threshold
    if not saturated and still_productive:
        confidence = (
            CoverageConfidence.LOW
        )  # cut off (budget / round / query-plan) while productive
    elif saturated and point >= config.high_coverage_threshold:
        confidence = CoverageConfidence.HIGH  # genuinely saturated, high coverage
    else:
        confidence = CoverageConfidence.MODERATE
    return CoverageBand(low=low, high=max(high, point), point=point, confidence=confidence)


def _recommendation(
    *,
    stopping_reason: StoppingReason,
    marginal_yield: float,
    distinct: int,
    unsearched: Sequence[UnsearchedChannel],
    geo_gaps: Sequence[str],
    config: CoverageConfig,
) -> str | None:
    """The single, actionable next step — never an over-claim, always a path to *more* coverage."""
    still_productive = distinct > 0 and marginal_yield >= config.productive_yield_threshold
    if stopping_reason is StoppingReason.BUDGET_CAP and still_productive:
        pct = round(marginal_yield * 100)
        return (
            f"The run stopped at the discovery budget cap while still finding new candidates "
            f"(~{pct}% of records were new); raise the budget to search further."
        )
    if stopping_reason is StoppingReason.EXHAUSTED and still_productive:
        pct = round(marginal_yield * 100)
        return (
            f"The planned query set ran out while still finding new candidates (~{pct}% of records "
            f"were new); widen the discovery query plan or add channels to search further."
        )
    if stopping_reason is StoppingReason.ROUND_CAP:
        return (
            "The run hit the round-count backstop with work still queued; review the discovery "
            "config (window size / per-query limits) before relying on this coverage estimate."
        )
    parts: list[str] = []
    if unsearched:
        parts.append(
            f"expand to the {len(unsearched)} unsearched account-scope channel(s) to widen coverage"
        )
    if geo_gaps:
        parts.append(
            f"add a channel covering the uncovered target geo(s): {', '.join(sorted(geo_gaps))}"
        )
    return ("To find more, " + "; ".join(parts) + ".") if parts else None


def _framing(
    *,
    band: CoverageBand,
    searched_count: int,
    unsearched_count: int,
    geo_gaps: Sequence[str],
    total_records: int,
    distinct: int,
) -> str:
    """The one-line, completeness-free statement (Doc C §7 wording rule): an *estimate over the
    channels searched* + named gaps — never "we found them all". Distinguishes *no captures*
    (``total_records == 0`` — no signal) from *captures but no new candidates* (``distinct == 0`` —
    every record a re-find, a strong saturation signal), so it never falsely claims "no records
    returned" when records were returned."""
    if total_records <= 0 or band.confidence is CoverageConfidence.NONE:
        return (
            f"No candidate records were returned by the {searched_count} channel(s) searched, so "
            f"no coverage can be estimated; {unsearched_count} account-scope channel(s) in the "
            "registry were not searched."
        )
    geo_clause = (
        f", and {len(geo_gaps)} target geo(s) are not covered by any searched channel"
        if geo_gaps
        else ""
    )
    if distinct <= 0:
        return (
            f"Estimated {band.as_percent()} of the addressable account set found via the "
            f"{searched_count} channel(s) searched: this run returned {total_records} record(s) "
            "but 0 new candidates (every record matched an already-known account — a strong "
            "saturation signal). An estimate over the channels searched, not a completeness "
            "guarantee; "
            f"{unsearched_count} account-scope channel(s) in the registry were not "
            f"searched{geo_clause}."
        )
    return (
        f"Estimated {band.as_percent()} of the addressable account set found via the "
        f"{searched_count} channel(s) searched. This is an estimate over the channels searched, "
        f"not a completeness guarantee; {unsearched_count} account-scope channel(s) in the "
        f"registry were not searched{geo_clause}."
    )


def estimate_coverage(
    *,
    run_id: RunId,
    observations: Sequence[ChannelObservation],
    stopping_reason: StoppingReason,
    universe: Sequence[UnsearchedChannel],
    icp_geos: Sequence[str] = (),
    admitted: int | None = None,
    needs_review: int | None = None,
    rejected: int | None = None,
    config: CoverageConfig = DEFAULT_COVERAGE_CONFIG,
) -> CoverageReport:
    """Estimate coverage for a stopped discovery run — the pure, swappable estimation core.

    ``observations`` are the per-channel yield counters (in search order); ``universe`` is the full
    set of account-scope channels the registry could cover (each a ``(source_key, tier,
    geo_coverage)`` triple); ``icp_geos`` are the ICP's target region codes (empty ⇒ no geo
    constraint). Returns a :class:`CoverageReport` whose band is a *band* (never a point), whose
    ``channels_not_searched`` is the geo-applicable universe minus the channels queried, and whose
    ``stopping_reason`` lets the client read *why* the run stopped. Deterministic for fixed inputs;
    writes nothing."""
    by_key, total_records, distinct = _aggregate(observations)
    searched = tuple(by_key.keys())
    searched_set = frozenset(searched)
    # Normalised target geos for comparison, mapped back to the ICP's original casing for display.
    geo_norms = frozenset(_norm_geo(g) for g in icp_geos)
    geo_display: dict[str, str] = {}
    for g in icp_geos:
        geo_display.setdefault(_norm_geo(g), g)

    marginal_yield = distinct / total_records if total_records > 0 else 0.0
    band = _band(
        distinct=distinct,
        total_records=total_records,
        marginal_yield=marginal_yield,
        stopping_reason=stopping_reason,
        config=config,
    )

    # Unsearched = the geo-applicable account-scope universe minus what was queried this run.
    not_searched = tuple(
        sorted(
            (
                c
                for c in universe
                if c.source_key not in searched_set and _geo_applicable(c, geo_norms)
            ),
            key=lambda c: c.source_key,
        )
    )
    # Geo gaps = target geos no *registry-known searched* channel covers. We can only name a gap
    # from positive geo knowledge: a searched channel absent from the registry has UNKNOWN geo and
    # might cover anything, so with *zero* registry-known searched channels we name no gap (Doc C §7
    # — never fabricate one; a fully unseeded registry then yields no spurious gap + no "add a
    # channel" advice contradicting the searched channels). A global known channel covers all geos.
    universe_by_key = {c.source_key: c for c in universe}
    known_searched = [universe_by_key[key] for key in searched if key in universe_by_key]
    geo_gaps: tuple[str, ...] = ()
    if geo_norms and known_searched:
        covered: set[str] = set()
        for channel in known_searched:
            if not channel.geo_coverage:
                covered |= geo_norms
            else:
                covered |= {_norm_geo(g) for g in channel.geo_coverage if _norm_geo(g) in geo_norms}
        geo_gaps = tuple(sorted(geo_display[n] for n in geo_norms if n not in covered))

    recommendation = _recommendation(
        stopping_reason=stopping_reason,
        marginal_yield=marginal_yield,
        distinct=distinct,
        unsearched=not_searched,
        geo_gaps=geo_gaps,
        config=config,
    )
    framing = _framing(
        band=band,
        searched_count=len(searched),
        unsearched_count=len(not_searched),
        geo_gaps=geo_gaps,
        total_records=total_records,
        distinct=distinct,
    )
    return CoverageReport(
        run_id=run_id,
        coverage_estimate_band=band,
        channels_searched=searched,
        channels_not_searched=not_searched,
        per_channel_new_candidate_curve=_curve(by_key),
        stopping_reason=stopping_reason,
        total_records=total_records,
        distinct_candidates=distinct,
        admitted=admitted,
        needs_review=needs_review,
        rejected=rejected,
        geo_gaps=geo_gaps,
        recommendation=recommendation,
        framing=framing,
    )


__all__ = ["estimate_coverage", "saturation_coverage"]
