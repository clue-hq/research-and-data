# Slots And Layout Engine

This document describes the current `engine/slots-layout` implementation in
`crates/lumen-core`. It is intentionally implementation-level documentation:
it records what the engine does today, what it does not do yet, and how other
workstreams should consume it.

The key architectural rule remains:

```text
scene / ops / slots are the shared contract; layout is a core adapter around that contract.
```

The layout engine is not editor-owned, export-owned, or agent-owned. It lives
inside `lumen-core`, consumes the canonical `Scene`, emits canonical
`ComputedGeometry`, and reports structured diagnostics through the existing
diagnostic model.

## Source Files

- `crates/lumen-core/src/layout.rs`
  - Public layout API.
  - Taffy-backed layout traversal and style conversion.
  - Computed geometry production.
  - Slot-aware layout validation.
  - Current heuristic text measurement.
- `crates/lumen-core/src/lib.rs`
  - Exports the layout API from `lumen-core`.
- `crates/lumen-core/Cargo.toml`
  - Adds `taffy = "0.10.1"` with `std`, `flexbox`, and `taffy_tree` features.
- `crates/lumen-core/tests/layout_engine.rs`
  - Native tests covering layout mechanics and slot/layout diagnostics.

## Public API

The public API is intentionally small:

```rust
pub struct LayoutOptions {
    pub validate_slots: bool,
}

pub struct LayoutResult {
    pub geometry: BTreeMap<NodeId, ComputedGeometry>,
    pub diagnostics: Vec<Diagnostic>,
}

pub fn layout_scene(scene: &Scene, options: LayoutOptions) -> LayoutResult;

pub fn validate_layout(scene: &Scene, options: LayoutOptions) -> Vec<Diagnostic>;

pub fn layout_operations(scene: &Scene, options: LayoutOptions) -> Vec<Operation>;
```

### `LayoutOptions`

`LayoutOptions` currently has one option:

- `validate_slots`
  - `true` by default.
  - When `true`, layout computation is followed by slot-aware validation.
  - When `false`, the engine computes geometry and reports only layout-engine
    diagnostics such as Taffy failures and transformed-child exclusions.

This split lets callers use the engine in two modes:

- geometry-only preview/update mode
- geometry plus finalization/preflight validation mode

### `LayoutResult`

`LayoutResult` carries:

- `geometry`
  - A `BTreeMap<NodeId, ComputedGeometry>`.
  - Includes every node the layout pass can compute.
  - Uses stable scene node IDs, not Taffy node IDs.
- `diagnostics`
  - Structured `Diagnostic` values.
  - All layout-specific diagnostics use `Phase::Layout`.
  - Diagnostics do not prevent geometry from being returned.

### `layout_scene`

`layout_scene` is the main entry point. It:

1. Walks every page in document order.
2. Computes geometry for each page child.
3. Recursively computes child geometry.
4. Delegates auto-layout containers to Taffy.
5. Writes `layout_bounds` and `render_bounds` into the result map.
6. Optionally validates slots using the computed geometry.

It does not mutate the input scene.

### `validate_layout`

`validate_layout` is a convenience wrapper:

```rust
let diagnostics = validate_layout(&scene, LayoutOptions::default());
```

It runs layout and returns only diagnostics. It is useful for agent/export/API
preflight checks that do not need geometry.

It does not replace `validate_scene`. Structural validation and layout
validation are separate phases:

- `validate_scene` checks the contract shape: pages, tree integrity, slot
  references, export profile sanity, and similar structural invariants.
- `validate_layout` checks computable geometry, content fit, safe areas,
  overflow policy implications, image policy shape, and repeater/conditional
  layout scaffolding.

Callers that need a complete preflight should run both:

```rust
let mut diagnostics = validate_scene(&scene);
diagnostics.extend(validate_layout(&scene, LayoutOptions::default()));
```

### `layout_operations`

`layout_operations` converts computed geometry into scene operations:

```rust
let ops = layout_operations(&scene, LayoutOptions { validate_slots: false });
scene.apply_operations(ops)?;
```

Each operation is:

```rust
Operation::UpdateNode {
    node_id,
    patch: NodePatch {
        computed: OptionalFieldPatch::Set(computed_geometry),
        ..NodePatch::default()
    },
}
```

This preserves the operation-log model. Layout output is persisted through the
same mutation surface as any other scene change.

Important details:

- `layout_operations` currently returns operations even if layout diagnostics
  were produced.
- Callers that care about diagnostics should call `layout_scene` first and
  decide whether to apply operations.
- Applying these operations to a finalized scene will still be blocked by the
  existing operation finalization guard.
- The operation patches only touch `Node.computed`.

## Dependency Boundary

The engine uses Taffy as the flexbox solver. Taffy is not exposed through the
public API.

Current dependency declaration:

```toml
taffy = { version = "0.10.1", default-features = false, features = ["std", "flexbox", "taffy_tree"] }
```

This keeps `lumen-core` platform-independent and compatible with native and
`wasm32-unknown-unknown` builds. The core still does not depend on React,
Konva, FastAPI, databases, object storage, browser APIs, filesystem APIs, or
WebGPU.

## Scene Model Inputs

The layout engine consumes existing scene contract types:

- `Scene`
- `Page`
- `Node`
- `NodeKind`
- `Transform`
- `SizeSpec`
- `Dimension`
- `AutoLayoutNode`
- `AutoLayoutProps`
- `ComputedGeometry`
- `Slot`
- `OverflowPolicy`
- `ImagePolicy`
- `ConditionalRule`
- `RepeaterRule`

No new layout-specific scene type was added.

## Layout Containers

Only nodes whose `NodeKind` is `AutoLayout(AutoLayoutNode)` are solved through
Taffy as flex containers.

The relevant fields are:

```rust
NodeKind::AutoLayout(AutoLayoutNode {
    direction: AutoLayoutDirection::Row | AutoLayoutDirection::Column,
    wrap: bool,
})

Node.layout: Option<AutoLayoutProps>

AutoLayoutProps {
    gap: f64,
    padding: [f64; 4],
    grow: f64,
}
```

Current padding order is:

```text
[top, right, bottom, left]
```

`AutoLayoutProps.grow` exists in the scene contract but is not currently used
by the V1 solver. Child fill weights come from `Dimension::Fill { weight }`.

## Supported Layout Mechanics

The V1 engine supports:

- page-root layout traversal
- non-auto manual child traversal
- auto-layout row flow
- auto-layout column flow
- fixed sizing
- hug sizing
- fill sizing
- weighted fill on the main axis
- gap
- 4-sided padding
- wrapping
- parent hug sizing
- fill-to-hug fallback
- computed layout bounds
- transform-aware render bounds
- exclusion of rotated or skewed children from normal auto-layout flow

## Page Traversal

Layout starts from each page:

1. The page size becomes the available parent size for top-level children.
2. Each page child starts at its own `Transform.x` and `Transform.y`.
3. Page children are laid out in page child order.
4. Page background, bleed, and safe area do not directly affect geometry.
5. Safe area is used later by slot validation.

A top-level child with fixed size uses that fixed size. A top-level child with
fill size resolves against the page size. A top-level child with hug size uses
the engine's natural-size heuristic.

## Non-Auto Nodes

For nodes that are not `NodeKind::AutoLayout`, layout is direct:

- The node size is resolved with `resolve_manual_size`.
- Geometry is written for the node.
- Children are recursively laid out at:

```text
parent_origin + child.transform.(x, y)
```

Manual size resolution:

| Dimension | Resolution |
|---|---|
| `Fixed(value)` | `value` |
| `Fill { .. }` | available parent width or height |
| `Hug` | current natural-size heuristic |

For non-auto containers (`Frame` and `Group`), the engine does not run flex
math. Their children keep explicit transform offsets.

## Auto-Layout Nodes

Auto-layout nodes are converted into a temporary Taffy tree.

The engine builds a fresh `TaffyTree<MeasureContext>` for each auto-layout root.
It keeps an internal map between stable `NodeId` values and temporary Taffy
node IDs. Temporary Taffy IDs never leave the module.

For an auto-layout container:

1. Convert the container node into a Taffy `Style`.
2. Build Taffy children from normal-flow child nodes.
3. Exclude rotated or skewed children from normal flow.
4. Run `compute_layout_with_measure`.
5. Translate Taffy-relative layout output back into absolute scene geometry.
6. Recursively lay out excluded transformed children using their explicit
   transforms.

## Taffy Style Mapping

The current style mapping is deliberately conservative.

Every node gets a Taffy `Style` with:

- `size.width`
- `size.height`
- `flex_shrink = 0.0`

Auto-layout containers additionally get:

- `display = Display::Flex`
- `flex_direction = Row` or `Column`
- `flex_wrap = Wrap` or `NoWrap`
- `gap.width = gap`
- `gap.height = gap`
- `padding.left = padding[3]`
- `padding.right = padding[1]`
- `padding.top = padding[0]`
- `padding.bottom = padding[2]`
- `align_items = Start`
- `align_content = Start`
- `justify_content = Start`

The engine intentionally starts with start alignment only. Center/end/space
between behavior can be added later without changing the scene/slot contract.

## Dimension Mapping

The scene model uses:

```rust
Dimension::Fixed(f64)
Dimension::Hug
Dimension::Fill { weight: f64 }
```

The mapping to Taffy depends on whether the node is inside an auto-layout flow.

### Fixed

`Fixed(value)` maps to:

```rust
length(value)
```

### Hug

`Hug` maps to:

```rust
auto()
```

Leaf nodes provide a measure context so Taffy can ask for natural size.

### Fill Outside Auto-Layout Flow

For a node outside a parent flow:

- If the parent size is known, fill resolves to the parent size.
- If the parent size is unknown, fill resolves to `auto()`.

### Fill Inside Auto-Layout Flow

For a child inside an auto-layout parent:

- If the fill dimension is on the main axis, it maps to `auto()` and sets
  `flex_grow` to the fill weight.
- If the fill dimension is on the cross axis and the parent has definite cross
  space, it maps to `percent(1.0)`.
- If the fill dimension is on the cross axis and the parent does not have
  definite cross space, it maps to `auto()`.

This gives Figma-like behavior for common row/column cases while preserving a
clear fallback when there is no usable parent space.

## Weighted Fill

Weighted fill uses `Dimension::Fill { weight }`.

For a row container:

- Child width `Fill { weight }` becomes `flex_grow = weight`.
- Child height fill is cross-axis fill.

For a column container:

- Child height `Fill { weight }` becomes `flex_grow = weight`.
- Child width fill is cross-axis fill.

Invalid or non-positive weights are normalized to `1.0` internally.

## Fill-To-Hug Fallback

The engine implements a Brilliant-inspired fill-to-hug fallback before handing
children to Taffy.

Fill children fall back to hug when:

- the parent main-axis content size is not definite, or
- the parent has no positive free space after subtracting non-fill natural
  sizes and gaps.

This prevents fill children from collapsing to unusable zero or negative sizes
inside hug parents or fully occupied fixed parents.

The fallback is per auto-layout container and per main axis. Fallback children
do not get `flex_grow`; they are measured as natural-size content.

## Gap And Padding

`AutoLayoutProps.gap` maps to both Taffy row and column gap. This supports:

- row gap between row children
- column gap between column children
- line gap in wrapped flows, through Taffy's flex wrapping behavior

Padding is 4-sided and uses this order:

```text
[top, right, bottom, left]
```

Padding affects Taffy layout. Children are placed inside the padded content box.

## Wrapping

Wrapping is controlled by:

```rust
AutoLayoutNode { wrap: true }
```

When enabled, the Taffy style uses:

```rust
FlexWrap::Wrap
```

The V1 engine delegates line formation to Taffy. There is no editor-level drag
insertion or reorder behavior in this branch.

## Natural Size Heuristics

V1 uses deterministic heuristics for natural size. These are good enough for
layout tests and early slot-fit validation, but they are not a full text,
image, vector, or PDF measurement engine.

Current natural-size behavior:

| Node kind | Natural size |
|---|---|
| `Text` | estimated text width and one line-height |
| `Image` | fixed size if present, otherwise zero |
| `Line` | absolute `x2`, `y2` |
| `Frame` / `Group` / `AutoLayout` with no children | fixed size if present, otherwise zero |
| `Frame` / `Group` / `AutoLayout` with children | max child transform plus child natural size |
| `Rect` / `Ellipse` / `Vector` / `Instance` | fixed size if present, otherwise zero |

Text natural-size estimate:

- whitespace character weight: `0.33`
- ASCII uppercase character weight: `0.62`
- other character weight: `0.52`
- width: weighted character count multiplied by font size
- line height: `font_size * 1.2`

When Taffy asks for measured text size with a definite available width, the
engine estimates wrapped height using:

```text
ceil(unwrapped_width / available_width) * line_height
```

This is intentionally explicit and limited. It does not claim to solve shaping,
font fallback, ligatures, hyphenation, bidi, non-Latin scripts, or real PDF
font metrics.

## Computed Geometry

Layout output is written into existing `ComputedGeometry`:

```rust
pub struct ComputedGeometry {
    pub layout_bounds: Rect,
    pub render_bounds: Rect,
}
```

### `layout_bounds`

`layout_bounds` is the layout-space rectangle:

- absolute page-space x
- absolute page-space y
- computed width
- computed height

It is the box used by layout and slot fit checks.

### `render_bounds`

`render_bounds` is the conservative visible/export/editor bounds rectangle.

For untransformed nodes, it equals `layout_bounds`.

For rotated, skewed, or flipped nodes, the engine transforms the four rectangle
corners and stores the axis-aligned bounding box. The current transform model
uses the node's top-left layout origin as the transform origin.

Safe-area validation uses `render_bounds`, not `layout_bounds`, so transformed
required slots are checked against their visible bounds.

## Transformed Children In Auto-Layout

Children with any of the following are excluded from auto-layout flow:

- non-zero rotation
- non-zero `skew_x`
- non-zero `skew_y`

They produce:

```text
LUMV0701 warning
```

The child is still laid out manually using its explicit transform relative to
the auto-layout parent. This matches the V1 rule that transformed children are
not silently included in naive flow math.

Flipped children are not excluded from flow, but their `render_bounds` accounts
for the flip.

## Slot Layer

Slots are validation metadata. They are not layout primitives.

The layout engine never changes:

- slot definitions
- slot bindings
- placeholder text
- text content
- font size
- image policy
- conditional rules
- repeater rules

Slots are used only after geometry is computed. The validator resolves:

1. slot fixtures
2. bound nodes
3. computed geometry
4. page ancestry
5. safe area
6. policy shape
7. overflow implications

## Slot Fixtures

For each slot, V1 constructs a deduplicated fixture list from:

1. `slot.placeholder`
2. `slot.validation.samples`
3. `slot.validation.worst_case`
4. a synthetic `"M"` string from `slot.validation.max_length`
5. a synthetic `"M"` string from `slot.formatting.max_length` if validation
   max length is absent

Synthetic max-length strings are capped at 512 characters.

Empty or whitespace-only fixture strings are ignored.

Required slots with no usable fixture emit:

```text
LUMV0800 error
```

## Text Slot Fit Validation

Text slot fit validation applies only when:

- the slot content type is `TextShort`, `TextLong`, or `RichTextLimited`, and
- the bound node is `NodeKind::Text`.

Current limitation: V1 does not yet emit a type-mismatch diagnostic when a text
slot is bound to a non-text node. That should be added before finalization rules
become stricter.

For each fixture, the engine checks fit against the bound node's
`layout_bounds`.

### Non-Wrap Fit

For non-wrap policies, a fixture fits when:

```text
estimated_text_width <= bounds.width
line_height <= bounds.height
```

### Wrap Fit

For `OverflowPolicy::Wrap`, the engine estimates:

```text
line_count = ceil(estimated_text_width / bounds.width)
```

Available lines are:

```text
floor(bounds.height / line_height)
```

Allowed lines are:

```text
min(max_lines.unwrap_or(available_lines), available_lines)
```

The fixture fits only when:

```text
line_count <= allowed_lines
```

### Shrink Font

For `OverflowPolicy::ShrinkFont`, V1 diagnoses feasibility only.

Current behavior:

- Check at the node's current font size.
- If it overflows, check again at `min_font_size`.
- If the min-size check fits, emit an advice diagnostic.
- If the min-size check still overflows, emit an error diagnostic.
- Do not write a new font size.
- Do not produce a `NodePatch` that changes text style.

`max_font_size` is preserved in the policy model but is not currently used by
the V1 feasibility check.

### Clip And Ellipsis

`Clip` and `Ellipsis` allow the layout to proceed but emit a warning when a
fixture overflows, because content may be lost.

### Expand Container

`ExpandContainer` emits advice when a fixture overflows. V1 does not resize the
container or generate repair operations.

### Ask Agent To Repair

`AskAgentToRepair` emits a warning when a fixture overflows. V1 does not call an
agent or generate repair operations.

## Image And Logo Policy Validation

Image-like slots are:

- `ContentType::Image`
- `ContentType::Logo`

They must have `slot.image_policy`.

Because `ImagePolicy.fit` is a required enum field, the fit mode is present when
the policy exists. V1 validates policy shape rather than applying image layout.

Checks:

- missing image policy
- focal point in `0.0..=1.0`
- positive aspect ratio when aspect ratio is present
- min-DPI present when print fidelity is required

Print fidelity is required when either:

- `scene.meta.medium` is `Print` or `DirectMail`, or
- any export profile has `pdf_intent = Print`, or
- any export profile has `include_bleed = true`

V1 does not validate real asset pixel dimensions, real DPI, transparency, or
licensing/provenance metadata.

## Required Slot Safe-Area Validation

For required slots, every bound node is checked against its page safe area when
the page has `safe_area`.

The check uses:

```text
geometry.render_bounds inside page.safe_area
```

If the page has no safe area, V1 does not emit a safe-area diagnostic.

Optional slots are not currently safe-area checked.

## Conditional Rule Validation

Conditionals are scaffolded only.

Current checks:

- empty `ConditionalRule.expression` emits an error
- `EmptyBehavior::UseFallback` without placeholder emits a warning

V1 does not:

- evaluate expressions
- hide regions
- preserve placeholders at runtime
- substitute fallback content
- reflow after conditional hiding

## Repeater Rule Validation

Repeaters are scaffolded only.

Current checks:

- slot with repeater behavior must use `ContentType::RepeaterGroup`
- `template_node_id` must exist
- `max_items` must be greater than or equal to `min_items`
- `ReflowPolicy::Paginate` emits advice because pagination is not applied

V1 does not:

- clone repeated regions
- bind item data
- evaluate runtime item counts
- hide missing items
- wrap repeated regions
- paginate repeated regions
- repair overflow

## Diagnostic Codes

All diagnostics below use `Phase::Layout`.

| Code | Severity | Subject | Meaning |
|---|---|---|---|
| `LUMV0700` | Error | Node | Failed to build or compute a Taffy layout tree. |
| `LUMV0701` | Warning | Node | Rotated or skewed auto-layout child was excluded from normal flow. |
| `LUMV0800` | Error | Slot | Required slot has no placeholder or validation fixture. |
| `LUMV0801` | Error | Slot | Slot binds a missing node. |
| `LUMV0802` | Error | Slot | Bound node has no computed geometry. |
| `LUMV0803` | Error | Slot | Required slot bound node falls outside page safe area. |
| `LUMV0810` | Error | Slot | Text fixture overflows under `Error` policy. |
| `LUMV0811` | Advice | Slot | Text fixture would likely fit by shrinking, but V1 does not mutate font size. |
| `LUMV0812` | Error | Slot | Text fixture still overflows at `min_font_size`. |
| `LUMV0813` | Error | Slot | Text fixture exceeds wrap line limits or available lines. |
| `LUMV0814` | Warning | Slot | `Clip` or `Ellipsis` may lose overflowing content. |
| `LUMV0815` | Warning | Slot | Slot needs agent repair under `AskAgentToRepair`. |
| `LUMV0816` | Advice | Slot | Slot would require expansion, but V1 does not resize containers. |
| `LUMV0820` | Error | Slot | Image-like slot has no image policy. |
| `LUMV0821` | Error | Slot | Image focal point is outside `0.0..=1.0`. |
| `LUMV0822` | Error | Slot | Image aspect ratio is non-positive. |
| `LUMV0823` | Error | Slot | Print-sensitive image slot lacks a `min_dpi` policy. |
| `LUMV0830` | Error | Slot | Conditional rule expression is empty. |
| `LUMV0831` | Warning | Slot | Conditional fallback behavior lacks fallback content. |
| `LUMV0840` | Error | Slot | Slot has repeater behavior but is not a repeater group. |
| `LUMV0841` | Error | Slot | Repeater references a missing template node. |
| `LUMV0842` | Error | Slot | Repeater `max_items` is below `min_items`. |
| `LUMV0843` | Advice | Slot | Repeater requests pagination, which is not applied in V1. |

## Example Usage

Geometry-only use:

```rust
let result = layout_scene(
    &scene,
    LayoutOptions {
        validate_slots: false,
    },
);

for (node_id, computed) in result.geometry {
    println!("{node_id}: {:?}", computed.layout_bounds);
}
```

Preflight use:

```rust
let mut diagnostics = validate_scene(&scene);
diagnostics.extend(validate_layout(&scene, LayoutOptions::default()));

let has_errors = diagnostics
    .iter()
    .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error);
```

Persist computed geometry:

```rust
let result = layout_scene(
    &scene,
    LayoutOptions {
        validate_slots: false,
    },
);

if result
    .diagnostics
    .iter()
    .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error)
{
    let operations = layout_operations(
        &scene,
        LayoutOptions {
            validate_slots: false,
        },
    );
    scene.apply_operations_checked(operations)?;
}
```

Callers can also reuse `result.geometry` directly and construct operations
without recomputing if they need to avoid a second layout pass.

## Test Coverage

`crates/lumen-core/tests/layout_engine.rs` currently covers:

- row layout with fixed children
- column layout with fixed children
- gap and padding offsets
- weighted fill distribution
- hug parent sizing
- fill-to-hug fallback
- wrapping into multiple lines
- transformed child exclusion and render bounds
- computed geometry persisted through operation patches
- required slot without usable content
- text fixture that fits
- text overflow with `Error`
- shrink-font feasibility without mutation
- wrap max-line overflow
- clip and ellipsis lossy-content warnings
- required slot outside safe area
- image/logo invalid focal point, aspect ratio, and min-DPI policy
- repeater and conditional scaffold validation

The full workspace verification for this implementation passed:

```bash
cargo fmt --check
cargo test
cargo check --target wasm32-unknown-unknown
```

## Current Limitations

The following are explicit V1 boundaries:

- no applied font-size mutation for `ShrinkFont`
- no real text shaping
- no font fallback
- no font licensing checks
- no bidirectional text support
- no non-Latin shaping correctness
- no hyphenation
- no real line-breaking engine
- no automatic pagination
- no live editor drag insertion or reorder behavior
- no agent repair loop
- no brand-token-aware measurement
- no real image metadata or DPI validation
- no asset provenance/licensing validation
- no condition evaluation
- no repeater cloning
- no runtime visibility changes
- no center/end/space-between alignment
- no margins
- no absolute positioning model beyond transformed-child exclusion/manual transforms
- no component-instance expansion
- no vector geometry measurement beyond fixed size

These are not hidden implementation details. They are deferred subsystems.

## VNext Priorities

The highest-priority next steps are:

1. Promote `ShrinkFont` from feasibility diagnostics to applied layout
   operations when safe.
2. Replace heuristic text measurement with a controlled text measurement
   subsystem that can be shared by server export and browser/editor preview.
3. Add better wrap and ellipsis behavior while preserving the existing
   `OverflowPolicy` contract.
4. Add explicit diagnostics for text slots bound to non-text nodes and image
   slots bound to non-image nodes.
5. Define operational semantics for conditionals and repeaters before adding
   cloning, hiding, or reflow behavior.
6. Add alignment controls if the scene contract grows explicit alignment fields.
7. Add asset metadata inputs for real image DPI/aspect validation.

The important contract point is that the current slot policy model already
contains the variants needed for these upgrades. Future work should add applied
behavior behind the existing policy model rather than replacing the slot
contract.

## Downstream Integration Guidance

Editor workstreams should:

- render `node.computed.layout_bounds` when present
- keep editor interaction semantics separate from core layout semantics
- use `layout_operations` or equivalent `UpdateNode` patches to persist
  computed geometry
- surface `Phase::Layout` diagnostics in the inspector or validation UI

Export workstreams should:

- treat computed geometry as the canonical box model when present
- use `render_bounds` for conservative visibility and safe-area reporting
- run structural and layout validation before final exports
- avoid inventing export-specific slot-fit behavior

Agent workstreams should:

- call `validate_layout` during critique/repair loops
- inspect stable diagnostic codes
- propose operations against scene nodes and slot policies
- avoid directly mutating text size for `ShrinkFont` until applied repair
  semantics are implemented

API/persistence workstreams should:

- store `ComputedGeometry` inside the existing scene JSON
- store layout changes as operations when keeping an operation history
- run checked operation application at trust boundaries
- not redefine slot/layout validation in database models

DSL/compiler workstreams should:

- continue lowering lightweight slot annotations to the canonical slot model
- not encode rich overflow, fit, conditional, or repeater semantics directly in
  node names
- emit layout-capable scenes and let `lumen-core` validate slot behavior

## Implementation Invariants

The current implementation relies on these invariants:

- `Scene` remains the canonical runtime model.
- `Operation` remains the canonical mutation surface.
- Slots are semantic metadata, not layout primitives.
- Taffy IDs are temporary implementation details.
- Layout diagnostics use `Phase::Layout`.
- Structural diagnostics remain in `validate_scene`.
- Computed geometry uses existing `ComputedGeometry`.
- Layout does not mutate the scene directly.
- Persisted layout output goes through `Operation::UpdateNode`.
- V1 text fit diagnostics must not pretend to be full text shaping.
