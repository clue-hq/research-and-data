"""M6.5 (ENG-150) — the pure coverage-confidence estimator (no DB).

One test per acceptance criterion of the estimation core: a coverage **band** (never a point),
deterministic for fixed inputs; the saturation model monotonic in redundancy and *capped below
completeness*; the budget-cap-high-yield vs marginal-yield-exhausted confidence distinction; the
unsearched-channels diff (universe − searched, geo-filtered) + named geo gaps; and the Doc C §7
wording rule (an estimate *over the channels searched*, never "we found them all").
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_research.core import RunId
from clue_research.discovery_scoring import (
    DEFAULT_COVERAGE_CONFIG,
    ChannelObservation,
    CoverageConfidence,
    CoverageConfig,
    StoppingReason,
    UnsearchedChannel,
    estimate_coverage,
    saturation_coverage,
)

_RUN = RunId(UUID(int=0xC0FFEE))

# Over-claiming phrases the framing must never contain — coverage is "confidence, not a completeness
# guarantee" (note the honest negation legitimately uses "completeness"/"guarantee", so the banned
# set is the *assertions of completeness*, not those substrings).
_COMPLETENESS_WORDS = (
    "exhaustive",
    "all accounts",
    "every account",
    "found them all",
    "fully covered",
    "100% of",
)


def _obs(key: str, returned: int, new: int, *, errors: int = 0) -> ChannelObservation:
    return ChannelObservation(
        source_key=key, records_returned=returned, new_candidates=new, errors=errors
    )


def _chan(key: str, *, tier: int = 2, geo: tuple[str, ...] = ()) -> UnsearchedChannel:
    return UnsearchedChannel(source_key=key, tier=tier, geo_coverage=geo)


def _estimate(
    observations: list[ChannelObservation],
    *,
    stopping_reason: StoppingReason = StoppingReason.MARGINAL_YIELD,
    universe: list[UnsearchedChannel] | None = None,
    icp_geos: tuple[str, ...] = (),
    config: CoverageConfig = DEFAULT_COVERAGE_CONFIG,
    **counts: int,
):
    return estimate_coverage(
        run_id=_RUN,
        observations=observations,
        stopping_reason=stopping_reason,
        universe=universe or [],
        icp_geos=icp_geos,
        config=config,
        **counts,
    )


# --- AC1: a band, not a point; deterministic --------------------------------
def test_estimate_returns_a_band_not_a_point() -> None:
    report = _estimate([_obs("exa", 100, 40)])
    band = report.coverage_estimate_band
    assert 0.0 <= band.low <= band.point <= band.high <= 1.0
    assert band.low < band.high  # a genuine band, never a single false-precise number
    assert "–" in band.as_percent() or band.as_percent().endswith("%")
    assert band.method  # the swappable-method tag is present


def test_estimate_is_deterministic_for_fixed_inputs() -> None:
    obs = [_obs("exa", 120, 30), _obs("apollo", 80, 10)]
    a = _estimate(obs, universe=[_chan("clay")])
    b = _estimate(obs, universe=[_chan("clay")])
    assert a.model_dump() == b.model_dump()


# --- the saturation model: monotonic, bounded, capped below completeness -----
def test_saturation_coverage_edges_and_monotonicity() -> None:
    assert saturation_coverage(1.0) == 0.0  # no redundancy → no saturation evidence
    assert saturation_coverage(0.0) == 1.0  # fully saturated (degenerate)
    # strictly decreasing in the marginal yield (more redundancy ⇒ higher coverage)
    samples = [saturation_coverage(m / 10) for m in range(1, 10)]
    assert samples == sorted(samples, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in samples)


def test_more_redundancy_yields_higher_coverage_point() -> None:
    low_dup = _estimate([_obs("exa", 100, 80)])  # m = 0.8 (mostly new)
    high_dup = _estimate([_obs("exa", 100, 10)])  # m = 0.1 (mostly re-finds)
    assert high_dup.coverage_estimate_band.point > low_dup.coverage_estimate_band.point


def test_band_never_asserts_completeness() -> None:
    # Even with overwhelming redundancy (m = 0.01), the estimate is capped below 1.0.
    report = _estimate([_obs("exa", 1000, 10)], universe=[_chan("apollo")])
    band = report.coverage_estimate_band
    assert band.high <= DEFAULT_COVERAGE_CONFIG.coverage_ceiling < 1.0
    assert band.point < 1.0
    assert "100%" not in band.as_percent()
    framing = report.framing.lower()
    assert "estimate over the channels searched" in framing
    assert "not a completeness guarantee" in framing
    assert not any(word in framing for word in _COMPLETENESS_WORDS)


# --- AC3: budget-cap-high-yield (low confidence) vs saturated (higher) -------
def test_budget_cap_with_high_yield_is_low_confidence() -> None:
    report = _estimate(
        [_obs("exa", 100, 70)],  # still finding 70% new when the cap hit
        stopping_reason=StoppingReason.BUDGET_CAP,
    )
    assert report.coverage_estimate_band.confidence is CoverageConfidence.LOW
    assert report.recommendation is not None and "budget" in report.recommendation.lower()


def test_marginal_yield_exhausted_is_higher_confidence_than_budget_cut() -> None:
    saturated = _estimate(
        [_obs("exa", 400, 20)],  # 5% new → genuinely saturated
        stopping_reason=StoppingReason.MARGINAL_YIELD,
    )
    budget_cut = _estimate(
        [_obs("exa", 100, 70)],
        stopping_reason=StoppingReason.BUDGET_CAP,
    )
    assert saturated.coverage_estimate_band.confidence is CoverageConfidence.HIGH
    # the two stops are read differently — the whole point of surfacing stopping_reason
    assert (
        saturated.coverage_estimate_band.confidence
        is not budget_cut.coverage_estimate_band.confidence
    )
    assert saturated.stopping_reason is StoppingReason.MARGINAL_YIELD


def test_round_cap_recommends_reviewing_config() -> None:
    report = _estimate([_obs("exa", 50, 40)], stopping_reason=StoppingReason.ROUND_CAP)
    assert report.recommendation is not None
    assert "config" in report.recommendation.lower()


# --- AC2: unsearched-channels diff = universe − searched, geo-filtered -------
def test_unsearched_is_universe_minus_searched() -> None:
    report = _estimate(
        [_obs("exa", 50, 25)],
        universe=[_chan("exa"), _chan("apollo"), _chan("clay")],
    )
    assert report.channels_searched == ("exa",)
    assert tuple(c.source_key for c in report.channels_not_searched) == ("apollo", "clay")


def test_unsearched_excludes_geo_inapplicable_channels() -> None:
    report = _estimate(
        [_obs("exa", 50, 25)],
        universe=[
            _chan("apollo"),  # global (no geo) → applicable
            _chan("jp_directory", geo=("JP",)),  # JP-only → not applicable to a US ICP
            _chan("us_directory", geo=("US",)),  # US → applicable
        ],
        icp_geos=("US",),
    )
    not_searched = {c.source_key for c in report.channels_not_searched}
    assert not_searched == {"apollo", "us_directory"}  # the JP-only channel is filtered out


def test_geo_gaps_are_named() -> None:
    report = _estimate(
        [_obs("exa", 50, 25)],
        universe=[_chan("exa", geo=("US",)), _chan("apollo", geo=("DE",))],
        icp_geos=("US", "DE"),
    )
    # the only searched channel covers US; DE is uncovered by any searched channel
    assert report.geo_gaps == ("DE",)
    assert "geo" in report.framing.lower()


def test_global_searched_channel_covers_all_geos() -> None:
    report = _estimate(
        [_obs("exa", 50, 25)],
        universe=[_chan("exa")],  # global searched channel
        icp_geos=("US", "DE", "FR"),
    )
    assert report.geo_gaps == ()  # a global channel covers every target geo


# --- AC4 wording rule + the empty run ---------------------------------------
def test_found_nothing_is_none_confidence() -> None:
    report = _estimate(
        [_obs("exa", 0, 0)],
        stopping_reason=StoppingReason.EXHAUSTED,
        universe=[_chan("apollo")],
    )
    band = report.coverage_estimate_band
    assert band.confidence is CoverageConfidence.NONE
    assert band.low == band.high == band.point == 0.0
    assert "no coverage can be estimated" in report.framing.lower()
    assert report.distinct_candidates == 0


# --- the curve + the counts -------------------------------------------------
def test_curve_reflects_per_channel_yield_in_order() -> None:
    report = _estimate([_obs("b_chan", 40, 10), _obs("a_chan", 60, 30)])
    curve = report.per_channel_new_candidate_curve
    assert tuple(p.source_key for p in curve) == ("b_chan", "a_chan")  # input (search) order kept
    first = curve[0]
    assert first.records_returned == 40 and first.new_candidates == 10
    assert first.redundant == 30  # 40 - 10
    assert abs(first.marginal_yield - 0.25) < 1e-9
    assert report.total_records == 100 and report.distinct_candidates == 40


def test_admitted_counts_are_threaded_through() -> None:
    report = _estimate([_obs("exa", 100, 40)], admitted=30, needs_review=5, rejected=5)
    assert report.admitted == 30 and report.needs_review == 5 and report.rejected == 5


def test_new_candidates_clamped_to_records_returned() -> None:
    # A malformed counter (new > returned) cannot inflate the found set past the records seen.
    report = _estimate([_obs("exa", 5, 10)])
    assert report.distinct_candidates == 5
    assert report.per_channel_new_candidate_curve[0].marginal_yield <= 1.0


def test_duplicate_observations_for_one_source_are_aggregated() -> None:
    report = _estimate([_obs("exa", 50, 20), _obs("exa", 30, 5)])
    assert report.channels_searched == ("exa",)
    assert len(report.per_channel_new_candidate_curve) == 1
    point = report.per_channel_new_candidate_curve[0]
    assert point.records_returned == 80 and point.new_candidates == 25


def test_coverage_ceiling_is_config_driven() -> None:
    strict = CoverageConfig(coverage_ceiling=0.8)
    report = _estimate([_obs("exa", 1000, 10)], config=strict)
    assert report.coverage_estimate_band.high <= 0.8


# --- audit fixes: EXHAUSTED semantics, distinct=0, geo unseeded/case, ceiling --
def test_exhausted_with_high_yield_is_low_confidence_and_recommends_widening() -> None:
    # EXHAUSTED = the planned query set drained; finding new candidates while it drains is a
    # low-coverage "widen the plan" situation, NOT genuine saturation (only MARGINAL_YIELD is).
    report = _estimate([_obs("exa", 100, 70)], stopping_reason=StoppingReason.EXHAUSTED)
    assert report.coverage_estimate_band.confidence is CoverageConfidence.LOW
    assert report.recommendation is not None
    rec = report.recommendation.lower()
    assert "widen" in rec or "query plan" in rec


def test_records_returned_but_zero_new_is_max_saturation_not_none() -> None:
    # Every record a re-find (records>0, distinct=0) = maximal saturation, never "no records".
    report = _estimate([_obs("exa", 200, 0)], stopping_reason=StoppingReason.MARGINAL_YIELD)
    band = report.coverage_estimate_band
    assert band.confidence is not CoverageConfidence.NONE
    assert band.point > 0.0  # maximal saturation, not zero
    assert report.distinct_candidates == 0 and report.total_records == 200
    framing = report.framing.lower()
    assert "no candidate records were returned" not in framing  # not a false claim
    assert "0 new candidates" in framing


def test_zero_captures_is_none_with_no_records_framing() -> None:
    report = _estimate([_obs("exa", 0, 0)], stopping_reason=StoppingReason.EXHAUSTED)
    assert report.coverage_estimate_band.confidence is CoverageConfidence.NONE
    assert "no candidate records were returned" in report.framing.lower()


def test_geo_gaps_suppressed_when_no_searched_channel_is_registry_known() -> None:
    # Unseeded/partial registry: the searched channel is absent from the universe → its geo is
    # UNKNOWN, so we must not fabricate a geo gap (Doc C §7) nor advise "add a channel for US".
    report = _estimate([_obs("exa", 100, 30)], universe=[], icp_geos=("US",))
    assert report.geo_gaps == ()
    assert report.recommendation is None or "geo" not in report.recommendation.lower()


def test_geo_matching_is_case_insensitive() -> None:
    # ICP supplies 'us'/'de' (free-form), registry stores 'US'/'DE' — they must still match.
    report = _estimate(
        [_obs("exa", 50, 25)],
        universe=[_chan("exa", geo=("US",)), _chan("apollo", geo=("DE",))],
        icp_geos=("us", "de"),
    )
    # exa (searched) covers US → US not a gap; DE uncovered by any searched channel → DE is the gap,
    # rendered in the ICP's original casing ('de'); apollo (DE, unsearched, applicable) is listed.
    assert report.geo_gaps == ("de",)
    assert {c.source_key for c in report.channels_not_searched} == {"apollo"}


def test_no_config_can_render_one_hundred_percent() -> None:
    # ceiling is strictly < 1.0 by the type, so completeness can never be asserted by a config swap.
    # (the constraint le=0.99 means even the max ceiling renders 99%, never 100%)
    with pytest.raises(ValidationError):
        CoverageConfig(coverage_ceiling=1.0)
    at_max = CoverageConfig(coverage_ceiling=0.99)
    report = _estimate([_obs("exa", 5000, 5)], config=at_max)  # extreme saturation
    assert "100%" not in report.coverage_estimate_band.as_percent()
    assert report.coverage_estimate_band.high < 1.0
