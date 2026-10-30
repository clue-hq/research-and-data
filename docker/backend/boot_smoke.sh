#!/usr/bin/env bash
# Boot every service from the built image and check it comes up (first deployment spec §9.5):
# migrations run, both APIs answer /healthz, the worker registers its handlers and starts, the
# S3 storage backend round-trips an object, and the sandbox runs a trivial script through the
# image's Docker CLI.
# Usage: boot_smoke.sh <backend-image> <sandbox-image>
# Self-contained: starts its own throwaway Postgres (pgvector), Redis and S3 server on a private Docker
# network and removes everything on exit, so it runs the same on a Mac (Docker Desktop) and in CI.
set -Eeuo pipefail
IMAGE="${1:?usage: boot_smoke.sh <backend-image> <sandbox-image>}"
SANDBOX="${2:?usage: boot_smoke.sh <backend-image> <sandbox-image>}"
NET="clue-boot-smoke-$$"
PLATFORM_PORT=18020
DESIGN_PORT=18010
ENVF=""

cleanup() {
  docker rm -f smoke-platform smoke-design smoke-worker smoke-pg smoke-redis smoke-s3 > /dev/null 2>&1 || true
  docker network rm "$NET" > /dev/null 2>&1 || true
  rm -f "$ENVF"
}
trap cleanup EXIT
cleanup
ENVF="$(mktemp)"

cat > "$ENVF" <<ENV
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@smoke-pg:5432/clue
CLUE_REDIS_URL=redis://smoke-redis:6379/0
CLUE_STORAGE_BACKEND=fs
CLUE_STORAGE_FS_ROOT=/tmp/artifacts
CLUE_AGENT_WORKSPACE_ROOT=/tmp/clue-workspaces
CLUE_DESIGN_RUNTIME_ENABLED=1
CLUE_SANDBOX_ENABLED=true
CLUE_SANDBOX_IMAGE=$SANDBOX
LUMEN_EMBEDDED_FLEET_WORKER=0
# No model key here: the worker refuses to boot on a stub gateway unless it is allowed explicitly,
# and the agent model provider needs some key to be built (it makes no request until a turn runs).
CLUE_GATEWAY_ALLOW_STUB=true
CLUE_OPENROUTER_API_KEY=boot-smoke-placeholder-not-a-key
ENV

docker network create "$NET" > /dev/null
docker run -d --name smoke-pg --network "$NET" \
  -e POSTGRES_USER=clue -e POSTGRES_PASSWORD=clue -e POSTGRES_DB=clue pgvector/pgvector:pg16 > /dev/null
docker run -d --name smoke-redis --network "$NET" redis:7 > /dev/null
# SeaweedFS as the S3 server (MinIO no longer publishes pullable images); with no identities
# configured it accepts any credentials.
docker run -d --name smoke-s3 --network "$NET" chrislusf/seaweedfs:4.48 server -s3 -dir=/data > /dev/null
ready=no
for _ in $(seq 1 60); do
  # pg_isready over TCP: the image's init phase answers on the socket before the real server is up.
  docker exec smoke-pg pg_isready -h 127.0.0.1 -U clue -d clue > /dev/null 2>&1 && { ready=yes; break; }
  sleep 1
done
[ "$ready" = yes ] || { echo "FAILED: throwaway Postgres never became ready"; docker logs --tail 50 smoke-pg; exit 1; }
docker exec smoke-pg psql -h 127.0.0.1 -U clue -d clue -qc "CREATE EXTENSION IF NOT EXISTS vector"

start() { docker run -d --name "$1" --network "$NET" --env-file "$ENVF" "${@:2}" > /dev/null; }
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

docker run --rm --network "$NET" --env-file "$ENVF" "$IMAGE" migrate
echo "ok: migrate"
start smoke-platform -e PORT=$PLATFORM_PORT -p "127.0.0.1:$PLATFORM_PORT:$PLATFORM_PORT" "$IMAGE" platform-api
start smoke-design -e PORT=$DESIGN_PORT -p "127.0.0.1:$DESIGN_PORT:$DESIGN_PORT" "$IMAGE" design-api
wait_http "http://127.0.0.1:$PLATFORM_PORT/healthz" smoke-platform
wait_http "http://127.0.0.1:$DESIGN_PORT/healthz" smoke-design

# The S3 backend through the app's own factory (CLUE_STORAGE_* settings + secrets → S3Storage):
# create the bucket, then put, exists, get, list and delete one object.
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: it runs in the container
docker run --rm --network "$NET" --entrypoint "" \
  -e CLUE_STORAGE_BACKEND=s3 -e CLUE_STORAGE_S3_BUCKET=boot-smoke -e CLUE_STORAGE_S3_REGION=us-east-1 \
  -e CLUE_STORAGE_S3_ENDPOINT_URL=http://smoke-s3:8333 \
  -e CLUE_STORAGE_S3_ACCESS_KEY_ID=smoke-access -e CLUE_STORAGE_S3_SECRET_ACCESS_KEY=smoke-secret-key \
  "$IMAGE" python -c '
import asyncio, os, aioboto3
from clue_storage import S3Storage, storage_from_settings

async def main():
    last = None
    for _ in range(60):  # the S3 server may still be starting
        try:
            async with aioboto3.Session().client("s3", endpoint_url=os.environ["CLUE_STORAGE_S3_ENDPOINT_URL"],
                    aws_access_key_id="smoke-access", aws_secret_access_key="smoke-secret-key",
                    region_name="us-east-1") as s3:
                await s3.create_bucket(Bucket="boot-smoke")
            break
        except Exception as exc:
            last = exc
            await asyncio.sleep(1)
    else:
        raise SystemExit(f"FAILED: the throwaway S3 server never accepted a bucket: {last}")
    store = storage_from_settings()
    assert isinstance(store, S3Storage), type(store)
    key, body = "boot-smoke/probe.txt", b"boot smoke\n"
    await store.put(key, body, media_type="text/plain")
    assert await store.exists(key)
    assert await store.get(key) == body
    assert key in [k async for k, _ in store.list_blobs()]
    await store.delete(key)
    assert not await store.exists(key)

asyncio.run(main())
'
echo "ok: s3 storage round trip (put, exists, get, list, delete)"

# The worker drives the sandbox through the host's Docker socket; give it the socket's group as the
# containers see it (root on Docker Desktop, the docker group on Linux).
DOCKER_GID="$(docker run --rm --entrypoint stat -v /var/run/docker.sock:/var/run/docker.sock "$SANDBOX" -c %g /var/run/docker.sock)"
start smoke-worker --group-add "$DOCKER_GID" -v /var/run/docker.sock:/var/run/docker.sock "$IMAGE" fleet-worker
wait_log smoke-worker fleet.boot.handlers_registered
wait_log smoke-worker worker.start

# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: it expands in the container
docker run --rm --network "$NET" --group-add "$DOCKER_GID" -v /var/run/docker.sock:/var/run/docker.sock \
  -e SANDBOX="$SANDBOX" "$IMAGE" shell -c '
    set -e
    python -c "from clue_agents.sandbox.docker_runner import docker_available; ok, why = docker_available(\"$SANDBOX\"); assert ok, why"
    echo "ok: docker_available($SANDBOX)"
    out=$(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
          --user 1000:1000 "$SANDBOX" python -c "print(2 + 2)")
    [ "$out" = "4" ]
    echo "ok: sandbox ran python under the lockdown flags"'
echo "BOOT SMOKE PASSED"
