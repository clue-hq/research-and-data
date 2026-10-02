# Semarang local stack — 2026-09-12

## Authorization and resource ownership

- Founder requested a running stack for testing the Brand Context frontend changes, isolated
  from San Salvador. Subsequently approved sharing the existing Postgres container provided
  every process uses **clue_semarang** only. No database copy or migration was performed.
- Founder explicitly approved `/private/tmp/clue-agent-workspaces-semarang` for platform-agent
  scratch after the runtime rejected an in-checkout root. `WorkspaceRootPolicy` requires this
  root to be unrelated to both the source worktree and service home. The guard is unchanged.
- Database: `clue_semarang` on localhost:55040, existing `clue-pg-istanbul` container.
  Schema is already the branch's single head `2cd622be2da0`.
- Dedicated Redis: `clue-redis-semarang`, Redis 7, localhost:56379 database 0, bound only to
  127.0.0.1. Persistent data is bind-mounted from this checkout's `.runtime/redis`.
- Frontend http://localhost:3040; platform API 127.0.0.1:8070; design API 127.0.0.1:8071.
  Four detached fleet workers, three slots each. Design API embedded worker is disabled.
- Artifact storage `.artifacts`, ARV2 raw `.artifacts/arv2`, design scratch/traces and logs
  `.runtime/…`, engine cache under this checkout's design subtree, all rooted in Semarang.
  Native helper built in `subsystems/clue-design/target/release/lumen-api-helper`.
  Font-library manifest is explicitly absolute so root-cwd workers and design-cwd API agree.
- Auth remains enabled. Clerk origins and frontend/design CORS are scoped to :3040.
  No sibling processes or databases were changed. No provider research/extraction was launched.

## Start, inspect, stop

From the Semarang root:

```sh
.venv/bin/python scripts/dev_stack_semarang.py up
.venv/bin/python scripts/dev_stack_semarang.py status
.venv/bin/python scripts/dev_stack_semarang.py down
```

- `up` validates the database name, Redis endpoint, and local paths; starts/reuses Semarang's
  own Redis; refuses an occupied application port owned by an untracked process.
- Process records are `.runtime/processes.json`; logs are `.runtime/logs/*.log`.
- Process ownership checks combine PID, creation time and working directory. `down` signals
  only recorded owned process groups. It leaves Redis and shared Postgres running.
- Worker launches remain staggered because the existing registry seeding race is unresolved.
- Do **not** use `dev_stack.sh` or `dev_stack_san_salvador.sh` for this checkout: those launch
  other ports and stop processes with broad global `pkill` patterns.
- Runtime directory and local env files are ignored. Secrets are not committed. Updated env
  examples document new settings and match the effective non-machine-specific values.

## Verification and observations

- Semarang database identity and schema verified directly. Existing data: 125 Knowledge
  documents, no design brand kits or design assets. Typography/assets need a brand kit before
  they can be tested against live extracted data; do not seed or copy sibling tenant data.
- Both APIs served OpenAPI; all four workers reached `worker.start` with concurrency 3.
- Inspected live process environments without printing secrets: every database URL resolved
  to localhost:55040/clue_semarang; own Redis, artifact root, scratch and helper paths.
  No San Salvador reference in live environments or root/frontend local env files.
- Imported platform modules and py_lumen_config resolve inside this checkout.
- Authenticated browser verification used the existing test account and existing workspace;
  login, fixed test verification, workspace selection and Brand Context route succeeded.
- Native helper release build succeeded. Initial sandbox build failed on dependency DNS;
  retry with approved network access succeeded. Build log: `.runtime/logs/helper-build.log`.
- Initial worker startup failed because in-checkout platform scratch violates the runtime
  policy; fixed with founder-approved external Semarang-only path. Failed attempts remain
  in appended worker logs; use the latest startup timestamp when assessing health.
- Launcher Python compilation, Ruff formatting/lint and git whitespace checks passed.

## Closing state

- Stack left running: platform API PID 62008, design API 62057, frontend 62083, workers
  62088 / 62233 / 62373 / 62566. Consult `.runtime/processes.json` for current IDs after restart.
- Final process-environment audit included the absolute font manifest; all seven passed.
  The four inspected pre-existing San Salvador process IDs remained running.
- Browser opened the real Company overview Knowledge document: rendered headings, bold list
  labels and clickable website link; HTTP 200, no framework error overlay, no browser errors.
  Screenshot `.runtime/brand-context-live.png`. Browser verification session closed afterwards;
  application services remain running for the founder.
