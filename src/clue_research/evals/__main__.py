"""Run the eval harness against the stub gold set (``python -m clue_research.evals``).

The runnable form of the regression-on-swap demonstration: it scores the stub gold set
with two different stub judges and prints both reports plus the per-rubric delta. CI invokes this
(`make eval`); no live LLM/provider calls are made.
"""

from __future__ import annotations

from clue_research.evals import (
    EvalHarness,
    GroundedStubJudge,
    StubJudge,
    default_scorers,
    stub_gold_set,
)


def main() -> None:
    gold, produced = stub_gold_set()
    scorers = default_scorers()

    lenient = EvalHarness(scorers, StubJudge()).run(gold, produced)
    strict = EvalHarness(scorers, GroundedStubJudge()).run(gold, produced)

    print(lenient.summary())
    print(strict.summary())
    delta = strict.delta(lenient)
    print("regression-on-swap (judge: stub -> grounded_stub) per-rubric delta:")
    for rubric, change in delta.items():
        print(f"  {rubric}: {change:+.2f}")


if __name__ == "__main__":
    main()
