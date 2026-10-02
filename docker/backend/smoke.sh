#!/usr/bin/env bash
# Static smoke test of a built backend image: every service imports, the helper runs, the fonts
# and Tailwind toolchain are present, Chromium launches, and the image runs as non-root.
# Usage: docker/backend/smoke.sh <image>
set -Eeuo pipefail
IMAGE="${1:?usage: smoke.sh <image>}"
run() { docker run --rm --pull never --entrypoint "" "$IMAGE" "$@"; }
docker image inspect "$IMAGE" > /dev/null 2>&1 || { echo "FAILED: image $IMAGE is not present locally (build or pull it first)" >&2; exit 1; }

run python -c "import clue_api.projections_main, clue_api.fleet_main, clue_page_origin.main"
echo "ok: platform imports"
run bash -c 'cd /app/subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime python -c "import lumen_api.main, lumen_api.ingestion_pool"'
echo "ok: design imports"
run bash -c 'echo "{\"action\":\"build_info\"}" | "$LUMEN_CORE_HELPER"' | grep -q '"engine_commit"'
echo "ok: helper answers build_info"
run test -f /app/subsystems/clue-design/apps/api/font-library/manifest.json
echo "ok: font manifest"
run test -d /app/subsystems/clue-design/apps/editor/node_modules/@tailwindcss/node
echo "ok: tailwind toolchain"
run test -f /app/subsystems/clue-design/apps/editor/public/vendor/tailwind-browser.js
echo "ok: tailwind browser runtime"
run node --version
run docker --version
run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop()"
echo "ok: chromium launches"
[ "$(run id -u)" = "1000" ]
echo "ok: non-root (uid 1000)"
run alembic --help > /dev/null
echo "ok: alembic"
run python -c "import aioboto3"
echo "ok: s3 storage sdk"
run sh -c 'case "$CLUE_ARV2_RAW_ROOT" in /*) ;; *) exit 1 ;; esac \
  && d="$CLUE_ARV2_RAW_ROOT/media/smoke" && mkdir -p "$d" && touch "$d/probe.mp3" && rm -r "$d"'
echo "ok: arv2 raw root writable"
echo "SMOKE PASSED"
