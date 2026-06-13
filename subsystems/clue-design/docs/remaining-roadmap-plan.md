# Remaining Roadmap Implementation Plan (Post A–G)

Date: 2026-06-13
Status: approved sequencing; working spec for the four remaining workstreams.
Baseline: `main` at `9f9ef66` (Phases A–G complete, Effects V0, Skia
server-side, browser WASM core all merged).

## Purpose

The A–G product roadmap from the Brilliant-vs-Lumen gap analysis is built
and on `main`. Four named items remain, all explicitly parked with owners
during the phases that deferred them:

1. **Wave 3 — CanvasKit editor swap** (`editor/canvaskit-canvas-v0`): replace
   the react-konva editor canvas with CanvasKit, so editor preview and the
   server export pipeline share one rendering engine family. Spike verdict:
   GO-WITH-CAVEATS (`spike/canvaskit-editor`, `eb06b44`).
2. **Print fidelity** (`export/print-fidelity-v0`): native vector PDF with
   embedded fonts and real TrimBox/BleedBox, replacing the verified
   raster-flattened fallback that bulk print ships today. Absorbs the
   **Paginate reflow** cut (pagination is a print/multi-page-flow concern).
3. **Landing pages** (`web/landing-pages-v0`): the B1 contract — a
   responsive web artifact that shares Lumen's slot / Brand Kit / content
   contracts but **not** scene geometry. Coupling surface is the BindingSet
   `links` field, which already exists.
4. **Phase G V0 cuts** (`phase-g/personalization-runtime-v1`): the two
   personalization cuts that are G-owned — **per-instance editing** and
   **general conditional grammar**. (The third cut, Paginate, lands in
   print fidelity above; it is a layout/print concern, not a binding one.)

This document is the master spec for all four. Each is its own branch +
worktree off `main`, the established pattern.

## Codebase Grounding (read 2026-06-13)

- **Skia PDF backend is available**: `crates/lumen-skia/src/pdf_flatten.rs`
  already imports `skia_safe::pdf` (used for raster embedding in G7), so the
  pinned `skia-safe =0.97.2` build exposes the PDF document API. The native
  vector path = render to a `pdf::new_document` canvas instead of a raster
  `Surface`; Skia's PDF backend embeds typefaces from the FontCollection
  automatically. **Open question for P1**: Skia's PDF API sets MediaBox from
  page size but historically does not expose per-page TrimBox/BleedBox — P1
  must verify and, if absent, inject those boxes via a post-process pass.
- **Conditional grammar** lives in `crates/lumen-core/src/binding.rs`:
  `ConditionalExpr { Has(SlotKey), Missing(SlotKey), Eq(SlotKey, String) }`
  (line 127) with a string parser (`has`/`missing`/`eq`). Phase-G-v1 extends
  this enum + parser; everything downstream (`instance.rs` evaluation) keys
  off the enum.
- **BindingSet `links`** (the landing-page coupling) is already in
  `binding.rs` per the B2 contract: `links.landing_page.url` →
  `generated.*` (provider `qr`) → `UrlQr` slot. Landing pages consume the
  same per-instance values + URL; they do not touch the scene model.
- **Per-instance editing was cut by design** (G Decision 1: instances are
  derived artifacts, no per-instance manual editing in V0 — drift/audit
  concern). Re-introducing it is a *design decision*, not just code; v1
  gates on that decision (slice GV0).
- **The render-command semantics** the CanvasKit editor must match are
  pinned by the spike and the Skia goldens: drop-shadow `sigma = blur/2`
  via `saveLayer`; dash stroke phase requires SVG-equivalent rect contours
  (not `drawRRect`); gradient geometry `(0,0)→(cos·w, sin·h)`. The current
  `RenderNodeDescriptor` drops shadows beyond `shadow[0]` (a Konva-era
  contract limitation) — C1 fixes the contract.
- **WASM core is merged**: the editor's optimistic path is `lumen-wasm`
  (engine commit handshake, server-only fallback). CanvasKit slots in as the
  *renderer* under that same editor; it does not touch the engine boundary.

## Sequencing Across The Four

All four are largely independent and parallelizable (the proven E+Effects /
G+WASM pattern). Dependency and risk notes that order them:

| Workstream | Depends on | Blocks | Parallel-safe? | Relative size |
|---|---|---|---|---|
| `export/print-fidelity-v0` | lumen-skia (merged) | nothing (G7 flatten stays as fallback until P lands) | yes | medium |
| `web/landing-pages-v0` | BindingSet `links` (merged) | nothing | yes — greenfield app surface | large (new paradigm) |
| `editor/canvaskit-canvas-v0` | WASM core + Skia goldens (merged) | nothing | yes | large (interaction layer) |
| `phase-g/personalization-runtime-v1` | Phase G (merged) | nothing | yes | small–medium |

**Recommended cadence.** These are bigger and less coupled than prior waves,
so do not fan out all four at once. Two sensible groupings:

- **Group 1 (start now, parallel):** `export/print-fidelity-v0` and
  `phase-g/personalization-runtime-v1`. Both are server-side Rust+Python,
  both small–medium, both finish quickly and de-risk customer-facing gaps
  (print shops reject the raster fallback; conditional grammar is the most
  requested G extension). They touch nearly disjoint surfaces (export vs
  binding) — clean parallel.
- **Group 2 (start after Group 1 merges, parallel):** `editor/canvaskit-canvas-v0`
  and `web/landing-pages-v0`. Both are large, both front-end-heavy, both
  benefit from the smaller workstreams landing first (CanvasKit reuses the
  print workstream's confirmation of the shared draw-command semantics;
  landing pages can consume a stabilized binding/conditional contract).
  Landing pages opens with an internal spike (L0) the way Wave 3 did.

Each group's second-to-merge takes the integration-merge gate (merge main
in, full matrix, merge out) — the procedure that caught real interactions in
every prior wave. Cross-group, print + CanvasKit both reason about Skia draw
semantics but in different languages (Rust PDF canvas vs canvaskit-wasm in
TS); the shared artifact is the *goldens*, not source — both diff against
them, so no textual conflict.

---

# Workstream P: `export/print-fidelity-v0`

## Purpose

Replace the bulk-print raster-flattened PDF with native vector PDF: embedded
(subsetted) fonts, real vector text and shapes, and distinct
MediaBox/TrimBox/BleedBox so a print shop can locate the trim line. Close the
three B3 gaps (no font embedding, image nodes unrendered, no trim/bleed
boxes). Absorb Paginate reflow (multi-page repeater flow) since it produces
the print pages this path renders.

The raster flattener (`pdf_flatten.rs`) stays as the explicit fallback for
effects PDF cannot represent vector-natively; the support matrix decides
per-node which path applies.

## Decisions

1. **Native vector PDF via the Skia PDF backend** (`skia_safe::pdf`,
   confirmed available). A `SkiaPdfRenderer` in `lumen-skia` draws the scene
   to a PDF document canvas using the SAME scene→draw mapping as
   `SkiaSceneRenderer` (single source — refactor the shared draw logic into a
   backend-agnostic painter that targets either a raster `Surface` or a PDF
   canvas). Fonts embed automatically from the FontManager's FontCollection;
   text is real vector glyphs, not raster.
2. **TrimBox/BleedBox are mandatory for print profiles.** If Skia's PDF API
   does not emit per-page TrimBox/BleedBox (verify in P1), inject them with a
   minimal Rust PDF post-process (e.g. `lopdf`) that adds the boxes to each
   page dictionary. MediaBox = bleed extent; TrimBox = page trim;
   BleedBox = bleed extent. Page geometry comes from the scene's
   `PageSize` + `bleed` (already mm-correct per B3).
3. **Per-node fidelity is matrix-driven, never silent.** Extend the
   `RendererEffectSupport` matrix: PDF vector path is `Native` for solid/
   gradient fills, strokes (dash/cap/join), text, and drop shadows Skia's PDF
   backend supports; `Approximate`→raster-flatten the node's region for
   effects PDF cannot vector-encode (e.g. complex multi-shadow with spread if
   Skia PDF degrades them); diagnostics (`LUME04xx`) state which path each
   node took. No effect renders wrong; it renders native, raster-fallback, or
   diagnoses.
4. **Pagination V0 is repeater-driven and conservative** (the absorbed
   Paginate cut). When a repeater's items exceed the page content box, flow
   continuation items onto cloned continuation pages (same page template,
   header/footer preserved if marked). V0 scope: repeaters only; top-to-bottom
   flow; no orphan/widow control; no flowing of non-repeater content. Anything
   beyond → explicit validation error (same discipline G used to defer it).
   Lives here because the print PDF is the consumer and pagination only
   matters for multi-page print artifacts.
5. **Phase G bulk export upgrades to vector PDF when the artifact qualifies.**
   G7's flatten path becomes the fallback branch; the export profile + support
   matrix choose vector-first. The print-size/DPI diagnostics and the QR
   scan-back conformance carry over unchanged (a vector-PDF QR is an embedded
   image XObject or vector path — must still scan).

## Slices

- **P0 — baseline + failing tests.** Mailer fixture from B3 (DL, 3mm bleed,
  safe area, text, QR image, a gradient + shadow node); failing tests naming
  the vector surface: font embedded (`pdffonts` shows `emb yes`), TrimBox ≠
  MediaBox, image node present, QR scans from the 300dpi render, vector text
  selectable (`pdftotext` returns the headline).
- **P1 — Skia PDF spike-gate + shared painter refactor.** Stand up
  `pdf::new_document`, render one fixture, confirm (a) fonts embed,
  (b) whether TrimBox/BleedBox are settable via Skia or need the lopdf
  post-process — **decide and record before building further**. Refactor the
  draw logic out of `SkiaSceneRenderer` into a `ScenePainter` that targets a
  generic Skia `Canvas` (raster surface or PDF canvas), so raster and vector
  share one implementation. Gate: the existing raster goldens are byte-stable
  after the refactor (no behavior change), PDF backend produces a parseable
  document.
- **P2 — vector PDF render + boxes.** `SkiaPdfRenderer` behind the existing
  PDF export interface; MediaBox/TrimBox/BleedBox per Decision 2; embedded
  fonts; vector text/shapes/gradients; image nodes drawn (the B3 image gap
  closed). Diagnostics replace the `LUME04xx` "cannot embed / not rendered"
  warnings with "embedded / rendered vector" info, retaining warnings only
  where the matrix forces raster fallback.
- **P3 — support matrix + per-node fallback.** Extend `RendererEffectSupport`
  for the PDF-vector path; nodes the vector path cannot represent fall back to
  region raster (reuse `pdf_flatten` machinery per-region); every fallback
  emits a precise diagnostic. Tests: a node forced to fallback raster-embeds
  and diagnoses; everything else stays vector.
- **P4 — pagination (Paginate reflow).** Layout pass detecting repeater
  overflow past the page content box; continuation-page generation; the
  `ReflowPolicy::Paginate` path in `instance.rs` stops being a validation
  error and produces multi-page output. Tests: a repeater with N items over
  capacity produces ⌈N/per-page⌉ pages; non-repeater overflow still errors;
  derived scene stays valid; deterministic.
- **P5 — Phase G wire-up + conformance.** G7 bulk export selects vector-first
  with raster fallback; the conformance batch re-runs producing vector PDFs;
  QR scans from the vector PDF; `pdffonts`/`pdfinfo -box`/`pdftotext` assert
  embedding, boxes, and selectable text across the batch. Full matrix.

## Risks

- **TrimBox/BleedBox not exposed by Skia PDF** → the lopdf post-process
  fallback (P1 decides). Bounded; PDF page-dict editing is well-trodden.
- **Skia PDF shadow/effect fidelity** differs from raster → the support
  matrix + per-region raster fallback (P3); never silent.
- **Painter refactor regresses raster goldens** → P1 gates on byte-stable
  raster output before any vector work.
- **Font subsetting licensing** → Inter is OFL (embeddable/subsettable);
  record the embedding-permission check; non-embeddable brand fonts (future)
  diagnose, not crash.

---

# Workstream L: `web/landing-pages-v0`

## Purpose

Per the B1 decision: a personalized landing page is responsive, flowing web
content — forcing it into the fixed-canvas scene model would be a category
error. Build the landing-page renderer as a **separate app surface** that
shares Lumen's slot, Brand Kit, and content contracts but renders as
responsive web, consuming the same per-instance binding values the design
engine produces. The design engine's responsibility ends at per-instance URL
allocation + the QR encoding it (both already shipped in Phase G); this
workstream builds what that URL serves.

## Decisions

1. **Not a scene; a web template.** Landing pages do not use `Scene`/`Node`/
   layout. They are a responsive template (section-based: hero, body,
   CTA, proof points, contact) bound to the SAME slot keys and BindingSet
   values an artifact uses, themed by the SAME Brand Kit tokens. The shared
   contract is the data (slots, binding values, brand tokens), not the
   geometry.
2. **Rendering stack decided by L0 spike.** Candidates: Next.js SSR/SSG (the
   editor is already Next.js — shared tooling), static per-instance HTML
   generation at batch time, or runtime-rendered with a URL→binding lookup.
   Decision criterion: per-instance URLs must resolve fast, be cacheable, and
   reuse Brand Kit token resolution. Lean SSG-per-instance or runtime SSR with
   a binding-set lookup; L0 picks one against a real binding set + brand kit.
3. **Brand tokens resolve through the existing resolver.** Reuse
   `lumen-core`'s Brand Kit token resolution (colors, type scale, spacing)
   compiled to CSS custom properties / a theme object — one brand source for
   artifact and landing page, so they visibly match.
4. **Slot content types map to web semantics.** `text_short`→heading/label,
   `text_long`→prose block, `image`/`logo`→responsive `<img>` with the same
   fit/focal policy, `url_qr`→the page IS the QR target (no QR on the page
   itself), `list`/`repeater`→repeated web sections. Overflow is not a
   fixed-box concern on the web (content reflows), so the artifact's
   overflow policies do not apply; instead validate presence/required.
5. **The coupling surface is read-only and minimal.** Landing pages consume
   `BindingSet.values` + `links` + the brand ref; they never mutate scenes,
   binding sets, or template revisions. No new write coupling into the design
   engine.

## Slices

- **L0 — spike + stack decision (internal, time-boxed).** Render one real
  binding set (the Phase G mailer's `account.name`/`contact.full_name`/
  `campaign.cta`/insights) into a responsive page themed by a real Brand Kit,
  in each candidate stack; measure render path, cacheability, brand-token
  reuse, build complexity. Deliverable: a stack decision recorded in memory +
  this doc, and a working minimal render. (Mirrors the CanvasKit spike's
  evidence-first discipline.)
- **L1 — landing-page template contract.** A `LandingTemplate` model (sections,
  each bound to slot keys + content type), validated against a revision's slot
  summary the way BindingSet validation works; brand-ref attached. Wasm-clean
  if it lives in lumen-core; otherwise an app-side schema sharing the
  slot/brand types.
- **L2 — renderer.** The chosen stack renders `LandingTemplate` + BindingSet +
  Brand Kit → responsive HTML/CSS with brand tokens as CSS variables;
  responsive breakpoints; accessible semantics. Visual checks at mobile/desktop
  widths.
- **L3 — per-instance serving + URL.** Resolve `links.landing_page.url` →
  the rendered page for that binding set; the URL the QR already encodes now
  serves real content. Caching/immutability headers; 404 for unknown
  instances.
- **L4 — batch generation + brand match.** Generate pages for a binding-set
  batch (alongside Phase G's artifact batch); assert the landing page and the
  mailer for the same recipient share brand tokens and content (the QR on the
  printed mailer resolves to the matching page). Conformance: a batch of N
  binding sets produces N reachable, brand-consistent pages; the QR→URL→page
  chain end-to-end scan-and-fetch verified.

## Risks

- **Scope creep into a CMS/page builder** → V0 is template-bound rendering
  only; no visual landing-page editor (that is a far-future product call).
- **Brand-token→CSS fidelity drift** vs the artifact → both resolve from the
  same Brand Kit; L4 asserts shared tokens, not eyeball matching.
- **Hosting/serving model** is a platform decision beyond the design engine →
  L0 picks the simplest reachable option (static gen or SSR) and flags the
  production hosting as a deployment concern, not a blocker.

---

# Workstream C: `editor/canvaskit-canvas-v0` (Wave 3)

## Purpose

Swap the react-konva editor canvas for CanvasKit so the editor preview and
the server export share one rendering engine family (Skia). The spike proved
fidelity (0.003% perceptual diff vs the canonical raster, including the
two-shadow stack, gradient stack, and dashed round-cap stroke Konva can only
approximate). The work is the caveats: bundle strategy, descriptor-contract
extension, the immediate-mode interaction layer (Konva gave hit-testing and
event delegation for free; CanvasKit does not), text, and a flag-gated
cutover with Konva retained as fallback.

## Decisions

1. **CanvasKit default build** (has ParagraphBuilder; the +350 KB `full`
   build is unnecessary — spike-verified). Lazy-load the ~2.9 MB gzip wasm
   (2.24 MB brotli) behind the editor route with `Cache-Control: immutable`;
   it is not on the first-paint path. Skia version must match the server's
   pinned `skia-safe =0.97.2` family (the recorded version contract).
2. **Variable Inter TTF** (`InterVariable.ttf`, 460 KB gzip), not the four
   static weights (800 KB gzip) — fewer fetches, all weights. woff2 is NOT
   loadable by CanvasKit (spike); ship TTF.
3. **Extend `RenderNodeDescriptor` to carry the full shadow stack and
   SVG-contour stroke geometry.** The current contract drops shadows beyond
   `shadow[0]` (Konva-era limitation) and dashes assume `drawRRect`. C1 adds
   `allShadows` and encodes the SVG-equivalent rect-contour convention the
   spike found (else dash phase shifts around the border). This is the one
   shared lumen-core/`renderAdapter.ts` change; it is additive and Konva
   ignores the new fields, so Konva keeps working during the flag period.
4. **Hit-testing moves to a shared geometry surface, not the renderer.**
   Konva gave retained-scene hit-testing for free; CanvasKit is immediate-
   mode. Rather than rebuild hit-testing in TS, put point→node hit-testing in
   `lumen-core` (it is geometry over computed bounds — the agent benefits too,
   and it stays consistent across renderers) and expose it through `lumen-wasm`.
   This is the single largest slice and the real cost of the swap.
5. **Flag-gated, Konva retained as fallback** behind
   `NEXT_PUBLIC_LUMEN_CANVASKIT` (parallel to the WASM-core flag). Cutover is
   a parity exercise: the CanvasKit editor render must match the Skia export
   goldens; Konva stays until parity + interaction conformance hold.
6. **Manual wasm-memory discipline** (Paint/Path/Surface/Paragraph/shaders are
   wasm-heap objects) handled by a small RAII-style helper + a lint convention;
   a long-session leak test guards it.

## Slices

- **C0 — build + bundle integration.** canvaskit-wasm dependency; lazy-load +
  brotli + immutable caching; variable-font fetch (one `FontMgr`); module
  singleton init promise; size + cold-init assertions in CI (budget the
  ~2.9 MB gzip explicitly, distinct from the 684 KB WASM-core budget). Gate:
  editor builds and loads CanvasKit lazily without regressing first paint.
- **C1 — descriptor contract extension.** `RenderNodeDescriptor` gains
  `allShadows` (full effect stack) and SVG-contour stroke paths; `renderAdapter.ts`
  populates them; the edit-parity and effects-render-parity fixtures extend to
  cover them; Konva path unaffected (ignores new fields). Shared
  lumen-core/editor change — lands first so both renderers read one contract.
- **C2 — CanvasKit stage + descriptor interpreter.** The spike's
  `CanvasKitStage` + `drawNode` mapping, productized: gradients, paint stacks,
  dash/cap/join via SVG-contour paths, drop-shadow stack via `saveLayer` +
  chained `MakeDropShadow` (sigma=blur/2), images via `drawImageRect`;
  WebGL2 surface with CPU fallback; ResizeObserver-driven surface recreate
  with devicePixelRatio backing; dirty-flag + single rAF redraw; RAII memory
  helper. Render-parity test: CanvasKit stage output vs the Skia export
  goldens (the spike's 0.003% bar).
- **C3 — interaction layer (the big one).** Point→node hit-testing in
  lumen-core exposed via lumen-wasm; selection (single, marquee), drag, resize
  with handles, hover — rebuilt on a custom event→hit-test→gesture pipeline
  (Konva's event delegation is gone). Every gesture still emits the same
  canonical operations through the WASM engine (no new mutation path).
  Conformance: the W6 gesture script (drag/resize/text/effects/page-rename)
  through the CanvasKit path produces envelopes identical to the Konva path.
- **C4 — text rendering + edit overlay.** SkParagraph-driven text layout in
  the editor (the same Inter font bytes the server uses — bit-faithful breaks,
  closing the heuristic-divergence the spike measured on caps/digits/hyphens);
  text editing via a positioned DOM input overlay (CanvasKit, like Konva,
  cannot host a live caret). Note: this makes the editor's in-browser text
  measurement match the server for the first time (the WASM core's E3 honesty
  caveat — heuristic in-browser — is resolved here via CanvasKit's SkParagraph,
  the planned Wave 3 path).
- **C5 — flag-gated cutover + parity.** Both renderers selectable; the full
  editor test suite runs under the CanvasKit flag; visual-regression parity vs
  Skia export goldens; leak test over a long session; bundle/init CI gates.
- **C6 — conformance + Konva retirement decision.** Interaction conformance
  (C3 envelopes) + render parity (C2/C5) green under the flag; decide whether
  to delete Konva or keep it one release as fallback (recommend: keep behind
  the flag one release, delete in a follow-up once the CanvasKit path has
  soaked).

## Risks

- **Interaction feel** (drag/resize latency, handle precision) needs real
  browser QA, not just unit tests → C3/C5 include manual interaction QA and a
  frame-budget check on a 100+-node scene (the spike flagged `saveLayer` cost
  for shadowed nodes at scale).
- **wasm-memory leaks** in long sessions → RAII helper + the C5 soak/leak test.
- **Bundle weight** on first editor load → lazy-load + brotli + immutable
  cache (C0); it is off the first-paint path.
- **Hit-testing correctness** under transforms/rotation/clip → lumen-core
  hit-testing tested against the same geometry the renderer uses; rotated/
  skewed nodes (the effects model has them) get explicit cases.

---

# Workstream GV1: `phase-g/personalization-runtime-v1`

## Purpose

The two Phase-G-owned V0 cuts: **general conditional grammar** (extend beyond
`has`/`missing`/`eq`) and **per-instance editing** (instance-level overrides
that survive re-derivation). Both were deliberately deferred — conditional
grammar to keep V0 scope fixed, per-instance editing because it raises a
genuine drift/audit design question. (Paginate, the third cut, lands in the
print workstream.)

## Decisions

1. **Conditional grammar extends the existing enum, stays a closed grammar.**
   `ConditionalExpr` gains `And`/`Or`/`Not` combinators and comparison forms
   (`ne`, `in(slot, [literals])`, `gt`/`lt` for numeric/stat slots) — a
   bounded boolean algebra over slot predicates, NOT a general expression
   language (no arithmetic, no string ops, no user functions). Anything
   outside the grammar is a validation error naming the unsupported form
   (the same discipline V0 used). Parser + evaluator extend in lockstep with
   golden expression tests.
2. **Per-instance editing is override-based, not free editing, and re-derivation
   reconciles.** An instance carries an optional **override set**: a small,
   audited list of per-slot value/asset overrides layered on top of the
   binding set at derivation time. Re-derivation re-applies overrides (they
   are inputs, like the binding set), so instances stay derived artifacts —
   NOT mutable scenes. This preserves G Decision 1's invariant (instances are
   a pure function of inputs) while letting a user fix one recipient. Overrides
   that no longer apply (slot removed in a new revision) surface as
   diagnostics, never silently drop. **GV0 gates on ratifying this model**
   before any code — it is the design decision that got the feature cut.
3. **No instance-level scene mutation surface.** Overrides are binding-layer
   data, validated like binding values; they never produce ad-hoc operations
   on a derived scene. This is the line that keeps audit and batch
   re-derivation coherent.

## Slices

- **GV0 — ratify the per-instance override model (design gate).** Write the
  override contract (where it attaches, how re-derivation layers it, how
  conflicts/stale overrides surface) and confirm it against the audit/drift
  concern that cut the feature. No code until the model is recorded. (If the
  override model proves insufficient for a real need, that is the signal to
  escalate — but the override approach is the recommended default.)
- **GV1 — conditional grammar extension.** Extend `ConditionalExpr` +
  parser + `instance.rs` evaluator with the bounded boolean algebra;
  exhaustive grammar tests (each new form, each rejection); existing G
  conditional fixtures still pass; deterministic.
- **GV2 — per-instance override contract.** `InstanceOverrideSet` in
  `binding.rs` (per-slot value/asset overrides), validated against the
  revision slot summary; derivation layers overrides over binding values;
  stale/invalid overrides diagnose. Round-trip determinism: same
  (binding + overrides) → identical instance.
- **GV3 — API + agent/editor surface.** Override CRUD on an instance
  (validated on write); re-derivation honors overrides; the agent/editor can
  set an override (the audited per-recipient fix path). Conformance: a batch
  where one instance has an override derives correctly and stays idempotent;
  the override is visible in the instance's audit.

## Risks

- **Override model proves too narrow** for a real user need (e.g. they want to
  move an element, not just change a value) → GV0 surfaces this before code;
  the honest answer if so is "that need is template-level (new revision), not
  instance-level," preserving the invariant — or a scoped escalation.
- **Conditional grammar creep** → the grammar stays closed; rejection tests
  guard the boundary.

---

# Integration And Merge Strategy

1. **Group 1 first** (`export/print-fidelity-v0`, `phase-g/personalization-runtime-v1`):
   parallel worktrees off `main`, disjoint surfaces (export vs binding).
   Second-to-merge takes the integration-merge gate (merge main in, full
   matrix, merge out).
2. **Group 2 after Group 1 merges** (`editor/canvaskit-canvas-v0`,
   `web/landing-pages-v0`): cut fresh from the updated `main`. CanvasKit and
   landing pages touch mostly disjoint surfaces (Rust/editor renderer vs new
   web app), but both read the brand/slot/binding contracts — second-to-merge
   takes the gate.
3. **Per-branch memory protocol** as always; this document travels via `main`
   to every new branch.
4. **Verification bar unchanged**: every slice green before commit (fmt,
   clippy `-D warnings`, cargo test, wasm32 checks, pytest when Python is
   touched, editor test/lint/build when the editor is touched); end-to-end
   proofs over mocks; final reports carry verification evidence; the lead
   re-verifies from a clean checkout before each merge.

# Consolidated Risk Register

| Risk | Owner | Mitigation |
|---|---|---|
| Skia PDF lacks TrimBox/BleedBox API | P | P1 spike-gate decides; lopdf post-process fallback |
| Painter refactor regresses raster goldens | P | P1 gates on byte-stable raster before vector work |
| Pagination scope creep | P | V0 = repeaters only, top-to-bottom, no orphan/widow; else error |
| Landing-page stack/hosting unknown | L | L0 spike picks the simplest reachable stack; hosting flagged as deployment |
| Landing scope creep into a page builder | L | V0 = template-bound rendering only, no visual editor |
| CanvasKit interaction feel | C | C3/C5 manual browser QA + frame-budget check at scale |
| wasm-memory leaks (CanvasKit) | C | RAII helper + C5 soak/leak test |
| Hit-testing correctness under transforms | C | lumen-core hit-testing, rotated/skewed/clip cases |
| Per-instance override model insufficient | GV1 | GV0 design gate before code; template-level is the honest fallback |
| Conditional grammar creep | GV1 | Closed grammar + rejection tests |

# Acceptance Criteria (per workstream)

- **P**: bulk-print PDFs are native vector — `pdffonts` shows embedded fonts,
  `pdfinfo -box` shows distinct TrimBox/BleedBox, `pdftotext` returns
  selectable headline text, image nodes render, QR scans from the vector PDF;
  Paginate produces correct multi-page repeater output; raster fallback only
  where the matrix forces it, always diagnosed; full matrix green.
- **L**: a binding-set batch produces N reachable, brand-consistent landing
  pages; the QR on the matching printed mailer resolves to its page (end-to-end
  scan→fetch); pages share Brand Kit tokens with the artifact; no write
  coupling into the design engine.
- **C**: CanvasKit editor render matches the Skia export goldens (spike's
  0.003% bar); the W6 gesture script produces envelopes identical to the Konva
  path; in-browser text breaks match the server (SkParagraph); bundle/init/leak
  CI gates hold; flag-gated with Konva fallback intact.
- **GV1**: extended conditional grammar evaluates and rejects per spec;
  per-instance overrides layer at derivation and survive re-derivation
  idempotently; instances remain pure functions of (binding + overrides);
  audit shows overrides; full matrix green.

# Housekeeping (do before Group 1 launch)

The five merged/throwaway worktrees from prior waves are stale and clutter the
workspace (`engine-effects-contract-v0`, `engine-skia-text-raster-v0`,
`engine-wasm-editor-core-v0`, `phase-g-personalization-runtime-v0` — all
merged to `main`; `spike-canvaskit-editor` — harvested, report on its branch).
Remove the worktrees (branches are preserved in history/merge commits; the
spike branch is kept for its report). This keeps `git worktree list` legible
for the next round.
