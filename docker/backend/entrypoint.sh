#!/usr/bin/env bash
# One image, every Python service (first deployment spec §9.1). Railway sets PORT. CLUE_BIND_HOST is
# the listen address: 0.0.0.0 (IPv4) unless set; the design API sets :: on Railway because it is
# reachable only over Railway's IPv6 private network (:: listens on IPv6 only — measured).
set -Eeuo pipefail
DESIGN_DIR=/app/subsystems/clue-design
DESIGN_PATH=".:apps/api:apps/agent_runtime"

case "${1:-}" in
  platform-api)
    cd /app && exec uvicorn clue_api.projections_main:app --host "${CLUE_BIND_HOST:-0.0.0.0}" --port "${PORT:-8020}" ;;
  design-api)
    cd "$DESIGN_DIR" && PYTHONPATH="$DESIGN_PATH" exec uvicorn lumen_api.main:app --host "${CLUE_BIND_HOST:-0.0.0.0}" --port "${PORT:-8010}" ;;
  fleet-worker)
    cd /app && exec python -m clue_api.fleet_main ;;
  ingestion-pool)
    cd "$DESIGN_DIR" && PYTHONPATH="$DESIGN_PATH" exec python -m lumen_api.ingestion_pool ;;
  migrate)
    cd /app && exec alembic upgrade head ;;
  shell)
    shift; exec bash "$@" ;;
  *)
    echo "usage: clue {platform-api|design-api|fleet-worker|ingestion-pool|migrate|shell}" >&2
    exit 2 ;;
esac
