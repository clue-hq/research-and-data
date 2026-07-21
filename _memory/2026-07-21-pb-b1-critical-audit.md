# 2026-07-21 — PB-B1 critical audit (review only)

**Branch:** `platform/b1-fleet-worker` at `f67d24d`, reviewed against the treaty baseline
`e615e81`. **No production/test fixes made in this session.** Scope was the 21 branch-only files:
fleet migration/package/settings/import contracts/spec/tests plus the prior environment note.

## Verdict

B1 is **not integration-ready** despite the happy-path exit gate and one clean full-suite pass.
Two concurrency invariants are false in ordinary/runtime-failure cases, and the required DB-suite
rerun gate is flaky because FIFO order is not total.

## Blocking findings

1. **QueueBackedScheduler drops M7's per-entity single-flight lock.** The existing
   `AccountScheduler` wraps `run_one` in an injected `LockFactory`; the replacement has no lock seam
   and calls `run_one` directly. Two healthy campaign runs containing the same entity therefore run
   it concurrently under different account-run/idempotency keys (double-research/double-spend risk).
   Reproduced with two scheduler instances: peak same-entity concurrency = 2.
2. **The run lease is not a reliable single-driver fence.** `_heartbeat` exceptions are not caught
   or observed by `_drive_task`; the heartbeat task dies while the phase continues, the lease
   expires, and a takeover worker can drive the same run concurrently. Reproduced against the real
   DB queue/lease: one simulated heartbeat-path exception produced two `advance()` calls with peak
   concurrent drivers = 2. Even the handled `renew() -> False` path is cooperative only (old phase
   continues to its boundary after expiry); hard fencing remains an explicit design decision.
3. **Priority/FIFO order is nondeterministic and the standing rerun gate fails.** Claim order is
   only `(priority, enqueued_at)`. PostgreSQL `now()` is transaction-stable, so same-priority rows
   enqueued in one transaction tie with no final key. On a fresh schema the first full `make check`
   passed (1991), while the immediate second run failed
   `test_claim_order_is_priority_then_fifo` (`low-second` before `low-first`). A separate 10-run
   focused loop happened to pass, confirming plan/physical-order sensitivity rather than a stable
   FIFO contract.
4. **The kill test does not observe the simulated external spend.** The paid call is represented by
   `sleep`; only afterward does the test atomically insert its journal row and finish the ledger. A
   kill after an external provider accepted/charged the call but before that DB transaction would
   repeat the provider call on takeover while the test still reports one journal row. The test proves
   DB effect/ledger atomicity, not no duplicate external provider spend.

## Important non-blocking/integration findings

- Tier labels are free-form and ordered by `TierCutoffs.bands`, but B1's default priority uses a
  hard-coded name ladder/digit regex. Valid labels such as `platinum/gold/silver` all rank `100` and
  lose best-tier-first ordering. Integration must bind a rank derived from the committed rubric (or
  the task must carry a canonical rank); the current wiring checklist does not say so.
- `Settings` and the worker accept non-positive/inconsistent timing values. Verified that all
  negative intervals and `deep_window=0` load successfully. Required relations include heartbeat
  below lease TTL and task staleness safely beyond heartbeat/lease behavior.
- Lease-conflict handback requeues without changing `enqueued_at`; claim-next immediately picks the
  same head row again, starving later runs. Reproduced: two drains attempted run A twice while run B
  remained queued with zero attempts.
- Import contract F2 is a manual blocklist, not an allow-only-durable contract: root re-exports and
  future research/storage packages can bypass it. It must be extended at B2 integration at minimum.
- Conductor stops run scripts with SIGHUP before SIGKILL, but `run_worker` handles only SIGTERM and
  SIGINT; local Run-button stop is therefore not the advertised graceful drain.

## Valid intentional deferrals (not counted as B1 defects)

Per treaty §3.4, production `clue_api` wiring is correctly absent: construct the real
`CampaignRun`, add the worker `__main__`/DB+obs lifespan, swap in the queue scheduler, route
submit/resume through `enqueue_drive`, and thread `CLUE_FLEET_*` settings. The integration wiring
also needs to update `DeepPhaseComposition.scheduler`'s concrete `AccountScheduler` annotation and
bind rubric-derived tier priority. Those are larger than the prior “three lines” description but
remain integration-owned.

## Verification and diagnostics

- `git diff --check e615e81..HEAD`: clean.
- `alembic heads`: one head, `10642c862e43`.
- Focused fleet/settings suite: green before the full run.
- Dirty persistent DB full gate: 7 known pre-existing `acme.example` uniqueness failures (Recipe
  script data); reset only the isolated `clue_nouakchott` public schema via `.env`/`make db-fresh`.
- Fresh `make check`: **1991 passed**. Immediate second `make check`: **1 failed, 1990 passed** on
  nondeterministic FIFO ordering.
- `make db-smoke`: green, full upgrade -> base -> head, one head.
- Diagnostic first attempt at the cross-scheduler DB repro failed because it omitted
  `db_lifespan()`; rerun inside the lifespan succeeded and cleaned its run-scoped fleet rows.
- Worktree remained production-code clean; this note is the only audit-session file change.

## Recommended repair order

1. Restore the per-entity lock seam in `QueueBackedScheduler`, including a two-campaign concurrency
   regression test.
2. Decide/implement real fencing semantics; at minimum supervise heartbeat exceptions and cancel or
   abort the active phase promptly, then add heartbeat-fault + live-zombie takeover tests.
3. Add a monotonic enqueue sequence (or equivalent total FIFO key) and order by it.
4. Correct the exit test's claim: either inject an observable idempotent provider boundary or state
   precisely that it proves ledger/DB-effect exactly-once, not external-call exactly-once.
5. Bind tier priority from ordered rubric data; validate all fleet settings/relations; fix
   lease-conflict starvation and harden F2.
