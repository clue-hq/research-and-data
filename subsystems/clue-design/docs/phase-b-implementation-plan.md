# Phase B Implementation Plan: Layout And Text Reliability

Date: 2026-06-10

Branch: `phase-b/layout-text-reliability-v0`

Primary spec: `docs/phase-b-layout-text-reliability.md`

Reference benchmark:
`/Users/aryankeshri/Documents/brilliant-design/design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`

## Objective

Implement Phase B as a production-grade step toward reliable AI-authored design
artifacts. The goal is not just to add syntax. The goal is to make generated
artifacts survive real content, arbitrary dimensions, user edits, and preview
export without breaking visually.

Phase B must directly recover these demo failures:

- **The Square Ad Failure**: the user asked for a 1:1 ad, but the scene/export
  stayed tied to preset page dimensions.
- **Text And Elements Going Out Of Proportion**: the model relied on brittle
  manual coordinates and fixed text boxes, so copy overflowed and hierarchy was
  weak.
- **Literal Newline In Quoted Text**: the compiler caught the issue, but the
  text model and repair hints were too thin for repeated reliable authoring.

Phase B should close the following product gaps from the gap analysis:

- **DSL Comparison**: explicit arbitrary page dimensions; richer text syntax;
  usable auto-layout authoring syntax.
- **Layout Engine Comparison**: alignment, computed geometry conformance,
  auto-layout recipes, repairable layout operations.
- **Text And Typography Comparison**: line height, letter spacing, wrapping,
  max lines, direction, hierarchy, overflow diagnostics.
- **Scene Model Comparison**: page dimensions, text fields, layout alignment,
  and computed geometry remain canonical scene data, not renderer guesses.
- **Rendering/Export/Preview**: preview and export honor computed geometry and
  page dimensions consistently.

## Working Principle

Brilliant's key layout/text lesson is:

```text
Do not ask the model to win by perfect pixel math.
Give it declarative constraints, strong layout recipes, and fast visual/text
feedback.
```

For Lumen, that means:

- Presets are shortcuts, not constraints.
- Page size is canonical scene data.
- Auto-layout is the default structure for content.
- Free positioning is for decorative and chart-like regions.
- Text wrapping and fit are measured and diagnosed systematically.
- Export/editor/agent preview consume the same computed geometry.
- Every semantic change flows through canonical operations.

## Current Baseline

Current useful foundations:

- `Scene`, `PageSize`, `Node`, `TextNode`, `AutoLayoutProps`, and
  `ComputedGeometry` already exist.
- DSL supports pages, nodes, sizing, fills, tokens, `hug`, `fill`, gap, padding,
  wrap, and typed `x(...)` / `y(...)` AST anchors.
- Taffy-backed layout supports fixed, hug, fill, weighted fill, gap, padding,
  wrap, parent hug sizing, fill-to-hug fallback, transformed-child exclusion,
  and computed geometry.
- Preflight resolves brand tokens, runs layout, and persists computed geometry.
- Export/editor adapters exist.
- Phase A adds visual critique loop scaffolding and persisted run traces.

Current blockers:

- Page DSL only supports `preset(...)`; `custom` still behaves like A4 in DSL
  helper sizing.
- `x(...)` / `y(...)` are parsed but not stored or applied.
- Computed geometry is not consistently used as the render position contract.
- Text fields are too thin.
- Text measurement is heuristic and embedded in layout instead of shared.
- Plain text nodes do not get comprehensive overflow diagnostics.
- Agent knowledge lacks Phase B layout templates that the model can copy.

## Architecture Boundaries

### Core Owns

- canonical scene contract
- operation vocabulary and checked application
- DSL lowering into operations
- layout computation
- text measurement contract and baseline deterministic measurer
- layout/text diagnostics
- computed geometry operations

### Export Owns

- SVG/PNG/PDF adapter rendering
- page-size-to-output dimensions
- renderer-specific warnings
- text rendering from measured line boxes
- export conformance fixtures

### Editor Owns

- UI controls and canvas rendering
- gesture interpretation
- inspector controls
- emitting operations
- not redefining design semantics

### Agent Runtime Owns

- selecting Phase B knowledge
- asking for robust layout/text DSL
- feeding diagnostics and previews into critique/repair
- not mutating scenes directly

### API Owns

- persisting scene JSON, operation history, diagnostics, and preview refs
- not redefining layout/text semantics

## Dependency Graph

The implementation should follow this dependency order:

```text
B0 failing fixtures and tests
  -> B1 custom page dimensions
  -> B2 alignment scene contract
  -> B3 computed geometry render conformance
  -> B4 text scene contract and DSL
  -> B5 text measurement adapter
  -> B6 all-text overflow diagnostics
  -> B7 SVG/editor text rendering parity
  -> B8 layout templates and agent knowledge
  -> B9 layout repair operation helpers/editor scaffolding
  -> B10 conformance review and cleanup
```

Do not start with agent prompts or templates before the deterministic engine
surfaces are correct. The agent can only use features that the compiler,
layout, and renderers agree on.

## Work Package B0: Failing Fixtures And Test Harness

Purpose:

Create evidence for every demo failure and every Phase B contract before
changing implementation.

Deliverables:

- `crates/lumen-core/fixtures/phase_b/square_linkedin_ad.lumen`
- `crates/lumen-core/fixtures/phase_b/banner_custom_size.lumen`
- `crates/lumen-core/fixtures/phase_b/autolayout_alignment.lumen`
- `crates/lumen-core/fixtures/phase_b/text_wrapping.lumen`
- `crates/lumen-core/fixtures/phase_b/text_overflow_plain_node.json`
- Rust tests for DSL, layout, text measurement, and validation.
- SVG export tests for custom dimensions and computed geometry.
- Editor adapter tests for page and node descriptors.
- Agent-runtime fixture prompt for a square LinkedIn ad.

Initial failing tests:

- `dsl_custom_page_size_lowers_to_scene_page_size`
- `svg_export_honors_custom_square_page_size`
- `editor_page_descriptor_honors_custom_page_size`
- `autolayout_row_x_center_positions_children`
- `autolayout_row_x_space_between_distributes_children`
- `autolayout_column_y_end_bottom_aligns_children`
- `svg_export_uses_computed_xy_for_layouted_children`
- `editor_descriptor_uses_computed_xy_for_layouted_children`
- `dsl_text_typography_fields_lower_to_text_node`
- `text_measurement_line_height_changes_height`
- `text_measurement_letter_spacing_changes_width`
- `plain_text_overflow_is_diagnosed_without_slot`
- `multiline_svg_text_uses_measured_line_boxes`

Gate:

The failing tests must reflect desired product behavior, not implementation
details. They should stay meaningful after refactors.

## Work Package B1: Custom Page Dimensions

Purpose:

Remove the preset bottleneck that caused the 1:1 ad failure.

Files likely touched:

- `crates/lumen-core/src/dsl.rs`
- `crates/lumen-core/src/scene.rs`
- `crates/lumen-core/src/validation.rs`
- `crates/lumen-core/tests/dsl_compiler.rs`
- `crates/lumen-core/tests/validation.rs` or equivalent
- `crates/lumen-export/tests/export_adapter.rs`
- `apps/editor/src/engine/contracts.ts`
- `apps/editor/src/engine/renderAdapter.ts`

Contract changes:

- Extend DSL page AST with explicit page properties:
  - `size(width,height,unit)`
  - optionally `background(paint)` in the same pass
  - keep `preset(name[,orientation])`
- Keep `PageSize` as canonical:
  - `width`
  - `height`
  - `unit`
  - `preset`
  - `orientation`
- Explicit `size(...)` must override preset dimensions.
- Presets still populate dimensions when no explicit size exists.
- `PagePreset::Custom` must never imply A4 dimensions when explicit size is
  available.

DSL target syntax:

```text
page page_square size(1080,1080,px)
page page_story size(1080,1920,px)
page page_a4 preset(a4,portrait)
page page_banner preset(linkedin_ad) size(1200,1200,px)
```

Validation:

- non-finite values: error
- zero/negative values: error
- unsupported units: DSL error
- very large raster output: export warning/error by raster adapter

Tests:

- DSL parse/lower test proves `size(...)`.
- Scene validation rejects invalid page dimensions from JSON.
- SVG export honors custom dimensions.
- PNG helper uses page dimensions and caps extreme raster sizes.
- Editor page descriptor has exact custom dimensions after unit scaling.

Acceptance:

The agent no longer needs to draw a fake `1080x1080` inner frame to satisfy a
square output request. The canonical page is square.

## Work Package B2: Auto-Layout Alignment Contract

Purpose:

Make `x(...)` / `y(...)` real layout semantics instead of parsed warnings.

Files likely touched:

- `crates/lumen-core/src/scene.rs`
- `crates/lumen-core/src/dsl.rs`
- `crates/lumen-core/src/layout.rs`
- `crates/lumen-core/tests/layout_engine.rs`
- `apps/editor/src/engine/contracts.ts`
- `apps/editor/src/engine/operations.ts`
- `apps/editor/src/engine/editorEngine.ts`

Scene additions:

```rust
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LayoutAnchor {
    Start,
    Center,
    End,
    SpaceBetween,
    Stretch,
}
```

Extend `AutoLayoutProps`:

```rust
pub align_x: LayoutAnchor,
pub align_y: LayoutAnchor,
```

Serde compatibility:

- default `align_x = Start`
- default `align_y = Start`
- existing fixtures deserialize unchanged

DSL lowering:

- `x(s|start)` -> `align_x = Start`
- `x(c|center)` -> `align_x = Center`
- `x(e|end)` -> `align_x = End`
- `x(sb|space_between|space-between)` -> `align_x = SpaceBetween`
- `x(stretch)` -> `align_x = Stretch`
- same for `y(...)`

Layout mapping:

Row:

- `align_x` -> `justify_content`
- `align_y` -> `align_items`

Column:

- `align_y` -> `justify_content`
- `align_x` -> `align_items`

Invalid combinations:

- `SpaceBetween` on cross axis should emit a layout diagnostic.
- `Stretch` on main axis should emit a layout diagnostic.
- Keep behavior deterministic; choose safe fallback `Start` after diagnostic.

Diagnostics:

- `LUMV0710`: invalid auto-layout anchor for axis
- `LUMV0711`: space-between requires definite main-axis size
- `LUMV0712`: stretch on cross axis requires definite parent constraints

Tests:

- row start/center/end/space-between
- column start/center/end/space-between
- cross-axis center/end/stretch
- invalid cross-axis space-between
- default old scenes still start-align

Acceptance:

Lumen DSL can express Brilliant-style layout alignment:

```text
nav al(h,x(sb),y(c),g(16),pad(24)) s(fill,hug)
card al(v,x(s),y(sb),g(0),pad(32)) s(360,540)
button al(h,x(c),y(c),g(8),pad(12,20)) s(hug,hug)
```

## Work Package B3: Computed Geometry Render Conformance

Purpose:

Make layout output authoritative for render positions and sizes.

Current problem:

Layout stores absolute page-space `ComputedGeometry.layout_bounds`, but render
adapters often use authored `Transform.x/y` for position. This means the scene
can have correct layout while preview/export still uses stale positions.

Files likely touched:

- `crates/lumen-export/src/svg.rs`
- `crates/lumen-export/src/png.rs`
- `crates/lumen-export/src/pdf.rs`
- `crates/lumen-export/src/sidecar.rs`
- `apps/editor/src/engine/renderAdapter.ts`
- `apps/editor/src/engine/contracts.ts`
- `crates/lumen-export/tests/export_adapter.rs`
- `apps/editor/src/engine/__tests__/*`

Render-box rule:

```text
if node.computed exists:
  layout x/y/width/height = computed.layout_bounds
else:
  x/y = node.transform.x/y
  width/height = fixed size fallback

rotation/skew/flip still come from node.transform
```

SVG rendering strategy:

Use absolute page-space positions when computed geometry exists. This avoids
double-applying nested parent transforms. For non-computed nodes, preserve the
existing nested transform behavior.

Critical tests:

- Auto-layout child with transform `(0,0)` but computed `x=200` exports at
  `x=200`.
- Nested auto-layout child exports at absolute page-space computed position.
- Non-computed manual frame still uses authored transform.
- Rotated child excluded from auto-layout still uses manual transform and
  render bounds correctly.
- Editor render descriptors match SVG export descriptors.

Potential helper:

Create an adapter-local `render_box(node)` first. If duplication grows, move a
platform-independent helper into `lumen-core`.

Acceptance:

An auto-layout scene that passes preflight renders consistently in editor, SVG,
PNG preview, and visual critic payloads.

## Work Package B4: Text Scene Contract And DSL

Purpose:

Give the DSL and scene enough typography information to produce reliable,
professional layouts.

Files likely touched:

- `crates/lumen-core/src/scene.rs`
- `crates/lumen-core/src/dsl.rs`
- `crates/lumen-core/src/brand.rs`
- `crates/lumen-core/src/operations.rs`
- `crates/lumen-core/tests/dsl_compiler.rs`
- `crates/lumen-core/tests/brand_tokens.rs`
- `apps/editor/src/engine/contracts.ts`

Scene additions:

Minimum Phase B fields:

```rust
pub enum TextDirection {
    Ltr,
    Rtl,
    Auto,
}

pub enum TextWrap {
    NoWrap,
    Wrap,
}

pub struct TextNode {
    pub content: String,
    pub font_family: String,
    pub font_size: f64,
    pub font_weight: u16,
    pub align: TextAlign,
    pub line_height: f64,
    pub letter_spacing: f64,
    pub max_lines: Option<u16>,
    pub wrap: TextWrap,
    pub direction: TextDirection,
    pub style_token: Option<String>,
    pub line_height_token: Option<String>,
    pub letter_spacing_token: Option<String>,
}
```

Possible future fields should be documented but not necessarily implemented:

- font fallback stack
- styled ranges
- underline/italic
- language/locale
- font asset reference

Defaults:

- `line_height = 1.2`
- `letter_spacing = 0.0`
- `max_lines = None`
- `wrap = NoWrap` unless sizing or DSL explicitly requests wrap
- `direction = Ltr`

DSL additions:

Property form:

```text
headline text "Copy" font("Inter",48,700,left) lh(1.08) ls(-0.4) max_lines(2) wrap_text(true)
body text "Copy" style($type.body) lh($font.lineHeight.relaxed) s(fill,hug)
rtl_body text "..." dir(rtl) align(right) s(fill,hug)
```

Terse `t(...)` options:

```text
t("Copy","Inter",48,700,align(l),lh(1.08),ls(-0.4),max(2),wrap(true))
```

Parsing notes:

- Keep old `font("Inter",16,700,left)` supported.
- Keep old `text "..."` supported.
- Treat unsupported typography options as DSL diagnostics.
- Token forms for line height and letter spacing should lower to token carriers
  only where the scene has precise fields.
- Literal physical newline inside quoted text should receive a precise repair
  hint. Escaped `\n` is allowed.

Validation:

- font size must be finite and positive
- line height must be finite and positive
- max lines must be positive if present
- letter spacing must be finite
- unknown direction errors

Acceptance:

The model can express the core Brilliant text controls needed for reliable
hierarchy and fit without bloating every text line.

## Work Package B5: Controlled Text Measurement Adapter

Purpose:

Centralize measurement so layout, validation, export, and agent summaries stop
inventing separate text-fit answers.

Files likely touched:

- `crates/lumen-core/src/text_measure.rs` new
- `crates/lumen-core/src/layout.rs`
- `crates/lumen-core/src/lib.rs`
- `crates/lumen-export/src/svg.rs`
- `crates/lumen-core/tests/text_measure.rs` new
- `crates/lumen-core/tests/layout_engine.rs`
- `crates/lumen-export/tests/export_adapter.rs`

Core public API:

```rust
pub struct TextMeasureInput { ... }
pub struct TextMeasureOutput { ... }
pub struct TextLineBox { ... }

pub trait TextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput;
}

pub struct HeuristicTextMeasurer;
```

Phase B backend:

- Move current width heuristic into `HeuristicTextMeasurer`.
- Add line splitting for:
  - escaped newline breaks
  - whitespace wrapping
  - hard max width
  - max lines
- Apply line height and letter spacing.
- Surface `overflow_x`, `overflow_y`, `clipped`, and `line_count`.

Non-goals for this backend:

- HarfBuzz-class shaping
- exact browser font metrics
- hyphenation
- full bidi algorithm
- PDF font embedding

Boundary:

The contract should be strong enough that a future browser/font/PDF measurer can
replace the heuristic backend without changing layout/export callers.

Layout integration:

- Natural text size uses `TextMeasureInput`.
- Taffy measure callback uses the same measurer.
- Slot text fit uses the same measurer.
- All-text overflow diagnostics use the same measurer.

Export integration:

- SVG text rendering uses measured lines.
- Multiline text becomes `tspan` rows.
- `letter-spacing`, `direction`, `text-anchor`, and line-height-derived y
  offsets are reflected where possible.

Acceptance:

One measurement contract drives layout, slot fit, plain text diagnostics, and
SVG rendering.

## Work Package B6: All-Text Overflow Diagnostics

Purpose:

Catch visual text failures even when there is no ABM slot attached.

Files likely touched:

- `crates/lumen-core/src/layout.rs`
- `crates/lumen-core/src/text_measure.rs`
- `crates/lumen-core/tests/layout_engine.rs`
- `crates/lumen-agent/src/lib.rs`
- `apps/agent_runtime/lumen_deepagent/tools.py` if summaries include layout
  diagnostics

Diagnostics:

```text
LUMV0900 invalid text metrics
LUMV0901 text box collapsed to zero size
LUMV0902 non-wrapping text overflows horizontally
LUMV0903 wrapped text exceeds available height
LUMV0904 text exceeds max_lines
LUMV0905 text render bounds exceed page or clipped parent
LUMV0906 text uses fallback fill
```

Validation rules:

- Every text node is measured after computed geometry exists.
- Fixed-height text boxes get overflow-y diagnostics.
- Non-wrapping text gets overflow-x diagnostics.
- `max_lines` is enforced.
- If a text node is inside a clipping parent and text exceeds the parent clip
  region, emit a diagnostic.
- Diagnostics should include node ID, page ID where possible, and repair hints.

Repair hints:

- use `s(fill,hug)` for prose
- lower font size or use style token
- increase max lines
- increase container height
- switch parent to auto-layout
- add `wrap_text(true)`
- split copy into headline/body/CTA nodes

Acceptance:

The second demo failure cannot pass preflight silently just because text nodes
compile and export.

## Work Package B7: Export And Editor Text/Geometry Parity

Purpose:

Ensure the user, critic, and final export see the same geometry and text fit.

Files likely touched:

- `crates/lumen-export/src/svg.rs`
- `crates/lumen-export/src/png.rs`
- `crates/lumen-export/src/pdf.rs`
- `apps/editor/src/engine/renderAdapter.ts`
- `apps/editor/src/engine/contracts.ts`
- `apps/editor/src/engine/__tests__/*`

SVG requirements:

- page dimensions from `PageSize`
- render boxes from computed geometry
- multiline measured text with `tspan`
- visible warnings for unsupported typography fidelity
- `direction` attribute for RTL/auto where possible
- `letter-spacing` attribute
- line-height through y offsets

Editor requirements:

- render descriptors include:
  - computed `x/y/width/height`
  - line height
  - letter spacing
  - max lines
  - wrap
  - direction
- selection and inspector read the same fields.
- group nodes remain non-visual.
- active page selection remains scoped.

PNG/PDF requirements:

- custom page size honored.
- text fidelity limitations are diagnostic, not hidden.

Acceptance:

When a Phase B fixture is preflighted, editor preview and SVG export agree on
page size, node boxes, and basic text line positions.

## Work Package B8: Layout Templates And Agent Knowledge

Purpose:

Make the improved engine usable by agents. Brilliant succeeds partly because
its agents have example-heavy layout and typography knowledge.

Files likely touched:

- `apps/agent_runtime/knowledge/lumen-dsl/authoring.md`
- `apps/agent_runtime/knowledge/design/layout-recipes.md`
- `apps/agent_runtime/knowledge/design/typography-and-composition.md`
- `apps/agent_runtime/skills/lumen-dsl-design/SKILL.md`
- `apps/agent_runtime/evaluation/fixture_prompts.json`
- `docs/phase-a-agent-quality-loop.md` if Phase B changes critic expectations

New knowledge modules or sections:

- custom page sizing
- square LinkedIn ad pattern
- landscape ad pattern
- ABM one-pager pattern
- direct-mail header/body/footer pattern
- CTA row pattern
- proof-point/stat-card pattern
- text wrapping and line-height rules
- when to use group vs frame vs auto-layout
- common repair hints for overflow

Required example shape:

```text
page page_square size(1080,1080,px)
  shell fr p(0,0) s(fill,fill) fill($surface.brand)
    content al(v,x(s),y(c),g($space.lg),pad($space.xl)) s(fill,fill)
      headline text "..." s(fill,hug) style($type.headline) max_lines(2)
      body text "..." s(fill,hug) style($type.body) wrap_text(true) max_lines(4)
```

Agent guidance:

- never fake page size with an inner frame
- use auto-layout for content
- use groups for decorative/freeform layers
- use `s(fill,hug)` for prose
- use `hug` for CTA labels and short values
- prefer type tokens
- keep one focal element
- check diagnostic codes before visual repair

Acceptance:

Agent fixtures should generate DSL that uses Phase B features naturally.

## Work Package B9: Layout Repair Operation Helpers And Editor Scaffolding

Purpose:

Prepare for practical repair without waiting for full Phase D modify language.

Files likely touched:

- `crates/lumen-core/src/operations.rs`
- `crates/lumen-core/tests/operations.rs`
- `apps/editor/src/engine/editorEngine.ts`
- `apps/editor/src/engine/operations.ts`
- `crates/lumen-agent/src/lib.rs`

Helpers:

- update page size
- update auto-layout anchors
- update gap/padding
- update text metrics
- set dimension mode fixed/hug/fill
- reorder child within parent
- insert child at index
- move child before/after sibling

Use existing `UpdateNode`, `AddPage`, `InsertNode`, `MoveNode`, and page-patch
operations where available. Add new operation variants only if the current
patch model cannot express a canonical mutation cleanly.

Editor scaffolding:

- insertion-index helper for auto-layout parent
- reorder operation test
- undo grouping shape documented
- inspector field patch tests

Agent scaffolding:

- visual critique category `layout_text`
- repair recommendation maps overflow diagnostics to structured operation
  surface where a targeted patch is possible.

Acceptance:

A critic issue like "body text overflows in node body_copy" can map to a
targeted repair plan instead of regenerating the whole page.

## Work Package B10: Conformance, Review, And Completion Audit

Purpose:

Prove Phase B actually closes the intended product gaps.

Required verification:

```bash
cargo fmt --check
cargo test
cargo clippy --all-targets -- -D warnings
cargo check --target wasm32-unknown-unknown
npm run lint
npm test
npm run build
LUMEN_AGENT_RUN_LIVE=0 /Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests apps/agent_runtime/tests -q
```

Required product fixtures:

- square LinkedIn ad custom page fixture
- text-heavy one-pager fixture
- row/column alignment fixture
- custom banner fixture
- long account name text-fit fixture

Review checklist:

- Does `PageSize` contain the user-requested canvas size?
- Does SVG export exactly match the custom canvas dimensions?
- Do editor descriptors match export dimensions?
- Does layout compute center/end/space-between?
- Does export use computed `x/y`, not stale transforms?
- Do text fields serialize/deserialize through Rust and TypeScript contracts?
- Do plain text nodes get overflow diagnostics?
- Do agent knowledge files instruct robust layout patterns?
- Does the square ad fixture no longer fail the way the demo failed?

Completion standard:

Phase B is not complete merely because tests pass. It is complete when the
custom-dimension, auto-layout, text-measurement, all-text diagnostics, and
preview/export/editor conformance fixtures demonstrate that the demo failure
modes are structurally addressed.

## Suggested Commit Slices

Keep commits reviewable and contract-focused:

1. `Add Phase B failing fixtures`
2. `Support explicit custom page dimensions`
3. `Add auto-layout alignment contract`
4. `Use computed geometry in render adapters`
5. `Extend text scene and DSL fields`
6. `Add shared text measurement adapter`
7. `Diagnose all text overflow`
8. `Render measured multiline SVG text`
9. `Add Phase B layout templates and agent knowledge`
10. `Add layout repair helpers and conformance tests`

## Implementation Notes And Decisions

### Presets

Presets remain useful for common print and ad dimensions, but they must never be
required. A preset is a convenience function that produces `PageSize`; it is not
a renderer constraint.

### Page Size Source Of Truth

The page size lives in `Scene.pages[page_id].size`. Render/export adapters must
not infer page dimensions from prompt text, preset names, selected viewport, or
inner frames.

### Layout Source Of Truth

Authored transforms describe manual placement. Computed geometry describes
preflighted layout placement. When computed geometry exists, renderers should
treat it as authoritative for layout boxes.

### Text Measurement

The Phase B measurer can remain heuristic, but it must be centralized and
honest. A single imperfect answer is better than four inconsistent imperfect
answers.

### Professional-Grade Scope

Professional-grade for Phase B means:

- robust contract boundaries
- deterministic diagnostics
- cross-adapter conformance
- useful text-fit behavior
- agent-authorable layout templates

It does not mean full browser/PDF font shaping in this branch. That deeper
backend is enabled by the text measurement boundary and should follow later.

