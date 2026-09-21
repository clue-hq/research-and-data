# 2026-09-22 — lome lane: ports and database

Lane: workspace `lome`, branch `research-streaming-v3` (HEAD `ab31814a2`, PR #72 merge). `.env` and
`apps/frontend/.env.local` arrived as copies of the jerusalem-v1 lane (ports ending in 8, a
`clue_lome` database that was never created) and were re-pointed on 2026-09-22 per the founder.

## Ports (all end in 4; 3020/8010/8020/8030 = san-salvador's live stack, 3028/8018/8028/8038 = jerusalem-v1's)
| port | process |
|---|---|
| 3024 | frontend (Next.js) — `CLUE_APP_ORIGIN`, Clerk authorized parties, design CORS list |
| 8014 | design API (lumen) — `CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN`, frontend `LUMEN_API_BASE_URL` |
| 8024 | platform API — frontend `CLUE_API_BASE_URL` |
| 8034 | platform API twin |

`CLUE_TRIAL_PORT=8010` left as is (trial surface disabled; same as the jerusalem note).

Start ONLY via `./scripts/dev_stack_lome.sh up|down|restart-api|restart-workers|status` (untracked;
body byte-identical to the jerusalem wrapper, header re-labelled). It exports the `DEV_STACK_*`
block from `.env` and refuses on a mismatch with `.env` / `apps/frontend/.env.local`. Logs
`/tmp/lome_*.log`, agent workspaces `/private/tmp/clue-agent-workspaces-lome`. Never `up | tail`.

## Database — founder instruction 2026-09-22: use `clue_san-salvador`
`CLUE_DATABASE_URL` / `DEV_STACK_DB_URL` → `postgresql+asyncpg://clue:clue@localhost:55040/clue_san-salvador`
(the istanbul container). Verified: its `alembic_version` = `5cac3234cfb3` = this branch's single
head, so no migration is needed.

**Hazard, recorded not resolved:** the san-salvador lane's stack was RUNNING on 3020/8010/8020/8030
at the time, on the SAME database. Two stacks over one DB means two fleets claiming the same jobs
and design runs, and every turn made from either UI lands in the other's history. Either stop the
san-salvador stack before `up` here, or clone (`pg_dump | psql` inside `clue-pg-istanbul`, per the
jerusalem note) and repoint both DSN lines. A DB clone WITHOUT the source's `.artifacts` fails every
turn on a missing blob (damascus/jerusalem notes).

## Owed before `up` works
- `.artifacts/` (`CLUE_STORAGE_FS_ROOT`) is absent → rsync san-salvador's (~1 GB) — it holds the
  blobs the shared DB's rows cite.
- `subsystems/clue-design/target/release/lumen-api-helper` not built → `cargo build --release -p
  lumen-api-helper` in `subsystems/clue-design` (lumen-core changed at PR #72; copying an older
  binary mismatches `/build-info`).
- `apps/frontend/node_modules` absent → `npm ci` in `apps/frontend`.
- Sandbox image `clue-agent-sandbox:latest` is present on this host.
- The stray untracked `_memory/2026-09-18-jerusalem-lane-ports.md` copy is left in place.
