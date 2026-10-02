# 2026-09-04 — Plan 4 shipped: text bounds by painted lines, hug default, Fit to text; item G previewed

Plan: `docs/superpowers/plans/2026-09-04-text-bounds-and-inspector-typography.md` (roadmap Plan 4,
items F + G). Commits `1168774d4..fffb6d4ee` (Rust + frontend + agent prompts + rebuilt wasm). SDD
with Opus implementers; every diff reviewed and every test re-run first-hand by the controller. The
design API + fleet worker were restarted on the rebuilt release helper (engine stamp `32ce2d50a1ca`,
wasm handshake matched). Rulings R1–R8 are in the plan header.

## What changed
- **Engine (lumen-core):** `ComputedGeometry.text_lines: Vec<Rect>` — page-space painted line boxes,
  placed from `validate_text_nodes`' own `with_bounds` measurement by `painted_text_lines` (align
  factor 0/½/1 across the box's horizontal slack, `valign_offset` across the vertical; justify placed
  like left). Empty + unserialized for non-text nodes → existing JSON byte-identical. Text hit-tests
  inside any painted line (`TEXT_LINE_PICK_SLOP = 2`); a text node with no positive-area line keeps
  the box test. `ProvidedTextMeasurer` records may carry lines (`ProvidedMetrics`/`ProvidedLine`);
  the wasm payload gained `lines: [{x,y,width,height,baseline}]`.
- **R8 (found by the live proof):** `resolve_manual_size` — the path for page children, frame
  children and children of a frozen Stack — measured a text node's hug height with NO width bound, so
  a fixed-width wrapped headline hugged its unwrapped line count (Apollo: 2 lines hugged, 3 painted,
  box 142 under 213 of glyphs). Now `natural_height_at_width` measures at the resolved width
  (unbounded only when the width itself hugs); `measure_taffy_node` prefers the leaf's definite width
  (taffy already clamped, so that half is defensive). Server-side hug heights for wrapped text are
  corrected too — that is the point of "text height is hug".
- **DSL + prompts + skill:** an unsized text element lowers to `s(hug,hug)` (was 0×0 → LUMV0901);
  `_AUTHOR_TEACHING_BODY` and the LinkedIn ad skill's Type section say TEXT HEIGHT IS HUG
  (`test_prompts_text_height.py`).
- **Editor measurement bridge:** `skiaLineMeasurements` sends, per laid-out text node, records keyed
  on the solved box — `(max_width, max_height)` for the validate key and `(max_width)` for the
  hug-height key — carrying CanvasKit's line boxes measured LEFT-aligned at the box width;
  `injectSkiaMeasurements` re-runs the line pass until the solved sizes stop moving (≤4 rounds; the
  line records move hug boxes, so one round's validate key can name a height the next round
  replaces). `textMeasurementSignature` includes each text node's solved size.
- **Canvas:** a text selection (and Plan 3's hover) outlines the union of its painted lines; when the
  layout box differs by > 0.5 units on any edge a dashed frame marks the box and carries the resize
  handles + rotation pivot (`data-scene-selection-frame`). Gesture geometry stays the layout box.
- **Fit to text:** text inspector Layout section; one `fitToText` property-change event → height hug,
  width untouched; dead while the height already hugs.

## Live proof (colombo, Apollo ad `doc_cf05190c…`, evidence `/tmp/plan4-evidence-keep/`)
- Click in the empty half of the headline box → `left_col` (the wash behind it), not the headline.
- Click the "x" glyph → `node-b7b525c3`, outline 6.3×13.5 px on the glyph, dashed frame on its box.
- Hover over the headline → hover outline = the text union (184.5×95.7 px), not the 226×97 box.
- Select the headline → solid union outline + dashed 503×216 frame with handles
  (`03-headline-selected.png`).
- Fit to text → document v271 → v272, height hug, button disabled. BEFORE R8 the hugged box came out
  142 units tall under 213 of glyphs (2 vs 3 lines); AFTER R8 (rebuilt engine, reloaded) the box
  height equals the painted height (95.7 px both) — the frame remains only for the fixed width's slack.

## Gates
- `cargo test --workspace`: 72 targets / 1116 tests green with goldens + visual baselines generated
  from the pre-plan commit `4fcebc432` in a temp worktree (so the raster comparison is before/after,
  not self-generated); re-run after R8: green, no golden drift. Release helper rebuilt; wasm rebuilt
  (`build:wasm` + `copy-design-vendor.mjs`, vendor copy identical); design editor vitest 691/691.
- Frontend `npm test` 2699 pass (1 pre-existing jsdom skip), lint clean. Agent-runtime pytest exit 0.
- API pytest against throwaway `clue_plan1_test`: 29 failures, all in lanes Plan 4 never touched
  (custom-component compiler/publish/runtime worker, live image-provider calls in `test_api` W14/W17,
  agent-runtime web turns, ad-assets onboarding job timing, ingestion grammar-audit timing). The same
  ten files run on the pre-plan base commit `4fcebc432` fail identically (28 vs 29 ids, the delta being
  two timing-flaky ingestion tests and one onboarding test that also fails on base when re-run
  twice). Pre-existing environment failures, not Plan 4's; recorded rather than weakened.

## Operational findings (not Plan 4's to fix)
- `cargo fmt --all` reformats 73 pre-existing files across 8 crates — never run it; format only new
  hunks (`rustfmt --check <file>`), stage by explicit path.
- The lumen-skia goldens and lumen-core visual baselines are deliberately untracked (`0f63d3080`) and
  `cargo test --workspace` cannot even compile `lumen-core/tests/visual_regression.rs` in a fresh
  worktree until `UPDATE_SKIA_GOLDENS=1 … raster_golden` / `UPDATE_LUMEN_VISUAL_BASELINES=1 …
  visual_regression` have written them. Generate them from the BASE commit in a temp worktree
  (`git worktree add /tmp/x <base>`, same `CARGO_TARGET_DIR`) so the gate proves no drift.
- The frontend's `pretest`/`predev` hook rebuilds the wasm on engine-source drift and leaves the
  tracked `apps/editor/public/wasm/lumen_wasm_bg.wasm` modified; commit it deliberately at the end.

## Open
- **Item G** — founder reviewed the preview 2026-09-04: the line-height and letter-spacing icons are
  approved; the duplicate Vertical alignment row is DROPPED (it already ships); Line height and Letter
  spacing sit two-up in one row like Max lines + Wrap (preview revised, `10-item-g-preview-v2.png`).
  Still open before controls land: lucide as the source for `rows-3`/`wrap-text`, the 0.05 stepper as
  new chrome, and whether Resize belongs beside Fit to text.
- Documents authored before R8 keep their stored geometry until the next layout pass; the editor
  relays out on load, so they display correctly now — nothing to migrate.
- The `x` node's box (11.8×37) is narrower than its painted glyph line (14×30): the dashed frame
  reads as a hair inside the outline; correct per R5, worth a glance if it looks noisy at 100%.
- Test-DB hygiene ruling still open (API suite ran on `clue_plan1_test`).
