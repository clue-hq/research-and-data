# Phase B: Layout And Text Reliability

Date: 2026-06-10

Branch: `phase-b/layout-text-reliability-v0`

Detailed implementation plan: `docs/phase-b-implementation-plan.md`

Purpose:

Make generated artifacts resilient to real content, arbitrary page dimensions,
layout edits, and typography changes. Phase B is the corrective product phase
after the first prompt-to-DSL spike: a design that compiles is not enough. The
artifact must honor the requested canvas, use robust layout structure, fit text
predictably, and render consistently across agent preview, SVG export, editor
preview, and future PNG/PDF export.

## Sources Reviewed

Lumen sources:

- `reference_docs/ABM-Design-Engine-Temporary-Spec.md`
- `reference_docs/Brilliant-Reverse-Engineering-Report.md`
- `reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`
- `docs/dsl-compiler.md`
- `docs/slots-layout.md`
- `docs/preflight-pipeline.md`
- `docs/phase-a-agent-quality-loop.md`
- `crates/lumen-core/src/scene.rs`
- `crates/lumen-core/src/dsl.rs`
- `crates/lumen-core/src/layout.rs`
- `crates/lumen-core/tests/layout_engine.rs`
- `crates/lumen-export/src/svg.rs`
- `apps/editor/src/engine/contracts.ts`
- `apps/editor/src/engine/renderAdapter.ts`

Brilliant sources:

- `brilliant/objects-syntax.md`
- `brilliant/knowledge/blueprint/core.md`
- `brilliant/knowledge/blueprint/layout.md`
- `brilliant/knowledge/blueprint/layout-patterns.md`
- `brilliant/knowledge/blueprint/text.md`
- `brilliant/knowledge/reference/text.md`
- `brilliant/knowledge/reference/layout-guides.md`
- `brilliant/knowledge/design/typography.md`
- `brilliant/knowledge/design/foundations.md`

## Product Goal

Phase B should make this true:

```text
User asks for a 1:1 LinkedIn ad or any other custom-sized artifact
  -> agent writes valid Lumen DSL with explicit page/artboard dimensions
  -> DSL lowers to canonical Scene + Operations
  -> brand tokens resolve
  -> layout computes stable geometry with hug/fill/wrap/alignment
  -> text measurement catches overflow and line-count failures
  -> editor/export/agent preview all honor the same computed geometry
  -> visual critic reviews the actual rendered result
  -> repair loop can target layout/text defects without regenerating everything
```

Presets must remain convenience shortcuts only. They must not constrain what a
valid page can be. If a user or agent asks for `1080x1080px`, the authored page
must become a `1080x1080px` page in the canonical `Scene`, and every renderer
must honor that.

## Brilliant Benchmark

Brilliant's layout and text system works because several pieces reinforce each
other:

- Blueprint has explicit sizing primitives: fixed, `hug`, `fill`, and weighted
  `fill:N`.
- Auto-layout is central, not optional: `al(h|v,x(...),y(...),g(...),pad(...))`.
- Alignment is physical and explicit: `x(s|c|e|sb)` and `y(s|c|e|sb)`.
- Wrapping is documented as a layout behavior, not a text afterthought.
- Text docs tell authors when to use `hug` and when to use `s(fill,hug)`.
- Text has line height, letter spacing, direction, font weight, font family,
  alignment, rich text ranges, and clear sizing modes.
- The compiler/runtime has diagnostics for ghost frames, wrap hints, collapsed
  zero-size elements, invisible text, and clipping.
- The same layout engine supports agent-authored Blueprint and human editor
  interactions: drag insertion, reorder, insertion indicators, and undo.
- Rendered preview is part of the loop, so clipping and proportion failures are
  seen quickly.

The strongest Brilliant design principle for Phase B is:

```text
Use declarative layout and text constraints so the model does not need perfect
manual pixel math.
```

## Baseline Before Phase B

Before this branch, Lumen already had a strong foundation:

- `Scene` is canonical.
- `Operation` is the mutation/history surface.
- `PageSize` already stores width, height, unit, preset, and orientation.
- `Dimension` supports fixed, `hug`, `fill`, weighted fill, and token sizes.
- `AutoLayoutNode` supports row/column and wrap.
- `AutoLayoutProps` supports gap, padding, token carriers, and grow.
- `layout_scene` is Taffy-backed.
- Layout supports fixed sizing, hug, fill, weighted fill, gap, padding, wrap,
  parent hug sizing, fill-to-hug fallback, transformed-child exclusion, and
  computed geometry.
- Slot fit validation exists, including text overflow policies.
- Preflight resolves brand tokens before layout and applies computed geometry.
- SVG export and the editor have adapter surfaces around the canonical scene.

Important baseline gaps:

- DSL page lines only support `preset(...)`.
- `PagePreset::Custom` currently has A4-like fallback dimensions in DSL helper
  behavior instead of taking explicit dimensions from the authored page line.
- Auto-layout `x(...)` and `y(...)` are parsed as typed AST but are not lowered
  into the scene contract yet.
- `AutoLayoutProps` has no alignment fields.
- SVG/editor adapters size nodes from computed geometry but still position many
  nodes from authored transforms, so computed layout positions are not yet a
  full export/editor contract.
- Text nodes lack line height, letter spacing, max lines, wrap mode, text
  direction, font fallback, and computed line boxes.
- Text measurement is a deterministic heuristic embedded in layout, not a
  reusable adapter shared by layout, export, editor, and agent summaries.
- Text overflow diagnostics are mostly slot-driven. Plain text nodes can still
  be visually broken without a slot.
- Editor direct manipulation for auto-layout insertion/reorder/undo is not yet
  aligned with the core layout semantics.

## Implemented In This Branch

This branch closes the first production-critical Phase B slice:

- DSL pages now support explicit custom dimensions with
  `page page_square size(1080,1080,px)`.
- Presets remain shortcuts; valid custom dimensions are canonical `PageSize`
  data and export/editor adapters honor them.
- Scene validation rejects non-finite, zero, and negative page dimensions.
- `AutoLayoutProps` now carries `align_x` and `align_y`, and DSL `x(...)` /
  `y(...)` anchors lower into those fields.
- The Taffy layout adapter maps row/column physical anchors into main and
  cross-axis alignment, with diagnostics for invalid axis combinations.
- A shared `text_measure` module owns deterministic heuristic measurement for
  line height, letter spacing, wrapping, max lines, and line boxes.
- `TextNode` now carries line height, letter spacing, max lines, wrap mode,
  direction, and token carriers for line height and letter spacing.
- DSL text properties include `lh(...)`, `ls(...)`, `max_lines(...)`,
  `wrap_text(...)`, and `dir(...)`.
- Layout validation now measures every text node after computed geometry, not
  only slotted text nodes.
- SVG, PNG, and early PDF exporters share the computed render-geometry rule.
  SVG/PDF text rendering uses measured line boxes; PNG rasterizes the canonical
  SVG page output so text, paint, transforms, and computed geometry remain
  visually aligned with the SVG preview.
- The editor contract and render adapter mirror Phase B scene fields, use
  computed positions/sizes where present, and expose operation helpers for page
  size, layout alignment, text metrics, move/reorder, and basic undo.
- Agent knowledge and evaluation prompts now teach custom page sizing,
  auto-layout recipes, alignment, and text fit controls.

Still intentionally deferred:

- Full HarfBuzz-class shaping, bidi shaping, hyphenation, font embedding, and
  print-grade PDF typography.
- Polished drag insertion indicators and full editor auto-layout manipulation.
- Rich text ranges and production page safe-area/bleed DSL forms.
- Browser screenshot parity and deeper raster/image/font resolution beyond the
  current SVG-to-PNG raster path.

## Phase B Scope

Phase B owns cross-cutting product reliability across:

- scene model
- operation contract
- DSL compiler
- layout engine
- text measurement
- preflight diagnostics
- SVG export conformance
- editor render/operation conformance
- agent knowledge and critique summaries for layout/text defects

Phase B should not become a print-fidelity branch. PDF font embedding,
subsetting, final licensing enforcement, full HarfBuzz-class shaping, and
multi-page pagination remain deeper print/export work. Phase B must still
define the boundary for those systems so the product does not paint itself into
a corner.

## Target Contracts

### 1. Custom Page And Artboard Dimensions

Add first-class explicit custom page dimensions to DSL and scene validation.

Primary DSL form:

```text
page page_square size(1080,1080,px)
page linkedin_square size(1200,1200,px)
page letter_a4 preset(a4,portrait)
page banner size(1600,900,px) background(#0f172a)
```

Recommended supported page properties:

```text
preset(name[,orientation])
size(width,height,unit)
safe(x,y,width,height[,unit])
bleed(top,right,bottom,left[,unit])
background(paint)
name("Display name")
```

Phase B implementation can start with `size(...)` and `background(...)`; `safe`
and `bleed` may be added if the parser work is small and does not destabilize
the branch.

Scene behavior:

- Explicit `size(...)` lowers into `Page.size.width`, `Page.size.height`, and
  `Page.size.unit`.
- Explicit `size(...)` sets `preset: Some(PagePreset::Custom)` or `preset:
  None`. Prefer `Some(Custom)` for backward-compatible enum handling unless a
  migration to `None` is intentionally made.
- Orientation is derived from dimensions unless explicitly supplied:
  - `width >= height` => landscape
  - `height > width` => portrait
- Presets remain shortcuts that fill the same `PageSize` fields.
- A preset plus explicit size is legal only if explicit size wins and a warning
  records that the preset was used as a semantic label, not a constraint.

Validation:

- Reject non-finite width/height.
- Reject zero or negative width/height.
- Reject unsupported units.
- Warn or error on dimensions that exceed configured raster/export caps.
- Reject page sizes that cannot be represented by SVG/PNG/PDF adapters.

Exporter/editor behavior:

- SVG `width`, `height`, and `viewBox` must come from canonical `PageSize`.
- PNG raster dimensions must derive from `PageSize`, DPI, and scale, with caps.
- PDF page size must derive from `PageSize`, not from presets.
- Editor page descriptor must use `PageSize`, not a preset lookup.

Acceptance tests:

- `page page_square size(1080,1080,px)` exports an SVG with
  `width="1080"` `height="1080"` `viewBox="0 0 1080 1080"`.
- `page page_banner size(1600,900,px)` remains `1600x900` through preflight,
  editor descriptor, SVG export, and sidecar.
- `preset(linkedin_ad)` still works as a shortcut.
- Invalid custom sizes halt in DSL or structural validation.

### 2. Auto-Layout Alignment Semantics

Promote parsed layout anchors into canonical scene fields.

Scene model addition:

```rust
pub enum LayoutAnchor {
    Start,
    Center,
    End,
    SpaceBetween,
    Stretch,
}

pub struct AutoLayoutProps {
    pub gap: f64,
    pub gap_token: Option<String>,
    pub padding: [f64; 4],
    pub padding_token: Option<String>,
    pub grow: f64,
    pub align_x: LayoutAnchor,
    pub align_y: LayoutAnchor,
}
```

Rules:

- `x(...)` and `y(...)` are physical axes, matching Brilliant.
- For row layout:
  - `x(...)` maps to main-axis `justify_content`.
  - `y(...)` maps to cross-axis `align_items`.
- For column layout:
  - `y(...)` maps to main-axis `justify_content`.
  - `x(...)` maps to cross-axis `align_items`.
- `sb` is valid only on the main axis.
- `stretch` is valid only on the cross axis.
- Invalid anchor/axis combinations should produce `Phase::Layout` diagnostics
  and not silently fall back.

Taffy mapping:

| Lumen anchor | Taffy main axis | Taffy cross axis |
|---|---|---|
| Start | `JustifyContent::Start` | `AlignItems::Start` |
| Center | `JustifyContent::Center` | `AlignItems::Center` |
| End | `JustifyContent::End` | `AlignItems::End` |
| SpaceBetween | `JustifyContent::SpaceBetween` | invalid/advice |
| Stretch | invalid/advice | `AlignItems::Stretch` |

Acceptance tests:

- Row `x(c)` centers children as a group.
- Row `x(e)` right-aligns children.
- Row `x(sb)` distributes first and last children to edges.
- Row `y(c)` vertically centers children.
- Column `y(e)` bottom-aligns children.
- Column `x(c)` horizontally centers children.
- `x(sb)` in a column warns or errors because `sb` is not cross-axis.

### 3. Computed Geometry As Render Contract

Computed geometry must become a real cross-adapter contract, not only a size
hint.

Current risk:

- Layout computes absolute `layout_bounds`.
- Some adapters use computed width/height but still position nodes from authored
  `Transform`.
- That means layout can be correct while the preview/export is still wrong.

Target:

- If `node.computed` exists, renderer adapters use `computed.layout_bounds.x`,
  `computed.layout_bounds.y`, `width`, and `height` as the layout box.
- Authored `Transform` still contributes rotation, skew, and flip.
- Manual transforms remain source-of-truth only when computed geometry is absent
  or when a child is explicitly out of auto-layout flow.
- SVG, editor, PNG, PDF, sidecar, and visual-critic payloads agree on box
  positions and dimensions.

Implementation detail:

Define a renderer helper in each adapter, or a shared core helper if it can stay
platform-independent:

```text
render_box(node) =
  if computed exists:
    x = computed.layout_bounds.x
    y = computed.layout_bounds.y
    width = computed.layout_bounds.width
    height = computed.layout_bounds.height
  else:
    x = node.transform.x
    y = node.transform.y
    width/height = fixed node size or fallback
```

For nested SVG rendering, avoid double-applying absolute positions. The branch
must decide one strategy and test it:

- absolute page-space rendering for all nodes when computed exists, or
- local rendering with parent-relative computed deltas.

Given current `ComputedGeometry` stores absolute page-space bounds, the safer
near-term strategy is absolute page-space rendering for computed layouts.

Acceptance tests:

- Auto-layout row child exported at computed `x`, not stale transform `x`.
- Editor descriptor uses computed `x/y/width/height`.
- SVG sidecar matches exported node positions.
- Visual regression fixture proves preflighted auto-layout preview differs from
  non-preflight stale transform export.

### 4. Auto-Layout Templates And Knowledge

Brilliant gives the model copyable layout recipes. Lumen should do the same,
but in Lumen DSL.

Add Phase B knowledge/templates for:

- square LinkedIn ad
- landscape LinkedIn ad
- email hero/header
- direct-mail letter header/body/footer
- one-page brochure section
- two-column ad
- proof-point stack
- stat cards
- CTA row
- image plus copy
- logo/header/footer strip

Template requirements:

- Use explicit `page size(...)`.
- Use fixed outer shell plus auto-layout inner content.
- Use `s(fill,hug)` for prose.
- Use `hug` for labels, buttons, and short values.
- Use `x(...)`, `y(...)`, `g(...)`, and `pad(...)` systematically.
- Avoid manual text box pixel math except for deliberate decorative elements.
- Include slot keys where ABM personalization is likely.

Acceptance tests:

- At least three templates compile, preflight, layout, and SVG-export.
- At least one template uses custom page dimensions.
- At least one template uses row alignment and one uses column alignment.
- At least one template includes long text fixtures and passes text diagnostics.

### 5. Text Scene Model

Expand `TextNode` so typography is not trapped in a single `font(...)` tuple.

Target fields:

```rust
pub struct TextNode {
    pub content: String,
    pub font_family: String,
    pub font_size: f64,
    pub font_weight: u16,
    pub align: TextAlign,
    pub line_height: TextMetric,
    pub letter_spacing: TextMetric,
    pub max_lines: Option<u16>,
    pub wrap: TextWrap,
    pub direction: TextDirection,
    pub style_token: Option<String>,
    pub font_family_token: Option<String>,
    pub font_size_token: Option<String>,
    pub font_weight_token: Option<String>,
    pub line_height_token: Option<String>,
    pub letter_spacing_token: Option<String>,
}
```

Concrete names may change during implementation, but the contract must support:

- line height multiplier or absolute value
- letter spacing value
- max line count
- wrap/no-wrap behavior
- LTR/RTL direction
- token carriers for line height and letter spacing

Start with whole-element text style. Rich text ranges can be scaffolded but
should not block Phase B unless the implementation is already clean.

Default behavior:

- Line height defaults to `1.2` for headings/labels if no style token resolves.
- Body/prose style tokens should resolve to a more relaxed line height.
- Letter spacing defaults to `0`.
- Direction defaults to `ltr`.
- Wrap defaults from sizing:
  - width `hug` => no wrap
  - fixed/fill width + height `hug` => wrap with auto height
  - fixed width + fixed height => wrap and diagnose overflow

### 6. Text DSL

Add agent-friendly text syntax while preserving current forms.

Preferred terse form:

```text
headline t("Let neurosurgeons focus on surgery","Inter",48,700,align(l),lh(1.08),ls(-0.4),max(2),wrap(true))
body t("AI phone agents answer calls and route patient requests.","Inter",20,500,align(l),lh(1.4),max(3),wrap(true)) s(fill,hug)
arabic_body t("...",$font.family,18,500,align(r),dir(rtl),lh($font.lineHeight.relaxed)) s(fill,hug)
```

Property form:

```text
headline text "Let neurosurgeons focus on surgery" font("Inter",48,700,left) lh(1.08) ls(-0.4) max_lines(2) wrap_text(true)
```

Supported parser aliases:

```text
lh(value) / line_height(value)
ls(value) / letter_spacing(value)
max(n) / max_lines(n)
dir(ltr|rtl|auto) / direction(ltr|rtl|auto)
wrap_text(true|false)
align(l|c|r|j) inside t(...)
```

Guidance:

- Do not make DSL the full typography source of truth. DSL creates authored
  fields and token refs; Brand Kit resolution remains preflight-owned.
- Diagnostics must halt on unsupported or ambiguous text tokens. Do not guess.
- Literal physical newlines inside quoted strings should receive a repair hint:
  use escaped `\n` or split into multiple text nodes.

Acceptance tests:

- DSL lowers `lh`, `ls`, `max`, `dir`, and `wrap_text` into `TextNode`.
- Token forms lower into token carriers.
- Invalid line height, negative max lines, unknown direction, and unsupported
  text option syntax produce line-specific diagnostics.

### 7. Controlled Text Measurement Adapter

Replace the current embedded heuristic with an explicit measurement boundary.

Core types:

```rust
pub struct TextMeasureInput {
    pub content: String,
    pub font_family: String,
    pub font_size: f64,
    pub font_weight: u16,
    pub line_height: f64,
    pub letter_spacing: f64,
    pub direction: TextDirection,
    pub wrap: TextWrap,
    pub max_width: Option<f64>,
    pub max_lines: Option<u16>,
}

pub struct TextMeasureOutput {
    pub natural_width: f64,
    pub natural_height: f64,
    pub used_width: f64,
    pub used_height: f64,
    pub line_count: u16,
    pub clipped: bool,
    pub overflow_x: bool,
    pub overflow_y: bool,
    pub lines: Vec<TextLineBox>,
}
```

Implementation stages:

1. Move the existing heuristic into `HeuristicTextMeasurer`.
2. Make layout and slot validation call the adapter instead of local helper
   functions.
3. Make SVG export consume `TextMeasureOutput` for line splitting and `tspan`
   rendering.
4. Add a browser/editor measurement adapter later, behind the same input/output
   contract.
5. Add a print-grade shaping backend later for non-Latin, bidi, hyphenation,
   PDF, and font embedding work.

Why this matters:

- The product should not have one fit estimate in layout and a different visual
  result in SVG/PDF/editor.
- Even a heuristic backend becomes safer once it is centralized and explicitly
  labeled as heuristic.

Acceptance tests:

- Same `TextMeasureInput` produces same result in layout and export tests.
- Line height changes measured height.
- Letter spacing changes measured width.
- `max_lines` marks clipping.
- Explicit newline escape creates multiple line boxes.
- RTL direction is stored and surfaced even if full bidi shaping is deferred.

### 8. All-Text Overflow Diagnostics

Slot-only fit validation is not enough. Any visible text can break the design.

Add layout diagnostics for every text node:

- text box width/height is zero
- text natural width exceeds non-wrapping box
- wrapped text exceeds max lines
- wrapped text exceeds fixed height
- line height too small or non-finite
- font size non-finite or non-positive
- text node has no fill and export would use fallback
- text extends outside page bounds
- text render bounds exceed parent clip region

Suggested codes:

```text
LUMV0900 text has invalid typography metrics
LUMV0901 text box collapsed to zero size
LUMV0902 non-wrapping text overflows horizontally
LUMV0903 wrapped text exceeds available height
LUMV0904 text exceeds max_lines
LUMV0905 text render bounds exceed page or clipped parent
LUMV0906 text uses fallback fill
```

Severity:

- Errors for definite clipping, invalid metrics, or non-recoverable overflow.
- Warnings/advice for fallback fill or likely visual imbalance.

Acceptance tests:

- Plain text node with no slot still emits overflow diagnostics.
- Slot diagnostics and all-text diagnostics dedupe where they describe the same
  failure.
- Agent critique summaries include latest text overflow diagnostics.

### 9. Layout Repair Operations

Phase B should expose enough repair primitives that the agent can fix layout
and text without regenerating the whole artifact.

Core operations already have `UpdateNode`; Phase B should add or document
helpers for:

- set page size
- set auto-layout alignment
- set gap/padding
- set text wrap/max lines/line height/letter spacing
- set width/height to fixed/hug/fill
- apply computed layout operations
- reorder child in parent
- move child before/after sibling

If new operation variants are needed, add them only when `UpdateNode` patches
are too ambiguous. Keep operation history canonical.

Editor operations:

- drag into auto-layout parent computes insertion index
- reorder within auto-layout parent uses checked operation batch
- undo/redo records a single semantic operation group
- inspector changes for gap/padding/alignment/text metrics emit operations

This does not require a fully polished UI in the first Phase B commit, but the
operation semantics and tests should exist before the UI is considered reliable.

### 10. Editor Layout Parity

Editor must not own layout semantics, but it must expose them correctly.

Required behavior:

- Render computed page-space geometry when present.
- Show auto-layout direction, gap, padding, wrap, `x`, and `y`.
- Allow changing alignment through controls.
- Allow changing text line height, letter spacing, wrap, max lines, and
  direction.
- Show layout/text diagnostics on selected node/page.
- Keep group nodes non-visual.
- Keep selection scoped to active page.
- Do not mutate scene objects directly; use operations.

Interactive behavior:

- Dragging over an auto-layout parent shows insertion indicator.
- Dropping emits reparent/reorder operations.
- Reordering is undoable.
- Resizing a child updates sizing mode intentionally:
  - manual resize can switch fixed dimension
  - modifier/inspector can switch hug/fill
  - text auto-height should preserve `height = hug`

### 11. Export And Preview Parity

SVG export is the immediate correctness target. PNG/PDF should follow the same
rules.

SVG requirements:

- page dimensions from `PageSize`
- node positions from computed geometry when present
- text line boxes rendered using measurement output
- `line-height`, `letter-spacing`, `direction`, and `text-anchor` reflected
  where SVG supports them
- multiline text rendered with `tspan` rows
- overflow/clipping diagnostics surfaced before final export

PNG requirements:

- raster size from page dimensions, DPI, and scale
- cap large raster dimensions with a diagnostic
- eventually use the same SVG or scene renderer so text parity does not drift

PDF requirements:

- phase B should not claim print-grade typography unless font embedding and
  shaping are implemented
- still honor custom page dimensions
- emit clear diagnostics when PDF text fidelity is limited

### 12. Agent And Knowledge Updates

Phase B must make the agent prefer robust layout.

Update agent knowledge:

- Lumen DSL page sizing examples.
- Auto-layout recipes.
- Text wrapping rules.
- Typography hierarchy rules.
- "Use auto-layout for content; use groups for decorative/freeform layers."
- "Use `s(fill,hug)` for paragraphs and long ABM text."
- "Use `hug` for CTA labels, badges, metrics, logos, and short values."
- "Never fake a custom canvas by drawing a large inner frame on the wrong page."

Update critique prompts:

- flag canvas aspect mismatch
- flag text overflow/clipping
- flag stale computed geometry
- flag body copy line length
- flag low hierarchy/too many dominant text elements
- flag missing wrap on prose
- flag alignment/gap inconsistency

## Implementation Plan

### B0: Baseline Fixtures And Failing Tests

Create failing tests before changing behavior:

- custom square page DSL -> scene -> export
- custom banner page DSL -> scene -> editor page descriptor
- row/column alignment fixtures
- computed `x/y` conformance fixture
- text line-height and letter-spacing fixture
- all-text overflow fixture
- SVG multiline text fixture
- agent preview fixture for square LinkedIn ad

Deliverables:

- `crates/lumen-core/fixtures/phase_b/*.lumen`
- layout tests
- DSL tests
- export tests
- editor adapter tests

### B1: Custom Page Dimensions

Implement:

- DSL AST for `size(width,height,unit)`
- parsing/normalization/diagnostics
- lowering into `PageSize`
- page validation for finite positive dimensions
- SVG/export tests
- editor descriptor tests

Exit criteria:

- The square ad failure cannot recur because the scene itself carries the
  requested square page dimensions.

### B2: Alignment Scene Contract And Taffy Mapping

Implement:

- `LayoutAnchor`
- `AutoLayoutProps.align_x`
- `AutoLayoutProps.align_y`
- serde defaults/migration compatibility
- DSL lowering for `x(...)` and `y(...)`
- Taffy mapping
- invalid anchor diagnostics
- tests for row/column main/cross behavior

Exit criteria:

- `al(h,x(sb),y(c),...)` and `al(v,y(sb),x(c),...)` behave like the
  Brilliant-inspired knowledge docs say they should.

### B3: Computed Geometry Render Conformance

Implement:

- shared render box helper or equivalent in adapters
- SVG computed position rendering
- editor computed position rendering
- sidecar position checks
- visual/export fixture tests

Exit criteria:

- A preflighted auto-layout scene renders in SVG/editor at the same computed
  positions produced by `layout_scene`.

### B4: Text Contract And DSL

Implement:

- text line height
- letter spacing
- max lines
- wrap mode
- direction
- token carriers where needed
- DSL parser/lowering
- TypeScript contracts
- brand token resolver updates for text style fields

Exit criteria:

- Agents can express the typography properties Brilliant's text docs rely on
  for reliable hierarchy and wrapping.

### B5: Text Measurement Adapter And Diagnostics

Implement:

- `TextMeasureInput`
- `TextMeasureOutput`
- `TextLineBox`
- `HeuristicTextMeasurer`
- layout integration
- slot validation integration
- all-text overflow validation
- SVG multiline rendering

Exit criteria:

- Text fit is validated even without slots, and layout/export use one
  measurement contract.

### B6: Layout Templates And Agent Knowledge

Implement:

- Phase B layout recipe docs under `apps/agent_runtime/knowledge`
- updated Lumen DSL skill guidance
- fixture templates for common ABM artifacts
- evaluation prompts that use custom dimensions and auto-layout

Exit criteria:

- Agent-authored designs use auto-layout instead of brittle manual geometry for
  ordinary content structures.

### B7: Editor Interaction Semantics

Implement or scaffold with tests:

- reorder child operation helper
- before/after insertion helpers if needed
- auto-layout insertion index calculation
- undo grouping for layout edits
- inspector controls for alignment/text metrics

Exit criteria:

- Human edits preserve the same layout semantics the agent uses.

### B8: Conformance And Review

Run and add:

- Rust unit tests
- wasm compile check
- SVG export tests
- editor tests
- visual regression fixture for square LinkedIn ad
- review against this document and the product gap analysis

Exit criteria:

- No Phase B feature is considered complete until editor/export/preflight agree
  on scene geometry and text diagnostics.

## Implementation Risks

### Text Measurement Scope

The immediate implementation can centralize the heuristic measurer, but that is
not the final product-grade endpoint. Phase B should make the contract correct
and shared. Later print/export fidelity can replace the backend with a real
font/shaping implementation without changing callers.

### Computed Geometry And Nested Rendering

The current `ComputedGeometry` stores absolute page-space bounds. SVG/editor
renderers must avoid double-transforming nested children. This needs tests for:

- nested auto-layout inside frame
- manual group inside auto-layout
- rotated child excluded from auto-layout flow
- clipping parent

### Backward Compatibility

Adding fields to `TextNode` and `AutoLayoutProps` requires serde defaults and
TypeScript contract updates. Existing fixtures must still deserialize.

### Agent Over-Specification

Do not ask the agent to specify every typography field on every line. The
knowledge system should teach sensible defaults and use style tokens. Explicit
fields are for cases where the design needs precise control.

## Verification Commands

Phase B should finish with:

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

Visual fixtures should also be regenerated or checked once the Phase B preview
contracts are implemented.

## Product Acceptance Criteria

Phase B is done only when:

- A square LinkedIn ad prompt produces a square page in the canonical scene.
- Exported SVG dimensions match the requested custom page dimensions.
- Auto-layout alignment works for start, center, end, and space-between.
- Export and editor both honor computed positions and sizes.
- Text supports line height, letter spacing, max lines, wrap, and direction.
- Plain text nodes produce overflow diagnostics even without slots.
- Layout templates compile and produce stable previews.
- The agent knowledge stack tells the model to use auto-layout and text
  wrapping for content-heavy artifacts.
- The implementation is reviewed against the Brilliant comparison and the known
  demo failures.
