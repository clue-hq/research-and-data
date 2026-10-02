#!/usr/bin/env bash
# Restore rehearsal (first deployment spec §8 step 3): restore the newest R2 dump into a throwaway
# Postgres (pgvector) and check it. Usage: restore_check.sh
# CLUE_RESTORE_FROM_FILE=<path to a .dump> restores that file instead of downloading from R2.
set -Eeuo pipefail
WORK="$(mktemp -d)"
CONTAINER="clue-restore-check-$$"
trap 'rm -rf "$WORK"; docker rm -f "$CONTAINER" > /dev/null 2>&1 || true' EXIT

if [ -n "${CLUE_RESTORE_FROM_FILE:-}" ]; then
  NAME="$(basename "$CLUE_RESTORE_FROM_FILE")"
  cp "$CLUE_RESTORE_FROM_FILE" "$WORK/$NAME"
else
  # shellcheck source=/dev/null
  source "${CLUE_BACKUP_ENV:-/srv/clue/backup.env}"
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  aws_r2() {
    docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -v "$WORK:/work" \
      amazon/aws-cli:2.17.0 --endpoint-url "$R2_ENDPOINT" --region auto "$@"
  }
  NAME="$(aws_r2 s3 ls "s3://$R2_BUCKET/db-backups/" | awk '{print $4}' | grep -E '^clue-.*\.dump$' | sort | tail -1)"
  [ -n "$NAME" ] || { echo "no backups found in s3://$R2_BUCKET/db-backups/" >&2; exit 1; }
  aws_r2 s3 cp "s3://$R2_BUCKET/db-backups/$NAME" "/work/$NAME"
fi

docker run -d --name "$CONTAINER" -e POSTGRES_PASSWORD=check -v "$WORK:/work" pgvector/pgvector:pg16 > /dev/null
for _ in $(seq 1 60); do
  docker exec "$CONTAINER" pg_isready -U postgres > /dev/null 2>&1 && break
  sleep 1
done
psql_check() { docker exec "$CONTAINER" psql -U postgres -d clue -At -v ON_ERROR_STOP=1 -c "$1"; }
docker exec "$CONTAINER" psql -U postgres -At -c "CREATE DATABASE clue" > /dev/null
docker exec "$CONTAINER" pg_restore --no-owner --exit-on-error -U postgres -d clue "/work/$NAME"
echo "alembic head: $(psql_check "SELECT version_num FROM alembic_version")"
for table in workspace account_entity arv2_research_job design_document design_web_publish; do
  echo "$table: $(psql_check "SELECT count(*) FROM $table") rows"
done
echo "RESTORE CHECK PASSED for $NAME"
