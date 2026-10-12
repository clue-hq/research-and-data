#!/bin/bash
# =============================================================================
# THE dev stack runbook. Commands: up|down|restart-api|restart-workers|restart-ingestion|restart-editor|status
#
# Written 2026-08-29 after a stack rebuild from memory burned an evening on
# three separate port/origin mismatches. This file is the single source of
# truth for how the stack runs — if a port or flag changes, change it
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
#   8040  page origin (clue_page_origin)
#                                — the PUBLIC page origin. Serves published web
#                                  pages by hostname at
#                                  http://<label>.pages.localhost:8040/<slug>
#                                  (browsers resolve *.localhost to loopback).
#   3120  site editor (apps/frontend/packages/site-editor)
#                                — the Puck site editor on its own domain,
#                                  http://<label>.editor.localhost:3120, one
#                                  label per workspace. The app frames it; it
#                                  holds no login (Wave 2 D2 / Contract 9).
#   ----  primary fleet workers — chat, design turns and research; no port.
#   ----  ingestion controller  — starts one coordinator and 4 x 10 image slots
#                                  on demand; execution children stop when idle.
#                                  See docs/runbooks/ingestion-pool.md.
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
#   DEV_STACK_BUILD_SANDBOX_IMAGE    1 = let `up` build the agent code-sandbox image when it is
#                                    missing (default 0: refuse and name `make sandbox-image`)
# PORT KNOBS (added 2026-09-17 so a lane can run beside another lane's stack
# instead of having to `down` it first — the hangzhou lane was the first to
# need it, see scripts/dev_stack_hangzhou.sh). Defaults are THE PORT MAP above,
# so every existing wrapper and the istanbul checkout are unchanged. A lane that
# overrides them must ALSO name the same ports in its .env
# (CLUE_DESIGN_API_BASE_URL, LUMEN_API_ORIGIN, the frontend origin in
# LUMEN_API_CORS_ORIGINS and CLUE_AUTH_CLERK_AUTHORIZED_PARTIES) and in its
# apps/frontend/.env.local (CLUE_API_BASE_URL, LUMEN_API_BASE_URL,
# CLUE_APP_ORIGIN) — the three guards in the port map do not read these knobs.
#   DEV_STACK_FRONTEND_PORT          Next.js app port            (default 3020)
#   DEV_STACK_DESIGN_PORT            design API (lumen) port     (default 8010)
#   DEV_STACK_PLATFORM_PORT          platform API port           (default 8020)
#   DEV_STACK_PLATFORM2_PORT         platform API twin's port    (default 8030)
#   DEV_STACK_EDITOR_PORT            site editor port             (default 3120)
#
# THE AGENT CODE SANDBOX (added 2026-09-20; spec docs/superpowers/specs/2026-09-19-agent-code-
# execution-and-document-attachments-design.md). Head-of-ABM's `run_python@1` runs the agent's
# Python in a Docker container from CLUE_SANDBOX_IMAGE (.env; default clue-agent-sandbox:latest),
# and the flag CLUE_SANDBOX_ENABLED is ON by default (founder, 2026-09-20). The FLEET WORKERS are
# the processes that start containers, so a worker host without Docker or without the image
# makes every run refuse `sandbox_unavailable` and every PDF / DOCX / PPTX / XLSX attachment
# unreadable to the agent. `up` and `restart-workers` therefore check Docker and the image
# BEFORE starting workers and refuse on a miss — build once per host with `make sandbox-image`
# (~600 MB, ~2 min), or set DEV_STACK_BUILD_SANDBOX_IMAGE=1 to let `up` build it. Setting
# CLUE_SANDBOX_ENABLED=false in .env skips the check (and turns the tool off). `status` reports it.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_URL="${DEV_STACK_DB_URL:-postgresql+psycopg://aryankeshri@localhost/clue_istanbul_dev}"
WORKERS="${DEV_STACK_WORKERS:-1}"
WORKER_CONCURRENCY="${DEV_STACK_WORKER_CONCURRENCY:-1}"
# The lane wrapper's knob wins; otherwise honour a CLUE_AGENT_WORKSPACE_ROOT already in the
# shell (the co-founder's local setup exports it), and only then the historical default.
AGENT_WORKSPACE_ROOT="${DEV_STACK_AGENT_WORKSPACE_ROOT:-${CLUE_AGENT_WORKSPACE_ROOT:-/private/tmp/clue-agent-workspaces}}"
LOG="${DEV_STACK_LOG_PREFIX:-/tmp/browser}"
FRONTEND_PORT="${DEV_STACK_FRONTEND_PORT:-3020}"
DESIGN_PORT="${DEV_STACK_DESIGN_PORT:-8010}"
PLATFORM_PORT="${DEV_STACK_PLATFORM_PORT:-8020}"
PLATFORM2_PORT="${DEV_STACK_PLATFORM2_PORT:-8030}"
EDITOR_PORT="${DEV_STACK_EDITOR_PORT:-3120}"
PLATFORM_ENV=(
  CLUE_DATABASE_URL="$DB_URL"
  CLUE_DESIGN_RUNTIME_ENABLED=1
  CLUE_DESIGN_API_BASE_URL="http://127.0.0.1:${DESIGN_PORT}"
  CLUE_AGENT_WORKSPACE_ROOT="$AGENT_WORKSPACE_ROOT"
  # Custom-domain publishing S1 — the dev posture for the page origin. The suffix is
  # `pages.localhost` (no DNS setup: browsers resolve *.localhost to loopback) and the origin
  # trusts the Host header instead of an edge secret, because there is no Cloudflare Worker in
  # front of it locally. The repo `.env` keeps the PRODUCTION defaults; these override per process.
  CLUE_PAGES_SYSTEM_SUFFIX=pages.localhost
  CLUE_PAGES_PUBLIC_SCHEME=http
  CLUE_PAGES_PUBLIC_PORT=8040
  CLUE_PAGES_TRUST_HOST_HEADER=true
  CLUE_PAGES_EDGE_SECRET=
)

load_env() { set -a; source "$ROOT/.env"; set +a; }

# The code sandbox's preconditions, checked where the workers are (re)started. Reads the .env
# already loaded by the caller. Exits 2 with the fix named rather than starting workers that
# would refuse every run_python call.
sandbox_preflight() {
  if [ "${CLUE_SANDBOX_ENABLED:-true}" != "true" ]; then
    echo "  sandbox: disabled (CLUE_SANDBOX_ENABLED=${CLUE_SANDBOX_ENABLED}) — binary attachments are unreadable to the agent"
    return 0
  fi
  local image="${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest}"
  if ! command -v docker >/dev/null 2>&1; then
    echo "sandbox: CLUE_SANDBOX_ENABLED=true but docker is not installed on this host — install Docker Desktop, or set CLUE_SANDBOX_ENABLED=false in .env" >&2
    exit 2
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "sandbox: CLUE_SANDBOX_ENABLED=true but the Docker daemon is not reachable — start Docker Desktop, or set CLUE_SANDBOX_ENABLED=false in .env" >&2
    exit 2
  fi
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    if [ "${DEV_STACK_BUILD_SANDBOX_IMAGE:-0}" = "1" ]; then
      echo "sandbox: image $image missing — building it (DEV_STACK_BUILD_SANDBOX_IMAGE=1)…"
      ( cd "$ROOT" && CLUE_SANDBOX_IMAGE="$image" make sandbox-image ) || exit 2
    else
      echo "sandbox: CLUE_SANDBOX_ENABLED=true but the image $image is not built on this host — run 'make sandbox-image' once (~600 MB, ~2 min), or DEV_STACK_BUILD_SANDBOX_IMAGE=1 $0 up, or set CLUE_SANDBOX_ENABLED=false in .env" >&2
      exit 2
    fi
  fi
  echo "  sandbox: enabled, image $image present"
}

worker_log() {  # worker 1 keeps the historical name; 2..N get a suffix
  if [ "$1" -eq 1 ]; then echo "${LOG}_fleet_worker.log"; else echo "${LOG}_fleet_worker_$1.log"; fi
}

start_platform_api() {  # both twins; a settings change (.env) needs both restarted
  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port "$PLATFORM_PORT" \
      > "${LOG}_platform_api_${PLATFORM_PORT}.log" 2>&1 & )

  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn clue_api.projections_main:app --port "$PLATFORM2_PORT" \
      > "${LOG}_platform_api.log" 2>&1 & )
}

start_page_origin() {  # public page origin — serves http://<label>.pages.localhost:8040/<slug>
  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn --factory clue_page_origin.main:build_application --port 8040 \
      > "${LOG}_page_origin.log" 2>&1 & )
}

# The site editor on its own domain (Wave 2 Contract 9): http://<label>.editor.localhost:$EDITOR_PORT.
# Its settings are passed per process, like the page origin's: .env keeps the production suffix.
# The command line names this checkout's absolute script path so pkill never touches a sibling lane.
start_site_editor() {
  ( cd "$ROOT/apps/frontend/packages/site-editor" && env \
      PORT="$EDITOR_PORT" HOST=127.0.0.1 \
      CLUE_APP_ORIGIN="http://localhost:${FRONTEND_PORT}" \
      LUMEN_API_BASE_URL="http://127.0.0.1:${DESIGN_PORT}" \
      CLUE_SITE_EDITOR_SUFFIX="editor.localhost:${EDITOR_PORT}" \
      "$ROOT/apps/frontend/node_modules/.bin/tsx" "$ROOT/apps/frontend/packages/site-editor/scripts/dev.ts" \
      > "${LOG}_site_editor.log" 2>&1 & )
}

stop_site_editor() {
  pkill -f "$ROOT/apps/frontend/packages/site-editor/scripts/dev.ts" 2>/dev/null || true
}

# Restart ONLY the site editor (a change to its server code; client changes rebuild by themselves).
restart_editor() {
  load_env
  stop_site_editor
  for _ in $(seq 1 20); do
    lsof -iTCP:"$EDITOR_PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
  done
  start_site_editor
  echo "restarting site editor…"; sleep 6; status
}

# Restart ONLY the two platform API processes — the way to pick up a changed
# .env setting (e.g. CLUE_VERIFICATION_ENABLED, 2026-09-11) without touching the
# frontend, the design API or the fleet workers. Workers keep their old settings
# until `down`/`up`.
restart_api() {
  load_env
  pkill -f "$ROOT/.venv/bin/python -m uvicorn clue_api.projections_main:app" 2>/dev/null || true
  pkill -f "$ROOT/.venv/bin/python -m uvicorn --factory clue_page_origin.main:build_application" 2>/dev/null || true
  for _ in $(seq 1 20); do
    lsof -iTCP:"$PLATFORM_PORT" -sTCP:LISTEN >/dev/null 2>&1 || lsof -iTCP:"$PLATFORM2_PORT" -sTCP:LISTEN >/dev/null 2>&1 || lsof -iTCP:8040 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
  done
  start_platform_api
  start_page_origin
  echo "restarting platform API…"; sleep 6; status
}

start_workers() {  # $WORKERS processes × $WORKER_CONCURRENCY slots, launched together
  for i in $(seq 1 "$WORKERS"); do
    ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
        CLUE_FLEET_WORKER_CONCURRENCY="$WORKER_CONCURRENCY" PYTHONUNBUFFERED=1 \
        "$ROOT/.venv/bin/python" -m clue_api.fleet_main \
        > "$(worker_log "$i")" 2>&1 & )
  done
}

# Idle controller; capture and annotation run only in its on-demand children.
start_ingestion_pool() {
  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" PYTHONUNBUFFERED=1 \
      "$ROOT/.venv/bin/python" -m lumen_api.ingestion_pool \
      > "${LOG}_ingestion_pool.log" 2>&1 & )
}

stop_ingestion_pool() {
  pkill -f "$ROOT/.venv/bin/python -m lumen_api.ingestion_pool" 2>/dev/null || true
}

restart_ingestion_pool() {
  load_env
  stop_ingestion_pool
  for _ in $(seq 1 70); do
    pgrep -f "$ROOT/.venv/bin/python -m lumen_api.ingestion_pool" >/dev/null || break
    sleep 0.5
  done
  if pgrep -f "$ROOT/.venv/bin/python -m lumen_api.ingestion_pool" >/dev/null; then
    echo 'Ingestion pool is still draining; wait before restarting it.' >&2
    return 2
  fi
  start_ingestion_pool
}

# Restart ONLY the fleet workers, respawned with the SAME count and per-worker
# concurrency the lane wrapper sets. Check nothing is mid-job first: a killed
# worker's job is orphaned until its lease expires.
#
# Every pkill/pgrep pattern in this file is anchored on THIS workspace's
# interpreter ("$ROOT/.venv/bin/python -m …"): sibling worktrees (semarang,
# istanbul, …) run the same module names on the same box against their own
# databases, and a bare "clue_api.fleet_main" match killed theirs (2026-09-12).
restart_workers() {
  load_env
  sandbox_preflight
  pkill -f "$ROOT/.venv/bin/python -m clue_api.fleet_main" 2>/dev/null || true
  for _ in $(seq 1 20); do
    [ "$(pgrep -f "$ROOT/.venv/bin/python -m clue_api.fleet_main" | wc -l | tr -d ' ')" -eq 0 ] && break
    sleep 0.5
  done
  start_workers
  echo "restarting fleet workers…"; sleep 8; status
}

up() {
  load_env
  sandbox_preflight
  mkdir -p "$AGENT_WORKSPACE_ROOT" && chmod 700 "$AGENT_WORKSPACE_ROOT"

  ( cd "$ROOT/subsystems/clue-design" && \
    env "${PLATFORM_ENV[@]}" \
        LUMEN_EMBEDDED_FLEET_WORKER=1 \
        LUMEN_CORE_HELPER="${LUMEN_CORE_HELPER:-$ROOT/subsystems/clue-design/target/release/lumen-api-helper}" \
        LUMEN_API_CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT},http://localhost:3000" \
        PYTHONPATH=.:apps/api:apps/agent_runtime \
        "$ROOT/.venv/bin/python" -m uvicorn lumen_api.main:app --port "$DESIGN_PORT" \
        > "${LOG}_design_api.log" 2>&1 & )

  start_platform_api
  start_page_origin

  # Workers may boot together: since 2026-09-12 the registry seed takes a
  # transaction-scoped advisory lock (ledger A2), so concurrent boots queue on
  # it instead of racing to `field_definition_pkey`.
  start_workers

  start_ingestion_pool

  # Class fix 2026-08-31: hard-killed/overlapping dev-server starts corrupt the
  # .next route graph (single routes 404 while siblings work — twice live on
  # 2026-08-30/31). A cold route compile costs seconds; a corrupted cache costs
  # a debugging session. Always start the frontend from a clean cache.
  rm -rf "$ROOT/apps/frontend/.next"
  # --hostname 127.0.0.1: bind IPv4 loopback explicitly so a browser (and the BFF's
  # loopback checks) reach the app on http://127.0.0.1:<port> as well as localhost.
  ( cd "$ROOT/apps/frontend" && CLUE_SITE_EDITOR_SUFFIX="editor.localhost:${EDITOR_PORT}" \
      npm run dev -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" \
      > "${LOG}_frontend.log" 2>&1 & )
  start_site_editor

  echo "starting…"; sleep 8; status
  echo
  echo "app:   http://localhost:${FRONTEND_PORT}"
  echo "editor: http://<label>.editor.localhost:${EDITOR_PORT} (one label per workspace; open a site in the app)"
  echo "login: aryan+clerk_test_design@example.com / ClueDev2026!stripe / code 424242"
}

down() {
  stop_ingestion_pool
  pkill -f "$ROOT/.venv/bin/python -m uvicorn lumen_api.main:app" 2>/dev/null || true
  pkill -f "$ROOT/.venv/bin/python -m uvicorn clue_api.projections_main:app" 2>/dev/null || true
  pkill -f "$ROOT/.venv/bin/python -m uvicorn --factory clue_page_origin.main:build_application" 2>/dev/null || true
  pkill -f "$ROOT/.venv/bin/python -m clue_api.fleet_main" 2>/dev/null || true
  pkill -f "next dev.*${FRONTEND_PORT}" 2>/dev/null || true
  stop_site_editor
  echo "stack stopped"
}

status() {
  for spec in "$FRONTEND_PORT frontend" "$DESIGN_PORT design-api" "$PLATFORM_PORT platform-api" "$PLATFORM2_PORT platform-api-2" "8040 page-origin" "$EDITOR_PORT site-editor"; do
    port="${spec%% *}"; name="${spec#* }"
    if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "  $name ($port): UP"
    else
      echo "  $name ($port): DOWN"
    fi
  done
  pool_running="$(pgrep -f "$ROOT/.venv/bin/python -m lumen_api.ingestion_pool" | wc -l | tr -d ' ' || true)"
  echo "  ingestion-pool: ${pool_running:-0} process(es), including idle controller"
  running="$(pgrep -f "$ROOT/.venv/bin/python -m clue_api.fleet_main" | wc -l | tr -d ' ')"   # macOS pgrep has no -c
  if [ "${running:-0}" -gt 0 ]; then
    echo "  fleet-worker: UP ($running process(es), $WORKER_CONCURRENCY slot(s) each)"
  else
    echo "  fleet-worker: DOWN"
  fi
  load_env
  if [ "${CLUE_LANGFUSE_ENABLED:-false}" = "true" ]; then
    echo "  langfuse: enabled (${CLUE_LANGFUSE_HOST:-https://cloud.langfuse.com}, env=${CLUE_LANGFUSE_ENVIRONMENT:-unset}) — make langfuse-check to verify the keys"
  else
    echo "  langfuse: disabled"
  fi
  if [ "${CLUE_SANDBOX_ENABLED:-true}" = "true" ]; then
    if docker image inspect "${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest}" >/dev/null 2>&1; then
      echo "  sandbox: enabled, image ${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest} present"
    else
      echo "  sandbox: enabled but image ${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest} MISSING or Docker down — run_python refuses; make sandbox-image"
    fi
  else
    echo "  sandbox: disabled (CLUE_SANDBOX_ENABLED=false) — binary attachments unreadable to the agent"
  fi
}

case "${1:-status}" in
  up) up ;;
  down) down ;;
  restart-api) restart_api ;;
  restart-workers) restart_workers ;;
  restart-ingestion) restart_ingestion_pool ;;
  restart-editor) restart_editor ;;
  status) status ;;
  *) echo "usage: $0 up|down|restart-api|restart-workers|restart-ingestion|restart-editor|status"; exit 2 ;;
esac
