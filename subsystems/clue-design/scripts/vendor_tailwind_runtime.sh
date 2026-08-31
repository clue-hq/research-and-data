#!/usr/bin/env bash
# G7: vendor the Tailwind v4 BROWSER runtime into the editor's public assets so
# it is served at /vendor/tailwind-browser.js — the URL every shell passes to
# `GET /documents/{id}/web/render` as `runtime_src`, and the first entry in the
# agent runtime's own search path (`lumen_agent.tools.web_substrate
# .tailwind_runtime_path`, which inlines the file for preview screenshots).
#
# Why this script exists: an editor-mode render carries the theme as a
# `<style type="text/tailwindcss">` block and NO utility rules, so this runtime
# is what compiles every layout class the agent authors. Until now nothing in
# this repo produced the file — it survived only as a hand-copied artifact in
# one working tree, and every fresh checkout rendered pages with no layout.
#
# Best-effort, like copy_canvaskit_assets.sh: a missing install warns and exits
# 0 (the agent runtime falls back to the package path directly), so `npm run
# dev` is never blocked by it.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The package's dist bundle IS the browser runtime (a single IIFE, ~282KB).
SRC="$ROOT_DIR/apps/editor/node_modules/@tailwindcss/browser/dist/index.global.js"
OUT_DIR="$ROOT_DIR/apps/editor/public/vendor"

if [[ ! -f "$SRC" ]]; then
  echo "WARNING: @tailwindcss/browser not installed ($SRC missing); rendered pages will have NO layout utilities." >&2
  exit 0
fi
mkdir -p "$OUT_DIR"
cp "$SRC" "$OUT_DIR/tailwind-browser.js"
echo "copied tailwind-browser.js to public/vendor/ ($(wc -c < "$OUT_DIR/tailwind-browser.js" | tr -d ' ') bytes)"
