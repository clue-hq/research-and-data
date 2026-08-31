# 2026-08-27 — Wave A / A2 (defect R3-B): fleet hygiene

Capability-gated claims + job/task status reconciliation. Base `46bc872f5`; landed as
`1c4ba8b80` on `worktree-agent-a9458360d2b3fae4d`. No engine changes. Local commit only.

## The defect, and the exact gap

From `.context/w5-apollo-e2e-report.md` §R3-B: a detached design fleet worker running two-day-old
code with `LUMEN_BRAND_AD_ASSETS` unset claimed an `ad_assets` ingestion task 0.5s after enqueue
and failed it. The fleet task went `FAILED` with `result_ref_json {"outcome": "error"}` while the
owning `design_ingestion_job` row stayed `queued`, `error_json: null`, for nine minutes.

**Named gap.** `DesignJobWorkHandler.handle`'s preamble — `_parse` (the tagged-union envelope
validation), the work-id widening check, and the `_claim` call — all run *before*
`claim_job_for_execution` moves the row `queued -> running`. D5 Round C's in-handler containment
(`_terminalize_failed`) only covered `body.exception()`, i.e. post-claim faults. A preamble raise
escaped into `clue_fleet.work_worker.LeasedWorkWorker._run_task`, whose `except Exception` is
**fleet-plane only**: it finished the task `FAILED` with the literal `{"outcome": "error"}` (which
is how the report's `result_ref_json` identifies the path) and returned, never touching the design
row. The reaper could not recover it either — both `sweep_stranded_runs` / `sweep_stranded_jobs`
read only `status = 'running'` rows, so a `queued` orphan was invisible to every mechanism.

Trigger in the field: the stale worker's `DesignIngestionKind` had no `AD_ASSETS` member, so the
envelope failed the union parse.

## Fix 1 — capability-gated claims (claim seam is SQL-side)

- `clue_fleet.queue.TaskCapability` — "if the payload carries `field`, its value must be in
  `supported`". Serialized as one jsonb bind (`as_json`), evaluated as a `NOT EXISTS` predicate
  inside `_CLAIM_NEXT_SQL`'s candidate SELECT using `cap->'supported' @> jsonb_build_array(...)`
  (containment, not `NOT IN`, so a JSON-null or non-string discriminant is fail-closed).
  Empty capabilities => predicate vacuously true => statement is behaviourally identical to before.
- Threaded through `claim_next_task`, `TaskQueue`/`DbTaskQueue`, `WorkQueue`/`DbWorkQueue`.
- `clue_fleet.work_worker.CapabilityGated` — an **opt-in** protocol (`task_capabilities`), not a
  new member on `WorkHandler`: 10 handlers exist and 9 genuinely own their whole kind. Resolved
  per claim attempt (`LeasedWorkWorker._capabilities`) so a flag-gated lane answers for live
  config; a raise there skips the kind for the pass rather than claiming blind.
- `TaskCapability.permits` / `payload_is_claimable` are the Python mirror of the SQL predicate;
  both in-memory fakes (`tests/fleet/conftest.py`, `tests/fleet/test_work_worker.py`) now evaluate
  it, so a fake cannot hand a worker work the DB would have withheld.
- `lumen_api.fleet_handler.runnable_ingestion_kinds()` builds from `DesignIngestionKind`'s own
  members minus flag-off lanes (`_FLAGGED_INGESTION_KINDS`). **The stale-worker guarantee needs no
  version negotiation**: a build cannot list a lane it has no member for.

## Fix 2 — reconciliation, two layers

- **(a) synchronous.** `handle()` wraps its whole body; on any exception it reconciles by WORK ID
  (the only identifier that survives an unparseable envelope) and returns
  `WorkResult(outcome="preamble_error", references={... "reconciliation": <outcome>})` instead of
  raising. Outcomes are honest strings: `job_failed` / `run_failed` / `job_refused` /
  `run_refused` / `unknown_work` / `unreconciled`.
- **(b) sweep.** `fleet_reaper.sweep_orphaned_jobs` / `sweep_orphaned_runs` over *dispatched but
  still `queued`* rows whose task is terminal or absent, failing them with `ORPHANED_CODE =
  "design.task_orphaned"`. Wired into `run_reaper_pass` after the two stranded sweeps.
- Shared policy lives in one place: `fleet_reaper.reconcile_dispatched_failure`, used by both the
  handler's containment and (via the DAL) the sweeps. It is in `fleet_reaper` because terminalizing
  a *run* also requires the terminal SSE event in the same transaction, which the handler has no
  business learning.
- New DAL: `ingestion.fail_dispatched_job` / `list_dispatched_queued_jobs` and the run twins
  `runs.fail_dispatched_run` / `list_dispatched_queued_runs`. The `fail_dispatched_*` writes accept
  `status IN ('queued','running')` and carry the claim CAS's own fence
  (`lease_generation IS NULL OR lease_generation <= :gen`) when a generation is supplied, so an
  incapable worker cannot stamp `failed` over a capable takeover.

**Policy: orphans are failed, never re-offered.** A stranded `running` row is re-offered once
because its work was interrupted mid-flight; an orphaned `queued` row's task was already claimed
and terminalized by a worker that judged it unrunnable, so a re-offer buys the same verdict.

## Red cases proven

1. Worker seam — patched `_capabilities` to return `()`: the stale worker claims the `ad_assets`
   row (`test_a_stale_worker_leaves_a_lane_it_cannot_run_for_the_capable_worker` fails). Restored.
2. Handler — removed the `try/except` around `_handle`: the ValidationError raises straight out of
   `handle()`, exactly the R3-B mechanism. Restored.
3. Reaper — kept as a **permanent** guard rather than a temporary patch: the orphan test asserts
   `sweep_stranded_jobs` leaves the row `queued` before `sweep_orphaned_jobs` fails it.

## Tests

- New `tests/design/test_design_fleet_r3b_db.py` (12 tests, DB-gated): SQL claim filtering,
  turn-payloads-unfiltered, no-capability default, the handler's flag-driven declaration, preamble
  containment, generation-fenced refusal, unknown work id, both orphan sweeps (task failed / task
  missing), the healthy waiting case, the run twin + its SSE terminal event, the grace window.
- New capability tests in `tests/fleet/test_work_worker.py` (4).
- Green: `tests/fleet` + `tests/design` (251), `tests/design/test_design_fleet_r3b_db.py`,
  `uv run mypy` (only the pre-existing `ad_assets.py:151`), `ruff check`/`format` on all changed
  files, `lint-imports` 26 kept / 0 broken.
- Throwaway DB for this worktree: `docker run --name clue-pg-r3b -p 55901:5432 pgvector/pgvector:pg16`,
  `alembic upgrade head`. Removed at session end.

### Failures VERIFIED pre-existing at base 46bc872f5 (checked out base files and re-ran)

- `subsystems/clue-design/apps/agent_runtime/tests/test_web_retokenize.py` (3) — no `npm install`
  under `apps/editor`; the test's own message says so.
- `subsystems/clue-design/apps/api/tests/test_custom_component_compiler.py` (up to 5) — node.
- `subsystems/clue-design/apps/api/tests/test_ad_assets_onboarding.py::test_an_empty_harvest_says_so_at_the_top_level`
  — fails at base; in isolation it fails on `job["stage"] == outcome["summary"]` (an R2-C
  assertion), under load on `status`. **Order-dependent / shared-`fleet_task` interference —
  worth its own look, unrelated to R3-B.**
- `tests/api/test_production_context_s31_fleet_db.py::test_real_fleet_chain_...` — recipe promotion
  `tool:open_design_leg:version_mismatch`.
- `tests/sources/test_waterfall.py` (3–4 under `-k`) — `SourceManifestRedefinitionError`, a subset
  -run registry-isolation artifact.
- `ruff format` would reformat 4 untouched files; `ruff check` has 1 pre-existing error
  (`test_toolbelt_wiring.py`); `mypy` has 1 (`clue_design/ad_assets.py:151`). So `make check` is
  **already red at base** — none of it from this work.

## Residuals / open questions

1. **No capable worker => the job waits forever, silently.** By design (the brief: leave it
   unclaimed), and the reaper correctly treats a `queued` task as healthy. But there is now no
   surface that says "this `ad_assets` job has been offered for an hour and no worker in the fleet
   declares the lane". A per-kind "offered but unclaimable" age metric or a much longer
   unclaimed-age sweep is the obvious follow-up. **Needs a founder call on what should happen.**
2. **`LeasedWorkWorker._run_task`'s generic `except Exception` is unchanged** and still finishes
   the task `FAILED` with `{"outcome": "error"}` without any domain reconciliation. Correct for
   R3-B (the design handler now contains its own preamble), but every *other* handler with domain
   state behind its task has the same latent shape. Not surveyed — deliberately out of scope.
3. **B1 hard lease fence tokens remain deferred** (noted, not fixed, per the constraint). The
   capability filter is purely a SELECT-side predicate and touches no lease internals.
4. **`_FLAGGED_INGESTION_KINDS` must be maintained** when a future lane gets a flag. It is one
   dict entry beside the enum member, and forgetting it is the *safe* direction (the lane is
   claimable, i.e. today's behaviour), not the unsafe one.
5. **Capability is coarse: flag only.** `ad_assets` also needs an OpenRouter key to distil, but the
   lane can legitimately run harvest+custody without one, so the key is deliberately NOT part of
   the capability (per the founder-approved design: "any flag that kind requires").
6. **Design-subsystem twin.** These changes are on the platform copy under
   `subsystems/clue-design/apps/api/lumen_api/`. There is no separate design-repo copy of the
   reaper/handler to keep in step (unlike the AD4.C F9 canvas residual).
