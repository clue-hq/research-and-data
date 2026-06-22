"""M0.5 acceptance: reserved span names — judge vs use-gate distinct, phases match Doc C §4."""

from __future__ import annotations

import pytest

from clue_research.obs import (
    CAMPAIGN_PHASES,
    SPAN_COMPLIANCE_USE_GATE,
    SPAN_VERIFICATION_CORROBORATION,
    SPAN_VERIFICATION_FAITHFULNESS_JUDGE,
    SPAN_VERIFICATION_FRESHNESS,
    SPAN_VERIFICATION_PRE_SPEND_GATE,
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


def test_five_verification_spans_distinct_and_namespaced() -> None:
    # M9 emits five accuracy/identity spans (pre-spend gate, corroboration, faithfulness judge,
    # identity-binding, freshness); each is distinct and lives under the verification.* namespace,
    # and none collides with the M10 appropriateness/use gate (Doc D §5).
    names = {
        SPAN_VERIFICATION_PRE_SPEND_GATE,
        SPAN_VERIFICATION_CORROBORATION,
        SPAN_VERIFICATION_FAITHFULNESS_JUDGE,
        SPAN_VERIFICATION_IDENTITY_BINDING,
        SPAN_VERIFICATION_FRESHNESS,
    }
    assert len(names) == 5
    assert all(name.startswith("verification.") for name in names)
    assert SPAN_COMPLIANCE_USE_GATE not in names


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
