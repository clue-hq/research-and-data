"""M0.5 acceptance: metric emitters increment correctly from claim provenance."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from clue_core import (
    Claim,
    ExtractionMethod,
    IdentityBinding,
    VerificationStatus,
)
from clue_research.obs import (
    METRIC_CLAIMS_SURVIVING,
    METRIC_CLAIMS_TOTAL,
    METRIC_CONTACT_CLAIMS_TOTAL,
    METRIC_CONTACT_STRONG_BINDING,
    METRIC_COST_CAP_CENTS,
    METRIC_COST_CENTS,
    METRIC_PHASE_PROGRESS,
    METRIC_TIER4_PASSED,
    METRIC_TIER4_TOTAL,
    InMemorySink,
    record_cost_burndown,
    record_phase_progress,
    record_source_yield,
    record_verification_health,
)


def _verified(claim: Claim) -> Claim:
    return claim.model_copy(update={"verification_status": VerificationStatus.VERIFIED})


def test_source_yield_counts_surviving_by_source(make_account: Callable[..., Claim]) -> None:
    sink = InMemorySink()
    claims = [
        _verified(make_account(source_url="https://a")),
        make_account(source_url="https://a"),  # unverified -> does not survive
        _verified(make_account(source_url="https://b")),
    ]
    record_source_yield(claims, sink=sink)
    assert sink.counter(METRIC_CLAIMS_TOTAL, source="https://a") == 2
    assert sink.counter(METRIC_CLAIMS_SURVIVING, source="https://a") == 1
    assert sink.counter(METRIC_CLAIMS_TOTAL, source="https://b") == 1
    assert sink.counter(METRIC_CLAIMS_SURVIVING, source="https://b") == 1


def test_verification_health(
    make_account: Callable[..., Claim], make_contact: Callable[..., Claim]
) -> None:
    sink = InMemorySink()
    claims = [
        _verified(
            make_account(
                source_tier=4, extraction_method=ExtractionMethod.LLM_SYNTHESIS, evidence_span="x"
            )
        ),
        make_account(
            source_tier=4, extraction_method=ExtractionMethod.LLM_SYNTHESIS, evidence_span="y"
        ),  # tier-4, judge not passed
        make_contact(identity_binding=IdentityBinding.STRONG),
        make_contact(identity_binding=IdentityBinding.WEAK),
    ]
    record_verification_health(claims, sink=sink)
    assert sink.counter(METRIC_TIER4_TOTAL) == 2
    assert sink.counter(METRIC_TIER4_PASSED) == 1
    assert sink.counter(METRIC_CONTACT_CLAIMS_TOTAL) == 2
    assert sink.counter(METRIC_CONTACT_STRONG_BINDING) == 1


def test_cost_burndown_sums_exactly(make_account: Callable[..., Claim]) -> None:
    sink = InMemorySink()
    claims = [make_account(cost_cents=Decimal("1.5")), make_account(cost_cents=Decimal("2.0"))]
    record_cost_burndown(claims, cap_cents=Decimal("100"), sink=sink)
    assert sink.gauge_value(METRIC_COST_CENTS) == 3.5
    assert sink.gauge_value(METRIC_COST_CAP_CENTS) == 100.0


def test_phase_progress(make_account: Callable[..., Claim]) -> None:
    sink = InMemorySink()
    record_phase_progress("discovery", completed=3, total=10, sink=sink)
    assert sink.gauge_value(METRIC_PHASE_PROGRESS, phase="discovery") == 0.3
    with pytest.raises(ValueError, match="unknown campaign phase"):
        record_phase_progress("not_a_phase", completed=1, total=2, sink=sink)
