# Dev stack — how to run the platform + design agent locally

Written 2026-08-29 from a live session where rebuilding this from memory cost an evening.
Everything below is the tested configuration. **If a port or flag changes, change it here
and in `scripts/dev_stack.sh` — never only in a terminal.**

## TL;DR

```bash
./scripts/dev_stack.sh up       # starts all five processes
./scripts/dev_stack.sh status   # shows what's up
./scripts/dev_stack.sh restart-api   # restarts ONLY the two platform API processes (picks up a changed .env setting; workers keep theirs until down/up)
./scripts/dev_stack.sh restart-workers   # restarts ONLY the fleet workers, same count × concurrency as the wrapper sets; check nothing is mid-job first
./scripts/dev_stack.sh down     # stops everything
```

Then open **http://localhost:3020** and sign in:

| | |
|---|---|
| Email | `aryan+clerk_test_design@example.com` |
| Password | `ClueDev2026!stripe` |
| Email code | `424242` (fixed — Clerk test-mode `+clerk_test` address, no real email is sent) |

## Running the same stack from another worktree (added 2026-09-11)

`scripts/dev_stack.sh` reads five `DEV_STACK_*` knobs, each defaulting to exactly what the
istanbul checkout always did, so a lane can run the identical five processes on the identical
ports against **its own** database without copying the script:

| Knob | Meaning | istanbul default |
|---|---|---|
| `DEV_STACK_DB_URL` | the database every process uses | `clue_istanbul_dev` (psycopg) |
| `DEV_STACK_WORKERS` | fleet worker **processes** | 1 |
| `DEV_STACK_WORKER_CONCURRENCY` | drain slots per process (`CLUE_FLEET_WORKER_CONCURRENCY`) | 1 |
| `DEV_STACK_AGENT_WORKSPACE_ROOT` | `CLUE_AGENT_WORKSPACE_ROOT` | `/private/tmp/clue-agent-workspaces` |
| `DEV_STACK_LOG_PREFIX` | log file prefix | `/tmp/browser` |

A lane sets them in a wrapper script next to the runbook, never in a shell export. The first one is
**`scripts/dev_stack_san_salvador.sh`** (the ARV2 lane on branch `track-r4`): DB from that
checkout's `.env` (`clue_san-salvador` on :55040), 4 workers × 3 slots (the O6 exit-gate ruling),
logs at `/tmp/san-salvador_*.log`. Because the ports are the same, **only one of the two stacks
can run at a time** — `down` the other first. Everything else in this file (login, symptom table,
prerequisites) applies unchanged; the lane's `apps/frontend/.env.local` must name 8020 / 8010 /
`http://localhost:3020` like istanbul's, and its `.env` must carry
`LUMEN_API_ORIGIN=http://127.0.0.1:8010` and 3020 in `LUMEN_API_CORS_ORIGINS`.

## The port map (memorize the first one)

| Port | Process | Why it must be exactly this |
|---|---|---|
| **3020** | frontend (Next.js) | THE app port. Three separate guards reject anything else: `CLUE_APP_ORIGIN` in `apps/frontend/.env.local` (the BFF 403s **writes** from other origins — chat send silently dies), Clerk's `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` in `.env` (sign-in loops on "session expired"), and the design API's CORS list. Running on 3000/3030 produces exactly those three symptoms, one at a time. |
| 8010 | design API (`lumen_api.main:app`) | `CLUE_DESIGN_API_BASE_URL` points here; serves the editor, asset store, design tools. |
| 8020 | platform API (`clue_api.projections_main:app`) | `CLUE_API_BASE_URL` in `apps/frontend/.env.local` points here — auth/session + the whole `/api/v1` surface. **Without it: "Your workspace is temporarily unavailable."** |
| 8030 | platform API (second instance, same app) | Historical twin; some flows were exercised against it. Cheap to run, keep it. |
| — | fleet worker (`clue_api.fleet_main`) | Drives design runs. **No worker = messages accepted but nothing ever generates.** |

## `.env` keys that break everything when missing (all already set — do not remove)

| Key | Why |
|---|---|
| `CLUE_STORAGE_FS_ROOT` (ABSOLUTE path to this checkout's `.artifacts`) | Every process must read/write the same blob store. A process without it silently falls back to `/private/tmp/lumen-dev-storage` and the stack splits — DB rows point at bytes nobody can find ("clone blobs missing", agent composes instead of cloning). |
| `LUMEN_AGENT_API_KEY` + `LUMEN_AGENT_BASE_URL` | The design agent reads its OWN names; `CLUE_OPENROUTER_API_KEY` alone is not enough. Missing → design runs die in ~1s. |
| `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` includes `http://localhost:3020` | Else sign-in loops forever on "session expired" (the backend rejects every token minted by the tab). |
| `CLUE_SCRAPE_BACKEND=scrapling` + `CLUE_STAGE0_PAGE_FETCHER=scrapling` | Standing rule; Firecrawl showing in logs means the env is wrong. |
| `LUMEN_API_BASE_URL=http://127.0.0.1:8010` — in **`apps/frontend/.env.local`**, not `.env` | The frontend's design proxy (`/api/clue/design/*`) needs it. Missing → every design render 500s: **grey gallery thumbnails, editor canvas never renders** — while chat and generation work fine, which makes it look like the design finished "invisibly". Found live 2026-08-29 (was an ad-hoc shell export that evaporated at a stack rebuild). |
| Model pins: grok-4.6 everywhere | Env alone is NOT enough — catalog profile (head-of-abm v40), registry promotion, composer pins, and the gateway chat-completions flag all matter. GPT-5.6-terra in the picker → `missing_finalize` step failures. |

## One-time machine prerequisites

- Postgres running locally; dev DB `clue_istanbul_dev` at head (`alembic upgrade head`).
- Repo venv at `.venv` (used by every python process — never bare `python`).
- `apps/frontend`: `npm install && npm run design-system:build` (canvaskit-wasm comes with install).
- Design engine helper built: `subsystems/clue-design/target/release/lumen-api-helper`.
- **Playwright chromium available to the venv (once per machine):**
  `python -m playwright install chromium`, from the repo `.venv` — the same venv the design
  API runs in. It backs the design preview renders **and** every **web** gallery thumbnail;
  without it `GET /documents/{id}/thumbnail` for a web document answers a typed 502
  (`thumbnail.capture_failed`) and every web gallery card falls back to the empty preview
  frame. Scene/ad thumbnails do not need it — they come from the engine's own Skia PNG export.
- Vendored Tailwind runtime present: `apps/editor/public/vendor/tailwind-browser.js` (untracked in git — previews render unstyled without it).
  It is also what the **web thumbnail** capture inlines: with no runtime the thumbnail
  route refuses loudly with `thumbnail.tailwind_runtime_missing` (a 502) rather than
  screenshotting an unstyled page, and the card shows the empty frame. The route's resolver
  searches both homes — `apps/editor/public/vendor/tailwind-browser.js` **and**
  `apps/frontend/public/vendor/tailwind-browser.js`, plus either app's
  `node_modules/@tailwindcss/browser/dist/index.global.js` — so either copy satisfies it.
  `LUMEN_TAILWIND_RUNTIME=/abs/path/to/tailwind-browser.js` overrides the search path
  (same env the agent runtime's preview capture uses); a set-but-missing path is a
  refusal, not a fall-through to the default candidates.
  The route's full typed-502 vocabulary is four codes: `thumbnail.tailwind_runtime_missing`,
  `thumbnail.capture_failed`, and the kind-aware engine-error split
  `thumbnail.render_failed` (web) / `thumbnail.export_failed` (scene/ad).
- **The design-API process must be able to HTTP-fetch its own advertised origin**
  (`request.base_url`). The web-thumbnail capture composes the document's asset URLs against
  that origin and the headless page fetches them itself, so if the public host is not
  reachable from inside the API's own network — the usual reverse-proxy split — the capture
  still returns **200 with the imagery silently missing**. Nothing client-side can detect
  that (it is a valid PNG), and the immutable `?v=` cache then pins the bad artwork for the
  whole life of that document version. Locally this is free (the API's origin is its own
  `127.0.0.1:8010`); on any deployment, check it before trusting a thumbnail.
- `/private/tmp/clue-agent-workspaces` exists with mode 700 (the script creates it).

## Verifying the stack is actually healthy (30 seconds)

```bash
./scripts/dev_stack.sh status                          # all five UP
grep -m1 fs_root /tmp/browser_fleet_worker.log         # must print .../istanbul/.artifacts
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8020/auth/v1/session   # 401 = auth surface alive
```

Then in the browser: sign in → workspace loads → open a project → send "ping" in a chat →
the message must get a response. If all four work, the stack is genuinely up.

## Running / watching a design generation

1. In a project chat, ask for the page. Head-of-ABM opens a **design session** (the editor
   tab appears with an empty grey canvas — that's normal, nothing generated yet).
2. Your **next** message in that thread starts generation (5–20 min on grok-4.6).
3. Watch progress: `tail -f /tmp/browser_fleet_worker.log` — the `"completion"` fields are
   the agent narrating its steps. `"served_model"` confirms which LLM is really answering.
4. **Previews on disk** (per iteration, before anything commits):
   `subsystems/clue-design/.deepagent-workspace/run_<INNER-ID>/iter_N/preview_1440.png`
   — the inner `run_…` id is the one printed in the worker log lines (it differs from the
   outer job id in `design_agent_run`).
5. Full run forensics: `.venv/bin/python subsystems/clue-design/scripts/run_view.py <run_id>`
   (needs `CLUE_DATABASE_URL` + absolute `CLUE_STORAGE_FS_ROOT` in env).
6. Turns are transactional: the canvas/gallery only update when the turn **finishes**. A
   stopped or failed turn saves nothing.

## Stopping a stuck/unwanted design run

```bash
pkill -f clue_api.fleet_main                       # kills the turn transactionally — nothing half-saved
psql -d clue_istanbul_dev -c "UPDATE design_agent_run SET status='failed' WHERE status='running'"
./scripts/dev_stack.sh up                          # worker comes back idle (script is idempotent-ish; or relaunch just the worker)
```

## Symptom → cause table (every one of these happened live on 2026-08-29)

| Symptom | Cause |
|---|---|
| "Your workspace is temporarily unavailable" | Nothing listening on **8020** (`CLUE_API_BASE_URL` target). |
| Sign-in loops on "Your session has expired" | Tab's port missing from `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`. |
| Signed in, but Enter/send does nothing in chat | Tab's origin ≠ `CLUE_APP_ORIGIN` (BFF 403s all writes). Use **3020**. |
| Agent says clone "blobs are missing" and composes instead | Storage-root split (`CLUE_STORAGE_FS_ROOT` unset in some process) — or blob files present but `artifact` custody rows missing (a blob is only readable through its DB row). |
| Design run dies in ~1 second | Worker missing `LUMEN_AGENT_API_KEY`/`LUMEN_AGENT_BASE_URL`. |
| `missing_finalize` step failures | Wrong model (gpt-5.6-terra) — the platform's grok-4.6 pins aren't in effect. |
| Editor tab opens with an empty grey canvas | Normal — the design session is open; generation starts on your next message. |
| Design run FINISHED but gallery thumbnails stay grey / editor won't render the page | `LUMEN_API_BASE_URL` missing from `apps/frontend/.env.local` — the design proxy 500s. Check: `grep "LUMEN_API_BASE_URL is required" /tmp/browser_frontend.log`. |
| Fresh-DB worker won't boot (recipe/schema errors) | Recipe seeding validates all revisions against today's registry — see `_memory/` 2026-08-29 notes (recipe0 v16–18 are replay-only; stale profile digests must be re-pinned). |
| `up` reports every process UP, but a route/endpoint that exists on this branch 404s from the API (e.g. `/documents/{id}/thumbnail` missing from `/openapi.json`) | **A stale process from an earlier session still owns the port.** `up` does not `down` first, so the new uvicorn dies with `[Errno 48] address already in use` while the OLD one keeps serving — and `status` only checks that *something* listens, so it reports UP. Check: `grep -c "address already in use" /tmp/browser_design_api.log` and `ps -o lstart -p $(pgrep -f "uvicorn lumen_api.main:app")`. Fix: always `down` before `up`, and if a port survives it, `lsof -iTCP:<port> -sTCP:LISTEN -t \| xargs kill -9`. Found live 2026-08-31. |
| Gallery cards are grey/empty for **web** documents only (ads are fine) | No Playwright Chromium, or no vendored Tailwind runtime, on the design-API process — see the prerequisites above. The API log names which: `thumbnail.capture_failed` vs `thumbnail.tailwind_runtime_missing`. Nothing is poisoned — fix the prerequisite and the next gallery read regenerates. |
| ONE route 404s while its siblings work (e.g. `/projects/…/chats/…` → Next 404, but `/projects/…` 307s to sign-in; page.tsx exists on disk; DB rows exist) | Corrupted Next dev build cache — repeated `down` cycles pkill the dev server mid-write and its route graph can drop a route. Fix: `down` → `rm -rf apps/frontend/.next` → `up`. Found live 2026-08-30. |

## Two rules learned the hard way (2026-09-12)

* **Never pipe the wrapper's output** (`… restart-workers | tail`). The `( … & )` subshells that
  spawn the API twins and the workers stay alive as their parents and keep the pipe's write end
  open, so `tail` never sees end-of-file and the caller hangs for as long as the stack runs.
  Redirect to a file instead: `./scripts/dev_stack_san_salvador.sh restart-workers > /tmp/x.log 2>&1`.
* **Every kill pattern is anchored on this workspace's interpreter path.** Sibling worktrees
  (semarang, istanbul, …) run the same module names on the same box; a bare
  `pkill -f clue_api.fleet_main` from any launcher kills every worktree's workers. This lane's
  workers were stopped that way at 14:18 on 2026-09-12 by a launcher outside this workspace.
