"""M11.3 acceptance — the per-field tier-4 verification-health surface (Doc C §6; hermetic, no DB).

Proves the metric the M11.3 spec names — share of tier-4 claims passing the faithfulness judge,
**per field** — is emitted with a ``field_key`` dimension and that summing across fields recovers
the aggregate, so M13.4 / the M4.6 learning loop can read a per-field pass-rate.
"""

from __future__ import annotations

from clue_core import (
    Claim,
    ExtractionMethod,
    ResearchMode,
    VerificationStatus,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.obs.metrics import METRIC_TIER4_PASSED, METRIC_TIER4_TOTAL, InMemorySink
from clue_research.synthesis import record_synthesis_health

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"


def _claim(
    *,
    key: str = _PAIN,
    tier: int = 4,
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> Claim:
    method = ExtractionMethod.LLM_SYNTHESIS if tier == 4 else ExtractionMethod.SCRAPE
    claim = account_claim(
        entity_id=new_entity_id(),
        field_key=key,
        value_json="a synthesized value about Acme Corp",
        source_tier=tier,
        extraction_method=method,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://acme.com/eng",
        evidence_span="about Acme Corp",
    )
    if status is not VerificationStatus.UNVERIFIED:
        claim = claim.model_copy(update={"verification_status": status})
    return claim


def test_record_synthesis_health_emits_per_field_pass_rate() -> None:
    sink = InMemorySink()
    claims = [
        _claim(key=_PAIN, status=VerificationStatus.VERIFIED),
        _claim(key=_PAIN, status=VerificationStatus.REJECTED),
        _claim(key=_PAIN, status=VerificationStatus.UNVERIFIED),
        _claim(key=_MOVES, status=VerificationStatus.VERIFIED),
    ]
    record_synthesis_health(claims, sink=sink)

    # operational_pain: 3 tier-4 claims, 1 verified => 1/3
    assert sink.counter(METRIC_TIER4_TOTAL, field_key=_PAIN) == 3
    assert sink.counter(METRIC_TIER4_PASSED, field_key=_PAIN) == 1
    # strategic_moves: 1 tier-4 claim, 1 verified => 1/1
    assert sink.counter(METRIC_TIER4_TOTAL, field_key=_MOVES) == 1
    assert sink.counter(METRIC_TIER4_PASSED, field_key=_MOVES) == 1


def test_record_synthesis_health_skips_non_tier4_claims() -> None:
    sink = InMemorySink()
    record_synthesis_health([_claim(tier=3, status=VerificationStatus.VERIFIED)], sink=sink)
    # a tier-3 claim contributes to no tier-4 counter (the judge governs only tier-4 synthesis)
    assert sink.counter(METRIC_TIER4_TOTAL, field_key=_PAIN) == 0
    assert sink.counter(METRIC_TIER4_PASSED, field_key=_PAIN) == 0


def test_per_field_counters_sum_to_the_aggregate() -> None:
    sink = InMemorySink()
    claims = [
        _claim(key=_PAIN, status=VerificationStatus.VERIFIED),
        _claim(key=_MOVES, status=VerificationStatus.VERIFIED),
        _claim(key=_MOVES, status=VerificationStatus.REJECTED),
    ]
    record_synthesis_health(claims, sink=sink)
    total = sink.counter(METRIC_TIER4_TOTAL, field_key=_PAIN) + sink.counter(
        METRIC_TIER4_TOTAL, field_key=_MOVES
    )
    passed = sink.counter(METRIC_TIER4_PASSED, field_key=_PAIN) + sink.counter(
        METRIC_TIER4_PASSED, field_key=_MOVES
    )
    assert total == 3 and passed == 2  # summing field_key recovers the aggregate
