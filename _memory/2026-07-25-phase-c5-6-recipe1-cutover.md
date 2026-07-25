# C5.6 — Recipe #1 cutover and run views

## Final state

- C5.6 is implemented on `platform/c5-recipe-execution`; C5.0–C5.6 are now complete.
- System Recipe #1 v2 is executable and promoted. It contains one exact
  `advance_project_phase@1` node for each `ProjectPhase` and calls the existing
  `ProjectRun.advance` implementation rather than duplicating phase logic.
- A retryable external-wait outcome abandons only the current attempt, pauses the graph, and keeps
  the logical node resumable. Tier, deep-canary, and review checkpoint decisions resume the
  Recipe-owned graph; unowned runs retain the legacy queue path.
- Recipe #0 confirmed entry validates and freezes the immutable Client-KB, ICP, product-context,
  readiness, project, project-run, registry, and supervisor-policy resources. Reverse-profiling
  and ICP-confirmed graph nodes are born complete only for a complete Stage-0 lineage.
- Stage-0 lineage detection is based on the immutable lineage tuple, not the run's mutable current
  phase. This keeps start-tool replay stable after the run advances.
- New-run routing is disabled by default and supports an explicit workspace allowlist or a
  deterministic workspace percentage. Existing unowned runs are not backfilled.
- The execution reader now exposes project-run ownership, full graph/timeline/pins/artifacts, recipe
  library lifecycle plus live compatibility, and supervision/control history. Effective controls
  include only the latest still-active state.
- The A4 manifest renders journal nodes, dependencies, statuses, and pins when an execution owner
  exists, and retains the legacy synthetic phase/account view otherwise.
- The test/eval-only canonical outcome fingerprint includes pin roles, phase/gate decisions,
  attempted/filled fields, coverage gaps, verification categories, controls, and cost/yield bands
  while excluding ids, timestamps, prose, unordered refs, and token counts.

## Integration details

- Toolbelt inventory is 32 tools after adding `submit_project_checkpoint@1`; the standing
  Recipe-#0/#1 replay audit also includes `advance_project_phase@1`.
- The fleet composition root registers execution-control tools before system recipe seeding, then
  binds a deferred project-execution router. This breaks the boot dependency cycle without a
  second executor or driver.
- Runtime settings added:
  `CLUE_RECIPE1_ROUTING_ENABLED`, `CLUE_RECIPE1_WORKSPACE_ALLOWLIST`,
  `CLUE_RECIPE1_CANARY_PERCENT`, `CLUE_RECIPE1_SUPERVISOR_POLICY_VERSION`, and
  `CLUE_RECIPE_EXECUTOR_MAX_CONCURRENCY`.
- No database migration was required in C5.6. The existing single head remains
  `ed7a01cd8845`.
- Scripts 01–06 exposed a post-workspace-localization residual: they accepted `workspace_id` but
  did not ensure the workspace or stamp seeded accounts. `scripts/script_support.py` now owns that
  shared setup and every account seed is workspace-local.

## Verification

- Focused C5 integration suites are green: tool contracts/toolbelt, recipes, executor, journal,
  controls, Recipe #0 regression, Recipe #1 cutover/parity, projections, and SSE replay.
- Clean full suite: 2,456 collected; 2,436 passed and 20 skipped.
- `ruff format --check` and `ruff check` pass for the repository when the unrelated untracked
  `.claude/` and `.codex/` skill copies are excluded; `mypy` passes across 393 source files;
  import-linter keeps all 24 contracts.
- Scripts 01–06 pass as one chained offline run.
- Clean throwaway Postgres migration smoke passes head → base → head; `alembic heads` reports only
  `ed7a01cd8845`.
- The first dirty-database repository attempt correctly failed migration downgrade because prior
  crash-harness executions contained pre-materialized C5.3 nodes; two discovery counts saw the
  same committed fixtures. Resetting only the dedicated throwaway database produced the clean
  green run. One fixed-30-second SIGKILL subprocess timed out under the first loaded run, then
  passed both alone and in the clean full suite.

## C6 handoff

- Consume the C5 graph-append, exact pin, parameter-artifact, authority, execution-owner,
  checkpoint, supervision, and historical-view seams; do not add another orchestration stack.
- Decide the final owner of C1's advisory coverage evaluator and preserve one evaluator only.
- Recipe #1 routing remains disabled by default. Enabling a production workspace is an operational
  rollout decision, not a code-completion step.
- Preserve the legacy unowned-run fallback until an explicit retirement/backfill policy is
  separately approved.
