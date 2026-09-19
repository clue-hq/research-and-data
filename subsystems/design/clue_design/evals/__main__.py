"""Exit-judgment golden-set DEMO (``make eval-design-exit``) — offline, no live calls.

Prints the decision baseline (the fixtures' canned judgments through the fail-safe
envelope — the same thing the ``make check`` gate asserts passes 100%), then scores two
deliberately weakened judges and shows :func:`check_exit_regressions` naming what broke.
Like ``make eval-verification``, this is a demonstration of the machinery and **always
exits 0**; the enforced swap-gate is the same functions run over a REAL judge's verdicts
against a stored baseline when the P3.7 orchestrator bridge lands.
"""

from __future__ import annotations

from clue_design.evals.golden import (
    ExitGoldenFixture,
    GoldenReport,
    check_exit_regressions,
    run_decision_golden,
    score_judge,
)
from clue_design.exit_judgment import ExitJudgment


def _print(title: str, report: GoldenReport) -> None:
    print(f"\n{title}: {report.passed}/{report.total} (pass rate {report.pass_rate:.2f})")
    for kind, (passed, total) in sorted(report.by_kind.items()):
        print(f"  {kind:16s} {passed}/{total}")
    for failure in report.failures:
        print(f"  FAIL {failure}")


def main() -> int:
    baseline = run_decision_golden()
    _print("decision baseline (canned judgments)", baseline)

    def never_exits(_fixture: ExitGoldenFixture) -> ExitJudgment:
        return ExitJudgment(close_this_session=False, reasoning="keep going")

    def always_locks(_fixture: ExitGoldenFixture) -> ExitJudgment:
        return ExitJudgment(
            close_this_session=True, current_artifact_accepted=True, reasoning="locked"
        )

    for name, judge in (("never-exits", never_exits), ("always-locks", always_locks)):
        report = score_judge(judge)
        _print(f"weakened judge: {name}", report)
        for sentence in check_exit_regressions(baseline, report):
            print(f"  REGRESSION {sentence}")

    print("\ndemo only: always exits 0 (the enforced gate scores a real judge vs a baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
