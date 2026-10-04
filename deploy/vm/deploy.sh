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
# Must match compose.yaml (tests/deploy/test_vm_compose.py pins both).
AGENT_WORKSPACES=/srv/clue/workspaces            # CLUE_AGENT_WORKSPACE_ROOT
DESIGN_WORKSPACE=/srv/clue/lumen-agent           # LUMEN_AGENT_WORKSPACE_ROOT
OLD_DESIGN_WORKSPACE="$AGENT_WORKSPACES/lumen-agent"
FLEET=(chat design batch1 batch2 batch3 ingestion)
HEALTH_WAIT_S="${CLUE_DEPLOY_HEALTH_WAIT_S:-45}"

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

# The fleet workers' own boot check, run with the NEW image before anything restarts. Production
# 2026-10-04: a 0755 entry in the agent workspace root crash-looped every fleet worker right after
# `up`. Refused here, the old workers keep running and the error names the entry.
docker run --rm --user 1000:1000 --env-file "$ENV_FILE" \
  -e CLUE_AGENT_WORKSPACE_ROOT="$AGENT_WORKSPACES" -v "$AGENT_WORKSPACES:$AGENT_WORKSPACES" \
  "$BACKEND" shell -c "cd /app && python -c 'from clue_api.agent_workspace_wiring import build_agent_workspace_factory as boot; boot(storage=None)'" \
  || { echo "the agent workspace root $AGENT_WORKSPACES fails the workers' boot check (above); nothing was restarted" >&2; exit 1; }

# The design agent's own root: UID 1000 (every container's user) and 0700. Docker would otherwise
# create a missing bind-mount source as root, and `clue` cannot chown. Idempotent.
docker run --rm --user 0:0 -v /srv/clue:/srv/clue "$BACKEND" \
  shell -c "install -d -m 700 -o 1000 -g 1000 $DESIGN_WORKSPACE && chmod 700 $DESIGN_WORKSPACE"
# One-time move of the old root, which lived INSIDE the agent workspace root. The fleet stops first
# so no old worker re-creates the old path mid-move (it would come back 0755 and break the next
# boot). Only UID 1000/root can see inside the 0700 workspace root, hence the containers.
if docker run --rm --user 0:0 -v /srv/clue:/srv/clue "$BACKEND" shell -c "test -d $OLD_DESIGN_WORKSPACE"; then
  "${COMPOSE[@]}" stop "${FLEET[@]}"
  docker run --rm --user 0:0 -v /srv/clue:/srv/clue "$BACKEND" \
    shell -c "cp -a $OLD_DESIGN_WORKSPACE/. $DESIGN_WORKSPACE/ && rm -rf $OLD_DESIGN_WORKSPACE"
  echo "moved the design agent workspace to $DESIGN_WORKSPACE"
fi

set_line "$COMPOSE_ENV" BACKEND_IMAGE "$BACKEND"
"${COMPOSE[@]}" up -d --remove-orphans
"${COMPOSE[@]}" ps

# `up` reports success even when a worker cannot boot and restarts forever (177 restarts went
# unnoticed on 2026-10-04). Compare restart counts across a short wait; any rise, or a container
# that is not running, fails the deploy with its log tail.
baseline=""
for id in $("${COMPOSE[@]}" ps -q "${FLEET[@]}"); do
  baseline+="$(docker inspect -f '{{.Name}} {{.RestartCount}} {{.State.Running}}' "$id")"$'\n'
done
sleep "$HEALTH_WAIT_S"
unhealthy=""
for id in $("${COMPOSE[@]}" ps -q "${FLEET[@]}"); do
  read -r name restarts running <<<"$(docker inspect -f '{{.Name}} {{.RestartCount}} {{.State.Running}}' "$id")"
  before="$(awk -v n="$name" '$1 == n {print $2}' <<<"$baseline")"
  if [ "$running" != "true" ] || [ "$restarts" -gt "${before:-0}" ]; then
    unhealthy+=" ${name#/}"
    docker logs --tail 30 "$id" >&2 || true
  fi
done
if [ -n "$unhealthy" ]; then
  echo "deploy of $SHA FAILED: restarting or stopped after up:$unhealthy" >&2
  exit 1
fi
echo "deployed $SHA"
