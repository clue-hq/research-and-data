"""Workspace-scoped, MVCC-only projections over the C1 coverage ledgers."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from clue_core import (
    ClaimId,
    CostCents,
    CoverageAttemptId,
    CoverageEvaluatorAdviceId,
    EntityId,
    ProjectRunId,
    ResearchTerminalStatus,
    RunId,
)
from clue_db import ConnFactory
from clue_research.coverage import list_attempts, list_decisions, list_evaluator_advices


class ResearchCoverageField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: str
    terminal_status: ResearchTerminalStatus | None = None
    round_count: int
    cost_cents: CostCents
    attempt_refs: tuple[CoverageAttemptId, ...]
    claim_refs: tuple[ClaimId, ...]
    reason_code: str
    reason_detail: str


class ResearchCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    project_run_id: ProjectRunId | None = None
    fields: tuple[ResearchCoverageField, ...]


class ResearchAttemptHistoryItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: CoverageAttemptId
    round: int
    strategy_key: str
    source_family: str | None
    outcome: str
    stop_reason: str
    reason_detail: str | None
    cost_cents: CostCents
    claim_refs: tuple[ClaimId, ...]


class ResearchAttemptHistory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    entity_id: EntityId
    field_key: str
    attempts: tuple[ResearchAttemptHistoryItem, ...]


class ResearchEvaluatorAdviceItem(BaseModel):
    """Body-free, explicitly non-authoritative evaluator projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluator_advice_id: CoverageEvaluatorAdviceId
    round: int
    proposal_kind: str
    planned_fields: tuple[str, ...]
    valid: bool
    answering_model: str
    prompt_version: str
    sufficient_for_goal: bool | None
    recommendations: tuple[str, ...]
    warning_codes: tuple[str, ...]
    non_authoritative: bool


class ResearchEvaluatorAdviceHistory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    entity_id: EntityId
    items: tuple[ResearchEvaluatorAdviceItem, ...]


async def research_coverage(
    *,
    conn_factory: ConnFactory,
    workspace_id: str,
    run_id: RunId,
    project_run_id: ProjectRunId | None = None,
    entity_id: EntityId | None = None,
) -> ResearchCoverage | None:
    async with conn_factory() as conn:
        attempts = await list_attempts(
            conn, workspace_id=workspace_id, run_id=run_id, entity_id=entity_id
        )
        decisions = await list_decisions(
            conn, workspace_id=workspace_id, run_id=run_id, entity_id=entity_id
        )
    if project_run_id is not None:
        attempts = [item for item in attempts if item.project_run_id == project_run_id]
        decisions = [item for item in decisions if item.project_run_id == project_run_id]
    if not attempts and not decisions:
        return None
    by_field: dict[tuple[EntityId, str], list[object]] = defaultdict(list)
    for item in attempts:
        by_field[(item.entity_id, item.field_key)].append(item)
    latest = {(item.entity_id, item.field_key): item for item in decisions}
    fields: list[ResearchCoverageField] = []
    for key, _raw in sorted(by_field.items(), key=lambda pair: (str(pair[0][0]), pair[0][1])):
        typed = [item for item in attempts if (item.entity_id, item.field_key) == key]
        decision = latest.get(key)
        if decision is None:
            continue
        fields.append(
            ResearchCoverageField(
                entity_id=key[0],
                field_key=key[1],
                terminal_status=decision.terminal_status,
                round_count=max(item.round for item in typed),
                cost_cents=sum((item.cost_cents for item in typed), start=CostCents(0)),
                attempt_refs=tuple(item.id for item in typed),
                claim_refs=tuple(ref for item in typed for ref in item.claim_refs),
                reason_code=decision.reason_code,
                reason_detail=decision.reason_detail,
            )
        )
    return ResearchCoverage(run_id=run_id, project_run_id=project_run_id, fields=tuple(fields))


async def research_attempt_history(
    *,
    conn_factory: ConnFactory,
    workspace_id: str,
    run_id: RunId,
    entity_id: EntityId,
    field_key: str,
) -> ResearchAttemptHistory | None:
    async with conn_factory() as conn:
        attempts = await list_attempts(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            entity_id=entity_id,
            field_key=field_key,
        )
    if not attempts:
        return None
    return ResearchAttemptHistory(
        run_id=run_id,
        entity_id=entity_id,
        field_key=field_key,
        attempts=tuple(
            ResearchAttemptHistoryItem(
                attempt_id=item.id,
                round=item.round,
                strategy_key=item.strategy_key,
                source_family=item.source_family,
                outcome=item.outcome.value,
                stop_reason=item.stop_reason,
                reason_detail=item.reason_detail,
                cost_cents=item.cost_cents,
                claim_refs=item.claim_refs,
            )
            for item in attempts
        ),
    )


async def research_evaluator_advice_history(
    *,
    conn_factory: ConnFactory,
    workspace_id: str,
    run_id: RunId,
    entity_id: EntityId,
) -> ResearchEvaluatorAdviceHistory | None:
    async with conn_factory() as conn:
        advices = await list_evaluator_advices(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            entity_id=entity_id,
        )
    if not advices:
        return None
    return ResearchEvaluatorAdviceHistory(
        run_id=run_id,
        entity_id=entity_id,
        items=tuple(
            ResearchEvaluatorAdviceItem(
                evaluator_advice_id=item.id,
                round=item.round,
                proposal_kind=item.proposal_kind.value,
                planned_fields=item.planned_fields,
                valid=item.valid,
                answering_model=item.answering_model,
                prompt_version=item.prompt_version,
                sufficient_for_goal=(
                    item.result.sufficient_for_goal if item.result is not None else None
                ),
                recommendations=(
                    tuple(value.recommendation.value for value in item.result.assessments)
                    if item.result is not None
                    else ()
                ),
                warning_codes=(
                    tuple(
                        warning.value
                        for value in item.result.assessments
                        for warning in value.warning_codes
                    )
                    if item.result is not None
                    else ()
                ),
                non_authoritative=item.non_authoritative,
            )
            for item in advices
        ),
    )


__all__ = [
    "ResearchCoverageField",
    "ResearchCoverage",
    "ResearchAttemptHistoryItem",
    "ResearchAttemptHistory",
    "ResearchEvaluatorAdviceItem",
    "ResearchEvaluatorAdviceHistory",
    "research_coverage",
    "research_attempt_history",
    "research_evaluator_advice_history",
]
