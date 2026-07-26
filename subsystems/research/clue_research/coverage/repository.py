"""The only SQL repository for the append-only C1 coverage ledgers."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    CoverageAttemptId,
    CoverageDecisionId,
    CoverageEvaluatorAdviceId,
    EntityId,
    EntityType,
    ProjectRunId,
    ResearchAttemptOutcome,
    ResearchTerminalStatus,
    RunId,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.coverage.models import (
    CoverageAttempt,
    CoverageDecision,
    CoverageEvaluatorAdvice,
    EvaluatorProposalKind,
    GoalJudgeResult,
)

_ATTEMPT_COLUMNS = (
    "id, workspace_id, run_id, project_run_id, entity_id, entity_type, field_key, tier, "
    "round, strategy_key, source_family, outcome, stop_reason, reason_detail, cost_cents, "
    "claim_refs_json, quality_mode, created_at"
)
_DECISION_COLUMNS = (
    "id, workspace_id, run_id, project_run_id, entity_id, entity_type, field_key, tier, "
    "round, terminal_status, next_strategy_key, reason_code, reason_detail, attempt_refs_json, "
    "claim_refs_json, judge_model, judge_prompt_version, evaluator_advice_id, created_at"
)
_ADVICE_COLUMNS = (
    "id, workspace_id, run_id, project_run_id, entity_id, entity_type, tier, round, "
    "proposal_kind, planned_fields_json, result_json, valid, answering_model, prompt_version, "
    "cost_cents, non_authoritative, created_at"
)


def _attempt(row: Mapping[str, object]) -> CoverageAttempt:
    values = dict(row)
    raw_refs = values.pop("claim_refs_json")
    return CoverageAttempt(
        **{
            **values,
            "id": CoverageAttemptId(row["id"]),  # type: ignore[arg-type]
            "run_id": RunId(row["run_id"]),  # type: ignore[arg-type]
            "project_run_id": (
                ProjectRunId(row["project_run_id"])  # type: ignore[arg-type]
                if row["project_run_id"] is not None
                else None
            ),
            "entity_id": EntityId(row["entity_id"]),  # type: ignore[arg-type]
            "entity_type": EntityType(str(row["entity_type"])),
            "outcome": ResearchAttemptOutcome(str(row["outcome"])),
            "claim_refs": tuple(
                ClaimId(UUID(str(value))) for value in (decode_jsonb(raw_refs) or ())
            ),
        }
    )


def _decision(row: Mapping[str, object]) -> CoverageDecision:
    values = dict(row)
    raw_attempt_refs = values.pop("attempt_refs_json")
    raw_claim_refs = values.pop("claim_refs_json")
    terminal = row["terminal_status"]
    return CoverageDecision(
        **{
            **values,
            "id": CoverageDecisionId(row["id"]),  # type: ignore[arg-type]
            "run_id": RunId(row["run_id"]),  # type: ignore[arg-type]
            "project_run_id": (
                ProjectRunId(row["project_run_id"])  # type: ignore[arg-type]
                if row["project_run_id"] is not None
                else None
            ),
            "entity_id": EntityId(row["entity_id"]),  # type: ignore[arg-type]
            "entity_type": EntityType(str(row["entity_type"])),
            "terminal_status": (
                ResearchTerminalStatus(str(terminal)) if terminal is not None else None
            ),
            "attempt_refs": tuple(
                CoverageAttemptId(UUID(str(value)))
                for value in (decode_jsonb(raw_attempt_refs) or ())
            ),
            "claim_refs": tuple(
                ClaimId(UUID(str(value))) for value in (decode_jsonb(raw_claim_refs) or ())
            ),
            "evaluator_advice_id": (
                CoverageEvaluatorAdviceId(row["evaluator_advice_id"])  # type: ignore[arg-type]
                if row["evaluator_advice_id"] is not None
                else None
            ),
        }
    )


def _advice(row: Mapping[str, object]) -> CoverageEvaluatorAdvice:
    values = dict(row)
    raw_fields = decode_jsonb(values.pop("planned_fields_json")) or ()
    raw_result = decode_jsonb(values.pop("result_json"))
    return CoverageEvaluatorAdvice(
        **{
            **values,
            "id": CoverageEvaluatorAdviceId(row["id"]),  # type: ignore[arg-type]
            "run_id": RunId(row["run_id"]),  # type: ignore[arg-type]
            "project_run_id": (
                ProjectRunId(row["project_run_id"])  # type: ignore[arg-type]
                if row["project_run_id"] is not None
                else None
            ),
            "entity_id": EntityId(row["entity_id"]),  # type: ignore[arg-type]
            "entity_type": EntityType(str(row["entity_type"])),
            "proposal_kind": EvaluatorProposalKind(str(row["proposal_kind"])),
            "planned_fields": tuple(str(value) for value in raw_fields),
            "result": GoalJudgeResult.model_validate(raw_result)
            if raw_result is not None
            else None,
        }
    )


async def record_attempt(conn: AsyncConnection, value: CoverageAttempt) -> CoverageAttempt:
    await conn.execute(
        text(
            """
            INSERT INTO coverage_attempt (
                id, workspace_id, run_id, project_run_id, entity_id, entity_type, field_key, tier,
                round, strategy_key, source_family, outcome, stop_reason, reason_detail, cost_cents,
                claim_refs_json, quality_mode
            ) VALUES (
                :id, :workspace_id, :run_id, :project_run_id, :entity_id,
                CAST(:entity_type AS entity_type), :field_key, :tier, :round, :strategy_key,
                :source_family, CAST(:outcome AS research_attempt_outcome), :stop_reason,
                :reason_detail, :cost_cents, CAST(:claim_refs_json AS jsonb), :quality_mode
            )
            ON CONFLICT (run_id, entity_id, field_key, tier, round, strategy_key) DO NOTHING
            """
        ),
        {
            **value.model_dump(exclude={"claim_refs", "created_at"}),
            "entity_type": value.entity_type.value,
            "outcome": value.outcome.value,
            "claim_refs_json": serialize_value_json([str(item) for item in value.claim_refs]),
        },
    )
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ATTEMPT_COLUMNS} FROM coverage_attempt WHERE "
                    "run_id=:run_id AND entity_id=:entity_id AND field_key=:field_key "
                    "AND tier=:tier "
                    "AND round=:round AND strategy_key=:strategy_key"
                ),
                value.model_dump(
                    include={"run_id", "entity_id", "field_key", "tier", "round", "strategy_key"}
                ),
            )
        )
        .mappings()
        .one()
    )
    return _attempt(dict(row))


async def record_decision(conn: AsyncConnection, value: CoverageDecision) -> CoverageDecision:
    await conn.execute(
        text(
            """
            INSERT INTO coverage_decision (
                id, workspace_id, run_id, project_run_id, entity_id, entity_type, field_key, tier,
                round, terminal_status, next_strategy_key, reason_code, reason_detail,
                attempt_refs_json, claim_refs_json, judge_model, judge_prompt_version
                , evaluator_advice_id
            ) VALUES (
                :id, :workspace_id, :run_id, :project_run_id, :entity_id,
                CAST(:entity_type AS entity_type), :field_key, :tier, :round,
                CAST(:terminal_status AS research_terminal_status), :next_strategy_key,
                :reason_code, :reason_detail, CAST(:attempt_refs_json AS jsonb),
                CAST(:claim_refs_json AS jsonb), :judge_model, :judge_prompt_version
                , :evaluator_advice_id
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            **value.model_dump(
                exclude={"attempt_refs", "claim_refs", "created_at", "terminal_status"}
            ),
            "entity_type": value.entity_type.value,
            "terminal_status": (
                value.terminal_status.value if value.terminal_status is not None else None
            ),
            "attempt_refs_json": serialize_value_json([str(item) for item in value.attempt_refs]),
            "claim_refs_json": serialize_value_json([str(item) for item in value.claim_refs]),
        },
    )
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DECISION_COLUMNS} FROM coverage_decision WHERE "
                    "run_id=:run_id AND entity_id=:entity_id AND field_key=:field_key "
                    "AND tier=:tier "
                    "AND (round=:round OR terminal_status IS NOT NULL) "
                    "ORDER BY (round=:round) DESC, created_at LIMIT 1"
                ),
                value.model_dump(include={"run_id", "entity_id", "field_key", "tier", "round"}),
            )
        )
        .mappings()
        .one()
    )
    return _decision(dict(row))


async def record_evaluator_advice(
    conn: AsyncConnection,
    value: CoverageEvaluatorAdvice,
) -> CoverageEvaluatorAdvice:
    """Insert one immutable evaluation boundary and reject identity/payload disagreement."""

    await conn.execute(
        text(
            """
            INSERT INTO coverage_evaluator_advice (
                id, workspace_id, run_id, project_run_id, entity_id, entity_type, tier, round,
                proposal_kind, planned_fields_json, result_json, valid, answering_model,
                prompt_version, cost_cents, non_authoritative
            ) VALUES (
                :id, :workspace_id, :run_id, :project_run_id, :entity_id,
                CAST(:entity_type AS entity_type), :tier, :round, :proposal_kind,
                CAST(:planned_fields_json AS jsonb), CAST(:result_json AS jsonb), :valid,
                :answering_model, :prompt_version, :cost_cents, :non_authoritative
            )
            ON CONFLICT (run_id, entity_id, tier, round, proposal_kind) DO NOTHING
            """
        ),
        {
            **value.model_dump(
                exclude={
                    "planned_fields",
                    "result",
                    "created_at",
                    "entity_type",
                    "proposal_kind",
                }
            ),
            "entity_type": value.entity_type.value,
            "proposal_kind": value.proposal_kind.value,
            "planned_fields_json": serialize_value_json(list(value.planned_fields)),
            "result_json": (
                serialize_value_json(value.result.model_dump(mode="json"))
                if value.result is not None
                else None
            ),
        },
    )
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ADVICE_COLUMNS} FROM coverage_evaluator_advice WHERE "
                    "run_id=:run_id AND entity_id=:entity_id AND tier=:tier AND round=:round "
                    "AND proposal_kind=:proposal_kind"
                ),
                {
                    "run_id": value.run_id,
                    "entity_id": value.entity_id,
                    "tier": value.tier,
                    "round": value.round,
                    "proposal_kind": value.proposal_kind.value,
                },
            )
        )
        .mappings()
        .one()
    )
    persisted = _advice(dict(row))
    comparable = {"created_at"}
    if persisted.model_dump(exclude=comparable) != value.model_dump(exclude=comparable):
        raise ValueError("coverage evaluator advice identity already has a different payload")
    return persisted


async def get_evaluator_advice(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: RunId,
    entity_id: EntityId,
    tier: str,
    round: int,
    proposal_kind: EvaluatorProposalKind,
) -> CoverageEvaluatorAdvice | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ADVICE_COLUMNS} FROM coverage_evaluator_advice WHERE "
                    "workspace_id=:workspace_id AND run_id=:run_id AND entity_id=:entity_id "
                    "AND tier=:tier AND round=:round AND proposal_kind=:proposal_kind"
                ),
                {
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "entity_id": entity_id,
                    "tier": tier,
                    "round": round,
                    "proposal_kind": proposal_kind.value,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return _advice(dict(row)) if row is not None else None


async def list_evaluator_advices(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: RunId,
    entity_id: EntityId | None = None,
) -> list[CoverageEvaluatorAdvice]:
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ADVICE_COLUMNS} FROM coverage_evaluator_advice "
                    "WHERE workspace_id=:workspace_id AND run_id=:run_id "
                    "AND (CAST(:entity_id AS uuid) IS NULL OR entity_id=:entity_id) "
                    "ORDER BY round, proposal_kind, created_at, id"
                ),
                {
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "entity_id": entity_id,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_advice(dict(row)) for row in rows]


async def list_attempts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: RunId,
    entity_id: EntityId | None = None,
    field_key: str | None = None,
) -> list[CoverageAttempt]:
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ATTEMPT_COLUMNS} FROM coverage_attempt "
                    "WHERE workspace_id=:workspace_id AND run_id=:run_id "
                    "AND (CAST(:entity_id AS uuid) IS NULL OR entity_id=:entity_id) "
                    "AND (CAST(:field_key AS text) IS NULL OR field_key=:field_key) "
                    "ORDER BY round, field_key, created_at, id"
                ),
                {
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "entity_id": entity_id,
                    "field_key": field_key,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_attempt(dict(row)) for row in rows]


async def list_decisions(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: RunId,
    entity_id: EntityId | None = None,
    field_key: str | None = None,
) -> list[CoverageDecision]:
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DECISION_COLUMNS} FROM coverage_decision "
                    "WHERE workspace_id=:workspace_id AND run_id=:run_id "
                    "AND (CAST(:entity_id AS uuid) IS NULL OR entity_id=:entity_id) "
                    "AND (CAST(:field_key AS text) IS NULL OR field_key=:field_key) "
                    "ORDER BY round, field_key, created_at, id"
                ),
                {
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "entity_id": entity_id,
                    "field_key": field_key,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_decision(dict(row)) for row in rows]
