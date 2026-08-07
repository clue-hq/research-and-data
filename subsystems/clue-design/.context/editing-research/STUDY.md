# Lumen Human-Editable Designs + Agent Round-Trip: Authoritative Study

**Verdict in one line:** Build **Stance A (per-node `position_mode` + `absolute_box` on the Node, scene-as-canonical)** as the spine, graft **Stance C's `LayoutMode::Free` per-container conversion** for the common "free this whole section" case, and graft **Stance B's `base_anchor` + provenance idea** as a single field on the freed node (not a separate document). Reject a standalone override-layer document and reject a scene→DSL emitter. The round-trip is **YES**, gated on **one wiring fix** (seed the agent from the live scene), not an architectural rewrite.

This is a decision, not a survey. Where the three architects diverge, the chosen side and the reason are called out explicitly in section 8.

> **Adversarial verification verdict: `sound-with-corrections`** (full detail in `VERIFICATION.md`). The spine is verified against real code. Two material re-scopings before acting:
> 1. **Phase 0 is bigger than "one wiring fix."** Forcing continuation mode is a director/loop+prompts change (`new_artifact` is an `AgentActionMode` in `schemas.py:161`/`loop.py:87-88`, *not* a `tools.py` method), AND the agent's authoring must be changed to **never re-author an existing `NodeId`** (else `compile_dsl_into_scene` hard-errors `LUMD0401` on replay, `dsl.rs:704-715`) — that duplicate-id behavioral change is the real gating work, larger than the seeding wire-up.
> 2. **Agent-apply is `applyOperations` onto the live scene, not a wholesale `replaceScene`** (`EditorApp.tsx:1028-1060`). The real loss vector is op-collision **plus the post-preflight `replaceScene(preflight.scene)` at `EditorApp.tsx:1099`** swapping in a *token-baked* scene each turn (strips live token bindings → degrades future re-theming). Needs explicit handling.
>
> Everything else flagged was citation drift, not substance.

---

## 1. Why the first attempt failed — the precise mechanical reason

The failure is not "the editor was buggy." It is structural: **for auto-layout children, position is solved and discarded-on-write, never stored.** Direct manipulation wrote to a field the solver does not read.

The solver has two regimes, dispatched purely on parent kind in `layout_node_at` (`crates/lumen-core/src/layout.rs:157-169`):

- **Absolute regime** (Frame / Group / Page / leaf children): the child is laid out at `origin.x + child.transform.x, origin.y + child.transform.y` — `transform.x/y` **is** the position and is honored verbatim (`layout.rs:141-145`, `layout.rs:179-192`).
- **Flex regime** (children of an `AutoLayout` node): positions come from Taffy's solved `layout.location` added to the parent origin (`collect_taffy_geometry`, `layout.rs:322-330`). **The authored `transform.x/y` is never passed into the Taffy `Style` and is completely ignored.**

The editor already encodes exactly this rule: `isNodeLayoutManaged` returns true iff the direct parent is `auto_layout` (`apps/editor/src/engine/sceneQueries.ts:172-181`), and `isNodeDirectGeometryEditable` = `!locked && !layoutManaged` (`sceneQueries.ts:183-192`). For an auto-layout child this gate is **false**, so the canvas drag/resize op builders early-return null (`apps/editor/src/engine/canvasOperations.ts:41,77`) and the inspector X/Y/W/H fields are disabled (`apps/editor/src/components/InspectorPanel.tsx:248-279`).

So when the prior attempt tried to make managed nodes draggable, the chain that broke was:

1. A drag commits `updateNodeTransform`, which writes `transform.x/y` only (`canvasOperations.ts:26-62`).
2. That patch is render-affecting, so `computed` is cleared to force a relayout (`editing.rs:1002-1006`, mirrored editor-side at `operations.ts:65-79`).
3. The next whole-tree relayout (`engine.rs:135-138`, no incremental/dirty tracking) re-solves the auto-layout parent via Taffy and **overwrites the node's position from `layout.location`** (`layout.rs:322-330`), discarding the human's `transform.x/y`.

**The node snapped back.** That is the entire failure. There is no per-node escape from flow today except an *accidental* one: a rotated/skewed auto-layout child is pulled out of flow and its transform honored (`is_out_of_flow_transform`, `layout.rs:1508-1512`; routed at `layout.rs:264-282` and `340-357`), emitting warning LUMV0701. This was never designed as a free-placement flag — it is a side effect of rotation — **but it is the proof-of-concept that the solver can honor an out-of-flow auto-layout child**, and it is exercised by passing tests (`tests/layout_engine.rs:766-789`). That existing path is the seam the fix rides on.

Secondary mechanical hazard at the **style** layer (the same failure mode, re-skinned): raw literal edits and their `*_token` sibling are applied independently with no cross-field invalidation (`operations.rs:556-597`). The destructive `TokenResolver::resolve_node` bakes the token into a literal and sets the token field to `None` (`brand.rs:3405-3583`) on a *cloned* scene during preflight — so a human's raw opacity/font edit that left the token intact gets clobbered when preflight re-applies the surviving token. Picking a raw fill color is worse: it replaces the whole `fills` array and discards any `Paint::Token` (`InspectorPanel.tsx:381-386`), destroying the design *intent* even though the literal round-trips.

---

## 2. The core decision: what becomes the source of truth

**Commit: the canonical persisted Scene JSON is the source of truth — the moment a human edits, and forever.** Not the DSL. Not a separate override document.

This is not a preference; the codebase already decided it:

- The DB stores `current_scene_json` plus an append-only operation/edit-envelope log with inverses; **there is no `dsl_source` column** (`apps/api/migrations/001_init.sql:3-39`, `003_edit_envelopes.sql:7-28`).
- The DSL is **create-only** and lowered into canonical Operations applied to the persisted Scene; the scene is **not** re-derived from DSL (`dsl.rs:54-95`). Authoring an existing node id hard-errors LUMD0401 (`dsl.rs:704-715`).
- **No scene→DSL serializer exists anywhere** in the repo — a grep for `to_dsl`/`emit_dsl`/`scene_to_dsl` returns zero hits across `crates/` and `apps/`. The only serialize path is `scene_json()` (`lumen-wasm` `engine.rs:175`). Its absence is *by design*, not a gap.
- Human (`source:editor`) and agent (`source:agent`) edits already run through the **same** `build_structured_edit_batch` path with byte-parity by construction (`apps/editor/src/engine/structuredEdits.ts:8-13`, `editing.rs:2269`).

**Implication for the round-trip.** Because the scene is canonical and the agent edits it by stable `NodeId` (author-assigned `[A-Za-z0-9_-]` strings, not UUIDs — `ids.rs:26-89`), the round-trip is **a re-edit-in-place problem, not a reverse-engineering problem.** A human's freehand edits are ordinary scene fields; the agent re-reads the same JSON and emits more operations against the same ids. **No scene→DSL emitter is needed and none should be built** — building one would be expensive, lossy, and would re-create the human↔agent format gap that the override-layer architects rightly fear, while a scene-ops surface avoids it entirely.

**Why not an override-layer document (Stance B's core bet)?** B's instinct — keep agent and human edits *structurally separable* — is correct and partially adopted (see §3, `base_anchor`). But making the human edits a **separate persisted document** (`overrides: BTreeMap<NodeId, NodeOverride>` as a sibling column) is the wrong cost/benefit:

- It **doubles the persistence and undo surface**. Undo today is per-Operation-batch inverse replay (`operations.rs:920-940`); a separate override map needs its own `SetOverride`/`ClearOverride` invertible variants or undo silently skips human edits. B concedes this.
- It requires a **`compose_overrides` post-pass that must run in BOTH the editor (`engine.rs`) and the server preflight/export (`preflight.rs:164-195`)** or a frozen position looks right in-editor and wrong on export. The compose chokepoint is real and clean — `layout_scene` is a pure function that fills a geometry map (`layout.rs:72-92`), and the write into `node.computed` happens afterward in `engine.rs:129-140` and `preflight.rs:164-195` — but you pay the parity tax *twice* (once for the override pass, once for the absolute-box honoring) instead of once.
- Most decisively: **the agent now has to reason about two artifacts** (`base_scene` + `human_overrides`) and a three-verb reconcile protocol (honor/bake/drop) for every override. That is exactly the kind of bespoke machinery that makes the agent loop brittle. With Stance A, an absolute node is *one node with two extra fields* the agent reads in the same `_node_brief` it already consumes (`tools.py:1739`).

The genuinely valuable part of B — "did the human nudge this 12px off where I'd put it?" — is captured by a **single `base_anchor` field on the freed node** (§3), not a parallel document. That gives B's reconciliation signal at ~5% of B's cost.

---

## 3. Freehand mode — exact data-model + engine + editor changes

**Definition.** Freehand = freezing a node's currently-solved geometry into a stored absolute box and flipping it out of flow, **without reparenting** (it stays a logical child of its container). This mirrors Figma's "absolute position inside auto-layout" escape hatch. There are two granularities, and we ship both because they serve different user intents:

- **Per-node detach** (Stance A): "free *this one* element" while its siblings stay in the stack.
- **Per-container free mode** (Stance C, grafted): "make *this whole section* a free canvas." This is the more common real intent and is cheaper to honor (the solver simply skips Taffy for that container and runs the absolute path it already has).

### 3.1 Data-model changes (NEW)

Add to `Node` (`crates/lumen-core/src/scene.rs:268-295`), all `#[serde(default)]` so existing persisted `current_scene_json` deserializes byte-identically (the established pattern — see `effects` at `scene.rs:281`, `opacity_token` at `scene.rs:285`):

```rust
#[serde(default)] pub position_mode: PositionMode,      // Managed (default) | Absolute
#[serde(default, skip_serializing_if = "Option::is_none")]
pub absolute_box: Option<Rect>,                          // page-space, reuse Rect (scene.rs:696-702)
#[serde(default, skip_serializing_if = "Option::is_none")]
pub base_anchor: Option<Rect>,                           // GRAFT from B: solved box at detach time
```

`PositionMode { Managed, Absolute }` with `Default = Managed`. `Rect` already exists and is exactly the type `ComputedGeometry.layout_bounds` uses (`scene.rs:704-708`) — no new geometry type.

For per-container free mode (GRAFT from C), add to `AutoLayoutProps` (`scene.rs` near the `gap_token` optional-default pattern at `scene.rs:473`):

```rust
#[serde(default)] pub layout_mode: LayoutMode,           // Stack (default) | Free
```

**Why `base_anchor`:** it is the solved box at the instant of detach. The agent later diffs `absolute_box` against `base_anchor` to know "the human moved this 12px right of where the solver put it" and can preserve the *offset* after a relayout instead of either clobbering or blindly pinning. This is B's single best idea, kept as one field instead of a document.

**What is reused, not built:** `transform` already stores rotation/skew/flip; `SizeSpec`/`Dimension` (`scene.rs:528-550`) already model Fixed/Hug/Fill/Token; `opacity`+`opacity_token`, `fills`/`strokes`/`effects`, `corner`, `clip`, `asset_placement` are all already plain fields. Freehand adds **no** new visual-property model.

### 3.2 Engine / solver changes (small, localized)

1. **Per-node:** widen the out-of-flow check in `build_taffy_node` (`layout.rs:264`) from `is_out_of_flow_transform(child)` to `is_out_of_flow_transform(child) || child.position_mode == Absolute`, so an Absolute child is excluded from the Taffy flex children list **exactly like a rotated child is today.** In the absolute-routing path (`layout.rs:340-357`), lay the Absolute node out at its stored `absolute_box` (page space) instead of `origin + transform`.

2. **Per-container (GRAFT C):** in `layout_node_at` (`layout.rs:166`), when the container's `layout_mode == Free`, skip `layout_auto_node` and route children through the absolute path (`layout.rs:179-192`). This *generalizes the kind-switch that already exists at `layout.rs:157-169`* — it is a branch, not a subsystem.

3. **Render stays uniform.** The solver still calls `write_geometry` (`layout.rs:727-742`), which fills the geometry map → written back to `node.computed` in `engine.rs:129-140`. For an Absolute node, `write_geometry` is called with the `absolute_box` origin/size, so `computed.layout_bounds` ends up correct and `render_box_for_node` (`render_geometry.rs:22-45`) — which prefers `computed` and only falls back to `transform`+Fixed when `computed` is None — needs **zero change**. This avoids the stale-`computed` hazard entirely (no reliance on clearing `computed` to expose a transform fallback).

### 3.3 The detach / re-attach operations (NEW orchestration)

This is the piece that genuinely does not exist today. Model as **`UpdateNode`/`NodePatch` field additions** (cheapest — reuses the universal mutator at `operations.rs:102-126,158`) plus two composite builders:

- **`DetachToFreehand{node_id}`**: read the node's solved `computed.layout_bounds`; write `position_mode = Absolute`, `absolute_box = computed.layout_bounds`, `base_anchor = computed.layout_bounds`, and convert `size` Hug/Fill→Fixed using the solved w/h. One invertible Operation.
- **`ReattachToLayout{node_id}`**: clear `absolute_box`, set `position_mode = Managed`; optionally restore Hug/Fill if intent was captured.
- **`ConvertContainerToFree{node_id}`** / **`ConvertContainerToStack`** (GRAFT C): set `layout_mode`, and for free conversion bake each child's `transform.x/y` from `computed.layout_bounds - parent_origin` and `size = Fixed`.

**Invertibility is mandatory.** Add inverses in `inverse_for_operation` (`operations.rs:942-...`, the matcher that powers `invert_operations` at `operations.rs:920-940`) so undo and the `edit_envelopes` log stay consistent. This is non-negotiable: today `FinalizeTemplate` and child-adopting `InsertNode` are the *only* non-invertible ops (`operations.rs:1019-1030`); detach must not join them or the local 50-frame undo stack and the server inverse history (`EditorApp.tsx`) diverge.

### 3.4 How each freehand edit is stored

| Edit | Stored as | Status |
|---|---|---|
| **Drag** (Absolute node) | update `absolute_box.x/y` via `UpdateNode` | NEW commit target; gesture math reused |
| **Resize** (Absolute node) | update `absolute_box.w/h`; `size` stays Fixed | reuses `transformerMath.ts:69-138` (mode-agnostic) |
| **Drag** (managed node) | reorder via `MoveNode`-by-index (`operations.rs:505-554`) — changes flow order, not pixels | see §4 |
| **Font family/size/weight** | `TextNode` fields via `UpdateNode`/`TextEditPatch` (`scene.rs:343-371`, `editing.rs`) | EXISTS, not layout-gated |
| **Color / recolor** | per-fill `StackEntryEdit` or `fills` patch (`editing.rs:550-567`) | EXISTS; clear sibling token (§5) |
| **Opacity** | `opacity` field (`scene.rs:284`) | EXISTS in UI (`InspectorPanel.tsx:281-297`) |
| **Crop (focal/fit)** | `asset_placement.fit`+`focal_point` (`assets.rs:328-338`) | model + render EXIST (`svg.rs:1032-1072`); **no UI** — build inspector |
| **Crop (free rect)** | new normalized field on `AssetPlacement` | **NEW, deferred** (§6) |

### 3.5 Editor changes

- Extend `isNodeDirectGeometryEditable` (`sceneQueries.ts:183-192`) to return true when `position_mode == Absolute` **or** the parent container is `layout_mode == Free`, even under an auto_layout parent.
- Point the existing drag/resize commits (`canvasOperations.ts:26-114`) at `absolute_box` for Absolute nodes; the gesture machine (`gestureMachine.ts:180-193`) and `transformerMath.ts` are mode-agnostic pure box math and need **no** changes.
- Add a **per-selection action** "Detach to freehand" / "Re-attach to layout" and "Convert section to free / stack". This is an inspector/selection action — **not** in `editorModes.ts`, which is misleadingly named and only defines right-sidebar panels (`apps/editor/src/engine/editorModes.ts:1,10-15`). The only real interaction mode is `WorkspaceTool = "select" | "hand"` (`workspaceViewport.ts:11`).

---

## 4. Layout-managed editing mode — mapping each edit onto the solver without fighting it

Managed editing is the **default and already largely works.** The principle: in managed mode the human edits *intent* (the solver's inputs), never *pixels*. Routing is decided by the existing `isNodeDirectGeometryEditable` predicate.

| Edit | How it maps | Fights solver? |
|---|---|---|
| **Resize** | re-choose `SizeSpec` mode: set `Dimension::Fixed(v)`, or toggle Hug/Fill via `UpdateNode` (`scene.rs:528-550`). The one UX gap: inspector W/H handles for a managed child must emit a **size-mode** change, not a transform — `updateNodeTransformAndSize` collapses to Fixed today (`operations.ts:294-303`), which is right for absolute but should be a "set size mode" variant for managed. | No |
| **Move** | translate the gesture to a **reorder** via `MoveNode`-by-index (`operations.rs:505-554`). Managed drag changes flow order; freehand drag changes `absolute_box`. | No |
| **Recolor** | `fills` patch / per-fill `StackEntryEdit` (`editing.rs:550-567`). Solver ignores fills. **Must clear sibling `*_token`** (§5). | No (style layer) |
| **Font / typography** | `TextNode` fields (`scene.rs:343-371`); affects measurement → solver re-flows correctly via the text measurer. | No |
| **Opacity** | `opacity` field; solver ignores it. Clear `opacity_token` on raw edit. | No |
| **Gap / padding / align / direction** | `AutoLayoutProps` via `UpdateNode` (`scene.rs:470-497`); inspector already exposes these. | No — *this is the point of managed mode* |
| **Crop (focal/fit)** | `asset_placement`; solver ignores; render honors via `focal_crop_geometry`. | No |

**Bindings & slots interaction.** Token bindings survive in the live editing scene because `resolve_scene_tokens` runs on a **cloned** scene in preflight (`brand.rs:2358-2378`, `preflight.rs:145`) — the live document keeps tokens. So "managed recolor = pick a new token" round-trips cleanly. Slot-bound text is volatile (overwritten at instance derivation, `instance.rs:733-762`), and nodes have no slot back-reference, so a human editing slot-bound text gets a non-durable change — a UI warning is desirable but out of MVP scope. `Node.locked` is honored by the editor gate but **ignored by the solver and agent**; it is not a "do-not-relayout" signal and should not be overloaded as one.

---

## 5. The round-trip answer

### CAN the agent take back human freehand edits? **YES — under the canonical Scene JSON + stable NodeIds, gated on one wiring fix.**

Today the answer is **NO**, for exactly one reason that is **wiring, not architecture**:

- The runtime **always** starts from an empty scene: `LumenDesignTools.__init__` calls `core.new_scene` (`apps/agent_runtime/lumen_deepagent/tools.py:132`); both entry points pass no scene (`providers.py:155`, `factory.py:30`).
- The editor's live scene reaches the runtime **only as truncated prompt text**: `editor_agent_prompt` embeds `scene_context_summary(payload.scene)` keeping the first 80 node briefs (`apps/api/lumen_api/main.py:3079-3107`); `payload.scene` is the full editor scene (`models.py:104`) but is **never parsed back into a working Scene**.
- So the agent regenerates from empty and emits constructive `add_page`/`insert_node` ops that either collide on replay onto the live scene (`EditorApp.tsx:1028-1060`) or trigger a wholesale `replaceScene` that **discards human work** (`EditorApp.tsx:521-549`).

### The fix that closes the round-trip

1. **Seed the agent's working scene from the live scene.** Add an optional `initial_scene` arg: `LumenDesignTools.__init__` (`tools.py:132`) seeds `self.scene` from `payload.scene` instead of `new_scene`; thread it through `factory.py:30` / `providers.py:155` → `create_provider_quality_loop`; parse `payload.scene` in `run_agent_turn_preview` (`main.py:3040-3068`) into the seeded scene rather than only summarizing it. The core tool already accepts an arbitrary input scene (`core.py:86`), and `compile_dsl_into_scene` applies additively onto an existing `&mut Scene` (`dsl.rs:54-95`), so the machinery downstream already works.

2. **Force continuation/director mode.** Forbid `new_artifact` and `start_fresh_rewrite_scene` (`tools.py:1498-1500`) when `initial_scene` is present, so the seed is never wiped.

3. **Return ops diffed against the seed,** not constructive-from-empty ops, so replay doesn't collide (`main.py:3136-3137`).

4. **Surface the new fields to the agent.** Extend `_node_brief`/`summarize_scene` (`tools.py:1739`) to expose `position_mode`, `absolute_box`, `base_anchor`, and container `layout_mode`, so the agent can distinguish "human pinned this — preserve it" from "I own this, safe to relayout."

Once seeded, the existing edit-in-place machinery works: DSL `modify #node_id` resolves targets by `NodeId` against the live scene and reads current state (`dsl.rs:2310-2348`), and structured `UpdateNode`/`MoveNode` ops target real ids — the same vocabulary human edits use.

### What is preserved vs reconciled vs discarded

- **Preserved losslessly:** all visual props (color/opacity/font/stroke/fit/focal-crop are plain invertible fields), node identity, parent membership, **and absolute placement** — because `absolute_box` is a first-class persisted field the solver honors, not an opaque overlay. The agent re-edits an Absolute node by `NodeId` and can choose to respect its box, preserve the `base_anchor` offset, or re-attach it.
- **Reconciled (the agent decides, informed by `base_anchor`):** if the agent restructures a node such that a pinned box no longer makes sense, it sees `absolute_box` vs `base_anchor` and chooses to re-pin, bake the offset into the new layout, or re-attach to flow. This is B's reconcile value, achieved with one field and no separate document.
- **Discarded / semantically lossy (honest limits):**
  - Converting a Stack to Free **bakes Hug/Fill→Fixed** (the `fixed_or_zero` lossiness at `layout.rs:1495-1505`); the agent cannot auto-re-flow that container back to a clean stack without re-authoring. Mitigate by optionally stashing the pre-bake `SizeSpec`; otherwise accept it as explicit, per-container, and visible in the model.
  - If a raw color edit destroyed a `Paint::Token` (`InspectorPanel.tsx:381-386`), the design *intent* (the token binding) is gone even though the literal round-trips — the agent can no longer re-theme that node. This is the prior failure mode resurfacing at the **style** layer.
  - After heavy freehand detaching, the design degrades toward "just positioned nodes" and the agent's slot/repeater/worst-case layout-quality machinery (`slots.rs`) has less Hug/Fill intent to grip. Round-trip is **structurally** fine but the agent's **repair quality** degrades on a heavily-freehanded scene.

**Honest bottom line:** round-trip is mechanically guaranteed by scene+ops+stable-ids; it is *semantically* lossy in proportion to how much structure the human dissolves into absolute pixels. That is unavoidable in any architecture (B included — B's overrides also carry no slot provenance) and is the right trade.

---

## 6. Recommended scope & sequencing

Ship in the user's instinctive order: **make the round-trip exist first, then freehand, then managed correctness, then crop.** Each phase is independently shippable and usable.

### Phase 0 — Close the round-trip (highest leverage, smallest change, ZERO engine work)
This alone flips the agent from "regenerate" to "edit-in-place" and makes **today's already-free nodes** (frame/group/page children, which already drag/resize) round-trip.
- `tools.py:132` — add `initial_scene`; seed `self.scene` from `payload.scene`.
- `factory.py:30`, `providers.py:155`, `create_provider_quality_loop` — thread it through.
- `main.py:3040-3068` — parse `payload.scene` into the seed; return ops **diffed against the seed**.
- `tools.py:1498` — continuation mode forbidding `new_artifact`/`start_fresh_rewrite_scene`.
- Validate: agent `modify #id` against a human-edited scene applies without LUMD0901 / id collision.

### Phase 1 — Freehand as a real mode (the user's first product win)
- `scene.rs:268-295` — add `position_mode`, `absolute_box`, `base_anchor` (serde defaults); `AutoLayoutProps` — add `layout_mode`.
- `layout.rs:264` — honor `position_mode == Absolute` in the out-of-flow check; `layout.rs:166` — route `layout_mode == Free` containers through the absolute path; `layout.rs:340-357` — lay Absolute nodes at `absolute_box`.
- `operations.rs` — `DetachToFreehand` / `ReattachToLayout` / `ConvertContainerToFree` as `NodePatch` fields + composite builders; **inverses in `inverse_for_operation` (`operations.rs:942`)**.
- `sceneQueries.ts:183-192` — gate honors `position_mode`/`layout_mode`; `canvasOperations.ts:26-114` — commit to `absolute_box`.
- Per-selection toggle action (inspector, not `editorModes.ts`).
- `tools.py:1739` — expose new fields in `_node_brief`.
- **Single-node + single-container only; defer multi-select.**

### Phase 2 — Managed-mode correctness + missing basics
- **Stale-token clobber fix** (closes the §1 style hazard): on a raw literal write to a token-bearing field, clear the matching `*_token` sibling in the same patch (`operations.rs:556-597`, `brand.rs:3453-3532`).
- Managed-drag → reorder via `MoveNode`-by-index; managed W/H → size-mode change variant.
- **Crop / opacity / image inspector UI** — model + render already exist for fit/focal (`assets.rs:328-338`, `svg.rs:1032-1072`); only the inspector control is missing.
- **Live image preview in editor** — today images draw as placeholder fills (`drawDescriptors.ts:16-17`), so a human cropping gets no feedback; wire asset bytes through.

### Phase 3 / DEFER
Free-form rectangular crop rect (new normalized `AssetPlacement` field + `svg.rs`/`render.rs` support); arbitrary path crop masks; multi-select group transform; reparent-on-drag with world-position preservation (today `MoveNode` does **no** coordinate conversion — `operations.rs:505-554` — so a reparent jumps); true components/instances with detach/override (`NodeKind::Instance` is unused scaffolding, `instance.rs`); a scene→DSL emitter (**never build** — unnecessary by design); PDF image/opacity (`pdf.rs:286`).

---

## 7. Risks, open questions, and what to validate first

### Validate FIRST (cheap, decisive, do before writing Phase 1 code)
1. **Phase 0 replay collision.** Does `engine.applyOperations` reject, silently merge, or duplicate when the agent's ops are replayed onto a non-empty seeded scene (`EditorApp.tsx:1028-1060`)? This decides whether Phase 0 is "just lossy" or "actively breaks." Test before anything else.
2. **Serde round-trip.** Confirm adding `position_mode`/`absolute_box`/`base_anchor`/`layout_mode` with defaults leaves existing persisted `current_scene_json` byte-identical and passes the W6 conformance/parity fixtures. Defaults must be exactly right or old scenes shift.
3. **NodeId stability across human edits.** The agent re-targets by `NodeId`. If the editor's human delete+recreate changes an id, the agent loses its handle. Confirm the editor's id-allocation for human-created/edited nodes is stable/reused.

### Standing risks
- **Editor↔server layout parity.** A frozen `absolute_box` correct in the editor's heuristic relayout could be wrong on the server's approximate Skia measurer (`text_measure.rs` `ProvidedTextMeasurer`), making a frozen text box clip on export. Mitigate: bake `absolute_box` from the *canonical* layout pass, not the editor's, and keep the Absolute-honoring logic in `lumen-core` so editor and `preflight.rs` share it.
- **Overflow rule LUMV0801.** A child exceeding a *clipped* parent's bounds is an **error** that rejects the whole checked apply (`layout.rs:831-847`). A freehand drag outside a clipped frame would reject the batch. Need a policy: auto-disable clip, clamp, or downgrade to warning for Absolute/Free-mode nodes.
- **Two uncoordinated undo stacks** (client snapshot stack vs server inverse-op history). Detach/Convert ops must be invertible in **both** or undo diverges — the inverse work in `operations.rs:942` is what makes the server side consistent; the client stack already snapshots scenes.
- **Stale-token clobber** (Phase 2) is a real code change, not free — and even fixed, a destroyed `Paint::Token` loses re-theming intent permanently.
- **Semantic erosion** — covered in §5; accept as the honest cost of human freedom, contained and visible in the model.

### Open questions for the user / next investigation
- Do the agent's authoring prompts behave correctly handed a large human-modified scene they did not author (detached/absolute nodes, broken slot bindings)? They were likely built assuming the agent authored everything (`prompts.py`, `loop.py` classification).
- Is a true free-form crop rect in scope for a later phase, and should it be stored in normalized 0..1 source space (survives asset re-upload) — on `AssetPlacement`, not `ImageNode`?
- Should slot-bound-text volatility surface a UI warning, given a human's typed text there is only a fixture (`instance.rs:733-762`)?

---

## 8. Where the architects diverge — and the chosen side

| Dispute | A (detach-to-absolute / scene-canonical) | B (override-layer document) | C (free-layout container mode) | **Chosen** |
|---|---|---|---|---|
| **Source of truth after a human edit** | Scene JSON, mutated in place | Untouched base scene + separate override doc | Scene JSON, mutated in place | **Scene JSON (A/C).** Codebase already made this call (`001_init.sql`, no `dsl_source`). |
| **Where freehand position lives** | `absolute_box` field on Node | `NodeOverride.position` in sibling map | child `transform.x/y` under a Free container | **Both A's per-node `absolute_box` AND C's per-container `Free` mode** — different user intents, both cheap, both reuse the existing absolute path. |
| **Agent/human edit separability** | Same fields, no separation | Permanent structural separation (2 artifacts) | Same fields, no separation | **A/C: one artifact.** Adopt B's *signal* (`base_anchor`) as one field, reject B's *document*. Separation isn't worth 2× persistence/undo + 2-artifact agent reasoning. |
| **Solver change** | Widen out-of-flow check (1 line) | `compose_overrides` post-pass in editor+server | Branch the kind-switch for Free | **A's widen + C's branch.** Both generalize the *existing tested* out-of-flow/kind-switch paths (`layout.rs:264`, `layout.rs:157-169`). B's compose-pass is clean (single chokepoint at `write_geometry`→`computed`) but pays the parity tax twice. |
| **Hug/Fill loss on detach** | Per-node, only if size collapses | None (base untouched) | Per-container bake to Fixed | **Accept it, scoped + visible.** B avoids it but at the cost of the override document; the loss is honest and contained. |
| **Scene→DSL emitter** | Not needed | Not needed | DSL grammar extended with `free` | **Not needed; do not build.** C's DSL `free` directive is optional polish (lets the agent *author* free layouts in DSL); the agent can *consume and modify* them via scene ops without it. Defer the grammar work. |

**Net:** A is the spine because it makes freehand a *first-class persisted per-node concept* the solver honors with a one-line generalization of a tested path, keeps render uniform (no stale-`computed` games), and needs no new subsystem. C grafts on as the "free this whole section" container mode using the same absolute path. B contributes exactly one field (`base_anchor`) for reconciliation. The round-trip closes with a wiring change, not a rewrite.
