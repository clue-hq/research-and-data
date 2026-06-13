#!/usr/bin/env bash
# Wave 3 C0: copy the CanvasKit wasm into the editor's public assets so the
# browser can lazy-load it from /canvaskit/. The Next.js build never depends
# on the artifact existing — a missing module degrades the editor to the
# Konva renderer (Decision 7), so this is a best-effort copy.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT_DIR/apps/editor/node_modules/canvaskit-wasm/bin/canvaskit.wasm"
OUT_DIR="$ROOT_DIR/apps/editor/public/canvaskit"

if [[ ! -f "$SRC" ]]; then
  echo "WARNING: canvaskit-wasm not installed ($SRC missing); the CanvasKit canvas will be unavailable." >&2
  exit 0
fi
mkdir -p "$OUT_DIR"
cp "$SRC" "$OUT_DIR/canvaskit.wasm"
GZ_BYTES=$(gzip -9 -c "$OUT_DIR/canvaskit.wasm" | wc -c | tr -d ' ')
echo "copied canvaskit.wasm to public/canvaskit/ (${GZ_BYTES} bytes gzipped)"
