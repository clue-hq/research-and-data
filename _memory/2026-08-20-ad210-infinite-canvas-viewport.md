# 2026-08-20 — AD2.10: the ad editor's stage is an infinite canvas; the artboard is the only tile

Branch `integration/frontend-design-part-iv-v4`. Task brief + full evidence:
`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/task-ad2.10-report.md`.
Predecessor: `_memory/2026-08-20-ad2-close-out.md` (AD2's read path, which shipped Ruling 17).

## The ruling

Founder, 2026-08-20: the artboard must not be restricted to the dummy's `.imageCanvas` area.
"Like how in Figma there's an infinite canvas in the background, and on top of that there's a
page on which you do your designs. Our case should be exactly that, nothing more and nothing
less." Plus: the artboard carries a subtle shadow so it reads as a physical tile.

**This retires Ruling 17** (AD2.3's fit margin 0, "the card IS the artboard"). Ruling 17 made
exactly one zoom level look right; above the fit the ad was drawn larger than the card's
~638px surface and silently clipped with no pan, below it the leftover card read as padding,
and the card's `aspect-ratio: 1` made any non-square page wrong even at fit.

## What is true now

- The `<canvas>` is the whole neutral output stage (`.sceneOutputStage`, no padding, no
  centring, no scroll). `.imageCanvas` keeps ONE role: the designed empty state.
- The workspace clears to `--bg-canvas` = **`#f5f5f5`**, the design subsystem's own token
  value (`subsystems/clue-design/apps/editor/src/app/tokens.css`). The platform defines no
  such property, so `scene-artifact-canvas.module.css`'s `.stage` defines it and the draw loop
  reads it back off the canvas element — CSS and painted pixels are one value. Deliberately
  NOT `--clue-ds-color-bg-page` (#F8F9FB): indistinguishable from a white page.
- The artboard's chrome is `drawArtboard`, ported in structure from the source stage (shell
  behind → content clipped to the page box → border on top) with the shell re-valued as a real
  blurred drop shadow (`MaskFilter.MakeBlur`, `rgba(15,23,42,.16)`, sigma 16, +4px) and the
  border keeping the retired card's hairline (`#E6E9ED`). Both are **screen-constant**:
  `artboardChromeGeometry(rect, zoom)` divides every px constant by the zoom, because chrome
  painted inside the viewport transform would otherwise scale with content.
- Fit-on-open is a contain-fit **to the stage** inset by `ARTBOARD_FIT_MARGIN = 64` (32px per
  edge). AD2.8's `{applied, fit, fitLabel}` model is intact.
- Pan and pointer-anchored wheel-zoom are ported from the source canvas
  (`CanvasKitCanvas.tsx` `onWheel` / hand-drag): plain wheel pans (trackpad two-finger),
  ⌘/Ctrl+wheel zooms ±0.08 at the pointer, space-drag and middle-drag pan, a plain press still
  selects (AD2.5 untouched). Engine clamp `[0.1, 2.0]` intact; pan clamped to keep ≥96px of
  the artboard on screen.
- The header's zoom control gained a THIRD, display-only value (`onGestureZoom` → the
  session's `gesture`), outranking the chosen step and the fit, because after a pinch neither
  of those is where the viewport is. It uses `formatZoomPercent` (whole percent, engine clamp)
  rather than the menu's `snapZoomPercent` (5% steps, 10–150% clamp), so 172% reports as
  "172%", not "150%". It never feeds back into the canvas's `zoom` prop.

## Traps worth remembering

1. **React's `onWheel` is passive.** React registers wheel at the root as a passive listener,
   so `preventDefault` inside a React handler is a no-op — the source editor's own handler has
   this latent. A native `addEventListener("wheel", …, {passive:false})` is required, or
   ⌘+wheel zooms the browser page over the canvas.
2. **Two wheel events in one frame collapse.** A props-ref read inside a handler is stale
   until the next commit, so a synchronous burst discarded all but the last step (found in the
   browser: six pans moved one step). The functional `setState(live => …)` form is the fix;
   the ref now carries only the DERIVED base viewport.
3. **`deltaMode === 1`** (Firefox + mouse wheel) is in LINES; ×16 or a notch pans 3px.
4. **The gesture-viewport reset must not key on the artboard or the stage size** — a relayout
   or a panel toggle would yank a panned workspace back to centre. It keys on `(pageId, zoom)`
   and is done with React's render-time adjust-state pattern (the repo lints `setState` in an
   effect, and an effect would paint one stale frame anyway).

## Verified

`npm run design-system:build && npm test && npm run lint && npm run build` — 1414/1414 tests
(the adapter file 35 → 49), lint 0 errors / 3 pre-existing warnings, build green. No Python
source touched. Browser-proven end to end on both the artifact route and the chat route with
`data-scene-engine="wasm"`; screenshots `/tmp/ad210-*.png` (listed in the task report).

## Left behind

- `doc_ad210storyportrait00000000001` — a real 1080×1920 Story ad in the dev DB (workspace
  `ws_8040…`, project `prj_79aa…`), created through the engine by
  `.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/seed_ad210_story_doc.py`
  (imports the AD2.2 seeder; deterministic ids; re-run is a no-op). It exists because both
  pre-existing dev ad documents are square, so nothing else could prove a non-square page.

## Open (small)

- Re-picking the zoom step you are already on does not re-centre (the override is a string, so
  the prop does not change). Every other route back to centre works. A nonce would close it.
- The wheel-zoom step is the source's linear ±0.08 per event; on a trackpad pinch that is
  fast. One constant in `sceneWheelViewport` if the founder wants it re-tuned.
- Space is `preventDefault`ed document-wide while an ad canvas is mounted (outside form
  fields/contenteditable) so the shell cannot page-scroll under a pan.
- §1.1's artifact-name label and W×H chip still do not exist — Gate G-A's sheet owns them, and
  nothing here fakes them.
