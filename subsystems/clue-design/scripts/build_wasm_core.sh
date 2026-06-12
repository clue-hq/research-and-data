#!/usr/bin/env bash
# Build the browser WASM core (crates/lumen-wasm) into the editor's public
# assets and enforce the Track E bundle budget (<3MB gzipped).
#
# Usage:
#   ./scripts/build_wasm_core.sh                # build + size check
#   ./scripts/build_wasm_core.sh --check        # size check only (artifact must exist)
#   ./scripts/build_wasm_core.sh --if-missing   # build only when the artifact is absent;
#                                               # warn-and-skip when the toolchain is missing
#
# The editor loads the module at runtime from /wasm/, so the Next.js build
# never depends on this artifact existing; missing/failed loads degrade the
# editor to server-only mode (Track E Decision 4/5).
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/apps/editor/public/wasm"
WASM_PACK="${WASM_PACK:-$ROOT_DIR/apps/editor/node_modules/.bin/wasm-pack}"
ARTIFACT="$OUT_DIR/lumen_wasm_bg.wasm"
BUDGET_BYTES=$((3 * 1024 * 1024))

if [[ "${1:-}" == "--if-missing" ]]; then
  if [[ -f "$ARTIFACT" ]]; then
    exit 0
  fi
  if [[ ! -x "$WASM_PACK" ]] || ! command -v cargo >/dev/null 2>&1; then
    echo "WARNING: wasm artifact missing and the build toolchain is unavailable;" >&2
    echo "         wasm-engine test suites will skip. Run: npm run build:wasm" >&2
    exit 0
  fi
  echo "wasm artifact missing — building lumen-wasm (first build takes a few minutes)"
  set -- # fall through to a full build
fi

if [[ "${1:-}" != "--check" ]]; then
  if [[ ! -x "$WASM_PACK" ]]; then
    echo "wasm-pack not found at $WASM_PACK (run: npm --prefix apps/editor install)" >&2
    exit 1
  fi
  "$WASM_PACK" build "$ROOT_DIR/crates/lumen-wasm" \
    --target web \
    --release \
    --out-dir "$OUT_DIR" \
    --out-name lumen_wasm
fi

if [[ ! -f "$ARTIFACT" ]]; then
  echo "missing artifact: $ARTIFACT" >&2
  exit 1
fi

RAW_BYTES=$(wc -c <"$ARTIFACT" | tr -d ' ')
GZ_BYTES=$(gzip -9 -c "$ARTIFACT" | wc -c | tr -d ' ')
echo "lumen_wasm_bg.wasm: ${RAW_BYTES} bytes raw, ${GZ_BYTES} bytes gzipped (budget ${BUDGET_BYTES})"

if (( GZ_BYTES >= BUDGET_BYTES )); then
  echo "FAIL: gzipped wasm bundle exceeds the 3MB budget" >&2
  exit 1
fi
echo "OK: wasm bundle within budget"
