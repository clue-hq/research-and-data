"""Phase C1 durable coverage ledger and bounded goal evaluator."""

from clue_research.coverage.controller import (
    DEFAULT_STRATEGIES,
    CoverageController,
    CoveragePolicyError,
)
from clue_research.coverage.judge import GoalJudge
from clue_research.coverage.models import (
    CoverageAttempt,
    CoverageDecision,
    GoalJudgeAssessment,
    GoalJudgeCall,
    GoalJudgeRecommendation,
    GoalJudgeResult,
    GoalJudgeWarning,
    ResearchStrategy,
    RoundResult,
)
from clue_research.coverage.repository import (
    list_attempts,
    list_decisions,
    record_attempt,
    record_decision,
)

__all__ = [
    "CoverageAttempt",
    "CoverageDecision",
    "ResearchStrategy",
    "GoalJudgeAssessment",
    "GoalJudgeRecommendation",
    "GoalJudgeResult",
    "GoalJudgeWarning",
    "GoalJudgeCall",
    "RoundResult",
    "GoalJudge",
    "CoverageController",
    "CoveragePolicyError",
    "DEFAULT_STRATEGIES",
    "record_attempt",
    "record_decision",
    "list_attempts",
    "list_decisions",
]
