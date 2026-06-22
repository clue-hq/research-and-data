"""Offline verification-eval battery **demo** (``python -m clue_research.verification.eval_cli``).

The runnable, offline form of the M9.6 regression-on-swap *demonstration* (substrate §6): it scores
the hand-verified gold pack with two deterministic stub judges and prints both reports, the
per-metric delta, and what the regression gate *would* do on that judge swap. No database, no live
LLM call (CI-safe — the M0.6 acceptance), and it **always exits 0** — it is a demo, not the gate.

This is deliberately NOT the enforced CI gate: it always swaps in a *deliberately* weaker judge, so
a regression always fires; making it exit non-zero would fail CI on every run. The enforced
fail-on-regression command (which scores the *current* config against a stored ``eval_run`` baseline
and does ``raise SystemExit(regression_exit_code(report))``) is wired at the ``api`` composition
root; the offline proof that the gate machinery fails on a weakened judge is
``tests/.../test_eval_harness.py::test_regression_gate_fails_on_weakened_judge``.
"""

from __future__ import annotations

from clue_research.evals import GroundedStubJudge, StubJudge
from clue_research.verification.eval_harness import VerificationEvalHarness, check_regressions
from clue_research.verification.golden import verification_gold_pack


def main() -> None:
    pack = verification_gold_pack()
    # The baseline is the STRONG judge (grounded — it catches the planted negatives); the candidate
    # is the WEAK judge (the lenient stub — it misses them). Swapping in the weaker judge regresses
    # the faithfulness *mechanism recall*, which the gate must catch (the "weakened judge" AC).
    strong = VerificationEvalHarness(judge=GroundedStubJudge()).run(pack)
    weak = VerificationEvalHarness(judge=StubJudge()).run(pack)

    print(f"baseline  {strong.summary()}")
    print(f"candidate {weak.summary()}")

    print("regression-on-swap (judge: grounded_stub -> stub) per-metric delta:")
    for metric, change in weak.delta(strong).items():
        if change:
            print(f"  {metric}: {change:+.2f}")

    gate = check_regressions(weak, strong, tolerance=0.0)
    if gate:
        print(f"[demo] the gate WOULD FAIL on this swap ({len(gate)} metric(s) dropped):")
        for regression in gate:
            print(f"  {regression.metric}: {regression.baseline:.2f} -> {regression.current:.2f}")
    else:
        print("[demo] no metric dropped beyond tolerance")


if __name__ == "__main__":
    main()
