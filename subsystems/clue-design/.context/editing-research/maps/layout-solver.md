# Layout Solver & Geometry Resolution — Subsystem Map

Scope: how Lumen turns authored layout intent (fill/hug/fixed + align + gap + pad +
transform) into resolved absolute rects, where that geometry lives, and what it would
take to "freeze" it for freehand editing and round-trip it back to the agent.

Primary files:
- `crates/lumen-core/src/layout.rs` (the solver; 1706 lines)
- `crates/lumen-core/src/page_geometry.rs` (page/artboard rect + unit conversion)
- `crates/lumen-core/src/render_geometry.rs` (read-side geometry accessors)
- `crates/lumen-core/src/text_measure.rs` (text sizing the solver depends on)
- `crates/lumen-core/src/scene.rs` (the data model: `Node`, `Transform`, `Dimension`, `ComputedGeometry`)
- Consumers: `crates/lumen-wasm/src/engine.rs` (`relayout`), `crates/lumen-core/src/preflight.rs`, `apps/editor/src/engine/{sceneQueries,canvasOperations,renderAdapter}.ts`

---

## 1. The data model — authored intent vs resolved pixels

Two distinct representations coexist on every `Node` (`scene.rs:268-320`):

**Authored intent (input to the solver):**
- `transform: Transform` (`scene.rs:273`, def `503-512`): `{ x, y, rotation, skew_x, skew_y, flip_x, flip_y }`. `x`/`y` are a **parent-relative offset** in scene points.
- `size: SizeSpec` (`scene.rs:274`, `528-550`): `width`/`height` each a `Dimension`:
  - `Dimension::Fixed(f64)` — fixed points
  - `Dimension::Hug` — size to content
  - `Dimension::Fill { weight }` — grow to fill parent (weight = flex-grow)
  - `Dimension::Token { token }` — unresolved brand token (treated as Hug at layout time)
- `layout: Option<AutoLayoutProps>` (`scene.rs:292`, `470-483`): only meaningful when `kind == AutoLayout`. Holds `gap`, `padding: [f64;4]` (top, right, bottom, left), `grow`, `align_x: LayoutAnchor`, `align_y: LayoutAnchor`.
- `kind: NodeKind` (`scene.rs:322-335`): `Frame | Group | Rect | Ellipse | Line | Text | Image | Vector | AutoLayout(direction,wrap) | Instance`.

**Resolved pixels (output of the solver):**
- `computed: Option<ComputedGeometry>` (`scene.rs:293`, `704-708`): `{ layout_bounds: Rect, render_bounds: Rect }`. **`Rect` is absolute, page-space `{x,y,width,height}`** (`scene.rs:696-702`). `layout_bounds` = axis-aligned solved box; `render_bounds` = bounding box after rotation/skew/flip.

`computed` is a **derived render cache**, not authored data. It is `None` until a layout pass writes it (`engine.rs:119-128` documents this explicitly). It serializes with the scene (no `skip_serializing`), so a persisted scene carries the last solved geometry, but it is always recomputed and overwritten on the next layout pass.

> **Boundary between intent and pixels:** `transform`+`size`+`layout`+`kind` are the *intent*; `computed` is the *resolved pixels*. The solver reads intent + parent context and writes `computed`. Nothing in the solver reads `computed` back as input — it is purely an output sink (verified: no read of `node.computed` inside `layout.rs`).

---

## 2. Two layout regimes: absolute (Frame/Group) vs flex (AutoLayout)

The engine has **two completely different positioning paths**, dispatched per node in `layout_node_at` (`layout.rs:150-193`):

### Regime A — Absolute / manual (Frame, Group, and all leaf kinds)
`layout_node_at` (`layout.rs:150-193`):
- Computes size via `resolve_manual_size` (`629-642`): `Fixed→value`, `Fill→parent_size on that axis`, `Hug|Token→natural_size`.
- Writes geometry at the **passed-in `origin`** (`write_geometry`, line 177).
- Recurses into children, **adding each child's `transform.x/y` to the parent origin** (`183-191`):
  ```rust
  self.layout_node_at(child_id,
      Point2 { x: origin.x + child.transform.x, y: origin.y + child.transform.y },
      size, page_id);
  ```
- Top-level page children also start from `child.transform.x/y` relative to page origin (`layout_pages`, `141-145`).

**→ For a Frame/Group child, `transform.x/y` IS the position. The solver honors it.** This is the existing "absolute positioning" path.

### Regime B — Flex / auto-layout (AutoLayout nodes and their in-flow children)
`layout_auto_node` (`layout.rs:195-242`) builds a **Taffy** (flexbox) tree:
- `build_taffy_node` (`244-297`) recursively maps each Lumen node to a Taffy node with a `Style` from `style_for_node`.
- `tree.compute_layout_with_measure(...)` runs Taffy's flex solver (`225-231`).
- `collect_taffy_geometry` (`299-374`) walks the Taffy result and writes `computed` using **Taffy's `layout.location` (the flex-solved position)** added to the parent origin (`322-330`):
  ```rust
  let origin = Point2 { x: parent_origin.x + f64::from(layout.location.x),
                        y: parent_origin.y + f64::from(layout.location.y) };
  ```

**→ For an in-flow auto-layout child, `transform.x/y` is completely IGNORED. Taffy decides the position from flow + align + gap + pad.** The authored `transform` is never consulted (it isn't passed into `build_taffy_node` or the Taffy `Style`).

### The one escape hatch that exists today
Inside an AutoLayout parent, a child is pulled **out of flow** if it is rotated or skewed — `is_out_of_flow_transform` (`layout.rs:1508-1512`): true when `rotation`, `skew_x`, or `skew_y` is non-zero. Such a child:
- is **excluded** from the Taffy children list (`build_taffy_node`, `264-282`) and emits warning `LUMV0701`;
- is **not** in the Taffy map, so `collect_taffy_geometry` lays it out via the absolute path `layout_node_at`, **honoring its `transform.x/y`** as an offset from the parent's solved origin (`340-357`).

> **This is the only existing mechanism by which a node escapes the flex solver, and it is a side effect of rotation/skew — not an intended "free placement" flag.** A non-rotated child of an auto-layout parent has **no way** to opt out of flow. There is no `absolute`, `position`, `pinned`, or `freehand` field on `Node` or `AutoLayoutProps` (verified: grep of scene.rs and the whole crate found nothing).

---

## 3. How fill / hug / fixed map to the solver

`taffy_dimension_for_node` (`layout.rs:500-532`) converts a `Dimension` to a Taffy `Dimension` per axis, given the parent's flow context:

| `Dimension` | Taffy result | Notes |
|---|---|---|
| `Fixed(v)` | `length(v)` | exact points |
| `Hug` | `auto()` | sized by measure callback / content |
| `Fill{weight}` on **main axis** | `auto()` + `flex_grow = weight` | grow set in `style_for_node` (`443-460`) |
| `Fill{weight}` on **cross axis** | `percent(1.0)` if cross has definite space, else `auto()` | |
| `Fill` with **no flow / no parent** | `length(parent_size on axis)` or `auto()` | absolute path fallback |
| `Token{..}` | `auto()` | unresolved token → hug; emits `LUMV0702` warning (`376-415`) |

`flex_grow` is set from `Dimension::Fill{weight}` **only** (`style_for_node:443-460`), guarded by `fill_fallback_nodes` (a `Fill` child that cannot fit is demoted to its natural size — `flow_context:565-590`, prevents overflow deadlocks).

> **Note:** `AutoLayoutProps.grow` (`scene.rs:478`) is authored/stored and round-trips, but the **solver never reads it** — flex-grow comes exclusively from `Dimension::Fill{weight}`. The node-level `grow` field is effectively dead in the solver.

`natural_size` (`layout.rs:644-685`) computes hug/content size:
- Text → `measurer.measure(...)` (heuristic or injected Skia metrics)
- Image/Rect/Ellipse/Vector/Instance → `fixed_or_zero` (fixed dims or 0)
- Line → `(|x2|, |y2|)`
- Frame/Group/AutoLayout with children → **bounding box of children using `child.transform.x + child_size`** (`664-678`) — i.e. hug of an absolute container measures children by their `transform` offsets.

---

## 4. How align / gap / pad are applied

In `style_for_node` (`layout.rs:462-495`), only for `NodeKind::AutoLayout` with `layout` props:
- `flex_direction` from `auto.direction` (Row/Column).
- `flex_wrap` from `auto.wrap`.
- `gap` = `length(props.gap)` on both axes (`473-476`).
- `padding` mapped `TaffyRect { left: padding[3], right: padding[1], top: padding[0], bottom: padding[2] }` (`477-482`) — note the `[top, right, bottom, left]` storage order.
- **Align mapping depends on direction** (`483-494`):
  - Row: `justify_content = main_axis_alignment(align_x)`, `align_items = cross_axis_alignment(align_y)`, `align_content = cross_axis_content_alignment(align_y)`.
  - Column: `justify_content = main_axis_alignment(align_y)`, `align_items = cross_axis_alignment(align_x)`, `align_content = cross_axis_content_alignment(align_x)`.

`LayoutAnchor` → Taffy translation:
- `main_axis_alignment` (`1359-1366`): Start/Stretch→`Start`, Center→`Center`, End→`End`, SpaceBetween→`SpaceBetween`.
- `cross_axis_alignment` (`1368-1376`): Start→`Start`, Center→`Center`, End→`End`, Stretch→`Stretch`, SpaceBetween→`Start` (falls back).
- Validation `validate_layout_anchors` (`889-909`, `1388-1431`): `Stretch` on main axis or `SpaceBetween` on cross axis → warning `LUMV0710`.

**DSL surface (important — two different meanings of x/y):**
- `pos(x,y)` / `p(x,y)` → `DslProperty::Position` → writes `node.transform.x/y` (`dsl.rs:3078-3084`, applied `2344-2347` and `3695-3698`). This is the **offset**.
- `x(center)` / `y(sb)` → `DslProperty::LayoutAnchor` → writes `AutoLayoutProps.align_x/align_y` (`dsl.rs:3419-3432`). This is the **align mode**.
- `s(w,h)` / `size(w,h)` → `DslProperty::Size` (`dsl.rs:3085-3094`). `s(fill,hug)` etc.
- `gap(n)`, `pad(...)`, `grow(n)` → `AutoLayoutProps`.

---

## 5. Where geometry is stored and when it is recomputed ("layout-managed", mechanically)

### Entry points
- `layout_scene(scene, options) -> LayoutResult { geometry: BTreeMap<NodeId, ComputedGeometry>, diagnostics }` (`layout.rs:72-92`). Pure function: takes a `&Scene`, returns a geometry map; **does not mutate the scene**.
- `layout_operations(scene, options) -> Vec<Operation>` (`98-110`): wraps each computed geometry in `Operation::UpdateNode { patch.computed = Set(...) }`.

### Write-back paths (where `computed` lands on the node)
1. **Editor (WASM) — `WasmEngine::relayout`** (`engine.rs:129-140`): runs `layout_scene`, then writes `node.computed = Some(computed)` directly onto scene nodes (no operations). Called on `load_scene` (`115`) and after every edit. Documented as a "derived render cache" that "writes geometry directly onto nodes — it does NOT emit operations" so recomputed geometry "never enters the authored edits sent to the server."
2. **Server / preflight — `preflight_scene`** (`preflight.rs:164-195`): runs `layout_scene` after token resolution, builds `layout_operations` setting `computed`, and applies them to the scene so previews/repair agents see solved geometry.

### What gets recomputed on a change
The solver is **whole-tree, recompute-on-demand**. There is no incremental/dirty-tracking layout. Every `relayout` re-solves all pages and overwrites every node's `computed` (`engine.rs:135-138`). The doc comment claims idempotence: re-laying out an unedited scene leaves unedited nodes unchanged, so an edit "only moves the node it touched and that node's true layout dependents" — but mechanically the whole map is recomputed; it just produces identical values for untouched subtrees.

### The cache-invalidation contract
When an edit changes a render-affecting field, `computed` is **cleared** so it can't go stale:
- `editing.rs:1002-1006`: if `node_patch_affects_render(patch)` (or image asset changes), set `node_patch.computed = Clear`.
- `node_patch_affects_render` (`editing.rs:2089-2103`) returns true for changes to `kind`, **`transform`**, **`size`**, fills, strokes, effects, corner, opacity, asset, clip, **`layout`**. Mirrored on the editor side in `operations.ts:65-79`.
- So a human drag (a `transform` patch) clears `computed`; the next `relayout` re-solves. **For a Frame/Group child the re-solve honors the new transform; for an auto-layout child the re-solve discards it.** This is the exact source of "drag fought the solver."

### Read-side accessors (`render_geometry.rs`)
- `node_render_size(node)` (`11-20`): prefers `computed.layout_bounds.{w,h}`, else falls back to fixed dims (Hug/Fill/Token → 0).
- `render_box_for_node(node, parent_origin)` (`22-45`): prefers `computed.layout_bounds` made parent-relative; else falls back to `transform.x/y` + fixed size.
- Editor mirror `nodePositionForRender` (`renderAdapter.ts:487-517`): uses `computed.layout_bounds` when present; for a **layout-managed** node with no `computed` it returns `{0,0}` rather than `transform` (because "`transform` is NOT its real position — flow owns it").

---

## 6. Page / artboard geometry

`page_geometry(page)` (`page_geometry.rs:45-66`) returns the page `layout: Rect { 0, 0, width, height }` in canonical points. `normalize_page_size` (`72-91`) converts authored units (mm/in/px) to points at author time and stores `unit: Pt` canonically. The page rect is the root coordinate space; all node `computed` rects are absolute in this space. Bounds validation (`validate_artboard_bounds`, `744-853`) checks node `layout_bounds`/`render_bounds` against page/parent rects (`LUMV0800/0801/0802`), with a 1pt tolerance for the root frame (`PAGE_BOUNDS_TOLERANCE_PT`, `1672-1691`).

---

## 7. The editor's current "layout-managed" gate (what already ships)

`apps/editor/src/engine/sceneQueries.ts`:
- `isNodeLayoutManaged(scene, nodeId)` (`172-181`): **true iff the node's parent is an `auto_layout` node.**
- `isNodeDirectGeometryEditable(scene, nodeId)` (`183-192`): `!locked && !isNodeLayoutManaged`.

`canvasOperations.ts` `buildCanvasTransformPatch` (`~75-104`): **bails out (`isNodeDirectGeometryEditable` false) for layout-managed or locked nodes** — so the editor today silently refuses direct drag/resize on any auto-layout child. For directly-editable nodes it writes a `transform` patch (x/y from canvas, rotation, scaled size) and clamps to parent bounds (`clampNodeTransformToParentBounds`, `sceneQueries.ts:194-209`).

The inspector reflects this state: `InspectorPanel.tsx:193` `layoutManaged`, the "Layout-managed child" label (`994-1003`), and "layout-managed children can change sizing mode even when their direct X/Y geometry is locked" (`372`). `SelectionOverlay` hides resize/rotate handles for layout-managed nodes (`SelectionOverlay.tsx:42`).

> **So "layout-managed" already exists as a UI concept, defined purely by "parent is auto_layout." The editor's answer today is: allow direct geometry edits only for non-auto-layout-child nodes; everything else is solver-owned and hands-off.**

---

## 8. The agent authoring / round-trip model (how an edit gets "taken back")

- Agents author by emitting **DSL text blocks**, compiled incrementally through a `DslCompileSession` (`dsl.rs:158-226`; agent side `apps/agent_runtime/lumen_deepagent/tools.py:170-261` `compile_dsl_block`).
- The session tracks `seen_node_ids`, `parent_stack`, `emitted_slots` (`DslCompileSessionSnapshot`, `dsl.rs:236-243`) — i.e. **identity-by-NodeId**, plus the indentation/parent cursor for *append* continuation.
- The DSL has a **`modify #node_id`** grammar that targets any existing node by id and emits `UpdateNode`/`MoveNode` operations (`build_modify_operations`, `build_move_to_parent`, etc. — `editing.rs:1467-1709`).
- **There is NO scene→DSL serializer in the codebase** (verified: no `to_dsl`/`scene_to_dsl`/`emit_dsl` anywhere in `crates/` or `apps/`). The agent does not regenerate DSL from a scene; it appends/modifies. The canonical state is the **scene (operations applied to JSON)**, not DSL text.
- `sync_scene_preserving_context(scene)` (`dsl.rs:208-217`) lets a session adopt an externally-mutated scene while keeping its parser cursor, then `retain`s only parent-stack frames whose parent can still receive children.

**Re-parenting semantics (critical for round-trip):** `MoveNode` (`operations.rs:505-554`) changes only child-list membership. It **does not adjust `transform.x/y`** — there is no coordinate-space conversion. `build_ungroup` (`editing.rs:1318-1402`) likewise moves children and only **clears `computed`**, leaving `transform` untouched so the next preflight re-solves positions. So a node's `transform` is reinterpreted relative to whatever parent it lands in.

---

## 9. Editing implications & round-trip

### What EXISTS today
1. **Absolute positioning is already real for Frame/Group/leaf children.** `transform.x/y` is honored as a parent-relative offset by `layout_node_at` (`layout.rs:183-191`). A subtree of plain Frames behaves like a free-placement canvas; the editor already lets you drag/resize those nodes (`isNodeDirectGeometryEditable`).
2. **`computed` (`ComputedGeometry`) is exactly the "resolved absolute rect" representation** a freeze would need — it is absolute page-space, serialized with the scene, written by both editor and server paths.
3. **A "layout-managed" boolean already gates the editor UI**, defined as "parent is auto_layout" (`sceneQueries.ts:172-181`).
4. **One escape hatch exists**: rotating/skewing an auto-layout child pulls it out of flow and makes its `transform` honored (`layout.rs:264-282`, `340-357`) — but it's an accidental mechanism, costs a rotation, and emits a warning.
5. **The agent round-trip is identity-based, not DSL-text-based.** Any node that exists in the scene (however it got there) is addressable by `modify #id`, and `MoveNode` re-parenting is already a first-class operation.

### What is MISSING for a real FREEHAND mode
1. **No per-node "escape the solver" flag.** There is no `position: absolute`, `pinned`, or `freehand` field on `Node`/`AutoLayoutProps`. To let a *non-rotated* child of an auto-layout opt out of flow, the model needs a new field, and `build_taffy_node`/`collect_taffy_geometry` need to route flagged children through the absolute `layout_node_at` path (the rotation hack already shows the wiring point — `layout.rs:264-282`, `340-357`).
2. **No coordinate-space conversion on regime switch.** Switching a node from flow to absolute (or re-parenting) does **not** convert its `transform` from "flow-decided" to "explicit." `MoveNode` keeps the old `transform` verbatim (`operations.rs:505-554`). A freehand toggle must first **bake** the current solved position: read `computed.layout_bounds`, subtract the parent's solved origin, and write the result into `transform.x/y` (and `size` into `Fixed`). Nothing does this today.
3. **No "freeze subtree to absolute" routine.** A freeze would: for each node in the subtree, set `transform.x/y` ← (`computed.layout_bounds.x/y` − parent `computed` origin), set `size.width/height` ← `Fixed(computed.layout_bounds.w/h)`, and clear `Hug/Fill` so the next relayout reproduces the same pixels. The raw inputs all exist (`render_geometry.rs:22-45` already does the parent-relative subtraction for rendering); only the write-back operation is missing.
4. **Toggling off auto-layout on a container is destructive and guarded.** `build_ungroup` refuses auto-layout containers without `allow_layout` and, when forced, deletes the container and clears `computed` (`editing.rs:1345-1354`, `1380-1397`). There is no "keep the Frame, just turn flow off and bake child positions" operation.
5. **Token/Hug/Fill dimensions don't carry a resolved value.** `Dimension` has no slot for "resolved px." Freezing must rewrite them to `Fixed`, which **discards authored intent** — a one-way lossy conversion unless intent is stored separately.

### The round-trip ("can the agent take it back?") — assessment
- **Mechanically YES, because state is scene-not-DSL and addressing is by NodeId.** After a human freehand edit (transform change, regime switch, re-parent), the node still exists with the same id, so the agent can `modify #id`, `move`, restyle, or delete it. The `DslCompileSession` survives an externally-mutated scene via `sync_scene_preserving_context` (`dsl.rs:208-217`).
- **But "resume editing intelligently" is degraded after a freeze.** If freehand baked `Hug/Fill` into `Fixed` and dropped a node out of flow, the agent loses the semantic intent (e.g., "this fills the row"). The agent would see fixed boxes at absolute offsets and could not re-flow them without re-authoring the auto-layout relationship. **No mechanism preserves authored intent alongside a frozen override** (e.g., a `freehand_override` layer separate from the solver inputs). Designing one — keep `size`/`layout` as intent, add an optional `absolute_override: Option<Rect>` consulted by the solver — is the key representational choice that makes a *clean* round-trip possible.
- **Re-parenting into/out of an auto-layout is the sharpest edge.** Because `MoveNode` does no coordinate conversion, a human dragging a node from a Frame into an auto-layout (or vice versa) will see it jump on the next relayout (flow ignores `transform`; or absolute honors a now-meaningless `transform`). Any freehand mode must bracket re-parents with a bake-then-convert step.

### Realistic scope to make freehand usable (engine-side)
- (S) Add `absolute_override: Option<Rect>` (or a `positioning: Auto|Absolute` enum + frozen `transform`/`size`) to `Node`; have `build_taffy_node` exclude overridden children from flow and `collect_taffy_geometry` lay them out absolutely (mirror the rotation path).
- (S) Add a `freeze_subtree` edit op: read `computed`, write parent-relative `transform` + `Fixed` size (+ set the override flag). Inverse = clear the override.
- (M) Add a non-destructive "disable flow on this container" op (vs ungroup) that bakes child positions.
- (M) Decide intent-preservation: store solver inputs (`size`/`layout`) untouched and let the override win, so the agent can later "re-enable layout" losslessly.
- (S) Bracket `MoveNode` with coordinate conversion when crossing a flow boundary.

---

## Diagnostics emitted by the solver (for completeness)
`LUMV0700` build/compute failure; `LUMV0701` rotated/skewed child excluded from flow; `LUMV0702` unresolved token dimension → hug; `LUMV0710` invalid anchor; `LUMV0800/0801/0802/0803` bounds/safe-area; `LUMV0900-0904` text metrics/overflow; `LUMV0810-0816` slot text-fit. All are warnings/errors on the resolved geometry — none block or alter the solve itself except by being surfaced to the repair loop.
