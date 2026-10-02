#!/bin/bash
# The jerusalem-v1 lane's stack (branch design/account-binding-v1), 2026-09-18.
#
# Same five processes and the same login as scripts/dev_stack.sh (read DEV_STACK.md), but on
# ITS OWN PORTS so it can run beside another lane's stack on the runbook ports, against THIS
# checkout's database. Unlike the hangzhou wrapper, every knob lives in .env (the DEV_STACK_*
# block) and this script only exports it — one source of truth, nothing to keep in sync here.
#
#   ./scripts/dev_stack_jerusalem.sh up|down|restart-api|restart-workers|status
#
#   3028  frontend        http://localhost:3028
#   8028  platform API
#   8018  design API
#   8038  platform API twin
#
# The ports MUST also match what .env and apps/frontend/.env.local name for the BFF origin
# guard, Clerk's authorized parties and the design API's CORS list (those read the files, not
# the knobs) — the checks below refuse to start on a mismatch rather than produce the runbook's
# three silent symptoms.
# The agent code sandbox (2026-09-20): `up`/`restart-workers` refuse until `make sandbox-image`
# has built the image on this host, because the fleet workers below run Head-of-ABM's
# run_python@1 in that container (CLUE_SANDBOX_ENABLED is on by default; see DEV_STACK.md).
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

env_value() {  # $1 file, $2 key → the value, quotes stripped, empty if absent
  grep -E "^$2=" "$1" | head -1 | cut -d= -f2- | tr -d "\"'"
}
require() {  # $1 key → export it from .env, refuse if absent
  value="$(env_value "$ROOT/.env" "$1")"
  [ -n "$value" ] || { echo ".env: $1 is missing or empty" >&2; exit 2; }
  export "$1=$value"
}
expect() {  # $1 file, $2 key, $3 expected
  actual="$(env_value "$ROOT/$1" "$2")"
  if [ "$actual" != "$3" ]; then
    echo "$1: $2 is '$actual', .env's DEV_STACK_* block expects '$3' — fix one file or the other, never just one side" >&2
    exit 2
  fi
}

for key in DEV_STACK_FRONTEND_PORT DEV_STACK_PLATFORM_PORT DEV_STACK_DESIGN_PORT DEV_STACK_PLATFORM2_PORT \
           DEV_STACK_DB_URL DEV_STACK_WORKERS DEV_STACK_WORKER_CONCURRENCY \
           DEV_STACK_AGENT_WORKSPACE_ROOT DEV_STACK_LOG_PREFIX; do
  require "$key"
done

expect .env CLUE_DATABASE_URL "$DEV_STACK_DB_URL"
expect .env CLUE_DESIGN_API_BASE_URL "http://127.0.0.1:${DEV_STACK_DESIGN_PORT}"
expect .env LUMEN_API_ORIGIN "http://127.0.0.1:${DEV_STACK_DESIGN_PORT}"
expect .env CLUE_APP_ORIGIN "http://localhost:${DEV_STACK_FRONTEND_PORT}"
expect apps/frontend/.env.local CLUE_API_BASE_URL "http://127.0.0.1:${DEV_STACK_PLATFORM_PORT}"
expect apps/frontend/.env.local LUMEN_API_BASE_URL "http://127.0.0.1:${DEV_STACK_DESIGN_PORT}"
expect apps/frontend/.env.local CLUE_APP_ORIGIN "http://localhost:${DEV_STACK_FRONTEND_PORT}"
for key in LUMEN_API_CORS_ORIGINS CLUE_AUTH_CLERK_AUTHORIZED_PARTIES; do
  case ",$(env_value "$ROOT/.env" "$key")," in
    *",http://localhost:${DEV_STACK_FRONTEND_PORT},"*) ;;
    *) echo ".env: $key does not list http://localhost:${DEV_STACK_FRONTEND_PORT}" >&2; exit 2 ;;
  esac
done

exec "$ROOT/scripts/dev_stack.sh" "$@"
