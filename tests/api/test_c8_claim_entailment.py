"""PC-C8 §6c-b — the contract of the M9.3-backed ``ClaimEntailmentJudge`` implementation.

No live model call: a real judgment is an LLM round trip and does not belong in this suite. What is
pinned here is everything the wrapper itself owns — the claim it builds for the judge, the
content-addressed judgment identity that makes repair possible, the verdict→admission mapping, and
the deliberate distinction between "the words do not support it" and "we could not ask".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import JsonValue

from clue_api.claim_entailment import (
    ENTAILMENT_JUDGMENT_NAMESPACE,
    FaithfulnessClaimEntailmentJudge,
    entailment_judgment_id,
)
from clue_core import (
    Claim,
    EntityId,
    ExtractionMethod,
    JudgeResult,
    JudgeVerdict,
    new_entity_id,
)
from clue_research.stage0 import ClaimEntailment, ClaimEntailmentJudge
from tests.db.conftest import run_async

_QUOTE = "We are fully HIPAA compliant, and every deployment is BAA-backed."
_FIELD = "client.hipaa_compliant"


@dataclass
class _FakeJudge:
    """A ``FaithfulnessJudge`` that records the claim it was handed and returns a fixed verdict."""

    verdict: JudgeVerdict = JudgeVerdict.SUPPORTED
    score: float = 0.95
    error: Exception | None = None
    seen: list[Claim] = field(default_factory=list)

    async def judge(self, claim: Claim) -> JudgeResult:
        self.seen.append(claim)
        if self.error is not None:
            raise self.error
        return JudgeResult(
            claim_id=claim.id,
            verdict=self.verdict,
            score=self.score,
            rationale="fixed",
            judge_model="test/judge",
            cost_cents=Decimal(0),
        )


def _entails(judge: _FakeJudge, *, value: JsonValue = True, quote: str = _QUOTE) -> ClaimEntailment:
    wrapper: ClaimEntailmentJudge = FaithfulnessClaimEntailmentJudge(judge=judge)
    return run_async(
        wrapper.entails(
            entity_id=EntityId(new_entity_id()),
            field_key=_FIELD,
            value=value,
            quote=quote,
        )
    )


def test_the_judgment_id_is_content_addressed_and_never_a_claim_id() -> None:
    """The repair guarantee: a different value or span is a different cached question.

    An interview claim's id is ``uuid5(onboarding_input, entity, field_key)`` — it carries neither
    the value nor the quote — so keying the judgment on it would serve a refused attempt's stale
    verdict to its own correction. This is why the judgment has its own identity.
    """

    base = entailment_judgment_id(field_key=_FIELD, value=True, quote=_QUOTE)
    assert base == entailment_judgment_id(field_key=_FIELD, value=True, quote=_QUOTE)
    assert base != entailment_judgment_id(field_key=_FIELD, value=False, quote=_QUOTE)
    assert base != entailment_judgment_id(field_key=_FIELD, value=True, quote=_QUOTE[:20])
    assert base != entailment_judgment_id(field_key="client.other", value=True, quote=_QUOTE)
    # Key-sorted canonical JSON, so a value round-tripped through jsonb (which does NOT preserve
    # object key order) recomputes the same id — the property that makes "which verdict admitted
    # this claim?" answerable from the stored claim. The live §6c probe caught this.
    assert entailment_judgment_id(
        field_key=_FIELD, value={"a": 1, "b": 2}, quote=_QUOTE
    ) == entailment_judgment_id(field_key=_FIELD, value={"b": 2, "a": 1}, quote=_QUOTE)
    # Order still matters where it is part of the value: a list is a sequence, not a set.
    assert entailment_judgment_id(
        field_key=_FIELD, value=["a", "b"], quote=_QUOTE
    ) != entailment_judgment_id(field_key=_FIELD, value=["b", "a"], quote=_QUOTE)
    # The separator is load-bearing: field/quote boundaries cannot be shifted into each other.
    assert entailment_judgment_id(field_key="ab", value=1, quote="c") != entailment_judgment_id(
        field_key="a", value=1, quote="bc"
    )
    assert ENTAILMENT_JUDGMENT_NAMESPACE == "stage0-interview-entailment"


def test_the_probe_claim_carries_the_span_as_evidence_and_never_tier_four() -> None:
    """What the judge is asked: this value, this span, nothing wider — and no status side effect.

    ``source_tier`` 4 is the only tier for which the M9.3 judge drives ``verification_status``.
    The probe is tier 1, so a judgment about a claim row that does not exist yet writes no status.
    """

    judge = _FakeJudge()
    _entails(judge)

    (probe,) = judge.seen
    assert probe.evidence_span == _QUOTE
    assert probe.value_json is True
    assert probe.field_key == _FIELD
    assert probe.source_tier == 1
    assert probe.extraction_method is ExtractionMethod.HUMAN
    assert probe.source_url is None
    assert probe.id == entailment_judgment_id(field_key=_FIELD, value=True, quote=_QUOTE)


def test_only_a_supported_verdict_over_the_threshold_admits_the_value() -> None:
    supported = _entails(_FakeJudge(verdict=JudgeVerdict.SUPPORTED, score=0.95))
    assert (supported.supported, supported.verdict) == (True, "supported")

    for verdict in (JudgeVerdict.PARTIAL, JudgeVerdict.UNSUPPORTED, JudgeVerdict.CONTRADICTED):
        refused = _entails(_FakeJudge(verdict=verdict, score=0.99))
        assert refused.supported is False
        assert refused.verdict == verdict.value

    # `supported` below the policy threshold is not an admission either.
    weak = _entails(_FakeJudge(verdict=JudgeVerdict.SUPPORTED, score=0.5))
    assert weak.supported is False
    assert weak.verdict == "supported"


def test_a_judge_outage_is_reported_as_unavailable_not_as_an_unsupported_value() -> None:
    """Fail closed, but honestly: the two refusals lead the model to different repairs."""

    result = _entails(_FakeJudge(error=RuntimeError("gateway down")))
    assert result.supported is False
    assert result.verdict == "unavailable"


def test_a_list_value_travels_as_canonical_json_to_the_judge() -> None:
    """A list is the shape the acceptance run could never express; it must reach the judge whole."""

    judge = _FakeJudge()
    assert _entails(judge, value=["SOAP", "APSO", "H&P"]).supported is True
    (probe,) = judge.seen
    assert probe.value_json == ["SOAP", "APSO", "H&P"]
