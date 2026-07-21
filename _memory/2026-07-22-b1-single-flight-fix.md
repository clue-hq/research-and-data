# 2026-07-22 — PB-B1 audit fix #1: per-entity single-flight in QueueBackedScheduler

**Branch:** `platform/b1-fleet-worker`. Resolves audit **blocking finding #1** (see
`_memory/2026-07-21-pb-b1-critical-audit.md`). Scope was fleet-lane only per the treaty
(`platform/fleet/` + `tests/fleet/` + docs/memory); no `clue_api/` or `durable/` edits.

## What changed & why

`clue_fleet.scheduler.QueueBackedScheduler` replaced `durable.AccountScheduler` at the deep seam
but **dropped** the Doc C §4 per-entity single-flight lock: it called `run_one` bare. The queue
dedup key is `(kind, campaign_run_id, dedup_key)`, so two campaign runs holding the same entity
are two distinct rows — the queue alone can't serialize them. Repro: two schedulers, same entity,
peak concurrency = 2 (double-research/double-spend).

Fix (mirrors `AccountScheduler._run_one`, semaphore → entity lock → `run_one`; the lock covers
`run_one` only, not the queue `finish` bookkeeping):

- `__init__` gains `lock_factory: LockFactory` as a **required** keyword-only arg (no `None`
  default, no fallback), imported from `clue_research.durable` (allowed path, already used for
  `AccountSpec`/`RunOne`). **Required-not-optional decision:** the baseline api composition already
  forgot to pass the factory to `AccountScheduler` (optional there;
  `platform/api/clue_api/deep/composition.py:345` omits it → single-flight silently off). Making
  it required turns a silent omission into a construction-time `TypeError`. Explicit opt-out is
  still possible via a written null context-manager factory, never a default.
- Both execution paths wrapped in `async with self._lock_factory(spec.entity_id)` inside the
  semaphore slot: the `_replay` (done-job replay) path and the `_drain` execute branch.
- **`in_flight`-before-lock ordering (critical):** in `_drain`, `in_flight.add(key)` happens
  BEFORE awaiting the entity lock. While a drainer blocks on a lock held by another run, its
  claimed row can cross the staleness window and look orphaned to a sibling's claim-next; the
  `in_flight` guard must cover the lock wait so the sibling's stale re-claim can't double-run the
  job. The existing try/except (aborted.set + finish FAILED + raise) and finally
  (in_flight.discard) are intact around the new lock context.

## Tests added (TDD: RED observed before GREEN)

- `tests/fleet/conftest.py::ProcessLocalLockFactory` — shared per-entity `asyncio.Lock`
  (`defaultdict`, keyed on `str(entity_id)`) + `acquired: Counter[str]` journal; callable
  `factory(entity_id) -> async ctx mgr`. Mirrors `tests/durable/test_account_scheduler.py`'s
  `_per_entity_lock_factory`.
- `test_scheduler.py::test_cross_run_same_entity_is_single_flighted` — two runs, one shared queue,
  one shared lock factory, shared entity → peak concurrency for shared entity == 1, both runs
  return correct input-ordered results.
- `test_scheduler.py::test_replayed_done_job_acquires_the_entity_lock` — a done-from-previous-drive
  replay still acquires the entity lock (journal asserts 1 acquisition).
- `test_scheduler.py::test_lock_factory_is_required` — `pytest.raises(TypeError)` on construction
  without `lock_factory`.
- `test_fleet_db.py::test_cross_run_same_entity_is_single_flighted_on_the_real_queue` — DB-gated
  twin against real `DbTaskQueue` (committed rows, run-scoped `uuid5` ids, `db_lifespan`).
- Construction sites updated: `_scheduler` helper (fresh factory default + optional shared param),
  the DB in-flight-guard test, and `exit_gate_harness.build_worker` (process-local factory —
  honest because the run lease already guarantees one driver per run; prod wires
  `account_entity_lock_factory(get_redis())` at the api root).

RED evidence: `TypeError: QueueBackedScheduler.__init__() got an unexpected keyword argument
'lock_factory'` (2 offline + 1 DB test) and "DID NOT RAISE TypeError" (required-arg test).

## Verification

- `uv run pytest tests/fleet/`: **43 passed** (+4 new test fns; was 39).
- `uv run ruff check --fix` + `ruff format` on touched files: clean.
- `make check`: **EXIT=0** — ruff format/check clean, mypy `Success: no issues found in 287
  source files`, import-linter **18 contracts kept 0 broken**, **1995 passed**.
- Seam conformance `test_scheduler_satisfies_the_deep_handler_seam`: still passes (the protocol
  has no constructor, so the required arg does not break structural conformance).

## Residuals / open follow-ups

- **(a) api wiring — integration-owned (treaty §3.4).** Wire
  `account_entity_lock_factory(get_redis())` into BOTH schedulers at the api composition root: the
  `QueueBackedScheduler` swap AND the pre-existing `AccountScheduler` omission at
  `composition.py:345`. See the `[B1×api]` backlog entry + spec integrator checklist. Single-flight
  *strength* is the M2.4 Redis entity lock's; cross-process fencing quality (incl. the known
  `multi_lock`/short-TTL early-expiry caveat) is inherited from M2.4, not re-solved here.
- **(b) audit finding #2 — heartbeat-death lease fencing** still open (next in the repair queue):
  `_heartbeat` exceptions aren't observed by `_drive_task`, so the heartbeat can die while the
  phase continues, the lease expires, and a takeover drives concurrently.
- **(c) audit finding #3 (FIFO tiebreak non-total → flaky rerun gate) and #4 (exit test observes
  DB-effect/ledger exactly-once, not external-provider spend)** still open.
- **(d) `campaign_run` → `project_run` rename** staged design agreed but not executed; stage 1
  (fleet-lane rename) pending user confirmation of spellings.
