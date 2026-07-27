"""C7.2 governed derivation-entailment judge tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    Completion,
    EmbeddingResult,
    EntailmentJudgeRequest,
    EntailmentReasonCode,
    EntailmentSupport,
    EntailmentVerdictKind,
    EntityType,
    ExtractionMethod,
    Message,
    ResearchMode,
    ResearchSubjectRef,
    ResearchSupportRole,
    VerificationStatus,
    new_entity_id,
    new_run_id,
)
from clue_research.verification import (
    EntailmentJudgeImpl,
    build_entailment_messages,
    parse_entailment_response,
)

from .conftest import rollback_conn, run_async


class FakeGateway:
    def __init__(
        self,
        text: str = ('{"verdict":"supported","confidence":0.91,"reason_codes":["entailed"]}'),
        *,
        answering_model: str = "fallback/judge",
        raises: bool = False,
    ) -> None:
        self.text = text
        self.answering_model = answering_model
        self.raises = raises
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, messages))
        if self.raises:
            raise RuntimeError("gateway unavailable")
        return Completion(
            model=self.answering_model,
            text=self.text,
            cost_cents=Decimal("0.4"),
        )

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:  # pragma: no cover
        raise NotImplementedError


def _derived(entity_id=None) -> Claim:  # type: ignore[no-untyped-def]
    return Claim(
        entity_id=entity_id or new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json="the new funding creates a transformation window",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        claim_flavor=ClaimFlavor.DERIVED,
        verification_status=VerificationStatus.UNVERIFIED,
    )


def _request() -> EntailmentJudgeRequest:
    derived = _derived()
    support = Claim(
        entity_id=derived.entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount_usd": 20_000_000, "round": "B"},
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        source_url="https://registry.example/funding",
        confidence=0.88,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        verification_status=VerificationStatus.VERIFIED,
    )
    return EntailmentJudgeRequest(
        derived_claim=derived,
        target=ResearchSubjectRef(
            entity_id=derived.entity_id,
            entity_type=EntityType.ACCOUNT,
            canonical_entity_version=1,
        ),
        supports=(
            EntailmentSupport(
                claim=support,
                role=ResearchSupportRole.DIRECT_EVIDENCE,
                ordinal=0,
            ),
        ),
        support_set_sha256="a" * 64,
        policy_version=1,
    )


def test_strict_parser_accepts_only_bounded_schema() -> None:
    parsed = parse_entailment_response(
        '{"verdict":"supported","confidence":0.91,"reason_codes":["entailed"]}'
    )
    assert parsed is not None
    assert parsed.reason_codes == (EntailmentReasonCode.ENTAILED,)

    assert (
        parse_entailment_response(
            'prefix {"verdict":"supported","confidence":0.9,"reason_codes":["entailed"]}'
        )
        is None
    )
    assert (
        parse_entailment_response(
            '{"verdict":"supported","confidence":0.9,"reason_codes":["entailed"],'
            '"rationale":"copied personal text"}'
        )
        is None
    )
    assert (
        parse_entailment_response(
            '{"verdict":"supported","confidence":0.9,"reason_codes":["not_entailed"]}'
        )
        is None
    )
    assert (
        parse_entailment_response(
            '{"verdict":"supported","confidence":0.9,"reason_codes":["entailed","missing_support"]}'
        )
        is None
    )
    assert (
        parse_entailment_response(
            '{"verdict":"unsupported","confidence":0.2,'
            '"reason_codes":["not_entailed","not_entailed"]}'
        )
        is None
    )


def test_prompt_fences_untrusted_values_and_requests_no_body() -> None:
    messages = build_entailment_messages(_request())
    assert len(messages) == 2
    assert "untrusted" in messages[0].content.lower()
    assert "<<<PROPOSED_VALUE>>>" in messages[1].content
    assert "<<<ORDERED_SUPPORTS>>>" in messages[1].content
    assert "copied support text" in messages[0].content
    assert '"value_json"' in messages[1].content


def test_judge_supported_malformed_and_gateway_error_fail_closed(
    require_verification_db: None,
) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            supported_gateway = FakeGateway()
            supported = await EntailmentJudgeImpl(
                gateway=supported_gateway,
                conn_factory=factory,
            ).judge(_request())
            assert supported.verdict is EntailmentVerdictKind.SUPPORTED
            assert supported.reason_codes == (EntailmentReasonCode.ENTAILED,)
            assert supported.answering_model == "fallback/judge"
            assert supported.cost_cents == Decimal("0.4")

            malformed = await EntailmentJudgeImpl(
                gateway=FakeGateway("not json"),
                conn_factory=factory,
            ).judge(_request())
            assert malformed.verdict is EntailmentVerdictKind.UNSUPPORTED
            assert malformed.reason_codes == (EntailmentReasonCode.MALFORMED_RESPONSE,)

            failed = await EntailmentJudgeImpl(
                gateway=FakeGateway(raises=True),
                conn_factory=factory,
            ).judge(_request())
            assert failed.verdict is EntailmentVerdictKind.ERROR
            assert failed.reason_codes == (EntailmentReasonCode.MODEL_ERROR,)

    run_async(_run())
