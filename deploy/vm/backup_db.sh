#!/usr/bin/env bash
# Nightly Postgres dump to R2 (first deployment spec §8). Refuses an empty dump or one pg_restore
# cannot read, keeps 14 days, and checks in to Sentry cron monitoring only on success.
set -Eeuo pipefail
# shellcheck source=/dev/null
source "${CLUE_BACKUP_ENV:-/srv/clue/backup.env}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="clue-$STAMP.dump"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws_r2() {
  docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -v "$WORK:/work" \
    amazon/aws-cli:2.17.0 --endpoint-url "$R2_ENDPOINT" --region auto "$@"
}

docker run --rm -v "$WORK:/work" postgres:16 \
  pg_dump --format=custom --no-owner --dbname="$PGURL" --file="/work/$NAME"
[ -s "$WORK/$NAME" ] || { echo "backup FAILED: empty dump" >&2; exit 1; }
docker run --rm -v "$WORK:/work" postgres:16 pg_restore --list "/work/$NAME" > /dev/null \
  || { echo "backup FAILED: pg_restore cannot read the dump" >&2; exit 1; }
aws_r2 s3 cp "/work/$NAME" "s3://$R2_BUCKET/db-backups/$NAME"

# Retention: delete dumps whose date is more than 14 days ago.
CUTOFF="$(python3 -c 'import datetime as d; print((d.datetime.now(d.timezone.utc) - d.timedelta(days=14)).strftime("%Y%m%d"))')"
aws_r2 s3 ls "s3://$R2_BUCKET/db-backups/" | awk '{print $4}' | while read -r old; do
  day="$(echo "$old" | sed -nE 's/^clue-([0-9]{8})T[0-9]{6}Z\.dump$/\1/p')"
  if [ -n "$day" ] && [ "$day" -lt "$CUTOFF" ]; then
    aws_r2 s3 rm "s3://$R2_BUCKET/db-backups/$old"
  fi
done

curl -fsS -m 10 "$SENTRY_CRON_URL_BACKUP" > /dev/null
echo "backup OK: $NAME ($(wc -c < "$WORK/$NAME" | tr -d ' ') bytes)"
