"""M8.3 committee people-source seam (pure — no DB).

The candidate model is grounded by construction (anti-fabrication), exposes the strong-key gate
predicate, and the source ordering honors the planner order then trust tier.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_research.profiling.committee.sources import (
    CommitteePersonCandidate,
    order_committee_sources,
)

from ..conftest import FakeCommitteeSource, make_candidate


def test_candidate_requires_grounding() -> None:
    # No strong key AND no source_url → a pure fabrication → rejected at construction.
    with pytest.raises(ValidationError):
        CommitteePersonCandidate(source_key="apollo_people", full_name="Jane Doe", title="CTO")


def test_candidate_grounded_by_strong_key_or_source_url() -> None:
    assert make_candidate(linkedin_url="https://linkedin.com/in/jane").has_strong_key
    assert make_candidate(verified_email="jane@acme.example").has_strong_key
    # source_url alone grounds the record but is NOT a strong key (will be dropped at the gate).
    only_url = make_candidate(source_url="https://acme.example/team", full_name="Jane")
    assert only_url.has_strong_key is False


def test_has_strong_key_ignores_blank() -> None:
    assert make_candidate(linkedin_url="   ", source_url="https://x").has_strong_key is False


def test_order_uses_plan_then_tier() -> None:
    a = FakeCommitteeSource(source_key="apollo_people", tier=2)
    z = FakeCommitteeSource(source_key="zoominfo_people", tier=3)
    page = FakeCommitteeSource(source_key="team_page", tier=2)
    ordered = order_committee_sources([a, z, page], plan=["team_page", "apollo_people"])
    keys = [s.source_key for s in ordered]
    # plan order first (team_page, apollo_people), then the remaining by tier (zoominfo tier 3).
    assert keys == ["team_page", "apollo_people", "zoominfo_people"]


def test_order_without_plan_is_tier_order() -> None:
    a = FakeCommitteeSource(source_key="apollo_people", tier=3)
    page = FakeCommitteeSource(source_key="team_page", tier=1)
    ordered = order_committee_sources([a, page])
    assert [s.source_key for s in ordered] == ["team_page", "apollo_people"]
