# Task 9d — in-process fleet worker concurrency (founder ruling 2026-09-10)

Branch `onboarding/o6-head-of-abm`, base `ef0a2d02a`. One worker process can now drive several
fleet tasks at once; several worker processes still run against the same queue.

## What shipped

- `Settings.fleet_worker_concurrency: int = Field(default=1, ge=1)` (`CLUE_FLEET_WORKER_CONCURRENCY`),
  in the `CLUE_FLEET_*` block of `libs/clue-config/clue_config/settings.py`. Documented in
  `.env.example` (a new "Fleet worker concurrency" block — the other `CLUE_FLEET_*` knobs were
  **already** absent from `.env.example`; that pre-existing parity gap was left alone) and mirrored
  in the local `.env`.
- `LeasedWorkWorker(..., concurrency=1)`: `run()` starts N `_drain_loop(slot)` asyncio tasks over
  the same queue, leases and handler instances. Each slot is today's loop verbatim (round-robin
  over kinds, db-error backoff, poll sleep). `drain_once(*, slot=None)`, `_run_task`, `_heartbeat`
  and `_touch` carry the slot so every log line names it alongside `worker_id`.
- **Slot-failure policy (chosen, tested):** a raising slot logs `worker.slot_crashed` and stays
  dead; siblings keep draining; `run()` re-raises the first failure only once **every** slot has
  ended, so `run_worker` → `asyncio.run` exits non-zero exactly when the drain is really gone.
- `fleet_wiring._SerializedHandler` — a per-handler `asyncio.Lock` wrapper (forwards `kind` and the
  R3-B `task_capabilities`, read per call). Applied to **`drive_run` only**.

## Handler safety audit (all handlers registered in `build_multi_work_worker`)

| handler | verdict |
|---|---|
| `drive_run` (`_OwnedRunGuardHandler`→`ProjectRunWorkHandler`→`ComposingRunDriver`) | **serialised** |
| `execute_graph` (`RecipeExecutionHandler`/`RecipeExecutor`) | safe |
| `entity_research_job` (legacy flag off by default) | safe |
| `agent_turn` | safe |
| `stage0_recon` | safe |
| `official_site_crawl` | safe |
| `onboarding_run` | safe (own `_db_lock`) |
| `arv2_account_research` | safe (own `_db_lock` + `_jobs` semaphore) |
| `design_job` | safe |

`drive_run` is the only unsafe one, for two independent reasons:
`ComposingRunDriver.composed` (`run_composition.py:~450`) keeps an unlocked LRU registry cache with
an `await` between miss and fill and evicts by size (`composer_registry_cache_size` default 8), and
`clue_research.durable.ProjectRun` (`durable/project.py:~389`) states single-driver-per-run as a
precondition it does not enforce ("what lets phase idempotency use a zero `stale_after`").

## Open follow-ups (recorded, not fixed here — all out of 9d's scope)

1. **The work lease does not fence two slots of one process.** All slots share one `worker_id`, and
   `_ACQUIRE_SQL` (`platform/fleet/clue_fleet/lease.py:~57`) re-issues a *live* lease to its own
   `worker_id` **without bumping `generation`**. Across processes the fence holds; inside one
   process it does not. Reachable only if two slots hold two task rows with the same `work_id`
   (needs the stale-reclaim branch, which the heartbeat's `touch` normally prevents) — unproven,
   but it is why `drive_run` is serialised rather than trusted. A real fix is a per-slot lease
   identity, which changes `claimed_by`/orphan-sweep semantics; deliberately not attempted.
2. **Per-task caps become per-process × N.** `recipe_executor_max_concurrency`, the crawl
   coordinator's `worker_concurrency` + extraction semaphore, and onboarding's per-run
   `onboarding_max_parallel_runs` are all built *per task*, so raising the knob multiplies provider
   fan-out. Size the knob against provider rate limits, not CPU.
3. **Default `asyncio.to_thread` executor.** Design turns, onboarding Exa hops and ARV2 provider
   hops all park a thread for the length of the call on one `min(32, cpu+4)` pool. Saturation
   presents as "the provider got slow".
4. **Onboarding holds `_db_lock` across the catalog-reconcile model call** (`onboarding_driver.py`
   `_catalog_sync`, 120s timeout) and across `persist_body` in `_settle`. Correct, but under
   concurrency it is now a *cross-run* stall, not a per-run one. Owner: the onboarding lane.
5. **Design `_CHECKPOINTER_SETUP_DONE`** (`subsystems/clue-design/apps/api/lumen_api/fleet_handler.py:~604`)
   is a module-global check-then-act across `to_thread` threads; with concurrency two design turns
   can both call `PostgresSaver.setup()`. Its own comment calls `setup()` idempotent DDL, and
   serialising the whole design kind would defeat the point of the ruling, so it is recorded rather
   than locked. Owner: the design lane.

## Verification

`uv run pytest tests/fleet tests/api/test_fleet_wiring.py tests/design/test_design_fleet_reaper_db.py
tests/design/test_design_fleet_turns_db.py tests/arv2/test_settings.py
tests/arv2/test_onboarding_settings.py --ignore-glob='*_live.py' -p no:randomly` → 141 passed
(DB: `clue_o6_head`). ruff check/format clean on the touched files; mypy on them reports the same
23 pre-existing errors as base `ef0a2d02a` (verified in a throwaway worktree at base) — zero new.
