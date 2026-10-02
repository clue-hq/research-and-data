#!/usr/bin/env bash
# Deploy one commit to the VM (first deployment spec §9.3). Run AFTER Railway's deploy of the same
# commit is green: Railway's platform-api pre-deploy command owns `alembic upgrade head`; this script
# only checks the database is at head, so two migration runs can never race.
# Usage: deploy.sh <git-sha>   (run as the clue user)
set -Eeuo pipefail
SHA="${1:?usage: deploy.sh <git-sha>}"
APP="${CLUE_APP_DIR:-/srv/clue/app}"
ENV_FILE="${CLUE_ENV_FILE:-/srv/clue/env}"
COMPOSE_ENV="${CLUE_COMPOSE_ENV:-/srv/clue/compose.env}"
BACKEND="ghcr.io/clue-hq/clue-backend:$SHA"
SANDBOX="ghcr.io/clue-hq/clue-agent-sandbox:$SHA"
COMPOSE=(docker compose --env-file "$COMPOSE_ENV" -f "$APP/deploy/vm/compose.yaml")

set_line() {  # set_line FILE KEY VALUE — replace KEY's line, or append it when absent
  if grep -q "^$2=" "$1"; then
    sed -i.bak "s#^$2=.*#$2=$3#" "$1" && rm -f "$1.bak"
  else
    echo "$2=$3" >> "$1"
  fi
}

git -C "$APP" fetch origin main
git -C "$APP" checkout --detach "$SHA"
python3 "$APP/deploy/check_prod_env.py" worker "$ENV_FILE"
docker pull "$BACKEND"
docker pull "$SANDBOX"
set_line "$ENV_FILE" CLUE_SANDBOX_IMAGE "$SANDBOX"

MIGRATE_URL="$(grep '^CLUE_MIGRATE_DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
docker run --rm --env-file "$ENV_FILE" -e CLUE_DATABASE_URL="$MIGRATE_URL" "$BACKEND" \
  shell -c "cd /app && alembic current 2>/dev/null | grep -q '(head)'" \
  || { echo "database is not at head for $SHA — wait for Railway's deploy (it runs the migration)" >&2; exit 1; }

set_line "$COMPOSE_ENV" BACKEND_IMAGE "$BACKEND"
"${COMPOSE[@]}" up -d --remove-orphans
"${COMPOSE[@]}" ps
echo "deployed $SHA"
