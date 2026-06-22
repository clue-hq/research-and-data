"""M8.3 committee coverage confidence (pure — no DB).

Coverage is a trust statement, not a completeness guarantee: a band + the named unsearched
people-channels, never an exhaustiveness claim (Doc C §7).
"""

from __future__ import annotations

from clue_research.profiling.committee.coverage import (
    CommitteeCoverageConfidence,
    estimate_committee_coverage,
)
from clue_research.profiling.committee.stopping import CommitteeStopReason


def test_no_admits_is_none_confidence() -> None:
    cov = estimate_committee_coverage(
        channels_searched=["apollo_people"],
        all_channels=["apollo_people", "team_page"],
        stopping_reason=CommitteeStopReason.EXHAUSTED,
        candidates_seen=0,
        admitted=0,
    )
    assert cov.confidence is CommitteeCoverageConfidence.NONE
    assert cov.estimate_point == 0.0
    assert "team_page" in cov.channels_not_searched


def test_names_unsearched_channels_and_never_claims_exhaustive() -> None:
    cov = estimate_committee_coverage(
        channels_searched=["apollo_people"],
        all_channels=["apollo_people", "zoominfo_people", "team_page"],
        stopping_reason=CommitteeStopReason.MARGINAL_YIELD,
        candidates_seen=10,
        admitted=4,
    )
    assert set(cov.channels_not_searched) == {"zoominfo_people", "team_page"}
    assert cov.estimate_high <= 1.0
    assert cov.estimate_point < 1.0  # never claims it found the whole committee
    assert "not a completeness guarantee" in cov.framing
    # saturated but channels still unsearched → MODERATE (not HIGH).
    assert cov.confidence is CommitteeCoverageConfidence.MODERATE


def test_budget_cut_off_is_low_confidence() -> None:
    cov = estimate_committee_coverage(
        channels_searched=["apollo_people"],
        all_channels=["apollo_people", "team_page"],
        stopping_reason=CommitteeStopReason.BUDGET_CAP,
        candidates_seen=8,
        admitted=5,
    )
    assert cov.confidence is CommitteeCoverageConfidence.LOW


def test_saturated_with_no_unsearched_is_high() -> None:
    cov = estimate_committee_coverage(
        channels_searched=["apollo_people", "team_page"],
        all_channels=["apollo_people", "team_page"],
        stopping_reason=CommitteeStopReason.MARGINAL_YIELD,
        candidates_seen=20,
        admitted=4,  # low marginal yield → saturated
    )
    assert cov.confidence is CommitteeCoverageConfidence.HIGH
    assert cov.channels_not_searched == ()


def test_band_brackets_point() -> None:
    cov = estimate_committee_coverage(
        channels_searched=["apollo_people"],
        all_channels=["apollo_people"],
        stopping_reason=CommitteeStopReason.EXHAUSTED,
        candidates_seen=6,
        admitted=3,
    )
    assert cov.estimate_low <= cov.estimate_point <= cov.estimate_high
    assert cov.estimate_low >= 0.0 and cov.estimate_high <= 1.0
    # exhausted the (single) channel universe → MODERATE (bounded by which channels exist).
    assert cov.confidence is CommitteeCoverageConfidence.MODERATE
