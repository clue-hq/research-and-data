# 2026-08-24 — rich text editing (A→B→C) SHIPPED on the scene editor; live walk pending

Plan: `docs/superpowers/plans/2026-08-24-rich-text-editing.md` (design + rulings + residuals).
Founder scope directive (debug-slow-runs conversation): **C is the destination, ship A→B→C**.
Regime: Opus explores/implements/reviews per lane rule, Fable orchestrates + reviews round 2.
Review detail: `_memory/2026-08-24-rich-text-review-fixes.md`.

## Commits (all local on `integration/frontend-design-part-iv-v8`, base `887c08d82`; NOT pushed)

- `80ca6fb93` plan doc.
- `c9f4d8a96` **rung A** — "Text" content row in the ad text inspector (`InspectorTextArea`,
  ⌘/Ctrl+Enter commit / Enter=newline; `case "content"` → `updateTextNode`).
- `963078d6c` **rung B** — double-click inline editing (upstream `TextEditOverlay` port; session
  interlocks; paint suppression via descriptor override; §1.9/§7 dated supersessions).
- `003492f84` **rung C core** — `engine/scene/textSpans.ts`: UTF-16↔UTF-8 offset mapping,
  five-rule pre-validation (engine validates only at layout — LUMV0906), span algebra
  (split/merge/normalize), tracked + diff reconciliation, D4-edge re-authoring.
- `098f243ce` **rung C UI** — `SceneTextToolbar` (B/I/U/S + solid/token color) over the overlay's
  native selection; per-action undo frames; inspector content edits remap spans; wasm-artifact
  D4/round-trip proofs (`wasmTextSpans.artifact.test.ts`).
- `75a258357` review fix wave 1 (P1 D4 raw-vector guard + chained-commit wasm regression; session
  dirty/refusal honesty; C-9 prose corrections; restatement fallback).
- `906ed33a1` review fix wave 2 (split `contentDirty`/`spansDirty`; reseed selection reset;
  token-ref weight guard; residuals recorded).

## Verification

Frontend suite 2016 → **2234 pass / 0 fail / 0 skipped** at every step's close; lint 0 errors
(2 known `canvasOperations.ts` warnings); `design-system:build` + `build` green throughout.
Wasm-artifact suites RUN (artifact vendored from the colombo workspace; preflight stamp
`7810bea23027` verified). Backend untouched; root `make check` not re-run (no non-frontend files
changed by the code commits). Adversarial review round 1 (fresh Opus, P1 reproduced against the
real wasm) + scoped round 2 (fresh Opus) + Fable review of the round-2 diff.

## Load-bearing engine facts (verified this session)

- `TextSpan` offsets are UTF-8 bytes into the STORED content; five validity rules enforced only
  at LAYOUT — the frontend pre-validates (`spanValidationIssues`) because an invalid vector
  applies clean and silently drops the node from measurement.
- Engine D4 clears spans when content changes and the spans vector is RAW byte-identical
  (`operations.rs:620-631`) — `spansVectorForContentEdit` must compare RAW stored vectors
  (normalized comparison was the P1) and re-author structurally when needed (split; else no-op
  channel restatement; else accept the clear).
- `updateTextNode` whole-kind spread carries stale spans forward; the engine backstops (D4), the
  session/inspector paths remap instead.

## Residuals / founder-visible (full list in the plan doc)

1. **T5 live browser walk NOT run** — no dev stack was up in this workspace (all service ports
   closed). The three rungs are proven by 2234 tests incl. real-wasm proofs, not pixels. Walk the
   seeded ad (double-click → type → Escape/commit → select range → Bold/recolor → undo chain →
   agent-turn interleave) on a live stack before calling the lane closed.
2. C-9 freeze fires on the double-click's first press (ratified freeze-on-press, prose corrected;
   option to defer to drag-threshold needs a ruling).
3. Commit-refusal keeps the typed draft (differs from inspector revert-on-refusal; disclosed).
4. Restatement fallback: exhaustible on unsplittable spans (5th suffix edit clears); restated
   overrides are durable (stop following later node-base changes).
5. Silent refusal paths (`use-scene-manual-edits` not-armed/D9) leave a session with no stated
   reason — needs a shared write-path message decision.
6. Toolbar reuses web-toolbar visual language; collapsed-caret toggles disabled; no ⇧⌘X chord.
7. Selection surface is the overlay textarea (not WYSIWYG mid-session); contentEditable/CanvasKit
   upgrade path recorded in the plan.
8. Design-subsystem's own editor copies untouched (its own lane, per standing practice).
