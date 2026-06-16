#!/usr/bin/env bash
# Dev helper for agents/design-recipes-quality-v0.
#
# The important invariant is that the checked-out branch, backend helper, and
# browser WASM artifact all report the same engine_commit. Generated WASM files
# are gitignored, so always run `prepare` after switching branches/worktrees.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${LUMEN_VENV_PYTHON:-/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python}"
HOST="${LUMEN_HOST:-127.0.0.1}"
API_PORT="${LUMEN_API_PORT:-8002}"
WEB_PORT="${LUMEN_WEB_PORT:-3002}"
BACKEND_LOG="${LUMEN_BACKEND_LOG:-/tmp/lumen-design-recipes-quality-v0-backend.log}"
FRONTEND_LOG="${LUMEN_FRONTEND_LOG:-/tmp/lumen-design-recipes-quality-v0-frontend.log}"
FIXTURE_ROOT="${LUMEN_AGENT_FIXTURE_ROOT:-$ROOT_DIR/.lumen-fixtures/agent-quality-hygiene}"
FIXTURE_TRACE_DIR="${LUMEN_AGENT_FIXTURE_TRACE_DIR:-$FIXTURE_ROOT/traces}"
AGENT_MODE="${LUMEN_AGENT_MODE:-quality-loop}"
AGENT_MAX_ITERATIONS="${LUMEN_AGENT_MAX_ITERATIONS:-5}"
ENV_FILE="${LUMEN_ENV_FILE:-$ROOT_DIR/.env}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") prepare       Rebuild browser WASM and verify local helper/WASM handshake
  $(basename "$0") verify-local  Print git HEAD and local WASM engine version
  $(basename "$0") doctor        Print branch/runtime hygiene status
  $(basename "$0") clean-runtime Remove local dev caches/logs created by this helper
  $(basename "$0") backend       Start FastAPI backend with tee logs
  $(basename "$0") frontend      Start Next editor frontend with browser WASM + CanvasKit flags
  $(basename "$0") check-served  Compare local WASM bytes with the frontend-served bytes
  $(basename "$0") browser-reset Print the DevTools cache/service-worker reset snippet
  $(basename "$0") run-fixtures  Run the 3 fixed hygiene prompts and archive outputs

Environment overrides:
  LUMEN_VENV_PYTHON=$VENV_PYTHON
  LUMEN_HOST=$HOST
  LUMEN_API_PORT=$API_PORT
  LUMEN_WEB_PORT=$WEB_PORT
  LUMEN_BACKEND_LOG=$BACKEND_LOG
  LUMEN_FRONTEND_LOG=$FRONTEND_LOG
  LUMEN_AGENT_FIXTURE_ROOT=$FIXTURE_ROOT
  LUMEN_AGENT_MODE=$AGENT_MODE
  LUMEN_AGENT_MAX_ITERATIONS=$AGENT_MAX_ITERATIONS
  LUMEN_ENV_FILE=$ENV_FILE
EOF
}

need_file() {
  if [[ ! -f "$1" ]]; then
    echo "missing required file: $1" >&2
    exit 1
  fi
}

load_env() {
  cd "$ROOT_DIR"
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ENV_FILE"
    set +a
  else
    echo "warning: no .env found at $ENV_FILE" >&2
  fi
}

git_head() {
  git -C "$ROOT_DIR" rev-parse --short=12 HEAD
}

wasm_version() {
  cd "$ROOT_DIR"
  node --input-type=module - <<'JS'
import { readFileSync } from 'node:fs';
import init, { engineVersion } from './apps/editor/public/wasm/lumen_wasm.js';
await init({ module_or_path: readFileSync('./apps/editor/public/wasm/lumen_wasm_bg.wasm') });
console.log(engineVersion());
JS
}

wasm_hash() {
  cd "$ROOT_DIR"
  need_file "apps/editor/public/wasm/lumen_wasm_bg.wasm"
  shasum -a 256 apps/editor/public/wasm/lumen_wasm_bg.wasm | awk '{print $1}'
}

verify_local() {
  cd "$ROOT_DIR"
  local head
  head="$(git_head)"
  echo "worktree : $ROOT_DIR"
  echo "branch   : $(git rev-parse --abbrev-ref HEAD)"
  echo "git HEAD : $head"
  echo "status   :"
  git status --short --branch
  echo
  echo "local WASM engineVersion:"
  wasm_version
  echo "local WASM sha256:"
  wasm_hash
}

prepare() {
  cd "$ROOT_DIR"
  echo "Building browser WASM for $(git rev-parse --abbrev-ref HEAD) @ $(git_head)"
  npm --prefix apps/editor run build:wasm
  echo
  verify_local
  echo
  echo "Verifying helper/WASM version handshake:"
  node scripts/verify_handshake.mjs
}

doctor() {
  verify_local
  echo
  echo "runtime ports:"
  echo "  backend  http://$HOST:$API_PORT"
  echo "  frontend http://$HOST:$WEB_PORT"
  echo
  echo "fixture output:"
  echo "  $FIXTURE_ROOT"
  echo
  echo "backend build-info if server is running:"
  curl -fsS "http://$HOST:$API_PORT/build-info" || true
  echo
}

clean_runtime() {
  cd "$ROOT_DIR"
  echo "Removing local dev runtime caches/logs for this worktree."
  rm -rf apps/editor/.next
  rm -rf "$FIXTURE_ROOT"
  rm -f "$BACKEND_LOG" "$FRONTEND_LOG"
  rm -f /tmp/lumen-design-recipes-quality-v0-served-wasm.wasm
}

backend() {
  cd "$ROOT_DIR"
  need_file "$VENV_PYTHON"
  load_env
  local cors_origins
  cors_origins="${LUMEN_API_CORS_ORIGINS:-}"
  for origin in "http://$HOST:$WEB_PORT" "http://localhost:$WEB_PORT"; do
    if [[ ",$cors_origins," != *",$origin,"* ]]; then
      cors_origins="${cors_origins:+$cors_origins,}$origin"
    fi
  done
  export LUMEN_API_CORS_ORIGINS="$cors_origins"
  echo "Backend: http://$HOST:$API_PORT"
  echo "Log: $BACKEND_LOG"
  echo "CORS origins: $LUMEN_API_CORS_ORIGINS"
  PYTHONPATH=apps/api:apps/agent_runtime "$VENV_PYTHON" -m uvicorn lumen_api.main:app \
    --host "$HOST" \
    --port "$API_PORT" \
    2>&1 | tee "$BACKEND_LOG"
}

frontend() {
  cd "$ROOT_DIR"
  load_env
  echo "Frontend: http://$HOST:$WEB_PORT"
  echo "Log: $FRONTEND_LOG"
  NEXT_PUBLIC_LUMEN_API_BASE_URL="http://$HOST:$API_PORT" \
  NEXT_PUBLIC_LUMEN_WASM_CORE=1 \
  NEXT_PUBLIC_LUMEN_CANVASKIT=1 \
    npm --prefix apps/editor run dev -- --hostname "$HOST" --port "$WEB_PORT" \
    2>&1 | tee "$FRONTEND_LOG"
}

check_served() {
  cd "$ROOT_DIR"
  local local_wasm served_wasm url local_hash served_hash
  local_wasm="apps/editor/public/wasm/lumen_wasm_bg.wasm"
  served_wasm="/tmp/lumen-design-recipes-quality-v0-served-wasm.wasm"
  url="http://$HOST:$WEB_PORT/wasm/lumen_wasm_bg.wasm?cb=$(date +%s)"

  need_file "$local_wasm"
  echo "Fetching served WASM from $url"
  curl -fsSL "$url" -o "$served_wasm"
  echo
  local_hash="$(shasum -a 256 "$local_wasm" | awk '{print $1}')"
  served_hash="$(shasum -a 256 "$served_wasm" | awk '{print $1}')"
  echo "local  $local_hash  $local_wasm"
  echo "served $served_hash  $served_wasm"
  if [[ "$local_hash" != "$served_hash" ]]; then
    echo "WASM HASH MISMATCH: clear browser/dev-server caches and rerun prepare." >&2
    exit 1
  fi
  echo
  echo "WASM HASH OK: frontend is serving the current local browser artifact."
  echo "Backend build-info:"
  curl -fsS "http://$HOST:$API_PORT/build-info" || true
  echo
}

browser_reset() {
  cat <<EOF
Paste this in browser DevTools on http://$HOST:$WEB_PORT:

await Promise.all((await caches.keys()).map(k => caches.delete(k)));
await Promise.all((await navigator.serviceWorker.getRegistrations()).map(r => r.unregister()));
location.reload();
EOF
}

fixture_prompt() {
  case "$1" in
    linkedin-square)
      echo "Make a 1:1 LinkedIn ad for product launch by healthcare focused AI startup Insight Health AI. They launched Magic-Doc that automates document processing of healthcare practices at 1/10 the cost. Use an exact 1080x1080px canvas, clean healthcare startup art direction, strong readable hierarchy, generous margins, and a clear Book a Demo call to action."
      ;;
    a4-appointment-card)
      echo "Create a patient appointment card of A4 size. Use preset(a4,portrait), canonical A4 layout points, a bounded clipped root artboard frame, clear appointment headline, patient instructions, clinic routing benefit, and a clear Book a Demo call to action."
      ;;
    landscape-flyer-card)
      echo "Create a simple one-page flyer/card in landscape orientation for Insight Health AI. Use a wide landscape digital canvas, clean healthcare startup styling, a clear headline, concise body copy, three benefits, generous margins, and one clear Book a Demo call to action."
      ;;
    *)
      echo "unknown fixture: $1" >&2
      return 2
      ;;
  esac
}

copy_run_artifacts() {
  local run_dir="$1"
  local out_dir="$2"
  mkdir -p "$out_dir"
  for filename in trace.jsonl final.json knowledge.json input.json scene.json; do
    if [[ -f "$run_dir/$filename" ]]; then
      cp "$run_dir/$filename" "$out_dir/$filename"
    fi
  done
  find "$run_dir/iterations" -type f \( -name "preview.svg" -o -name "preview.png" -o -name "preview_*.svg" -o -name "preview_*.png" \) -print0 2>/dev/null \
    | while IFS= read -r -d '' artifact; do
        local iteration
        iteration="$(basename "$(dirname "$artifact")")"
        cp "$artifact" "$out_dir/${iteration}-$(basename "$artifact")"
      done
}

extract_run_id() {
  node -e 'const fs=require("fs"); const p=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); process.stdout.write(p.run_id || p.result?.run_id || "");' "$1"
}

run_fixture() {
  local name="$1"
  local prompt run_id output_json run_dir out_dir
  prompt="$(fixture_prompt "$name")"
  out_dir="$FIXTURE_ROOT/$name"
  output_json="$out_dir/cli-output.json"
  mkdir -p "$out_dir" "$FIXTURE_TRACE_DIR"
  echo "Running fixture: $name"
  echo "$prompt" > "$out_dir/prompt.txt"
  LUMEN_AGENT_TRACE_DIR="$FIXTURE_TRACE_DIR" \
  LUMEN_AGENT_MAX_ITERATIONS="$AGENT_MAX_ITERATIONS" \
  PYTHONPATH=apps/api:apps/agent_runtime \
    "$VENV_PYTHON" -m lumen_deepagent.cli --mode "$AGENT_MODE" "$prompt" \
    | tee "$output_json"
  run_id="$(extract_run_id "$output_json")"
  if [[ -z "$run_id" ]]; then
    echo "could not extract run_id from $output_json" >&2
    exit 1
  fi
  run_dir="$FIXTURE_TRACE_DIR/$run_id"
  if [[ ! -d "$run_dir" ]]; then
    echo "missing run trace directory: $run_dir" >&2
    exit 1
  fi
  copy_run_artifacts "$run_dir" "$out_dir"
  {
    echo "{"
    echo "  \"fixture\": \"$name\","
    echo "  \"run_id\": \"$run_id\","
    echo "  \"trace_dir\": \"$run_dir\","
    echo "  \"git_head\": \"$(git_head)\","
    echo "  \"wasm_sha256\": \"$(wasm_hash)\","
    echo "  \"agent_mode\": \"$AGENT_MODE\","
    echo "  \"max_iterations\": $AGENT_MAX_ITERATIONS"
    echo "}"
  } > "$out_dir/manifest.json"
  echo "Archived fixture outputs in $out_dir"
}

run_fixtures() {
  cd "$ROOT_DIR"
  need_file "$VENV_PYTHON"
  load_env
  verify_local
  run_fixture linkedin-square
  run_fixture a4-appointment-card
  run_fixture landscape-flyer-card
  echo
  echo "Fixture archive complete: $FIXTURE_ROOT"
}

case "${1:-}" in
  prepare)
    prepare
    ;;
  verify-local)
    verify_local
    ;;
  doctor)
    doctor
    ;;
  clean-runtime)
    clean_runtime
    ;;
  backend)
    backend
    ;;
  frontend)
    frontend
    ;;
  check-served)
    check_served
    ;;
  browser-reset)
    browser_reset
    ;;
  run-fixtures)
    run_fixtures
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "unknown command: $1" >&2
    usage >&2
    exit 2
    ;;
esac
