#!/bin/bash
# =============================================================================
# THE dev stack runbook. One command per verb: ./scripts/dev_stack.sh up|down|status
#
# Written 2026-08-29 after a stack rebuild from memory burned an evening on
# three separate port/origin mismatches. This file is the single source of
# truth for how the five processes run — if a port or flag changes, change it
# HERE, never only in a shell command.
#
# THE PORT MAP (do not improvise):
#   3020  frontend (Next.js)     — THE app port. CLUE_APP_ORIGIN in
#                                  apps/frontend/.env.local names it, the BFF
#                                  403s writes from any other origin, and
#                                  Clerk's authorized parties allowlist
#                                  (.env CLUE_AUTH_CLERK_AUTHORIZED_PARTIES)
#                                  must contain it. Browse to
#                                  http://localhost:3020 — nothing else.
#   8010  design API (lumen)     — embedded fleet worker + engine helper.
#   8020  platform API           — auth/session + the whole /api/v1 surface
#                                  the frontend proxies to (CLUE_API_BASE_URL).
#   8030  platform API (2nd)     — historical twin of 8020; kept because some
#                                  session flows were exercised against it.
#   ----  fleet worker(s)        — drive design runs and every fleet job kind;
#                                  no port.
#
# DEV LOGIN (Clerk dev instance, test mode):
#   email     aryan+clerk_test_design@example.com
#   password  ClueDev2026!stripe        (reset via Clerk API 2026-08-29)
#   code      424242                    (fixed code for +clerk_test emails)
#
# Env comes from repo-root .env (CLUE_STORAGE_FS_ROOT is pinned ABSOLUTE there —
# never remove it; a process without it silently writes blobs to
# /private/tmp/lumen-dev-storage and the stack splits). Logs land in /tmp/browser_*.log.
#
# LANE KNOBS (added 2026-09-11 so a second worktree can run the SAME stack on
# the SAME ports against ITS OWN database, without a copy of this file). Every
# default below is exactly what this script did before the knobs existed, so
# the istanbul checkout is unchanged. A lane sets them in a tiny wrapper script
# next to this one (see scripts/dev_stack_san_salvador.sh) — never in a shell
# export, which evaporates at the next rebuild.
#   DEV_STACK_DB_URL                 the database every process uses
#   DEV_STACK_WORKERS                how many fleet worker PROCESSES to start
#   DEV_STACK_WORKER_CONCURRENCY     drain slots per worker process
#                                    (CLUE_FLEET_WORKER_CONCURRENCY, O6 task 9d)
#   DEV_STACK_AGENT_WORKSPACE_ROOT   CLUE_AGENT_WORKSPACE_ROOT for the lane
#   DEV_STACK_LOG_PREFIX             log file prefix (default /tmp/browser)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_URL="${DEV_STACK_DB_URL:-postgresql+psycopg://aryankeshri@localhost/clue_istanbul_dev}"
WORKERS="${DEV_STACK_WORKERS:-1}"
WORKER_CONCURRENCY="${DEV_STACK_WORKER_CONCURRENCY:-1}"
AGENT_WORKSPACE_ROOT="${DEV_STACK_AGENT_WORKSPACE_ROOT:-/private/tmp/clue-agent-workspaces}"
LOG="${DEV_STACK_LOG_PREFIX:-/tmp/browser}"
PLATFORM_ENV=(
  CLUE_DATABASE_URL="$DB_URL"
  CLUE_DESIGN_RUNTIME_ENABLED=1
  CLUE_DESIGN_API_BASE_URL=http://127.0.0.1:8010
  CLUE_AGENT_WORKSPACE_ROOT="$AGENT_WORKSPACE_ROOT"
)

load_env() { set -a; source "$ROOT/.env"; set +a; }

worker_log() {  # worker 1 keeps the historical name; 2..N get a suffix
  if [ "$1" -eq 1 ]; then echo "${LOG}_fleet_worker.log"; else echo "${LOG}_fleet_worker_$1.log"; fi
}

up() {
  load_env
  mkdir -p "$AGENT_WORKSPACE_ROOT" && chmod 700 "$AGENT_WORKSPACE_ROOT"

  ( cd "$ROOT/subsystems/clue-design" && \
    env "${PLATFORM_ENV[@]}" \
        LUMEN_EMBEDDED_FLEET_WORKER=1 \
        LUMEN_CORE_HELPER="$ROOT/subsystems/clue-design/target/release/lumen-api-helper" \
        LUMEN_API_CORS_ORIGINS="http://localhost:3020,http://127.0.0.1:3020,http://localhost:3000" \
        PYTHONPATH=.:apps/api:apps/agent_runtime \
        "$ROOT/.venv/bin/python" -m uvicorn lumen_api.main:app --port 8010 \
        > "${LOG}_design_api.log" 2>&1 & )

  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port 8020 \
      > "${LOG}_platform_api_8020.log" 2>&1 & )

  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port 8030 \
      > "${LOG}_platform_api.log" 2>&1 & )

  # Workers start one at a time, a few seconds apart: every worker seeds the
  # field registry at boot with plain INSERTs, and two booting together race
  # to `field_definition_pkey` — three of four died that way on 2026-09-11.
  # The stagger is a runbook mitigation; the seed itself is not concurrency-safe.
  for i in $(seq 1 "$WORKERS"); do
    [ "$i" -gt 1 ] && sleep 6
    ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
        CLUE_FLEET_WORKER_CONCURRENCY="$WORKER_CONCURRENCY" PYTHONUNBUFFERED=1 \
        "$ROOT/.venv/bin/python" -m clue_api.fleet_main \
        > "$(worker_log "$i")" 2>&1 & )
  done

  # Class fix 2026-08-31: hard-killed/overlapping dev-server starts corrupt the
  # .next route graph (single routes 404 while siblings work — twice live on
  # 2026-08-30/31). A cold route compile costs seconds; a corrupted cache costs
  # a debugging session. Always start the frontend from a clean cache.
  rm -rf "$ROOT/apps/frontend/.next"
  ( cd "$ROOT/apps/frontend" && npm run dev -- --port 3020 \
      > "${LOG}_frontend.log" 2>&1 & )

  echo "starting…"; sleep 8; status
  echo
  echo "app:   http://localhost:3020"
  echo "login: aryan+clerk_test_design@example.com / ClueDev2026!stripe / code 424242"
}

down() {
  pkill -f "uvicorn lumen_api.main:app" 2>/dev/null || true
  pkill -f "uvicorn clue_api.projections_main:app" 2>/dev/null || true
  pkill -f "clue_api.fleet_main" 2>/dev/null || true
  pkill -f "next dev.*3020" 2>/dev/null || true
  echo "stack stopped"
}

status() {
  for spec in "3020 frontend" "8010 design-api" "8020 platform-api" "8030 platform-api-2"; do
    port="${spec%% *}"; name="${spec#* }"
    if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "  $name ($port): UP"
    else
      echo "  $name ($port): DOWN"
    fi
  done
  running="$(pgrep -f "clue_api.fleet_main" | wc -l | tr -d ' ')"   # macOS pgrep has no -c
  if [ "${running:-0}" -gt 0 ]; then
    echo "  fleet-worker: UP ($running process(es), $WORKER_CONCURRENCY slot(s) each)"
  else
    echo "  fleet-worker: DOWN"
  fi
}

case "${1:-status}" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 up|down|status"; exit 2 ;;
esac
