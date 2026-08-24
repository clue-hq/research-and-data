# 2026-08-24 — rich-text (scene editor) adversarial-review fix wave

Branch `integration/frontend-design-part-iv-v8`. Base `098f243c` (frontend suite 2203 pass / 0 fail /
0 skipped) → one commit on top. Plan: `docs/superpowers/plans/2026-08-24-rich-text-editing.md`
(amended in the same commit).

## What was fixed (F1–F7, all TDD: red test first)

- **F1 (P1, silent styling loss).** `spansVectorForContentEdit` compared the candidate against the
  NORMALIZED stored vector; the engine compares RAW (`operations.rs:620-631`). Because the split is
  deterministic, a SECOND suffix edit regenerated the stored split → raw-equal → engine cleared every
  span. Now compares raw (`stableKey(node.spans ?? [])`), and the split chooser skips a candidate that
  collides with the stored key. Signature collapsed to `(node: TextNode, content, nextSpans)` — the
  stored vector and "did content change?" are both derived from the node, so the two can no longer
  disagree. Pinned by a chained two-commit case against the REAL wasm
  (`wasmTextSpans.artifact.test.ts`), a chained pure case, and an inspector-path case.
- **F2 (P3-1, unsplittable vectors).** No interior char boundary anywhere (every span one character —
  a coloured "!") → the vector used to go out unchanged and die. Second fallback added: RESTATE a
  channel the span lacks at the node's own value (`underline` → `strikethrough` → `italic` → weight,
  the weight ONLY when the node has no `style_token`, because `resolvedTextFields` resolves a token's
  weight over the literal). Renders identically, raw-differs. The clear stands only for a
  single-character span already stating every channel (constructible; pinned as such).
- **F3 (P2, idle session reverts a concurrent write).** `TextEditSession` gained `dirty` (set by every
  typing transition and by `applyStyle`; never by the model). Clean session RE-SEEDS from the live
  model (`textEditSessionReseed`) and writes nothing (`textEditSessionOperations`). Dirty session keeps
  its draft across a model change — unchanged posture.
- **F4 (P2/P3-4, refusal discarded typed text).** `commitTextEdit` now writes BEFORE closing and closes
  only when the write landed or there was nothing to write (`textEditSessionEnds`); `settle` re-arms
  its latch and takes the caret back on refusal. A refused formatting commit reverts the working spans
  (`textEditSessionAfterStyleCommit`). Keep-the-draft deliberately differs from the inspector's
  revert-on-refusal (AD4.R) — recorded as founder-visible item 7.
- **F5 (P2, false C-9 prose).** The freeze DOES fire — on the double-click's first pointer-down, via
  `freezeLayoutForPress`, like any press on a freezable node. Behaviour untouched; both docstrings and
  the plan's standing constraint 4 rewritten (dated correction, old text struck not deleted).
  Founder-visible item 8 records the "defer the freeze to the drag threshold" option as needing a
  ruling.
- **F6 (P3-2).** `scene-apply.ts` `case "content"` now runs the same `spanValidationIssues` pre-send
  guard the session path calls load-bearing (throw in dev/test, drop the spans channel in production).
- **F7 (P3-3 + P3-5).** The "⌘Z takes them back one at a time" comment was false inside a session
  (document undo skips typing targets) — corrected. P3-5 (a no-op content commit could mint a version
  carrying normalized spans; unreachable via `fieldCommit`) recorded as a code comment, not fixed.

## Gates

`npm test` 2225 pass / 0 fail / 0 skipped (2203 + 22; the wasm artifact suites RUN, 6 cases).
`npm run design-system:build && npm run lint && npm run build` — 0 errors, the 2 known
`canvasOperations.ts` unused-var warnings only.

## Residuals / notes for the next session

- F4's component plumbing (settle latch, refocus-on-refusal) is React and therefore not unit-tested;
  its RULES are pure and pinned (`textEditSessionEnds` / `textEditSessionAfterStyleCommit`).
- The review cited `scene-artifact-canvas.tsx:281-285` for the false C-9 claim; at `098f243c` those
  lines are the props interface. The real claim was the `handleDoubleClick` docstring (~1434) — that
  is what was corrected.
- Refocus-on-refusal is best-effort (`element.focus()` inside a blur handler); the session stays open
  either way, so a lost focus fight costs nothing but a click.
- No browser walk was run for this wave (no live stack in this session).
