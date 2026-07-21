# 2026-07-21 — PB-B1: the fleet worker (harness build step 0)

**Branch:** `platform/b1-fleet-worker`, cut from the treaty commit `e615e81` per the PB treaty
protocol. Integrates back onto `platform/workspace-restructure` in order B2 → B3 → **B1**.
**Spec:** `docs/specs/PB-B1-fleet-worker.md` (surface map, design, shared-surface manifest,
acceptance criteria = the treaty exit gates).

## What landed

`clue_fleet` is real (was an R2 scaffold): `enums.py` (package-local `FleetTaskKind`/
`FleetTaskStatus`), `lease.py` (`run_lease` repo + `DbLeaseStore` — atomic acquire/expiry
takeover, holder-guarded renew/release, DB-clock only), `queue.py` (`fleet_task` repo +
`DbTaskQueue` — idempotent enqueue, `reopen_terminal` for drive tasks, SKIP LOCKED claim-next in
`(priority, enqueued_at)` order, stale reclaim, holder-guarded finish/requeue/touch),
`scheduler.py` (`QueueBackedScheduler` — the REQ-10 tier-priority deep drain, drop-in for
`AccountScheduler` at the deep-handler seam; in-flight guard against sibling re-claims),
`worker.py` (`CampaignRunWorker` — drive_run drain loop, lease heartbeat that also touches the
task claim, graceful stop, lease-loss cooperative abort, per-run fault isolation), `runner.py`
(signal-driven process shell). Migration `10642c862e43` (hash id off `98422adaaa38`):
`run_lease` + `fleet_task` + the two DB enums; reversible; one head.

**Zero `durable/` edits were needed** — the worker drives `CampaignRun`'s public
`status`/`advance` (a `RunDriver` protocol it satisfies structurally) and the scheduler
implements the public `run_accounts` seam. Shared surfaces touched: `Settings` (+`CLUE_FLEET_*`,
append-only), root `pyproject.toml` (+2 import contracts: research never imports fleet;
fleet→research only through durable, direct-imports-only via `allow_indirect_imports`),
fleet `pyproject.toml` deps. **No `clue_api` wiring** (treaty §3.4) — at integration: swap
`AccountScheduler` → `QueueBackedScheduler` in the deep-handler wiring, add the worker
`__main__` composition, and have resume/submit surfaces call `enqueue_drive`.

## Decisions taken (flag for founder review)

1. **One `fleet_task` table, two kinds** (`drive_run` / `account_job`) — one claim-next path,
   one dedup shape; projections (B4) read one table.
2. **A paused run ends its drive task** (`done`, outcome=`paused`); re-driving is a fresh
   `enqueue_drive`, which re-opens the terminal task (`reopen_terminal`). Account jobs never
   reopen — their `done` row is the run's completion marker (the deep drain replays them
   through `run_one`, spend-free via ledger/sub-phase markers).
3. **Run-FAILED ≠ task-failed**: a drive that brings a run to `FAILED` is a *successful* drive
   (task `done`, outcome=`failed`); task `FAILED` is reserved for driver exceptions, parked
   until explicit requeue.
4. **Fencing is cooperative** (lease-loss aborts between phases; all queue/lease writes
   holder-guarded). The residual zombie-mid-phase window is the same one today's resume path
   has; governed by the account-step ledger + M2.4 entity locks (spec §2.3).
5. **Tier→priority policy** is injectable; default understands `top/high/mid/low` + numeric
   labels, unknown → last (researched, never dropped).

## Verification (all green, 2026-07-21)

- `tests/fleet/` — 39 tests: offline loop/scheduler suites on in-memory fakes; DB-gated
  lease/queue semantics (zero-TTL trick: `now()` frozen per txn, so expiry/staleness are
  deterministic, no sleeps); enum parity; seam conformance
  (`QueueBackedScheduler` satisfies `clue_api.deep.handler.DeepAccountScheduler`).
- **Exit gate** (`test_exit_gate.py`): real subprocesses + SIGKILL at ≥200/500 done account
  jobs → probe acquire fails while the dead worker's lease is live → fresh worker takes over
  after expiry → run COMPLETED → **exactly-once proven** via the `exit_gate_spend_journal`
  (one row per key, written atomically with the ledger `succeeded` — the M8 pattern), all 500
  account-step keys + all 8 phase keys `succeeded` once, both workers present in the journal,
  queue fully drained, lease released, worker B exits 0 on SIGTERM.
- Standing gates: `make check` green (incl. the exit gate in the DB suite), full suite green
  on rerun, `db-smoke` reversible with one head, `scripts/01–06` stub-mode chain completes.

## Self-review catches (fixed before commit)

- `RETURNING` ambiguity in claim-next (fleet_task vs candidate subquery) → qualified columns.
- `enqueue_drive` dedup would have permanently blocked re-driving a paused run → `reopen_terminal`.
- Drain deadlock when `run_one` raised (siblings poll-looped forever) → shared `aborted` event.
- Long-job staleness hazard: sibling drainers could re-claim+re-run a still-executing account
  job → in-flight guard (+ DB test with an instantly-stale window); live drive tasks could be
  churned between workers → heartbeat `touch` on the claim.
- One driver exception would have killed the worker loop → task FAILED + drain continues.

## Follow-ups (integration-time, recorded not blocking)

- `clue_api` wiring commit (integrator, per treaty §3.4): scheduler swap, worker `__main__`,
  `enqueue_drive` from resume/submit surfaces, real `Settings.fleet_*` → worker/scheduler knobs.
- The exit-gate test leaves committed run-scoped rows in the branch DB (unique ids per
  invocation; rerun-idempotent). Its non-alembic `exit_gate_spend_journal` table is dropped in
  the test's `finally` — leaving it leaked failed `test_no_domain_tables_at_m0_head` (which
  asserts a downgraded schema holds only alembic-managed tables); caught by the gate battery.
- Priority refresh: an account job's priority is set at first enqueue; a mid-run tier_cutoffs
  adjust does not re-prioritize already-queued jobs (advisory ordering only — revisit if B4
  steering needs live reprioritization).
- **Pre-existing (NOT B1, in `scripts/` — outside B1's owned surfaces, left for integration):**
  two chain-hint drifts in the Recipe #1 scripts: `02_icp_synthesis`'s `Next:` line passes
  `--icp-key/--icp-version`, which `03_find_accounts` no longer accepts (03 runs fine without
  them), and `04_account_profiling` prints no `Next:` hint toward 05 (05/06 run standalone,
  seeding their own demo entities — README-documented). The chain itself completes 01→06 in
  stub mode; only the printed hints drifted.
- **Pre-existing (NOT B1): the DB suite is not hermetic against `scripts/` leftovers.**
  Reproduced independently of any fleet change: on a fresh migrated DB the tests/api
  identity-binding/gate-routing/composition tests are green; after `scripts/01` seeds its
  "acme" demo data, up to 7 of them fail (e.g.
  `test_injected_classifier_born_binding_weak_on_same_name`) until the DB is refreshed. The
  gate order that works (and matches the treaty's "fresh DB" wording): `db-fresh` → `migrate` →
  full suite → rerun → `db-smoke` → scripts *last*. Worth a small cross-lane fix at
  integration (script data under throwaway ids, or suite fixtures that scope their reads).
