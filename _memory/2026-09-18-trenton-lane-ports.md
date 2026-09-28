# 2026-09-18 — trenton lane: ports and env

Lane: workspace `trenton`, branch `research-streaming-v3` (cut at `1c629c040`, the same HEAD as
`jerusalem-v1`). `.env` and `apps/frontend/.env.local` were copied from the jerusalem-v1 lane
(already re-pointed at `clue_trenton` and the `trenton` absolute paths) and on 2026-09-18 the
ports were moved from jerusalem's all-8 series to an all-9 series.

## Ports (all end in 9; 3020/8010/8020/8030 = runbook lane, 3028/8018/8028/8038 = jerusalem-v1)
| port | process |
|---|---|
| 3029 | frontend (Next.js) — `CLUE_APP_ORIGIN`, Clerk authorized parties, design CORS list |
| 8019 | design API (lumen) — `CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN`, frontend `LUMEN_API_BASE_URL` |
| 8029 | platform API — frontend `CLUE_API_BASE_URL` |
| 8039 | platform API twin |

Start ONLY via `./scripts/dev_stack_trenton.sh up|down|restart-api|restart-workers|status` — a
byte-for-byte sibling of the jerusalem wrapper with only the header changed: it exports the
`DEV_STACK_*` block from `.env` and refuses to start when `.env` / `apps/frontend/.env.local`
disagree with it. 4 workers × 3 slots, logs `/tmp/trenton_*.log`, agent workspaces
`/private/tmp/clue-agent-workspaces-trenton`. `./scripts/dev_stack_trenton.sh status` passed the
env-consistency checks on 2026-09-18.

## Database
`clue_trenton` on `localhost:55040` (the `clue-pg-istanbul` container, the instance that also holds
`clue_san-salvador`) was created 2026-09-18 as a `pg_dump | psql` clone of the LIVE
`clue_san-salvador`, run inside the container (host pg_dump is v15, server v16; a TEMPLATE copy
needs the source idle and it had ~25 live connections). Verification recorded in the recap of
that session: per-table row counts identical, alembic current = `be968ae45500` = this branch's
single head. NOTE: Conductor also provisions a per-workspace `clue-pg-trenton` container on
:55160 — the lane does NOT use it; `.env` pins :55040.

## Owed before `up` fully works (same list as jerusalem's)
- `subsystems/clue-design/target/release/lumen-api-helper` is not built in this worktree
  (`cargo build --release` in `subsystems/clue-design`).
- ~~`.artifacts/` missing~~ DONE 2026-09-18 19:50: the first live turn failed with
  `ArtifactIntegrityError: artifact blob is missing` (the pinned brand-knowledge documents cite
  blobs from san-salvador's store) and showed as "Queued" forever in the UI. Fixed by
  `rsync -a --ignore-existing san-salvador/.artifacts/ .artifacts/` (949 MB). A cloned DB needs its
  `.artifacts` copied in the same step — record this in the next lane clone.
- Follow-up (product, unowned): a fleet task that fails BEFORE the turn stream opens (here in
  `read_pinned_documents`) emits no `turn.failed`, so the chat bubble stays "Queued" instead of
  showing the failure. Task `5e56d46c…` on thread `thr_78372b31…` is the repro.
- `CLUE_TRIAL_PORT=8010` left as is (trial surface disabled).
- `scripts/dev_stack_trenton.sh` is untracked, not committed — founder review, as with jerusalem's.
