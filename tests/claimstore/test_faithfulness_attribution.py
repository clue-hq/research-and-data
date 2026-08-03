"""Part II — one claim-to-faithfulness-subject attribution contract.

The public object is always the real claim ``A``.  A judged interview claim is looked up by the
content-addressed question ``Q`` first and by ``A`` only as a legacy fallback; ordinary claims use
``A`` alone.  These tests pin that identity contract separately from its product consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    JudgeVerdict,
    ResearchMode,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import InMemorySink
from clue_research.claimstore import (
    METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS,
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    FaithfulnessSubjectIdentityError,
    entailment_judgment_id,
    faithfulness_lookup_plan,
    read_faithfulness_attributions,
)
from tests.db.conftest import run_async

from .conftest import rollback_conn


def _claim(
    *,
    value: object = "HIPAA-ready",
    quote: str | None = "We have completed the controls required for HIPAA readiness.",
    source_key: str | None = None,
) -> Claim:
    return Claim(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        field_key="account.operational_pain",
        value_json=value,  # type: ignore[arg-type]
        source_key=source_key,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        evidence_span=quote,
        confidence=0.95,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )


def test_lookup_plan_uses_a_for_ordinary_claim_even_when_it_has_evidence() -> None:
    claim = _claim(source_key="client_interview")
    assert faithfulness_lookup_plan(claim).actual_claim_id == claim.id
    assert faithfulness_lookup_plan(claim).subject_ids == (claim.id,)


def test_lookup_plan_prefers_q_then_a_only_for_the_judged_source() -> None:
    claim = _claim(source_key=SOURCE_CLIENT_INTERVIEW_JUDGED)
    question_id = entailment_judgment_id(
        field_key=claim.field_key,
        value=claim.value_json,
        quote=claim.evidence_span or "",
    )
    plan = faithfulness_lookup_plan(claim)
    assert plan.actual_claim_id == claim.id
    assert plan.subject_ids == (question_id, claim.id)


def test_lookup_plan_fails_typed_and_bounded_for_a_malformed_judged_claim() -> None:
    claim = _claim(source_key=SOURCE_CLIENT_INTERVIEW_JUDGED, quote=None)
    with pytest.raises(FaithfulnessSubjectIdentityError) as caught:
        faithfulness_lookup_plan(claim)
    assert caught.value.actual_claim_id == claim.id
    assert caught.value.reason_code == "judged_interview_evidence_span_missing"


def test_batch_reader_isolates_a_malformed_judged_claim_and_emits_a_bounded_metric() -> None:
    claim = _claim(source_key=SOURCE_CLIENT_INTERVIEW_JUDGED, quote=None)
    sink = InMemorySink()

    async def scenario() -> None:
        # No valid lookup plan means the store must not issue a SQL query.
        result = await read_faithfulness_attributions(
            cast(AsyncConnection, object()), (claim,), sink=sink
        )
        assert result == {}

    run_async(scenario())
    assert sink.counter(
        METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS,
        reason="judged_interview_evidence_span_missing",
    ) == pytest.approx(1)


@pytest.mark.usefixtures("require_claimstore_db")
def test_batch_reader_applies_q_precedence_a_fallback_and_ordinary_equivalence_once() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ordinary = _claim(value="ordinary", source_key="client_interview")
            q_only = _claim(value="q-only", source_key=SOURCE_CLIENT_INTERVIEW_JUDGED)
            legacy_a = _claim(value="legacy-a", source_key=SOURCE_CLIENT_INTERVIEW_JUDGED)
            both = _claim(value="both", source_key=SOURCE_CLIENT_INTERVIEW_JUDGED)
            malformed = _claim(
                value="malformed",
                quote=None,
                source_key=SOURCE_CLIENT_INTERVIEW_JUDGED,
            )

            q_only_id = faithfulness_lookup_plan(q_only).subject_ids[0]
            both_q_id = faithfulness_lookup_plan(both).subject_ids[0]
            now = datetime.now(UTC)
            rows = (
                # Ordinary behaviour is unchanged: verdict lives on A.
                (ordinary.id, "supported", 0.91, now, "ordinary"),
                # The new producer writes under Q.
                (q_only_id, "supported", 0.92, now, "q-only"),
                # Legacy compatibility: a judged-source claim may still have only A.
                (legacy_a.id, "unsupported", 0.12, now, "legacy-a"),
                # Q wins even when A was judged later.
                (both_q_id, "partial", 0.55, now, "both-q"),
                (both.id, "contradicted", 0.01, now + timedelta(minutes=5), "both-a"),
            )
            for subject_id, verdict, score, judged_at, model in rows:
                await conn.execute(
                    text(
                        """
                        INSERT INTO faithfulness_verdict
                            (claim_id, verdict, score, rationale, judge_model, answering_model,
                             prompt_version, cost_cents, judged_at)
                        VALUES
                            (:claim_id, CAST(:verdict AS judge_verdict), :score, '', :model,
                             :model, 'part-ii-test', 0, :judged_at)
                        """
                    ),
                    {
                        "claim_id": str(subject_id),
                        "verdict": verdict,
                        "score": score,
                        "model": model,
                        "judged_at": judged_at,
                    },
                )

            statements: list[str] = []

            def capture(
                _conn: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                statements.append(statement)

            event.listen(conn.sync_connection, "before_cursor_execute", capture)
            sink = InMemorySink()
            try:
                found = await read_faithfulness_attributions(
                    conn,
                    (ordinary, q_only, legacy_a, both, malformed),
                    sink=sink,
                )
            finally:
                event.remove(conn.sync_connection, "before_cursor_execute", capture)

            assert set(found) == {ordinary.id, q_only.id, legacy_a.id, both.id}
            assert found[ordinary.id].verdict is JudgeVerdict.SUPPORTED
            assert found[q_only.id].verdict is JudgeVerdict.SUPPORTED
            assert found[legacy_a.id].verdict is JudgeVerdict.UNSUPPORTED
            assert found[both.id].verdict is JudgeVerdict.PARTIAL
            assert malformed.id not in found  # isolated, never mislabeled unsupported
            assert sink.counter(
                METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS,
                reason="judged_interview_evidence_span_missing",
            ) == pytest.approx(1)
            assert all(item.actual_claim_id == claim_id for claim_id, item in found.items())
            verdict_reads = [
                sql for sql in statements if "FROM faithfulness_verdict" in " ".join(sql.split())
            ]
            assert len(verdict_reads) == 1, "mixed attribution must be one batch verdict query"

    run_async(scenario())
