# Phase B Deferred Layout And Typography Backlog

Date: 2026-06-10

Branch: `phase-b/layout-text-reliability-v0`

Purpose:

Record the layout, editor, and typography capabilities intentionally deferred
from Phase B. These are not rejected features. They are product-grade follow-up
work that should be revisited after the Phase B contracts are integrated and
the agent loop proves it can use the new layout/text primitives reliably.

Phase B established the core contracts:

- custom page dimensions as canonical scene data
- auto-layout alignment fields and Taffy mapping
- computed geometry as the renderer/editor position contract
- shared heuristic text measurement
- text fields for line height, letter spacing, wrap, max lines, and direction
- all-text overflow diagnostics
- basic editor operation helpers and undo scaffolding

The backlog below captures what is still missing compared with a mature
Figma/Brilliant-style layout and typography system.

## 1. Auto-Layout Editor Manipulation

Current state:

- The scene and layout engine can represent row/column auto-layout, wrap, gap,
  padding, grow, hug, fill, and alignment.
- The editor has basic operation helpers and inspector controls.
- The editor does not yet provide a full direct-manipulation auto-layout UX.

Deferred capabilities:

- Drag a node into an auto-layout parent.
- Compute insertion index from pointer position.
- Show insertion indicators between children.
- Show preview spacing/gap while dragging.
- Reorder children within an auto-layout parent by drag.
- Reorder children by keyboard.
- Move before/after a sibling through explicit helper operations.
- Group a drag/reorder as one undoable semantic operation.
- Preserve intended sizing mode during drag/resize.
- Show auto-layout parent hit zones for nested layouts.

Why deferred:

This is editor interaction work, not core layout semantics. Phase B first needed
the canonical scene fields and computed geometry contract. Polished drag/drop
should build on those stable semantics instead of inventing editor-only layout
behavior.

Recommended future branch:

`editor/auto-layout-manipulation-v0`

## 2. Advanced Child Layout Controls

Current state:

- Children can participate in row/column flow.
- Size can be fixed, hug, fill, or weighted fill.
- `AutoLayoutProps.grow` exists at the layout-props level.

Deferred capabilities:

- Per-child `align-self`.
- Per-child margins.
- Per-child flex basis.
- Per-child shrink controls.
- Explicit child order independent of document tree order.
- Absolute-position child mode inside an auto-layout parent.
- Baseline alignment for text rows.
- Aspect-ratio constraints.
- Min/max width and height.
- Percent-based sizing.
- Fit-content and clamp-style sizing policies.

Why deferred:

These controls widen the scene contract and layout validation surface. They
should be added once the current fixed/hug/fill/alignment behavior is stable in
agent output, editor preview, and export.

Recommended future branch:

`engine/layout-constraints-v0`

## 3. Responsive And Adaptive Layout Behavior

Current state:

- Layout is computed for the current page/canvas dimensions.
- Wrap exists, but there are no breakpoint or alternate-layout semantics.

Deferred capabilities:

- Breakpoints by page/canvas width.
- Container-query-like layout changes.
- Alternate direction by available width.
- Adaptive gap/padding tokens by size class.
- Responsive typography scale by artifact size.
- Alternate content density modes.
- Explicit layout variants for square, portrait, landscape, and print formats.

Why deferred:

The immediate ABM artifact workflow needs reliable single-surface generation
first. Responsive variants are important for multi-channel campaigns, but they
should come after core single-canvas layout is trustworthy.

Recommended future branch:

`engine/responsive-layout-v0`

## 4. Layout Repair Operations

Current state:

- `UpdateNode`, `UpdatePage`, `MoveNode`, and editor helpers can express many
  targeted changes.
- Agents can receive diagnostics, but repair operation planning is still basic.

Deferred capabilities:

- Convert a frame/group into auto-layout.
- Convert an auto-layout section back to manual/freeform layout.
- Increase/decrease gap.
- Increase/decrease padding.
- Change child sizing mode to fixed/hug/fill.
- Make children evenly spaced.
- Center a group of children.
- Wrap children into a second row.
- Move a node before/after another node.
- Fit text by switching height to hug.
- Fit text by increasing container height.
- Fit text by reducing type scale within policy.
- Apply repair suggestions from diagnostics to structured operations.

Why deferred:

The operation vocabulary can already carry low-level patches. The missing layer
is a product/agent repair planner that maps human/critic feedback to those
patches reliably.

Recommended future branch:

`agents/layout-repair-tools-v0`

## 5. Layout Diagnostics And Quality Heuristics

Current state:

- Phase B adds core layout/text overflow diagnostics.
- Invalid alignment combinations and text overflows are detected.

Deferred capabilities:

- Cramped spacing diagnostics.
- Inconsistent gap diagnostics.
- Ghost frame detection.
- Invisible child detection.
- Clipped child detection beyond current text fit.
- Stale computed geometry detection.
- Bad hierarchy warnings, such as too many dominant text nodes.
- Page margin/safe-area quality diagnostics.
- Unbalanced composition diagnostics.
- Overlapping element diagnostics.
- Warnings for excessive manual positioning in content-heavy designs.

Why deferred:

These are partly product-quality judgments rather than pure structural
validation. They should be driven by real failed generations and visual critic
traces.

Recommended future branch:

`qa/layout-quality-diagnostics-v0`

## 6. Deep Typography And Text Shaping

Current state:

- Text nodes support line height, letter spacing, max lines, wrap, direction,
  and style tokens.
- A shared heuristic text measurer exists.
- SVG/PDF can render measured line boxes, but the measurements are not
  font-accurate.

Deferred capabilities:

- Real font loading.
- Font fallback stack.
- Font asset resolution.
- Accurate glyph metrics.
- HarfBuzz-class shaping.
- Ligatures.
- Kerning.
- Script shaping for Indic, Arabic, and other complex scripts.
- Unicode bidirectional algorithm.
- RTL layout correctness beyond storing `direction`.
- Language-aware line breaking.
- Hyphenation.
- Ellipsis rendering.
- Rich text ranges.
- Italic/underline/decoration.
- Paragraph spacing before/after.
- Baseline grid and baseline alignment.
- Text vertical alignment inside fixed boxes.
- Text-on-path or advanced decorative typography.

Why deferred:

Phase B needed a shared measurement boundary first. Exact typography requires a
font-aware shaping backend and export/editor renderer integration. That is a
large subsystem and should replace the heuristic backend without changing the
callers.

Recommended future branches:

- `spike/text-shaping-fonts`
- `engine/text-shaping-v0`
- `export/print-typography-v0`

## 7. Print-Grade PDF Typography And Font Export

Current state:

- PDF honors page dimensions and basic measured text line boxes.
- PDF still uses early built-in/simple font behavior.
- SVG remains the current visual fidelity baseline.

Deferred capabilities:

- PDF font embedding.
- Font subsetting.
- Font license enforcement at export time.
- Exact PDF glyph positioning.
- CMYK/print color handling.
- Bleed and crop mark output.
- Print-safe line breaking.
- Multi-page pagination-sensitive text flow.

Why deferred:

This belongs to print/export fidelity. It depends on asset runtime, font
metadata, license policy, and the deeper text shaping backend.

Recommended future branch:

`export/print-fidelity-v0`

## 8. PNG And Raster Preview Fidelity

Current state:

- PNG export exists as a conservative fallback.
- It honors custom page size and computed rectangle geometry.
- It does not render full text/image/vector fidelity.

Deferred capabilities:

- Rasterize the canonical SVG output.
- Render text with the same measured line boxes as SVG.
- Resolve image/logo assets into raster output.
- Render gradients, vectors, shadows, and effects.
- Enforce raster dimension caps with product diagnostics.
- Produce critic-ready preview images with full visual fidelity.

Why deferred:

SVG is the current fidelity baseline. A proper PNG path should either rasterize
SVG or use a real scene renderer, not duplicate partial renderer behavior.

Recommended future branch:

`export/raster-preview-v0`

## 9. Rich Design-System Layout Knowledge

Current state:

- Agent knowledge now includes custom page dimensions, basic auto-layout
  recipes, and text fit guidance.

Deferred capabilities:

- Larger catalog of layout recipes by artifact type.
- Brand-specific spacing and type scale guidance.
- Channel-specific layout rules for LinkedIn, email, print, and direct mail.
- Examples of repair patterns for overflow and bad hierarchy.
- Retrieval of typography/layout knowledge based on prompt intent.
- Mode-rich design-system authoring similar to Brilliant's `.styles`
  guidance.

Why deferred:

Knowledge should evolve with actual product failures. Phase B gives agents the
language and engine primitives; future work should add richer examples and
retrieval once we know where outputs still fail.

Recommended future branch:

`agents/layout-typography-knowledge-v0`

## Priority Order

Recommended order when revisiting this backlog:

1. `editor/auto-layout-manipulation-v0`
2. `agents/layout-repair-tools-v0`
3. `engine/layout-constraints-v0`
4. `qa/layout-quality-diagnostics-v0`
5. `export/raster-preview-v0`
6. `engine/text-shaping-v0`
7. `export/print-fidelity-v0`
8. `engine/responsive-layout-v0`
9. `agents/layout-typography-knowledge-v0`

The practical reason for this order:

- First make layout editable and repairable.
- Then add constraints that prevent bad layouts.
- Then improve preview fidelity.
- Then replace heuristic text measurement with real shaping.
- Then deepen print/export behavior and responsive variants.

