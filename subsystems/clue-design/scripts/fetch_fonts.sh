#!/usr/bin/env bash
# Wave 3 C4: fetch the variable Inter TTF the CanvasKit canvas renders + measures
# with (the same family the server uses). OFL-licensed. woff2 is NOT loadable by
# CanvasKit's FontMgr, so we ship TTF. Best-effort: a missing font degrades text
# to the CanvasKit default face, not a hard failure.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/apps/editor/public/fonts"
DEST="$OUT_DIR/InterVariable.ttf"
INTER_VERSION="v4.1"

if [[ -f "$DEST" ]]; then
  exit 0
fi
mkdir -p "$OUT_DIR"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if ! curl -fsSL -o "$tmp/inter.zip" "https://github.com/rsms/inter/releases/download/${INTER_VERSION}/Inter-${INTER_VERSION#v}.zip"; then
  echo "WARNING: could not fetch Inter ${INTER_VERSION}; CanvasKit text uses its default face." >&2
  exit 0
fi
unzip -o -j "$tmp/inter.zip" "InterVariable.ttf" -d "$OUT_DIR" >/dev/null
echo "fetched InterVariable.ttf ($(du -h "$DEST" | cut -f1))"
