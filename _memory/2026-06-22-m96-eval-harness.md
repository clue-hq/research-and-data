# 2026-06-22 — M9.6 Eval harness + golden account set + rubric scoring (ENG-156)

## State: DONE (impl + 4-dimension adversarial review workflow + skeptic-verify + completeness critic + fixes); awaiting user review
Branch `m9/verification-layer`. The 6th and **final** M9 issue. Migration `015474d0a18c` off the M9.5
head `cb39832d29bb`. `make check` green (lint/format/mypy/import-linter **11/0** — added the new
"evals is a core-only leaf" contract; 481 passed). **23/23** M9.6 tests (19 pure + 4 DB-gated) +
full verification + M0.6 evals suites green on docker `clue-m9-pg` (5433); db-smoke up→down→up
reversible, single head `015474d0a18c`; `make eval` + `make eval-verification` demos run offline
(no DB, no live LLM). M9.6 *fills* the M0.6 eval scaffold (`clue_research.evals`, ENG-127) with the
real verification battery; it does NOT replace it.

## Adversarial audit (4-dimension review workflow + skeptic-verify + completeness critic) — outcome
A background Workflow ran 4 parallel dimension reviewers (correctness / spec-conformance /
architecture / data-integrity) → per-finding skeptic-verify → a completeness critic. 9 confirmed
findings + 5 critic gaps. **One critic gap was BUILD-BREAKING: a review subagent edited
`evals/models.py` to inject two "adversarial-probe" imports (`from clue_research.claimstore …`,
`from clue_research.verification import GOLD_SUITE`) — a live circular import that broke every
importer of `evals`. Reverted immediately** (the agents were given edit tools by mistake). **Fixed
in this PR:**
1. **[MED] `evals` core-only invariant was documented but NOT machine-enforced** — added import-linter
   Rule 7 ("the eval scaffold (evals/) is a core-only leaf"; forbids evals→claimstore/verification/
   gateway/db/…). Now 11 contracts; this would have caught the probe edit. **High-value structural fix.**
2. **[LOW correctness] `requires_evidence_span` dropped on the golden_fixture round-trip** — added the
   column to the migration + seed/load; the round-trip test now asserts **full GoldClaim equivalence**
   AND **score-equivalence** (scoring the produced pack against the DB-loaded gold == against the
   in-code gold), the loader's documented purpose.
3. **[LOW spec] AC2 per-rubric spans missing** — the base M0.6 runner emits no spans; added a
   `verification.eval.rubric` span per rubric; the span test asserts it.
4. **[LOW spec] AC7 config snapshot thin** — added `corroboration_threshold` + `freshness_cadence_version`
   (via a new `FreshnessImpl.policy` accessor) to the default snapshot; the eval_run test asserts them.
5. **[MED integrity] `eval_cli` named a "gate" but always exits 0** — relabelled it a **demo** (Makefile +
   banner), and added the `regression_exit_code(report)` primitive (the real fail-on-regression command
   is wired at the api root against a stored `eval_run` baseline). Added `test_regression_exit_code` +
   `test_eval_cli_demo_runs`.
6. **[LOW critic] faithfulness precision rested on one tier-4 positive** — added a 2nd faithful tier-4
   positive (`account.resonance.sentiment`) so precision is exercised over >1 sample.
7. **[LOW integrity] `sample_promoted_claims` unbounded scan** — added a `max_scan` LIMIT (bounded memory).
**Deferred to backlog (CLAUDE.md/AGENTS.md):** scalar-jsonb decoder DRY (nit — 3 copies; consolidate
with the M9.4 `normalize_host` item); gate-block/corroboration are scenario-driven not golden-fixture
(spec's own 4-kind taxonomy — extend when the taxonomy grows); `entity_type` re-derived (heuristic)
on fixture load.

## Original design (locked) — unchanged below
Branch `m9/verification-layer`. The 6th and **final** M9 issue. Migration off the M9.5 head
`cb39832d29bb`. M9.6 *fills* the M0.6 eval scaffold (`clue_research.evals`, ENG-127) with the real
verification battery; it does NOT replace it.

## The load-bearing architecture decision: WHERE the battery lives (import-linter)
- `clue_research.evals` (M0.6) is the **generic, core-only frame**: `GoldSet`/`GoldEntity`/
  `GoldClaim`, the `Scorer` + `Judge` protocols, `StubJudge`/`GroundedStubJudge`, the 3 deterministic
  scorers, `EvalHarness(scorers, judge).run(gold, actual) -> EvalReport`, `EvalReport.delta` (the
  regression-on-swap signal). **It imports only `core`** (documented invariant). So the DB-backed and
  gateway-backed parts of M9.6 **cannot** live in `evals`.
- `clue_research.verification` (M9) **may import `evals`** (evals is NOT in the worker-independence
  list — verified in pyproject `[tool.importlinter]`), plus `claimstore`/`config`/`obs`/`db`/`core`/
  `identity`. So the M9.6 verification battery lives in `verification/` (consistent with M9.1–M9.5),
  reusing the `evals` frame.
- The LLM rubric scorers / judge take an **injected `core.gateway.LLMGateway`** (the gate impls never
  import `clue_research.gateway`, mirroring M9.3). Offline (CI / `make eval`) injects the
  deterministic `StubGateway` (via `gateway.build_gateway`, which returns the stub when no
  `OPENROUTER_API_KEY`) — **no live LLM calls**, the M0.6 acceptance.

⇒ Split: pure data **shapes** are extended in `evals/models.py` (core-only); DB/LLM **behaviour**
lives in `verification/`.

## Dual-plane (mirrors M9.1–M9.5: pure tests + DB-gated tests)
- **Offline plane** (in `make check`, no DB, no live LLM): the harness + the 5 mechanism metrics run
  the **pure classifiers** — `verification.classify_binding` (M9.4), `verification.staleness` /
  `FreshnessImpl().evaluate` (M9.5), `verification.values_agree`/`independent_source_count` (M9.2),
  and the `evals.Judge` seam (`StubJudge`/`GatewayJudge`+`StubGateway`) for M9.3 — over an in-code
  `GoldPack` (planted positive + negative scenarios). Proves every AC offline.
- **DB plane** (skips without a DSN): `golden_fixture` round-trip (`seed_golden_fixtures` /
  `load_golden_fixtures`), `eval_run` persistence with a config snapshot, the human spot-check
  sampler over the real `claim` store + ingest-back.

## Surfaces
1. **`evals/models.py` (additive, pure-core)** — `FixtureKind` enum (positive / negative_fabrication
   / negative_samename / negative_stale / negative_unsupported); `GoldClaim` gains
   `fixture_kind=POSITIVE`, `mode: ResearchMode|None`, `expected_source_url: str|None`;
   `MechanismMetric{mechanism, detected, expected, false_positive}` (+ `recall`/`precision`);
   `Regression{metric, baseline, current, delta, tolerance, regressed}`; `EvalReport` gains
   `mechanism_metrics=()`, `regressions=()`, `config_snapshot={}` (+ `has_regression`). Defaults keep
   the M0.6 tests green. Mirrors the `FixtureKind` enum in the DB enum (parity-tested).
2. **`verification/golden.py`** — `GoldPack{gold: GoldSet, produced: list[Claim], contacts:
   dict[id,ContactEntity], accounts: dict[id,AccountEntity], now}`: the hand-verified set spanning
   M1 (account_discovery) / M2 (account_profiling) / M3 (committee_discovery) / M4
   (contact_profiling) × field-classes (core/account/account.resonance/contact/contact.facet), with
   positives AND the 4 negative kinds, each negative carrying a *planted produced claim* the relevant
   mechanism must catch. `verification_gold_pack()` builds it. `seed_golden_fixtures(conn, gold)` /
   `load_golden_fixtures(conn) -> GoldSet` round-trip the expectations to/from `golden_fixture`;
   `ingest_golden_fixture(conn, ...)` writes a fixture row (the spot-check loop calls it via
   `ingest_spot_check(conn, sample)` in `eval_harness`).
3. **`verification/eval_harness.py`** — the 5 PURE mechanism-metric computers over a `GoldPack`:
   `identity_binding_metric` (M9.4: every negative_samename produced claim classifies WEAK = recall;
   positives that stay STRONG = no false-positive); `freshness_metric` (M9.5: negative_stale →
   STALE/EXPIRED); `faithfulness_metric` (M9.3 via `evals.Judge`: negative_unsupported/fabrication →
   not entailed); `corroboration_metric` (M9.2: a single-source load-bearing claim is NOT promoted, ≥N
   independent agree → promotable, disagreeing tier≤2 → conflict); `gate_block_metric` (M9.1: a
   doomed request — unknown field / tier-not-in-plan / unresolved entity — is REJECT). The
   `VerificationEvalHarness(scorers, judge)` composes the `evals.EvalHarness` rubric run + the
   mechanism metrics → an extended `EvalReport`. `check_regressions(current, baseline, *, tolerance)
   -> tuple[Regression,...]` (rubric pass-rate or mechanism recall dropping > tolerance = a
   regression; the CI gate fails on any). `record_eval_run(conn, report, config_snapshot)` persists.
   `sample_promoted_claims(conn, *, per_stratum, scope)` = the stratified human-spot-check sampler.
   M9-local spans (`verification.eval.run`/`.mechanism`/`.rubric`) + metrics
   (`research.verification.eval.*`). A weakened `GatewayJudge` variant (or the M0.6 stub pair) gives
   the regression-on-swap demo.
4. **`verification/eval_cli` / `make eval` extension** — keep the M0.6 stub demo; add the M9.6
   verification battery run (offline, `build_gateway` → stub) printing the rubric + mechanism report
   and the regression gate verdict. CI-runnable, no live calls.
5. **Migration** (off `cb39832d29bb`): `golden_fixture {id, entity_ref, field_key,
   expected_value_json jsonb, expected_source_url, expected_tier, fixture_kind <new enum>, mode
   research_mode, created_at}` + `eval_run {id, suite, config_snapshot_json jsonb, started_at,
   report_json jsonb}`. New `fixture_kind` enum (parity-tested vs `evals.FixtureKind`); reuses the
   `research_mode` enum (0002). Reversible; no claim ALTER, no trigger change.
6. **Tests** `tests/verification/test_eval_harness.py` — pure (each mechanism catches its negative;
   regression-on-swap fails; positives not false-flagged; coverage spans all modes × mechanisms) +
   DB-gated (fixture round-trip, eval_run snapshot, spot-check stratified + ingest, fixture_kind enum
   parity).

## Acceptance-criteria → coverage map
- AC golden pos+neg per mode × mechanism → `verification_gold_pack()` + a coverage test.
- AC per-rubric + per-mechanism metrics each with a span → harness emits both, spans asserted.
- AC weakened judge/model → measurable regression + CI gate FAILS → `check_regressions` + stub-pair /
  weakened-`GatewayJudge` test.
- AC swapped resolver wrong value caught by factual-accuracy → a wrong-value produced fixture.
- AC same-name→binding, unsupported→faithfulness, stale→freshness → the 3 mechanism tests.
- AC human spot-check sampler stratified + ingest-back → `sample_promoted_claims` + `ingest_spot_check` DB tests.
- AC eval_run recorded with config snapshot → `record_eval_run` + a load test.

## Out of scope (documented)
- The client-facing verification-health dashboard (M13.4 — M9.6 emits the metrics).
- The disposition feedback / source reweighting (M13.2/M13.3).
- The generic test/CI scaffold itself (M0.6 — M9.6 fills it).
- Running the FULL pipeline to produce claims — the harness scores a provided/loaded claim set
  (offline: the planted GoldPack; DB: the `claim` store).
