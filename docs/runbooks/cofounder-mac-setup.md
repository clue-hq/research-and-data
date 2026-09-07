# Running the full stack on a second Mac — onboarding, sign-in, brand-kit fetch

Written 2026-09-07 for the cofounder's machine, verified against `scripts/dev_stack.sh`,
`.env.example`, `apps/frontend/.env.example`, and the code paths behind self-serve
onboarding. `DEV_STACK.md` remains the authority for the port map, the dev login, and the
five processes; this runbook is the *first-time machine setup* on top of it, sized for the
flows a second person will exercise: **a new account, a new sign-in, onboarding, and the
brand-kit fetch.**

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
Then change only the machine-specific lines in the root `.env`:

| Key | Set to |
|---|---|
| `CLUE_DEV_DB_URL` | `postgresql+psycopg://<your-macos-username>@localhost/clue_istanbul_dev` |
| `CLUE_STORAGE_FS_ROOT` | the **absolute** path to this checkout's `.artifacts` |
| `LUMEN_CORE_HELPER` | the absolute path to `subsystems/clue-design/target/release/lumen-api-helper` in this checkout |
| `CLUE_SELF_SERVE_PROVISIONING_ENABLED` | `true` — **the flag that gates onboarding** (see §5); defaults to off |

Keys the template leaves blank and you must have real values for: `CLUE_OPENROUTER_API_KEY`
and `OPENROUTER_API_KEY`, `LUMEN_AGENT_API_KEY` (the design agent reads its *own* key),
`CLUE_AUTH_CLERK_ISSUER` + `CLUE_AUTH_CLERK_JWKS_URL`, `CLUE_EXA_API_KEY`,
`CLUE_FIRECRAWL_API_KEY`, `CLUE_SUMBLE_API_KEY`, `BRANDFETCH_API_KEY` + `BRANDFETCH_CLIENT_ID`,
`PDL_API_KEY`, `IMAGE_MODEL_API_KEY`. The model pins (grok-4.6 for the agents,
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
3. **Setting-up screen** (`POST /stage0/setup`). Fires Stage-0 recon: the fast lane runs
   *inside the platform web process*, the background lane on the fleet worker. Extraction
   calls OpenRouter; pages are fetched by scrapling's plain HTTP fetcher (no browser); the
   tier-3 competitor / buyer-profile facts come from Exa. The official-site crawl is off by
   default (`CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`).
4. **Brand-kit ingestion.** The same screen enqueues exactly one website ingestion through
   the design API (`POST /brand-kits/ingest/website`); the job runs on the design API's
   embedded fleet worker: Brandfetch lookup, page capture (Chromium), asset descriptions and
   a brand brief through vision models on OpenRouter. It lands as a **draft** behind the
   Brand-context approval gate; nothing approves it automatically.

Every new workspace spends real credits on OpenRouter, Brandfetch and Exa. Ad-asset
generation is off by default (`LUMEN_BRAND_AD_ASSETS=0`).

## 6. Run and verify

```bash
./scripts/dev_stack.sh up          # five processes; prints the URL and the dev login
./scripts/dev_stack.sh status      # all five UP
grep -m1 fs_root /tmp/browser_fleet_worker.log   # must print THIS checkout's .artifacts
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
| Setting-up screen stalls, then continues | expected: the recon fast lane blocks the web process during each extraction |
| Brand kit never appears | the design API was down when setup fired; it self-heals on the next replay of the setup screen |
| Stale engine after pulling Rust changes | rebuild the helper, then `down` and `up` — the API loads the binary at start |
| Thread pages 500 with `UndefinedColumn` | migrations were run against the wrong database; rerun the `alembic upgrade head` line from §2 |
