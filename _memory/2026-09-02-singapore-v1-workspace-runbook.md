# singapore-v1 workspace runbook — ports + database (founder ruling 2026-09-02)

**Binding for every testing / browser run in this worktree.** The trunk runbook
(`DEV_STACK.md` + `scripts/dev_stack.sh`) has been specialized IN THIS WORKTREE to these
values — start the stack ONLY via `./scripts/dev_stack.sh up|down|status`, never ad hoc.

## Port map (founder-assigned; never improvise others)

| Port | Process |
|---|---|
| **3025** | frontend (Next.js) |
| **8015** | platform API (`clue_api.projections_main:app`) |
| **8025** | design API (`lumen_api.main:app`, embedded fleet worker + engine helper) |
| **8035** | fleet worker (`clue_api.fleet_main`) — **reserved**; the worker binds NO port today (queue-driven). |

The trunk's historical 8030 platform-API twin is NOT run in this workspace (nothing here
was ever exercised against it; reinstate deliberately if a session flow wants it).

## Database

- **This workspace's DB:** `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_singapore_v1`
  (already set in `.env`; the dev-stack script pins the psycopg-driver form of the same DB
  for its processes).
- Created 2026-09-02 as a clone of the `clue` database on the same instance
  (`CREATE DATABASE clue_singapore_v1 TEMPLATE clue` — template path worked, zero active
  connections at the time). 314 tables, 395 design_account rows at clone time.
  (First instruction said clone `clue_colombo`; founder corrected mid-turn to `clue`.)
- Upgraded to this branch's alembic head `6eff96862040` immediately after cloning
  (clone was at `518a3784f3a4`).
- psql access: `PGPASSWORD=clue psql -h localhost -p 55040 -U clue -d clue_singapore_v1`.

## What was rewired (all LOCAL, deliberately uncommitted — keep it that way)

Workspace-specific config must not leak into feature-branch history; these stay as
working-tree modifications (`.env`/`.env.local` are untracked anyway):

1. `scripts/dev_stack.sh` — DB_URL → singapore_v1@55040; ports 8010→8025, 8020→8015,
   3020→3025; 8030 twin removed; CORS origins → 3025; **`down()` pkill patterns are now
   port/path-scoped** so it cannot kill sibling workspaces' identically-named processes
   (the fleet-worker pattern keys on the `singapore-v1/.venv` path in the cmdline).
2. `DEV_STACK.md` — specialization banner + every port/DB reference updated to match.
3. `.env` — `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` gained `http://localhost:3025` +
   `http://127.0.0.1:3025` (else sign-in loops). `CLUE_DATABASE_URL` + absolute
   `CLUE_STORAGE_FS_ROOT` (…/singapore-v1/.artifacts) were already correct.
4. `apps/frontend/.env.local` — `CLUE_API_BASE_URL` → 8015, `CLUE_APP_ORIGIN` → 3025,
   `LUMEN_API_BASE_URL` → 8025 (the three guards from DEV_STACK.md's symptom table).

## Gotchas carried forward

- `CLUE_TRIAL_PORT=8010` in `.env` is the (disabled) Sumble trial canary — its 8010 is a
  coincidence with the trunk design-API port, unrelated to this workspace's 8025; left as is.
- Dev login (Clerk test mode): `aryan+clerk_test_design@example.com` / `ClueDev2026!stripe`
  / code `424242`.
- Always `down` before `up` (stale-port trap in DEV_STACK.md's symptom table).
