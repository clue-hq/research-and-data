#!/usr/bin/env bash
# Boot every service from the built image against throwaway Postgres (pgvector) + Redis and check it
# comes up (first deployment spec §9.5): both APIs answer /healthz, the worker registers its
# handlers and starts, and the sandbox runs a trivial script through the image's Docker CLI.
# Usage: boot_smoke.sh <backend-image> <sandbox-image>
# Expects Postgres on 127.0.0.1:5432 (clue/clue/clue, vector extension created) and Redis on :6379,
# and Linux host networking (GitHub's ubuntu runners).
set -Eeuo pipefail
IMAGE="${1:?usage: boot_smoke.sh <backend-image> <sandbox-image>}"
SANDBOX="${2:?usage: boot_smoke.sh <backend-image> <sandbox-image>}"
DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
ENVF="$(mktemp)"
cat > "$ENVF" <<ENV
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue
CLUE_REDIS_URL=redis://127.0.0.1:6379/0
CLUE_STORAGE_BACKEND=fs
CLUE_STORAGE_FS_ROOT=/tmp/artifacts
CLUE_AGENT_WORKSPACE_ROOT=/tmp/clue-workspaces
CLUE_DESIGN_RUNTIME_ENABLED=1
CLUE_SANDBOX_ENABLED=true
CLUE_SANDBOX_IMAGE=$SANDBOX
LUMEN_EMBEDDED_FLEET_WORKER=0
# No model key in CI: the worker refuses to boot on a stub gateway unless it is allowed explicitly.
CLUE_GATEWAY_ALLOW_STUB=true
ENV
cleanup() {
  docker rm -f smoke-platform smoke-design smoke-worker > /dev/null 2>&1 || true
  rm -f "$ENVF"
}
trap cleanup EXIT
start() { docker run -d --name "$1" --network host --env-file "$ENVF" "${@:2}" > /dev/null; }
wait_http() {  # wait_http URL CONTAINER
  for _ in $(seq 1 90); do
    curl -fsS "$1" > /dev/null 2>&1 && { echo "ok: $1"; return 0; }
    sleep 2
  done
  echo "FAILED: $1 never answered"
  docker logs --tail 100 "$2"
  return 1
}
wait_log() {  # wait_log CONTAINER EVENT
  for _ in $(seq 1 90); do
    docker logs "$1" 2>&1 | grep -q "\"event\": \"$2\"" && { echo "ok: $1 logged $2"; return 0; }
    sleep 2
  done
  echo "FAILED: $1 never logged $2"
  docker logs --tail 100 "$1"
  return 1
}

docker run --rm --network host --env-file "$ENVF" "$IMAGE" migrate
start smoke-platform -e PORT=18020 "$IMAGE" platform-api
start smoke-design -e PORT=18010 "$IMAGE" design-api
wait_http http://127.0.0.1:18020/healthz smoke-platform
wait_http http://127.0.0.1:18010/healthz smoke-design

start smoke-worker --group-add "$DOCKER_GID" -v /var/run/docker.sock:/var/run/docker.sock "$IMAGE" fleet-worker
wait_log smoke-worker fleet.boot.handlers_registered
wait_log smoke-worker worker.start

# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: it expands in the container
docker run --rm --network host --group-add "$DOCKER_GID" -v /var/run/docker.sock:/var/run/docker.sock \
  -e SANDBOX="$SANDBOX" "$IMAGE" shell -c '
    set -e
    python -c "from clue_api.sandbox.docker_runner import docker_available; ok, why = docker_available(\"$SANDBOX\"); assert ok, why"
    echo "ok: docker_available($SANDBOX)"
    out=$(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
          --user 1000:1000 "$SANDBOX" python -c "print(2 + 2)")
    [ "$out" = "4" ]
    echo "ok: sandbox ran python under the lockdown flags"'
echo "BOOT SMOKE PASSED"
