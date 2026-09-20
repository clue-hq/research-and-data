#!/bin/bash
# The hangzhou lane's stack (branch research-streaming-v3: the composer `@` file-tagging
# feature, cut from research-streaming), 2026-09-17.
#
# Same five processes and the same login as scripts/dev_stack.sh (read DEV_STACK.md), but on
# ITS OWN PORTS so it can run beside san-salvador's stack on the runbook ports instead of
# having to stop it first, against THIS checkout's throwaway database taken from .env
# (`clue_hangzhou` on :55040), one fleet worker, its own agent-workspace root and logs under
# /tmp/hangzhou_*.log.
#
# The agent code sandbox (2026-09-20): `up`/`restart-workers` refuse until `make sandbox-image`
# has built the image on this host, because the fleet workers below run Head-of-ABM's
# run_python@1 in that container (CLUE_SANDBOX_ENABLED is on by default; see DEV_STACK.md).
#
#   ./scripts/dev_stack_hangzhou.sh up|down|restart-api|restart-workers|status
#
#   3050  frontend        http://localhost:3050
#   8090  platform API
#   8091  design API
#   8092  platform API twin
#
# The ports here MUST match what .env and apps/frontend/.env.local name (the BFF origin
# guard, Clerk's authorized parties and the design API's CORS list read those files, not
# these knobs) — the check below refuses to start on a mismatch rather than produce the
# runbook's three silent symptoms.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export DEV_STACK_FRONTEND_PORT=3050
export DEV_STACK_PLATFORM_PORT=8090
export DEV_STACK_DESIGN_PORT=8091
export DEV_STACK_PLATFORM2_PORT=8092

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
export DEV_STACK_WORKERS=1
export DEV_STACK_WORKER_CONCURRENCY=1
export DEV_STACK_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-hangzhou
export DEV_STACK_LOG_PREFIX=/tmp/hangzhou

exec "$ROOT/scripts/dev_stack.sh" "$@"
