"""A locally deterministic producer-to-product proof for judged-claim verdict attribution."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from clue_api.claim_entailment import FaithfulnessClaimEntailmentJudge
from clue_api.review.composition import DbVerificationAnnotationReader
from clue_core import (
    AccountStatus,
    Claim,
    Completion,
    EntityType,
    ExtractionMethod,
    Message,
    ResearchMode,
    ReuseScope,
    new_run_id,
)
from clue_research.claimstore import (
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    entailment_judgment_id,
    insert_claim,
)
from clue_research.identity import insert_account_entity
from clue_research.narrative import read_faithfulness_citation
from clue_research.verification import FaithfulnessJudgeImpl
from tests._workspace import seed_workspace
from tests.profiling.conftest import conn_session_factory, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WORKSPACE = "part-ii-attribution-a"
_OTHER_WORKSPACE = "part-ii-attribution-b"
_FIELD = "core.primary_tech_stack"
_VALUE = ["SOC 2", "HIPAA"]
_QUOTE = "Our platform has completed SOC 2 controls and supports HIPAA-governed deployments."


class _SupportedGateway:
    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        del messages, opts
        return Completion(
            model=model,
            text=(
                '{"verdict":"supported","score":0.96,'
                '"rationale":"the quoted controls entail the typed value"}'
            ),
            cost_cents=Decimal(0),
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError


def test_actual_q_producer_is_visible_to_narrative_and_review_only_as_a() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WORKSPACE)
            await seed_workspace(conn, _OTHER_WORKSPACE)
            account_id = await insert_account_entity(
                conn,
                canonical_name="Attribution Test Co",
                primary_domain="attribution.test",
                status=AccountStatus.ACTIVE,
                workspace_id=_WORKSPACE,
            )
            judge = FaithfulnessJudgeImpl(
                gateway=_SupportedGateway(),
                conn_factory=conn_session_factory(conn),
            )
            producer = FaithfulnessClaimEntailmentJudge(judge=judge)
            admitted = await producer.entails(
                entity_id=account_id,
                field_key=_FIELD,
                value=_VALUE,
                quote=_QUOTE,
            )
            assert admitted.supported is True

            actual = Claim(
                entity_id=account_id,
                entity_type=EntityType.ACCOUNT,
                field_key=_FIELD,
                value_json=_VALUE,
                source_key=SOURCE_CLIENT_INTERVIEW_JUDGED,
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                evidence_span=_QUOTE,
                confidence=0.96,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=_WORKSPACE,
            )
            await insert_claim(conn, actual)
            question_id = entailment_judgment_id(
                field_key=_FIELD,
                value=_VALUE,
                quote=_QUOTE,
            )
            assert question_id != actual.id
            counts = (
                await conn.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE claim_id = :q), "
                        "count(*) FILTER (WHERE claim_id = :a) FROM faithfulness_verdict"
                    ),
                    {"q": str(question_id), "a": str(actual.id)},
                )
            ).one()
            assert tuple(counts) == (1, 0), "the real producer wrote Q, never A"

            citation = await read_faithfulness_citation(conn, actual)
            assert citation is not None
            assert citation.claim_id == actual.id
            assert citation.verdict == "supported"

            reader = DbVerificationAnnotationReader(conn_factory=conn_session_factory(conn))
            visible = await reader.annotations_for_claims(
                claim_ids=(actual.id,), workspace_id=_WORKSPACE
            )
            assert set(visible) == {actual.id}
            assert visible[actual.id].faithfulness_verdict is not None
            assert visible[actual.id].faithfulness_verdict.value == "supported"

            hidden = await reader.annotations_for_claims(
                claim_ids=(actual.id,), workspace_id=_OTHER_WORKSPACE
            )
            assert hidden == {}, "a side-table row cannot bypass claim-store tenant scope"

    run_async(scenario())
