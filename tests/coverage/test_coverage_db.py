from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_config.coverage import ResearchLoopPolicy
from clue_core import (
    Completion,
    EmbeddingResult,
    Entity,
    EntityId,
    EntityType,
    FieldDef,
    Message,
    PassKind,
    ResearchAttemptOutcome,
    ResearchTerminalStatus,
    RunId,
    new_coverage_attempt_id,
    new_coverage_decision_id,
)
from clue_projections.research_coverage import (
    research_attempt_history,
    research_coverage,
    research_evaluator_advice_history,
)
from clue_research.coverage import (
    CoverageAttempt,
    CoverageController,
    CoverageDecision,
    EvaluatorProposalKind,
    GoalJudge,
    list_attempts,
    list_decisions,
    list_evaluator_advices,
    record_attempt,
    record_decision,
)
from tests._workspace import seed_workspace
from tests.profiling.conftest import conn_session_factory, rollback_conn, run_async


class _EvaluatorGateway:
    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        return Completion(model=model, text=self._text, cost_cents=Decimal(0))

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        raise AssertionError("coverage evaluator never embeds")


def _attempt(workspace_id: str, *, run_id: RunId, round_number: int = 1) -> CoverageAttempt:
    return CoverageAttempt(
        id=new_coverage_attempt_id(),
        workspace_id=workspace_id,
        run_id=run_id,
        entity_id=EntityId(uuid4()),
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        tier="high",
        round=round_number,
        strategy_key="deterministic_exact",
        source_family="deterministic",
        outcome=ResearchAttemptOutcome.NO_HIT,
        stop_reason="tier_exhausted",
        reason_detail="No usable claim was produced.",
        cost_cents=Decimal("1.25"),
    )


def test_attempt_is_idempotent_and_append_only(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c1_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            value = _attempt(workspace_id, run_id=run_id)
            first = await record_attempt(conn, value)
            replay = await record_attempt(
                conn, value.model_copy(update={"id": new_coverage_attempt_id()})
            )
            assert replay.id == first.id
            assert len(await list_attempts(conn, workspace_id=workspace_id, run_id=run_id)) == 1
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text("UPDATE coverage_attempt SET reason_detail='changed' WHERE id=:id"),
                    {"id": first.id},
                )

    run_async(scenario())


def test_only_one_terminal_decision_wins_across_rounds(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c1_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            attempt = _attempt(workspace_id, run_id=run_id)
            first = await record_decision(
                conn,
                CoverageDecision(
                    id=new_coverage_decision_id(),
                    workspace_id=workspace_id,
                    run_id=run_id,
                    entity_id=attempt.entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key=attempt.field_key,
                    tier="high",
                    round=1,
                    terminal_status=ResearchTerminalStatus.UNFILLED_TERMINAL,
                    reason_code="max_rounds",
                    reason_detail="Research stopped at the configured round cap.",
                    attempt_refs=(attempt.id,),
                ),
            )
            second = await record_decision(
                conn,
                CoverageDecision(
                    id=new_coverage_decision_id(),
                    workspace_id=workspace_id,
                    run_id=run_id,
                    entity_id=attempt.entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key=attempt.field_key,
                    tier="high",
                    round=2,
                    terminal_status=ResearchTerminalStatus.BUDGET_EXHAUSTED,
                    reason_code="budget_exhausted",
                    reason_detail="Budget exhausted.",
                ),
            )
            assert second.id == first.id
            decisions = await list_decisions(conn, workspace_id=workspace_id, run_id=run_id)
            assert len(decisions) == 1

    run_async(scenario())


def test_workspace_scoped_reads_fail_closed(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed_workspace(conn, f"ws_c1_owner_{uuid4().hex[:8]}")
            foreign = await seed_workspace(conn, f"ws_c1_foreign_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            await record_attempt(conn, _attempt(owner, run_id=run_id))
            assert await list_attempts(conn, workspace_id=foreign, run_id=run_id) == []

    run_async(scenario())


def test_caller_selects_an_engine_permitted_distinct_strategy_then_stops_at_cap(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c1_rounds_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            entity = Entity(entity_id=EntityId(uuid4()), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.recent_funding",
                value_type="object",
                tier_plan=(),
                pass_kind=PassKind.DEEP,
            )
            controller = CoverageController(
                policy=ResearchLoopPolicy(
                    max_rounds_by_tier={"high": 2},
                    marginal_yield_floor=0,
                    strategy_transitions={
                        "deterministic_exact": (
                            "official_site_exact",
                            "tier3_web_widened",
                        ),
                        "official_site_exact": ("tier3_web_widened",),
                        "tier3_web_widened": ("tier4_research_product",),
                        "tier4_research_product": (),
                    },
                )
            )
            first = await controller.run_round(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
            )
            assert first.terminal is False
            second = await controller.run_round(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
                strategy_hint="tier3_web_widened",
            )
            assert second.terminal is True
            attempts = await list_attempts(conn, workspace_id=workspace_id, run_id=run_id)
            assert [item.strategy_key for item in attempts] == [
                "deterministic_exact",
                "tier3_web_widened",
            ]
            decisions = await list_decisions(conn, workspace_id=workspace_id, run_id=run_id)
            assert decisions[-1].reason_code == "max_rounds"

    run_async(scenario())


def test_invalid_evaluator_cannot_plan_or_terminally_stop_a_permitted_retry(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c1_advisory_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            entity = Entity(entity_id=EntityId(uuid4()), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.recent_funding",
                value_type="object",
                tier_plan=(),
                pass_kind=PassKind.DEEP,
            )
            controller = CoverageController(
                judge=GoalJudge(_EvaluatorGateway("not valid evaluator output"), model="judge/test")
            )
            result = await controller.run_round(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
            )
            assert result.terminal is False
            decisions = await list_decisions(conn, workspace_id=workspace_id, run_id=run_id)
            assert decisions[0].terminal_status is None
            assert decisions[0].next_strategy_key == "official_site_exact"
            assert decisions[0].reason_code == "retry_permitted_evaluator_unavailable"

    run_async(scenario())


def test_valid_propose_stop_advice_cannot_create_a_terminal_decision(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c1_advice_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            entity = Entity(entity_id=EntityId(uuid4()), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.recent_funding",
                value_type="object",
                tier_plan=(),
                pass_kind=PassKind.DEEP,
            )
            payload = {
                "assessments": [
                    {
                        "field_key": field.field_key,
                        "meaningful_gap_remaining": False,
                        "recommendation": "propose_stop",
                        "warning_codes": ["goal_appears_satisfied"],
                        "rationale": "The requested research goal appears satisfied.",
                    }
                ],
                "sufficient_for_goal": True,
            }
            controller = CoverageController(
                judge=GoalJudge(_EvaluatorGateway(json.dumps(payload)), model="judge/test")
            )
            result = await controller.run_round(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
            )
            assert result.terminal is False
            decisions = await list_decisions(conn, workspace_id=workspace_id, run_id=run_id)
            assert decisions[0].terminal_status is None
            assert decisions[0].next_strategy_key == "official_site_exact"
            assert decisions[0].reason_code == "retry_permitted_evaluator_questions_value"

    run_async(scenario())


@pytest.mark.parametrize("payload", ["not-json", "valid-stop"])
def test_agent_stop_proposal_is_typed_append_only_advice_and_never_terminal(
    require_profiling_db: None,
    payload: str,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c67_stop_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            entity = Entity(entity_id=EntityId(uuid4()), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.recent_funding",
                value_type="object",
                tier_plan=(),
                pass_kind=PassKind.DEEP,
            )
            stop_payload = {
                "assessments": [
                    {
                        "field_key": field.field_key,
                        "meaningful_gap_remaining": False,
                        "recommendation": "propose_stop",
                        "warning_codes": ["goal_appears_satisfied"],
                        "rationale": "No further useful evidence appears likely.",
                    }
                ],
                "sufficient_for_goal": True,
            }
            gateway_text = json.dumps(stop_payload) if payload == "valid-stop" else payload
            controller = CoverageController(
                judge=GoalJudge(_EvaluatorGateway(gateway_text), model="judge/test")
            )
            advice = await controller.assess_stop_proposal(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
                requested_round=1,
            )
            replay = await controller.assess_stop_proposal(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
                requested_round=1,
            )
            assert replay.id == advice.id
            assert advice.proposal_kind is EvaluatorProposalKind.AGENT_STOP_PROPOSAL
            assert advice.non_authoritative is True
            assert advice.valid is (payload == "valid-stop")
            assert await list_attempts(conn, workspace_id=workspace_id, run_id=run_id) == []
            assert await list_decisions(conn, workspace_id=workspace_id, run_id=run_id) == []
            rows = await list_evaluator_advices(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=entity.entity_id,
            )
            assert [item.id for item in rows] == [advice.id]
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "UPDATE coverage_evaluator_advice SET non_authoritative=false WHERE id=:id"
                    ),
                    {"id": advice.id},
                )

    run_async(scenario())


def test_explicit_round_replays_exact_coverage_and_evaluator_boundary(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, f"ws_c67_replay_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            entity = Entity(entity_id=EntityId(uuid4()), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.recent_funding",
                value_type="object",
                tier_plan=(),
                pass_kind=PassKind.DEEP,
            )
            controller = CoverageController()
            first = await controller.run_round(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
                requested_round=1,
            )
            replay = await controller.run_round(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=None,
                entity=entity,
                tier="high",
                field_defs=(field,),
                requested_round=1,
            )
            assert replay.replayed is True
            assert replay.attempt_ids == first.attempt_ids
            assert replay.decision_ids == first.decision_ids
            assert replay.evaluator_advice_id == first.evaluator_advice_id
            assert (
                len(
                    await list_evaluator_advices(
                        conn,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        entity_id=entity.entity_id,
                    )
                )
                == 1
            )
            history = await research_evaluator_advice_history(
                conn_factory=conn_session_factory(conn),
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=entity.entity_id,
            )
            assert history is not None
            assert history.items[0].non_authoritative is True
            assert "rationale" not in history.model_dump_json()

    run_async(scenario())


def test_enum_values_match_migration_contract() -> None:
    assert {item.value for item in ResearchAttemptOutcome} == {
        "claims_produced",
        "no_hit",
        "blocked",
        "budget_stop",
        "failed",
    }
    assert {item.value for item in ResearchTerminalStatus} == {
        "filled",
        "unfilled_terminal",
        "blocked_by_policy",
        "budget_exhausted",
    }


def test_projections_are_reference_only_and_workspace_scoped(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed_workspace(conn, f"ws_c1_projection_{uuid4().hex[:8]}")
            foreign = await seed_workspace(conn, f"ws_c1_projection_x_{uuid4().hex[:8]}")
            run_id = RunId(uuid4())
            attempt = await record_attempt(conn, _attempt(owner, run_id=run_id))
            decision = await record_decision(
                conn,
                CoverageDecision(
                    id=new_coverage_decision_id(),
                    workspace_id=owner,
                    run_id=run_id,
                    entity_id=attempt.entity_id,
                    entity_type=attempt.entity_type,
                    field_key=attempt.field_key,
                    tier=attempt.tier,
                    round=1,
                    terminal_status=ResearchTerminalStatus.UNFILLED_TERMINAL,
                    reason_code="strategies_exhausted",
                    reason_detail="Every permitted strategy was exhausted.",
                    attempt_refs=(attempt.id,),
                ),
            )
            assert decision.terminal_status is ResearchTerminalStatus.UNFILLED_TERMINAL
            factory = conn_session_factory(conn)
            coverage = await research_coverage(
                conn_factory=factory, workspace_id=owner, run_id=run_id
            )
            assert coverage is not None
            assert coverage.fields[0].attempt_refs == (attempt.id,)
            assert coverage.fields[0].reason_code == "strategies_exhausted"
            history = await research_attempt_history(
                conn_factory=factory,
                workspace_id=owner,
                run_id=run_id,
                entity_id=attempt.entity_id,
                field_key=attempt.field_key,
            )
            assert history is not None
            dumped = history.model_dump(mode="json")
            assert "value_json" not in str(dumped)
            assert (
                await research_coverage(conn_factory=factory, workspace_id=foreign, run_id=run_id)
                is None
            )

    run_async(scenario())
