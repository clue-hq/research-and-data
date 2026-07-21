# 2026-07-22 — PB-B1 review-hardening session (fleet worker)

**Branch:** `platform/b1-fleet-worker`. Executed a fully-designed hardening batch adjudicated from
an 8-angle + principal-adjudication code review of the branch's recent commits. **Verdict: no
blocking regressions found**; the batch is defensive hardening + one perf index + one docs pin.
Five sequential commits, TDD throughout, `make check` green twice (2010 passed), `db-smoke`
reversible/single-head, exit-gate + durable suites green.

## Findings & dispositions

Fixed:
1. **IdempotencyScope value-string replay gap (docs).** `idempotency_key` bakes the
   `IdempotencyScope` member VALUE (`"account_step"`/`"campaign_phase"`) into every ledger key AND
   the `idempotency_ledger.scope` column (a Postgres `idempotency_scope` enum, migration
   `df78df38b168`). A stage-2 executor renaming the value → in-flight runs re-run completed phases.
   Pinned in `docs/specs/PB-rename-campaign-run-to-project-run.md` §4.5 + §4.1 cross-ref: rename the
   member NAME + helpers only; values frozen forever (needs a mandatory enum comment at stage 2).
2. **Conservative lease deadline** (`worker.py::_heartbeat`). Seed/refresh the ownership deadline
   from the loop instant captured *before* each acquire/renew round-trip (`t_acquire` param + `t0`
   pre-renew), so the local deadline is always ≤ the DB's server-stamped `expires_at` — the fence
   can't fire after true expiry.
3. **Denser retries near the deadline** — renew-error retry sleeps `min(hb, max(0.05, margin/4))`.
4. **`2·heartbeat_interval < lease_ttl` constructor validation** — a config that would false-fence
   a healthy lease is a `ValueError` at construction. Verified all sites satisfy it: prod defaults
   (10/30), Settings defaults (10/30, not yet wired), DB gate (0.3/1.5), exit gate (0.5/2.0),
   ExplodingDriver (defaults). Only violator was the `_worker` test helper (hb=60 vs default
   ttl=30) → bumped its default `lease_ttl` to 600s (quiet heartbeat preserved). Closes part of the
   settings-validation backlog; full Settings-level validation still open.
5. **Unconditional post-unwind release** — `finally` now gathers both children then releases
   holder-guarded UNCONDITIONALLY; a transient-error fence frees the still-held lease at once
   instead of stalling a full TTL. (Flipped two existing "not released" assertions.)
6. **Drive-first on a photo finish** — `if drive in done:` checked first, so a same-tick terminal
   drive isn't misreported `lease_lost`/requeued.
7. **Touch on every beat (incl. error beats)** — a sustained renew fault no longer lets a live
   driver's claim go stale (extracted `_touch` helper).
8. **Interim §1a rename guard** (`tests/fleet/test_rename_guard.py`) — CamelCase allow-set +
   per-file snake occurrence-count allowlist over the two fleet roots; makes "the marked exceptions
   are the ONLY legacy campaign_run tokens" structural until stage 2's empty-allowlist guard. (Its
   snapshot must be bumped when a fleet file adds/removes a `campaign_run*` token — commit 4's new
   test bumped `test_scheduler.py` 11→12.)
9. **Scheduler cleanups** (`scheduler.py`, fakes): one `_run_locked` single-flight core (was
   duplicated across `_replay`/`_drain`); `_replay` now checks `aborted` before AND after the
   semaphore (was: replay tasks ran detached after a sibling failure); one FIFO truth in
   `FakeTaskQueue` (dropped `_FakeTask.seq`, sort on `row.enqueue_seq`); ONE shared
   `tests/lock_factory.py::ProcessLocalLockFactory` (EntityId-object keyed, `acquired` journal)
   replacing three copies (fleet conftest / exit-gate harness / durable test). The harness
   subprocess bootstraps `sys.path` (repo root not on path there) + imports the dependency-light
   (pytest-free) helper.
10. **Run-scoped claim index** — migration `10642c862e43` edited IN PLACE (branch-local, unmerged —
    the established ruling): `fleet_task_run` is now `(project_run_id, kind, priority, enqueue_seq)`
    (was `(project_run_id, kind)`). Serves the deep drain's run-narrowed ordered claim; the prefix
    still serves the projection read. EXPLAIN with a 20k-row multi-run backlog confirms the planner
    picks `fleet_task_run` for the run-narrowed claim (empty table prefers the partial
    `fleet_task_claim_next`, which is left unchanged for the global drive-task drain).

Discretionary micro-cleanups (flagged, **SKIPPED** — noted for a future pass): collapsing
`FakeLeaseStore.renew_always_raises`+`renew_raise_budget` into one `renew_raises_remaining`, and
removing `ScriptedDriver.advance_finished` (redundant with `advances`). Skipped to keep this
already-large batch tightly scoped and avoid re-touching shared test fakes just before the gate;
both are pure test-fake tidies with no production value.

## Deferred (integration-era — NOT in this batch)
- **(i) Cross-run entity-lock waits park a semaphore slot; `in_flight` ordering is comment-enforced.**
  In `QueueBackedScheduler`, a drainer blocked on a *foreign* run's entity lock holds its semaphore
  slot, and the mark-in_flight-before-lock ordering is documented, not structurally guaranteed.
  Revisit at integration (try-lock / requeue-on-contention, or claim-exclusion) — a design change,
  not a point fix.
- **(ii) `LeaseStore.acquire/renew` return only a bool, not the DB `expires_at`.** Surfacing the
  server-stamped expiry as the seam-level ownership primitive (instead of the worker re-deriving a
  monotonic deadline) is the cleaner long-term contract; integration-era.

## Operational caveat
The fleet migration `10642c862e43` was edited **in place**. Any local DB stamped at that revision
*before* these edits will NOT have the new `fleet_task_run` shape — run `make db-fresh &&
alembic upgrade head` (workspace Postgres, non-default port via `.env`). No other lane carries this
migration, so there is nothing to `alembic merge`.

## Commits
1. `docs(specs): pin IdempotencyScope value strings …`
2. `fix(fleet): review hardening — conservative lease deadline …`
3. `test(fleet): interim §1a rename guard …`
4. `refactor(fleet): review cleanups — single _run_locked core …`
5. this note.
