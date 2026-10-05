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

## 4. Research jobs stranded as `suspended` after a lost lease — OPEN (most serious)

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

## 6. Hot retry loop on lease contention — OPEN

- **What happened (~11:25–11:31):** worker `67e90478` (`extra6`) re-claimed Garner Health's Syracuse
  quality-reconciliation tasks hundreds of times in minutes (one task 502 attempts, others 266, 123,
  30) while the job was already `completed`. None of it is logged.
- **Cause:** all reconciliation tasks of one generation share one work id
  (`continuation_work_id`). `clue_fleet/work_worker.py` `_run_leased_task`: when the work lease is
  held, the task is requeued at once and claimed again after the poll interval, so queued siblings
  spin until the holder finishes; then they end `completed` / `superseded`.
- **Impact:** wasted database round-trips and slot time; attempt counts become meaningless for
  diagnosis.
- **Fix needed (OPEN):** back off (`available_at` in the future) when the lease is held, or collapse
  queued continuations for one generation into one task.

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

## Current state at the time of writing (~11:32)

- Brand kits: all three done (Stripe 517/701 described, Garner 95/99, AltCarbon 101/111).
- Research: Garner Health — both account jobs completed; committee research Syracuse 4/4 people
  done, Carmel Clay 1 done and 4 running. Stripe — Tencent Cloud account job running (relaunched,
  new job `0a041c6b…`) with 4 committee people running alongside; Cloudinary held (`suspended`); the
  first Tencent job stays `suspended`. AltCarbon — Mitsubishi Heavy Industries account job running;
  Volvo Group held (not started).
- Running by hand and NOT stopped by `dev_stack down`: 4 extra ingestion coordinators, the 2 mismatched
  extra workers were retired once idle (`74f06c95` at 11:26:31, `09200c59` at 11:34:21). `extra5`/`extra6` ARE stopped by `down`.
