#!/usr/bin/env bash
# Provision the editor's public Inter fonts. Two independent legs:
#   1. The FOUR STATIC faces the server embeds (repo fonts/ = the
#      cross-runtime parity contract) — the CanvasKit canvas registers these
#      same bytes so weight selection matches exports exactly. Copied, never
#      fetched: the repo is the source of truth.
#   2. The variable Inter TTF for the DOM @font-face (editor UI chrome only —
#      CanvasKit never applies the weight axis, so it is useless there).
# OFL-licensed. woff2 is NOT loadable by CanvasKit's FontMgr, so we ship TTF.
# Best-effort on the fetch leg: a missing variable font degrades UI chrome
# type, not canvas text.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/apps/editor/public/fonts"
DEST="$OUT_DIR/InterVariable.ttf"
INTER_VERSION="v4.1"

mkdir -p "$OUT_DIR"
for face in Inter-Regular Inter-SemiBold Inter-Bold Inter-ExtraBold; do
  if [[ ! -f "$OUT_DIR/$face.ttf" ]]; then
    cp "$ROOT_DIR/fonts/$face.ttf" "$OUT_DIR/$face.ttf"
    echo "copied $face.ttf from repo fonts/"
  fi
done

if [[ -f "$DEST" ]]; then
  exit 0
fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if ! curl -fsSL -o "$tmp/inter.zip" "https://github.com/rsms/inter/releases/download/${INTER_VERSION}/Inter-${INTER_VERSION#v}.zip"; then
  echo "WARNING: could not fetch Inter ${INTER_VERSION}; CanvasKit text uses its default face." >&2
  exit 0
fi
unzip -o -j "$tmp/inter.zip" "InterVariable.ttf" -d "$OUT_DIR" >/dev/null
echo "fetched InterVariable.ttf ($(du -h "$DEST" | cut -f1))"
