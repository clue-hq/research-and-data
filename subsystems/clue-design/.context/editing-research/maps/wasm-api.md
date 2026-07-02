# Subsystem map: WASM engine API boundary

Scope: the contract between the React/CanvasKit editor JS and the Rust engine
compiled to WASM. Entry points: `crates/lumen-wasm/src/lib.rs` (wasm-bindgen
bindings) and `crates/lumen-wasm/src/engine.rs` (the testable engine logic).
JS-side consumer: `apps/editor/src/engine/wasmEngine.ts`.

The golden rule of this crate (stated in its own header) is decisive for the
editing study: **"this crate has zero semantics of its own"**
(`crates/lumen-wasm/src/lib.rs:4-8`). Every request routes to a lumen-core entry
point; the WASM layer only does (de)serialization, a relayout to refresh the
render cache, and a mechanical before/after scene diff. Any new editing
capability therefore has to be added in lumen-core first, then surfaced here.

---

## 1. The FULL exported API surface

There are exactly **3 free functions** and **9 instance methods** on
`LumenEngine`. That is the entire boundary.

### Free functions (`crates/lumen-wasm/src/lib.rs`)

| JS name | Rust fn | Signature (JS) | Returns |
|---|---|---|---|
| `engineVersion()` | `engine_version` (`lib.rs:23-26`) | `() => string` | JSON `{ schema_version, engine_commit, text_measurement }` |
| `slotIdForKey(key)` | `slot_id_for_key` (`lib.rs:31-34`) | `(key: string) => string` | the deterministic slot id |
| `new LumenEngine(sceneJson)` | constructor (`lib.rs:44-49`) | `(sceneJson: string) => LumenEngine \| throws JsError` | engine instance |

### Instance methods (`crates/lumen-wasm/src/lib.rs:41-121`)

All take/return **JSON strings** (wasm-bindgen `&str`/`String`); the TS wrapper
does the `JSON.stringify` / `JSON.parse`.

| JS name | Rust fn | Signature (JS) | Mutates scene? | Returns (JSON) |
|---|---|---|---|---|
| `loadScene(sceneJson)` | `load_scene` (`lib.rs:52-57`, `engine.rs:110-117`) | `(string) => void \| throws` | replaces whole scene | — (relayout side-effect) |
| `sceneJson()` | `scene_json` (`lib.rs:60-63`, `engine.rs:175-177`) | `() => string` | no | the full **local** scene (with `computed`) |
| `applyOperations(opsJson)` | `apply_operations` (`lib.rs:67-70`, `engine.rs:183-213`) | `(string) => string` | yes, atomic | `{ ok, applied_operations, diagnostics, inverse_operations, delta }` |
| `applyStructuredEdit(editJson)` | `apply_structured_edit` (`lib.rs:74-77`, `engine.rs:220-268`) | `(string) => string` | yes, atomic | `{ ok, applied_operations, diagnostics, operations, edit{...}, delta }` |
| `compileDslBlock(source)` | `compile_dsl_block` (`lib.rs:81-84`, `engine.rs:272-315`) | `(string) => string` | yes | `{ ok, compile_output{...}, operation_report, operation_error, delta }` |
| `layoutGeometry()` | `layout_geometry` (`lib.rs:87-90`, `engine.rs:320-328`) | `() => string` | no (read-only) | `{ geometry: {nodeId: ComputedGeometry}, diagnostics, text_measurement }` |
| `preflight()` | `preflight` (`lib.rs:93-95`, `engine.rs:333-341`) | `() => string` | no | `{ has_errors, diagnostics, text_measurement }` |
| `validate()` | `validate` (`lib.rs:98-100`, `engine.rs:344-346`) | `() => string` | no | `{ diagnostics }` |
| `hitTest(pageId, x, y)` | `hit_test` (`lib.rs:104-107`, `engine.rs:352-360`) | `(string, number, number) => string` | no | `{ hit: nodeId\|null, stack: nodeId[] }` |
| `setMeasurements(measJson)` | `set_measurements` (`lib.rs:112-115`, `engine.rs:149-171`) | `(string) => string` | refreshes `computed` | `{ ok, count }` or `{ ok:false, error }` |
| `version()` | `version` (`lib.rs:118-120`) | `() => string` | no | same handshake payload as `engineVersion()` |

The TS interface mirror that pins this surface is
`WasmEngineInstance` at `apps/editor/src/engine/wasmEngine.ts:36-49` and the
module surface `WasmModule` at `:79-83`.

### What is NOT here (verified by exhaustive grep of `lib.rs`)

- **No `export` / render-to-PDF/PNG** entry point. `render_contract` /
  `export_contract` exist in lumen-core but are never exposed via WASM; export
  is a server responsibility (the engine header calls server geometry
  "authoritative for text-dependent layout", `engine.rs:24-26`).
- **No DSL emit / scene→DSL.** The DSL is one-way input only: `compile_dsl*`
  and `normalize_dsl` exist (`crates/lumen-core/src/dsl.rs:23,58`) but there is
  **no function anywhere in lumen-core that serializes a Scene back to DSL**
  (grep for `to_dsl`/`emit`/`scene_to_dsl` finds only the compile-session's
  `emitted_slots` bookkeeping). This is a hard round-trip fact (see §6).
- **No undo/redo entry point.** Undo is split: the engine *returns* inverse
  operations (`inverse_operations` in every apply result) so the host can
  re-apply them, but the durable history lives **server-side** — the editor
  calls HTTP `fetchHistory` / `undoDocument` / `redoDocument`
  (`apps/editor/src/engine/structuredEdits.ts:186,216,220`), not the WASM
  module.
- **No "switch mode" / "make absolute" / "toggle layout management" call.** No
  such concept exists anywhere in the boundary or the core (see §4, §5).

---

## 2. Data contract: what JSON crosses the boundary

### The scene that crosses is the AUTHORED scene WITH a derived `computed` cache

The serialized type is `lumen_core::Scene` (`crates/lumen-core/src/scene.rs:12-22`):
`{ schema_version, meta, pages, nodes, slots, assets, export_profiles }`.

Each `Node` (`scene.rs:268-295`) carries BOTH the **authored** geometry inputs
and a **derived** resolved-geometry cache:

- Authored inputs: `transform { x, y, rotation, skew_x, skew_y, flip_x, flip_y }`
  (`scene.rs:504-512`), `size: SizeSpec { width: Dimension, height: Dimension }`
  (`scene.rs:528-550`) where `Dimension = Fixed(f64) | Hug | Fill{weight} |
  Token{token}`, `layout: Option<AutoLayoutProps>`, `kind`, `fills`, `strokes`,
  `effects`, `corner`, `opacity`, `clip`, `locked`, etc.
- Derived cache: `computed: Option<ComputedGeometry>` =
  `{ layout_bounds: Rect, render_bounds: Rect }` (`scene.rs:704-708`), each Rect
  `{ x, y, width, height }` in **absolute page space**.

So the answer to "is the scene returned to JS the resolved-geometry scene or the
authored scene?" is: **it is the authored scene, plus a `computed` field on each
node that holds the resolved rects.** They travel together. `computed` is a
render cache, not authoritative input — see §3.

### `computed` is recomputed locally on every mutation, with a deliberately weak measurer

`Engine::relayout()` (`engine.rs:129-140`) runs `layout_scene` over the whole
tree and writes the result into each node's `computed`. It is called after
init, `load_scene`, `apply_operations`, `apply_structured_edit`,
`compile_dsl_block`, and `set_measurements`. Crucially the header documents that
this **writes geometry directly onto nodes and does NOT emit operations**, so
the recomputed `computed` never enters the authored edits sent to the server
(`engine.rs:119-128`). The browser uses the lumen-core **heuristic** text
measurer (skia-safe can't target wasm32), so `text_measurement: "heuristic"` is
advertised and server geometry remains authoritative for text-dependent layout
(`engine.rs:23-26`, `lib.rs:10-14`). `setMeasurements` lets the editor inject
SkParagraph metrics to make text `computed` Skia-faithful (`engine.rs:142-171`).

### The per-edit channel is a DELTA, not a full scene

`apply*` results carry `delta` = a mechanical before/after diff of the scene's
entity maps (`scene_delta`, `engine.rs:379-395`). It is a pure map comparison
with no operation-semantics knowledge: changed entries serialize as the new
value, removed entries as `null`. The TS side merges it immutably with
structural sharing (`applySceneDelta`, `wasmEngine.ts:153-189`). Full scene
snapshots cross only on init/reconcile/undo-frame (`lib.rs:5-8`,
`wasmEngine.ts:23-27`).

### Edit inputs

- **Operations**: a JSON array of `Operation` (`crates/lumen-core/src/operations.rs:128-205`).
  Relevant variants for editing: `InsertNode{parent,index,node}`,
  `RemoveNode{node_id}`, `MoveNode{node_id,new_parent,index}`,
  `UpdateNode{node_id, patch: NodePatch}`, plus page/slot/asset/export ops.
  `NodePatch` (`operations.rs:102-126`) is a sparse patch over every node field
  including `transform`, `size`, `fills`, `strokes`, `effects`, `corner`,
  `opacity`, `opacity_token`, `source_asset_id`, `asset_placement`, `clip`,
  `layout`, `locked`, and even `computed`. Each field is a `FieldPatch<T>` =
  `Unchanged | Set(T)` or `OptionalFieldPatch<T>` = `Unchanged | Set(T) | Clear`
  (`operations.rs:56-83`).
- **Structured edits**: `StructuredEditInstruction`
  (`crates/lumen-core/src/editing.rs:2208-2246`): `Modify{target,patch}`,
  `Delete{target}`, `MoveBefore{node_id,anchor}`, `MoveAfter{node_id,anchor}`,
  `MoveToParent{node_id,parent,index}`, `CloneSubtree`, `ReplaceNode`,
  `ArchiveAsset`, `HardDeleteAsset`, `DeleteExportProfile`. `build_structured_edit_batch`
  (`editing.rs:2269-2320`) lowers each to a checked `EditBatch` of canonical
  operations with inverses — the same path the API uses, so optimistic results
  match the server by construction (`engine.rs:215-219`).

`NodeEditPatch` (the modify payload, `editing.rs:571-595`) is what the inspector
edits flow through: `name`, `transform`, `size`, `fills`/`fill_edits`,
`strokes`/`stroke_edits`, `effects`/`effect_edits`, `corner`, `opacity`,
`opacity_token`, `clip`, `layout`, `source_asset_id`, `asset_placement`,
`locked`, `text`, `image_asset_id`. This is the full vocabulary the human-edit
inspector can already drive: font (`text`), size, color (`fills`), opacity,
crop (`asset_placement` / `image_asset_id`), recolor, etc.

### Atomicity & failure contract

`apply_operations_checked` (`operations.rs:240-269`) applies to a **clone (draft)**,
validates the whole result with `validate_scene`, and only commits if there are
no error diagnostics — otherwise the scene is untouched and an
`op.validation_failed` error with diagnostics is returned. The WASM layer maps
parse/apply failures to `{ ok:false, error:{code,message}, diagnostics }`
(`engine.rs:363-374`) and the TS wrapper returns `accepted:false` keeping the
old snapshot (`wasmEngine.ts:257-267,288-300`).

---

## 3. Authored geometry vs solved geometry: the two positioning models

This is the heart of the user's problem and it lives in `layout.rs`, surfaced
through `computed`.

There are **two positioning regimes**, decided by the node's PARENT kind:

1. **Manual / transform-driven** (Frame, Group, Rect, page children, and ANY
   node whose parent is not an auto-layout): the child's absolute origin is the
   parent origin plus `child.transform.x/y`, accumulated down the tree
   (`layout.rs:141-145` for page children, `:185-191` for Frame/Group children,
   `:351-356`/`:358-372` for the non-auto branches). Here `transform.x/y` IS the
   authored position and direct drag/resize works naturally.

2. **Auto-layout / solved** (any node whose parent is an `AutoLayout`): position
   comes from the Taffy flex solver via `layout.location` (`layout.rs:322-330`);
   the child's own `transform.x/y` is **ignored** for in-flow children. The
   exception is out-of-flow children (rotated/skewed), which Taffy excludes and
   which fall back to transform offsets (`layout.rs:264-` warns LUMV0701,
   `:335-357`). `AutoLayoutProps` (`scene.rs:471-497`) holds `gap`, `padding[4]`,
   `grow`, `align_x`, `align_y`; the container is an `AutoLayoutNode {direction:
   Row|Column, wrap}` (`scene.rs:447-458`).

So "positions are SOLVED not stored" is true **only for children of
auto-layout nodes**. For everything else, `transform.x/y` already is a stored,
freely-editable absolute-within-parent coordinate. There is no global "layout
managed" flag on a node — it is purely a function of `parent.kind ==
auto_layout`.

The editor already encodes exactly this rule on the JS side:
`isNodeLayoutManaged` returns true iff the parent node's kind is `auto_layout`
(`apps/editor/src/engine/sceneQueries.ts:172-181`), and
`isNodeDirectGeometryEditable` (`:183-192`) gates drag/resize to nodes that are
unlocked AND not layout-managed. The gesture-to-operation builders
short-circuit to `null` when that gate fails
(`apps/editor/src/engine/canvasOperations.ts:41-43, 77-79`).

---

## 4. Is there an API to apply absolute moves/resizes? To get resolved rects?

### Moves / resizes — YES, via `UpdateNode`/`NodePatch`, but no dedicated verb

There is no `setAbsolutePosition` or `resize` verb. The editor already performs
freehand-style drag/resize by emitting **`UpdateNode` operations that Set the
`transform` and `size` fields**:

- Drag → `canvasDragOperation` builds an `UpdateNode` patch with a new
  `transform { x, y }` in scene units (`canvasOperations.ts:26-62`, via
  `updateNodeTransform`).
- Resize → `canvasResizeOperation` builds an `UpdateNode` patch setting
  `transform` and `size: { width: Fixed(w), height: Fixed(h) }`
  (`canvasOperations.ts:64-114`, via `updateNodeTransformAndSize`).

Both run through `applyOperations` → `apply_operations_checked`. So the engine
ALREADY supports applying absolute moves/resizes to any non-auto-layout node.
What it does NOT do: apply a meaningful absolute move to a node whose parent is
auto-layout (the solver overwrites `transform.x/y` on the next `relayout`). The
JS gate exists precisely because of this.

### Reparenting — YES: `MoveNode` / `MoveToParent`

`Operation::MoveNode{node_id,new_parent,index}` (`operations.rs:153-157`) and
the structured `MoveToParent` (`editing.rs:1467-1484`) move a node between
parents. **Caveat (round-trip critical, §6): `MoveNode` does NOT recompute or
adjust `transform.x/y`.** It only re-links parent/child arrays. Moving a node
from page space into an auto-layout parent leaves its old absolute transform in
place (now ignored by the solver); moving it OUT of an auto-layout parent into a
manual parent leaves whatever stale `transform.x/y` it last had (often `0,0` or
an authored offset), so it will not land where the human last saw it on screen.

### Getting resolved rects for a node — YES, two ways

1. Read `node.computed.{layout_bounds,render_bounds}` from the scene/delta the
   engine returns (always populated after `relayout`). This is the normal path.
2. Call `layoutGeometry()` (`engine.rs:320-328`) for a fresh read-only
   `{ geometry: { nodeId: ComputedGeometry } }` map without mutating.

`hitTest(pageId,x,y)` (`engine.rs:352-360`) gives point→node in absolute page
space (topmost `hit` + bottom-to-top `stack`) — the inverse direction.

### Switch modes — NO

There is no engine concept of "freehand mode" vs "layout-managed mode" and no
API to toggle it. The only thing resembling a per-node mode is the implicit
`parent.kind == auto_layout` rule and the `locked: bool` field
(`scene.rs:294`), which `isNodeDirectGeometryEditable` also honors.

---

## 5. What EXISTS today vs what's MISSING for freehand / layout-managed editing

### Exists today

- Apply absolute move/resize to non-auto-layout nodes via `UpdateNode`
  (`transform`+`size` patches). Already wired through CanvasKit gestures.
- Full inspector-style property editing via `NodeEditPatch` (font/size/color/
  opacity/corner/clip/effects/strokes/asset placement/lock).
- Reparenting via `MoveNode` / `MoveToParent` (structure only).
- Convert a dimension to fixed: resize already sets `Dimension::Fixed`, so
  "freeze the solved size" is expressible.
- Resolved rects per node (`computed`) and on-demand `layoutGeometry()`.
- Hit-testing, atomic checked apply, inverse operations for undo, version
  handshake, structural-sharing deltas.
- A clean architectural seam: WASM has zero semantics, so new verbs are added
  in lumen-core and thinly forwarded.

### Missing (would need building)

- **No mode toggle.** A "freehand" mode that detaches a subtree from
  layout management has no representation. Two plausible designs, both NEW:
  (a) introduce explicit absolute positioning by giving auto-layout an
  out-of-flow / position:absolute child flag (today only rotation/skew forces
  out-of-flow, `layout.rs:264`, `is_out_of_flow_transform` at `:1509-1512`); or
  (b) reparent the node out of the auto-layout container into a Frame and
  bake its solved rect into `transform`+`size`.
- **No "bake computed → authored" operation.** Going freehand needs to convert
  a node's solved `computed.layout_bounds` into authored `transform.x/y` +
  `size: Fixed`. The engine can read `computed`, and `UpdateNode` can set
  transform/size, so the editor *could* assemble this op-by-op, but there is no
  single safe core verb that does it for a node or subtree (and `MoveNode`
  notably does not, §4/§6).
- **No scene→DSL emit.** If the agent's source of truth is DSL, there is no way
  to project a human-edited scene back into DSL (§6).
- **No partial / region relayout API.** `relayout` is whole-tree only
  (`engine.rs:129-140`); a layout-managed editing mode that wants to preview a
  single subtree re-solve has no narrower entry point.
- **No constraint/pin model** (e.g. "absolute but anchored to parent edge").
  Transform is a flat offset; there is no anchoring vocabulary beyond
  auto-layout `align_x/align_y`.

---

## 6. Editing implications & round-trip

### What the editor CAN ask the engine to do today

Everything a "basic editor" needs at the property level already exists as
operations: move/resize (non-auto-layout nodes), edit font family/size/weight
(`text` patch), color (`fills`/`fill_edits`), opacity, corner radius, clip,
crop/recolor images (`asset_placement`, `image_asset_id`, fills), lock, delete,
reparent, clone. The data is applied atomically and validated, and the engine
returns inverse operations so the host can build undo. The render snapshot stays
coherent because `relayout` always recomputes the whole tree's `computed` from
one pass (the documented fix for drag/edit coordinate desync,
`engine.rs:119-128`).

### Why freehand "fought the solver" (and what the boundary tells us)

The friction is not in the WASM API — it is structural. For children of
auto-layout containers the solver overwrites `transform.x/y` on every
`relayout`, so a `transform` patch is discarded visually. The current product
sidesteps this by simply forbidding direct drag/resize on layout-managed nodes
(`isNodeDirectGeometryEditable`, `sceneQueries.ts:183-192`). A real freehand
mode must change the **representation** so the solver yields control, not just
add an API:

- Option A (out-of-flow flag): add a per-node "absolute" marker that makes the
  layout engine treat the child like the existing rotation/skew out-of-flow
  case — position from `transform`, excluded from flex flow. This is the most
  surgical: it reuses the `is_out_of_flow_transform` branch
  (`layout.rs:264, 1509-1516`) and keeps the node in its parent for the agent.
- Option B (reparent + bake): on entering freehand, `MoveNode` the node to a
  plain Frame and `UpdateNode` its `transform`/`size` from `computed`. Simpler
  to express with today's ops, but it mutates structure the agent authored.

### The round-trip ("can the agent take it back?") — the crux

Three concrete obstacles, in increasing severity:

1. **`MoveNode` does not adjust transform** (`editing.rs:1467-1484`,
   `operations.rs:153-157`). Any reparent — the natural freehand gesture — loses
   the on-screen position because the new parent interprets `transform.x/y`
   differently (or ignores it). A round-trippable move needs a "move and
   preserve absolute position" variant that recomputes `transform` from the
   before/after `computed` of the old and new parents. **Missing.**

2. **No scene→DSL emit anywhere in lumen-core.** The agent authors in DSL and
   the compile path is strictly one-way (`dsl.rs`: `compile_dsl*`,
   `normalize_dsl`, but no inverse). If the agent's working representation is
   DSL, a human's freehand edits (new absolute coords, reparents,
   relative→absolute switches) cannot be reflected back into the DSL the agent
   reasons over. The agent would have to either (a) operate directly on the
   Scene (operations) rather than DSL going forward, or (b) gain a new
   scene→DSL projection. **Missing, and it is the deepest gap.** Note the WASM
   `compileDslBlock` holds a `DslCompileSessionSnapshot` (`engine.rs:80-81,
   272-275`) that indexes prior DSL state; after a human reparents/edits nodes
   outside DSL, that session no longer maps cleanly to the mutated scene
   (`load_scene` resets it precisely because it "indexed the previous scene
   state", `engine.rs:105-117`).

3. **The agent's authoritative geometry is server-Skia, the editor's is
   heuristic.** `computed` written in-browser is deliberately non-authoritative
   (`engine.rs:23-26`). Any baked freehand coordinates derived from the editor's
   heuristic `computed` will differ slightly from what the server/agent
   recompute, so a round-trip that bakes geometry must either use
   `setMeasurements`-corrected metrics or re-bake server-side.

### Realistic scope to make it usable (labeled inference, not present in code)

- The Scene representation is already adequate to *store* freehand state:
  `transform` + `size: Fixed` + `locked` exist; the only representational gap is
  an explicit "absolute / out-of-flow" marker so the solver leaves a
  layout-managed node alone (Option A). That is a small, additive lumen-core
  change plus one WASM-forwarded modify field.
- The round-trip is the expensive part. Making the **agent** able to resume a
  human-modified design most cheaply means making the agent operate on the
  **Scene/operation contract** (which already fully captures absolute positions,
  reparents, and every property) rather than on DSL — eliminating obstacle #2.
  If DSL must remain the agent's medium, a scene→DSL emitter is a substantial
  new subsystem.
- A "move and keep absolute position" core verb (obstacle #1) is bounded and
  high-value: it removes the single most common way a freehand gesture corrupts
  position.

All §6 design options labeled "Option A/B" and the scope paragraph are
inference about what to build; everything in §1–§5 is grounded in the cited
code as it exists today.
