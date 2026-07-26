"""Phase C1 durable coverage ledger and bounded goal evaluator."""

from clue_research.coverage.controller import (
    DEFAULT_STRATEGIES,
    CoverageController,
    CoveragePolicyError,
)
from clue_research.coverage.judge import COVERAGE_EVALUATOR_OWNER, GoalJudge
from clue_research.coverage.models import (
    CoverageAttempt,
    CoverageDecision,
    CoverageEvaluatorAdvice,
    EvaluatorProposalKind,
    GoalJudgeAssessment,
    GoalJudgeCall,
    GoalJudgeRecommendation,
    GoalJudgeResult,
    GoalJudgeWarning,
    ResearchStrategy,
    RoundResult,
)
from clue_research.coverage.repository import (
    get_evaluator_advice,
    list_attempts,
    list_decisions,
    list_evaluator_advices,
    record_attempt,
    record_decision,
    record_evaluator_advice,
)

__all__ = [
    "CoverageAttempt",
    "CoverageDecision",
    "CoverageEvaluatorAdvice",
    "EvaluatorProposalKind",
    "ResearchStrategy",
    "GoalJudgeAssessment",
    "GoalJudgeRecommendation",
    "GoalJudgeResult",
    "GoalJudgeWarning",
    "GoalJudgeCall",
    "RoundResult",
    "GoalJudge",
    "COVERAGE_EVALUATOR_OWNER",
    "CoverageController",
    "CoveragePolicyError",
    "DEFAULT_STRATEGIES",
    "record_attempt",
    "record_decision",
    "record_evaluator_advice",
    "get_evaluator_advice",
    "list_evaluator_advices",
    "list_attempts",
    "list_decisions",
]
