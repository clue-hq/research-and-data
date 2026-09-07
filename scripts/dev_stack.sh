#!/bin/bash
# =============================================================================
# THE dev stack runbook. One command per verb: ./scripts/dev_stack.sh up|down|status
#
# Written 2026-08-29 after a stack rebuild from memory burned an evening on
# three separate port/origin mismatches. This file is the single source of
# truth for how the five processes run — if a port or flag changes, change it
# HERE, never only in a shell command.
#
# THE PORT MAP (do not improvise) — these are the DEFAULTS; a second worktree
# overrides them through the CLUE_DEV_* keys below:
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
#   ----  fleet workers          — drive design runs and agent turns; no port.
#                                  CLUE_DEV_FLEET_WORKERS processes (default 1), each
#                                  supervising CLUE_FLEET_MAX_CONCURRENCY tasks at once.
#
# RUNNING TWO WORKTREES AT ONCE (added 2026-09-03):
#   Every port, the database URL and the log-file names come from env keys with
#   defaults equal to the map above, so an unset environment behaves exactly as
#   this script always did:
#     CLUE_DEV_DB_URL           default postgresql+psycopg://aryankeshri@localhost/clue_istanbul_dev
#     CLUE_DEV_FRONTEND_PORT    default 3020
#     CLUE_DEV_DESIGN_PORT      default 8010
#     CLUE_DEV_PLATFORM_PORT    default 8020
#     CLUE_DEV_PLATFORM_PORT_2  default 8030
#     CLUE_DEV_LOG_SUFFIX       default empty  → /tmp/browser_<name><suffix>.log
#     CLUE_DEV_FLEET_WORKERS    default 1      → how many fleet worker processes `up` starts
#                                                 (2026-09-08; a founder-facing stack runs 4)
#   Precedence: a value exported in your shell wins over the same key in
#   $ROOT/.env, which wins over the default. Each worktree normally sets its own
#   values in its own .env (also its own CLUE_STORAGE_FS_ROOT).
#   `down` only kills the PIDs this worktree's `up` recorded in
#   /tmp/clue_dev_stack<suffix>.pids — it can never take down the other stack.
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

# Captured BEFORE .env is sourced, so an explicit shell export beats the file.
CLI_DB_URL="${CLUE_DEV_DB_URL:-}"
CLI_FRONTEND_PORT="${CLUE_DEV_FRONTEND_PORT:-}"
CLI_DESIGN_PORT="${CLUE_DEV_DESIGN_PORT:-}"
CLI_PLATFORM_PORT="${CLUE_DEV_PLATFORM_PORT:-}"
CLI_PLATFORM_PORT_2="${CLUE_DEV_PLATFORM_PORT_2:-}"
CLI_LOG_SUFFIX="${CLUE_DEV_LOG_SUFFIX:-}"
CLI_FLEET_WORKERS="${CLUE_DEV_FLEET_WORKERS:-}"

load_env() { set -a; source "$ROOT/.env"; set +a; }

# Must run AFTER load_env — the knobs normally live in this worktree's .env.
resolve_config() {
  DB_URL="${CLI_DB_URL:-${CLUE_DEV_DB_URL:-postgresql+psycopg://aryankeshri@localhost/clue_istanbul_dev}}"
  FRONTEND_PORT="${CLI_FRONTEND_PORT:-${CLUE_DEV_FRONTEND_PORT:-3020}}"
  DESIGN_PORT="${CLI_DESIGN_PORT:-${CLUE_DEV_DESIGN_PORT:-8010}}"
  PLATFORM_PORT="${CLI_PLATFORM_PORT:-${CLUE_DEV_PLATFORM_PORT:-8020}}"
  PLATFORM_PORT_2="${CLI_PLATFORM_PORT_2:-${CLUE_DEV_PLATFORM_PORT_2:-8030}}"
  LOG_SUFFIX="${CLI_LOG_SUFFIX:-${CLUE_DEV_LOG_SUFFIX:-}}"
  FLEET_WORKERS="${CLI_FLEET_WORKERS:-${CLUE_DEV_FLEET_WORKERS:-1}}"
  case "$FLEET_WORKERS" in ''|*[!0-9]*|0) echo "CLUE_DEV_FLEET_WORKERS must be a positive integer (got '$FLEET_WORKERS')" >&2; exit 2;; esac

  PIDFILE="/tmp/clue_dev_stack${LOG_SUFFIX}.pids"
  DESIGN_ORIGIN="http://127.0.0.1:${DESIGN_PORT}"
  AGENT_WORKSPACE_ROOT="${CLUE_AGENT_WORKSPACE_ROOT:-/private/tmp/clue-agent-workspaces}"

  PLATFORM_ENV=(
    CLUE_DATABASE_URL="$DB_URL"
    CLUE_DESIGN_RUNTIME_ENABLED=1
    CLUE_DESIGN_API_BASE_URL="$DESIGN_ORIGIN"
    CLUE_AGENT_WORKSPACE_ROOT="$AGENT_WORKSPACE_ROOT"
  )
}

log_path() { echo "/tmp/browser_${1}${LOG_SUFFIX}.log"; }

# One "<name> <pid>" line per process, written by up, consumed by down/status.
record_pid() { echo "$1 $2" >> "$PIDFILE"; }
pid_of() { [ -f "$PIDFILE" ] && awk -v n="$1" '$1==n {print $2}' "$PIDFILE" || true; }

# Kill a recorded pid and everything it spawned (npm run dev → sh → next), and
# nothing else: we only ever walk down from PIDs this worktree started.
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

up() {
  load_env
  resolve_config
  mkdir -p "$AGENT_WORKSPACE_ROOT" && chmod 700 "$AGENT_WORKSPACE_ROOT"
  : > "$PIDFILE"

  (
    cd "$ROOT/subsystems/clue-design"
    env "${PLATFORM_ENV[@]}" \
        LUMEN_EMBEDDED_FLEET_WORKER=1 \
        LUMEN_CORE_HELPER="$ROOT/subsystems/clue-design/target/release/lumen-api-helper" \
        LUMEN_API_ORIGIN="$DESIGN_ORIGIN" \
        LUMEN_API_CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT},http://localhost:3000" \
        PYTHONPATH=.:apps/api:apps/agent_runtime \
        "$ROOT/.venv/bin/python" -m uvicorn lumen_api.main:app --port "$DESIGN_PORT" \
        > "$(log_path design_api)" 2>&1 &
    record_pid design-api "$!"
  )

  (
    cd "$ROOT"
    env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port "$PLATFORM_PORT" \
      > "$(log_path platform_api_8020)" 2>&1 &
    record_pid platform-api "$!"
  )

  (
    cd "$ROOT"
    env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port "$PLATFORM_PORT_2" \
      > "$(log_path platform_api)" 2>&1 &
    record_pid platform-api-2 "$!"
  )

  # N worker PROCESSES (CLUE_DEV_FLEET_WORKERS), each supervising CLUE_FLEET_MAX_CONCURRENCY
  # tasks at once (the in-process slots from 2026-09-07). Worker 1 keeps the historical log
  # name and pid label so an older pidfile/status keeps reading; the rest are numbered.
  for i in $(seq 1 "$FLEET_WORKERS"); do
    (
      cd "$ROOT"
      if [ "$i" -eq 1 ]; then log_name=fleet_worker; pid_name=fleet-worker; else log_name="fleet_worker_${i}"; pid_name="fleet-worker-${i}"; fi
      env "${PLATFORM_ENV[@]}" \
        LUMEN_API_ORIGIN="$DESIGN_ORIGIN" \
        "$ROOT/.venv/bin/python" -m clue_api.fleet_main \
        > "$(log_path "$log_name")" 2>&1 &
      record_pid "$pid_name" "$!"
    )
  done

  # Class fix 2026-08-31: hard-killed/overlapping dev-server starts corrupt the
  # .next route graph (single routes 404 while siblings work — twice live on
  # 2026-08-30/31). A cold route compile costs seconds; a corrupted cache costs
  # a debugging session. Always start the frontend from a clean cache.
  rm -rf "$ROOT/apps/frontend/.next"
  (
    cd "$ROOT/apps/frontend"
    npm run dev -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" \
      > "$(log_path frontend)" 2>&1 &
    record_pid frontend "$!"
  )

  echo "starting…"; sleep 8; status_resolved
  echo
  echo "app:   http://localhost:${FRONTEND_PORT}"
  echo "login: aryan+clerk_test_design@example.com / ClueDev2026!stripe / code 424242"
  echo
  echo "logs:"
  for name in frontend design_api platform_api_8020 platform_api fleet_worker; do
    echo "  $(log_path "$name")"
  done
  for i in $(seq 2 "$FLEET_WORKERS"); do echo "  $(log_path "fleet_worker_${i}")"; done
  echo "  pids: $PIDFILE"
}

down() {
  load_env
  resolve_config
  if [ ! -f "$PIDFILE" ]; then
    echo "no pidfile at $PIDFILE — nothing this worktree started is recorded."
    echo "(refusing to pkill by name: that would kill another worktree's stack)"
    return 0
  fi
  while read -r name pid; do
    [ -n "${pid:-}" ] || continue
    kill_tree "$pid"
    echo "  stopped $name ($pid)"
  done < "$PIDFILE"
  rm -f "$PIDFILE"
  echo "stack stopped"
}

status_resolved() {
  for spec in "$FRONTEND_PORT frontend" "$DESIGN_PORT design-api" "$PLATFORM_PORT platform-api" "$PLATFORM_PORT_2 platform-api-2"; do
    port="${spec%% *}"; name="${spec#* }"
    if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "  $name ($port): UP"
    else
      echo "  $name ($port): DOWN"
    fi
  done
  # Pidfile-scoped, not `pgrep -f clue_api.fleet_main`: that matches every
  # worktree's worker and would report this stack UP because another one is.
  up_count=0
  for i in $(seq 1 "$FLEET_WORKERS"); do
    if [ "$i" -eq 1 ]; then pid_name=fleet-worker; else pid_name="fleet-worker-${i}"; fi
    fleet_pid="$(pid_of "$pid_name")"
    if [ -n "$fleet_pid" ] && kill -0 "$fleet_pid" 2>/dev/null \
       && ps -p "$fleet_pid" -o command= 2>/dev/null | grep -q "clue_api.fleet_main"; then
      up_count=$((up_count + 1))
    fi
  done
  if [ "$up_count" -eq "$FLEET_WORKERS" ]; then
    echo "  fleet-workers: UP (${up_count}/${FLEET_WORKERS} processes × CLUE_FLEET_MAX_CONCURRENCY=${CLUE_FLEET_MAX_CONCURRENCY:-4} slots)"
  else
    echo "  fleet-workers: DOWN (${up_count}/${FLEET_WORKERS} processes up)"
  fi
}

status() { load_env; resolve_config; status_resolved; }

case "${1:-status}" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 up|down|status"; exit 2 ;;
esac
