"""M0.5 acceptance: reserved span names — judge vs use-gate distinct, phases match Doc C §4."""

from __future__ import annotations

import pytest

from clue_research.obs import (
    CAMPAIGN_PHASES,
    SPAN_COMPLIANCE_USE_GATE,
    SPAN_VERIFICATION_FAITHFULNESS_JUDGE,
    phase_span,
    resolve_span,
)
from clue_research.obs.spans import SPAN_VERIFICATION_IDENTITY_BINDING


def test_faithfulness_judge_and_use_gate_are_distinct_spans() -> None:
    # accuracy (judge) and appropriateness (use gate) must be separately measurable — Doc D §5
    names = {
        SPAN_VERIFICATION_FAITHFULNESS_JUDGE,
        SPAN_COMPLIANCE_USE_GATE,
        SPAN_VERIFICATION_IDENTITY_BINDING,
    }
    assert len(names) == 3
    assert SPAN_VERIFICATION_FAITHFULNESS_JUDGE != SPAN_COMPLIANCE_USE_GATE


def test_campaign_phases_match_doc_c_section_4_exactly() -> None:
    assert CAMPAIGN_PHASES == (
        "reverse_profiling",
        "icp_confirmed",
        "discovery",
        "scoring",
        "tier_checkpoint",
        "deep",
        "verification",
        "handoff",
    )


def test_phase_span_builds_and_validates() -> None:
    assert phase_span("discovery") == "campaign.phase.discovery"
    assert phase_span("handoff") == "campaign.phase.handoff"
    with pytest.raises(ValueError, match="unknown campaign phase"):
        phase_span("not_a_phase")


def test_resolve_span() -> None:
    assert resolve_span("apollo") == "resolve.apollo"
