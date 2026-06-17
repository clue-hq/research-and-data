# Wave 3 — CanvasKit Editor Canvas: Detailed Implementation Plan

Date: 2026-06-13
Branch: `editor/canvaskit-canvas-v0` (planning branch, cut from
`editor/coordinate-model-v0` @ `3fddfc8` so the plan sits on the delivered
C-slice-0 substrate).
Scope chosen by product: **full editor swap** — replace the react-konva editor
canvas with CanvasKit, including the complete interaction layer (hit-testing,
drag, resize/rotate transformer, marquee, snapping), SkParagraph text + a DOM
edit overlay, and a flag-gated cutover with Konva retained as fallback.

Status: design/plan only. No implementation code in this branch.

---

## 0. Why, honestly, and what it costs

**Why swap at all.** Two reasons, only two:
1. **Pixel-faithful preview** — the editor renders with the same engine family
   (Skia) the server exports with, so what the user sees is what ships. The
   spike measured **0.003% perceptual diff** (4 of 120k px, no channel delta
   >32) between CanvasKit and the canonical export, including the two-shadow
   stack, gradient stack, and dashed round-cap stroke Konva can only
   approximate.
2. **Text honesty** — CanvasKit's SkParagraph measures text with the *same Inter
   bytes the server uses*, so editor line breaks and widths match the export.
   This closes the E3 heuristic-vs-Skia gap the coordinate-model fix documented
   (the editor currently renders local heuristic geometry; export is Skia).

**What it costs.** Konva is *retained-mode* and hands us hit-testing, event
delegation, drag, and a resize/rotate Transformer for free. CanvasKit is
*immediate-mode*: a drawing API with no scene graph, no events, no handles. The
swap is therefore a **rebuild of the entire interaction layer** — the single
largest, riskiest part of this workstream (slice C3).

**What de-risks it (the dividend of C-slice-0).** The
`editor/coordinate-model-v0` fix already delivered the substrate this build
stands on:
- **One coherent geometry source** (`computed`, kept fresh whole-tree by the
  engine) — hit-testing is now geometry over a single, trustworthy model.
- **A renderer-agnostic gesture→operation pipeline** — `canvasDragOperation`,
  `canvasResizeOperation`, `clampNodeTransformToParentBounds`,
  `clampNodeSizeToParentBounds` are pure and already tested.
- **Selection-target rules + container geometry** already factored out of Konva:
  `containerSelectionGeometry`, `isContainerNode`, `topLevelAncestorId`,
  `isNodeLayoutManaged`, `isCanvasDirectGeometryEditable`.
- **The descriptor contract** (`renderAdapter.ts` → `RenderNodeDescriptor`) the
  spike already proved CanvasKit can draw from.

So this is **"build gesture capture + a Skia draw loop on top of an existing,
coherent substrate,"** not "build an editor." The *commit half* of every
interaction is done; only the *capture half* (pointer → which node → deltas) is
new.

**Honest difficulty.** Moderate-to-high. Most tools are low effort once two
foundations exist (a hit-test function and a redraw loop). The cost
concentrates in three unavoidable places: the **transformer math under
rotation**, **text editing** (hard in any renderer), and **feel/perf at scale**.
Expect the classic curve — 80% fast, the last 20% (rotation edge cases,
snapping polish, latency) eats the schedule.

---

## 1. Decisions (extending the roadmap's Workstream C)

These confirm and sharpen `docs/remaining-roadmap-plan.md` → Workstream C.

1. **CanvasKit default build** (ships `ParagraphBuilder`; the +350 KB `full`
   build is unnecessary — spike-verified). Lazy-load the ~2.9 MB gzip wasm
   (2.24 MB brotli) behind the editor route, `Cache-Control: immutable`, off the
   first-paint path. Pin the `canvaskit-wasm` version to the Skia milestone that
   tracks the server's `skia-safe =0.97.2` family; record the exact
   `(canvaskit-wasm, skia milestone, skia-safe)` triple in the version contract
   and assert it in CI (parity goldens are the real guard; the version note is
   provenance).
2. **Variable Inter TTF** (`InterVariable.ttf`, ~460 KB gzip), not the four
   static weights (~800 KB gzip). woff2 is **not** loadable by CanvasKit
   `FontMgr` (spike) — ship TTF. One `FontMgr`, registered once at module init.
3. **Descriptor contract gains `allShadows` + SVG-contour stroke geometry**
   (C1). The current contract keeps only `shadow[0]` (a Konva-era cap) and dash
   geometry assumes `drawRRect`. Skia's rrect contour start differs from SVG's
   `<rect rx>` start `(x+rx, y)`, shifting dash phase (the spike measured 0.63%
   diff before the fix). Both changes are **additive**; Konva ignores the new
   fields, so the two renderers share one descriptor during the flag period.
4. **Hit-testing lives in `lumen-core`, not the renderer.** It is geometry over
   `computed`; putting it in Rust (a) keeps it consistent across renderers, (b)
   lets the agent reuse it, (c) makes it testable against the exact geometry the
   renderer draws. Exposed via `lumen-wasm`. This is the single largest slice
   and the real cost of the swap.
5. **Selection chrome + handles render in a DOM/SVG overlay, not in CanvasKit.**
   Rationale: 1px-crisp chrome at any zoom without device-pixel fiddling, handle
   hit-testing for free via the DOM, and — critically — **hover and selection
   changes do not trigger a wasm redraw**, which keeps the Skia draw loop quiet
   and the frame budget for actual content. The CanvasKit surface draws *scene
   content only*; an absolutely-positioned SVG layer above it draws selection
   box, child outlines (`containerSelectionGeometry`), hover outline, resize/
   rotate handles, marquee, and snap guides. (Figma renders chrome in WebGL too;
   for a V0 swap the overlay is the lower-risk, lower-cost path and is a clean
   seam to migrate later if needed.)
6. **The editor's in-browser text measurement becomes SkParagraph (C4),
   feeding the engine's layout.** Today the wasm core measures text with the
   heuristic (skia-safe can't target wasm32). CanvasKit *can* measure in-browser.
   C4 introduces a **measurement provider** the engine consumes: the editor
   measures via SkParagraph and feeds metrics into `relayout`, so `computed`
   becomes Skia-faithful and the editor render == export geometry. This resolves
   both the E3 caveat and the coordinate-model fix's "editor renders heuristic
   geometry" product consequence. See §4 (C4) for the mechanism and its risk.
7. **Flag-gated, Konva retained as fallback** behind
   `NEXT_PUBLIC_LUMEN_CANVASKIT` (parallel to `NEXT_PUBLIC_LUMEN_WASM_CORE`).
   Cutover is a parity exercise; Konva stays until render parity AND interaction
   conformance hold. Decide deletion in a follow-up after a soak release.
8. **Every gesture still emits the same canonical `Operation`s through the WASM
   engine.** No new mutation path. The conformance gate is the existing W6
   gesture script: through the CanvasKit path it must produce envelopes
   **byte-identical** (modulo `computed`, per the coordinate-model fix's
   normalization convention) to the Konva path.

---

## 2. Architecture at a glance

```
┌────────────────────────────── EditorApp (unchanged contract) ──────────────────────────────┐
│  scene (single-source, engine-relaid computed)                                              │
│      │                                                                                       │
│      ├─ renderAdapter.ts ── RenderNodeDescriptor (+ allShadows, SVG-contour strokes) ──┐     │
│      │                                                                                  ▼     │
│   selectedNodeId ─────────────────────────────►  CanvasKitCanvas (new, flag-gated)            │
│      ▲                                            ├─ <canvas>  : CanvasKitStage (content only) │
│      │                                            │     drawDescriptorTree(ck, …)  [C2]        │
│      │                                            └─ <svg overlay> : selection/handles/guides  │
│      │                                                  (chrome, hover, marquee)        [C3/5] │
│      │                                                                                          │
│   gesture state machine [C3] ── pointer events ──► hitTest()/hitStack() via lumen-wasm [C3]    │
│      │                            (idle→drag→commit, handle-drag, marquee, dbl-click drill-in)  │
│      └──────────────► canvasDragOperation / canvasResizeOperation (EXISTING, renderer-agnostic) │
│                                   │                                                              │
│                                   ▼                                                              │
│                       WasmEngine.applyOperations ──► relayout (computed fresh)  [C-slice-0]      │
│                                   │                        ▲                                     │
│                                   │                        └── measurement provider (SkParagraph)│
│                                   ▼                              [C4] replaces heuristic in-editor│
│                           SceneDelta ──► React scene ──► descriptors ──► redraw                  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

Konva path (`CanvasSurface.tsx`, `SceneNode.tsx`) stays intact behind the flag;
`CanvasKitCanvas` is a drop-in alternative consuming the same props
(`scene, activePageId, selectedNodeId, onSelectNode, onOperation`).

---

## 3. Slice plan

Each slice lists **deliverable**, **key files**, **contract/decision**, **tests**,
and **gate**. Slices are sized to land and review independently.

### C0 — Build + bundle integration
- **Deliverable:** `canvaskit-wasm` dependency; lazy module singleton (init
  promise, like the spike's `loadCanvasKit`); wasm + `InterVariable.ttf` served
  from `/canvaskit/` and `/fonts/` with immutable caching + brotli; the editor
  builds and loads CanvasKit lazily with no first-paint regression.
- **Key files:** `apps/editor/next.config` (headers, asset copy), a new
  `apps/editor/src/engine/canvaskit/loadCanvasKit.ts` (singleton init + FontMgr),
  build step to copy `canvaskit.wasm` + TTF into `public/`.
- **Contract:** module init happens exactly once; a failed/missing load resolves
  to "CanvasKit unavailable" and the editor stays on Konva (mirrors the wasm-core
  degrade-to-server pattern).
- **Tests/CI:** bundle-size assertion (budget ~2.9 MB gzip, **distinct** from the
  684 KB WASM-core budget); cold-init timing assertion (spike: ~283 ms first
  visit Chromium); a smoke test that the module + FontMgr initialize headless.
- **Gate:** editor first paint unaffected (CanvasKit not on the critical path);
  `npm run build` green; size/init CI checks pass.

### C1 — Descriptor contract extension (lands first; shared)
- **Deliverable:** `RenderNodeDescriptor` gains `allShadows: ShadowDescriptor[]`
  (full effect stack) and an SVG-equivalent stroke-contour path for dashed
  strokes; `renderAdapter.ts` populates both; Konva path unaffected (ignores new
  fields).
- **Key files:** `apps/editor/src/engine/renderAdapter.ts`, its tests,
  `effectsRenderParity.test.ts`, the edit-parity fixtures.
- **Contract:** additive only. `shadow` (single) stays for Konva; `allShadows`
  is the superset CanvasKit consumes. Dash geometry is emitted as a path that
  starts at SVG's `(x+rx, y)` so dash phase matches the export.
- **Tests:** extend effects-render-parity + edit-parity fixtures to cover the new
  fields; assert Konva descriptors are byte-unchanged for existing cases.
- **Gate:** full editor suite green; descriptor diff for non-shadow/non-dash
  nodes is empty.

### C2 — CanvasKit stage + descriptor interpreter (read-only render)
- **Deliverable:** productize the spike's `CanvasKitStage` + `drawDescriptorTree`
  into `apps/editor`: gradients, paint stacks (fills bottom-to-top then strokes),
  dash/cap/join via SVG-contour paths, drop-shadow **stack** via `saveLayer` +
  chained `ImageFilter.MakeDropShadow` (sigma = blur/2), images via
  `drawImageRect`. WebGL2 surface with CPU fallback; `ResizeObserver`-driven
  surface recreate at `devicePixelRatio`; dirty-flag + single-rAF redraw (no rAF
  while clean). RAII memory helper for `Paint`/`Path`/`Paragraph`/`Shader`.
- **Key files:** `apps/editor/src/engine/canvaskit/CanvasKitStage.tsx`,
  `drawDescriptors.ts` (the interpreter), `ckMemory.ts` (RAII scope helper),
  `CanvasKitCanvas.tsx` (the props-compatible wrapper, render-only for now).
- **Contract:** the surface draws **scene content only**; viewport (zoom/pan) is
  a canvas transform, not per-node math.
- **Tests:** render-parity — CanvasKit stage PNG vs the Skia export goldens at
  the spike's 0.003% bar (reuse `spike_canvaskit_baseline` harness, productized);
  a determinism test (same descriptors → same pixels).
- **Gate:** parity goldens pass; redraw stays at one rAF per descriptor change;
  no leaked Skia objects across N redraws (memory probe).

### C3 — Interaction layer (the big one)
Built in four reviewable sub-steps.

- **C3a — Hit-testing in `lumen-core`.**
  `hit_test(scene, page_id, point) -> Option<NodeId>` and
  `hit_stack(scene, page_id, point) -> Vec<NodeId>` (root→leaf, for drill-in).
  Geometry over `computed`: transform the point into each node's local frame
  (inverse transform incl. rotation/skew), top-down z-order, respects `clip`,
  recurses children. V0 hit shape = `computed` bbox for rects/text/images +
  path-fill test for vectors/lines; **alpha-accurate raster hit is a documented
  follow-up**, not V0. Exposed via `lumen-wasm`:
  `engine.hitTest(x, y)`, `engine.hitStack(x, y)`.
  - **Tests (Rust):** axis-aligned, rotated, skewed, clipped, nested, overlapping
    z-order, point-on-vector-path, miss-returns-none — against the same geometry
    the renderer draws.
- **C3b — Pointer→gesture state machine (TS).** A custom pipeline replacing
  Konva's delegation. States: `idle → pressed(node) → dragging(past threshold)
  → commit` plus `handle-drag`, `marquee`, `hover`. Selection-target rules reuse
  C-slice-0 helpers: single-click → deepest (`hitStack` leaf), double-click →
  `topLevelAncestorId`, layer panel → any level. Drag deltas: screen → ÷zoom →
  `canvasDragOperation` (existing). Non-direct-editable selections
  (`isCanvasDirectGeometryEditable`) get the existing notices, not handles.
  - **Tests:** a headless gesture-script harness (no Konva) feeding synthetic
    pointer events → assert the emitted operations; reuse the **W6 conformance
    fixture** — CanvasKit path envelopes must equal the Konva path (modulo
    `computed`).
- **C3c — Transformer (resize/rotate) in the SVG overlay.** 8 resize handles +
  a rotate handle around the selection bbox. Handle hit-testing via DOM. Resize
  math in the node's **local frame**: opposite-corner anchor stays fixed,
  min-size clamp (`clampNodeSizeToParentBounds`), aspect lock with Shift, flip on
  cross-over, all correct under rotation (resize in local space, map back).
  Rotate: angle from center to pointer, Shift-snap to 15°. Emits
  `canvasResizeOperation` (existing).
  - **Tests:** unit-test the handle→size/position math (the hard part) across
    rotation, aspect-lock, min-clamp, flip; a parity check that a scripted resize
    yields the same operation as the Konva Transformer path.
- **C3d — Marquee + snapping + selection chrome.** Rubber-band select
  (rect-vs-`computed`-bbox intersection over the page node list); edge/center
  snapping to siblings + page + safe area within a px threshold, with alignment
  guides drawn in the overlay; container chrome via `containerSelectionGeometry`;
  hover outline via `hitTest` on throttled pointer-move. All chrome in the SVG
  overlay (no wasm redraw on hover/selection).
  - **Tests:** marquee selection set, snap target selection + threshold,
    guide geometry — all pure functions, unit-tested.
- **Gate (C3):** the W6 gesture script through the CanvasKit path produces
  envelopes identical to Konva; manual browser QA on selection/drag/resize/rotate
  feel; frame-budget check on a 100+-node scene (the spike flagged `saveLayer`
  cost for shadowed nodes at scale).

### C4 — Text rendering + edit overlay (the convergence step)
- **Deliverable (render):** SkParagraph-driven text layout in the CanvasKit stage
  using the same Inter bytes the server uses — bit-faithful breaks on the
  caps/digit/hyphen cases the heuristic diverged on (spike: 16/35 lines differ).
- **Deliverable (measurement provider):** a `TextMeasurer` interface the engine
  consumes; the editor injects a SkParagraph-backed implementation, so
  `relayout` produces **Skia-faithful `computed`** and editor geometry == export
  geometry. Mechanism options to decide during implementation:
  - (a) **wasm→JS callback:** the wasm engine calls an injected JS measurer
    (wasm-bindgen supports JS imports) during layout. Cleanest single-source, but
    couples the engine to a host callback and complicates the pure-Rust tests.
  - (b) **measure-then-inject:** the editor pre-measures dirty text nodes via
    SkParagraph and writes metrics into the scene before `relayout`; the engine
    consumes provided metrics, falling back to heuristic when absent. Keeps the
    engine pure; adds a measure pass. **Recommended for V0** — lower coupling,
    incremental, and the heuristic stays as the offline/test default.
- **Deliverable (editing):** text editing via an absolutely-positioned DOM
  `contenteditable`/`textarea` overlay (CanvasKit, like Konva, cannot host a live
  caret). Click→caret index via SkParagraph glyph positions; commit writes
  `updateTextNode`. While editing, the CanvasKit text is hidden under the
  overlay; on blur it re-renders.
- **Key files:** `drawDescriptors.ts` (paragraph build/draw),
  `engine` text-measurement seam (`lumen-core`/`lumen-wasm` + editor provider),
  `TextEditOverlay.tsx`.
- **Contract:** with the provider active, the editor's `computed` for text is
  Skia geometry; the E3 caveat is resolved; the coordinate-model fix's
  "editor renders heuristic geometry" consequence is closed.
- **Tests:** text-measure parity (SkParagraph editor metrics vs server skia-safe
  metrics) on the spike's mixed-case/caps/digit/hyphen corpus; caret-index
  mapping; an edit round-trip emits the right op; relayout with the provider
  yields export-matching bounds.
- **Gate:** editor text geometry matches export within tolerance; editing UX
  works (caret, selection, IME basic); heuristic remains the headless/test
  default.

### C5 — Flag-gated cutover + parity
- **Deliverable:** both renderers selectable via `NEXT_PUBLIC_LUMEN_CANVASKIT`;
  the **full editor test suite runs under the CanvasKit flag** (parameterized);
  visual-regression parity vs Skia export goldens; a long-session leak/soak test;
  bundle + cold-init CI gates wired.
- **Tests:** the entire `apps/editor` suite green under both flags; a soak test
  that drags/edits for N minutes and asserts bounded wasm heap growth.
- **Gate:** parity + suite + soak green under the flag; no first-paint or bundle
  regression.

### C6 — Conformance + Konva retirement decision
- **Deliverable:** interaction conformance (C3 envelopes) + render parity (C2/C5)
  documented green under the flag; a written decision: delete Konva now or keep
  one release as fallback (**recommend keep one release**, delete in a follow-up
  after the CanvasKit path soaks in production).
- **Gate:** decision recorded; if "keep," the flag default flips to CanvasKit
  with Konva reachable; if "delete," a separate cleanup PR.

---

## 4. Sequencing & dependencies

- **Hard dependency:** `editor/coordinate-model-v0` (C-slice-0) merged to `main`
  — the single-source model, geometry helpers, and operation pipeline this build
  reuses. Cut the **implementation** branch fresh from the updated `main`; this
  planning branch holds only the doc.
- **Order:** C1 (shared descriptor) → C0 ∥ C2 (bundle ∥ render) → C3
  (interaction; C3a hit-test gates C3b–d) → C4 (text) → C5 → C6.
- **Parallelizable:** C0 and C1 are independent; within C3, the overlay chrome
  (C3d) can progress against C3b while C3c (transformer) is in flight.
- **Cross-stream:** C4's measurement convergence touches
  `engine-skia-text-raster-v0` territory — coordinate the text-measurer seam so
  server (skia-safe) and editor (SkParagraph) share one metric definition.

---

## 5. Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Interaction feel (drag/resize latency, handle precision, hit tolerance) | High | C3/C5 manual browser QA + frame-budget check on 100+-node scenes; tune hit tolerance + cursor affordances |
| Transformer math under rotation (flip, min-clamp, aspect, anchor) | High | Isolate as pure functions; exhaustive unit tests before wiring; parity vs Konva Transformer on a scripted resize |
| Hit-testing correctness under transform/clip/nesting | High | Put it in `lumen-core`, test against the exact geometry the renderer draws; rotated/skewed/clipped cases explicit |
| Text-measurement convergence complexity (engine measurer swap) | Med-High | V0 = measure-then-inject (engine stays pure, heuristic fallback); defer wasm→JS callback; parity test vs server metrics |
| Two measurement systems during transition (heuristic vs SkParagraph) | Med | Provider interface with heuristic default; CanvasKit provider only when the flag is on; conformance asserts coherence |
| wasm-memory leaks (Paint/Path/Surface/Paragraph/Shader) | Med-High | RAII scope helper + lint convention; C5 soak/leak test with bounded-growth assertion |
| Bundle weight on first editor load (~2.9 MB) | Med | Lazy-load + brotli + immutable cache (C0); off the first-paint path; explicit CI budget |
| `saveLayer` shadow cost at scale | Med | Dirty-rect redraw, layer caching for static content, frame-budget gate; cap previewed shadow stack if needed (document) |
| Chrome-in-overlay vs in-canvas divergence (zoom transforms) | Low-Med | Single source of truth for the viewport transform shared by canvas + overlay; snapshot tests on overlay geometry |
| Scope creep in the interaction layer | Med | V0 = select/drag/resize/rotate/marquee/snap/hover + text edit; alpha-accurate hit, multi-select transform, boolean ops, pen tool are explicit follow-ups |

---

## 6. Acceptance criteria

- CanvasKit editor render matches the Skia export goldens at the spike's 0.003%
  bar, including the full shadow stack, gradient stacks, and dashed round-cap
  strokes.
- The W6 gesture script (drag, resize, text edit, keyboard nudge, effects stack
  edit, page rename) through the CanvasKit path produces envelopes **identical**
  to the Konva path (modulo `computed`).
- Select / drag / resize / rotate / marquee / snap / hover and text editing all
  work in a real browser with acceptable feel; the container-drag semantics and
  selection-target rules from C-slice-0 are preserved.
- Editor text geometry matches export within tolerance (SkParagraph provider);
  the E3 caveat is closed under the flag.
- Full `apps/editor` suite green under both flags; soak test shows bounded wasm
  heap; bundle + cold-init within budget; first paint unaffected.
- A recorded Konva-retirement decision.

---

## 7. Effort shape (calibrated, not a commitment)

- **C0/C1** — small each (bundle plumbing; additive descriptor fields + fixtures).
- **C2** — medium (the spike already proved the draw mapping; productizing +
  parity harness + memory discipline is the work).
- **C3** — **large**, the dominant cost: C3a (hit-test in core) medium with heavy
  tests; C3b (gesture machine) medium; **C3c (transformer) the deepest single
  piece**; C3d (marquee/snap/chrome) medium.
- **C4** — medium-large (SkParagraph render is straightforward; the
  measurement-provider convergence and the edit overlay are the substance).
- **C5/C6** — small-medium (parameterize the suite, soak, decision).

The interaction layer (C3) plus text convergence (C4) are ~two-thirds of the
total. Everything else is plumbing the spike already de-risked.
