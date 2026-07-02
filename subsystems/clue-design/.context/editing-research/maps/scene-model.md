# Subsystem map: Scene & node model

Scope: `crates/lumen-core/src/{scene,instance,ids,snapshot,operations,layout,slots,assets,dsl,render_geometry}.rs`,
with cross-cuts into `apps/editor/src/engine/*` and `apps/api/.../database.py` + migrations.

This report separates **WHAT EXISTS TODAY** from **WHAT'S MISSING**. Speculation is labeled.

---

## 1. The Scene container

`Scene` is the root document model — `crates/lumen-core/src/scene.rs:12-22`:

```rust
pub struct Scene {
    pub schema_version: u32,
    pub meta: DocumentMeta,
    pub pages: BTreeMap<PageId, Page>,
    pub nodes: BTreeMap<NodeId, Node>,        // FLAT node store, keyed by id
    pub slots: BTreeMap<SlotId, Slot>,
    pub assets: BTreeMap<AssetId, AssetRecord>,
    pub export_profiles: Vec<ExportProfile>,
}
```

Key structural facts:
- **The node store is FLAT** (`nodes: BTreeMap<NodeId, Node>`). The tree is expressed by
  `Vec<NodeId>` child-lists (`Page.children` and `Node.children`), not by nesting. `scene.rs:188`, `scene.rs:275`.
- `SCHEMA_VERSION = 1` (`lib.rs:134`); stamped into every scene at construction (`scene.rs:27`).
- `meta.status` is `Draft` or `Finalized { template_revision_id }` (`scene.rs:176-181`). Finalized scenes
  reject all mutation except re-finalization (`operations.rs:271-277`).

### Pages
`Page` — `scene.rs:183-192`: `id`, `name`, `size: PageSize`, `children: Vec<NodeId>`, `bleed: Option<Rect>`,
`safe_area: Option<Rect>`, `background: Vec<Fill>`.
`PageSize` carries width/height/unit + preset/orientation + optional physical/raster output sizing
(`scene.rs:194-233`).

---

## 2. Node model — every node type and every property

### 2.1 The `Node` struct (shared by all kinds) — `scene.rs:268-295`

| Field | Type | Notes |
|---|---|---|
| `id` | `NodeId` | stable string id (see §4) |
| `name` | `Option<String>` | |
| `kind` | `NodeKind` | discriminator + per-kind payload (§2.2) |
| `transform` | `Transform` | **manual position/rotation/skew/flip** (§3) |
| `size` | `SizeSpec` | width + height as `Dimension` (fixed/hug/fill/token) (§2.3) |
| `children` | `Vec<NodeId>` | ordered child list (only meaningful for container kinds) |
| `fills` | `Vec<Fill>` | stacked paints, each with stable `PaintId` |
| `strokes` | `Vec<Stroke>` | stacked strokes w/ width, dash, cap, join, align |
| `effects` | `Vec<Effect>` | stacked effects (V0 = drop shadow only) |
| `corner` | `CornerRadii` | per-corner radius + optional token |
| `opacity` | `f64` | |
| `opacity_token` | `Option<String>` | token binding for opacity |
| `source_asset_id` | `Option<AssetId>` | provenance / font/vector source |
| `asset_placement` | `Option<AssetPlacement>` | **image fit/focal/crop intent** (§2.5) |
| `clip` | `bool` | clip children to bounds |
| `layout` | `Option<AutoLayoutProps>` | gap/padding/align/grow (§2.4) |
| `computed` | `Option<ComputedGeometry>` | **SOLVER OUTPUT** cached here (§3) |
| `locked` | `bool` | edit lock |

Defaults: `Node::new` gives `Transform::default()` (origin 0,0), `SizeSpec::fixed(0,0)`, opacity 1.0,
everything else empty/none (`scene.rs:297-319`).

### 2.2 `NodeKind` enum — `scene.rs:322-335`

```
Frame | Group | Rect | Ellipse | Line(LineNode) | Text(TextNode)
     | Image(ImageNode) | Vector(VectorNode) | AutoLayout(AutoLayoutNode)
     | Instance { source_node_id: NodeId }
```
- Containers (`can_have_children`): **only `Frame`, `Group`, `AutoLayout`** (`scene.rs:337-341`).
- `Line(LineNode)`: `{ x2, y2 }` endpoint (`scene.rs:441-445`).
- `Vector(VectorNode)`: `{ path_data: String }` (`scene.rs:437-439`).
- `Image(ImageNode)`: `{ asset_id: AssetId, alt: Option<String> }` (`scene.rs:430-434`).
- `AutoLayout(AutoLayoutNode)`: `{ direction: Row|Column, wrap: bool }` (`scene.rs:447-458`).
- `Instance { source_node_id }`: a reference kind — **but the real instance machinery is derivation, not this
  variant** (see §6). This variant is essentially unused scaffolding for a component model.

### 2.3 Text node properties — `TextNode` `scene.rs:343-392`
`content`, `font_family` (default "Inter"), `font_size`, `font_weight` (u16), `align`
(`Left|Center|Right|Justify`), `line_height` (default 1.2), `letter_spacing`, `max_lines: Option<u16>`,
`wrap` (`NoWrap|Wrap`), `direction` (`Ltr|Rtl|Auto`). Plus token overrides: `style_token`, `font_size_token`,
`line_height_token`, `letter_spacing_token`. Every typographic property a basic editor needs (family, size,
weight, alignment, line height, letter spacing) **exists as a first-class field**. Note: **text COLOR is not a
text field** — it comes from `node.fills` (the fill stack), same as any shape.

### 2.4 Sizing & layout props
- `SizeSpec { width: Dimension, height: Dimension }` (`scene.rs:528-532`).
- `Dimension` — `scene.rs:543-550`: `Fixed(f64) | Hug | Fill { weight } | Token { token }`. This is the
  fill/hug/fixed sizing model; `Token` defers to a brand token resolved before layout.
- `AutoLayoutProps` — `scene.rs:470-501`: `gap` (+`gap_token`), `padding: [f64;4]` (+`padding_token`),
  `grow`, `align_x: LayoutAnchor`, `align_y: LayoutAnchor`. `LayoutAnchor` =
  `Start|Center|End|SpaceBetween|Stretch` (`scene.rs:460-468`). **These live on the node, but only have effect
  when `kind == AutoLayout`** (the layout engine reads `node.layout` only for auto-layout nodes — `layout.rs:462`).

### 2.5 Paint / stroke / effect / color
- `Fill { id: PaintId, paint: Paint }` (`scene.rs:552-556`).
- `Paint` — `scene.rs:651-658`: `Solid{color} | LinearGradient{angle,stops} | RadialGradient{stops} | Token{token}`.
- `Color` — `scene.rs:666-672`: `Hex{value} | Token{token} | Oklch{l,c,h,alpha}`.
- `Stroke` — `scene.rs:558-589`: `paint`, `width` (+`width_token`), `dash`, `cap`, `join`, `align`.
- `Effect { id: EffectId, kind: EffectKind }`; V0 `EffectKind::DropShadow{color,opacity,x,y,blur,spread,color_token}`
  (`scene.rs:627-649`). Effects are individually addressable by `EffectId` (the edit contract).
- `CornerRadii` — `scene.rs:675-682`: four corners + optional token.

**Recolor, opacity, corner radius, stroke editing** are all directly representable. **Crop** is partial — see §3.4.

---

## 3. Position: SOLVED, not stored (with one manual-offset escape hatch)

This is the central question. The answer is nuanced.

### 3.1 There IS a manual position field: `Transform`
`Transform` — `scene.rs:503-512`: `{ x, y, rotation, skew_x, skew_y, flip_x, flip_y }`. `x`/`y` ARE a stored
manual offset. **But there is NO `absolute` flag and NO "position mode" field.** Whether `transform.x/y` is
honored depends entirely on the node's PARENT kind, decided at layout time, not stored on the node.

### 3.2 How the layout engine resolves position — `layout.rs`
- Page children: laid out at `origin = child.transform.{x,y}` (`layout.rs:141-146`). So **direct children of a
  page are "free-positioned": their stored `transform.x/y` IS their position.**
- Non-auto-layout containers (`Frame`/`Group`): children are recursively placed at
  `parent_origin + child.transform.{x,y}` (`layout.rs:179-192`, `layout.rs:359-372`). So **Frame/Group children
  are also free-positioned** — the frame does not reposition them; it only offsets by its own origin.
- AutoLayout containers: children are handed to the **Taffy flex solver**; their `transform.x/y` is IGNORED and
  the solver computes `layout.location` (`layout.rs:195-242`, `layout.rs:299-337`). So **only auto-layout children
  are "layout-managed"** in the sense that their position is fully solved and `transform.x/y` does nothing.
  - Exception: an auto-layout child with rotation/skew is treated as out-of-flow and KEEPS its transform
    (`layout.rs:264-282`, `is_out_of_flow_transform` `layout.rs:1508-1512`).

### 3.3 Where solved geometry lands: `computed`
The solver writes `ComputedGeometry { layout_bounds: Rect, render_bounds: Rect }` (`scene.rs:704-708`) and these
are **cached back onto each node's `computed` field** via `UpdateNode` operations
(`layout.rs:98-110`, `instance.rs:995-1006`). `layout_bounds` is the box; `render_bounds` accounts for
rotation/skew/flip (`render_bounds_for` `layout.rs:1514-1563`). Rendering reads `computed` first and falls back to
`transform.x/y + size` only when `computed` is absent (`render_geometry.rs:22-45`).

**So position is stored TWICE with different authority:**
1. `transform.x/y` — the authored manual offset (authoritative ONLY for free-positioned nodes).
2. `computed.layout_bounds` — the solver's resolved absolute geometry (authoritative for display; stale until
   relayout; cleared on edits that affect render — see `OptionalFieldPatch::Clear` usage throughout `editing.rs`).

The editor already encodes exactly this rule. `apps/editor/src/engine/sceneQueries.ts:172-192`:
`isNodeLayoutManaged` = "parent is an `auto_layout` node"; `isNodeDirectGeometryEditable` = not locked AND not
layout-managed. Drag/resize emit `transform`/`size` operations only for direct-geometry-editable nodes
(`canvasOperations.ts:41`, `:77`); handles are hidden otherwise (`selectionChrome.ts:79`).

### 3.4 Image crop — PARTIAL
There is **no per-node crop rectangle**. The only cropping-adjacent representation is `AssetPlacement`
(`assets.rs:328-338`): `{ fit: Option<ImageFitMode>, focal_point, preserve_transparency, alt_text }`, where
`ImageFitMode = Contain|Cover|Crop` (`slots.rs:172-178`) and `FocalPoint{x,y}` is normalized 0..1
(`slots.rs:180-184`). This expresses "fit/cover/crop-to-box with a focal point," NOT a freehand crop rect with
explicit inset/zoom. A true crop tool (drag crop handles, zoom, pan within frame) has **no field today**.
Shapes have no crop concept at all (crop ≈ `clip` + child positioning, but no dedicated model).

---

## 4. IDs & the parent-child tree

### 4.1 Stable string ids — `ids.rs`
All ids (`NodeId`, `PageId`, `SlotId`, `PaintId`, `EffectId`, `AssetId`, ...) are newtype wrappers over `String`,
serialized transparently (`ids.rs:42-89`). Validation allows `[A-Za-z0-9_-]`, non-empty (`ids.rs:26-40`).
`SlotKey` additionally allows `.` (`ids.rs:91-116`). **IDs are author/agent-assigned strings, not generated UUIDs**
— they are stable and human-meaningful (e.g. repeater clones get `{template}_item_{n}` — `instance.rs:560`).

### 4.2 Tree representation
- Parent → children: ordered `Vec<NodeId>` on `Page` and `Node`.
- Child → parent: **NOT stored.** `Scene::parent_of` does a linear scan over all pages then all nodes to find
  who lists this id as a child (`scene.rs:81-95`). Returns `ParentRef::Page(id) | ParentRef::Node(id)`
  (`scene.rs:141-146`). This means **reparenting is O(n) to discover and there is no back-pointer to keep in sync** —
  a plus for round-trip integrity (single source of truth = the child Vec).
- `descendants_of` walks children recursively with a `seen` set to guard cycles (`scene.rs:97-138`).

### 4.3 Reparenting — fully represented as a canonical operation
`Operation::MoveNode { node_id, new_parent: ParentRef, index }` (`operations.rs:153-157`). `move_node`
(`operations.rs:505-554`): rejects cycles (`is_descendant_of`), detaches from old parent (linear scan removes id
from every child Vec — `detach_node_from_parents` `operations.rs:864-871`), reinserts at index in the new parent.
**Reparenting across the page→frame→auto-layout boundary is a first-class, reversible operation.** The inverse of
`MoveNode` is computed as a `MoveNode` back to the recorded old parent+index (`operations.rs:1057-1076`).

Note: `transform.x/y` is **NOT adjusted** on move. So moving a free node into an auto-layout container silently
strips its visual position (now solver-owned); moving it back out resurrects the old `transform.x/y` unless an edit
cleared it. This is the round-trip hazard (see §8).

---

## 5. Serialization & persistence — the Scene IS the canonical artifact

### 5.1 In-core (snapshot.rs)
`Scene::to_canonical_json` = `serde_json::to_string_pretty` (`snapshot.rs:31-34`); `Scene::from_json` = parse
(`snapshot.rs:36-39`). Plain serde, no custom format. The whole node model derives `Serialize/Deserialize`.
Many fields use `#[serde(default, skip_serializing_if = ...)]` so older JSON round-trips byte-identically as new
fields (effects, stroke caps, tokens) are added — see comments at `scene.rs:278-282`, `scene.rs:591-596`.

### 5.2 Persistence (apps/api) — Scene is the source of truth, DSL is NOT stored
`documents.current_scene_json TEXT NOT NULL` is the live document
(`apps/api/migrations/001_init.sql:3-16`, read at `database.py:1147`). Versioned `snapshots.scene_json`
(`001_init.sql:31-39`), finalized `template_revisions.scene_json` (`:41-53`). History is an **append-only
operation/envelope log**, not stored DSL: `operation_log` (`:18-29`) and `edit_envelopes` carrying
`operations_json` + `inverse_operations_json` + `lineage_json` + intent/checkpoint
(`migrations/003_edit_envelopes.sql:7-28`). **There is no `dsl_source` column anywhere.**

### 5.3 DSL is a transient authoring input, lowered into operations onto the persisted Scene — `dsl.rs`
`compile_dsl_into_scene_with_session` parses DSL → emits `Vec<Operation>` → `scene.apply_operations_checked(...)`
(`dsl.rs:58-95`). The scene is carried in a `DslCompileSession` and mutated incrementally; the session snapshot
(seen ids, parent stack, emitted slots) persists *parser* context, not a re-derivable source
(`dsl.rs:97-243`). The DSL `p(x,y)` property writes `transform.x/y` (`dsl.rs:2344-2347`, `:3695-3697`).
**Implication: the Scene is NOT re-derived from DSL each time. The Scene is durable; the DSL is one of several
ways (alongside structured edit batches and undo/redo) to produce operations against it.** This is the single most
important fact for the round-trip question — a human's freehand edits and an agent's DSL/edits mutate the *same*
persisted Scene through the *same* operation pipeline.

---

## 6. Components / instances (instance.rs) — "managed vs detached"

**An instance is a DERIVED ARTIFACT, not a live linked copy.** `instance.rs:1-11`: an instance is a pure function
of `(revision snapshot, binding set, asset records)`. `derive_instance` (`instance.rs:213-287`) clones a finalized
template snapshot, flips status to Draft, applies binding values via canonical operations (text → `UpdateNode`,
asset → `PlaceAssetInSlot`, list → repeater clone), runs layout twice, then restores Finalized status.

- **Overrides do not exist as a stored diff.** There is no `overrides` map on a node. "Editing an instance" is not
  supported in V0 — `instance.rs:5-8`: "instances are never manually edited in V0 — repairs happen on the template
  (a new draft revision) or on binding values, both of which re-derive." So the only "detach"-like concept is:
  re-derive from a different template revision or different bindings.
- The `NodeKind::Instance { source_node_id }` variant (`scene.rs:334`) is scaffolding for a future component model;
  derivation does **not** use it. There is no instance↔master override-propagation system today.
- Repeater expansion clones template subtrees with deterministic ids and records `CloneLineage`
  (`instance.rs:557-656`, lineage type at `editing.rs:132-136`) — the closest thing to "this came from that master,"
  but it is one-shot clone provenance, not a live link.

**Relevance to freehand editing:** the component/instance system gives almost no leverage for the human-editing
problem. There is no "managed vs detached node" toggle at the node level; the only managed/free distinction that
actually governs editing is auto-layout parentage (§3).

---

## 7. Snapshots & history

- `snapshot.rs` is *just* JSON (de)serialization (`to_canonical_json`/`from_json`) — despite the name, **it is not an
  undo stack.** Undo/redo lives in the operation/envelope log.
- Real history: `EditBatch` (`editing.rs:138-206`) bundles `operations` + `inverse_operations` (computed at build
  time against the pre-edit scene via `Scene::invert_operations` — `operations.rs:920-940`) + touched targets +
  intent + optional `CloneLineage`. The API persists these as `edit_envelopes` (§5.2). `undo()`/`redo()` in DSL lower
  to applying inverse/original ops through a `DslHistoryAdapter` (`dsl.rs:35-47`, `:1672-1702`).
- **Invertibility caveats** (`operations.rs:1019-1030`, `:1222`): `FinalizeTemplate` and an `InsertNode` that adopts
  pre-existing children are NOT invertible (return `Ok(None)`). Everything else, including `MoveNode`, `UpdateNode`,
  `RemoveNode` (restores full subtree + slot bindings), is invertible.

---

## 8. Editing implications & round-trip

### What EXISTS today and helps
1. **The two-mode dichotomy the user wants is already half-built in semantics.** "Free-positioned" (drag/resize via
   `transform.x/y`) vs "layout-managed" (solver-owned) is decided by parent kind:
   page/Frame/Group child = free; auto-layout child = managed (`sceneQueries.ts:172-192`, `layout.rs`). The editor
   already gates handles and drag/resize on this (`canvasOperations.ts:41`, `:77`; `selectionChrome.ts:79`).
   → **FREEHAND mode** ≈ "ensure the node's parent is NOT an auto-layout" (a Frame/Group/page), then drag writes
   `transform.x/y`. **LAYOUT-MANAGED editing** ≈ editing under an auto-layout parent, where the inspector edits
   sizing mode / align / gap instead of raw x/y (the inspector text at `InspectorPanel.tsx:372` already says this).
2. **All edits are canonical, validated, reversible operations** through one pipeline
   (`apply_operations_checked` → `validate_scene` → reject on error, `operations.rs:240-269`). A human freehand drag
   and an agent repair are the same kind of mutation. There is no "human format" the agent can't read.
3. **The Scene is the single persisted source of truth** (§5). A human modifying it in freehand mode does not
   diverge into a separate representation — both human and agent operate on `current_scene_json`. The agent can
   "take it back" because there is nothing to reconcile: it just reads the current Scene and emits more operations.
4. **Reparenting is first-class and reversible** (`MoveNode` + inverse, §4.3). Switching a node between an
   auto-layout parent and a free parent is a representable, undoable operation.
5. **`transform` already carries rotation/skew/flip**, and the solver honors transformed children as out-of-flow even
   inside auto-layout (`layout.rs:264-282`) — so a freehand-rotated node has a defined behavior.

### What is MISSING / the hard edges for round-trip
1. **No explicit "position mode" / "absolute" flag on a node.** Free-vs-managed is *implicit* in parent kind. If
   FREEHAND mode means "let me drag this auto-layout child to an arbitrary spot WITHOUT removing it from the
   container," there is no field for that — you must either reparent it out (losing its place in the stack) or the
   solver will overwrite its position. A Figma-style "absolute position within auto-layout" boolean does not exist.
   (Speculation: the cleanest add is a per-node `position: Auto | Absolute` flag honored in `layout.rs` like the
   existing out-of-flow-transform path.)
2. **`transform.x/y` is not reconciled on reparent.** Moving a node into auto-layout does not zero its
   `transform.x/y`; moving it out does not recompute a sensible position from `computed.layout_bounds`. So a
   freehand→managed→freehand round-trip can resurrect stale coordinates. The agent has no recorded "what was the
   layout intent here" once a human has dropped a node somewhere absolute.
3. **`computed` is a cache that goes stale and must be cleared/recomputed.** Edits manually `Clear` `computed`
   (`editing.rs:1002-1006`, `instance.rs` relayout). A freehand editor that writes `transform` but forgets to clear
   `computed`, or an agent that reads stale `computed`, will mismatch. Render falls back to `transform` only when
   `computed` is `None` (`render_geometry.rs:22-45`) — so the invariant "clear computed on geometry edit" is
   load-bearing and currently enforced only by convention in builders.
4. **No crop model for a true crop tool** (§3.4). `AssetPlacement` gives fit/cover/focal-point but not an explicit
   crop rect/zoom/pan. Cropping shapes is not modeled at all.
5. **The agent's repair surface is intent/slot-oriented, and freehand edits have no slot/intent.** The structured
   edit + scope system (`editing.rs:276-525`) is built around *declared targets and slots*; instance derivation and
   repairs target the *template and bindings* (`instance.rs`). A human's raw freehand drag has no slot binding, no
   intent label, and no template provenance. The agent can still read and re-edit the resulting Scene (everything is
   just nodes + transforms), but it loses the semantic scaffolding (slots, repeaters, worst-case fixtures) that
   drives its quality checks. Round-trip is *structurally* fine but *semantically* lossy: after enough freehand
   edits, the design is "just nodes," and the agent's layout-aware repair loop has less to grip.
6. **Editing finalized templates is blocked** (`operations.rs:271-277`); a freehand session on a finalized doc must
   fork a new draft revision first.
7. **`NodeKind::Instance` and a real override/detach model do not exist** (§6). If the editing UX implies
   "components," that subsystem is unbuilt.

### Bottom line for architects
- Representation for round-trip already mostly works: one flat node store, stable string ids, a manual `transform`,
  a solver-output cache (`computed`), and a canonical/invertible operation log that both human and agent share. The
  Scene — not the DSL — is the durable artifact, so there is no human↔agent format gap.
- The realistic scope to make freehand usable AND agent-resumable:
  (a) add an explicit per-node position/layout mode so "free inside a container" is representable rather than implied
  by reparenting; (b) define reconciliation rules for `transform.x/y` ↔ `computed` on reparent and on mode flip so
  coordinates don't go stale; (c) guarantee the "clear `computed` on geometry edit → relayout" invariant in the
  operation layer rather than by builder convention; (d) decide whether the agent operates at the node level
  (works today, semantically lossy) or whether freehand edits should be captured as intent/slot-aware operations so
  the agent's layout-quality machinery still applies; (e) build a real crop model if crop is in scope.
