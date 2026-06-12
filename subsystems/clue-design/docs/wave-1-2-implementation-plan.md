# Wave 1 And Wave 2 Implementation Plan

Date: 2026-06-13
Status: approved sequencing; this document is the working spec for all five
tracks.

## Purpose And Sequencing Rationale

With phases A–F complete and merged (`main` at `2bbde6c`: Phase D targeted
editing + history, Effects Contract V0, Phase E asset runtime), the remaining
work is Phase G (personalization runtime — the product differentiator) plus
the renderer/engine convergence decisions (Skia, CanvasKit, browser WASM
core).

One dependency orders everything: **Phase G's batch fit-validation is only
as honest as text measurement**, and measurement today is heuristic
(`HeuristicTextMeasurer`: per-character width weights, whitespace word
wrapping — `crates/lumen-core/src/text_measure.rs`). If G ships on the
heuristic, every fit verdict, baseline, and golden it produces is
invalidated the day real shaping lands, because shaping changes line breaks
→ layout → fit verdicts. Therefore:

- **Wave 1 (short):** Skia on the server (text shaping + raster), the two
  pre-G contracts (landing pages, QR→URL binding chain), the print-fidelity
  check, and an optional CanvasKit spike.
- **Wave 2 (parallel, two worktrees):** Phase G on the server surface;
  browser WASM core on the editor surface.
- **Wave 3 (out of this document's scope, decision gated on the spike):**
  CanvasKit editor swap; eventually the write-once Rust scene→paint
  translation executed by CanvasKit (browser) and skia-safe (server).

The browser WASM core sits on no one's critical path; it runs parallel to G
because the surfaces are disjoint and because deferring it means every
G-era editor feature pays the TS-mirror tax again (as Effects V0 just did).

## Codebase Grounding (read 2026-06-13)

What exists and where the new work attaches:

- **Measurement boundary**: `TextMeasurer` trait with well-shaped
  `TextMeasureInput`/`TextMeasureOutput`/`TextLineBox` DTOs already exists
  (`text_measure.rs`). BUT the free function `measure_text()` hardcodes
  `HeuristicTextMeasurer`, and it is called directly from four sites in
  `layout.rs` (603, 734, 1253, 1395) and one in `lumen-export/src/svg.rs`
  (401). `LayoutOptions` exists (`{ validate_slots }`) and is the natural
  injection point. **A1's first job is threading `&dyn TextMeasurer`
  through these call sites.**
- **Raster path**: `lumen-export/src/png.rs` renders the SVG string via
  resvg/usvg (`usvg::Tree::from_str` → `resvg::render`). Critic previews
  consume the PNG artifacts (agent runtime `tools.py`).
- **Slot model is already G-shaped**: `slots.rs` carries `ConditionalRule`
  (+`EmptyBehavior`), `RepeaterRule` (+`ReflowPolicy` incl. `Paginate`),
  `Cardinality`, `ValidationFixtures` (samples/worst_case/max_length),
  `ImagePolicy` (fit/focal/min_dpi/aspect), `Editability`
  (TemplateOnly/InstanceOnly/...), `BindingHint`, and `ContentType::UrlQr`.
  **Phase G implements the runtime for contracts that already exist as
  data.** Finalized template revisions persist in `template_revisions`
  (scene snapshot + slot summary + export profiles + brand ref).
- **Editor state ownership** (target of W2): `EditorApp.tsx` owns the scene
  via `useState<Scene>` with snapshot-based local undo frames; optimistic
  edits flow through TS mirrors (`operations.ts`, `structuredEdits.ts`)
  policed by `fixtures/edit-parity/cases.json`.
- **Asset/generation seam for G**: Phase E's `generate_asset` helper action
  + provider registry exist with QR as the first provider
  (deterministic, scan-verified); no public API route yet — G lands it.
- **Phase D machinery G reuses**: clone builders with `CloneLineage`
  (repeater mechanic), envelopes/undo, strict scope, `FinalizeTemplate`
  validation gates.

---

# Wave 1

## Track A: `engine/skia-text-raster-v0` (this branch)

### Decisions

1. **New native-only crate `lumen-skia`.** `skia-safe` binds native C++
   Skia and cannot compile to wasm32; it must never enter `lumen-core`
   (which stays wasm-clean) or `lumen-export`'s portable surface. The
   crate implements the existing `TextMeasurer` trait plus a scene
   rasterizer. Composition happens in `lumen-api-helper` (the same
   pattern Phase E used for `lumen-assets`).
2. **Use `skia-safe` with the `textlayout` feature** (bundles
   SkParagraph + HarfBuzz + ICU) and `binary-cache`/prebuilt binaries to
   avoid building Skia from source in CI. Pin the version workspace-wide;
   record it in memory (it becomes the version CanvasKit must match in
   Wave 3).
3. **Deterministic server fonts.** A `FontManager` owning a font
   directory (`fonts/` at repo root, starting with Inter's static TTFs);
   fonts load from bytes, never from system font lookup, so server,
   CI, and (later) browser shape identically. Font files are the parity
   contract; the same files ship to CanvasKit in Wave 3.
4. **Raster becomes scene→Skia direct painting**, not SVG-string
   rasterization. This is the first instance of the write-once paint
   translation: a `SkiaSceneRenderer` in `lumen-skia` consuming the same
   scene + computed geometry the SVG exporter consumes, covering the
   Effects V0 surface natively (paint stacks, gradients, dash/cap/join,
   multi-shadow WITH spread — Skia does these first-class). resvg remains
   temporarily behind a comparison flag and is removed at the A5 gate.
5. **Measurement is injected, with the heuristic as the wasm fallback.**
   `LayoutOptions` gains `measurer: Option<&dyn TextMeasurer>` (None →
   heuristic, preserving wasm builds and existing tests until they opt
   in). `PreflightOptions` threads it through. The helper constructs the
   Skia measurer for every server compile/preflight/export path.
6. **Golden regeneration is a deliberate one-time event** at A5: PNG
   baselines and text-position-sensitive fixtures regenerate under Skia
   measurement + raster, reviewed as a dedicated commit. SVG markup
   goldens that don't encode text line breaks are unaffected; those that
   do are listed in the regeneration commit message.

### Slices

- **A1 — crate bootstrap + fonts.** `crates/lumen-skia` with skia-safe
  (textlayout, prebuilt binaries); `FontManager::from_dir` loading
  TTF bytes into an SkParagraph `FontCollection`; `fonts/` with Inter
  (400/600/700/800 + license file); CI caching notes in the crate README.
  Tests: font load, deterministic typeface resolution, missing-font
  fallback policy (explicit default family + warning diagnostic).
  Gate: crate builds in CI without compiling Skia from source.
- **A2 — `SkiaTextMeasurer`.** Implements `TextMeasurer` via SkParagraph:
  paragraph style from `TextMeasureInput` (font size, line-height
  multiplier via height override, letter spacing, max width for wrap,
  max_lines + ellipsis off, LTR/RTL from direction); output mapped to
  `TextMeasureOutput`/`TextLineBox` (per-line text ranges, x/y/width/
  baseline from line metrics). Thread the injection point: `LayoutOptions
  { measurer }`, the four `layout.rs` call sites, the `svg.rs` call site,
  `PreflightOptions`, helper wiring for compile/preflight/export actions.
  Tests: determinism (same input → identical output twice); sanity vs
  heuristic (same line count for trivially short text; wrap happens at
  most-plausible boundaries); overflow flags; max_lines truncation; RTL
  smoke; long-word behavior (Skia breaks, heuristic doesn't — pin Skia's).
  Gate: server preflight uses Skia measurement end to end; wasm build
  untouched and green.
- **A3 — `SkiaSceneRenderer` (PNG raster).** Paint the scene from
  computed geometry: pages (background stacks), rect/ellipse/line/vector
  paths, fills/strokes stacks in painting order, gradients from stops,
  dash/cap/join (+ inside/outside alignment natively via path inset/
  outset where cheap, else center + advice, matching the SVG policy),
  drop shadows with spread via SkPaint image filters, text via the SAME
  SkParagraph layout used by A2 (single source for line breaks), images
  from `AssetByteResolver` bytes with contain/cover/focal crop mapping
  (mirroring Phase E's SVG semantics). Output: `Pixmap → PNG bytes`
  behind the existing `PngExportAdapter` interface.
  Tests: golden PNGs for the effects card fixture, a text-wrap fixture,
  and the Phase E asset scene; pixel-diff harness with small tolerance
  (CPU backend pinned); resvg-vs-skia diff report emitted once for review.
  Gate: PNG export and critic previews come from Skia.
- **A4 — helper + critic wiring.** `export_preview`/document export paths
  construct the Skia measurer + renderer (store-root resolver from E
  composes unchanged); agent critique screenshots therefore inherit real
  shaping + real effects (Konva's preview cuts no longer leak into critic
  judgments). Remove the resvg path and dependency.
  Tests: existing API/agent suites; one new assertion that critic preview
  PNG contains shaped text (pixel-region heuristic on the fixture).
- **A5 — golden regeneration + conformance.** Regenerate affected
  baselines in one reviewed commit; update the visual-regression manifest;
  full matrix (Phase D test commands + `cargo test -p lumen-skia`).
  Acceptance: G can consume `TextMeasureOutput` as truth; the pixel
  source for critic/export is Skia; heuristic remains only as the wasm
  fallback.

### Risks

- skia-safe build friction (first-build time, platform toolchain):
  mitigated by prebuilt binaries + CI cache; budget the first day.
- SkParagraph line-height semantics differ from our multiplier model:
  pin with explicit height-override tests in A2 before anything depends
  on it.
- Scene→Skia painting drift vs SVG export: both consume the same
  computed geometry and the same measurer; A3 goldens diff against SVG
  renders of the same fixtures to bound divergence.

## Track B: Pre-G Contracts (specified here; verified during Wave 1)

### B1 — Landing pages are not scenes (decision)

A personalized landing page is responsive, flowing web content; forcing it
into the fixed-canvas scene model would be a category error. Decision:

- Landing pages are a **separate future workstream**
  (`web/landing-pages-v0`) that shares Lumen's **slot, Brand Kit, and
  content contracts** but not scene geometry.
- The design engine's responsibility in the chain ends at: per-instance
  **URL allocation**, the **QR asset** encoding it, and exposing the
  binding values a landing-page renderer would consume.
- Nothing in Phase G may assume landing pages render through the scene
  model; the `links` field below is the entire coupling surface.

### B2 — BindingSet contract (the Phase G data model)

A binding set is the per-recipient input to instance derivation. It is
data, never operations; instances derive from
`finalized snapshot + binding set + export profile`, never op-log replay
(temp spec §16.3).

```json
{
  "schema_version": 1,
  "binding_set_id": "bind_acme_dr_sharma",
  "template_revision_id": "tmpl_9f2c",
  "audience": { "account_id": "acct_acme", "contact_id": "ct_sharma" },
  "values": {
    "contact.full_name": { "kind": "text", "value": "Dr. Priya Sharma" },
    "account.logo":      { "kind": "asset", "asset_id": "asset_acme_logo" },
    "campaign.cta":      { "kind": "text", "value": "Book your demo" },
    "research.key_insights": {
      "kind": "list",
      "items": [ { "kind": "text", "value": "..." } ]
    }
  },
  "links": {
    "landing_page": { "url": "https://go.example.com/acme/dr-sharma" }
  },
  "generated": {
    "qr_landing": {
      "provider": "qr",
      "input": { "url_from": "links.landing_page.url", "ec_level": "h" },
      "bind_to_slot": "campaign.qr"
    }
  }
}
```

Rules: every `values` key must resolve to a slot key on the revision;
kinds must match slot `ContentType`; required slots without values fail
validation (or trigger `ConditionalRule`/fallback where defined);
`generated` entries run through Phase E's provider registry at derivation
time and are digest-stable (same URL → same QR asset). The QR→URL chain
is exactly: `links.*.url` → `generated.*` (provider `qr`) → bound to the
`UrlQr` slot → exported on the artifact.

### B3 — Print-fidelity check (procedure, run during Wave 1)

Before G designs bulk print export against the current PDF path: build a
mailer fixture (custom page size, 3mm bleed, safe area, text, QR image),
export print PDF, inspect with `pdffonts` (embedding), `pdfinfo`
(MediaBox/TrimBox/BleedBox), and Ghostscript render at 300dpi (visual +
QR scan). Record pass/gaps in the workstream memory. Known constraint:
the V0 PDF surface is solid-paint-only with explicit diagnostics; the
check documents what bulk print export can rely on TODAY and what the
print-fidelity workstream must add. G's bulk-export design consumes this
verdict (worst case: bulk print V0 ships PNG-at-300dpi-in-PDF flattening
via the A3 Skia raster — Skia's native PDF backend is the flagged
follow-up for the print workstream).

## Track C: CanvasKit Spike Charter (optional, one agent-day)

Branch `spike/canvaskit-editor`, throwaway. Questions to answer with
numbers: (1) bundle cost (wasm + fonts, gzipped) and init time; (2) render
the effects-card and asset fixtures from existing `RenderNodeDescriptor`s —
pixel-diff vs A3's Skia PNG (target: near-zero, same engine); (3)
SkParagraph in-browser with the same `fonts/` files — line breaks identical
to A2 on the wrap fixture; (4) API ergonomics for an imperative
React wrapper. Deliverable: a numbers-first report and a go/no-go
recommendation for Wave 3. No production code.

---

# Wave 2 (branches cut from main after Wave 1 merges)

## Track D: `phase-g/personalization-runtime-v0`

### Decisions

1. **Instances are derived artifacts, not documents.** An instance =
   pure function of (revision snapshot, binding set, asset store). Stored
   as instance rows (id, revision, binding_set, status, diagnostics,
   artifact refs, derived-scene cache); replayable by re-derivation. No
   per-instance manual editing in V0 (the gap analysis lists it as
   optional/future); repairs happen on the template (new draft revision)
   or on binding values — both audited surfaces that re-derive.
2. **Slot semantics execute, not extend.** G implements the runtime for
   the existing `slots.rs` contracts. V0 conditional expressions are
   restricted to `has(slot_key)` / `missing(slot_key)` / `eq(slot_key,
   "literal")` — no general expression language; anything else is a
   validation error naming the unsupported form.
3. **Repeaters ride Phase D clone machinery**: template subtree cloned
   per item with deterministic per-item IDs (suffix `_item_{n}`),
   `CloneLineage` recorded, per-item slot binding via the suffix policy,
   then reflow per `ReflowPolicy` (`Stack`/`Wrap` in V0; `Paginate` =
   explicit V0 validation error, owned by the print workstream).
4. **Batch jobs are synchronous-chunked in V0** (job row + chunked
   processing + resumable cursor), not a queue system. The job table is
   the seam where a real queue lands later.
5. **Overflow handling executes the slot's declared `OverflowPolicy`**,
   with `ShrinkFont` bounded by min/max, measured by the Skia measurer;
   `AskAgentToRepair` produces a repair-queue entry (template-level),
   never an in-instance mutation.

### Slices

- **G0 — fixtures + failing tests**: a finalized mailer revision fixture
  (slots: name, logo, CTA, insights repeater, conditional quote, QR), 3
  binding sets (nominal, worst-case lengths from `ValidationFixtures`,
  missing-optional-content), failing tests naming the runtime surface.
- **G1 — binding contracts in core** (`lumen-core/src/binding.rs`):
  `BindingSet`, `BoundValue` (per `ContentType`), `InstanceLink`,
  `GeneratedAssetSpec` per B2; validation against the revision's slot
  summary (keys exist, kinds match, required covered, cardinality,
  `FormattingConstraints.max_length`); wasm-clean.
- **G2 — derivation core**: `derive_instance(snapshot, binding_set,
  assets) -> DerivedInstance { scene, diagnostics, audit }` — text
  application, image/logo placement via existing `PlaceAssetInSlot`
  semantics, deterministic output (property: same inputs → identical
  scene JSON).
- **G3 — conditionals**: evaluate V0 expression forms; `EmptyBehavior`
  execution (HideRegion removes the bound subtree pre-layout;
  UseFallback substitutes placeholder; ValidationError); audit entries
  ("region X hidden: missing research.quote"); reflow via layout rerun.
- **G4 — repeaters**: clone-per-item with lineage, per-item binding,
  min/max enforcement, Stack/Wrap reflow, deterministic IDs; the
  effects/asset properties of the template subtree must survive cloning
  (regression-tested against the effects card).
- **G5 — per-instance generated assets**: execute `generated.*` specs
  through the E provider registry (public `POST /assets/generate` route
  lands here); QR digest-stability across re-derivation; provenance
  records the binding_set_id.
- **G6 — batch validation**: per-instance preflight (Skia measurement)
  producing `InstanceFitReport` (slot-level verdicts incl. executed
  overflow policy, diagnostics, worst-case flags); batch aggregation
  (counts by verdict, failing instances listed); this is the honest-fit
  promise — gate on the worst-case fixture catching a deliberate
  overflow.
- **G7 — bulk export**: chunked batch job rendering instances to
  SVG/PNG (Skia) and PDF (within the B3-verified surface); artifact
  storage via the E asset store (content-addressed outputs); manifest
  per batch; per-instance status.
- **G8 — API + persistence**: binding-set CRUD (validated on write),
  `POST /revisions/{id}/instances` (derive one), `POST /revisions/{id}/batches`
  (derive+validate+export many), instance/batch readback; migration 005.
- **G9 — agent/editor surfaces**: agent tools `validate_binding_set` /
  `derive_instance_preview` (critic can see a personalized instance);
  editor worst-case preview mode (render the worst-case binding set's
  derived scene read-only); repair queue entries for `AskAgentToRepair`.
- **G10 — conformance**: deterministic 100-instance batch from seeded
  binding sets; acceptance criteria: zero silent overflows (every fit
  issue surfaced), QR scan-verified on one sampled instance artifact,
  re-derivation idempotence, bulk export manifest complete.

## Track E: `engine/wasm-editor-core-v0`

### Decisions

1. **`lumen-wasm` is a thin binding crate** (wasm-bindgen) over
   lumen-core — zero semantics of its own (the §5.4 golden rule). The
   WASM module owns the local scene in its memory; JS sends operations/
   edits in and receives results out. No per-keystroke full-scene
   serialization.
2. **Server authority is untouched.** `/edits` + envelopes + base
   revision stay exactly as built; WASM upgrades the OPTIMISTIC path
   from TS approximation to the real engine. Reconcile-on-response
   remains (now expected to be a no-op except concurrent edits).
3. **Text honesty is explicit**: skia-safe cannot compile to wasm32, so
   in Wave 2 the in-browser engine measures text with the heuristic
   fallback; server-computed geometry remains authoritative for
   text-dependent layout, and the editor renders server geometry when
   available. Bit-faithful in-browser text arrives in Wave 3 via a
   CanvasKit-backed `TextMeasurer` through the same trait. Document this
   in the editor README; do not pretend parity that isn't there.
4. **Version handshake**: the WASM module exposes
   `{ schema_version, engine_commit }`; the editor compares against the
   API's build info and downgrades to server-only mode (current
   behavior) on mismatch — never mixed-version optimistic editing.
5. **TS mirrors retire incrementally** behind the
   `NEXT_PUBLIC_LUMEN_WASM_CORE` flag; the edit-parity fixture suite
   stays until the mirrors are deleted, then shrinks to a smoke test
   (same engine on both sides makes byte-parity tautological).

### Slices

- **W1 — `lumen-wasm` crate**: wasm-bindgen API — `init(scene_json)`,
  `applyOperations(ops) -> {report, diagnostics}`,
  `applyStructuredEdit(edit) -> batch result (ops, inverses, touched)`,
  `compileDslBlock(source, session)`, `layout()/preflight subset`,
  `sceneJson()`, `version()`; wasm-pack build wired into the editor
  build; size budget recorded (<3MB gz target).
- **W2 — state ownership refactor**: `WasmEngine` TS class owning the
  module instance; `EditorApp` consumes scene snapshots/selectors from
  it instead of `useState<Scene>` mutation paths; local undo frames keep
  working over engine snapshots; flag-gated with the legacy path intact.
- **W3 — optimistic pipeline**: gestures/inspector/DSL panel apply
  through the WASM engine locally + enqueue to `/edits`; server response
  reconciles (replace local scene on divergence, surface a diagnostic —
  divergence is a bug signal now, not routine).
- **W4 — mirror retirement**: `operations.ts` builders and
  `structuredEdits.ts` optimistic logic delegate to WASM; delete the
  duplicated semantics; parity suite reduced to smoke; editor tests
  migrated.
- **W5 — handshake + fallback**: version endpoint on the API, mismatch
  → server-only mode test; offline/load-failure degradation test.
- **W6 — conformance**: editor flows (drag/resize/text edit/effects
  panel) under the flag produce envelopes identical to legacy-path
  envelopes on the same gesture script; bundle-size CI assertion; full
  matrix.

---

# Integration And Merge Strategy

1. Track A merges first (small, everything depends on its measurement).
   Golden regeneration is isolated in its own commit for review.
2. B's verdicts (print check) and contracts live in this document +
   workstream memory; no code to merge. C is throwaway.
3. Wave 2 branches cut from post-A main. G and W run in parallel
   worktrees (proven pattern: E + Effects). Expected intersection: near
   zero (G: core binding/runtime + API + agent; W: bindings crate +
   editor). Whichever merges second takes the integration-merge gate
   (merge main in, full matrix, then merge out) — same procedure as the
   E/Effects integration, where the gate caught the one real semantic
   interaction.
4. Memory protocol per branch as always; this document travels via main
   to all Wave 2/3 branches.

# Consolidated Risk Register

| Risk | Mitigation |
| --- | --- |
| skia-safe build time/toolchain in CI | prebuilt binaries, cache, budgeted first day (A1 gate) |
| SkParagraph line-height/metrics semantics vs our multiplier model | pinned height-override tests in A2 before dependents |
| Golden churn from measurement change | one-time reviewed regeneration commit (A5), before G multiplies baselines |
| Conditional-expression scope creep in G | V0 grammar fixed to has/missing/eq; everything else validation-errors |
| Repeater reflow complexity | Stack/Wrap only in V0; Paginate explicitly errors (print workstream owns it) |
| WASM/JS boundary perf | scene lives in WASM memory; operations in, snapshots out; W6 perf assertion |
| Wave-2 text parity overclaim in editor | Decision E3 documents the heuristic fallback; server geometry authoritative |
| Engine version skew (deployed FE vs BE) | W5 handshake, server-only fallback |

# Acceptance Criteria (per track)

- **A**: server compile/preflight/export/critic all use Skia measurement
  and raster; wasm build green with heuristic fallback; goldens
  regenerated once; full matrix green.
- **B**: B1/B2 contracts in this doc unchallenged by G0 fixtures; B3
  verdict recorded in memory with explicit "bulk print can rely on X"
  statement.
- **C**: numbers-first spike report with go/no-go for Wave 3.
- **D**: G10 conformance — 100-instance deterministic batch, zero silent
  overflows, scan-verified QR, idempotent re-derivation, complete
  manifest.
- **E**: W6 conformance — identical envelopes vs legacy path on gesture
  scripts, mirrors deleted, handshake fallback tested, size budget held.
