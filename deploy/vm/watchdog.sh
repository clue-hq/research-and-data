#!/usr/bin/env bash
# Every 5 minutes (spec §11): memory, disk and every compose service. Checks in to Sentry cron
# monitoring only when all are healthy — a missed check-in is the alert.
set -Eeuo pipefail
# shellcheck source=/dev/null
source "${CLUE_BACKUP_ENV:-/srv/clue/backup.env}"
COMPOSE_FILE="${CLUE_COMPOSE_FILE:-/srv/clue/app/deploy/vm/compose.yaml}"
COMPOSE_ENV="${CLUE_COMPOSE_ENV:-/srv/clue/compose.env}"
fail() { echo "WATCHDOG: $*" >&2; exit 1; }

mem_used="$(free | awk '/^Mem:/ {printf "%d", ($3 / $2) * 100}')"
[ "$mem_used" -lt 85 ] || fail "memory at ${mem_used}%"
disk_used="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
[ "$disk_used" -lt 80 ] || fail "disk at ${disk_used}%"
running="$(docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" ps --status running --services)"
for svc in chat design batch1 batch2 batch3 ingestion pgbouncer; do
  grep -qx "$svc" <<< "$running" || fail "$svc not running"
done
curl -fsS -m 10 "$SENTRY_CRON_URL_WATCHDOG" > /dev/null
