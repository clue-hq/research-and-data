# 2026-09-01 — rich-text scene editing merged into this line; WYSIWYG upgrade scoped (deferred)

Session context: colombo workspace, founder testing the scene-ad editor end-to-end on the
colombo stack (frontend :3033, platform API :8052, design API :8060, own fleet worker,
DB `clue_colombo` @ :55040 — recipe in `_memory/2026-08-27-demo-night-setup.md`; istanbul's
parallel stack on 3020/8010/8020/8030 must never be touched). Apollo test login:
`apollo+clerk_test@example.com` / OTP 424242 → `ws_8163898e0d0e4420b578bdbc57d7f3e4`.

## What happened

1. **Merged `origin/integration/design-improvement`** into this branch (`3646efef5`, 60 commits:
   document thumbnails, ABM page fragments, agent-runtime skills, env-first agent model
   selection, alembic head join). `clue_colombo` migrated to head `6eff96862040`.
2. **Founder hit "no rich-text editing" in the scene editor.** Root cause (systematic-debugging
   walk): the entire scene rich-text feature — 10 commits (plan `80ca6fb93` … D1–D3 fixes
   `0f756feb9`) — lived ONLY on `integration/frontend-design-part-iv-v8`, forked at `887c08d82`
   and never merged back; this line had moved 426 commits since without it. Not a bug/flag —
   the code was absent from the build.
3. **Merged `origin/integration/frontend-design-part-iv-v8`** → `37044c6e7`. Clean (predicted
   by `git merge-tree` dry-run; 35 files, ~7.4k insertions, all design-editor + docs; no wasm
   or design-system rebuild needed). Frontend restarted (kill by PID after cwd check, rm .next),
   verified live in-browser: inspector "Text content" row, double-click inline session, B/I/U/S/A
   range toolbar on the Cursor ad. Session exited with Escape — document untouched.

## Residuals (from `_memory/2026-08-24-rich-text-editing-close-out.md`; #1 T5 walk CLOSED)

Open: C-9 freeze-on-first-press (drag-threshold deferral needs ruling); commit-refusal keeps
draft (inspector reverts — inconsistent, disclosed); silent refusal paths (not-armed/D9 — no
stated reason, shared write-path message decision pending); restatement fallback exhaustible on
unsplittable spans + restated overrides stop following node-base changes; minimal toolbar (no
⇧⌘X, collapsed-caret toggles disabled); mid-session not WYSIWYG; design-subsystem's own editor
copy untouched. Expected-not-a-bug: Bold on a 700-base toggles OFF to 400 (override semantics).

## Mid-session WYSIWYG — founder confirmed it as a real UX issue; scoped, then DEFERRED

Mechanism verified in code: formatting actions DO commit immediately (own undo frames, toolbar
state live) but `scene-artifact-canvas.tsx` rung-B rule suppresses ALL glyph painting for the
node under an open caret, and the overlay is a plain `<textarea>` — so applied styling is
physically invisible until the session closes. (A doc comment in that file saying styling
"appears on the canvas immediately" refers to document state, not visible pixels — do not be
misled by it.)

**Key architecture discount discovered:** the frontend ALREADY builds CanvasKit Paragraphs for
all text painting — `engine/scene/canvaskit/drawDescriptors.ts` (incl. segmented span painting
A6b D7 ~line 303), `fontFaces.ts` font provider, `paragraphLayoutMetrics`, and `textSpans.ts`
UTF-16↔UTF-8 mapping. Both upgrade options swap ONLY the input surface; session state machine,
span algebra, toolbar, undo frames all survive unchanged.

- **Option 2 — contentEditable overlay (~2–4 focused days, medium risk).** Render working spans
  as segment `<span>`s (live formatting free); DOM Selection↔flat-offset walk; the real 20% is
  mutation control — controlled-contentEditable re-render-from-state with a composition-mode
  carve-out (IME can't be preventDefault'd); existing beforeinput predict-then-verify + diff
  remap generalizes and remains the honest fallback. Still DOM-over-suppressed-canvas (D2 wrap
  parity class remains).
- **Option 3 — CanvasKit-native caret/selection (~2–3 weeks, open-ended IME tail; 3–6× opt 2).**
  Retained draft Paragraph + preview channel (copy the AD4.C gesture-preview substitution
  pattern); caret/selection via getGlyphPositionAtCoordinate/getRectsForRange through
  `sceneViewportModel` + new `gestureMachine` mode; hidden input for keys + IME composition
  PAINTED on canvas (the Figma-class money pit); overflow scrolling, bidi affinity, a11y mirror
  kept forever; validate canvaskit-wasm index units vs stored UTF-8 spans (graphemes/emoji).
  Payoff: pixel-identical WYSIWYG, kills the wrap-parity bug class permanently.

**Recommendation recorded: option 2 first (its hard part is prerequisite knowledge for 3's
hidden-input layer — nothing thrown away). Founder decision 2026-09-01: understood for future
scoping only; higher priorities now — NO work started.**
