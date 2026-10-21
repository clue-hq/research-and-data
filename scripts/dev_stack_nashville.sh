#!/bin/bash
# The nashville lane's stack (branch research/narration-quality: the separate page writer),
# 2026-10-04. Untracked local tooling, adapted from dev_stack_hangzhou.sh.
#
# Same five processes and the same login as scripts/dev_stack.sh (read DEV_STACK.md), but on
# ITS OWN PORTS so it can run beside san-salvador's stack on the runbook ports instead of
# having to stop it first, against THIS checkout's throwaway database taken from .env
# (`clue_nashville` on :55040, a copy of clue_addis-ababa), four fleet workers × three slots, its own agent-workspace root and logs under
# /tmp/nashville_*.log.
#
# The agent code sandbox (2026-09-20): `up`/`restart-workers` refuse until `make sandbox-image`
# has built the image on this host, because the fleet workers below run Head-of-ABM's
# run_python@1 in that container (CLUE_SANDBOX_ENABLED is on by default; see DEV_STACK.md).
#
#   ./scripts/dev_stack_nashville.sh up|down|restart-api|restart-workers|status
#
#   3060  frontend        http://localhost:3060
#   8062  platform API
#   8061  design API
#   8063  platform API twin
#
# The ports here MUST match what .env and apps/frontend/.env.local name (the BFF origin
# guard, Clerk's authorized parties and the design API's CORS list read those files, not
# these knobs) — the check below refuses to start on a mismatch rather than produce the
# runbook's three silent symptoms.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export DEV_STACK_FRONTEND_PORT=3060
export DEV_STACK_PLATFORM_PORT=8062
export DEV_STACK_DESIGN_PORT=8061
export DEV_STACK_PLATFORM2_PORT=8063
# 8040 is held by the addis-ababa worktree's page origin (2026-10-15), so this lane serves pages
# on 8064.
export DEV_STACK_PAGE_ORIGIN_PORT=8064

env_value() {  # $1 file, $2 key → the value, quotes stripped, empty if absent
  grep -E "^$2=" "$1" | head -1 | cut -d= -f2- | tr -d "\"'"
}
expect() {  # $1 file, $2 key, $3 expected
  actual="$(env_value "$ROOT/$1" "$2")"
  if [ "$actual" != "$3" ]; then
    echo "$1: $2 is '$actual', this wrapper expects '$3' — fix the file or the wrapper, never just one" >&2
    exit 2
  fi
}
expect .env CLUE_DESIGN_API_BASE_URL "http://127.0.0.1:${DEV_STACK_DESIGN_PORT}"
expect .env LUMEN_API_ORIGIN "http://127.0.0.1:${DEV_STACK_DESIGN_PORT}"
expect apps/frontend/.env.local CLUE_API_BASE_URL "http://127.0.0.1:${DEV_STACK_PLATFORM_PORT}"
expect apps/frontend/.env.local LUMEN_API_BASE_URL "http://127.0.0.1:${DEV_STACK_DESIGN_PORT}"
expect apps/frontend/.env.local CLUE_APP_ORIGIN "http://localhost:${DEV_STACK_FRONTEND_PORT}"
for key in LUMEN_API_CORS_ORIGINS CLUE_AUTH_CLERK_AUTHORIZED_PARTIES; do
  case ",$(env_value "$ROOT/.env" "$key")," in
    *",http://localhost:${DEV_STACK_FRONTEND_PORT},"*) ;;
    *) echo ".env: $key does not list http://localhost:${DEV_STACK_FRONTEND_PORT}" >&2; exit 2 ;;
  esac
done

DEV_STACK_DB_URL="$(env_value "$ROOT/.env" CLUE_DATABASE_URL)"
[ -n "$DEV_STACK_DB_URL" ] || { echo "CLUE_DATABASE_URL missing from $ROOT/.env" >&2; exit 2; }
export DEV_STACK_DB_URL
export DEV_STACK_WORKERS=4
export DEV_STACK_WORKER_CONCURRENCY=3
export DEV_STACK_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-nashville
export DEV_STACK_LOG_PREFIX=/tmp/nashville

exec "$ROOT/scripts/dev_stack.sh" "$@"
