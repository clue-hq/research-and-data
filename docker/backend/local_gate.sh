#!/usr/bin/env bash
# Local gate for the backend image: run before pushing any change to docker/backend/, the
# Dockerfile, pyproject.toml/uv.lock or the deploy-images workflow. It builds both images and runs
# the same checks CI runs (smoke.sh, boot_smoke.sh), so a CI round confirms rather than discovers.
# Builds for this machine's architecture (arm64 on a Mac); CI's amd64 run stays the final word.
# Usage: docker/backend/local_gate.sh   (from the repository root)
set -Eeuo pipefail
cd "$(git rev-parse --show-toplevel)"
BACKEND=clue-backend:local-gate
SANDBOX=clue-agent-sandbox:local-gate
LABEL=clue.local-gate=1
MIN_FREE_GB=15

# Docker Desktop's VM disk is fixed-size and shared with every lane's databases: a full disk
# crashes them (2026-10-03). Refuse to build without headroom.
free_kb="$(docker run --rm alpine df -Pk / | awk 'NR==2 {print $4}')"
if [ "$free_kb" -lt $((MIN_FREE_GB * 1024 * 1024)) ]; then
  echo "FAILED: Docker has $((free_kb / 1024 / 1024)) GB free; need ${MIN_FREE_GB} GB."
  echo "Free space first: docker image prune --filter label=$LABEL, docker builder prune --keep-storage 10GB"
  exit 1
fi
echo "ok: docker disk $((free_kb / 1024 / 1024)) GB free"

docker build --label "$LABEL" -t "$SANDBOX" docker/agent-sandbox
docker build --label "$LABEL" -f docker/backend/Dockerfile -t "$BACKEND" .
echo "ok: images built"

docker/backend/smoke.sh "$BACKEND"
docker/backend/boot_smoke.sh "$BACKEND" "$SANDBOX"

# Rebuilds leave the previous build's layers behind as dangling images; remove only ours.
docker image prune -f --filter "label=$LABEL" > /dev/null
echo "LOCAL GATE PASSED — push when ready; CI confirms on amd64"
