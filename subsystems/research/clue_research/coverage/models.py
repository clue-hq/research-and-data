"""Typed rows and engine value objects for Phase-C research coverage."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from clue_core import (
    ClaimId,
    CostCents,
    CoverageAttemptId,
    CoverageDecisionId,
    EntityId,
    EntityType,
    ProjectRunId,
    ResearchAttemptOutcome,
    ResearchTerminalStatus,
    RunId,
    UtcDatetime,
)
from clue_core.field import FieldKey


class CoverageAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CoverageAttemptId
    workspace_id: str
    run_id: RunId
    project_run_id: ProjectRunId | None = None
    entity_id: EntityId
    entity_type: EntityType
    field_key: FieldKey
    tier: str
    round: int = Field(ge=1)
    strategy_key: str
    source_family: str | None = None
    outcome: ResearchAttemptOutcome
    stop_reason: str
    reason_detail: str | None = None
    cost_cents: CostCents = Decimal(0)
    claim_refs: tuple[ClaimId, ...] = ()
    quality_mode: str | None = None
    created_at: UtcDatetime | None = None


class CoverageDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CoverageDecisionId
    workspace_id: str
    run_id: RunId
    project_run_id: ProjectRunId | None = None
    entity_id: EntityId
    entity_type: EntityType
    field_key: FieldKey
    tier: str
    round: int = Field(ge=1)
    terminal_status: ResearchTerminalStatus | None = None
    next_strategy_key: str | None = None
    reason_code: str
    reason_detail: str
    attempt_refs: tuple[CoverageAttemptId, ...] = ()
    claim_refs: tuple[ClaimId, ...] = ()
    judge_model: str | None = None
    judge_prompt_version: str | None = None
    created_at: UtcDatetime | None = None


class ResearchStrategy(BaseModel):
    """Stable executable strategy dimensions; prose is deliberately absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    source_family: str
    source_tiers: frozenset[int] = frozenset()
    modalities: frozenset[str] = frozenset()
    query_scope: str
    worker_route: str = "waterfall"

    @property
    def dimensions(self) -> tuple[str, tuple[int, ...], tuple[str, ...], str, str]:
        return (
            self.source_family,
            tuple(sorted(self.source_tiers)),
            tuple(sorted(self.modalities)),
            self.query_scope,
            self.worker_route,
        )


class GoalJudgeRecommendation(StrEnum):
    """Advisory sufficiency finding; never an executable research plan."""

    CONTINUE = "continue"
    RECONSIDER = "reconsider"
    PROPOSE_STOP = "propose_stop"


class GoalJudgeWarning(StrEnum):
    """Closed warning vocabulary safe for engine validation and projections."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LOW_EXPECTED_VALUE = "low_expected_value"
    DUPLICATIVE_SEARCH = "duplicative_search"
    GOAL_APPEARS_SATISFIED = "goal_appears_satisfied"
    EVALUATOR_UNCERTAIN = "evaluator_uncertain"


class GoalJudgeAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    meaningful_gap_remaining: bool
    recommendation: GoalJudgeRecommendation
    warning_codes: tuple[GoalJudgeWarning, ...] = ()
    rationale: str


class GoalJudgeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assessments: tuple[GoalJudgeAssessment, ...]
    sufficient_for_goal: bool


class GoalJudgeCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: GoalJudgeResult | None
    answering_model: str
    prompt_version: str
    cost_cents: CostCents = Decimal(0)
    valid: bool = True


class RoundResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    round: int
    attempt_ids: tuple[CoverageAttemptId, ...] = ()
    decision_ids: tuple[CoverageDecisionId, ...] = ()
    claim_refs: tuple[ClaimId, ...] = ()
    remaining_gap_count: int = 0
    terminal: bool = False
    replayed: bool = False
