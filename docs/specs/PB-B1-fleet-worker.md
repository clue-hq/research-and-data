# PB-B1 — the fleet worker (harness build step 0)

**Status:** in progress (lane opened 2026-07-21 on `platform/b1-fleet-worker`, cut from the
treaty commit `e615e81`)
**Authority:** `PB-phase-b-platform-infra-core.md` §2 (the B1 brief — owned surfaces, must-not-
touch, exit gate), harness doc §6/§9 (runtime topology, build step 0) and REQ-10 (fleet scale),
`docs/specs/_conventions.md` (workflow, gates).
**Scope discipline:** no new research behavior. Every phase body, the state machine, the
scheduler, `BudgetEngine`, and the idempotency-ledger semantics are untouched; B1 adds the
*process shell* around them — the pipeline gains kill-resumability, single-driver enforcement,
and tier-priority ordering.

---

## 1. Goal

The detached **`CampaignRunWorker`**: a separate OS process that drives existing M7 campaign-run
state machines (+ the M8A per-account graphs the `deep` phase fans out to) as **jobs**:

- a **per-run driver lease** — at most one worker drives a given `campaign_run` at a time; a
  second worker may not drive a leased run and takes over only after lease expiry (harness §6:
  "a per-run driver lease enforces a single driver"). This *enforces* the single-driver
  precondition M7.3 documents but deliberately left "to the scheduler/ops layer"
  (`durable/campaign.py` class docstring) — which is exactly this layer.
- a **task drain** — a durable `fleet_task` queue the worker claims work from
  (`SELECT … FOR UPDATE SKIP LOCKED`), plus graceful drain on shutdown (stop claiming, finish or
  hand back in-flight work) and stale-reclaim after a crash (kill -9 leaves a claimed task; the
  next worker re-owns it once it goes stale — the same recovery shape as the M7.4 ledger).
- a **tier-priority queue** — within the `deep` phase, account jobs execute in tier order under a
  bounded concurrency window (REQ-10: "budget exhaustion still researched the *best* accounts
  first"), via a queue-backed drop-in for the seam the deep handler already drives.

## 2. Design

### 2.1 `clue_fleet` package layout

| Module | What it owns |
|---|---|
| `enums.py` | `FleetTaskKind` (`drive_run` \| `account_job`), `FleetTaskStatus` (`queued` → `claimed` → `done` \| `failed`) — package-local lifecycle enums (the `durable/enums.py` precedent), mirrored by DB enums + parity tests |
| `lease.py` | the `run_lease` table repo + `DbLeaseStore`: atomic acquire (`INSERT … ON CONFLICT DO UPDATE … WHERE expires_at <= now()`), holder-guarded renew/release. All clock reads are DB `now()` (the M7.4 convention — no cross-worker NTP skew) |
| `queue.py` | the `fleet_task` table repo + `DbTaskQueue`: idempotent enqueue (`ON CONFLICT DO NOTHING` on `(kind, campaign_run_id, dedup_key)`), atomic claim-next (`FOR UPDATE SKIP LOCKED`, `ORDER BY priority, enqueued_at`), holder-guarded finish/requeue, stale-reclaim window |
| `scheduler.py` | `QueueBackedScheduler` — implements the exact `run_accounts(specs, campaign_run_id=…, checkpointer=…, run_one=…)` signature the M8A deep handler is typed against (`clue_api.deep.handler.DeepAccountScheduler`, asserted structurally in tests), so at integration it is a constructor-argument swap for `durable.AccountScheduler` — zero handler changes. Enqueues every spec as an `account_job` (priority = tier rank), drains under the concurrency window, marks tasks done/failed |
| `worker.py` | `CampaignRunWorker` — the drain loop: claim a `drive_run` task → acquire the run lease → step the run via the injected `RunDriver` seam (structurally satisfied by `durable.CampaignRun`) with a concurrent lease-heartbeat → finish the task with the run's terminal/suspended status → release the lease. Graceful `stop()` between phases; lease loss aborts the drive (cooperative fencing) |
| `runner.py` | `run_worker(...)` — the asyncio process entrypoint shell (signal handling, drain-on-SIGTERM). The *production* `__main__` (composing real phase handlers) is `clue_api` wiring and lands **at integration**, per the treaty §3.4; tests compose their own harness process |

### 2.2 The tables (one migration, hash id off `98422adaaa38`)

- **`run_lease`** — `campaign_run_id` (PK), `worker_id`, `acquired_at`, `renewed_at`,
  `expires_at`. A row is *held* while `expires_at > now()`; acquire atomically re-owns an expired
  row; renew/release are `WHERE worker_id = :me` (holder-guarded — a fenced-out zombie's write
  matches zero rows).
- **`fleet_task`** — `task_id` (PK), `kind`, `campaign_run_id`, `dedup_key`
  (`UNIQUE (kind, campaign_run_id, dedup_key)` — enqueue is idempotent), `priority`
  (smaller = sooner; tier rank for account jobs), `status`, `attempts`, `payload` (JSONB,
  references only), `result_ref` (JSONB, references only), `claimed_by`, `claimed_at`,
  `enqueued_at`, `updated_at`. Claim-next index on `(status, kind, priority, enqueued_at)`.

Both tables are *fleet-plane* state — no FK into research tables (`campaign_run_id` is carried as
an opaque id, the same way `idempotency_ledger` carries its key), so the fleet shell stays
subsystem-agnostic and the migration is purely additive.

### 2.3 Crash-safety model (why the exit gate holds)

Kill -9 at any point leaves: the lease row (expires by TTL), the claimed `drive_run` task
(stale-reclaimed), possibly an `IN_PROGRESS` phase checkpoint, claimed-but-unfinished
`account_job` rows, and `in_progress` idempotency-ledger rows. Recovery composes existing
guarantees, adding none:

1. Takeover worker re-owns the stale task **and must win the (expired) lease** — the lease is
   authoritative; a live lease blocks the takeover (the second half of the exit gate).
2. Re-entering the run replays committed phases (`COMMITTED` short-circuit), re-runs the
   interrupted phase (phase `stale_after` is zero *because* the lease now enforces the
   single-driver precondition it was designed around).
3. Re-entering `deep`: `done` account tasks re-invoke `run_one` (idempotent replay — the M8A
   sub-phase markers + the account-step ledger make it spend-free), `claimed`-stale tasks are
   re-owned, `queued` tasks drain in tier order. Exactly-once **spend** is the ledger's
   guarantee, exactly like today's resume path; the queue adds ordering + visibility + at-most-
   one concurrent executor per task.
4. A zombie driver (alive but lease-expired) is fenced cooperatively: heartbeat failure aborts
   its drive between phases, and its task/lease writes are holder-guarded no-ops. The residual —
   a zombie mid-*phase* write racing the takeover's re-run — is exactly the window the account-
   step ledger (non-zero staleness) and the M2.4 entity locks already govern in real runs;
   recorded as a known bound, not solved twice.

### 2.4 Drive semantics

- A `drive_run` task means "advance this run until it can't advance". Terminal (`COMPLETED` /
  `FAILED`) → task `done`. Suspended (`PAUSED` — human gate, budget graceful-stop, client
  pause) → task `done` with `result_ref.outcome = "paused"`; re-driving after
  `submit_checkpoint`/`resume` is a **new `enqueue_drive`** (the resume surface's job — the B4
  toolbelt; tests enqueue directly), which *re-opens* the finished drive task
  (`reopen_terminal` — a terminal row on the dedup key goes back to `queued`; account jobs
  never re-open: their `done` row is the exactly-once completion marker). A run that makes no
  progress (still `ACTIVE`, same phase — e.g. awaiting a checkpoint submission) ends the drive
  the same way (`"stalled"`), mirroring `run_to_completion`'s no-progress guard.
- **Live claims never go stale**: the driver's heartbeat renews the lease *and* re-stamps the
  drive task's claim (`touch`), and the deep drain's in-flight guard keeps sibling drainers
  from re-running a long account job whose claim crossed the staleness window mid-execution (a
  guarded re-claim is just a claim heartbeat). Staleness thus only ever fires for a *dead*
  holder — the recovery path, never the steady state.
- Graceful stop (SIGTERM / `stop()`): finish the current `advance()` (phases are the atomic
  unit, exactly like M7.3 `pause`), requeue the task (holder-guarded), release the lease.
- The worker never constructs phase handlers; it drives the injected `RunDriver` seam. Policy
  knobs (poll interval, lease TTL, heartbeat, stale window, deep window) are `CLUE_FLEET_*`
  settings — policy as data.

## 3. Shared-surface manifest (treaty §3)

| Surface | Touch |
|---|---|
| Alembic head | one migration, hash id, chained off `98422adaaa38` |
| `clue_config.settings` | append-only `CLUE_FLEET_*` fields |
| `core.enums` | **untouched** — fleet enums are package-local (`clue_fleet/enums.py`), per treaty §3.3 preference |
| Root `pyproject.toml` | `clue_fleet` already registered (R2); append two import contracts (research ⊄ fleet; fleet touches only `durable` inside research) |
| `clue_api` | **no wiring committed** (treaty §3.4); the scheduler-swap + worker `__main__` land at integration |

`durable/` seam edits: **none required** — the worker drives the public `CampaignRun` surface;
the scheduler implements the public `run_accounts` seam.

## 4. Acceptance criteria (= the treaty exit gate)

1. **Kill-resume exactly-once:** kill -9 the worker process at ~40% of a 500-account stub-mode
   run → start a fresh worker → the run completes; every `(account, field, tier)` account-step
   key and every `(campaign_run, phase)` phase key has **exactly one** `succeeded` ledger row,
   and total recorded spend equals the single-run expectation exactly (no double spend).
   [`tests/fleet/test_exit_gate.py`, real OS processes + SIGKILL]
2. **Lease takeover:** while worker A holds a run's lease, worker B cannot drive the run; after
   the lease expires without renewal, B acquires it and drives. [same test + focused DB tests]
3. **Tier-priority order:** account jobs execute best-tier-first under the concurrency window.
4. **Task drain:** graceful stop finishes the in-flight phase, requeues the task, releases the
   lease; a SIGKILLed worker's claimed task is reclaimed after the stale window.
5. Standing gates (treaty §5): `make check` green; full DB suite green fresh **and** on rerun;
   `db-smoke` reversible with one head; `scripts/01–06` stub-mode chain unchanged.
