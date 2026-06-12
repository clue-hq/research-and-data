# Effects Contract V0 — Spec And Implementation Plan

Date: 2026-06-12
Branch: `engine/effects-contract-v0`

## Purpose

Give Lumen a first-class, edit-addressable effects foundation: advanced
strokes, a basic drop-shadow model, multiple fill/stroke fidelity, honest
gradient preview in the editor, and a per-format renderer support matrix
with explicit fallback diagnostics. The goal is to make the visual model and
the modify language effect-aware — not to build Figma-grade effects.

The Brilliant lesson governs the architecture: effects are part of the
authored element model (stacked, individually addressable paints/effects
with stable IDs), every renderer consumes the same model, and formats that
cannot represent an effect natively degrade through an explicit policy
(native → raster fallback → diagnostic), never silently.

## Decisions (2026-06-12)

1. **Stable IDs are the contract.** Fills and strokes already carry
   `PaintId`; effects get `EffectId`. Every entry in a fill/stroke/effect
   stack is individually addressable so Phase D edit semantics extend to
   per-entry patches (`set/add/remove/reorder by ID`) without whole-vector
   replacement.
2. **V0 effect kinds: `DropShadow` only.** One outer shadow
   (`color, opacity, x, y, blur, spread`), multiple entries allowed,
   tokenizable color. Inner shadows, glows, blend modes, filters, masks,
   backdrop blur, mesh gradients, noise are explicitly out — the `Effect`
   enum is open for them later.
3. **Advanced strokes in V0:** dash arrays, caps (`butt|round|square`),
   joins (`miter|round|bevel`), and alignment (`center|inside|outside`).
   Alignment maps natively where the renderer supports it and degrades
   with a diagnostic where it cannot (SVG has no native alignment:
   approximate via path offsetting is out of scope — emit advice
   diagnostic and render center).
4. **Renderer support matrix is code, not prose.** A
   `RendererEffectSupport` table in `lumen-core::render_contract` declares
   per-format support: `Native`, `Approximate`, `Unsupported`. Exporters
   consult it and emit `LUMX` diagnostics for anything not `Native`.
   PDF V0 supports solid paints only: gradients/shadows/dashes on PDF emit
   `Approximate`/`Unsupported` diagnostics rather than wrong output.
5. **Editor parity before new effects.** Konva must render what SVG
   renders for the V0 surface: real linear/radial gradients (no first-stop
   flattening), all fills/strokes in order, dash/cap/join, drop shadows.
6. **Pattern/image fills are deferred to Phase E integration.** Image-as-
   paint needs the asset byte resolver; procedural patterns are not worth
   a custom model in V0. Out of scope here; the `Paint` enum stays open.

## Scope

1. **X1. Scene model** — `Effect { id: EffectId, kind: EffectKind }`,
   `EffectKind::DropShadow { color, opacity, x, y, blur, spread,
   color_token }`; `effects: Vec<Effect>` on `Node` (serde-defaulted);
   `Stroke` gains `dash: Option<Vec<f64>>`, `cap: StrokeCap`,
   `join: StrokeJoin`, `align: StrokeAlign` (defaulted, V0-JSON
   compatible); validation: unique effect IDs per node, finite numbers.
2. **X2. Edit semantics (Phase D extension)** — `NodeEditPatch` gains
   per-entry stack edits: `fills/strokes/effects:
   { set_entry(id, value) | add(entry, index?) | remove(id) |
   reorder(id, index) }`; inverses computed like all Phase D patches
   (round-trip property tests); scope closure treats effect edits as node
   edits; structured-edit wire format extended.
3. **X3. DSL** — modify-line surface:
   `#card stroke(stroke_border,#111827,w(1),dash(6,4),cap(round),join(round))`,
   `#card shadow(shadow_soft,#000000,o(0.18),x(0),y(8),blur(24),spread(0))`,
   `#card remove_effect(shadow_soft)`; creation-line equivalents; explicit
   IDs optional (deterministic `fill_1`-style IDs assigned, matching the
   existing paint-ID policy).
4. **X4. SVG export** — render full fill/stroke stacks in order
   (today: first-only + warning); `stroke-dasharray/linecap/linejoin`;
   drop shadows via `<filter feDropShadow>` (or feGaussianBlur composite
   for spread); deterministic filter IDs.
5. **X5. Editor parity** — Konva gradient rendering (linear/radial from
   the same stops), multi-fill/stroke painting order, dash/cap/join,
   shadows via Konva shadow props; parity test fixtures comparing
   editor-rendered props against SVG expectations.
6. **X6. Support matrix + diagnostics** — `RendererEffectSupport` table;
   PNG raster inherits SVG (resvg path) so it is `Native` where SVG is;
   PDF emits `LUMX` diagnostics per decision 4; preflight surfaces the
   matrix verdicts before export.
7. **X7. Conformance** — golden SVG fixtures (multi-fill card, dashed
   stroke, layered shadows, gradient + shadow combination); visual
   regression baselines; cross-language parity fixture additions for
   effect edits (extends `fixtures/edit-parity/cases.json`).

## Non-Goals (explicit, with owners)

- Inner shadows/glows, blend modes, filters, masks, backdrop blur, mesh
  gradients, noise/texture: effects-v1+ after this contract proves out.
- Image/pattern fills as paint: Phase E integration (byte resolver).
- Print-grade effect flattening/rasterization: export fidelity workstream.
- Exact stacked-effect compositing parity beyond the V0 surface: needs the
  renderer-architecture work the gap analysis assigns to later phases.

## Interaction With Phase D (important)

Phase D's edit layer is the reason this contract exists now: every new
stack entry is addressable, patchable, invertible, scope-checkable, and
undoable from day one. X2 must land with the same guarantees Phase D set:
round-trip inverse identity per builder, envelope persistence untouched
(operations remain canonical), and parity fixtures pinned from both Rust
and TypeScript.

## Slices, Tests, Gates

- **X1** tests: serde back-compat (V0 scene JSON parses), validation
  rejects duplicate effect IDs/non-finite values; wasm check. Gate: model
  lands without touching any renderer.
- **X2** tests: per-entry edit round-trips (apply; apply inverse ==
  identity); unrelated entries preserved; scope violations fail closed.
- **X3** tests: DSL lowering for stroke/shadow/remove_effect; cascade halt
  on malformed entries; deterministic ID assignment.
- **X4** tests: golden SVGs for stacks/dashes/shadows; filter ID
  determinism.
- **X5** tests: Vitest parity (gradient stops, painting order, shadow
  props); editor build green.
- **X6** tests: PDF export of a shadowed/gradient node emits the expected
  `LUMX` diagnostics and renders the supported subset.
- **X7**: full matrix + extended parity fixtures.

## Test Matrix

Phase D matrix plus `cargo test -p lumen-export --test effects_svg` and
the extended edit-parity fixture run on both sides.
