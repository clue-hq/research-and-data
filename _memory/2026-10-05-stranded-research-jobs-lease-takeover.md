# Stranded ARV2 research jobs: lease takeover + attempt fence — 2026-10-05

**Branch:** `claude/inspiring-saha-a803c0` (worktree `inspiring-saha-a803c0`, cut from trenton's
`website-quality/week1` at `10aca4a05`). Local commits only, not pushed.
**Fixes:** section 4 of `2026-10-05-multi-worker-multi-workspace-failures.md`.

## Root cause (confirmed, not inferred)
- trenton worker log `/tmp/trenton_fleet_worker_2.log`: `agent_turn.context_receipt` 10:45:08.26 →
  `model_windows.catalogue_unavailable` 10:46:53.58. The whole 105 s silence was ONE call:
  `model_windows._fetch_catalogue` (sync `urlopen`) reached from `DeepAgentTurnRuntime._build_graph`
  → `compaction_for`, on the worker's event loop. OpenRouter trickled the chunked body; each read
  beat `timeout=10` (per read), the last read timed out. No lease renewed meanwhile.
- Then: task stale at 60 s → re-claimed → `begin_job` refused `in_progress` → task closed as
  `completed` (no-op) → frozen worker woke, saw lease lost, `suspend_job` → stranded.
- Same no-op also strands a job left `in_progress` by a killed worker (pre-existing, unreported).
- Relaunching the same request does NOT repair it: `enqueue_launched_jobs` uses
  `reopen_terminal=False`, and the stranded task is `done`.

## Fix (commits 9bcbdd276, c0dc9aa55, 4619d1ea5, 5d289723d, f92461b91)
1. Runtime reads `compaction_for` via `asyncio.to_thread` (both graph-build sites; covers every
   governed agent). `model_windows`: 15 s deadline over the whole body (`read1`, NOT `read` — on a
   chunked body `read(n)` spans the whole trickle; found live), one fetch under a lock, failure
   retried after 600 s instead of cached forever.
2. `begin_job` claims `in_progress` too (only the lease holder calls it; work id == job id), bumping
   `attempt`. `finish_job`/`suspend_job` take `attempt`, write only `WHERE attempt=:a AND
   status='in_progress'`, return bool. Driver: fenced settle raises `_JobSuperseded` inside the
   settle transaction (rollback) → `WorkResult("superseded", requeue=True)`. The driver writes no
   job row before it claims: pre-claim stop just requeues; work-id mismatch fails the task (was
   needs_review on a row whose lease it did not hold); a failing claim requeues (5 s).
3. `scripts/requeue_stranded_arv2_research_jobs.py` (founder chose script over relaunch-reopen):
   started jobs (`suspended`/`in_progress`) with no queued/claimed task → re-open their own task.
   `not_started` excluded (person jobs may be held on purpose). Dry run default.
4. Card text for a suspended job: "paused, resuming automatically" (founder ruling).

## Verification
- Reproduced first on real code: `clue_inspiring` = dump/restore of `clue_trenton` on
  `clue-pg-trenton` @55160 (+ `.artifacts` APFS copy, worktree `.env` pointed at it); two real
  `fleet_main` workers, all provider keys invalid (no spend), worker A's catalogue URL patched to a
  local 1-byte-per-6-s chunked server. Same end state as trenton (job suspended, task done).
- After the fix, live on the clone: (a) lease renewed every 10 s through the trickle; job settled
  (`needs_review`, `provider_refused:openrouter:auth_invalid` — the invalid key). (b) Worker A's
  loop frozen 90 s (sync sleep in `_tool_runtime`, outside the claim transaction): B took over
  (attempt 3) and settled; A's late suspend logged `arv2.account_suspend_superseded attempt=2`.
- Tests (throwaway DB `clue_inspiring_test`, keys unset, `*_live.py` ignored): new
  `test_a_job_whose_driver_lost_its_lease_is_taken_over_not_stranded` (red before), store takeover/
  fence test, runtime off-loop test, three model_windows tests, offline driver cases. Sweep of
  tests/arv2 + related api/agents/gateway/fleet: green except 4 — 2 need `CLUE_BRANDFETCH_CLIENT_ID`
  unset (env), 2 fail identically on base `10aca4a05` (`miscellaneous` contact section:
  test_frontend_read_contacts rail test, display_pages stale-section test) — pre-existing.
- Repair script on clone: planned 5 → re-offered 5 → planned 0. Dry run on `clue_trenton`
  (read-only) lists exactly `27cc746e…` and `30b1bbfe…`. **Not applied on trenton** (its workers
  run old code; applying spends money) — founder's call.

## Open / follow-ups
- A superseded zombie's NON-status writes (claims, stage stamps, workspace files) are not fenced;
  bounded by cancellation latency once its loop runs (same class as the B1 residual in CLAUDE.md).
- A suspended job still raises the card's `needs_attention` pill though it resumes by itself — not
  changed (presentation ruling not asked).
- Blocking-call audit (read-only, this session): no other sync network call on the research loop.
  **Thread-pool starvation — FIXED (commit 386ad5e90, founder-approved plan):** every provider call
  and the loop's DNS lookup for a fresh DB connection (heartbeat included; host is a name) share the
  default executor, min(32, cpu+4) threads, vs ~18 concurrent provider calls per job x 4 jobs, some
  held 660-900 s. Measured: 80 slow calls in flight → fresh connection 39.9 s on the default pool
  (> 30 s lease), 0.02 s on 128 threads. `fleet_main._serve` now calls
  `clue_fleet.install_thread_pool(loop, max_workers=settings.fleet_thread_pool_size)` first thing;
  `CLUE_FLEET_THREAD_POOL_SIZE=128` in `.env.example` (+ worktree `.env`). Test
  `tests/fleet/test_worker_thread_pool.py` (lookup waited 2.9 s on the default pool → red).
  Not changed (measured/estimated small, founder agreed): media hashing/writing ~0.4 s per 200 MiB
  on the loop (`media_acquisition.py` ~257-305); workspace fsync (`specialist_wiring.py:410`, not
  measured). Not done: a dedicated DB pool for the heartbeat (pool exhaustion never measured).
  Other processes (design ingestion pool, platform API) keep Python's default pool.
  `tests/test_config_settings.py` fails 4 tests when `.env` is sourced into the shell — env leak,
  passes in a clean env (`env -i`).
- Clone artefacts left in place: DB `clue_inspiring` (~1.8 GB) and `clue_inspiring_test` on
  `clue-pg-trenton`, worktree `.env` + `.artifacts` copy. Drop with founder OK.
