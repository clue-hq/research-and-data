"""The eval-harness runner (M0.6).

Runs the rubric battery + the faithfulness judge over a gold set vs. the claims a run produced, and
reports per-rubric metrics. Both the scorers and the judge are swappable (the regression-on-swap
seam): re-point either and compare the reports' :meth:`EvalReport.delta` to see whether a model or
resolver swap moved the numbers before it merges (substrate §6).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from clue_core import Claim, EntityId
from clue_research.evals.judge import Judge
from clue_research.evals.models import EvalReport, GoldSet, RubricScore
from clue_research.evals.scorers import Scorer

FAITHFULNESS_RUBRIC = "faithfulness"


class EvalHarness:
    """Scores produced claims against a gold set. Scorers + judge are injected (swappable)."""

    def __init__(self, scorers: Sequence[Scorer], judge: Judge) -> None:
        self._scorers = tuple(scorers)
        self._judge = judge

    def run(self, gold: GoldSet, actual: Iterable[Claim]) -> EvalReport:
        index: dict[tuple[EntityId, str], Claim] = {
            (claim.entity_id, claim.field_key): claim for claim in actual
        }
        # per rubric: [scored, passed]
        tally: dict[str, list[int]] = {scorer.name: [0, 0] for scorer in self._scorers}
        tally[FAITHFULNESS_RUBRIC] = [0, 0]

        for entity in gold.entities:
            for gold_claim in entity.claims:
                produced = index.get((entity.entity_id, gold_claim.field_key))
                for scorer in self._scorers:
                    tally[scorer.name][0] += 1
                    if scorer.passed(produced, gold_claim):
                        tally[scorer.name][1] += 1
                # the judge scores only tier-4 (synthesized) claims that were actually produced
                if produced is not None and produced.source_tier == 4:
                    tally[FAITHFULNESS_RUBRIC][0] += 1
                    if self._judge.judge(produced).entailed:
                        tally[FAITHFULNESS_RUBRIC][1] += 1

        scores = tuple(
            RubricScore(rubric=name, scored=scored, passed=passed)
            for name, (scored, passed) in tally.items()
        )
        return EvalReport(gold_set=gold.name, judge=self._judge.name, rubric_scores=scores)
