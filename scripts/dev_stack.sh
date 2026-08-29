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
#   ----  fleet worker           — drives design runs; no port.
#
# DEV LOGIN (Clerk dev instance, test mode):
#   email     aryan+clerk_test_design@example.com
#   password  ClueDev2026!stripe        (reset via Clerk API 2026-08-29)
#   code      424242                    (fixed code for +clerk_test emails)
#
# Env comes from repo-root .env (CLUE_STORAGE_FS_ROOT is pinned ABSOLUTE there —
# never remove it; a process without it silently writes blobs to
# /private/tmp/lumen-dev-storage and the stack splits). Logs land in /tmp/browser_*.log.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_URL="postgresql+psycopg://aryankeshri@localhost/clue_istanbul_dev"
PLATFORM_ENV=(
  CLUE_DATABASE_URL="$DB_URL"
  CLUE_DESIGN_RUNTIME_ENABLED=1
  CLUE_DESIGN_API_BASE_URL=http://127.0.0.1:8010
  CLUE_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces
)

load_env() { set -a; source "$ROOT/.env"; set +a; }

up() {
  load_env
  mkdir -p /private/tmp/clue-agent-workspaces && chmod 700 /private/tmp/clue-agent-workspaces

  ( cd "$ROOT/subsystems/clue-design" && \
    env "${PLATFORM_ENV[@]}" \
        LUMEN_EMBEDDED_FLEET_WORKER=1 \
        LUMEN_CORE_HELPER="$ROOT/subsystems/clue-design/target/release/lumen-api-helper" \
        LUMEN_API_CORS_ORIGINS="http://localhost:3020,http://127.0.0.1:3020,http://localhost:3000" \
        PYTHONPATH=.:apps/api:apps/agent_runtime \
        "$ROOT/.venv/bin/python" -m uvicorn lumen_api.main:app --port 8010 \
        > /tmp/browser_design_api.log 2>&1 & )

  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port 8020 \
      > /tmp/browser_platform_api_8020.log 2>&1 & )

  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port 8030 \
      > /tmp/browser_platform_api.log 2>&1 & )

  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m clue_api.fleet_main \
      > /tmp/browser_fleet_worker.log 2>&1 & )

  ( cd "$ROOT/apps/frontend" && npm run dev -- --port 3020 \
      > /tmp/browser_frontend.log 2>&1 & )

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
  if pgrep -f "clue_api.fleet_main" >/dev/null 2>&1; then
    echo "  fleet-worker: UP"
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
