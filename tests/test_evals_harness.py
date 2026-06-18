"""M0.6 acceptance: the eval harness runs end-to-end on the stub gold set and is judge-swappable."""

from __future__ import annotations

from clue_research.evals import (
    FAITHFULNESS_RUBRIC,
    EvalHarness,
    GroundedStubJudge,
    StubJudge,
    default_scorers,
    stub_gold_set,
)


def test_harness_runs_end_to_end_and_emits_per_rubric_metrics() -> None:
    gold, produced = stub_gold_set()
    report = EvalHarness(default_scorers(), StubJudge()).run(gold, produced)

    metrics = report.metrics()
    # the standard rubric battery + the judge rubric are all present
    assert {"factual_accuracy", "citation_validity", "source_quality", FAITHFULNESS_RUBRIC} <= set(
        metrics
    )
    # every metric is a pass-rate in [0, 1]
    assert all(0.0 <= rate <= 1.0 for rate in metrics.values())
    # the deliberately-wrong employee_count value means factual accuracy is NOT perfect — the
    # scorer actually scores (it isn't vacuously 1.0)
    assert metrics["factual_accuracy"] < 1.0
    assert report.judge == "stub"


def test_regression_on_swap_judge_change_moves_the_metrics() -> None:
    gold, produced = stub_gold_set()
    scorers = default_scorers()

    lenient = EvalHarness(scorers, StubJudge()).run(gold, produced)
    strict = EvalHarness(scorers, GroundedStubJudge()).run(gold, produced)

    # the tier-4 claim has a span but its value is not contained in it: lenient judge passes it,
    # strict judge fails it -> a non-zero faithfulness delta (the regression-on-swap signal)
    delta = strict.delta(lenient)
    assert delta[FAITHFULNESS_RUBRIC] != 0.0
    assert lenient.metrics()[FAITHFULNESS_RUBRIC] == 1.0
    assert strict.metrics()[FAITHFULNESS_RUBRIC] == 0.0
    # the deterministic, claim-only rubrics are unchanged by the judge swap
    assert delta["factual_accuracy"] == 0.0
    assert delta["source_quality"] == 0.0
