#!/bin/bash
# The melbourne lane's stack (branch artifacts-page): same processes, ports and login as
# scripts/dev_stack.sh (read DEV_STACK.md), against THIS checkout's throwaway database taken
# from .env, one fleet worker, its own agent-workspace root and logs under /tmp/melbourne_*.log.
#
# The agent code sandbox (2026-09-20): `up`/`restart-workers` refuse until `make sandbox-image`
# has built the image on this host, because the fleet workers below run Head-of-ABM's
# run_python@1 in that container (CLUE_SANDBOX_ENABLED is on by default; see DEV_STACK.md).
#
#   ./scripts/dev_stack_melbourne.sh up|down|restart-api|restart-workers|status
#
# It cannot share the box with another lane's stack on the same ports: stop one first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

DEV_STACK_DB_URL="$(grep -E '^CLUE_DATABASE_URL=' "$ROOT/.env" | cut -d= -f2- | tr -d '"')"
[ -n "$DEV_STACK_DB_URL" ] || { echo "CLUE_DATABASE_URL missing from $ROOT/.env" >&2; exit 2; }
export DEV_STACK_DB_URL
export DEV_STACK_WORKERS=1
export DEV_STACK_WORKER_CONCURRENCY=1
export DEV_STACK_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-melbourne
export DEV_STACK_LOG_PREFIX=/tmp/melbourne

exec "$ROOT/scripts/dev_stack.sh" "$@"
