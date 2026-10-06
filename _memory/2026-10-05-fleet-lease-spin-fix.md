# Fleet lease spin: ARV2 quality continuations behind one held lease — 2026-10-05

**Branch:** `fix/fleet-lease-spin` (cherry-picked onto `research-streaming` from local
`claude/priceless-agnesi-62e868`, cut from `website-quality/week1` at `47ce65b69`).
**Fixes:** section 6 ("Hot retry loop on lease contention") of
`2026-10-05-multi-worker-multi-workspace-failures.md` on `website-quality/week1`.

## What happened (confirmed on the trenton DB, read-only)
- Generation `abdc99a8…` (work id `970544ce…`): revision 199 held the account's work lease
  11:24:33→11:28:14; revisions 200/201/202 were re-claimed 502/266/123 times and all ended
  `superseded` within 1 ms of it finishing; 203 then ran and applied. Lane total: 21 continuation
  tasks, 3,210 claims, 9 superseded, 8 applied; worst task 883 claims in four minutes. Nothing
  logged. The revisions were 198 `claim_changed`, 4 `person_result`, 1 `initial_settled` signals.
- Mechanism: every ARV2 quality continuation of an account shares one work id
  (`continuation_work_id`). The 10 s quality sweep (`fleet_main._quality_reconcile_loop` →
  `sweep_quality`, run by every fleet process) re-offers each behind generation's *current*
  revision; a new revision is a new dedup key, so each tick added a task beside the running one.
  `LeasedWorkWorker._run_leased_task` handed a task whose lease was held straight back as ready
  (`available_at = now()`), so every free slot re-claimed it every 1 s poll, and every claim
  counted in `fleet_task.attempts` (read as a retry budget by ARV2 research and the site crawl).
- Every other kind already keeps one live task per work id (agent turns by explicit design —
  `agent_turn_submission.py` docstring rejects "claim it then bounce off a lock").

## Fix (two layers; founder chose both)
1. **Source** — `enqueue_task(..., only_if_work_idle=True)`: a generic queue option, serialized by
   an advisory xact lock per `(kind, work id)`; no insert while a queued/claimed task of that kind
   exists on the work id. `sweep_quality` uses it: one live continuation per account; the tick
   after it ends offers the latest revision (≤10 s).
2. **Safety net** (all kinds) — `LeasedWorkWorker._wait_behind_held_lease`, for both the
   cross-worker and the same-process bounce: requeue with `uncount_attempt=True` and
   `delay = clamp((claimed_at − enqueued_at)/2, poll_interval, lease_ttl)` (DB-clock stamps), then
   `log.debug("worker.lease_held_requeue", …)`. The slot no longer sleeps after the hand-back.
- Does not interact with the stranded-jobs attempt fence (`2026-10-05-stranded-research-jobs-
  lease-takeover.md`): that fence is the *job row's* `attempt`, bumped only by `begin_job` under the
  lease; this only lowers `fleet_task.attempts` for a claim that never reached a handler. Entity
  research idempotency keys pair the task attempt with the lease generation, which still differs.

## Verification
- Tests red first, then green: `tests/fleet/test_work_worker.py` (held lease, wait bounds,
  same-process bounce), `tests/fleet/test_fleet_db.py` (attempt taken back; busy-work offer refused
  until the live task ends), `tests/arv2/test_quality_driver_db.py` (sweep asks for
  `only_if_work_idle`).
- Replay `scripts/fleet_lease_spin_replay.py` (real worker/queue/leases, 4 workers × 3 slots,
  production timings, 60 s stand-in reconciliation, a claim change every 8 s for 120 s; throwaway
  pg16, no LLM). Before (`47ce65b69`): 16 tasks, up to 8 live on the lease, 986 claims (970
  bounced), worst task 263 attempts, 14 superseded runs. After: 2 tasks, max 1 live, 2 claims,
  0 bounces, 0 superseded. Fixed code with old-style offers (safety net alone): ~120 claims,
  attempts ≤ 1. Catch-up 5.1–5.5 s after the last signal in all three.
- **Owed:** a live multi-worker walk on a lane (spends LLM; founder's call).
