# 2026-08-22 — Local full-stack run (API + fleet worker + frontend)

Goal session, not a code change: bring the platform up on localhost against the
founder's existing workspace `ws_ade9e215338c4da78aadc87692e4cce6` ("Insight Health").

## What the environment actually looked like

- **No docker on this machine.** The repo's Conductor `setup` script provisions a private
  per-workspace Postgres *via docker* on `$CONDUCTOR_PORT`; that is why the supplied `.env`
  carried `...@localhost:55040/clue` and why nothing answered there. The only live server is
  Homebrew `postgresql@17` on **5432** (running since 2026-08-09).
- **The `clue` database on 5432 does not belong to `main`.** It was stamped
  `a1c5b9842f0e` — a revision that exists only on
  `origin/platform/comprehensive-account-contact-research` (52 commits / ~40 migrations ahead
  of `main`: design lane part III, Stage-0 onboarding runtime, FI-4 self-serve auth).
- **The supplied `.env` is that branch's env, not main's.** Decisive tell: `design_runtime_enabled`,
  `budget_controls_enabled`, `chat_dev_inspector_*` exist in `clue_config.settings` only on that
  branch. Running main's code against that DB would have been old code on a much newer schema.
- The repo was re-cloned today (`/Users/shashank/Documents/clue-accounts/research-and-data`,
  reflog: `clone` @ 2026-08-22), so **no `.artifacts` root survived**. Chat transcripts written
  2026-08-16..18 keep their rows but their blobs are gone → those messages render
  `body_unavailable_reason: artifact_missing`. New messages are unaffected.

## What was done

- Wrote `.env` (repo root) and `apps/frontend/.env.local` from the supplied contents.
- Created a **git worktree** at `/Users/shashank/Documents/clue-accounts/run-comprehensive` on
  `origin/platform/comprehensive-account-contact-research` (detached at `c5f41bcd`) so the
  running stack matches the database, without touching either checkout's branch.
- Ran `uv sync --all-packages` + `npm install` + `npm run design-system:build` there.
- `alembic upgrade head` on `clue`: `a1c5b9842f0e` → **`612428f3731f`** (11 forward revisions;
  committee axis / coverage-field widening / product-knowledge pins). One head.
- Started, all from the worktree with `CLUE_DATABASE_URL` + `CLUE_REDIS_URL` **exported**
  (`clue_db.database_url()` / `clue_locks` read `os.environ` only — they never read `.env`;
  only `clue_config.Settings` does):
  - `python -m clue_api.projections_main` → http://127.0.0.1:8000 (log `/tmp/clue-api.log`)
  - `python -m clue_api.fleet_main` → worker + design_job lane (log `/tmp/clue-fleet.log`)
  - `npm run dev` in `apps/frontend` → http://localhost:3000 (log `/tmp/clue-frontend.log`)

## Deviations from the supplied `.env` (three, all forced)

1. `CLUE_DATABASE_URL` → `...@localhost:5432/clue` (55040 has no listener without docker).
2. Added `CLUE_STORAGE_BACKEND=fs` + `CLUE_STORAGE_FS_ROOT=/Users/shashank/Documents/clue-accounts/clue-artifacts`
   — the supplied file predates the storage block; without it the root defaults to the relative
   `.artifacts`, which the runbook forbids pairing with a long-lived DB.
3. `CLUE_CONTACT_CHANNEL_ENRICHMENT_ENABLED=true` → `false`. It is a **loud boot refusal** for the
   worker: `EntityResearchProductionCompositionError: channel enrichment is enabled without an
   independent validator-backed coordinator`. Same unowned composition gap first recorded
   2026-08-09; the branch's own `.env.example` keeps it off pending slice F. The API boots either
   way (it never builds the entity-research fleet) — only `fleet_main` refuses.
   Also set `CLUE_AGENT_WORKSPACE_ROOT=/private/var/tmp/clue-agent-workspace` (mode 0700; the
   supplied value was empty → `WorkspaceConfigurationError`).

## Posture the supplied `.env` selects (not changed — worth a decision)

- `CLUE_PRODUCT_PATH` is absent → `default`, so the §9 pilot overlay is **not** applied:
  `CLUE_FRONTEND_READ_ENABLED=false` (the `/frontend/v1` router is genuinely not mounted — verified
  against `/openapi.json`), plus `EXA_ACCOUNT_DEEP` / `SUMBLE_COMMITTEE` / `C7_SNAPSHOT` /
  `C7_PRODUCTION_HANDOFF` off. `CLUE_PRODUCT_PATH=integration_pilot` is the one-knob activation.
- `apps/frontend/.env.local` leaves `CLUE_ACCOUNTS_API_BASE_URL` commented → accounts/contacts
  screens stay on fixtures. Consistent with the backend router being off; both sides must flip.
- `CLUE_CLERK_JWT_TEMPLATE=clue-api` and `CLUE_AUTH_CLERK_AUDIENCE=clue-api` are **dead keys**
  since the 2026-08-09 session-token-native ruling; harmless (`extra="ignore"`), but they mislead.
- Auth is live Clerk: `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES=http://localhost:3000`, so the browser
  must use `localhost:3000`, not `127.0.0.1:3000`, or `azp` verification fails closed.

## Workspace / membership state (no changes made)

`ws_ade9e215338c4da78aadc87692e4cce6` already has two active memberships — `Www Test`
(clerk `user_3I1vhX…`, **owner**) and `Aryan Keshri` (clerk `user_3HsF4L…`, **admin**) — and
3 projects. Signing in with either linked Clerk account lands in it; a *new* Clerk account
self-provisions its own workspace instead and would need a membership row added.

## Verification

- `/openapi.json` 200; chat/projects/agent/project_runs surfaces present; no `/frontend/v1`.
- `GET /` → 307 `/sign-in?reason=session_expired` → 307 `/onboarding/sign-in` → 200.
- Worker log: `fleet.boot.handlers_registered phases=[review]`, `design_fleet.handler_registered`,
  `design_reaper.started`, `worker.start`. Both processes log the same `storage.backend.configured`
  root (the durability-unit check the runbook asks for).
- Not verified: an authenticated browser pass (needs the founder's Clerk credentials).

## Follow-ups

- Decide whether this session should run `CLUE_PRODUCT_PATH=integration_pilot`.
- `clue_winnipeg` was created this session as the winnipeg workspace's own database (empty,
  migrated to this branch's head `5d7ab295742b`) and is what this workspace's `.env` points at.
  Keep it for branch-local work, or drop it — the running stack does not use it.
- Remove the worktree with `git worktree remove /Users/shashank/Documents/clue-accounts/run-comprehensive`
  when the session ends.
