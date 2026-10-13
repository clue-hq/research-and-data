#!/usr/bin/env bash
# Static smoke test of a built backend image: every service imports, the helper runs, the fonts
# and Tailwind toolchain are present, Chromium launches, ffmpeg/ffprobe run (research media), and
# the image runs as non-root.
# Every check runs even when an earlier one fails, so one run reports every problem; the script
# exits non-zero if any check failed.
# Usage: docker/backend/smoke.sh <image>
set -Euo pipefail
IMAGE="${1:?usage: smoke.sh <image>}"
run() { docker run --rm --pull never --entrypoint "" "$IMAGE" "$@"; }
docker image inspect "$IMAGE" > /dev/null 2>&1 || { echo "FAILED: image $IMAGE is not present locally (build or pull it first)" >&2; exit 1; }

failed=()
check() {  # check LABEL COMMAND...
  local label="$1"
  shift
  if "$@"; then echo "ok: $label"; else echo "FAILED: $label"; failed+=("$label"); fi
}
quiet() { "$@" > /dev/null; }
helper_answers() { run bash -c 'echo "{\"action\":\"build_info\"}" | "$LUMEN_CORE_HELPER"' | grep -q '"engine_commit"'; }
runs_as_uid_1000() { [ "$(run id -u)" = "1000" ]; }

check "platform imports" run python -c "import clue_api.projections_main, clue_api.fleet_main, clue_page_origin.main"
check "design imports" run bash -c 'cd /app/subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime python -c "import lumen_api.main, lumen_api.ingestion_pool"'
check "helper answers build_info" helper_answers
check "font manifest" run test -f /app/subsystems/clue-design/apps/api/font-library/manifest.json
check "tailwind toolchain" run test -d /app/subsystems/clue-design/apps/editor/node_modules/@tailwindcss/node
check "tailwind browser runtime" run test -f /app/subsystems/clue-design/apps/editor/public/vendor/tailwind-browser.js
check "node" run node --version
check "ffmpeg" quiet run ffmpeg -version
check "ffprobe" quiet run ffprobe -version
check "docker cli" run docker --version
check "chromium launches" run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop()"
check "non-root (uid 1000)" runs_as_uid_1000
check "alembic" quiet run alembic --help
check "s3 storage sdk" run python -c "import aioboto3"
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: it expands in the container
check "arv2 raw root writable" run sh -c 'case "$CLUE_ARV2_RAW_ROOT" in /*) ;; *) exit 1 ;; esac \
  && d="$CLUE_ARV2_RAW_ROOT/media/smoke" && mkdir -p "$d" && touch "$d/probe.mp3" && rm -r "$d"'

if [ "${#failed[@]}" -gt 0 ]; then
  echo "SMOKE FAILED (${#failed[@]}): $(IFS=,; echo "${failed[*]}")"
  exit 1
fi
echo "SMOKE PASSED"
