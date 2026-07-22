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

## §1a vocabulary — rename complete (both stages)

Per harness doc §1a (*project* = the end-to-end ABM motion, historically "project_run"), the
B1-owned run-machinery identifiers were renamed on this lane (**stage 1**: `ProjectRunWorker`,
fleet-owned `project_run_id` end-to-end). The four seam exceptions that pinned the legacy
spelling flipped at **stage 2** (2026-07-22, right after Phase-B integration — playbook at
`docs/specs/PB-rename-campaign-run-to-project-run.md`, executed): the whole repo now speaks
`project_run` (`ProjectRun*` types via a `clue_core` contract-delta; the durable table/types
renamed by migration `814a272f79a5`), the in-code markers are deleted, and the empty-allowlist
guard `tests/test_project_rename_guard.py` replaced the interim fleet guard. Bare "campaign" is
**not** renamed — it stays a valid concept (a channel program within a project). The frozen
`IdempotencyScope` ledger *values* (`"account_step"`/`"campaign_phase"`) are durable data and
deliberately keep their spellings.

## 1. Goal

The detached **`ProjectRunWorker`**: a separate OS process that drives existing M7 campaign-run
state machines (+ the M8A per-account graphs the `deep` phase fans out to) as **jobs**:

- a **per-run driver lease** — at most one worker drives a given `project_run` at a time; a
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
| `queue.py` | the `fleet_task` table repo + `DbTaskQueue`: idempotent enqueue (`ON CONFLICT DO NOTHING` on `(kind, project_run_id, dedup_key)`), atomic claim-next (`FOR UPDATE SKIP LOCKED`, `ORDER BY priority, enqueued_at`), holder-guarded finish/requeue, stale-reclaim window |
| `scheduler.py` | `QueueBackedScheduler` — implements the exact `run_accounts(specs, project_run_id=…, checkpointer=…, run_one=…)` signature the M8A deep handler is typed against (`clue_api.deep.handler.DeepAccountScheduler`, asserted structurally in tests), so at integration it is a constructor-argument swap for `durable.AccountScheduler` — zero handler changes. Enqueues every spec as an `account_job` (priority = tier rank), drains under the concurrency window, marks tasks done/failed. Carries the same Doc C §4 per-entity single-flight as `AccountScheduler` via a **required** (not optional) `lock_factory` seam — every `run_one` (drain + done-replay) runs inside the injected per-entity lock, so two runs never deep-research one entity at once; the required-arg makes a forgotten factory a construction-time `TypeError` (prod wires `account_entity_lock_factory(get_redis())` at the api root) |
| `worker.py` | `ProjectRunWorker` — the drain loop: claim a `drive_run` task → acquire the run lease → step the run via the injected `RunDriver` seam (structurally satisfied by `durable.CampaignRun`) with a concurrent, **supervised** lease-heartbeat → finish the task with the run's terminal/suspended status → release the lease. Graceful `stop()` between phases; lease loss **cancels the in-flight phase immediately** (supervised-heartbeat fencing — §2.3) |
| `runner.py` | `run_worker(...)` — the asyncio process entrypoint shell (signal handling, drain-on-SIGTERM). The *production* `__main__` (composing real phase handlers) is `clue_api` wiring and lands **at integration**, per the treaty §3.4; tests compose their own harness process |

### 2.2 The tables (one migration, hash id off `98422adaaa38`)

- **`run_lease`** — `project_run_id` (PK), `worker_id`, `acquired_at`, `renewed_at`,
  `expires_at`. A row is *held* while `expires_at > now()`; acquire atomically re-owns an expired
  row; renew/release are `WHERE worker_id = :me` (holder-guarded — a fenced-out zombie's write
  matches zero rows).
- **`fleet_task`** — `task_id` (PK), `kind`, `project_run_id`, `dedup_key`
  (`UNIQUE (kind, project_run_id, dedup_key)` — enqueue is idempotent), `priority`
  (smaller = sooner; tier rank for account jobs), `status`, `attempts`, `payload` (JSONB,
  references only), `result_ref` (JSONB, references only), `claimed_by`, `claimed_at`,
  `enqueued_at`, `updated_at`. Claim-next index on `(status, kind, priority, enqueued_at)`.

Both tables are *fleet-plane* state — no FK into research tables (`project_run_id` is carried as
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
   re-owned, `queued` tasks drain in tier order. Exactly-once **DB effect / ledger** is the
   ledger's guarantee, exactly like today's resume path; the queue adds ordering + visibility +
   at-most-one concurrent executor per task. The **external-provider** call is at-least-once — a
   kill between provider-accept and the atomic ledger commit repeats it on takeover (audit finding
   #4); the exit gate observes this via the `exit_gate_provider_calls` journal and bounds it by the
   in-flight window. Provider-boundary exactly-once needs provider-side idempotency keys (resolver
   layer), out of B1 scope.
4. A zombie driver (alive but lease-expired) is fenced by **supervised heartbeat + immediate
   mid-phase cancellation** (the ruling below, superseding the earlier "cooperative fencing /
   aborts at the next phase boundary" language). The heartbeat is a *supervised* task, not a
   fire-and-forget coroutine: `_drive_task` waits on the drive and the heartbeat together
   (`asyncio.wait(FIRST_COMPLETED)`), and the heartbeat completing first is a fencing event that
   **cancels the in-flight `advance()` immediately**. The heartbeat itself is resilient (a renew
   that *raises* is logged and retried — the audit's finding #2 trigger no longer silently kills
   it; retries pack denser as the deadline nears, and the drive-task claim is re-stamped on
   *every* beat, including error beats, so a live driver's claim can't go stale under a sustained
   transient fault) and authoritative (it proves lease ownership against the event loop's monotonic
   clock, and declares the lease lost once it can no longer land a beat before true TTL expiry).
   The ownership deadline is **conservative**: seeded from the loop instant captured *before* each
   acquire/renew round-trip (never after it returns), so the local deadline is always ≤ the DB's
   server-stamped `expires_at` — the fence can never fire *after* true expiry. A construction-time
   **`2·heartbeat_interval < lease_ttl`** invariant guarantees at least a beat of margin, so a
   single transient blip can't false-fence a healthy lease (a config violating it is a
   `ValueError` at construction — closing part of the settings-validation backlog; full
   Settings-level validation remains open). On a same-tick photo finish (the final `advance()` and
   the fencing renew both resolving at once) the drive's real terminal result wins — a completed
   run is never misreported `lease_lost` and requeued. After both children are fully unwound the
   lease is **released unconditionally** (holder-guarded — a no-op after a genuine takeover, but a
   transient-error fence still holds the lease, so releasing frees it at once rather than stalling
   a full TTL for expiry). The zombie window thus shrinks from "the rest of the phase" (unbounded)
   to **cancellation latency** (residual = cancellation latency only, no longer a full phase); a
   cancelled phase is safe by construction because SIGKILL mid-phase is already proven resumable
   by the exit gate and cancellation is strictly gentler.

   **Hard fence tokens are explicitly deferred.** True hard fencing — a lease token stamped on
   acquire and re-checked on *every* durable write — requires changing the `durable/` ledger and
   state-machine write paths, outside B1's treaty scope; it is recorded as an integration /
   Temporal-era follow-up (and in the cross-milestone backlog). The residual: `advance()`'s
   durable writes are still un-fenced during the cancellation-latency window — the same class as
   today's documented resume-path residual (a zombie mid-*phase* write racing the takeover's
   re-run), bounded by the M7 account-step ledger (non-zero staleness) and the `ce6a147`
   per-entity single-flight locks. Must be re-examined before multi-worker production deployment.

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

**Integrator checklist (the api-composition-root wiring, treaty §3.4 — integration-owned):**

- **Wire the per-entity single-flight lock into `QueueBackedScheduler` (structural).** Construct
  `account_entity_lock_factory(get_redis())` and pass it as the scheduler's `lock_factory` — it is
  a **required** constructor arg, so the swap literally will not construct without it (a forgotten
  factory is a `TypeError`, not a silent double-research). This restores the Doc C §4 guarantee
  that `AccountScheduler` carried at the deep seam.
- **Fix the pre-existing baseline omission at `platform/api/clue_api/deep/composition.py:345`.**
  The baseline constructs `AccountScheduler(graph, max_parallel=…)` with **no** `lock_factory` —
  there the arg is optional and defaults to `None`, so prod per-entity single-flight was silently
  **off** wherever the baseline scheduler runs. Pass the same
  `account_entity_lock_factory(get_redis())` there too. (Both schedulers must be wired; B1 only
  made the *queue-backed* one fail-loud.)

## 4. Acceptance criteria (= the treaty exit gate)

1. **Kill-resume exactly-once (DB effect + ledger; provider boundary at-least-once):** kill -9 the
   worker process at ~40% of a 500-account stub-mode run → start a fresh worker → the run
   completes; every `(account, field, tier)` account-step key and every `(project_run, phase)`
   phase key has **exactly one** `succeeded` ledger row and exactly one `exit_gate_spend_journal`
   row — the effect row and the ledger `succeeded` finish share ONE transaction, so DB effects and
   the ledger are exactly-once despite the kill. The **provider boundary is at-least-once** (audit
   finding #4, narrowed from the earlier "no double spend anywhere" overstatement): the
   `exit_gate_provider_calls` journal (written before the "paid" call, in its own committed
   transaction) shows every key was invoked ≥1×, and a key whose provider-accept was orphaned by
   the kill is re-invoked on takeover — bounded by the in-flight drain window (`EXIT_GATE_WINDOW`),
   with worker A among the callers and worker B owning the single completing spend-journal row.
   True provider-boundary exactly-once requires provider-side idempotency keys (resolver /
   integration scope), not the fleet shell. [`tests/fleet/test_exit_gate.py`, real OS processes +
   SIGKILL]
2. **Lease takeover:** while worker A holds a run's lease, worker B cannot drive the run; after
   the lease expires without renewal, B acquires it and drives. [same test + focused DB tests]
3. **Tier-priority order:** account jobs execute best-tier-first under the concurrency window.
4. **Task drain:** graceful stop finishes the in-flight phase, requeues the task, releases the
   lease; a SIGKILLed worker's claimed task is reclaimed after the stale window.
5. Standing gates (treaty §5): `make check` green; full DB suite green fresh **and** on rerun;
   `db-smoke` reversible with one head; `scripts/01–06` stub-mode chain unchanged.
