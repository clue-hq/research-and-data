# 2026-07-26 — C6.7 governed per-account research agent

## Outcome

C6.7 is complete on `platform/c6-deepagent-runtime`. The governed account-research deepagent is a
bounded `ProfileAccountFn` replacement inside the existing admitted fleet slot; it is not a
second fleet or research pipeline. The C1 engine `GoalJudge` is the sole independent coverage
evaluator. C6.8 remains responsible for default-off API-root composition, workspace/canary
routing, comparative agent-versus-mechanical activation, and operational close-out.

## Implemented

- Added immutable `account-research@v1` prompt/profile and progressively disclosed
  `account-gap-research@v1` skill. The role has exactly `research_account_gaps@2`, no provider or
  claim-store access, and no delegation in v1.
- Added `account-research-unit@v1`, an internal standing C5 recipe with one-child fan-out, exact
  project/account/registry/coverage pins, operation identity, and the
  `account_research_interactions` authority gate.
- Added the replay-certified v2 gap tool with explicit durable rounds, typed advice receipts,
  truthful at-least-once external-boundary declaration, stale/skipped/terminal-field rejection,
  and exact operation-id replay.
- Added the real account-agent runtime over the existing C6 deepagent loop, per-role governed
  model, isolated workspace and immutable resources, seven-layer context contract, C5 adapter,
  checkpointer, durable turn receipts, and honest finalization authority.
- Added `GovernedAccountProfiler` and the injection seam on `build_deep_phase_handler`. The
  scheduler, leases/fencing, account plan/envelope, pre-spend gate, waterfall, claim/provenance
  path, verification, committee/contact stages, controls, and recovery stay in the existing
  mechanical shell. Default behavior is unchanged until C6.8 routes a canary.
- Added append-only `coverage_evaluator_advice` plus decision linkage. Round-boundary and agent
  stop-proposal assessments are typed, body-free in projection, and
  `non_authoritative=true`. A stop proposal creates no attempt or decision; malformed advice
  cannot terminalize research.
- Added a completion guard requiring every initially planned field to have an engine-authored
  terminal decision. Partial/failed agent turns cannot advance committee/contact work.
- Coverage spend remains booked by C1. The outer account stage records a zero-cost anchor and
  reloads authoritative cost, preventing duplicate spend on success or restart.
- Updated Doc A, the C6 child spec, implementation plan, and prompt/skill/profile maintainer guide.

## Ownership decisions

- Sole evaluator owner: `c1.engine.goal_judge`.
- Sole production construction site: `build_c1_coverage_evaluator` in
  `platform/api/clue_api/coverage_tools.py`.
- The account agent chooses only a planned gap subset, an admitted strategy hint, or whether to
  submit a stop proposal. It cannot judge its own sufficiency or author terminal coverage.
- V1 has no facet subagent. Add one only if comparative evals show a quality/coverage gain that
  justifies the extra context and envelope complexity.

## Verification

- Dedicated-clean-Postgres full suite: 2,583 passed, 20 skipped.
- Focused account/registry/recipe/coverage/deep-spend tests passed, including explicit-round
  replay, stop-proposal non-authority, malformed advice, append-only mutation rejection,
  body-free projection, no-double-charge, and no false phase advance.
- Ruff format/check passed across 849 tracked/source files with the unrelated untracked
  `.claude/` and `.codex/` directories excluded.
- Mypy: 416 source files clean.
- Import-linter: 24 contracts kept, 0 broken across 477 files and 3,405 dependencies.
- Alembic head-to-base-to-head smoke passed on a fresh disposable database; exactly one head:
  `6e30fac321bf`.
- `git diff --check` passed.
- Raw `make check` remains blocked only because Ruff discovers pre-existing T201 `print` findings
  in the unrelated untracked `.claude/` and `.codex/` skill copies. Those files, the user-owned
  `platform/agents/clue_agents/model.py`, scripted-model memory note, and research-model-surface
  document were left untouched and unstaged.

## Test-environment note

The Docker database was shadowed by a local Postgres listener on port 5432. Verification used the
explicit disposable local database `clue_c67_dar_es_salaam` under the local user, then removed
both the local and same-named Docker database. A second suite invocation against a previously
populated database produced expected cross-test registry/migration contamination; resetting the
disposable database restored the clean full-suite result.

## Next

Proceed with C6.8 only: construct the prepared account turn at the API root, add default-off
workspace allowlist/percentage routing, prove single ownership and mechanical fallback, compare
coverage/promotable evidence/verification/cost/rounds/recovery before enabling cohorts, add
telemetry/cleanup/runbook/projections, and run the final adversarial and repository close-out
battery.
