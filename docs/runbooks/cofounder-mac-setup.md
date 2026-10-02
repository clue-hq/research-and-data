# Running the full stack on a second Mac — onboarding, sign-in, chat + design agent, editor, brand kit, ad library

Written 2026-09-07 for the cofounder's machine, verified against `scripts/dev_stack.sh`,
`.env.example`, `apps/frontend/.env.example`, and the code paths behind self-serve
onboarding. `DEV_STACK.md` remains the authority for the port map, the dev login, and the
five processes; this runbook is the *first-time machine setup* on top of it, sized for the
flows a second person will exercise: **a new account, a new sign-in, onboarding, and the
brand-kit fetch, chatting with the design deepagent, every editor feature, and the ad library** — with at least four concurrent fleet workers (revised 2026-09-08).

## 1. Install once (Homebrew)

```bash
brew install uv node postgresql@17 pgvector redis rustup
rustup-init -y                      # stable Rust; cargo builds the design engine helper
brew services start postgresql@17
brew services start redis
```

| Tool | Why |
|---|---|
| **uv** | `make install` runs `uv sync --all-packages`: one venv (`.venv`) for the platform *and* the design subsystem's Python apps. pip is not used. |
| **Node 24** | Frontend (Next.js) and the design tooling. |
| **PostgreSQL 17 + pgvector** | The only source of truth, on the default port 5432. Postgres.app also works, but exactly one server may own 5432. |
| **Redis** | Not needed for the design flow; the fleet worker's lock client expects it once research lanes run. Cheap to start. |
| **Rust stable** | Builds `lumen-api-helper`, the engine binary the design API calls. No pinned toolchain file. |

Docker is **not** required. The Makefile's `db-up` uses Docker Compose, but the dev stack
expects a local Postgres.

## 2. Repo, venv, database

```bash
git clone git@github.com:clue-hq/research-and-data.git && cd research-and-data
git checkout design/website
make install                                   # uv sync --all-packages → .venv
.venv/bin/python -m playwright install chromium
createdb clue_istanbul_dev
psql clue_istanbul_dev -c "create extension if not exists vector"
CLUE_DATABASE_URL=postgresql+psycopg://$USER@localhost/clue_istanbul_dev .venv/bin/alembic upgrade head
```

- **A fresh database is the right base for onboarding tests.** Self-serve provisioning mints
  the workspace and brand on first sign-in, so no data dump is needed. (To reproduce an
  *existing* workspace instead: `pg_dump -Fc` it, `pg_restore --no-owner` here, copy that
  checkout's `.artifacts/` alongside, then run the `alembic upgrade head` line above.)
- **Run migrations with the stack's DSN, as above.** The repo `.env`'s `CLUE_DATABASE_URL`
  can name a *different* database than the stack uses; a missed migration surfaces as a 500
  on thread pages (`UndefinedColumn`).
- **Chromium for the venv** backs every website thumbnail *and* the brand-kit brief stage,
  which hands screenshots of the captured site to a vision model.

## 3. Build the frontend and the engine (once, and after pulling engine changes)

```bash
cd apps/frontend && npm install && npm run design-system:build && cd ../..
cp apps/frontend/node_modules/@tailwindcss/browser/dist/index.global.js apps/frontend/public/vendor/tailwind-browser.js
cd subsystems/clue-design && cargo build -p lumen-api-helper --release && cd ../..
cd subsystems/clue-design/apps/custom-component-compiler && npm ci && cd ../../../..
```

The Tailwind runtime file is untracked in git; previews render unstyled and web thumbnails
refuse (`thumbnail.tailwind_runtime_missing`) without it. The compiler's `node_modules` are
needed for custom-component compiles.

## 4. Env files

Get the two env files from a teammate **privately** (never through the repo): the root
`.env` and `apps/frontend/.env.local`. Both are at full key parity with their `.env.example`.

> **Do not copy the shared `.env` blindly.** Every path and address in it describes the
> machine it came from: the sender's checkout directory, the sender's Postgres and Redis,
> the sender's ports. Copied as-is, the stack either fails to start (helper binary not
> found, database refused) or — worse — starts and silently writes blobs to a path that
> does not exist on your disk. Go through the table below line by line and set each value
> for **your** machine before the first `up`.

Keys whose values are machine-specific (audit them all; the rest of the file travels as-is):

| Key | What it must say on YOUR machine |
|---|---|
| `CLUE_DATABASE_URL` | your Postgres, your database name (the sender's names their worktree's DB, e.g. `clue_colombo` on port 55040 in Docker) |
| `DEV_STACK_DB_URL` | the same database, `postgresql+psycopg://` form, for `scripts/dev_stack.sh` |
| `CLUE_REDIS_URL` | your Redis (`redis://localhost:6379/<n>`) |
| `CLUE_STORAGE_FS_ROOT` | the **absolute** path to this checkout's `.artifacts` |
| `LUMEN_CORE_HELPER` | the absolute path to `subsystems/clue-design/target/release/lumen-api-helper` **in this checkout** (built in §3) |
| `CLUE_AGENT_WORKSPACE_ROOT` | a scratch dir you own, e.g. `/private/tmp/clue-agent-workspaces` |
| `DEV_STACK_FRONTEND_PORT`, `DEV_STACK_DESIGN_PORT`, `DEV_STACK_PLATFORM_PORT`, `DEV_STACK_PLATFORM2_PORT`, `DEV_STACK_LOG_PREFIX` | your port map (the defaults 3020/8010/8020/8030 are fine on a machine running one stack) |
| `CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN` | `http://127.0.0.1:<your design port>` |
| `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`, `LUMEN_API_CORS_ORIGINS` | must include `http://localhost:<your frontend port>` |

And in `apps/frontend/.env.local`: `CLUE_APP_ORIGIN` (`http://localhost:<your frontend port>`),
`CLUE_API_BASE_URL` (`http://127.0.0.1:<your platform port>`), `LUMEN_API_BASE_URL`
(`http://127.0.0.1:<your design port>`), and `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` (same list
as the root file). The Clerk keys and every API key travel unchanged.

Then the remaining flags to check in the root `.env`:

| Key | Set to |
|---|---|
| `DEV_STACK_DB_URL` | `postgresql+psycopg://<your-macos-username>@localhost/clue_istanbul_dev` |
| `CLUE_STORAGE_FS_ROOT` | the **absolute** path to this checkout's `.artifacts` |
| `LUMEN_CORE_HELPER` | the absolute path to `subsystems/clue-design/target/release/lumen-api-helper` in this checkout |
| `CLUE_SELF_SERVE_PROVISIONING_ENABLED` | `1` — **the flag that gates onboarding** (see §5); defaults to off. It must be IN the file: exported by hand it vanishes on the next restart (2026-09-08 incident: every new account got "Provisioning failed with status 404") |
| `CLUE_DESIGN_API_BASE_URL` | `http://127.0.0.1:<your design port>` — the setup screen enqueues the brand-kit fetch through it; empty means no kit is ever born |
| `DEV_STACK_WORKERS` | `4` — worker **processes** `dev_stack.sh up` starts (founder ruling 2026-09-08: at least four) |
| `CLUE_FLEET_WORKER_CONCURRENCY` | `4` — tasks each process drains at once, so a second chat's turn never queues behind a first chat's design turn |
| `LUMEN_BRAND_AD_ASSETS` | `1` — mounts the ad-library routes (see §5b) |
| `LUMEN_AGENT_OPENROUTER_CHAT_COMPLETIONS` / `LUMEN_AGENT_WEB_SOLO` | `1` / `1` — the design agent's transport and the solo web loop; both ride in the copied file |

Keys the template leaves blank and you must have real values for: `CLUE_OPENROUTER_API_KEY`
and `OPENROUTER_API_KEY`, `LUMEN_AGENT_API_KEY` (the design agent reads its *own* key),
`CLUE_AUTH_CLERK_ISSUER` + `CLUE_AUTH_CLERK_JWKS_URL`, `CLUE_EXA_API_KEY`,
`CLUE_FIRECRAWL_API_KEY`, `CLUE_SUMBLE_API_KEY`, `BRANDFETCH_API_KEY` + `BRANDFETCH_CLIENT_ID`,
`PDL_API_KEY`, `IMAGE_MODEL_API_KEY`, and for the ad library `ADYNTEL_API_KEY` + `ADYNTEL_EMAIL` (Adyntel bills per harvest; a 402 "Insufficient tokens" in the ingestion job means the account needs credits). The model pins (grok-4.6 for the agents,
`CLUE_STAGE0_EXTRACTION_MODEL` for recon) ride along in the copied file — do not change them.

`apps/frontend/.env.local` must keep `CLUE_APP_ORIGIN=http://localhost:3020`,
`CLUE_API_BASE_URL=http://127.0.0.1:8020`, `LUMEN_API_BASE_URL=http://127.0.0.1:8010`, and the
Clerk publishable + secret keys of the shared **Clerk dev instance**. That instance's
dashboard is already configured the way onboarding needs (bot protection off, email
verification by code). Port 3020 is not negotiable: the BFF origin check, Clerk's authorized
parties list (`CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` in `.env`), and the design API's CORS list
all name it.

## 5. What a new account exercises (and what it needs)

1. **Sign-up** (`/onboarding`). A real email receives a real code from the Clerk dev
   instance. An address with `+clerk_test` before the `@` gets the fixed code `424242` and
   no email is sent.
2. **Session establish.** With `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true`, provisioning
   creates one workspace and one brand per valid session, with you as owner. With the flag
   off, the new identity has no workspace, the setup screen's recon refuses before any
   spend, and no brand kit is ever ingested.
3. **Setting-up screen** (`POST /stage0/setup`). Fires Stage-0 recon, which the platform
   enqueues for the fleet workers (both lanes run there; the web process only captures the
   website and offers the work). Extraction
   calls OpenRouter; pages are fetched by scrapling's plain HTTP fetcher (no browser); the
   tier-3 competitor / buyer-profile facts come from Exa. The official-site crawl is off by
   default (`CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`).
4. **Brand-kit ingestion.** The same screen enqueues exactly one website ingestion through
   the design API (`POST /brand-kits/ingest/website`); the job runs on the design API's
   embedded fleet worker: Brandfetch lookup, page capture (Chromium), asset descriptions and
   a brand brief through vision models on OpenRouter. It lands as a **draft** behind the
   Brand-context approval gate; nothing approves it automatically.

Every new workspace spends real credits on OpenRouter, Brandfetch and Exa.

5. **Brand context → Approve.** The ingested kit is a **draft**. Chat-generated ads and
   pages are born on the latest *approved* kit, so approve it on the Brand context page
   before generating in that workspace.

### 5b. The ad library is a separate, manual step

Onboarding never starts the ad library (harvested ads, the ad-DNA card, the pre-generated
grounds). It spends Adyntel credits, so it is started once per workspace, by hand, against
the design API (`LUMEN_BRAND_AD_ASSETS=1` mounts the routes):

```bash
# kit id + version from GET /brand-kits (X-Workspace-Id = the workspace); company_domain = the advertiser's own site
curl -s -X POST http://127.0.0.1:<design port>/brand-ad-assets/onboard \
  -H 'Content-Type: application/json' -H 'X-Workspace-Id: ws_…' \
  -d '{"brand_kit_id":"brand_kit_ing_…","brand_kit_version":1,"company_domain":"insighthealth.ai"}'
# progress / result
curl -s http://127.0.0.1:<design port>/brand-ad-assets/brand_kit_ing_… -H 'X-Workspace-Id: ws_…'
```

Exactly one of `company_domain` or `page_id` (a LinkedIn page id) is required. The job runs
on the fleet workers; the lane answers `card: null, creatives: []` until it finishes.

For source recovery or an ingestion check, add `"harvest_only": true` to the request.
It saves original ad images and their provenance, then skips ad-DNA analysis and background
generation. This still spends provider credits. The flag defaults to `false` and is persisted
with the job so a worker re-drive keeps the same scope. A successful harvest-only job reports
the overall onboarding outcome as `partial`: originals exist, but no new card or generated
imagery was requested. Read the job's steps to distinguish this from a failed harvest.

Before re-running an empty lane, inspect its ingestion job. Website ingestion succeeding
does not mean an ad job was offered. Verify that a resolved LinkedIn page belongs to the
exact advertiser (a regional page or similarly named company is not an equivalent identity).
A provider timeout or HTTP 204/non-JSON error is a failed fetch, not evidence that the brand
has no ads. Keep retries bounded with `max_pages` and `max_creatives`.

### 5c. Chat, design agent, editor

- A project chat's message opens a design leg; the design deepagent (grok-4.6 over OpenRouter,
  `LUMEN_AGENT_MODEL=openai:x-ai/grok-4.6`) generates the ad or page on a fleet worker, streams
  into the output pane, and the artifact opens in the editor. Nothing generates without a worker.
- Editor features (selection, inspector, Fit to text, replace image, clipboard, web annotations)
  need the wasm ↔ helper handshake (`node subsystems/clue-design/scripts/verify_handshake.mjs`
  → `HANDSHAKE OK`) and the vendored Tailwind runtime (§3). After pulling engine changes:
  rebuild the helper, then `down` and `up`.

## 6. Run and verify

```bash
./scripts/dev_stack.sh up          # frontend, design API, two platform APIs, DEV_STACK_WORKERS workers
./scripts/dev_stack.sh status      # every port UP and "fleet-workers: UP (4/4 processes × ... slots)"
grep -m1 fs_root /tmp/browser_fleet_worker.log   # must print THIS checkout's .artifacts
grep -m1 '"event": "worker.start"' /tmp/browser_fleet_worker.log   # must show "concurrency": 4
```

Open http://localhost:3020. For a plain smoke test, sign in with the dev account in
`DEV_STACK.md`. For the onboarding test, sign up with a fresh address and follow the
setting-up screen through to Brand context. Logs: `/tmp/browser_*.log`. Stop with
`./scripts/dev_stack.sh down` — never kill the processes by name (that can take down another
worktree's stack).

## 7. Things that bite

| Symptom | Cause |
|---|---|
| Sign-in loops on "session expired" | `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` lacks `http://localhost:3020` |
| "Your workspace is temporarily unavailable" | platform API on 8020 not up, or `CLUE_API_BASE_URL` wrong |
| New sign-up lands on access-denied / empty workspace picker | `CLUE_SELF_SERVE_PROVISIONING_ENABLED` not `true` |
| Grey thumbnails, canvas never renders, chat fine | `LUMEN_API_BASE_URL` missing from `.env.local`, or Chromium not installed for the venv |
| Design runs die in ~1s | `LUMEN_AGENT_API_KEY` / `LUMEN_AGENT_BASE_URL` unset (the OpenRouter key alone is not enough) |
| "Clone blobs missing", agent composes instead of cloning | `CLUE_STORAGE_FS_ROOT` relative or wrong |
| Setting-up screen sits on "Preparing…" for 4–6 minutes | expected: recon and the brand-kit fetch run on the workers; the page releases you when the fast lane completes |
| Second chat's message does nothing until the first chat finishes | `CLUE_FLEET_WORKER_CONCURRENCY` is 1 or `DEV_STACK_WORKERS` is 1 |
| Brand context shows the kit but the ad library is empty | expected until §5b has been run for that workspace |
| New account: "Provisioning failed with status 404" | `CLUE_SELF_SERVE_PROVISIONING_ENABLED` not set in the `.env` the platform API was started from |
| Brand kit never appears | the design API was down when setup fired; it self-heals on the next replay of the setup screen |
| Stale engine after pulling Rust changes | rebuild the helper, then `down` and `up` — the API loads the binary at start |
| Thread pages 500 with `UndefinedColumn` | migrations were run against the wrong database; rerun the `alembic upgrade head` line from §2 |
