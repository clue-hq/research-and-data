# Canonical Artboard Geometry V0 Implementation Plan

Date: 2026-06-14

Branch: `engine/canonical-artboard-geometry-v0`

Worktree: `/Users/aryankeshri/Documents/brilliant-design/engine-canonical-artboard-geometry-v0`

Base: `editor/canvaskit-canvas-v0` at `8cc5c7d`

## Purpose

This is the first implementation slice after the artboard/workspace planning
workstream.

The goal is to fix the page/artboard coordinate contract before building the
infinite editor workspace or changing agent generation defaults. The immediate
failure class is the A4 mismatch seen in agent run traces: the page is
`210 x 297 mm`, while children are authored as if the page were roughly
`595 x 842` layout units. Renderer scaling cannot know whether `400` means
400 px, 400 pt, or 400 mm, so fixing only CanvasKit, SVG, or a unit multiplier
would preserve the ambiguity.

This slice creates one canonical artboard layout coordinate system and moves
physical/raster output metadata out of the child geometry interpretation path.

## Implementation Status

Status: implemented and verified on 2026-06-14.

What landed:

- `PageSize` now supports canonical `pt` layout dimensions plus optional
  `source` and `output` metadata.
- `lumen-core::page_geometry` is the shared normalization and conversion
  surface for presets, custom sizes, physical metadata, raster defaults, layout
  bounds, page rects, and physical-size conversion.
- DSL page creation and page modification normalize new pages into canonical
  `pt` layout geometry. Legacy non-pt scenes still load and export.
- Validation emits `LUMV0805` advice for legacy non-pt page geometry and
  `LUMV0800`-`LUMV0803` for artboard/parent bounds and invalid canonical
  geometry cases.
- Layout, SVG, PNG, PDF, Skia raster, flattened PDF, export sidecars, export
  checks, editor descriptors, editor page creation, and editor export parity now
  consume the canonical layout contract.
- Editor export parity compares canonical `pt` SVG exports against the SVG
  `viewBox`, so physical print attributes such as `width="210mm"` do not
  override the canonical artboard bounds.
- Editor-created pages write canonical `pt` page sizes while preserving
  user-facing requested dimensions in `PageSize.source`; digital pages record
  raster defaults in `PageSize.output.raster`.
- Editor export warnings use the same TS page-geometry conversion helpers for
  physical/raster size estimates instead of maintaining a private conversion
  table.
- DSL compiler docs and agent knowledge now list `pt` as a supported page-size
  source unit and describe that new page commands normalize into canonical
  artboard layout bounds while preserving source/export size metadata.

Verification passed:

```bash
cargo check --workspace --tests
cargo test -p lumen-core
cargo test -p lumen-export
cargo test -p lumen-skia
cargo test -p lumen-agent
cargo test -p lumen-api-helper -p lumen-assets -p lumen-wasm
cargo test -p lumen-core --test layout_engine
cargo test -p lumen-core --test dsl_compiler
cargo test -p lumen-export
cargo test -p lumen-agent
cargo test --workspace
npm --prefix apps/editor test -- --run src/engine/__tests__/exportParity.test.ts src/engine/__tests__/renderAdapter.test.ts
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx src/components/__tests__/InspectorPanel.test.tsx
npm --prefix apps/editor test -- --run --testTimeout 20000
npm --prefix apps/editor run lint
git diff --check
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_phase_g_conformance.py -q
```

Verification notes:

- `apps/api/tests/test_api.py` passed 63 tests.
- `apps/api/tests/test_phase_g_conformance.py` passed 2 tests, but took about
  11.75 minutes; use narrow selectors or external timeouts for future reruns.
- Final non-browser completion audit on 2026-06-14 reran
  `cargo test --workspace`, the full editor Vitest suite with
  `--testTimeout 20000`, editor lint, `apps/api/tests/test_api.py`,
  `apps/api/tests/test_phase_g_conformance.py`, and `git diff --check`; all
  passed.
- The first broad API run was useful only after helper subprocess access was
  fixed; subsequent API verification should stay narrowed.
- A current full editor run with Vitest's default 5s per-test timeout hit
  unrelated local timeouts in slow WASM/React component tests. The affected
  component files pass when isolated. A concurrent full editor run while
  `cargo test --workspace` was compiling also timed out in the CanvasKit soak
  test. The standalone full 41-file editor suite passes with
  `--testTimeout 20000` (`298` tests).
- Browser-rendered editor smoke validation is intentionally out of scope for
  this session by user instruction and will be handled separately with the Codex
  Browser plugin; no Playwright/browser tests are part of the current
  verification set.

## Acceptance Audit

Status as of 2026-06-14:

| Criterion | Evidence |
| --- | --- |
| New DSL/page creation writes canonical `Unit::Pt` pages | `crates/lumen-core/tests/dsl_compiler.rs`; `cargo test --workspace` |
| A4 layout bounds are about `595.276 x 841.89` | `crates/lumen-core/src/page_geometry.rs`; canonical A4 editor/layout tests |
| Custom `1080 x 1080 px` remains authorable/exportable as `1080 x 1080` raster default | DSL/editor/export parity tests; `npm --prefix apps/editor test -- --run --testTimeout 20000` |
| Physical print metadata is preserved separately from layout bounds | `PageSize.source` / `PageSize.output.physical`; SVG/PDF/sidecar/export tests |
| SVG/PDF/PNG/Skia/editor consume canonical layout dimensions | shared `page_geometry` helpers; `cargo test --workspace`; editor parity tests |
| Bounds preflight catches page/artboard overflow and parent overflow | focused `layout_engine` tests for `LUMV0800`, `LUMV0801`, and `LUMV0802` |
| Existing non-pt scenes are not silently rewritten | legacy `LUMV0805` validation test and legacy fixture compatibility tests |
| Editor descriptor no longer treats canonical A4 child coordinates as mm | canonical A4 render-adapter test; browser-rendered smoke deferred |
| Coverage includes A4, US Letter, Envelope DL, square, wide/tall custom, mm custom, pt custom, bleed, PNG raster defaults, physical DPI, and legacy non-pt | DSL preset/unit tests, Phase F manifest tests, layout bounds tests, export adapter tests, PNG sizing unit tests |

## Non-Goals

- Do not build the infinite workspace UI in this branch.
- Do not add loose workspace objects outside exportable artboards.
- Do not rewrite the agent prompt/knowledge protocol beyond narrow docs/tests
  needed to prove the new geometry contract.
- Do not redesign auto-layout or targeted repair semantics.
- Do not remove legacy non-canonical scene support until a migration path exists.

## Pre-Implementation Grounding

Relevant code facts at branch start:

- `crates/lumen-core/src/scene.rs` stores `Page.size` as
  `PageSize { width, height, unit, preset, orientation }`.
- `Unit` currently supports `px`, `mm`, and `in`; there is no `pt` canonical
  layout unit.
- `crates/lumen-core/src/dsl.rs::page_size_for_preset` lowers A4 to
  `210 x 297 mm`, US Letter to `8.5 x 11 in`, LinkedIn to `1200 x 627 px`,
  and Custom to A4-like `210 x 297 mm`.
- Explicit custom page DSL already exists as `page id size(width,height,unit)`,
  and `size(1080,1080,px)` lowers to `PageSize { unit: Px, preset: Custom }`.
- `apps/editor/src/engine/renderAdapter.ts` multiplies page and node geometry by
  `unitScale(page.size.unit)`. A page in `mm` therefore causes every child
  number to be treated as mm on the editor surface.
- `crates/lumen-core/src/layout.rs` uses `page.size.width/height` directly as
  the parent size for layout.
- SVG, PNG, PDF, Skia raster, flattened PDF, export parity, and editor
  descriptors each contain page-unit conversion logic today.

Relevant docs at branch start:

- The product spec defines Page/Artboard as an exportable surface and says the
  document can contain multiple pages/artboards.
- Phase F already requires custom sizes to be first-class and presets to be
  shortcuts, not renderer/export capability boundaries.
- The Brilliant comparison records the square-ad failure as a mismatch between
  requested output size and actual `PageSize`, and recommends explicit
  page/artboard dimensions plus guardrails.
- The reverse-engineering report identifies the Brilliant pattern we should
  preserve: background fills live on parent frames, auto-layout is the default
  containment mechanism, and lint catches ghost frames/overflow cases.

## Core Decision

Use `pt` as the canonical layout unit for all new page/artboard scene geometry.

For new canonical scenes:

- `PageSize.width` and `PageSize.height` are layout bounds in `pt`.
- `PageSize.unit` is `pt`.
- Node `transform`, `size`, `computed`, stroke widths, font sizes, effects,
  safe areas, and bleed rectangles are interpreted in the same page-local
  layout coordinate space.
- Physical print size and default raster output size are stored as metadata,
  not as the unit used to interpret child geometry.
- Export adapters convert from the canonical layout bounds to SVG/PDF/PNG
  output targets.

The practical mapping:

| User/artifact input | Canonical layout | Output metadata |
| --- | --- | --- |
| A4 portrait | `595.276 x 841.89 pt` | physical `210 x 297 mm` |
| US Letter portrait | `612 x 792 pt` | physical `8.5 x 11 in` |
| LinkedIn square | `1080 x 1080 pt` | raster default `1080 x 1080 px` |
| Custom `6 x 4 in` | `432 x 288 pt` | physical `6 x 4 in` |
| Custom `210 x 297 mm` | `595.276 x 841.89 pt` | physical `210 x 297 mm` |

For digital pixel-sized artifacts, `1 authored px` maps to `1 layout pt` for
authoring. The raster pixel dimensions are preserved in raster metadata. This
keeps square/social/email artifacts ergonomic without making renderer pixels the
scene model's semantic unit.

## Scene Contract Shape

V0 should evolve `PageSize`, not add a second persisted page geometry object
that can drift.

Add:

```rust
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageSize {
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
    pub preset: Option<PagePreset>,
    pub orientation: Orientation,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<PageSizeSource>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output: Option<PageOutputSize>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageSizeSource {
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageOutputSize {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub physical: Option<PhysicalPageSize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub raster: Option<RasterPageSize>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PhysicalPageSize {
    pub width: f64,
    pub height: f64,
    pub unit: PhysicalUnit,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RasterPageSize {
    pub width_px: u32,
    pub height_px: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Unit {
    Pt,
    Px,
    Mm,
    In,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PhysicalUnit {
    Mm,
    In,
}
```

Notes:

- `Unit::Px`, `Unit::Mm`, and `Unit::In` remain for legacy scene loading and
  source metadata.
- New DSL/editor-created pages should write `unit: Pt`.
- `PageSizeSource` records what the user or preset asked for. It is useful for
  inspector display and round-tripping without changing geometry semantics.
- `PageOutputSize` records export defaults. It does not drive layout.
- Manual TypeScript contracts in `apps/editor/src/engine/contracts.ts` must be
  updated with optional `source` and `output` fields.

Add a non-persisted helper in `lumen-core`, for example
`crates/lumen-core/src/page_geometry.rs`:

```rust
pub struct PageGeometry {
    pub layout: Rect,
    pub source: Option<PageSizeSource>,
    pub physical: Option<PhysicalPageSize>,
    pub raster: Option<RasterPageSize>,
}

pub fn page_geometry(page: &Page) -> PageGeometry;
pub fn normalize_page_size(input: PageSizeInput) -> PageSize;
pub fn unit_to_points(value: f64, unit: &Unit) -> f64;
pub fn points_to_physical(value_pt: f64, unit: &PhysicalUnit) -> f64;
```

All layout/editor/export code should call this helper rather than maintaining
local page-size conversion tables.

## Compatibility Rule

Do not silently guess old ambiguous scenes.

V0 should support two modes:

1. Canonical mode: `page.size.unit == Unit::Pt`. All node geometry is page-local
   layout geometry. This is the only mode new DSL/editor pages should produce.
2. Legacy mode: `page.size.unit != Unit::Pt`. Preserve existing behavior enough
   to open/export old scenes, but emit an advisory diagnostic such as
   `LUMV0805 LEGACY_PAGE_UNIT`.

Do not auto-scale old child geometry during normal load/export. Some old scenes
used mm/in consistently, while the broken A4 traces used pt-like child values
inside an mm page. A silent migration cannot distinguish those intents. If a
bulk migration is needed later, implement it as an explicit migration command
with reviewable diffs.

## DSL Lowering Plan

Files:

- `crates/lumen-core/src/dsl.rs`
- `crates/lumen-core/tests/dsl_compiler.rs`
- `docs/dsl-compiler.md`
- agent knowledge docs only if tests expose stale guidance

Work:

1. Add `pt` to `parse_unit`, diagnostics, and TypeScript contract.
2. Replace `page_size_for_preset` with a normalizer that returns canonical
   `PageSize`.
3. Lower A4/US Letter/Envelope presets to `Unit::Pt` layout size with physical
   metadata.
4. Lower pixel custom sizes to `Unit::Pt` layout size with raster metadata.
5. Lower mm/in custom sizes to `Unit::Pt` layout size with physical metadata.
6. Preserve existing syntax `size(width,height,unit)` in V0. Sugar such as
   `size(210mm,297mm)` can be added later.
7. Update page modification lowering so `#page size(...)` uses the same
   normalizer as page creation.
8. Keep finite/positive validation and extend error hints to include `pt`.

Expected new tests:

- `dsl_a4_preset_lowers_to_canonical_pt_with_physical_metadata`
- `dsl_letter_preset_lowers_to_canonical_pt_with_physical_metadata`
- `dsl_custom_px_lowers_to_pt_with_raster_default`
- `dsl_custom_mm_lowers_to_pt_with_physical_metadata`
- `dsl_page_modify_size_uses_same_normalizer`
- `dsl_page_size_accepts_pt`

## Layout And Bounds Preflight

Files:

- `crates/lumen-core/src/layout.rs`
- `crates/lumen-core/src/preflight.rs`
- `crates/lumen-core/src/diagnostics.rs`
- `crates/lumen-core/tests/layout_engine.rs`
- `crates/lumen-core/tests/preflight_pipeline.rs`

Work:

1. Make page layout use `page_geometry(page).layout.width/height` for canonical
   pages.
2. Keep layout result geometry in canonical layout units.
3. Add an artboard-bounds validation step after layout geometry is produced.
4. Validate page children against the page trim bounds.
5. If `page.bleed` exists, treat content outside trim but inside bleed as a
   warning, not an export-blocking error.
6. Validate children against parent bounds. Use stricter severity when the
   parent clips or when the parent is the artboard/root surface; otherwise use a
   warning/advice diagnostic for visible overflow.
7. Use computed layout bounds when present. Fall back to authored fixed
   transform/size when a node has not been laid out.
8. Do not include shadows/effects in V0 overflow math; record this as an
   explicit limitation.

Suggested diagnostic codes:

- `LUMV0800`: page/artboard child exceeds exportable bounds.
- `LUMV0801`: child exceeds parent bounds.
- `LUMV0802`: child lies outside trim but inside bleed.
- `LUMV0803`: page has invalid canonical geometry.
- `LUMV0805`: legacy non-pt page unit detected.

Expected new tests:

- A4 page with a `595 x 842` background does not overflow after canonical
  lowering.
- A4 page with a `700 x 900` child emits `LUMV0800`.
- A child wider than a clipped frame emits `LUMV0801`.
- A child outside trim but inside bleed emits `LUMV0802`.
- Non-pt legacy page emits `LUMV0805` but remains openable.

## Export Adapter Plan

Files:

- `crates/lumen-export/src/svg.rs`
- `crates/lumen-export/src/png.rs`
- `crates/lumen-export/src/pdf.rs`
- `crates/lumen-export/src/sidecar.rs`
- `crates/lumen-skia/src/render.rs`
- `crates/lumen-skia/src/pdf_flatten.rs`
- `crates/lumen-export/tests/export_adapter.rs`
- `crates/lumen-skia/tests/raster_export.rs`

Work:

1. Move unit conversion out of each adapter into the `page_geometry` helper.
2. SVG:
   - Use canonical layout bounds for `viewBox`.
   - For print pages with physical metadata, emit physical `width`/`height`
     such as `210mm x 297mm` while keeping a pt viewBox.
   - For digital/raster pages, preserve output dimensions where appropriate,
     e.g. `viewBox="0 0 1080 1080"`.
3. PNG:
   - If the profile explicitly supplies scale/DPI, use it.
   - If raster metadata exists and no explicit raster override exists, use the
     stored default raster size.
   - If physical metadata exists and DPI is supplied, use physical inches times
     DPI.
   - Otherwise use canonical layout size times scale.
4. PDF:
   - MediaBox is in points, so canonical pt layout maps directly.
   - Include bleed by using canonical pt bleed bounds.
   - Print guardrail mixed-size comparison should compare canonical layout and
     output metadata, not raw source units.
5. Skia raster:
   - Scale raster surfaces from canonical page layout bounds.
   - Do not branch on `mm` or `in` for canonical pages.
6. Flattened PDF:
   - Use canonical pt page dimensions directly.
7. Sidecar:
   - Add optional page geometry metadata so API/editor can inspect layout,
     physical, and raster sizes without reparsing export bytes.

Expected new tests:

- `svg_a4_uses_physical_size_and_pt_viewbox`
- `svg_square_uses_canonical_layout_viewbox`
- `png_square_uses_raster_default_1080`
- `png_a4_uses_physical_dpi_when_profile_has_dpi`
- `pdf_a4_media_box_is_595x842_pt`
- `pdf_bleed_uses_canonical_pt_rect`
- `skia_raster_scales_from_layout_bounds`
- `flattened_pdf_uses_canonical_pt_pages`

## Editor Adapter Plan

Files:

- `apps/editor/src/engine/contracts.ts`
- `apps/editor/src/engine/renderAdapter.ts`
- `apps/editor/src/engine/exportParity.ts`
- `apps/editor/src/engine/canvaskitGestures.ts`
- `apps/editor/src/engine/sceneQueries.ts`
- `apps/editor/src/engine/__tests__/renderAdapter.test.ts`
- `apps/editor/src/engine/__tests__/exportParity.test.ts`

Work:

1. Add `pt` to `Unit`.
2. Update render descriptors so canonical pages render at layout width/height.
   For canonical pages, `unitScale` is `1`.
3. Keep `sceneUnitFromCanvas` and `canvasFromSceneUnit` as viewport/canvas
   conversion helpers, but make them use layout scale, not physical unit scale.
4. Update export parity:
   - SVG viewBox comparison should use canonical layout size.
   - PNG comparison should accept raster output as a scaled export of canonical
     layout.
   - PDF comparison should compare MediaBox points directly for canonical pages.
5. Do not add infinite workspace pan/zoom UI here. Existing viewport fit tests
   can be adjusted to pt layout dimensions.

Expected changed expectations:

- A4 page descriptor becomes about `595.276 x 841.89`, not `793.7 x 1122.5`.
- A `1080 x 1080 px` custom page still describes a `1080 x 1080` artboard,
  but stored as `unit: "pt"` with raster metadata.
- Node positions inside canonical pages no longer multiply by mm/in scale.

## API And Persistence Plan

Files to inspect during implementation:

- `apps/api`
- `apps/api-helper`
- `apps/editor/src/engine/exportRunner.ts`
- API tests that parse export artifact dimensions

Work:

1. Ensure JSON DTOs can carry optional `source` and `output` metadata.
2. Ensure persisted scenes with older `PageSize` JSON still deserialize via
   `serde(default)`.
3. Ensure export responses expose dimensions consistently:
   - layout dimensions in pt
   - physical dimensions when print metadata exists
   - raster dimensions for PNG output
4. Keep operation history canonical: page resize/update operations should carry
   the evolved `PageSize` object.

## Fixture Updates

Update or add fixtures where page unit assumptions are pinned:

- `crates/lumen-core/fixtures/conformance/phase_f_manifest.json`
- tokenized LinkedIn square fixtures
- editor minimal scene fixture
- export adapter helper scenes that currently build A4 as `Unit::Mm`
- Skia raster/export goldens only if raster dimensions intentionally change

Do not bulk-update fixtures without checking whether each fixture is asserting
legacy compatibility or canonical new behavior.

## Implementation Sequence

### CG0: Repro And Contract Tests

Add failing tests before changing behavior:

- New canonical A4 layout expectations.
- DSL preset/custom normalization expectations.
- SVG/PDF/PNG output dimension expectations.
- Preflight bounds diagnostics for page and parent overflow.
- Legacy non-pt page warning.

Gate:

- Tests fail for the expected current reasons.

### CG1: Core Geometry Contract

Implement `Unit::Pt`, page metadata fields, `page_geometry`, and normalization
helpers.

Gate:

- Scene serialization/deserialization works for old and new page JSON.
- Unit conversion tests pass.

### CG2: DSL/Page Operations

Route page creation and page modification through the normalizer.

Gate:

- New DSL tests pass.
- Existing custom-size tests are updated without losing custom-size support.

### CG3: Layout And Preflight Bounds

Make layout/preflight consume canonical layout geometry and add overflow
diagnostics.

Gate:

- Preflight emits the new bounds diagnostics.
- Layout tests still pass for auto-layout/fill/hug cases.

### CG4: Export Adapters

Move SVG/PNG/PDF/Skia/flattened-PDF conversion through page geometry.

Gate:

- Export adapter tests pass for A4, square, wide, tall, bleed, PDF, and PNG.
- No adapter has a private unit conversion table except through the helper.

### CG5: Editor Adapter And Parity

Update TypeScript contracts, render descriptors, CanvasKit gesture conversion,
and export parity.

Gate:

- Editor tests pass.
- A4, square, wide, and tall artboards have descriptor/export parity.

### CG6: Docs And Memory

Update the relevant local docs and branch memory with final contract details,
verification commands, and downstream implications.

Gate:

- `git diff --check` passes.
- The branch memory records durable decisions and follow-up work.

## Verification Commands

Run at minimum:

```bash
cargo test -p lumen-core
cargo test -p lumen-export
cargo test -p lumen-skia
npm --prefix apps/editor test -- --run
npm --prefix apps/editor run lint
git diff --check
```

If export/API DTOs change:

```bash
cargo test --workspace
```

If browser-visible descriptor behavior changes materially:

```bash
npm run dev
```

Then validate the editor manually or with Playwright under the CanvasKit flag
for A4 and square custom scenes.

## Acceptance Criteria

The branch is complete when:

- New DSL/page creation writes canonical `Unit::Pt` pages.
- A4 page layout bounds are about `595.276 x 841.89`.
- Custom `1080 x 1080 px` pages remain authorable and exportable as
  `1080 x 1080` raster defaults.
- Physical print metadata is preserved separately from layout bounds.
- SVG/PDF/PNG/Skia/editor all consume the same canonical layout dimensions.
- Bounds preflight catches page/artboard overflow and parent overflow.
- Existing non-pt scenes are not silently rewritten.
- The editor descriptor no longer treats all child numbers on A4 as mm.
- Tests cover A4, US Letter, square, wide/tall custom, mm custom, bleed, and
  legacy non-pt scene compatibility.

## Downstream Implications

After this branch lands:

- `editor/infinite-workspace-v0` can build the light workspace and bounded
  artboard UI on top of trustworthy artboard bounds.
- `agents/artboard-frame-generation-v0` can teach the agent to author against
  canonical artboard dimensions and use page fills/root frames instead of
  oversized background rectangles.
- `editor/canvaskit-polish-v0` can tune selection chrome, page labels, and
  inspector state without hiding broken geometry behind viewport scaling.
- Loose workspace objects should remain deferred until export-safe artboards
  and bounds diagnostics are stable.

## Open Questions For Implementation Review

1. Should physical metadata live directly on `PageSize.output.physical`, or on a
   future export-profile default? V0 recommends `PageSize.output` because the
   metadata is intrinsic to the artboard size.
2. Should SVG print exports use physical `width/height` attributes immediately,
   or keep pt attributes and expose physical size only in sidecar metadata?
   V0 recommends physical attributes plus pt viewBox for print pages.
3. Should legacy non-pt scenes emit warning or advice severity? V0 recommends
   advice unless a bounds/preflight error is also present.
4. Should `size(width,height,pt)` be agent-facing immediately? V0 recommends
   supporting it, but keeping px/mm/in examples in author docs because those
   are what users naturally request.
