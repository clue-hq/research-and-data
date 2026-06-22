"""`clue_research.evals` — test + eval-harness scaffold (M0.6).

The home of the accuracy-defence machinery (substrate §6): a runner scoring the claims a research
run produced against a hand-verified **gold set**, using a swappable **rubric battery** (factual
accuracy / citation validity / source quality) and a swappable **faithfulness judge** — with
deterministic stubs so CI runs with no live LLM/provider calls. M0.6 ships the frame + fixtures;
M9/M11 fill in the real gold set and the production judge.

Exposes the **conformance fixtures** (e.g. `assert_resolver_conformance`) every future component's
tests call to prove it honours an M0 seam. `evals` imports only `core`. Implements
ENG-127 (docs/specs/M00-foundations-and-shared-contracts.md §M0.6).
"""

from __future__ import annotations

from clue_research.evals.conformance import (
    assert_resolver_conformance,
    assert_valid_source_manifest,
)
from clue_research.evals.fixtures import stub_gold_set
from clue_research.evals.harness import FAITHFULNESS_RUBRIC, EvalHarness
from clue_research.evals.judge import GroundedStubJudge, Judge, JudgeVerdict, StubJudge
from clue_research.evals.models import (
    EvalReport,
    FixtureKind,
    GoldClaim,
    GoldEntity,
    GoldSet,
    MechanismMetric,
    Regression,
    RubricScore,
)
from clue_research.evals.scorers import (
    CitationValidityScorer,
    FactualAccuracyScorer,
    Scorer,
    SourceQualityScorer,
    default_scorers,
)

__all__ = [
    # harness
    "EvalHarness",
    "FAITHFULNESS_RUBRIC",
    # gold set + report shapes
    "GoldClaim",
    "GoldEntity",
    "GoldSet",
    "RubricScore",
    "EvalReport",
    "FixtureKind",
    "MechanismMetric",
    "Regression",
    "stub_gold_set",
    # rubric scorers
    "Scorer",
    "FactualAccuracyScorer",
    "CitationValidityScorer",
    "SourceQualityScorer",
    "default_scorers",
    # judge
    "Judge",
    "JudgeVerdict",
    "StubJudge",
    "GroundedStubJudge",
    # conformance fixtures
    "assert_resolver_conformance",
    "assert_valid_source_manifest",
]
