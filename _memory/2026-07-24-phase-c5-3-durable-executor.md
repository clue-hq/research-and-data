# 2026-07-24 — Phase C5.3 durable executor and generic fleet

## Scope and branch

- Implemented on `platform/c5-recipe-execution` after C5.2 commit `88b08d9`.
- Binding authority:
  `docs/specs/PC-C5-run-graph-recipes-executor.md` and
  `docs/superpowers/plans/2026-07-24-phase-c5-run-graph-recipes-executor.md` §5.
- C5.3 does not migrate Recipe #0/#1, add supervisor controls, or expose cancellation.

## Implemented

- Migration `d9b39fb407ed` adds `execute_graph`, renames fleet-private run keys to generic
  `work_id`, adds monotone lease generations, lease-stamped execution cursors, execution parameter
  artifact ownership, and immutable materialized-node scheduling fields. Upgrade/downgrade is
  reversible on a clean database and downgrade fails loud when C5.3 graph data would be lossy.
- `clue_fleet` now has `WorkId`, `WorkQueue`, `WorkLeaseStore`, `WorkHandler`, and
  `LeasedWorkWorker`. One fair worker drains both legacy `drive_run` and `execute_graph`; all
  project-run exports remain compatibility adapters. Legacy exit/restart behavior is unchanged.
- `DbExecutionStarter` accepts only promoted executable revisions at the supported protocol,
  validates governed parameter artifacts, resolves every exact compatibility pin before creating
  an execution/task, stores the resolved pins, materializes static nodes/edges, and atomically
  claims the one Recipe-#1 project-run owner.
- `RecipeExecutor` provides deterministic ready order, bounded concurrency, stable operation ids,
  lease-fenced cursor/event writes, cursor rebuild, abandoned-attempt recovery, fail-fast terminal
  policy, pause/resume, actor-bound idempotent gates, barriers/activities, and append-only bounded
  map expansion. Dynamic map children re-check the declaring map's promoted compatibility key.
- The production tool invoker exposes crash hooks around attempt start, tool dispatch, domain
  commit, and completion. Journal hooks cover event insert and cursor projection. Cancellation/
  fencing leaves attempts visibly unterminated for recovery rather than falsely failed.
- Typed controls now register at the API root:
  `start_recipe_execution`, `pause_recipe_execution`, `resume_recipe_execution`,
  `decide_recipe_gate`, `pin_execution_as_recipe`, and `advance_project_phase`. Steering controls
  are descriptor-rejected without display-safe audit snapshots. Pinning an ad-hoc execution
  parameterizes every selected display-safe input instead of copying hidden bodies.
- Resume-run, tier-checkpoint, and review-finalize surfaces route to the owning recipe execution
  when one exists and otherwise re-offer the legacy drive. The legacy handler refuses an owned run,
  preventing two drivers from racing.

## Crash/replay evidence

- Real subprocess SIGKILL/restart tests cover:
  `after_attempt_start`, `before_tool`, `after_domain_commit`,
  `after_completion_event`, `after_event_insert`, and `after_cursor_update`.
  The certified test tool records one provider/domain invocation and one idempotent effect.
- Transactional crash hooks additionally cover map expansion and committed gate decisions.
- Database tests cover stale lease-generation rejection, monotone takeover, abandoned-attempt
  recovery, gate authority/idempotence, stable map ordering, and generic dual-kind draining.
- The original 500-account real SIGKILL fleet exit gate remains green after the schema
  generalization.

## Verification and failures resolved

- `make db-smoke`: clean upgrade → base → head, green.
- Alembic has one head: `d9b39fb407ed`.
- Ruff format/lint, mypy, and all 24 import contracts: green.
- Focused execution/fleet/API database suites: green.
- Full repository pytest on a clean dedicated database: green through 100%; expected
  external-service cases skipped.
- The first full run against the reused default database failed because old test data made historic
  downgrades non-reversible; final verification used a clean per-branch database as required.
- The first clean run exposed one pre-existing system-seed assertion that counted every recipe
  event globally. It now scopes to the two seeded revision ids, so ad-hoc recipes can coexist.
- The fleet exit test had one remaining raw `project_run_id` query, and the review-resume test still
  expected the retired in-process drive. Both were updated to the C5.3 `work_id`/enqueue contract.

## C5.4 handoff

- Append a new executable Recipe-#0 revision; never mutate the C5.2 placeholder identity.
- Translate C4 Stage-0 steps and repeated interview slots into this executor, preserve outcome
  parity, and remove the in-memory runner only after the durable path proves URL-only, correction,
  readiness, override, and run-entry recovery.
- Reuse the exact starter, parameter artifact, pin, gate, map, operation-id, and worker contracts
  shipped here. Do not add a second Stage-0 scheduler or bypass the tool invocation journal.
