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

## Database — `clue_lome`, a clone of `clue_san-salvador` (founder ruling 2026-09-22, second pass)
The first instruction ("use `clue_san-salvador`") was superseded the same day once the hazard below
was raised: `clue_lome` was created inside `clue-pg-istanbul` (55040) as a `pg_dump | psql` clone
of the LIVE `clue_san-salvador` (dump inside the container — host pg_dump is v15 vs the v16 server).
Verified: 0 errors in `/tmp/lome_db_clone.log`, 345 tables both sides, row parity on workspace /
project / agent_turn / claim / account_entity / design_document / provider_call_ledger,
`alembic_version` = `5cac3234cfb3` = this branch's single head. Both DSN lines in `.env` point at
`postgresql+asyncpg://clue:clue@localhost:55040/clue_lome`.

**Hazard that drove the clone:** the san-salvador lane's stack was RUNNING on 3020/8010/8020/8030
on `clue_san-salvador`; two stacks over one DB means two fleets claiming the same jobs and every
turn from either UI landing in the other's history. A DB clone WITHOUT the source's `.artifacts`
fails every turn on a missing blob (damascus/jerusalem notes) — hence the rsync below.

## Owed before `up` works
- `.artifacts/` (`CLUE_STORAGE_FS_ROOT`): rsync from `../san-salvador/.artifacts/` STARTED 2026-09-22
  (log `/tmp/lome_artifacts_rsync.log`); confirm it finished before `up`.
- `subsystems/clue-design/target/release/lumen-api-helper` not built → `cargo build --release -p
  lumen-api-helper` in `subsystems/clue-design` (lumen-core changed at PR #72; copying an older
  binary mismatches `/build-info`).
- `apps/frontend/node_modules` absent → `npm ci` in `apps/frontend`.
- Sandbox image `clue-agent-sandbox:latest` is present on this host.
- The stray untracked `_memory/2026-09-18-jerusalem-lane-ports.md` copy is left in place.

## 2026-09-22 — first `up` on this lane (branch `feat/add-general-purpose-web-search-exa`)
- Helper binary COPIED from `../jerusalem-v1` (Rust source identical to `ab31814a2` on both sides;
  `git diff --stat` empty on crates/Cargo.*), not built here. `npm ci` done. `.artifacts/` rsynced.
- All seven processes UP via the wrapper (`up > /tmp/lome_up.log`, never `| tail`).
- **Environment defect found and repaired on the clone:** every fleet worker died at boot with
  `RecipeVersionConflict: recipe0-stage0@29 already exists with a different definition`. The
  san-salvador DB (and so this clone) holds a `@29` row seeded 2026-09-19 by the pre-merge
  design-fleet-parallelism branch (it pins `open_design_leg@5` and lacks `run_python@1`); the
  merged tree's v29 file is the base's. `recipe_revision` is append-only by trigger, and 4
  executions + 2 events reference the row, so it was rewritten IN PLACE to the file's definition
  (digest `0521a8c0…` → `c0f92871…`) with `DISABLE TRIGGER USER` inside one transaction, trigger
  re-enabled (`tgenabled=O`). Workers then seeded @30 and @31 and stayed up.
  **Founder action:** `/tmp/san-salvador_fleet_worker*.log` show the SAME conflict — the
  san-salvador stack's workers are dead; that live DB needs the same one-row repair (or a fresh
  seed) before its stack does any agent work.
- `restart-workers` exits 0 here (no hang seen this time).

- 2026-09-22 (later): stack DOWN for the research-streaming merge. After it, `clue_lome` sits at
  `5cac3234cfb3` and the tree head is the join `7c4fe6965720` — run `alembic upgrade head` against
  the lane DSN before `up`.
