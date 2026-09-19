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

---

## T5 LIVE WALK COMPLETE (2026-08-24, same day) — feature browser-proven

Residual #1 above is CLOSED. A medan-local dev stack was stood up (user-directed):
DB `clue-pg-medan` :55230 (pg_dump clone of the shared dev DB at istanbul:55040, head
`db145059253b`, seeded ads included), `clue-redis-medan` :6381, blob root `medan/.artifacts`
(merged colombo/.artifacts + /tmp/lumen-dev-storage), platform API :8020, design API :8065
(embedded design fleet worker), platform fleet worker, frontend :3020. Launch scripts:
`.context/stack/launch-*.sh`; env in root `.env` (medan-notes block documents every choice)
+ `apps/frontend/.env.local` (added `LUMEN_API_BASE_URL`).

**Walk verdict (Opus browser agent, real stack, seeded ad `doc_ad22linkedinsquare00000000001`):**
all 10 steps PASS functionally — rung A commit +1 version; rung B overlay open/Escape-cancel/
⌘Enter-commit; rung C Bold + recolor as own undo frames with live selection; typing inside a
styled range grew the span exactly (4..9 → 4..11); 5 undos restored byte-identical baseline;
zero app console errors. Bold on the 700-base headline correctly toggled OFF to 400 (override
semantics, not a bug).

**Three presentation defects found by the walk, fixed at `0f756feb9`, re-verified live:**
1. D1 overlay white-on-white (upstream's genuine `background:#ffffff` — deliberate divergence
   to `transparent`; artboard shows through where the node's glyphs are suppressed).
2. D2 serif fallback (scene says "Inter", DOM registers "Inter Variable" — overlay now emits a
   `"<family>", "<family> Variable", sans-serif` stack via pure `domFontFamilyStack`); wrap
   parity with the painted canvas is now line-identical.
3. D3 toolbar under the banner layer (z 30 vs 40) and placed into the banner band for
   top-of-artboard nodes — overlay/toolbar z → 41/42 AND `sceneTextToolbarPosition` takes a
   measured `stage.topInset`, flipping BELOW the node when above would clip. Proven with a
   real actionability-checked mouse click on Bold (696→697→698), where the pre-fix walk's
   identical click hit the banner span.

Suite at close: **2246 pass / 0 fail / 0 skipped**. Commits added since the first close-out:
`0f756feb9` (D1–D3 fixes). Doc restored: v698, content byte-identical, `spans: []`.

## Stack/env traps for the next session (hard-won)

- `next dev --hostname localhost` binds IPv6-ONLY on this box — curl passes (::1 fallback),
  Chrome fails (ERR_CONNECTION_REFUSED). Always `--hostname 0.0.0.0` (launch script has it).
- The design API's engine stamp comes from the `lumen-api-helper` BINARY (`build_info` action);
  a helper copied from another workspace can mismatch the vendored wasm → "Canvas editing is
  disabled" banner. Rebuild `cargo build --release -p lumen-api-helper` from THIS tree (~90s).
- gstack browse: `$B url` is read-only (silently ignores an argument) — navigate with `goto`.
- Clone auth: the walk's Clerk account mapped to platform user `usr_4580df…` with NO membership;
  inserted `mem_medanwalk4580df2026082401` (owner, Insight Health) into the CLONE only.
- Pre-existing, unrelated: `asset-store/2b0928ca…` 404 (likely the sohne-var face the brand-font
  banner reports); the /accounts page shows a version-support error in this clone.
