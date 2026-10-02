# 2026-09-01 — nashville workspace setup (TEMPORARY note — ports + database)

Temporary operational note for the **nashville** worktree (branch
`design/scene-ad-clipboard`, the scene-ad clipboard lane). Delete or fold into the
lane's close-out when this workspace retires.

## Port map (founder-assigned 2026-09-01 — do not collide with siblings)

| Service      | nashville | (istanbul) | (colombo) |
|--------------|-----------|------------|-----------|
| frontend     | **3023**  | 3020       | 3033      |
| platform API | **8013**  | 8010       | 8052      |
| design API   | **8023**  | 8020       | 8060      |
| fleet worker | **8033**  | 8030       | —         |

Mapping follows the istanbul pattern (3xxx = frontend; 801x/802x/803x = platform /
design / fleet). Istanbul's stack (3020/8010/8020/8030) and colombo's
(3033/8052/8060) must never be touched from this workspace.

## Database

- `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_nashville`
- `clue_nashville` was **cloned from `clue_colombo` 2026-09-01** (pg_dump|psql inside
  the `clue-pg-istanbul` container — the shared dev PG16 at :55040 — because colombo
  had 11 live connections, which rules out CREATE DATABASE … TEMPLATE). Verified:
  317 tables, alembic head `6eff96862040`, ~1 GB. Colombo untouched.
- Redis: `redis://localhost:6379/3` (index **3** — colombo owns /2; istanbul,
  missoula, tunis share /0; stuttgart runs its own :6380).

## Env edits made (local, gitignored files — no parity-rule impact)

- `.env`: DATABASE_URL → clue_nashville (was already set); REDIS /2→/3;
  `CLUE_DESIGN_API_BASE_URL` + `LUMEN_API_ORIGIN` 8060→8023 (were colombo's);
  3023 added to `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` + `LUMEN_API_CORS_ORIGINS`.
- `apps/frontend/.env.local`: `CLUE_API_BASE_URL` 8052→8013;
  `LUMEN_API_BASE_URL` 8060→8023 (were colombo's).
- Left alone: `CLUE_TRIAL_PORT=8010` (inert — `CLUE_TRIAL_ENABLED=false`);
  `CLUE_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-nashville` and
  `CLUE_STORAGE_FS_ROOT=<worktree>/.artifacts` (already nashville-local).

Start the stack only via `DEV_STACK.md`/`dev_stack.sh` (standing rule), overriding
ports to this map. Apollo test login recipe: `_memory/2026-08-27-demo-night-setup.md`.

## Addendum 2026-09-02 (live walk)

- Stack launched by mirroring `scripts/dev_stack.sh` with nashville substitutions (design 8023,
  platform 8013, fleet, frontend 3023; DB/agent root from `.env`; logs `/tmp/nashville-*.log`).
  Helper binary + tailwind runtime copied from istanbul (identical design-subsystem commit).
  `apps/frontend/.env.local` `CLUE_APP_ORIGIN` → `http://localhost:3023` (BFF write-origin guard).
- KNOWN GAP: the DB was cloned from colombo but the BLOB STORE (`.artifacts`) was not — legacy
  assets (Cursor lockup, Apollo wordmark, marble wash) 404 through the asset-store passthrough and
  render blank. Copy colombo's `.artifacts/` if legacy images matter; newly uploaded assets work.
- The Inter font-library `…/bytes` 404s (and the "Brand font unavailable" banner) are pre-existing.
