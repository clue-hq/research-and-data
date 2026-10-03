#!/usr/bin/env bash
# Boot one Railway service's process locally with its REAL production variables (from `railway run`),
# swapping only the database and Redis for throwaway local ones and turning Sentry/Langfuse off, so
# every startup refusal shows up in one pass — before a redeploy, not one failed deploy at a time
# (first deploy, 2026-10-03). Prints no variable values; the env file it hands docker is mode 0600 and
# deleted on exit.
# Usage (from a directory linked to the production project with `railway link`):
#   deploy/railway_boot_check.sh <railway-service> <clue command> <backend-image>
#   e.g. deploy/railway_boot_check.sh platform-api platform-api ghcr.io/clue-hq/clue-backend:production
# EXTRA_ENV="KEY=value ..." adds local-only overrides, to look past a refusal already understood.
set -Eeuo pipefail
SERVICE="${1:?usage: railway_boot_check.sh <railway-service> <clue command> <backend-image>}"
export CMD="${2:?}" IMAGE="${3:?}" NET=railway-boot-check PORT_LOCAL=18099
remove_containers() {
  docker rm -f rbc-pg rbc-redis rbc-app > /dev/null 2>&1 || true
  docker network rm "$NET" > /dev/null 2>&1 || true
}
remove_containers  # leftovers from an interrupted run
MIGRATE_LOG="$(mktemp)"
ENVF="$(mktemp)"
chmod 600 "$ENVF"
export MIGRATE_LOG ENVF
trap 'remove_containers; rm -f "$MIGRATE_LOG" "$ENVF"' EXIT

docker network create "$NET" > /dev/null
docker run -d --name rbc-pg --network "$NET" -e POSTGRES_USER=clue -e POSTGRES_PASSWORD=clue \
  -e POSTGRES_DB=clue pgvector/pgvector:pg16 > /dev/null
docker run -d --name rbc-redis --network "$NET" redis:7 > /dev/null
for _ in $(seq 1 60); do
  docker exec rbc-pg pg_isready -h 127.0.0.1 -U clue -d clue > /dev/null 2>&1 && break
  sleep 1
done
docker exec rbc-pg psql -h 127.0.0.1 -U clue -d clue -qc "CREATE EXTENSION IF NOT EXISTS vector"

# The service's variable NAMES from Railway; `railway run` puts their VALUES in the environment of
# the inner shell, which writes only those names to the 0600 env file docker reads.
KEYS="$(railway variables --service "$SERVICE" --json \
  | python3 -c 'import json, sys; print("|".join(sorted(json.load(sys.stdin))))')"
export KEYS
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: it runs under `railway run`
railway run --service "$SERVICE" -- bash -c 'env | grep -E "^($KEYS)=" | grep -vE "^RAILWAY_" > "$ENVF"'

overrides=(
  -e CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@rbc-pg:5432/clue
  -e CLUE_REDIS_URL=redis://rbc-redis:6379/0
  -e CLUE_SENTRY_ENABLED=false -e CLUE_LANGFUSE_ENABLED=false -e "PORT=$PORT_LOCAL"
)
for kv in ${EXTRA_ENV:-}; do overrides+=(-e "$kv"); done

if docker run --rm --network "$NET" --env-file "$ENVF" "${overrides[@]}" "$IMAGE" migrate > "$MIGRATE_LOG" 2>&1; then
  echo "ok: migrate"
else
  echo "FAILED: migrate"
  tail -5 "$MIGRATE_LOG"
  exit 1
fi
docker run -d --name rbc-app --network "$NET" -p "127.0.0.1:$PORT_LOCAL:$PORT_LOCAL" \
  --env-file "$ENVF" "${overrides[@]}" "$IMAGE" "$CMD" > /dev/null
rm -f "$ENVF"  # docker has read it; nothing else needs it

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT_LOCAL/healthz" > /dev/null 2>&1; then
    echo "ok: $SERVICE ($CMD) booted with its production variables; /healthz answers"
    exit 0
  fi
  [ "$(docker inspect -f '{{.State.Running}}' rbc-app 2> /dev/null)" = "false" ] && break
  sleep 2
done
echo "FAILED: $SERVICE ($CMD) did not come up"
docker logs rbc-app 2>&1 | grep -E "Error|refus|required|not configured" | tail -8
exit 1
