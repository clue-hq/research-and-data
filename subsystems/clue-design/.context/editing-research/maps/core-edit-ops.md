# Core Edit Operations — Subsystem Map

Scope: the canonical mutation layer of the Lumen engine. Two Rust files own it:
- `crates/lumen-core/src/operations.rs` (1334 lines) — the **canonical `Operation` enum** and its in-place apply/invert/validation logic. This is the *only* code path that mutates a `Scene`.
- `crates/lumen-core/src/editing.rs` (2321 lines) — the **structured-edit / patch layer**: typed patches (`NodeEditPatch`, `TextEditPatch`, …), builders (`build_node_modify`, `build_move_*`, `build_clone_subtree`, …), the `StructuredEditInstruction` wire enum, edit scoping, and inverse-batch assembly.

Supporting evidence drawn from `scene.rs` (the node model), `layout.rs` (the solver), `dsl.rs` (the authoring language), `validation.rs` (forbidden states), and the editor/WASM bindings (`apps/editor/src/engine/*`, `crates/lumen-wasm/src/engine.rs`).

> **TL;DR for the editing-system architects:** Every edit funnels through one enum, `Operation` (`operations.rs:131`). There are exactly 21 canonical operations. Geometry is stored two ways: an authored *relative* `Transform{x,y,…}` (`scene.rs:504`) plus a `SizeSpec` of `Dimension::{Fixed|Hug|Fill|Token}` (`scene.rs:529,545`), and a *solved* `ComputedGeometry` cache (`scene.rs:705`). **There is NO absolute-position flag, NO "detach from layout" operation, and NO freehand/layout-management toggle anywhere in the engine.** A node's "layout managed"-ness is purely emergent: it is managed iff its parent is an `AutoLayout` node. Resize = set `SizeSpec` to `Fixed`. Move = set `Transform.x/y` (only meaningful under non-auto-layout parents) or reorder via `MoveNode`. The DSL is **create-only** and rejects re-authoring an existing node id — so the agent round-trip does **not** happen by re-emitting DSL over a human's scene; it happens (today) by additive DSL + targeted `Operation`/structured edits against the persisted scene.

---

## 1. The canonical operation set (WHAT EXISTS TODAY)

All mutation is expressed as one of 21 variants of `enum Operation` (`operations.rs:131-205`). Application is `Scene::apply_operation_in_place` (`operations.rs:271-395`); the public entry points clone a draft, apply, then swap on success so a failed batch leaves the scene untouched (`operations.rs:214-269`).

| Operation | Mutates | Inputs | Key validation (in `apply_operation_in_place` / helpers) |
|---|---|---|---|
| `AddPage{page}` | inserts a `Page` | full `Page` | rejects duplicate page id `op.page_exists` (`operations.rs:397`) |
| `RemovePage{page_id}` | removes page + cascades its node subtrees | page id | `op.page_missing`; recursive `remove_node_recursive` (`operations.rs:408-420`) |
| `UpdateDocument{patch}` | doc meta (title/artifact_type/medium/brand_kit) | `DocumentPatch` | none beyond patch typing (`operations.rs:282-288`) |
| `UpdatePage{page_id,patch}` | page name/size/bleed/safe_area/background | `PagePatch` | `op.page_missing` (`operations.rs:422-436`) |
| **`InsertNode{parent,index,node}`** | adds a node under a parent at index | `ParentRef`, index, full `Node` | dup id `op.node_exists`; leaf-can't-have-children `op.leaf_parent`; child must exist/not-already-parented/no-dup; index bounds (`operations.rs:438-490`) |
| **`RemoveNode{node_id}`** | detaches + recursively deletes subtree; clears slot bindings | node id | `op.node_missing` (`operations.rs:492-503`) |
| **`MoveNode{node_id,new_parent,index}`** | reparent / reorder | node id, `ParentRef`, index | `op.node_missing`; cycle guard `op.cycle` (self/descendant); index bounds incl. post-detach adjust (`operations.rs:505-554`) |
| **`UpdateNode{node_id,patch}`** | the universal node mutator — see §2 | node id, `NodePatch` | `op.node_missing`; can't become leaf while it has children `op.leaf_parent` (`operations.rs:556-597`) |
| `UpsertSlot{slot}` | insert/replace a slot record | `Slot` | none (`operations.rs:302`) |
| `RemoveSlot{slot_id}` | drop slot record (unbinds) | slot id | none (`operations.rs:306`) |
| `UpsertAsset{asset}` | insert/replace asset record | `AssetRecord` | none (`operations.rs:310`) |
| `RemoveAsset{asset_id}` | drop asset record | asset id | refuses if referenced `op.asset_in_use` (`operations.rs:314-326`) |
| `PlaceAssetInNode{node_id,asset_id,placement}` | rewrites node `kind` to Image/Vector, sets `source_asset_id` + `asset_placement` | ids + `AssetPlacement` | leaf-only (`ensure_leaf_asset_target`); font→text-only; kind compatibility (`operations.rs:599-670`) |
| `PlaceAssetInSlot{slot_id,asset_id,placement}` | applies placement to every bound node | ids + placement | slot must be bound + kind-compatible (`operations.rs:672-733`) |
| `BindNodeToSlot{slot_id,node_id}` | append node to slot bindings | ids | node + slot must exist (`operations.rs:337-353`) |
| `UnbindNodeFromSlot{slot_id,node_id}` | remove node from bindings | ids | slot must exist (`operations.rs:355-364`) |
| `SetBrandKitRef{brand_kit_id,version}` | set doc brand kit | id+version | none (`operations.rs:365-374`) |
| `UpsertExportProfile{profile}` | insert/replace export profile by name | `ExportProfile` | none (`operations.rs:375-386`) |
| `RemoveExportProfile{name}` | drop export profile | name | none at op layer (`operations.rs:387-390`) |
| `FinalizeTemplate{template_revision_id}` | flips doc status → Finalized (locks all future mutation) | revision id | must have export profile, no error diagnostics, no incomplete required slots; not invertible (`operations.rs:391-393, 749-802`) |

**Global gate:** once a scene is finalized, *every* non-finalization operation is rejected with `op.finalized_scene` (`operations.rs:272-277`).

**Checked vs. unchecked apply:** `apply_operations_checked` (`operations.rs:240-269`) runs the full `validate_scene` after applying and rolls back the whole batch if any **error**-severity diagnostic appears (`op.validation_failed`). This is the path the editor/WASM and structured edits use — so a batch that produces an invalid scene (e.g. a child overflowing a clipped parent → `LUMV0801`) is rejected atomically.

---

## 2. `UpdateNode` / `NodePatch` — the universal node mutator

`UpdateNode` is where almost every "property edit" lands. The patch struct `NodePatch` (`operations.rs:102-126`) carries one field per mutable node property, each a `FieldPatch<T>` (`Unchanged|Set`) or `OptionalFieldPatch<T>` (`Unchanged|Set|Clear`). Apply is field-by-field via `apply_field_patch`/`apply_optional_patch` (`operations.rs:578-596, 1288-1300`):

- `name` (`OptionalFieldPatch<String>`)
- `kind` (`FieldPatch<NodeKind>`) — **can change a node's type**, e.g. Rect→Text, or change `AutoLayout` direction/wrap. Guard: cannot become a non-container while it still has children (`operations.rs:564-576`).
- `transform` (`FieldPatch<Transform>`) — x, y, rotation, skew_x, skew_y, flip_x, flip_y (`scene.rs:504-512`)
- `size` (`FieldPatch<SizeSpec>`) — width+height, each a `Dimension` (`scene.rs:529-550`)
- `fills` / `strokes` / `effects` (`FieldPatch<Vec<…>>`) — whole-stack replacement
- `corner` (`FieldPatch<CornerRadii>`)
- `opacity` (`FieldPatch<f64>`), `opacity_token` (`OptionalFieldPatch<String>`)
- `source_asset_id`, `asset_placement` (`OptionalFieldPatch`) — recolor/crop metadata lives here
- `clip` (`FieldPatch<bool>`)
- `layout` (`OptionalFieldPatch<AutoLayoutProps>`) — gap/padding/grow/align_x/align_y (`scene.rs:471-483`)
- `computed` (`OptionalFieldPatch<ComputedGeometry>`) — the solved-geometry cache; edit builders `Clear` it when a change affects render (see §5)
- `locked` (`FieldPatch<bool>`)

The **editing.rs `NodeEditPatch`** (`editing.rs:569-595`) is a friendlier superset of `NodePatch`: it adds **per-entry stack edits** (`fill_edits`, `stroke_edits`, `effect_edits` — `StackEntryEdit<T,I>` = `Set|Add|Remove|Reorder` addressed by stable id, `editing.rs:550-567`), a nested `TextEditPatch` (`editing.rs:529-544`: content, font_family, font_size, font_weight, align, line_height, letter_spacing, max_lines, wrap, direction, + token fields), and an `image_asset_id` shortcut that lowers to `PlaceAssetInNode`. `build_node_modify` (`editing.rs:905-1025`) resolves all of this into one `UpdateNode` (plus an optional `PlaceAssetInNode`).

So the answer to "is there an op to set-fill / set-opacity / set-text / set-font / set-color / set-align / set-gap / set-padding / set-size-mode" is: **yes, all of them, and all of them are `UpdateNode` variants** (color/recolor = `fills`/`strokes`; align/gap/padding = `layout`; font/text = `text`/`kind`; size-mode = `size`).

---

## 3. Catalog of edit *builders* (editing.rs) and the structured-edit wire enum

The agent/editor/API never construct `Operation`s by hand for semantic edits; they call **builders** that produce a validated `EditBatch` (operations + inverse + touched targets + intent). The `StructuredEditInstruction` enum (`editing.rs:2208-2246`) is the routing-only wire format; `build_structured_edit_batch` (`editing.rs:2269-2320`) dispatches each variant to exactly one builder:

| Wire instruction (`kind`) | Builder | What it does |
|---|---|---|
| `modify` | `build_modify_operations` → `build_node_modify`/`build_page_modify`/`build_slot_modify`/`build_asset_modify`/`build_document_modify`/`build_export_profile_modify` | property edits per target (`editing.rs:834-1137`) |
| `delete` (node) | `build_safe_delete` | refuses locked node or locked descendant (`editing.rs:1139-1177`) |
| `delete` (page) | `build_safe_delete_page` | protects last page; refuses locked subtree (`editing.rs:1183-1225`) |
| `delete` (slot) | `build_safe_delete_slot` | hard delete record, never deletes bound nodes (`editing.rs:1230-1261`) |
| `delete` (asset) | `build_archive_asset` | archive-first (status change), not removal (`editing.rs:1265-1281`) |
| `move_before` / `move_after` | `build_move_before/after` → `build_relative_move` | same-parent or cross-parent reorder relative to an anchor sibling (`editing.rs:1451-1465, 1657-1707`) |
| `move_to_parent` | `build_move_to_parent` | reparent to explicit parent+index (`editing.rs:1467-1484`) |
| `clone_subtree` | `build_clone_subtree` | deep clone with id remap, slot policy (detach/copy/suffix), computed policy (clear/preserve), records `CloneLineage` (`editing.rs:1486-1575`) |
| `replace_node` | `build_replace_node` | remove target + move replacement into its slot, optional slot preservation (`editing.rs:1577-1655`) |
| `archive_asset` / `hard_delete_asset` | `build_archive_asset` / `build_hard_delete_asset` | archive vs unreferenced hard delete (`editing.rs:1265-1316`) |
| `delete_export_profile` | `build_delete_export_profile` | protects last profile, optional replacement (`editing.rs:1407-1449`) |

**Group / ungroup:** `build_ungroup` (`editing.rs:1323-1402`) exists as a builder (moves children up to the group's parent at the group's index, clears their `computed`, deletes the emptied group; refuses to dissolve an `AutoLayout` container unless `allow_layout`). It is **NOT** in `StructuredEditInstruction` — so it is reachable from Rust callers but not yet exposed on the structured-edit wire format. There is **no `group` builder** (creating a group = `InsertNode` of a Frame/Group then `MoveNode`s — no convenience builder exists).

**Insert:** there is no `insert`/`create-node` variant in `StructuredEditInstruction`. New nodes enter the scene either via raw `Operation::InsertNode` (editor "add element", DSL authoring) or via `clone_subtree`. So the structured-edit surface is deliberately a *modify/move/delete/clone/replace* surface, not a *create* surface.

---

## 4. The geometry model — and the crux for free editing

### 4a. How position is stored (relative) vs. solved
A `Node` (`scene.rs:269-295`) stores:
- `transform: Transform` — `{x, y, rotation, skew_x, skew_y, flip_x, flip_y}` (`scene.rs:504-512`). **x/y are a relative offset from the parent's resolved origin**, not absolute page coordinates.
- `size: SizeSpec` — `{width: Dimension, height: Dimension}` where `Dimension = Fixed(f64) | Hug | Fill{weight} | Token{token}` (`scene.rs:529-550`).
- `computed: Option<ComputedGeometry>` — `{layout_bounds: Rect, render_bounds: Rect}` (`scene.rs:705-708`), the **solver's output cache**, in absolute page space.

The solver (`layout.rs`) consumes `transform`+`size` and writes `computed`. How `transform.x/y` is honored depends entirely on the parent:

- **Page / Frame / Group children (NON-auto-layout):** the child's `transform.x/y` is *added to the parent origin* and used directly as its position — i.e. it behaves like free relative positioning. See `layout_pages` (`layout.rs:141-145`), `layout_node_at` for frame/group children (`layout.rs:179-192`), and `collect_taffy_geometry`'s non-auto branch (`layout.rs:358-372`). Size is taken straight from `resolve_manual_size` (`layout.rs:629-642`: Fixed→value, Fill→parent size, Hug/Token→natural).
- **AutoLayout children:** positions are **solved by Taffy (flexbox)** from gap/padding/align/grow; the child's `transform.x/y` is **ignored** for in-flow children (`build_taffy_node`, `style_for_node`, `collect_taffy_geometry` recursion at `layout.rs:335-338`). The **only** escape hatch is `is_out_of_flow_transform` (`layout.rs:1508-1512`): a child with non-zero rotation or skew is *excluded from flow* (warned as `LUMV0701`, `layout.rs:264-281`) and keeps its explicit transform.

> **This is exactly why the user's prior freehand attempt fought the solver:** under an auto-layout parent, writing `transform.x/y` does nothing — Taffy overwrites the position. Under a frame/group/page parent, `transform.x/y` already *is* free positioning and works fine.

### 4b. The editor already encodes this distinction
`isNodeLayoutManaged(scene, nodeId)` (`apps/editor/src/engine/sceneQueries.ts:172-181`) returns **true iff the node's parent is an `auto_layout` node**. `isNodeDirectGeometryEditable` (`sceneQueries.ts:183-192`) = not-locked AND not-layout-managed. The canvas drag/resize handlers (`canvasOperations.ts:41, 77`) and keyboard nudge (`EditorApp.tsx:662`) **bail out entirely** when a node is layout-managed. So today the editor's answer to "edit a layout-managed node's geometry directly" is: *you can't* — only its inspector sizing-mode and the container's auto-layout props are editable.

### 4c. How RESIZE works today
`canvasResizeOperation` (`canvasOperations.ts:64-114`): multiplies the rendered size by the gesture scale, clamps to parent bounds, then emits **`updateNodeTransformAndSize`** which sets `size` to `{width:{kind:"fixed",value}, height:{kind:"fixed",value}}` and writes the new `transform` (`canvasOperations.ts:104-113`, builder at `operations.ts:294-303`). The inspector does the same via numeric fields (`InspectorPanel.tsx:261-341`). **So a resize converts the dimension to `Fixed` and stores an explicit value.** It does *not* change a Hug→Fixed "mode" implicitly beyond writing a Fixed dimension, and it is *gated off* for auto-layout children. There is **no resize that "absorbs" by toggling fill/hug↔fixed automatically** — the inspector exposes the mode switch as a manual control (`InspectorPanel.tsx:313-369`: fixed / hug / fill weight), but resize gestures always write Fixed.

### 4d. How MOVE/drag works today
`canvasDragOperation` (`canvasOperations.ts:26-62`): converts the canvas point to a scene unit, sets `transform.x/y`, snaps to parent/safe-area guides, clamps to parent bounds, emits **`updateNodeTransform`** (one `UpdateNode` with `transform` set). This is **free relative positioning** and only fires for non-layout-managed nodes. For **reordering** within a layout (the layout-managed case), the operations are `MoveNode` / `move_before` / `move_after` / `move_to_parent` — i.e. change the child *index*, not a coordinate. So there are two distinct move semantics: **free move (transform write)** for frame/group/page children, and **reorder/reparent (MoveNode)** for everyone.

### 4e. Crop / fit / recolor
- **Crop** lives in `AssetPlacement{fit, focal_point, preserve_transparency, alt_text}` (`assets.rs:328-338`); `ImageFitMode = Contain|Cover|Crop` (`slots.rs:174-178`), `FocalPoint{x,y}` (`slots.rs:180-184`). It is set via `PlaceAssetInNode`/`asset_placement` patch (`operations.rs:599-651`). Validation: `Crop` requires a focal point (`assets.rs:851`) and a license that allows modification (`assets.rs:880`). **There is no rectangular pixel-crop op — "crop" is fit-mode + focal point, not a crop rectangle.** Shape "crop" (clip) is the node's `clip: bool` flag (`scene.rs:291`), edited via the `clip` patch — there is no path/mask geometry.
- **Recolor** = whole-stack `fills`/`strokes` replacement or per-entry `fill_edits`/`stroke_edits` (`editing.rs:580-582`), or token rebinding (`Paint::Token`, `Color::Token`).

---

## 5. Computed-geometry invalidation (how edits and the solver cooperate)
When a builder makes a render-affecting change it explicitly sets `patch.computed = Clear` so the stale solved geometry is dropped and the solver recomputes. `node_patch_affects_render` (`editing.rs:2089-2103`) defines "render-affecting" (kind/transform/size/fills/strokes/effects/corner/opacity/tokens/asset/clip/layout). The TS side mirrors this exactly in `nodePatch`/`nodePatchAffectsRender` (`operations.ts:65, 70-90`) — pinned by parity fixtures. The WASM engine re-runs `relayout()` after every apply to refresh `computed` for the optimistic render (`lumen-wasm/src/engine.rs:201, 244`). **Implication:** `computed` is never authored by a human/agent edit; it is always derived. Any freehand design must therefore decide whether "freehand position" lives in `transform` (re-solved every layout) or in some new persisted field the solver would have to respect.

---

## 6. Validation — what edits are forbidden and why
Two layers:

1. **Operation-local guards** (in `apply_operation_in_place`): duplicate ids, missing targets, leaf-can't-parent, move cycles, asset-in-use, index bounds, finalized-scene lock (cited in §1).
2. **Whole-scene validation** (`validation.rs:validate_scene`, run by `apply_operations_checked`): the batch is rejected if it yields any **error** diagnostic. Relevant geometry/structure rules:
   - `LUMV0801` "node exceeds parent bounds" — **error if the parent clips, warning otherwise** (`layout.rs:831-847, 869-879`). This is the rule a free drag/resize most often trips: dragging a child outside a clipped frame is rejected.
   - `LUMV0401/0402/0403` parentage/orphan/cycle integrity (`validation.rs:247-360`).
   - `LUMV0300-0302` node-children rules (leaf with children, etc.).
   - `LUMV0501` incomplete required slot — blocks finalize, not normal edits.
   - Paint-stack and stroke-dash rules `LUMV0700-0703`.

   `move_node` cross-parent into an auto-layout container is *allowed* by the op layer (only cycle + index checked) but the resulting overflow/anchor diagnostics can fail the checked apply.

**Locking:** `node.locked` (`scene.rs:294`) is enforced in `build_node_modify` (allows only setting `locked:false`, `editing.rs:918-924`), `build_safe_delete` (+descendants, `editing.rs:1147-1167`), `validate_node_can_move`/`build_ungroup`/`build_clone_subtree` (`editing.rs:1721, 1355, 1497`). The editor also disables direct geometry edits for locked nodes (`sceneQueries.ts:188`).

---

## 7. Undo / redo / invertibility at this layer
**Inverses are computed structurally, not by snapshot diff.** `Scene::invert_operations` (`operations.rs:920-940`) steps an internal draft through the batch, computing each op's inverse against the exact intermediate state, and returns the inverses in reverse order. `inverse_for_operation` (`operations.rs:942-1223`) handles every variant:
- `InsertNode` → `RemoveNode` (but **None / not invertible** if the insert adopted pre-existing children — there is no detach op, `operations.rs:1019-1030`).
- `RemoveNode`/`RemovePage` → full subtree restore via `restore_subtree_operations` + slot-binding restore (`operations.rs:1031-1056, 1226-1266`).
- `MoveNode` → `MoveNode` back to the recorded parent+index (`operations.rs:1057-1076`).
- `UpdateNode`/`UpdatePage`/`UpdateDocument` → patch carrying the *prior* values of exactly the changed fields (`operations.rs:1077-1137`).
- `FinalizeTemplate` → **None (not invertible)** (`operations.rs:1222`).

`EditBatch::with_inverses` (`editing.rs:182-194`) attaches the inverse batch at *build time against the pre-edit scene* — the comment is explicit that inverses are unobtainable later without replay (`editing.rs:179-181`). `EditBatch.inverse_operations` is `Option`; `None` = not undoable.

**Where the undo stack lives:** *Not* in lumen-core. The authoritative document-level undo/redo is server-side (`POST /undo`, `/redo`, `/revert`; `structuredEdits.ts:201-238`, `HistoryPanel.tsx`). The editor also keeps a local optimistic undo/redo stack of `{scene, operations}` frames (`EditorApp.tsx:186-187, 556-601`), bounded to 50, and a frame is flagged "not undoable" when `inverse_operations` is null (`HistoryPanel.tsx:99`). So undo is a real, first-class capability — but it is per-batch inverse replay, and any freehand edit type must be made invertible by `inverse_for_operation` or it becomes a hard undo barrier.

---

## 8. The DSL is create-only — central to the round-trip question
`compile_dsl_into_scene_with_session` (`dsl.rs:58-95`) compiles a DSL block into a list of `Operation`s and `apply_operations_checked` them **onto the existing `&mut Scene`** (additive — it does not reset the scene). It carries a `DslCompileSessionSnapshot` (seen node ids, parent stack, emitted slots) so successive blocks build on prior state (`dsl.rs:97-156, 191-206`).

But authoring an element emits **only `Operation::InsertNode`** (`dsl.rs:1422-1440`), and the parser **halts with `LUMD0401` "duplicate node id"** if the element's id is already in `seen_node_ids` (`dsl.rs:704-715`), which is seeded from `scene.nodes.keys()` (`dsl.rs:614`). The DSL `Position(x,y)` property sets `transform.x/y` (`dsl.rs:2344-2347, 3695-3698`) and `Size(w,h)` sets the `SizeSpec` — but **only at create time, inside the element being inserted.** There is no DSL directive to *update* an existing node's transform/size/fills; the only directives over existing nodes are `delete`, `clone`, `replace`, and slot/asset placement.

**Consequence for round-trip:** the agent does **not** "take back" a human-edited design by re-emitting DSL that overwrites nodes — that path would `LUMD0401`-halt on every existing id. The agent re-edits a human-modified scene by issuing **targeted `Operation`/`StructuredEditInstruction`s against the persisted scene JSON** (the runtime keeps the scene and calls `apply_structured_edit`/`apply_operations`, `apps/agent_runtime/lumen_deepagent/tools.py:309, 327-389`), and uses DSL only to *add* new subtrees. The scene JSON — not the DSL — is the durable, round-trippable representation.

---

## 9. Editing implications & round-trip (the crux)

**What exists today that helps:**
- A single, validated, invertible operation algebra (`Operation`) with atomic batch apply/rollback and structural inverses — a solid substrate for any new edit type.
- Free relative positioning *already works* for children of pages/frames/groups: `transform.x/y` is honored verbatim by the solver. A "freehand" element parented to a frame is, mechanically, just a node with `Dimension::Fixed` size and an authored `transform`.
- The editor already distinguishes layout-managed (auto-layout child) from directly-editable nodes (`isNodeLayoutManaged`) and routes gestures accordingly. Move = transform write; reorder/reparent = `MoveNode`. Resize = Fixed size + transform.
- The scene JSON is the durable representation and survives both human (`source:"editor"`) and agent (`source:"agent"`) edits through the same `build_structured_edit_batch` path — byte-parity by construction (`structuredEdits.ts:7-14`).

**What is missing for the user's two modes:**
1. **FREEHAND mode (toggle off layout management):** there is **no `set-absolute` / `detach-from-layout` operation and no per-node "absolute" flag.** The only way to make an auto-layout child free today is (a) reparent it out of the auto-layout container via `MoveNode` (changes parent/index — structural), or (b) abuse `is_out_of_flow_transform` by giving it rotation/skew (a side effect, warned as `LUMV0701`). Neither is a clean toggle. A real freehand mode needs **a new node field** (e.g. `position: Relative|Absolute`) that the solver's auto-layout branch (`layout.rs:256-296`) checks to skip a child from flow while honoring its `transform`, plus a new `Operation`/builder to set it, plus an inverse in `inverse_for_operation`, plus validation (overflow still applies). Alternatively, "freehand" could be defined as "reparent to a Frame/Group" — which needs *no engine change* but changes the tree and may break slot/agent assumptions.
2. **LAYOUT-MANAGED editing mode (edit while solver governs):** largely exists — inspector edits to `layout` (gap/padding/align/grow) and `size` mode (hug/fill/fixed) already flow through `UpdateNode`. The gap is purely UX: direct-manipulation handles that *write back into layout props* (e.g. dragging a child to reorder, dragging an edge to set gap) rather than writing `transform`.

**The round-trip ("can the agent take it back?"):**
- **Mechanically yes, with caveats.** Because all edits — human or agent — converge on the same `Scene` and the same `Operation` algebra, an agent can re-target any node a human moved/resized: `UpdateNode` to re-fix size, `MoveNode` to reparent, structured `modify` to recolor/retext. The agent reads scene JSON, not DSL, so a human-modified scene is fully visible to it.
- **The hard parts are representational, not mechanical:**
  - If freehand is implemented as *reparenting into a frame*, the agent's mental model ("this lives in the hero auto-layout column") is now wrong — the node's parent/index changed, so subsequent agent layout edits (gap/align on the old container) no longer affect it. The agent needs to *detect* that a node was pulled out of flow. There is **no provenance flag** today distinguishing "agent-authored, layout-managed" from "human-detached-freehand."
  - If freehand is implemented as a new `absolute` flag, the agent's DSL re-authoring path still can't touch it (DSL is create-only and would `LUMD0401`), so all agent repair of human-freehand nodes must go through operations/structured edits — which is already true today and works, but means the DSL is *not* the round-trip medium.
  - **Invertibility must be preserved:** any new freehand operation must have an inverse in `inverse_for_operation` or it silently breaks undo (the batch becomes `inverse_operations: null`).
  - **Realistic scope to make it usable:** (1) add a persisted out-of-flow/absolute concept the solver respects (small, localized change in `layout.rs` auto branch + `scene.rs` + one new patch field) **or** define freehand as managed reparenting (zero engine change); (2) add edit provenance so the agent can tell what a human freely positioned vs. what it still owns; (3) ensure every new mutation is invertible; (4) keep DSL as additive-create only — re-editing is operations, not re-authored DSL. The engine's existing operation/patch/inverse machinery is strong enough that the work is mostly *adding one well-modeled positioning concept and the provenance to reason about it*, not rebuilding the edit layer.

---

## 10. File:line index (quick reference)
- Operation enum: `operations.rs:131-205`
- apply / apply_checked / rollback: `operations.rs:214-269`
- per-op apply + guards: `operations.rs:271-909`
- finalize lock: `operations.rs:272-277, 749-802`
- invert: `operations.rs:920-1267`
- NodePatch: `operations.rs:102-126`
- NodeEditPatch / TextEditPatch / StackEntryEdit: `editing.rs:529-595, 550-567`
- build_node_modify: `editing.rs:905-1025`
- move builders / validate_node_can_move: `editing.rs:1451-1707, 1709-1763`
- clone / replace / ungroup: `editing.rs:1486-1655, 1323-1402`
- StructuredEditInstruction + dispatch: `editing.rs:2208-2320`
- EditBatch + with_inverses: `editing.rs:138-206`
- edit scope: `editing.rs:208-525`
- Node / Transform / SizeSpec / Dimension / ComputedGeometry: `scene.rs:269-295, 504-512, 529-550, 705-708`
- AutoLayoutProps: `scene.rs:471-497`
- solver relative-position honoring: `layout.rs:141-145, 179-192, 358-372`
- solver auto-layout (transform ignored) + out-of-flow escape: `layout.rs:256-296, 1508-1512`
- resolve_manual_size: `layout.rs:629-642`
- overflow validation LUMV0801: `layout.rs:831-847`
- AssetPlacement / ImageFitMode / FocalPoint: `assets.rs:328-338`, `slots.rs:174-184`
- editor layout-managed gate: `sceneQueries.ts:172-192`
- editor drag/resize → operations: `canvasOperations.ts:26-114`
- TS operation builders: `operations.ts:236-386`
- WASM apply + relayout: `lumen-wasm/src/engine.rs:183-266`
- DSL create-only / dup-id halt: `dsl.rs:54-95, 614, 704-715, 1422-1440`
- DSL Position/Size properties: `dsl.rs:2344-2347, 3695-3702`
- agent runtime edit path: `apps/agent_runtime/lumen_deepagent/tools.py:170-389`
