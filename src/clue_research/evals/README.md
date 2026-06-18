# `clue_research/evals/` — Test + eval-harness scaffold (M0.6)

**Status:** implemented by M0.6 (ENG-127). **Spec:** [`docs/specs/M00-foundations-and-shared-contracts.md` §M0.6](../../../docs/specs/M00-foundations-and-shared-contracts.md)

The accuracy-defence machinery (substrate §6): score the claims a research run produced against a
hand-verified **gold set**, with a swappable **rubric battery** and a swappable **faithfulness judge**.
M0.6 ships the frame + deterministic stubs (CI makes no live LLM/provider calls); M9/M11 fill in the
real gold set and the production judge.

- `models.py` — gold-set fixture format (`GoldSet`/`GoldEntity`/`GoldClaim`) + result/metric shape
  (`RubricScore`/`EvalReport`, the verification-health pass-rate shape, Doc C §6).
- `scorers.py` — the rubric battery behind a `Scorer` seam: factual accuracy, citation validity, source quality.
- `judge.py` — the `Judge` seam + `StubJudge`/`GroundedStubJudge` (deterministic, no LLM).
- `harness.py` — `EvalHarness(scorers, judge).run(gold, produced) -> EvalReport`.
- `fixtures.py` — `stub_gold_set()` (a tiny deterministic gold + produced-claims pair).
- `conformance.py` — `assert_resolver_conformance` / `assert_valid_source_manifest` (the fixtures
  every future component's tests call to prove it honours an M0 seam).

## Regression-on-swap workflow

`make eval` (or `python -m clue_research.evals`) scores the stub gold set with two different judges and
prints the per-rubric **delta** — the signal that a model/resolver/judge swap moved quality. To
regression-test a swap before merge: run the harness with the current component, run it with the
candidate, and compare `EvalReport.delta`. Any drop is visible before it lands.

## Modular boundary

`evals` imports only `core` (and stdlib/pydantic). It is consumed by later milestones (M9/M11 fill the
gold set + judge); it imports no provider SDK and is not imported by `core`/`config`/`obs`. Enforced by
the import-linter contracts in `pyproject.toml`.
