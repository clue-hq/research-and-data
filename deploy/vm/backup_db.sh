#!/usr/bin/env bash
# Nightly Postgres dump to R2 (first deployment spec §8). Refuses an empty dump or one pg_restore
# cannot read, keeps 14 days, and checks in to Sentry cron monitoring only on success.
set -Eeuo pipefail
# shellcheck source=/dev/null
source "${CLUE_BACKUP_ENV:-/srv/clue/backup.env}"

# The backups must live apart from the app's files: the app's fleet workers delete every key in
# their bucket that has no `artifact` row (clue_storage.sweep_orphan_blobs), and a shared key would
# let an app bug or a leaked app key delete the backups. Checked first, so a misconfigured env
# file costs nothing and — with no Sentry check-in — raises the missed-backup alert.
APP_ENV="${CLUE_ENV_FILE:-/srv/clue/env}"
app_setting() { sed -nE "s/^$1=[\"']?([^\"']*)[\"']?\$/\1/p" "$APP_ENV" | tail -1; }
[ -r "$APP_ENV" ] || { echo "backup FAILED: cannot read the app env $APP_ENV to check separation" >&2; exit 1; }
if [ "$R2_BUCKET" = "$(app_setting CLUE_STORAGE_S3_BUCKET)" ]; then
  echo "backup FAILED: R2_BUCKET must not share the app's bucket ($R2_BUCKET) — its orphan sweep deletes dumps" >&2
  exit 1
fi
if [ "$AWS_ACCESS_KEY_ID" = "$(app_setting CLUE_STORAGE_S3_ACCESS_KEY_ID)" ]; then
  echo "backup FAILED: the backup key must not share the app's R2 key — give clue-backups its own token" >&2
  exit 1
fi
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
