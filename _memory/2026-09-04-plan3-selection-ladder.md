# 2026-09-04 — Plan 3 shipped: the selection ladder (button-first click, walk-up, hover outline)

**SUPERSEDED the same day by selection model v2** (`2026-09-04-selection-model-v2.md`): the founder
found the ladder impractical — the button-as-unit click left the label unreachable and unmovable, and
the second-click walk-up collided with double-click. Kept: hover outline, Alt-click/Escape walk-up,
the button shape rule. Removed: second-click walk-up + slop, the button double-click caret shortcut.

Plan: `docs/superpowers/plans/2026-09-04-selection-ladder.md` (roadmap Plan 3, item E). Commits
`843747f55..cb9f4ab89`, frontend only, engine untouched. SDD with Opus implementers; every diff
reviewed and every test re-run first-hand by the controller. The Next dev server hot-reloads.

## What changed
- `adapter/scene-selection-ladder.ts` (new, pure): `isButtonShaped`/`buttonLabelId` (R1: an
  `auto_layout` whose only present child is text), `selectionLadderHit` (representableHit, promoted
  to the button when the hit is its label), `selectionWalkUp` (R2: nearest representable ancestor,
  null from the root frame), `sceneHoverTarget` (never the selected node), `escapeSelectionEffect`
  (live gesture → reset; caret → none; else walk up, null at the root = clear),
  `selectionBreadcrumb` (root-first ancestry with display names), `WALK_UP_CLICK_SLOP_PX = 4`.
- `sceneDoubleClickEffect`: a button resolves to its label before the text rule (lock first, then
  the run gate). A button therefore no longer "drills out" on double-click; ancestors come from the
  walk-up gestures or the Layers section.
- `scene-artifact-canvas.tsx`: pointer-down and double-click use `selectionLadderHit`; Alt-click
  walks up from the hit without starting a press; a click on the already-selected node walks up on
  release when it travelled < 4 px and drew no drag preview; the Escape listener runs
  `escapeSelectionEffect` (context via a ref written in a no-deps effect — the React Compiler
  refuses ref writes in render and ref reads in JSX); pointer-move while idle hit-tests for a hover
  target (only a CHANGE reaches state; cleared on press, pan start, leave, Escape); the hover
  outline is `SelectionChrome variant="hover"` (`HOVER_OUTLINE_WIDTH = 1`, `HOVER_OUTLINE_OPACITY =
  0.55`, `data-scene-hover-outline`, drawn under the selection chrome, hidden during caret/preview/pan).

## Live proof (colombo, synthetic pointer events read back through the chrome attributes)
- Apollo ad `doc_cf05190c…`: Alt-click on the headline → `left_col`; second click → parent; Escape
  chain `split → card → artboard → cleared`; hover over the product image → `product`. The CTA
  itself resolved to `split`: `left_col` (clip, y 83–979) ends above `cta_btn` (y 958–1034), so the
  ENGINE's hit stack never contains the button — the roadmap's authoring-overflow note, Plan 4's
  domain (layout-box hit-testing), not Plan 3's.
- Brex ad `doc_f8668063…` (`cta_plate` = auto_layout with only `cta_label`, inside `footer`): hover
  → `cta_plate`; one click → `cta_plate` (inspector "auto_layout cta_plate"); double-click → caret
  on `cta_label` ("See how"); Escape closes the caret; click + second click → `footer`; hover over
  the headline → `headline`. Evidence: `/tmp/plan3-evidence-keep/`.
- The feared double-click/walk-up interaction did not occur (the caret opened on the label), so
  no `detail === 1` guard was added.

## Founder ruling 2026-09-04: NO inspector breadcrumb
The founder looked at the preview and declined it ("I don't think we need it really"): the Layers
section already shows the ancestry and selects on click, and the ladder gestures walk up without
UI. `selectionBreadcrumb` was removed with its test (no consumer); the roadmap's item E is
amended. Rule of thumb confirmed: no second navigation surface for something Layers already does.

## Founder request 2026-09-04: Layers tree "capped at depth 2" → indent by real depth
Not a data cap: `sceneLayerRows` walks any depth and expansion is seeded root + selection
ancestors (the rest is the user's toggles). The CSS `.layerRowNested` gave every nested row a flat
`padding-left: 16px` and never read the `--layer-depth` variable `InspectorLayerRow` sets, so depth
2+ rendered at the depth-1 indent and the tree looked two levels deep. Fix: `padding-left:
calc(var(--layer-depth) * 16px)`. Live-verified on the Apollo ad: depths 1–5 now render at
16/32/48/64/80 px (artboard › card › split › left_col › quote_row › ramp_logo). Labels still clip
(row `overflow: hidden`, no ellipsis) — fine at the depths an ad reaches.
