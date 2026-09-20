# 2026-09-20 — Freeze-bake fill parity (SDD on `project-home`, Opus implementers, controller review)

## Why
The 2026-09-20 live walk of multi-artifact legs surfaced an engine residual under ruling C-9
(freeze-on-grab): clicking a pill on the Capital ad stretched every pill to the artboard edge.
Diagnosis (controller, first-hand): `baked_container_size` kept `fill` on containers (and its
whole-`SizeSpec` patch re-opened the `fill` the child bake had just closed); the Stack solve
builds nested children with `parent_size=None` (`layout.rs:313`) so a cross-axis `fill` solves as
hug, while Free mode resolved `fill` against the parent's OUTER box (1080 vs 976). Founder rulings:
C-9 stands; items 3 (defer to drag) and 4 (scope / tell the agent) NOT changed; fix items 1 and 2
for every exception; text hug WIDTH bakes, hug HEIGHT stays.

## What shipped (commits, in order)
- `865231700` T1 — `editing.rs`: `baked_container_size` bakes `Hug|Fill`; `bake_dimension_for_child`
  gains `BakeAxis` (text keeps hug HEIGHT only); nine new `freehand_ops` cases (fill container under
  padded parent, nested fill under indefinite parent, weighted fill row, main-axis fallback, wrapped
  hug-width text, fill×hug headline, stretch-aligned children, wrapping row, convert-of-one).
- `17245a3ee` T2 — `layout.rs`: a Free container hands children its padded content box for `fill`;
  origin stays outer-relative; two tests (content-box fill; a fill child added after a freeze
  matches the Stack width).
- `eda538d91` T3 — `scripts/design_prefreeze_scene.py` (read-only; walks every edit envelope's
  inverse backwards from the head to `--before-seq`; revision-chain guard) + the three ads as
  fixtures in `crates/lumen-core/fixtures/scenes/freeze/` and the frontend `__fixtures__/freeze/`.
- `bf180031f` T4 — `tests/freeze_real_ads.rs`: whole-document zero motion + byte-identical inverse
  + per-node invariants; with the T1 bake reverted it reproduces the live symptom (row_md 684→976).
- `4af30e225` T5 — `freezeMotionReport` in `adapter/scene-gestures.ts`, `console.error("[freeze] …")`
  at `freezeLayoutForPress`; the three ads pinned in `wasmEngine.artifact.test.ts` (red on the old
  wasm: `row_dac.width 753 -> 1080`). `afc111019` — vendored wasm rebuilt (3168678 B raw, 985521 B
  gzipped, budget 3 MB). Release helper rebuilt (`target/release/lumen-api-helper`, spawned per call).

## Verified first-hand
Every task's diff read; `freehand_ops` 29, `--lib` 26, `core_engine` 10, `conformance` 6,
`freeze_real_ads` 3, the wasm artifact file 23 and the gestures file re-run by the controller;
`npm test` 3206/3207 (1 pre-existing skip), lint, build green per the implementer; stack all UP.

## Residuals / deferred minors (ledger `.superpowers/sdd/2026-09-20-freeze-bake-fill-parity/progress.md`)
- Stack solve = taffy whole-pixel-rounded geometry; Free path = unrounded natural sizes → a
  hug-height text shifts ≤0.71 px on freeze (19 named nodes across the three ads get a 1.0 px
  height tolerance; everything else 1e-6); the freeze also REMOVES four LUMV0903 overflow
  diagnostics on the real ads (same residual, safe direction). A rounding fix is a separate item.
- The absolute-children invariant is vacuous on these ads (none pins a child).
- Two pre-existing rustfmt diffs in `tests/freehand_ops.rs`; the freeze diagnostic is console-only;
  `scripts/dev_stack.sh` `restart-api`/`restart-workers` hang in their trailing `sleep; status`.
- Founder rulings NOT taken (deliberately): freeze on press rather than at the drag threshold;
  document-wide freeze scope; no signal to the design agent that a document was frozen.

## Owed — founder-triggered
Live check on a NEW ad (generated after the helper rebuild): in Edit mode click a pill inside a
fill-width row — nothing moves or stretches; devtools shows no `[freeze]` error; undo restores
`fill` on the row. The three ads already frozen today stay frozen (their rows are baked at the
old wrong widths); regenerate or undo them.

Still queued behind this (founder's order): the multi-artifact batch turn failure
(`agent_model_call_sequence` collision in `_record_design_receipts`) and the stuck leg
`e1b29465…` on `thr_91f106db…`.

## Addendum — the handshake needs a design-API restart after a helper rebuild
`GET /build-info` on the design API is CACHED per process (`app.state.build_info`), so after
`cargo build -p lumen-api-helper --release` the still-running 8010 process reports the OLD engine
stamp and the editor disables canvas editing ("in-browser engine is a different build than the
API": editor bb1aaeea610a vs API 62c7de8b022e, seen 2026-09-20 17:37). The helper itself is
spawned per call, so engine calls were already new; only the cached stamp lagged. `restart-api`
restarts the PLATFORM APIs only — the design API is restarted by reproducing `up`'s design-API
command (done by hand 2026-09-20; stamp now bb1aaeea610a on both sides). Follow-up for the runbook:
a `restart-design-api` command.

## Addendum 2 — "every edit drops edit mode and reloads the chat" (frontend, fixed 2026-09-20)
Diagnosed first-hand from the recording + logs (zero stream frames; design API only applied ops):
a manual edit bumps the document version → the URL write-back's `router.replace` re-renders the
page → the server-fetched feed lists the active document as UPDATED → `artifactsToAutoOpen`
re-opened it → the shell's `open-artifact` reset `editing:false` + selection → write-back to
`?surface=ad` → `routeQuery` change → `replaceThreadInRoute` identity change → the thread-resolution
effect re-ran `loadThreads`/`loadConversation` (the "chat reopens"). Pre-dates this week's work
(open-on-update from `248ced412`, 2026-09-14). Two fixes, both pinned red→green:
- `artifactsToAutoOpen` takes `openArtifactIds` (the shell's open tabs) and skips an updated
  document whose tab is already open; a NEW document is never in that set, so births open as before.
- the shell reducer's `open-artifact` is a no-op when the artifact is already active on the
  artifact surface with the rail open (from the gallery or a closed rail it still brings it forward).
Deferred (separate change): the thread-resolution effect in `use-project-chat-controller.ts`
depends on `replaceThreadInRoute`, whose identity follows `routeQuery`, so ANY URL param change
still reloads threads/conversation; with the two fixes above the loop no longer triggers it.
