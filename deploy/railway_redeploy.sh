#!/usr/bin/env bash
# Redeploy one Railway service from its configured source and wait until it is live.
# platform-api and design-api run the backend image CI built and tested
# (ghcr.io/clue-hq/clue-backend:production); Railway does not build it again. deploy-images calls
# this after moving the production tags. platform-api's pre-deploy `clue migrate` runs inside its
# deployment, so a SUCCESS here also means the schema is at head.
# Usage: deploy/railway_redeploy.sh <service> [timeout-seconds]
# Auth: RAILWAY_TOKEN, a project token for the production environment (CI), or a `railway login`
# session with this directory linked to the project.
set -Eeuo pipefail
SERVICE="${1:?usage: railway_redeploy.sh <service> [timeout-seconds]}"
TIMEOUT="${2:-1200}"

latest() {  # prints "<deployment-id> <status>" of the service's newest deployment
  railway deployment list --service "$SERVICE" --limit 1 --json \
    | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d[0]["id"], d[0]["status"]) if d else print("none", "none")'
}

read -r before _ < <(latest)
railway redeploy --service "$SERVICE" --from-source --yes
echo "redeploy of $SERVICE requested; waiting up to ${TIMEOUT}s"

deadline=$((SECONDS + TIMEOUT))
while [ "$SECONDS" -lt "$deadline" ]; do
  read -r id status < <(latest)
  if [ "$id" != "$before" ]; then
    case "$status" in
      SUCCESS)
        echo "ok: $SERVICE deployment $id is live"
        exit 0 ;;
      FAILED | CRASHED | REMOVED | SKIPPED)
        echo "FAILED: $SERVICE deployment $id ended $status"
        railway logs --service "$SERVICE" --deployment "$id" --lines 100 || true
        exit 1 ;;
    esac
  fi
  sleep 15
done
echo "FAILED: $SERVICE was not live after ${TIMEOUT}s"
exit 1
