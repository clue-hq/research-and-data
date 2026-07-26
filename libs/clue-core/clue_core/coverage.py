"""Shared Phase-C research-coverage contracts.

Coverage records effort and stopping decisions by reference. Claim values remain exclusively in
the claim store; these types are the small cross-lane vocabulary C4/C7 may safely consume.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict

from clue_core.field import FieldKey
from clue_core.primitives import EntityId, ProjectRunId, RunId

CoverageAttemptId = NewType("CoverageAttemptId", UUID)
CoverageDecisionId = NewType("CoverageDecisionId", UUID)
CoverageEvaluatorAdviceId = NewType("CoverageEvaluatorAdviceId", UUID)

_COVERAGE_EVALUATOR_ADVICE_NAMESPACE = UUID("3bb28fe2-1151-5f89-a044-d81cc3265f5c")


def new_coverage_attempt_id() -> CoverageAttemptId:
    return CoverageAttemptId(uuid4())


def new_coverage_decision_id() -> CoverageDecisionId:
    return CoverageDecisionId(uuid4())


def coverage_evaluator_advice_id(
    *,
    run_id: RunId,
    entity_id: EntityId,
    tier: str,
    round: int,
    proposal_kind: str,
) -> CoverageEvaluatorAdviceId:
    """Derive the append-only evaluator row identity from its complete logical boundary."""

    return CoverageEvaluatorAdviceId(
        uuid5(
            _COVERAGE_EVALUATOR_ADVICE_NAMESPACE,
            f"{run_id}:{entity_id}:{tier}:{round}:{proposal_kind}",
        )
    )


class ResearchAttemptOutcome(StrEnum):
    CLAIMS_PRODUCED = "claims_produced"
    NO_HIT = "no_hit"
    BLOCKED = "blocked"
    BUDGET_STOP = "budget_stop"
    FAILED = "failed"


class ResearchTerminalStatus(StrEnum):
    FILLED = "filled"
    UNFILLED_TERMINAL = "unfilled_terminal"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ResearchGapRef(BaseModel):
    """Reference-only description of one field gap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    project_run_id: ProjectRunId | None = None
    entity_id: EntityId
    field_key: FieldKey
    tier: str
    terminal_status: ResearchTerminalStatus | None = None
    latest_attempt_id: CoverageAttemptId | None = None


__all__ = [
    "CoverageAttemptId",
    "CoverageDecisionId",
    "CoverageEvaluatorAdviceId",
    "ResearchAttemptOutcome",
    "ResearchTerminalStatus",
    "ResearchGapRef",
    "new_coverage_attempt_id",
    "new_coverage_decision_id",
    "coverage_evaluator_advice_id",
]
