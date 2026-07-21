# 2026-07-22 — PB-B1 audit repairs #2/#3/#4

**Branch:** `platform/b1-fleet-worker` (on top of `ce6a147`, which fixed audit #1). Resolves the
three remaining audit findings from `_memory/2026-07-21-pb-b1-critical-audit.md`. Fleet-lane only
per the treaty (`platform/fleet/`, the B1 migration, `tests/fleet/`, `docs/specs/PB-B1-*`,
`CLAUDE.md`, `_memory/`); no `clue_api/` or `durable/` edits. Three sequential commits + this docs
commit. TDD throughout (RED captured before GREEN).

## Fix A (commit `6fd97c7`) — total FIFO order (finding #3, High)

**What/why:** `claim_next` ordered by `(priority, enqueued_at)`. Postgres `now()` is
transaction-stable, so same-priority `fleet_task` rows enqueued in one transaction tie with no
final key → nondeterministic FIFO; the audit's rerun gate reproduced it (first `make check` green,
immediate second failed `test_claim_order_is_priority_then_fifo`).

**Ruling/design:** add `enqueue_seq bigint GENERATED ALWAYS AS IDENTITY` to `fleet_task`; order
claim-next + list by `(priority, enqueue_seq)`; partial claim index →
`(kind, priority, enqueue_seq) WHERE status IN ('queued','claimed')`. Migration edited IN PLACE
(branch-local, unmerged, throwaway DBs — no new migration). A `reopen_terminal` re-drive KEEPS its
original `enqueue_seq` (identity doesn't re-mint on UPDATE) → a resumed run keeps its FIFO place
(intended). `FakeTaskQueue` surfaces its existing per-task `seq` as the row's `enqueue_seq`.
Downgrade already `DROP TABLE`s; the identity-owned sequence drops with it (reversible).

**RED:** new `test_same_transaction_enqueues_claim_in_insertion_order` — `AttributeError:
'FleetTaskRow' object has no attribute 'enqueue_seq'`. **GREEN:** that test 10×, plus the
previously-flaky `test_claim_order_is_priority_then_fifo` 10×.

## Fix B (commit `71e8456`) — supervised heartbeat + immediate cancellation (finding #2, Critical)

**What/why:** `_heartbeat` was `create_task`'d and never awaited/observed. A `renew()`/`touch()`
exception killed only the heartbeat coroutine while the phase drove on → lease expired → a takeover
worker drove the same run (reproduced peak drivers = 2). Even `renew() -> False` only aborted at
the next phase boundary — after takeover was already possible.

**Ruling (recorded in spec §2.3, worker/lease docstrings — supersedes "cooperative fencing / next
phase boundary"):** **supervised heartbeat + immediate mid-phase cancellation; hard fence tokens
explicitly deferred.** Hard fencing (a lease token re-checked on every durable write) touches
`durable/` write paths outside B1 scope → integration/Temporal-era follow-up. Zombie window shrinks
from "rest of phase" (unbounded) to **cancellation latency**; a cancelled phase is safe because
SIGKILL mid-phase is already proven resumable and cancellation is strictly gentler.

**Mechanics:** `_heartbeat` proves ownership against the event-loop monotonic clock (`deadline =
loop.time() + lease_ttl`, refreshed after every successful renew, seeded at start). `renew()`
False → lease gone → `lease_lost`, return. `renew()` RAISES → log (keep traceback), keep beating;
once `loop.time() >= deadline − heartbeat_interval` → declare lost. `touch()` failures logged +
ignored. `_drive_task` supervises both via `asyncio.wait(FIRST_COMPLETED)`: heartbeat-first =
fencing (set `lease_lost`, surface + log the heartbeat's crash exception — never dropped, cancel
the drive, await suppressing only the child's `CancelledError`, take `lease_lost` path = requeue,
no release); drive-first = cancel heartbeat, map outcome as before. Worker-level cancellation
(`BaseException`) still propagates.

**RED:** `test_transient_renewal_exception...` — no subsequent `renew:` success (the raise killed
the heartbeat); `test_persistent_renewal_exceptions...` — `advance_started == 2` (dead heartbeat
let the drive run past expiry); `test_renewal_denied_cancels_mid_phase_not_at_boundary` (deliberate
replacement of the old boundary-abort test) — `advance_finished == 1`; DB-gated
`test_heartbeat_death_never_yields_two_concurrent_drivers` (real DbLeaseStore/DbTaskQueue,
renew-raising wrapper on A, long probe advance, short stale window so the lease is the gate) —
`two concurrent drivers: 2`. **GREEN:** all; DB test peak 1, A cancelled, B takes over (~7s).

## Fix C (commit `d2114b3`) — honest exit-gate spend proof (finding #4, High)

**What/why:** the exit gate's "paid resolver call" was a bare `asyncio.sleep`, and the observable
journal row was written AFTER it, atomically with the ledger `succeeded`. A kill after a real
provider accepted/charged but before that transaction would repeat the provider call on takeover
while the test still reported one spend. **The old claim overstated it** ("no double spend
anywhere") — the test proves **DB-effect/ledger exactly-once, NOT provider exactly-once.**

**Design:** second journal `exit_gate_provider_calls (run_id, step_key, worker, call_id,
called_at)` — created by the test alongside `exit_gate_spend_journal`, dropped in the same
`finally` (leaking it would fail `test_no_domain_tables_at_m0_head`). The stub `run_one` records
the provider invocation in its OWN committed transaction BEFORE the sleep. Assertions state the
true contract: spend journal exactly one row/key (unchanged); every completed key ≥1 provider
call; duplicated keys (>1 call) must span the kill boundary (worker A among callers, completing
spend-journal row from worker B) and number ≤ `EXIT_GATE_WINDOW` (in-flight set at kill);
duplicates MAY legitimately be absent. Prose narrowed in harness/test docstrings + spec §2.3/§4.

**Claim correction (what the old claim overstated):** exactly-once is proven for DB effects and the
ledger; the **provider boundary is at-least-once** — a kill between provider-accept and
ledger-commit duplicates that call on takeover, observably, bounded by the in-flight window. True
provider-boundary exactly-once requires provider-side idempotency keys → resolver layer
(integration scope), not the fleet shell.

**RED:** provider assertions added first, failed against the unchanged harness ("no provider call
recorded for completed key ..." — empty table). **GREEN:** full DB-gated exit gate (real
subprocesses + SIGKILL) ~10s.

## Final gate

- `make db-fresh && alembic upgrade head` — clean to `10642c862e43`.
- `make check` run 1: **1999 passed** (69s). Immediate rerun (no db-fresh, the audit's failing
  gate): **1999 passed** (70s). The acme/scripts non-hermetic pollution did not appear (scripts
  not run in this workspace).
- `make db-smoke`: green, up → base → up, **single head** `10642c862e43` — the in-place migration
  edit is reversible.

## Residuals / still-open (audit non-blocking + deferred)

- **Hard fence tokens (backlog `[B1×integration]`):** `advance()`'s durable writes are un-fenced
  during the cancellation-latency window. The hard fix (lease token stamped/checked in `durable/`
  write paths) is deferred to integration/Temporal — **must be re-examined before multi-worker
  production deployment.**
- **SIGHUP-graceful-drain runner gap** (audit non-blocking): `run_worker` handles SIGTERM/SIGINT
  only; Conductor's Run-button stop sends SIGHUP first → not the advertised graceful drain. Open.
- Still open (audit non-blocking, integration-owned): tier-priority rubric binding (free-form tier
  labels rank 100 by the name ladder), fleet `Settings` validation (heartbeat < lease TTL etc.),
  lease-conflict handback starvation (requeue doesn't change ordering key — but note `enqueue_seq`
  keeps the head row's place; revisit), import-contract F2 blocklist hardening.
- Rename stage-1 (`tenant_id`/`client_id` → `workspace_id`) — cosmetic, still pending elsewhere.
