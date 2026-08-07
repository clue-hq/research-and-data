# Subsystem map: DSL parse + serialize (round-trip)

Scope: Does the engine serialize Scene → DSL? Is DSL or Scene canonical? Can a
human-edited scene be "taken back" by the DSL-authoring agent? All claims cite
`file:line`. **WHAT EXISTS TODAY** is separated from **WHAT'S MISSING**.

---

## TL;DR (the pivot for the round-trip)

1. **There is NO scene → DSL serializer anywhere in the codebase.** The DSL
   pipeline is strictly one-directional: `DSL text → parse → Operations →
   applied to Scene`. There is no `to_dsl`, `emit_dsl`, `scene_to_dsl`, or
   equivalent in Rust, WASM, the editor, or the agent runtime. (Repo-wide grep
   returned nothing.)
2. **Scene JSON — not DSL — is the canonical, persisted, round-tripped
   artifact.** Every layer (store, API, editor, WASM engine, agent) exchanges
   Scene JSON. DSL is a *write-only authoring instrument that emits deltas* into
   a live scene.
3. **Because DSL never has to be reconstructed, the round-trip "take it back" is
   theoretically intact**: the agent edits *by node id* against a live scene
   (`#node_id prop(...)` modify lines, `parent(...)` directives) and never needs
   to re-derive DSL of what a human did. A human's freehand edits live in the
   Scene; the agent patches the Scene.
4. **BUT today the agent-from-editor path is NOT wired to consume the human's
   scene.** `/agent/turn-preview` summarizes the posted scene into prompt *text*
   and then runs the agent against a **blank `new_scene`** — so the agent's
   `#node_id` modify lines would hit `LUMD0901 target node ... does not exist`.
   This is the single biggest, concrete round-trip gap, and it is a *wiring* gap,
   not an architectural impossibility (the core tool already accepts an arbitrary
   input scene).
5. **Absolute / manual x,y positioning is already first-class** in both the
   grammar (`p(x,y)`) and the layout solver — for nodes whose parent is a
   `frame`/`group`/`page`. "Everything is layout-managed" is only true for
   children of **`autolayout` (`al`)** containers. The editor already encodes
   this exact distinction (`isNodeLayoutManaged`).

---

## 1. Direction of the DSL pipeline (WHAT EXISTS)

### 1.1 Parse / compile entry points — all one-way (DSL → Scene)

`crates/lumen-core/src/dsl.rs`:
- `normalize_dsl(source) -> String` — dsl.rs:23 — purely a text-normalizer
  (re-emits the *input* lines, not a scene). Not a serializer.
- `parse_dsl(source) -> DslParseOutput` — dsl.rs:31.
- `compile_dsl(source) -> DslCompileOutput` — dsl.rs:49.
- `compile_dsl_into_scene(source, &mut Scene)` — dsl.rs:54 — applies DSL to an
  existing scene.
- `compile_dsl_into_scene_with_session(source, &mut Scene, session)` — dsl.rs:58.

The whole back half of `dsl.rs` is `lower_*`, `*_from_properties`, `parse_*`
helpers (dsl.rs:1304–5159). Function inventory shows **no** emit/serialize/to_dsl
function — only `parse`, `lower`, `apply`, `*_from_dsl` (DSL → scene types). The
only "to_*" style functions are `layout_anchor_to_scene` (dsl.rs:4142) and
`dimension_to_scene` (dsl.rs:4236) — both *into* the scene, never out.

### 1.2 Compilation produces Operations, then mutates the Scene

`compile_dsl_into_scene_with_session` (dsl.rs:58–96):
1. builds a `DslCompileSession` over `scene.clone()`,
2. `session.compile_block(source)` → `compile_output.operations`,
3. `scene.apply_operations_checked(operations)` (dsl.rs:83).

So the DSL's output is a `Vec<Operation>` applied to the scene. The Operation
set is the actual mutation vocabulary (operations.rs:131–205): `AddPage`,
`InsertNode`, `RemoveNode`, **`MoveNode`** (reparent), **`UpdateNode { patch }`**,
`UpsertSlot`, `PlaceAssetInNode`, etc. The DSL is a *front-end* over these.

### 1.3 The WASM engine serializes Scene → JSON, never Scene → DSL

`crates/lumen-wasm/src/engine.rs`:
- `from_scene_json(scene_json)` — engine.rs:93 — `serde_json::from_str` into a
  `Scene`.
- `load_scene(scene_json)` — engine.rs:110.
- **`scene_json(&self) -> String`** — engine.rs:175 →
  `serde_json::to_string(&self.scene)` (engine.rs:176). **This is the only
  "serialize the scene" path that exists — and it emits JSON, not DSL.**
- `compile_dsl_block(source)` — engine.rs:270 → `compile_dsl_into_scene_with_session`
  (engine.rs:275).

`crates/lumen-wasm/src/lib.rs` exposes `sceneJson()` (lib.rs:60–62),
`loadScene(scene_json)` (lib.rs:53), `compileDslBlock(source)`. There is **no**
`toDsl`/`emitDsl` export.

**Conclusion:** The engine round-trips through **JSON** (`Scene: Serialize +
Deserialize`, scene.rs:12). It cannot round-trip through DSL because no
Scene→DSL function exists.

---

## 2. Is DSL or Scene the canonical artifact? (WHAT EXISTS)

**Scene JSON is canonical, persisted, and round-tripped at every layer.**

- **Scene struct is fully (de)serializable**: `Scene` derives
  `Serialize, Deserialize` (scene.rs:12), as do all child types (`Node`
  scene.rs:268, `Transform` scene.rs:503, `SizeSpec` scene.rs:528, `Dimension`
  scene.rs:543, `AutoLayoutProps` scene.rs:470, etc.). Comments explicitly tune
  fields for **byte-identical scene-JSON round-trips** (scene.rs:279–282 on
  `effects`). This is the artifact they care about preserving losslessly.
- **Store/API persist the scene**: document revisions store `revision["scene"]`
  (main.py:1348, and revision/scene reads throughout main.py; tests assert
  `loaded["scene"] == scene`, test_api.py:296). No `.lumen`/DSL text is persisted
  as the document of record.
- **CoreClient passes scenes around as JSON**: `apply_operations(scene, ops)`
  (core.py:64), `apply_structured_edit(scene, edit)` (core.py:75),
  `compile_dsl_into_scene(scene, source, session)` (core.py:86),
  `preflight_scene(scene, …)` (core.py:101), `export_preview(scene, …)`
  (core.py:116). Every action is *(scene-in) → (scene-out)*.
- **Editor uses Scene JSON natively**: `wasmEngine.ts` does
  `JSON.parse(this.instance.sceneJson())` (wasmEngine.ts:203, 217, 237) and
  `loadScene(JSON.stringify(scene))` (wasmEngine.ts:212). The editor's working
  model is `Scene` (contracts.ts), never DSL.

### Can a human-edited scene be re-emitted as DSL? — NO (WHAT'S MISSING)

There is no code that converts a `Scene` back to DSL text. So if a human edits
the scene directly (via inspector/gesture → `UpdateNode`/`MoveNode`), that change
**cannot be expressed as DSL** by the engine. It can only be expressed as Scene
JSON (which is exactly what is stored and shipped around). This is *fine* given
that Scene JSON is canonical — but it means **DSL is not a faithful mirror of the
scene** and never round-trips a scene.

### Are absolute positions / detached nodes EXPRESSIBLE in the grammar? — YES, mostly (WHAT EXISTS)

Even though there is no auto-serializer, the *grammar can express* the things a
freehand edit produces, when authored by hand or by the agent:
- **Absolute x/y**: `p(x,y)` → `DslProperty::Position` → `node.transform.x/y`
  (parse: dsl.rs:3078; apply on create: dsl.rs:3695–3698; apply on modify:
  dsl.rs:2344–2348). See §3.
- **Reparent / detach**: the `parent(target, new_parent, placement)` directive
  lowers to `build_move_to_parent` → `MoveNode` (dsl.rs:1523–1564); `before(...)`/
  `after(...)` reorder (dsl.rs:1566–1579). A node can be moved into or out of an
  auto-layout container by id.
- **Size mode switches**: `s(w,h)` accepts a number, `hug`, `fill`,
  `fill(weight)`, or `$token` → `Dimension::{Fixed,Hug,Fill,Token}` (grammar.md
  property table; `dimension_to_scene` dsl.rs:4236; `Dimension` scene.rs:543).

Things NOT expressible in the grammar (a fidelity gap if you ever *did* try to
serialize): per-corner radius (grammar.md says 4-arg radius is unsupported →
`LUMD0230`); arbitrary scene fields only reachable via structured `UpdateNode`
patches (e.g. `locked`, `opacity_token`, `asset_placement` crop rects — see §5).

---

## 3. The layout solver is NOT globally flex — there are two positioning regimes (WHAT EXISTS — key finding)

This directly contradicts the framing that "almost everything is layout-managed,
positions are solved not stored." Positions **are** stored in `node.transform`
and the solver *honors them* for non-auto-layout containers.

`crates/lumen-core/src/layout.rs`:
- **Page children**: positioned at `child.transform.{x,y}` (layout.rs:141–145).
- **`layout_node_at`** branches on node kind (layout.rs:157–169): auto-layout →
  Taffy; everything else → manual.
- **Manual (frame/group) children**: each child positioned at
  `origin + child.transform.{x,y}` (layout.rs:179–192). Size resolved by
  `resolve_manual_size` (layout.rs:176). **This is absolute/manual placement, and
  it already works.**
- **Auto-layout (`al`) children**: positions come from Taffy flex
  (layout.rs:322–325 `parent_origin + layout.location`); explicit transforms are
  ignored. A rotated/skewed child is *excluded from flow* and keeps its explicit
  transform (`is_out_of_flow_transform`, layout.rs:264–280, warning `LUMV0701`).
- Mixed case: an auto-layout node can still contain non-flow children laid out by
  transform (layout.rs:340–357).

`DslProperty::Position(x,y)` writes `node.transform.x/y` on both create
(dsl.rs:3695) and modify (dsl.rs:2344). `Transform` carries `x,y,rotation,
skew_x,skew_y,flip_x,flip_y` (scene.rs:503–512). `node.computed:
Option<ComputedGeometry>` (scene.rs:293) is where the solver writes *resolved*
bounds — it is an output cache, populated by `layout_scene` emitting
`UpdateNode { computed }` ops (layout.rs:102–105).

**Implication:** "freehand mode" for a node already exists today *iff the node's
parent is not an auto-layout container*. The fight the user hit previously is
specifically with **auto-layout-parented** nodes, whose `transform` the solver
overwrites.

---

## 4. How the editor already distinguishes managed vs free (WHAT EXISTS)

The editor already implements the exact two-mode concept the user is proposing,
at node granularity:

- `isNodeLayoutManaged(scene, nodeId)` — sceneQueries.ts:172 — returns true **iff
  the node's direct parent is an `auto_layout` node** (sceneQueries.ts:177–180).
- `isNodeDirectGeometryEditable` — sceneQueries.ts:183 — `!locked &&
  !isNodeLayoutManaged` (sceneQueries.ts:188–191).
- Inspector shows X/Y fields bound to `selectedNode.transform.x/y`
  (InspectorPanel.tsx:249,255), and disables/explains direct geometry edits for
  layout-managed nodes (InspectorPanel.tsx:193, 300–301: "managed by an
  auto-layout parent… use layout controls").
- Selection handles (resize/rotate) are hidden for layout-managed nodes
  (SelectionOverlay.tsx:42).
- Arrow-key nudge writes a transform update but bails when
  `isNodeLayoutManaged` (EditorApp.tsx:662) and clamps to parent bounds
  (`clampNodeTransformToParentBounds`, EditorApp.tsx:667; sceneQueries.ts:194).

So a **FREEHAND mode** ≈ "this node's parent is a frame/group, edit
`transform.x/y` directly" already exists per-node. What's missing is a
*container-level toggle* to convert an `autolayout` into a `frame` (or to
"detach" a child to absolute) — that would be an `UpdateNode`/`MoveNode`-shaped
operation, which the engine can already apply.

---

## 5. The edit vocabulary the editor and DSL share (WHAT EXISTS)

Both human edits and agent edits funnel into the **same** `Operation`/`EditPatch`
primitives — this is what makes the round-trip coherent:

- Editor structured edits (`structuredEdits.ts`) build the *same wire format* the
  server uses; the comment is explicit: WASM `applyStructuredEdit` "routes
  through the same `lumen_core::build_structured_edit_batch` the server uses, so
  byte parity is by construction" (structuredEdits.ts:8–13).
- `build_structured_edit_batch` — editing.rs:2269 — and `build_node_modify`
  (editing.rs:905), `build_move_to_parent`, etc. produce `EditBatch`es of
  `Operation`s with optional inverses (`with_inverses`, editing.rs:182).
- The DSL modify line uses the **identical** machinery:
  `lower_modification` → `edit_patch_from_properties` →
  `build_modify_operations` (dsl.rs:1747–1751). The DSL `#node_id` and the
  editor's `modify` edit both resolve through `resolve_edit_target`
  (editing.rs:709) and `node_edit_patch_from_properties` (dsl.rs:2310), which
  **reads the node's current state** (`scene.nodes.get(node_id)`, dsl.rs:2316)
  and patches only changed fields (dsl.rs:2326–2348). It errors `LUMD0901 target
  node … does not exist` if the id is absent (dsl.rs:2316–2325).

**Key consequence for the round-trip:** the DSL modify path operates **by node
id against whatever scene is loaded**. It does not require the node to have been
DSL-authored. So as long as the agent's working scene IS the human-edited scene,
`#node_id …` and `parent(node, …)` will faithfully patch human-created/modified
geometry.

`NodeEditPatch` (editing.rs:571–597) and friends cover transform, size, corner,
layout, fill/stroke/effect stacks, text, name, opacity, locked, asset placement —
this is the full editing surface for recolor / resize / opacity / crop. (Crop =
`asset_placement`/`PlaceAssetInNode`, operations.rs:174; the DSL surface for crop
is thinner than the operation surface — a fidelity gap if crop must be authored
in DSL rather than as a structured op.)

---

## 6. How the agent observes a scene today (WHAT EXISTS) — it reads JSON summaries, never DSL

The agent never reconstructs DSL of an existing design. It reads **JSON
summaries** of the scene:
- `summarize_scene()` → `_scene_summary()` (tools.py:1178, 1681) — pages, counts,
  slots, plus per-node briefs.
- `_node_brief` (tools.py:1739) exposes `transform`, `size`, **`computed`**,
  `kind`, `text`, `slots`, `source_asset_id` — i.e., the agent can see a human's
  manual x/y and resolved bounds.
- `curated_context` injects `scene_summary` + a targeted `scene_subtree`
  (tools.py:1235–1236).
- The agent then emits DSL **deltas** (modify lines / continuations / directives)
  or structured operations against the live scene — it does not rewrite the whole
  thing from reconstructed DSL. (`is_surgical_dsl`, `is_modification_line`
  dsl.rs:4547; loop.py classification at loop.py:1539+.)

This is why a Scene→DSL serializer is *not strictly required* for the agent to
keep editing: it edits by id against the live scene and is briefed by JSON.

---

## 7. THE round-trip gap (WHAT'S MISSING — the make-or-break)

The editor-driven agent turn does **not** load the human-edited scene into the
agent's working scene.

Flow:
1. Editor posts the **full live `scene`** (with human edits) to
   `/agent/turn-preview` (agentRunner.ts:48–61; request type includes `scene:
   Scene`, agentRunner.ts:4–10).
2. API route `agent_turn_preview` (main.py:1016) → `run_agent_turn_preview`
   (main.py:3040).
3. `editor_agent_prompt(payload)` (main.py:3079) folds **only a text summary** of
   the scene into the prompt string: `scene_context_summary(payload.scene)`
   (main.py:3084, 3099) — `meta`, page summary, first **80** nodes
   (main.py:3103), slots. The full scene is *not* loaded as state.
4. `create_provider_quality_loop(prompt, config)` (providers.py:151) constructs
   `LumenDesignTools(config, prompt)` (providers.py:155) whose `__init__` does
   `self.scene = self.core.new_scene(...)` — a **blank scene** (tools.py:132).
5. The agent therefore authors DSL against an **empty** scene. Any `#node_id`
   modify line targeting a human's node id will fail `LUMD0901` (dsl.rs:2316).
   The agent can only *recreate from scratch* based on the text summary, and the
   returned `operations` are derived from a blank-scene compile (main.py:3110–3137,
   3166 returns `draft_scene = tools.scene`).

**Why this is a wiring gap, not an architectural wall:** `CoreClient.
compile_dsl_into_scene(scene, source, session)` (core.py:86) already takes an
**arbitrary input scene**, and `LumenDesignTools._replace_scene_from_core_response`
(tools.py:1619) already swaps `self.scene` to whatever core returns. To "take it
back," the agent need only be **seeded** with `payload.scene` instead of
`new_scene`. There is no Scene→DSL reconstruction required for the agent to
resume editing — it just needs the live scene as state and the existing
JSON-summary briefing.

Open uncertainty: whether the agent's authoring prompts/heuristics (prompts.py,
loop.py classification) behave well when handed a *large, human-mangled* scene
they did not author (e.g. detached/absolute nodes, renamed/duplicated ids,
broken slot bindings). The id-stability of human edits matters: modify lines key
on `NodeId`; if a human deletes/recreates a node, the id changes and the agent
loses its handle.

---

## 8. Fidelity assessment of a *hypothetical* Scene → DSL serializer (WHAT'S MISSING)

If the team ever decides DSL must mirror the scene (it currently must not), a
serializer would be **lossy** today:
- **Lossless-able**: kind, `p(x,y)`, `s(w,h)` incl. hug/fill/token, opacity,
  rotation/skew/flip, fills/strokes/shadows, font props, auto-layout props,
  slots, parenting/order.
- **Lossy / inexpressible in grammar**: per-corner radii (grammar.md →
  `LUMD0230`, only uniform `rd(r)`); `node.computed` (output cache — not
  authored; would be dropped, which is correct); `locked` is editable via patch
  but its DSL authoring surface is unclear; image crop rects
  (`asset_placement`) richer in `PlaceAssetInNode`/`NodeEditPatch` than in DSL
  `to(...)`/`asset(...)`; `opacity_token`/`*_token` fields. So a naive
  round-trip would silently normalize/drop these — another reason the team keeps
  **Scene JSON** (not DSL) as canonical.

---

## Editing implications & round-trip

**For human freehand/layout-managed editing:**
- "Freehand" already exists per-node for children of frame/group/page: the
  solver honors `node.transform.{x,y}` (layout.rs:179–192) and the editor lets
  you edit it (`isNodeDirectGeometryEditable`, sceneQueries.ts:183;
  InspectorPanel X/Y, InspectorPanel.tsx:249–255). The user's "FREEHAND mode" is
  largely **"convert/detach a node so its parent is a frame, not an autolayout."**
  That is a `MoveNode` + maybe `UpdateNode(layout=None)` op — already applicable
  by the engine; needs a UI affordance and possibly a DSL/structured verb to
  "detach to absolute."
- "Layout-managed editing mode" also exists: edit `AutoLayoutProps` (gap,
  padding, align, grow) and sizing modes while the solver governs flow
  (InspectorPanel.tsx:580–698; `updateAutoLayout*`). Geometry x/y is
  (correctly) locked for these nodes.
- Recolor/opacity/font/resize/crop all map to existing `NodeEditPatch`/operation
  fields (editing.rs:571–597), applied identically whether issued by human
  (structured edit) or agent (DSL modify). No new representation needed for these.

**For the agent round-trip ("take it back"):**
- The canonical artifact is **Scene JSON**, and that is the right representation
  to make the round-trip possible — it captures human freehand edits losslessly
  (absolute positions, reparents, detaches), and the agent edits it by node id.
  **No Scene→DSL serializer is needed.** The agent's DSL is a delta language over
  a live scene (modify lines resolve against `scene.nodes`, dsl.rs:2316;
  `parent(...)` → `MoveNode`, dsl.rs:1523).
- The **one concrete blocker** is that the editor→agent route runs the agent on a
  **blank scene** (tools.py:132) and only passes a text summary
  (main.py:3084) — so today the agent literally cannot patch the human's nodes
  (`LUMD0901`). Fix = seed `LumenDesignTools.scene` (and the DSL session's
  parser context) from `payload.scene`. The core tool already accepts an
  arbitrary input scene (core.py:86), so this is plumbing, not redesign.
- Secondary scope to make it *usable*: (a) keep **node ids stable** across human
  edits so the agent retains handles; (b) brief the agent on which nodes are now
  freehand/absolute vs layout-managed (the `_node_brief` already carries
  `transform`/`computed`, so the data is present — prompts must use it);
  (c) decide whether human "detach to absolute" needs a DSL verb so the agent can
  *author* that state, or whether the agent only ever consumes it via the live
  scene; (d) the agent's authoring heuristics need testing against
  human-modified scenes (they were built assuming the agent authored everything).

**Bottom line:** the round-trip is well-supported by the Scene-JSON-centric,
operation-based architecture. The DSL not having a serializer is not the problem
— it's by design. The realistic, bounded scope to make "agent takes back a
human's freehand edit" work is: (1) seed the agent loop with the live scene
(small, high-leverage), (2) guarantee id stability, (3) teach the agent prompts
to read the freehand/managed state already present in the scene, and (4) add an
explicit "detach/attach to layout" operation + UI (and optional DSL verb) for the
freehand toggle the user wants.
