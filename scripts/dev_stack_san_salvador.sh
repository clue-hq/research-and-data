#!/bin/bash
# The san-salvador lane's stack (branch track-r4: O6 + R1–R4 of ARV2), 2026-09-11.
#
# Same processes, same ports and same login as scripts/dev_stack.sh — read DEV_STACK.md for the
# port map and the symptom table — but against THIS checkout's database (the lane's throwaway
# `clue_san-salvador` on :55040, taken from .env so it can never drift from what the tests use),
# with FOUR fleet worker processes at THREE drain slots each (founder ruling 2026-09-10 for the
# exit-gate walks), the lane's own agent-workspace root, and logs under /tmp/san-salvador_*.log.
#
# The agent code sandbox (2026-09-20): `up`/`restart-workers` refuse until `make sandbox-image`
# has built the image on this host, because the fleet workers below run Head-of-ABM's
# run_python@1 in that container (CLUE_SANDBOX_ENABLED is on by default; see DEV_STACK.md).
#
#   ./scripts/dev_stack_san_salvador.sh up|down|restart-api|restart-workers|status
#
# It cannot share the box with the istanbul stack (same ports): stop one before starting the other.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

DEV_STACK_DB_URL="$(grep -E '^CLUE_DATABASE_URL=' "$ROOT/.env" | cut -d= -f2- | tr -d '"')"
[ -n "$DEV_STACK_DB_URL" ] || { echo "CLUE_DATABASE_URL missing from $ROOT/.env" >&2; exit 2; }
export DEV_STACK_DB_URL
export DEV_STACK_WORKERS=4
export DEV_STACK_WORKER_CONCURRENCY=3
export DEV_STACK_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-san-salvador
export DEV_STACK_LOG_PREFIX=/tmp/san-salvador

exec "$ROOT/scripts/dev_stack.sh" "$@"
