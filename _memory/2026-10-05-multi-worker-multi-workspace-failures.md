# Failures observed running several workspaces and extra workers at once — 2026-10-05

**Lane:** trenton (branch `website-quality/week1`), stack on 3029/8019/8029/8039.
**Setting:** four workspaces under one user (Conduit AI, plus Stripe, Garner Health and AltCarbon
added today) running setup research, brand-kit ingestion, Head of ABM turns, discovery and account
research at the same time, with extra fleet workers and extra ingestion coordinators started by
hand. Times are UTC.

Status key: **FIXED** (changed today), **WORKAROUND** (running, not a real fix), **OPEN** (needs a
code change), **MINE** (caused by how I operated the lane, not by the product).

---

## 1. Shared Postgres ran out of connections — FIXED (infra)

- **What happened (2026-10-04 ~14:40):** the Conduit re-extraction's image-analysis processes
  crashed on start six times in two minutes; 715 of 747 image descriptions failed ("Image worker did
  not complete analysis").
- **Cause:** the shared `clue-pg-papeete` container (port 55040) has `max_connections=100`. It was at
  98: trenton stack 57 (12 worker slots, APIs, ingestion analysis children), nashville 35, others 6.
  My background design test run pushed it over.
- **Fix:** trenton moved to its own container `clue-pg-trenton` (127.0.0.1:55160,
  `max_connections=300`). Re-extraction afterwards: 720/742 described, 0 crashes.
- **Product gap (OPEN):** an analysis child that cannot connect exits and its items are marked
  failed. It should retry later, not fail the items.

## 2. OpenRouter connection failures caused a Head of ABM `agent_timeout` — FIXED (config) + OPEN

- **What happened (10:05–10:17):** Stripe's first ICP turn (`thr_32b10e17…`, turn `2f55e589…`)
  ended `agent_timeout` with no message to the user beyond that word. Its 7th model call hung; the
  same call then timed out on grok-4.6, grok-4.7 and muse-spark, 3 attempts each.
- **Evidence:** in the same window 114 of Stripe's image descriptions failed with OpenRouter transport
  errors (62 "server disconnected without sending a response", 47 read timeouts, 5 write timeouts).
  OpenRouter's status page showed no incident; the connection recovered by ~10:18.
- **Contributing cause:** the per-call limit was 60 s, and Head of ABM calls on a 70k–90k-token context
  already took 55–68 s, so slightly slow calls failed even on a healthy connection.
- **Fix:** `CLUE_AGENT_MODEL_TIMEOUT_S` and `CLUE_GATEWAY_TIMEOUT_S` 60 → 120 (commit `d56774a1e`).
  A 68 s call has since succeeded.
- **Product gaps (OPEN):** image descriptions do not retry transport errors later (they fail after 2
  quick attempts); `agent_timeout` is shown to the user as a bare code with no "the model provider was
  unreachable, please resend" explanation.

## 3. Brand-kit ingestion runs one job at a time — WORKAROUND

- **What happened:** with three new workspaces, Garner Health and AltCarbon kits sat `queued` for 45+
  minutes behind Stripe's.
- **Cause:** the ingestion pool starts exactly one coordinator with concurrency 1
  (`lumen_api/ingestion_pool.py`: `desired_roles` and `concurrency=1 if role == "coordinator"`).
- **Workaround:** four extra coordinators started by hand
  (`.venv/bin/python -m lumen_api.ingestion_pool --role coordinator`, logs
  `/tmp/trenton_ingest_coord_extra{1..4}.log`). Kits then ran in parallel and all finished.
  These are started with a relative interpreter path, so `dev_stack … down` does NOT stop them; kill
  with `pkill -f "^.venv/bin/python -m lumen_api.ingestion_pool --role coordinator"`.
- **Fix needed (OPEN):** a setting for the number of coordinators.

## 4. Research jobs stranded as `suspended` after a lost lease — FIXED on `claude/inspiring-saha-a803c0` (see `2026-10-05-stranded-research-jobs-lease-takeover.md`)

- **What happened (10:45–10:47):** Stripe's account research on Cloudinary and Tencent Cloud
  (run `2056417c…`, jobs `30b1bbfe…`, `27cc746e…`) ended `suspended` after ~105 s with 0 model rounds,
  no failure message, and no task left to resume them. The project card said "paused, waiting for a
  worker".
- **Sequence (from `fleet_task` and worker logs):**
  1. 10:45:08 worker `90ea624c` (attempt 1) starts both jobs, both in the same process.
  2. The process stops renewing its leases for ~105 s; the only log lines in that gap are, at the end,
     `model_windows.catalogue_unavailable` / `window_unknown`.
  3. 10:46:07 both tasks are re-offered; worker `d3d1d0df` (attempt 2) sees the jobs already
     `in_progress` (`begin_job` only claims `not_started`/`suspended`) and closes the tasks as
     `completed` doing nothing.
  4. 10:46:53 attempt 1 notices its lease was lost and parks both jobs as `suspended`.
- **Likely cause:** blocking work on the worker's event loop stops lease renewal. Confirmed one such
  call: `clue_gateway/model_windows.py` uses synchronous `urllib.request.urlopen(timeout=10)`. The
  rest of the 105 s silence is unexplained (no model calls logged).
- **Workaround:** asked Head of ABM to relaunch research; Tencent Cloud then ran normally (new job
  `0a041c6b…`).
- **Fixes needed (OPEN):**
  - move blocking calls off the event loop (`asyncio.to_thread`) and find what else blocked;
  - when a re-offered task finds its job `in_progress` with an expired lease, take the job over
    instead of closing the task as done;
  - re-queue `suspended` jobs automatically (today nothing resumes them);
  - say "stalled" or "suspended" in the UI, not "waiting for a worker".

## 5. Extra fleet workers with a different environment broke a turn — FIXED (MINE) + OPEN

- **What happened (11:06–11:07):** AltCarbon's reply turn (`7aa3a9fe…`) failed twice in 40 s; the
  chat showed only an empty "Clue" reply and the turn's last status stayed `requested`.
- **Cause (MINE):** I started 4 extra fleet workers with only `source .env`. The stack's workers also
  get `CLUE_DESIGN_RUNTIME_ENABLED=1`, `CLUE_DESIGN_API_BASE_URL`, `CLUE_AGENT_WORKSPACE_ROOT` and the
  local `CLUE_PAGES_*` settings (`scripts/dev_stack.sh` `PLATFORM_ENV`). Attempt 1 ran on an extra
  worker, attempt 2 on a stack worker, and the retry was refused:
  `ExecutionConflict: execution id was replayed with a different recipe, scope, or parameters`.
  Design runs would also have broken on those workers (design runtime off).
- **Fix:** killed the 2 idle mismatched workers; started `extra5`/`extra6` with the stack's exact
  environment and the absolute interpreter path (so `down` stops them); a watcher kills the 2 busy
  mismatched workers once they hold no claimed task (a graceful stop would suspend their research,
  see 4). Re-sent the AltCarbon message; it ran on `extra5`.
- **Product gaps (OPEN):**
  - a turn whose start raises writes no terminal `agent_turn_event` and no chat message, so the user
    sees a silent hang;
  - a worker process accepts work even when design runtime or required settings are missing; it
    should refuse to start, or the execution parameters should not depend on process-local settings.

## 6. Hot retry loop on lease contention — FIXED (branch `claude/priceless-agnesi-62e868`)

- **What happened (~11:25–11:31):** worker `67e90478` (`extra6`) re-claimed Garner Health's Syracuse
  quality-reconciliation tasks hundreds of times in minutes (one task 502 attempts, others 266, 123,
  30) while the job was already `completed`. None of it is logged.
- **Cause:** all reconciliation tasks of one generation share one work id
  (`continuation_work_id`). `clue_fleet/work_worker.py` `_run_leased_task`: when the work lease is
  held, the task is requeued at once and claimed again after the poll interval, so queued siblings
  spin until the holder finishes; then they end `completed` / `superseded`.
- **Impact:** wasted database round-trips and slot time; attempt counts become meaningless for
  diagnosis.
- **Confirmed on the trenton DB (read-only, same day):** generation `abdc99a8…` (work id
  `970544ce…`): revision 199 held the lease 11:24:33→11:28:14; revisions 200/201/202 bounced
  502/266/123 times and all ended `superseded` within 1 ms of it; 203 then ran and applied. Its
  revisions came from 198 `claim_changed`, 4 `person_result`, 1 `initial_settled` signals. Lane
  total: 21 continuation tasks, 3,210 claims, 9 superseded, 8 applied; worst task 883 claims.
  Mechanism: the 10 s quality sweep (`_quality_reconcile_loop` → `sweep_quality`) re-offers each
  behind generation's *current* revision; a new revision is a new dedup key, so a new task joined
  the running one on the same lease every tick.
- **Fix (both layers, ruled with the founder):**
  1. *Source* — `enqueue_task(..., only_if_work_idle=True)` (generic queue option, advisory-locked
     per `(kind, work id)`): no insert while a queued/claimed task of that kind exists on the work
     id. `sweep_quality` uses it, so an account has at most one live continuation; the tick after
     it ends offers the latest revision (≤10 s later) — the agent-turn dispatcher's existing rule.
  2. *Safety net* — `LeasedWorkWorker._wait_behind_held_lease` (both the cross-worker and the
     same-process branch): requeue with `uncount_attempt=True` (a claim that never ran is not an
     attempt) and `delay = clamp((claimed_at − enqueued_at)/2, poll_interval, lease_ttl)`;
     `log.debug("worker.lease_held_requeue", …)`. Applies to every kind; other kinds keep one live
     task per work id, so they reach it only in crash recovery.
- **Verified:** new tests red first, then green — `tests/fleet/test_work_worker.py` (held lease,
  wait bounds, same-process bounce), `tests/fleet/test_fleet_db.py` (attempt taken back; busy-work
  offer refused until the live task ends), `tests/arv2/test_quality_driver_db.py` (sweep asks for
  `only_if_work_idle`). `tests/fleet` + `tests/arv2` on a throwaway pg16 DB: all pass except
  `test_quality_claims_db.py::test_provider_value_and_web_quote_use_originals_and_replay`, which
  fails identically on the unchanged base (pre-existing, not investigated). Worker-driving API
  tests (146) pass; mypy clean. **Owed:** a live multi-worker walk to see the spin gone.

## 7. Smaller issues seen along the way

- **Image-description model output (~3%)**, not multi-worker: runaway or empty JSON (12 of 22 on
  Conduit), required fields left blank (8), placement-count mismatch (2), model
  `deepseek/deepseek-v4.1-flash`. Fix idea: one retry on invalid output, provider structured output.
- **Setup research finished `completed_with_gaps`** for Stripe and AltCarbon (2 failed steps each),
  likely during the OpenRouter window in 2. Not yet inspected.
- **Workspace switcher:** the profile menu label can show the previous workspace after a switch;
  new workspaces appear only after a reload; switching needs a hover submenu. There is no
  "add workspace" UI and `/auth/v1/provision` is first-time-only, so extra workspaces for one user had
  to be created with the platform functions directly.
- **Langfuse export** to `us.cloud.langfuse.com` fails intermittently all day ("Failed to export span
  batch … HTTPSConnectionPool"): traces have gaps.
- **Stack lifecycle (MINE):** starting `dev_stack up` from a backgrounded tool call that later hit its
  time limit killed the whole stack. Start it detached:
  `nohup ./scripts/dev_stack_trenton.sh up > /tmp/trenton_up.log 2>&1 < /dev/null & disown`.
- **`claimed_at` is refreshed by heartbeats**, so many tasks showing the same claim time (11:22:06,
  11:31:47) is normal, not a mass re-claim; `attempts` stayed 1 for those.

## 8. Brand-brief step times out and retries for many minutes — OPEN

- **What happened:** the Stripe and Garner Health typography re-extractions (13:27, descriptions/
  vision/ads off) reached "Preparing your brand kit…" by ~13:43 and then sat there: the brand-brief
  agent's calls to grok-4.7 (`/responses`, reasoning medium, up to 3 screenshots) kept timing out and
  retrying ~every 2 minutes (Stripe from 13:42, Garner from 13:48). Conduit's morning run showed the
  same retries (08:11, 08:13). OpenRouter itself answered (3–4 s on /models).
- **Why it can take so long:** `lumen_ingestion/brief_agent.py` allows `MAX_AGENT_STEPS = 6` rounds;
  each call times out at ~120 s and is retried twice, so the step can run ~30 min before giving up.
  A refused brief still publishes the kit, so it delays rather than blocks.
- **Fix ideas (OPEN):** faster model or lower reasoning for the brief, fewer screenshots, no client
  retries on timeout (fail fast), or run the brief after the kit is published so it never delays it.

## Current state at the time of writing (~11:32)

- Brand kits: all three done (Stripe 517/701 described, Garner 95/99, AltCarbon 101/111).
- Research: Garner Health — both account jobs completed; committee research Syracuse 4/4 people
  done, Carmel Clay 1 done and 4 running. Stripe — Tencent Cloud account job running (relaunched,
  new job `0a041c6b…`) with 4 committee people running alongside; Cloudinary held (`suspended`); the
  first Tencent job stays `suspended`. AltCarbon — Mitsubishi Heavy Industries account job running;
  Volvo Group held (not started).
- Running by hand and NOT stopped by `dev_stack down`: 4 extra ingestion coordinators, the 2 mismatched
  extra workers were retired once idle (`74f06c95` at 11:26:31, `09200c59` at 11:34:21). `extra5`/`extra6` ARE stopped by `down`.
- 2026-10-05: filed clue-hq/research-and-data#99 — users logged out on weak networks (session_expired redirect on any missing token / backend 401, no retry; backend Clerk leeway 5 s); founder wants 3h+ sessions.
