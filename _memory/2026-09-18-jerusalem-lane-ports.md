# 2026-09-18 — jerusalem-v1 lane: ports and env

Lane: workspace `jerusalem-v1`, branch `design/account-binding-v1`. `.env` was copied from another
workspace on 2026-09-18 and re-pointed at this lane.

## Ports (all end in 8; 3020/8010/8020/8030 belong to another lane's running stack)
| port | process |
|---|---|
| 3028 | frontend (Next.js) — `CLUE_APP_ORIGIN`, Clerk authorized parties, design CORS list |
| 8018 | design API (lumen) — `CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN`, frontend `LUMEN_API_BASE_URL` |
| 8028 | platform API — frontend `CLUE_API_BASE_URL` |
| 8038 | platform API twin |

Start ONLY via `./scripts/dev_stack_jerusalem.sh up|down|restart-api|restart-workers|status`.
Unlike the hangzhou wrapper it hard-codes nothing: it exports the `DEV_STACK_*` block from `.env`
and refuses to start when `.env` / `apps/frontend/.env.local` disagree with it. 4 workers × 3 slots,
logs `/tmp/jerusalem-v1_*.log`, agent workspaces `/private/tmp/clue-agent-workspaces-jerusalem-v1`.

## Fixed while re-pointing
- Every absolute path in `.env` spelled the workspace `jersalem-v1` (a directory that does not
  exist); all occurrences now read `jerusalem-v1`.

## Owed before `up` works
- ~~Database `clue_jerusalem-v1` does not exist~~ DONE 2026-09-18: created inside the
  `clue-pg-istanbul` container as a `pg_dump | psql` clone of the LIVE `clue_san-salvador`
  (a TEMPLATE copy needs the source idle; the host pg_dump is v15 vs the v16 server, so dump
  inside the container). Verified: 340 tables row-for-row identical, alembic `be968ae45500` =
  this branch's single head, `.env` DSN connects. Two sibling branches (chat attachments; design
  agent context management) were cut from this branch and run in parallel; a third will be cut
  after the next discussion here.
- `subsystems/clue-design/target/release/lumen-api-helper` is not built in this worktree
  (`cargo build --release` in `subsystems/clue-design`).
- `.artifacts/` (`CLUE_STORAGE_FS_ROOT`) does not exist yet; check whether the storage layer creates it.
- `CLUE_TRIAL_PORT=8010` left as is (trial surface disabled).
- `scripts/dev_stack_jerusalem.sh` is untracked, not committed — founder review.

## 2026-09-19 — after the pull to research-streaming `5828dfd17` (PR #63 chat-rename, PR #64 add-attachment)
- Alembic head is now `d659c2d2b537` (chat_upload + agent_turn_submission_attachment); the lane
  DB `clue_jerusalem-v1` still sits at `be968ae45500` → run `alembic upgrade head` against the
  lane DSN before `up`.
- `.env` is missing the five `CLUE_CHAT_ATTACHMENT_*` keys (example lines 461-465, defaults
  10 files / 150 MB / 10 MB image / 5 MB text / 20 history images); the naming keys are in.
- `.artifacts/` is still absent: the damascus close-out shows a DB clone WITHOUT the source's
  `.artifacts` fails turns on missing blobs — copy san-salvador's `.artifacts` (923 MB) too.
- 2026-09-19 pull #2 → `21e3ef1e9` (PR #65/#66 design session continuity, PR #67 design agent
  account + seller context). No migration, no new env key; alembic head still `d659c2d2b537`.
  The ff aborted twice on `.context/attachments/*` now tracked upstream: all overlapping local
  copies were byte-identical (13 macOS screenshots have a U+202F in the name — compare with
  `git diff -z`, not `--name-only`), removed, and recreated by the checkout.
- 2026-09-19 22:05 — stack UP for the first time on this lane (all 7 processes) via the wrapper.
  Prep done: `npm ci` in apps/frontend; helper binary COPIED from the
  design-agent-account-context-transfer worktree (Rust source identical to HEAD, `git diff` empty
  on crates/Cargo.*), not built here; `.artifacts/` rsynced from san-salvador (1.0 GB); lane DB
  migrated be968ae45500 → d659c2d2b537; the five `CLUE_CHAT_ATTACHMENT_*` keys appended to `.env`
  (the file had no trailing newline — a blind `>>` glued the first line; fixed). A stale stack
  from 21:59 (no helper, no artifacts, frontend dead on missing node_modules) was `down`ed first.
  Trap re-learned: never pipe `dev_stack_jerusalem.sh up | tail` — the runbook says so; the
  detached subshells hold the pipe and the command never returns.
- 2026-09-20 pull #3 → `264acf834` (PR #70 projects directory + home). Lane DB migrated
  d659c2d2b537 → 5358a2422cb2; `.env` `CLUE_MEMORY_ENABLED` flipped false → true per the founder
  ruling of 2026-09-20 (example default flipped in 52f9a2699); stack restarted via the wrapper
  (`up > file`, never `| tail`). Owed from PR #70: the ten-step browser walk (plan Task 15 step 4).
- 2026-09-20 pull #4 → `92a65d552` (PR #68 document attachments + agent code sandbox, chat
  appearance pass). No migration. Eight new keys appended to `.env`
  (`CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES`, seven `CLUE_SANDBOX_*`, sandbox ON by default).
  `clue-agent-sandbox:latest` was already on this host (built 2026-09-19; `make sandbox-image`
  re-run fully cached — f8d0b7ebe changed only the README). Lane wrapper gained the runbook's
  sandbox note. Stack restarted via the wrapper; preflight reports the image present.
- 2026-09-21 pull #5 → `ab31814a2` (PR #72 design fleet parallelism: multi-artifact legs, derived
  turns, clarification cards, freeze-bake fill parity). No new env key. Lane DB migrated
  5358a2422cb2 → 5cac3234cfb3 (3 migrations + join). lumen-core changed → helper REBUILT here
  with `cargo build --release -p lumen-api-helper` (the sibling worktree the binary was copied
  from is gone); stack `down`/`up` so the design API's cached `/build-info` stamp matches
  (bb1aaeea610a). Owed from PR #72: the live proofs listed in the four 2026-09-19/20 notes.
- 2026-09-21 after the restart: `opentelemetry…trace_exporter "Failed to export span batch code: 403"`
  in the design and platform API logs. NOT a code or env problem: `CLUE_OTEL_TRACES_ENDPOINT` is
  empty (`tracing.installed exporting=false`), so the only OTLP exporter is the Langfuse SDK's;
  `make langfuse-check` and the REST API answer 200, but a POST to
  `https://us.cloud.langfuse.com/api/public/otel/v1/traces` with the same keys answers 403
  `{"message":"Ingestion suspended: Usage threshold exceeded. Please upgrade your plan."}` (a
  bogus key gets 401). Every lane shares these keys/host, so every lane is dropping traces until
  the Langfuse plan is upgraded or the usage window resets. Founder action; nothing to fix here.
- 2026-09-21 (later): the Langfuse suspension is LIFTED — MCP initialize and OTLP ingest both 200;
  the project-local `langfuse` MCP entry shows Connected. No restart needed; exporters resume.
