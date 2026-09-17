# Phase D: Targeted Editing And Repair Semantics

## Purpose

Phase D turns Lumen from a generate-once design engine into an iterative design
system where agents and users can refine an existing artifact without
regenerating the whole page.

The core product requirement is simple:

```text
"Move this logo left."
"Make the headline smaller."
"Replace this image."
"Put this CTA after the supporting copy."
"The reviewer says the body text overflows. Repair only that section."
```

Those requests must become precise, checked, replayable changes against the
canonical `Scene` through canonical `Operation` batches. They must not become
hidden Python mutations, ad hoc editor state, or full-page DSL regeneration.

## Roadmap Position

This phase is the product roadmap's targeted edit phase:

- Product Improvement Plan gaps: Modify Language, Compiler Recovery, Agent
  Protocol, Source Of Truth.
- DSL Comparison gaps: missing `#target`, `before`, `after`, `replace`,
  `clone`, `override`, checkpoint, and undo/redo lowering.
- Agent Loop Comparison gap: visual repair needs a precise edit surface after
  critique rejection.
- Scene Model Comparison gap: refinements must be canonical operation patches,
  not regenerated pages or hidden state.

Phase D depends on the contracts and behavior already established by:

- `engine/dsl-compiler`: parsed modify lines, parsed directives, cascade halt,
  `DslCompileSession`, draft-scene-backed lowering for current create/delete
  and parent semantics.
- `phase-b/layout-text-reliability-v0`: custom page dimensions, computed
  geometry, text diagnostics, truthful debug previews.
- `agents/product-quality-loop-v0`: structured visual critique and repair
  requests that can identify target pages, nodes, slots, and issue categories.
- `phase-f/editor-export-productization-v0`: editor gestures already emit
  canonical operations and expose many user-facing edit controls.

## Brilliant-Derived Principles

The Brilliant reverse-engineering report gives the main design inspiration:

1. **Flat target modify lines.**
   A flat line beginning with a ref mutates an existing element:

   ```text
   #hero fill(#ffffff) rd(16)
   #headline text("A tighter headline") font_size(44)
   ```

2. **Small streamed blocks.**
   Agents should author one small block at a time. After a block succeeds,
   preview and critique run before the next block.

3. **Cascade halt and resume.**
   A failing edit line must halt at exactly one line. Lines before the failure
   remain applied; lines after the failure are discarded. The next repair block
   resumes with the same session context.

4. **Stable refs enable repair.**
   Agents need stable node, page, slot, paint, and asset identifiers so they can
   target one piece of the scene without rewriting unrelated content.

5. **Directive verbs are first-class.**
   Brilliant exposes `parent`, `before`, `after`, `clone`, `replace`,
   `ungroup`, `override`, `delete`, `undo`, and `redo`. Lumen should preserve
   that authoring shape, but lower it through Lumen's canonical scene and
   operation model.

6. **Checkpoints are authoring and history anchors.**
   Brilliant uses written labels as undo anchors. Lumen should adopt the
   concept, but store checkpoint effects in operation history/run traces rather
   than in visual scene data.

7. **Editor and agent use the same semantics.**
   Brilliant's layout engine drives both agent-authored blueprints and human
   drag/reorder interactions. Lumen should share operation builders between
   agent patching, DSL edit lowering, API persistence, and the React/Konva
   editor.

## Current Lumen Baseline

Lumen already has the low-level contracts needed for many targeted edits:

- `Operation::UpdateNode`
- `Operation::UpdatePage`
- `Operation::MoveNode`
- `Operation::RemoveNode`
- `Operation::InsertNode`
- slot, asset, BrandKit, and export-profile operations
- checked operation application
- scene validation
- `DslCompileSession`
- parsed but currently unlowered `#target ...` modify lines
- parsed but currently unlowered `before`, `after`, `clone`, `replace`,
  `undo`, `redo`, and `override`
- editor-side operation helpers for many common direct manipulation workflows

The missing product layer is the targeted edit contract:

- target resolution
- patch grammar
- directive semantics
- structured agent patch DTOs
- diagnostics and safety policy
- trace/history/checkpoint behavior
- shared editor/agent operation builders

## Scope

Phase D should build:

1. Target-reference model for pages, nodes, slots, assets, export profiles, and
   document-level targets.
2. `#target ...` modify DSL lowering into canonical operations.
3. Structured operation patch tool for agents.
4. `before`, `after`, richer `parent`, and safe `delete`.
5. Text, style, layout, geometry, page, slot, and asset replacement patches.
6. Clone/override/component-oriented semantics for repeated structures.
7. Checkpoints and undo/redo after stable edit batches exist.
8. Shared edit builders reused by DSL, agent tools, API, and editor.
9. Tests and conformance fixtures that prove unrelated scene regions are
   preserved.

## Non-Goals

Phase D should not build:

- a new canonical document model
- a second editor state model
- a prompt-only repair policy that bypasses operations
- asset upload/storage/provider runtime
- full ABM personalization runtime
- print-fidelity text shaping
- full Figma parity
- collaboration/conflict resolution

It may define hooks or metadata needed by those future phases, but it should
not own their runtime behavior.

## Core Invariants

1. `Scene` remains the canonical runtime model.
2. `Operation` remains the canonical mutation and replay surface.
3. DSL is an authoring projection, not the source of truth.
4. Every targeted edit lowers to checked operation batches.
5. A failed edit batch must leave the scene unchanged.
6. A partial DSL block may apply valid operations before a cascade halt, but the
   failing line and later lines are not applied.
7. Every edit must have a target and a clear expected effect.
8. Targeted edits must preserve unrelated nodes, pages, slots, assets, and
   export profiles.
9. Repair tools should prefer small patches over whole-page regeneration.
10. Finalized template edits must create draft/revision behavior according to
    the existing template revision rules, not mutate finalized snapshots in
    place.

## Target Reference Contract

Phase D should introduce a typed target reference model shared by DSL, agent
tools, API DTOs, and editor helpers.

Recommended Rust shape:

```rust
pub enum EditTargetRef {
    Document,
    Page(PageId),
    Node(NodeId),
    Slot(SlotId),
    SlotKey(SlotKey),
    Asset(AssetId),
    ExportProfile(String),
}

pub struct ResolvedEditTarget {
    pub target: EditTargetRef,
    pub parent: Option<ParentRef>,
    pub index: Option<usize>,
    pub node_kind: Option<NodeKind>,
    pub page_id: Option<PageId>,
    pub slot_bindings: Vec<NodeId>,
}
```

Supported DSL target forms:

```text
#node_id ...
#page:page_id ...
#slot:campaign.headline ...
#slot_id:slot_campaign_headline_abcd1234 ...
#asset:asset_logo ...
#document ...
#export:print_pdf ...
```

Resolution rules:

- `#node_id` resolves to an existing node.
- `#page:page_id` resolves to an existing page.
- `#slot:key.path` resolves by `Slot.key`.
- `#slot_id:slot_id` resolves by `Slot.id`.
- `#asset:asset_id` resolves by `Scene.assets`.
- `#document` resolves to `Scene.document`.
- `#export:name` resolves by `Scene.export_profiles[name]`.
- Ambiguous or missing targets are hard diagnostics.
- Targets cannot resolve to deleted nodes or detached tree fragments.
- Locked nodes reject visual mutation unless the edit explicitly passes a
  future unlock authority.

Diagnostic examples:

```text
LUMD0901 target not found
LUMD0902 target is ambiguous
LUMD0903 target kind does not support this property
LUMD0904 target is locked
LUMD0905 target belongs to a finalized template revision
```

## Modify DSL Contract

Modify lines are flat and target existing scene objects:

```text
#headline text("Let surgeons focus on surgery.") font_size(44) lh(1.08) s(fill,hug)
#hero fill($surface.card) rd($radius.lg) pad($space.lg)
#logo p(48,48) s(112,48)
#page:linkedin_square size(1080,1080,px) background(#0f172a)
#slot:campaign.headline placeholder("Let surgeons focus on surgery.")
```

### Node Modify Properties

Node targets should support the same safe visual properties used for creation:

- `name("...")`
- `p(x,y)`
- `s(width,height)`
- `fill(...)`
- `f[(...)]`
- `stroke(...)`
- `st[(...)]`
- `font("family",size,weight,align)`
- `font_size(...)`
- `font_weight(...)`
- `style($type.token)`
- `text("...")` or `content("...")`
- `lh(...)` / `line_height(...)`
- `ls(...)` / `letter_spacing(...)` / `tracking(...)`
- `max_lines(...)`
- `wrap_text(true|false)`
- `dir(ltr|rtl|auto)`
- `asset(asset_id)`
- `path("...")`
- `source(node_id)`
- `rd(...)`
- `o(...)`
- `rot(...)`
- `sk(...)`
- `flip(...)`
- `clip(...)`
- `gap(...)`
- `pad(...)`
- `x(...)`
- `y(...)`
- `wrap(true|false)`
- `grow(...)`
- `locked(true|false)` if edit authority allows it

Each property lowers into the narrowest possible `NodePatch`.

#### Explicit typography token intent

`NodePatch.explicit_text_tokens` is an optional mask of `style`, `font_size`,
`line_height`, and `letter_spacing` booleans. It accompanies a text-kind update
and records which token channels the author deliberately set or cleared.
Reapplying the same token is explicit: changing a raw size from a skeleton value
to a resolved value must not detach an intentionally reapplied size token.

Sparse `TextEditPatch` lowering carries `Set`/`Clear` intent into this mask.
Declarative reconcile carries the full intended text state, and the active
retokenizer marks the bindings it creates. Inverse operations retain the mask
when restoring the captured text state. The mask is absent from legacy/raw
inspector updates: copied tokens still detach when their numeric channel changes,
so a person's raw font-size edit survives later brand resolution. Content-only
edits preserve bindings. This is additive operation metadata, not a scene schema
revision or a new token-resolution mode.

The runtime and saved-ledger paths must resolve to the same typography even
when only the runtime working copy has passed through preflight. Preflight still
consumes role and size bindings together in its resolved output; producers must
not depend on token-string inequality against that transient state to express
authoring intent.

### Text Replacement

Text replacement is a core Phase D requirement because visual critique often
requires copy edits without changing layout.

Supported forms:

```text
#headline text("New copy")
#headline content("New copy")
#headline append(" - now with call routing")
#headline prepend("For neurosurgery teams: ")
```

V0 should implement `text(...)` and `content(...)`. `append` and `prepend` are
optional but useful for agent repair and should be planned as a second slice if
they would complicate parser behavior.

Text parsing must reject literal unescaped newlines inside quoted content with
a precise diagnostic and repair hint.

### Page Modify Properties

Page targets should support:

```text
#page:linkedin_square name("LinkedIn Square Ad")
#page:linkedin_square size(1080,1080,px)
#page:mailer safe_area(24,24,1032,1032)
#page:mailer bleed(0,0,0,0)
#page:linkedin_square background(#0f172a)
```

These lower to `Operation::UpdatePage`.

### Slot Modify Properties

Slot targets should support metadata repair without touching bound text nodes:

```text
#slot:campaign.headline required(true)
#slot:campaign.headline placeholder("Let surgeons focus on surgery.")
#slot:campaign.headline sample("Let Dr. Sharma focus on surgery.")
#slot:campaign.headline overflow(shrink)
#slot:account.logo bind(logo_node)
#slot:account.logo unbind(old_logo_node)
```

V0 should implement the common metadata and binding operations that already
map cleanly to existing slot operations. Rich runtime behavior such as
conditionals and repeaters remains later ABM runtime work.

### Asset Modify Properties

Asset target mutation should stay metadata-only until Phase E asset runtime:

```text
#asset:asset_logo label("Insight Health logo")
#logo asset(asset_logo)
```

Replacing a node's image source is a node modify operation. Uploading or
generating a new asset remains outside Phase D.

## Directive Semantics

### `delete(...)`

Existing `delete(node_id)` should become a safe delete surface.

Rules:

- Reject missing targets.
- Reject page root deletion through node delete syntax.
- Reject locked nodes unless authority permits.
- Recursively remove descendants.
- Remove slot bindings for deleted descendants.
- Remove or report orphaned references.
- Keep operation application atomic.

Recommended syntax:

```text
delete(logo)
delete(footer_note, if_exists)
```

`if_exists` is optional. If supported, it should emit no operation and an info
diagnostic when the target does not exist. Default behavior should remain strict.

### `parent(...)`

Current `parent(node_id,parent_id,index)` should be expanded to support
explicit relative anchors:

```text
parent(logo, hero, index:0)
parent(logo, page:linkedin_square, index:2)
parent(logo, hero, before:headline)
parent(logo, hero, after:brand_mark)
```

Rules:

- Reject self-parenting.
- Reject descendant parenting cycles.
- Reject leaf parents.
- Resolve `before` and `after` inside the destination parent.
- Keep insertion indexes stable after detach when moving within one parent.
- Recompute parser/session parent stack after successful reparent.

### `before(...)` and `after(...)`

These are reorder/move convenience directives:

```text
before(cta, disclaimer)
after(logo, headline)
before(feature_2, feature_1, parent:feature_grid)
after(feature_3, feature_2, parent:feature_grid)
```

Semantics:

- If no parent is supplied, the target moves within the anchor's current parent.
- If a parent is supplied, target moves into that parent relative to the anchor.
- `before` inserts at the anchor index.
- `after` inserts at anchor index + 1.
- Target and anchor must not be the same node.
- Destination must be page or container node.
- The lowering output is `Operation::MoveNode`.

### `replace(...)`

Phase D needs both content replacement and structural replacement.

Use modify lines for simple replacement:

```text
#headline text("New headline")
#logo asset(asset_logo_alt)
```

Use `replace(...)` for subtree replacement:

```text
replace(hero_visual, with:hero_visual_v2)
```

Recommended V0 behavior:

1. `with:existing_node_id` moves an existing replacement subtree into the
   target's old parent/index, then deletes the old target.
2. Slot bindings can be preserved when the replacement is compatible:

   ```text
   replace(headline, with:headline_v2, slots:preserve)
   replace(card_1, with:card_1_v2, slots:detach)
   ```

3. Unsupported block replacement syntax should parse as a clear future
   diagnostic until implemented.

Recommended future block syntax:

```text
replace(hero_card)
  hero_card fr p(40,40) s(1000,hug) fill($surface.card) rd($radius.lg)
    headline text("New headline") s(fill,hug) style($type.headline)
```

Block replace is more expressive, but it touches parser context, ID policy,
slot preservation, and operation batching. It should be implemented only after
V0 replacement semantics are tested.

### `clone(...)`

Clone is needed for repeated structures such as feature cards, testimonial
blocks, product tiles, and ABM proof-point lists.

Recommended syntax:

```text
clone(feature_card, as:feature_card_2, after:feature_card)
clone(testimonial_card, as:testimonial_card_3, parent:testimonial_grid, index:2)
clone(feature_card, as:feature_card_2, slots:detach)
clone(feature_card, as:feature_card_2, slots:suffix("_2"))
```

Semantics:

- Deep-copy the source subtree.
- Generate deterministic new IDs from the requested root ID and child ID map.
- Reject collisions before applying operations.
- Insert the cloned root at the requested parent/index.
- Preserve visual properties, layout props, computed fields policy, fills,
  strokes, text, asset refs, and metadata.
- Default computed geometry policy should be `clear`, because layout/preflight
  should recompute clone geometry.
- Slot copy policy must be explicit:
  - `slots:detach`: no slot bindings copied.
  - `slots:copy`: bind cloned nodes to the same slots.
  - `slots:suffix("_2")`: create derived slots for cloned nodes.
- Default should be `detach` unless the user/agent explicitly asks to repeat a
  personalization slot.

Lowering can expand to `InsertNode` plus slot/asset operations rather than a
  first-class `CloneNode` operation, but the patch report should preserve the
  clone intent for trace/debug.

### `override(...)`

Override is the bridge between clone/component semantics and targeted patches.

Recommended syntax:

```text
override(feature_card_2)
  #feature_card_2_title text("Handles urgent scheduling calls")
  #feature_card_2_icon asset(asset_phone_icon)
```

V0 can treat override as a named patch group around normal modify lines. Full
component-instance override semantics should wait until the component model is
stable.

### `ungroup(...)`

Ungroup is useful but not required for the first Phase D product win.

Recommended semantics:

- Move children to the group's parent at the group's index.
- Preserve child order.
- Delete the now-empty group.
- Reject ungrouping non-container nodes.
- Reject ungrouping layout containers unless explicitly allowed, because it can
  destroy layout semantics.

### Checkpoints, Undo, And Redo

Checkpoints should become operation-history anchors, not scene nodes.

Existing DSL checkpoint syntax:

```text
// hero spacing fix
```

Recommended persisted metadata:

```rust
pub struct EditCheckpoint {
    pub label: String,
    pub scene_revision: u64,
    pub operation_index: usize,
    pub timestamp_ms: u64,
}
```

Undo/redo should be implemented after modify, move, replace, and clone
semantics stabilize.

V0 undo/redo recommendation:

- Keep undo/redo as editor/agent session actions over snapshots or inverse
  batches.
- Do not encode undo as a scene mutation operation.
- Persist checkpoint labels with operation batches in API/agent traces.
- Reject `undo(...)` and `redo(...)` in pure `compile_dsl` unless a history
  context is supplied.

Decided model (2026-06-12, see Post-V0 Decisions 0–2): document-level linear
undo/redo over persisted edit-batch envelopes. Each applied batch stores its
inverse operations, computed at apply time. Undo appends a new envelope that
applies the stored inverse; redo re-applies the original operations as a new
envelope; the history log is append-only, with mutable undo/redo cursors kept
as separate bookkeeping. Revert-to-checkpoint composes the inverses of every
batch after the anchor, newest first, into one envelope. Batches containing
`FinalizeTemplate` are not invertible and reject undo with a diagnostic.

Future syntax:

```text
undo("hero spacing fix")
redo("hero spacing fix")
```

## Structured Operation Patch Tool

Agents should not rely only on indentation-sensitive DSL for targeted repair.
Phase D should add a structured patch DTO that can be produced by the visual
critic/repair planner and converted into canonical operations.

Recommended request:

```json
{
  "schema_version": 1,
  "scene_revision": 12,
  "intent": "repair_text_overflow",
  "target": { "kind": "node", "id": "headline" },
  "edits": [
    { "kind": "set_text", "value": "Let surgeons focus on surgery." },
    { "kind": "set_text_style", "font_size": 44, "line_height": 1.08 },
    { "kind": "set_size", "width": "fill", "height": "hug" }
  ],
  "preconditions": [
    { "kind": "target_exists", "target": "headline" },
    { "kind": "node_kind", "target": "headline", "expected": "text" }
  ],
  "expected_effect": "headline text fits inside hero content column"
}
```

Recommended response:

```json
{
  "status": "applied",
  "operation_count": 3,
  "operations": [],
  "diagnostics": [],
  "touched_targets": [
    { "kind": "node", "id": "headline" }
  ],
  "preserved_targets": [
    { "kind": "page", "id": "linkedin_square" }
  ],
  "checkpoint": "repair headline overflow"
}
```

Structured edit kinds:

- `set_text`
- `set_node_name`
- `set_transform`
- `set_size`
- `set_fill`
- `set_stroke`
- `set_corner_radius`
- `set_opacity`
- `set_text_style`
- `set_layout`
- `set_asset`
- `move_before`
- `move_after`
- `move_to_parent`
- `delete_node`
- `replace_node`
- `clone_subtree`
- `bind_slot`
- `unbind_slot`
- `update_slot`
- `update_page`
- `update_export_profile`

The structured tool should produce the same canonical operations as DSL
lowering. The only difference is authoring surface.

## Operation Builder Layer

To avoid duplicate semantics, Phase D should add shared operation builders.

Recommended module:

```text
crates/lumen-core/src/editing.rs
```

Responsibilities:

- target resolution
- property patch conversion
- move index computation
- subtree clone ID remapping
- replace batch construction
- delete safety checks
- patch precondition validation
- patch reports and touched-target summaries

The DSL compiler, agent tools, API helper, and editor adapter should call these
builders rather than reimplementing target math in separate places.

Recommended public entry points:

```rust
pub fn resolve_edit_target(scene: &Scene, target: &EditTargetRef)
    -> Result<ResolvedEditTarget, EditError>;

pub fn build_modify_operations(scene: &Scene, target: EditTargetRef, patch: EditPatch)
    -> Result<EditBatch, EditError>;

pub fn build_move_before(scene: &Scene, node_id: NodeId, anchor_id: NodeId)
    -> Result<EditBatch, EditError>;

pub fn build_move_after(scene: &Scene, node_id: NodeId, anchor_id: NodeId)
    -> Result<EditBatch, EditError>;

pub fn build_replace_node(scene: &Scene, request: ReplaceNodeRequest)
    -> Result<EditBatch, EditError>;

pub fn build_clone_subtree(scene: &Scene, request: CloneSubtreeRequest)
    -> Result<EditBatch, EditError>;
```

`EditBatch` should include metadata but apply through normal operations:

```rust
pub struct EditBatch {
    pub operations: Vec<Operation>,
    pub touched_targets: Vec<EditTargetRef>,
    pub checkpoint_label: Option<String>,
    pub intent: Option<String>,
}
```

## Agent Repair Protocol

Phase D should update the agent loop so visual critic feedback becomes targeted
patches.

Recommended flow:

```text
critic issue
  -> target resolver
  -> edit-surface recommendation
  -> structured patch or modify DSL
  -> checked operation batch
  -> preflight
  -> export preview
  -> visual critique
```

Rules:

- If the critic names a concrete node/page/slot, prefer structured patch or
  modify DSL over whole-page DSL.
- If the critic requires a new section or major composition change, allow a
  small DSL creation block plus targeted patch.
- If no target can be resolved, ask the read/query tool for a page/node summary
  before regenerating.
- The repair prompt must include the exact target IDs and allowed edit surface.
- The repair result must state which targets it touched.
- The loop must fail closed if a repair modifies unrelated pages/nodes outside
  its declared target scope.

## Editor Integration

Phase F already added many editor operations. Phase D should unify those with
agent patch semantics.

Editor requirements:

- Inspector updates use shared operation builders where possible.
- Layer reorder uses the same `before`/`after` index math as DSL lowering.
- Delete shortcut uses safe delete.
- Duplicate/clone action uses `clone_subtree`.
- Replace image action uses `set_asset` or `replace_node`, not local state.
- Undo/redo history can adopt checkpoint labels from edit batches.
- Operation history UI should show batch intent, not only raw low-level
  operations.

## API And Persistence Integration

The API should expose a patch endpoint or helper action without redefining
semantics.

Recommended route:

```text
POST /documents/{document_id}/patches
```

Request:

```json
{
  "schema_version": 1,
  "base_version": 12,
  "patch": {},
  "actor": "agent",
  "source": "visual_repair",
  "checkpoint": "repair headline overflow"
}
```

Behavior:

- load canonical scene
- build canonical operations through Rust helper
- apply checked operations atomically
- persist the edit envelope as the history unit: intent, checkpoint label,
  actor, source, touched targets, base revision, canonical operations, and
  inverse operations (replay reads operations only)
- persist diagnostics
- return compact document summary and touched-target summary

If this route is too large for Phase D, the `lumen-api-helper` action should be
implemented first so Python/agent code can still call Rust semantics.

## Diagnostics And Safety

Phase D should add diagnostics that are useful to an LLM repair loop:

- target not found
- unsupported target type
- unsupported property for target kind
- incompatible replacement node kind
- clone ID collision
- replace would orphan slot binding
- move would create cycle
- move anchor missing
- delete target locked
- delete target has protected slot
- patch touched undeclared target
- base scene revision mismatch

Every diagnostic should include:

- severity
- stable code
- target if known
- concise message
- repair hint
- source DSL line when applicable

## Testing Strategy

Phase D should be test-driven. Add failing tests first.

### Core Operation Builder Tests

- resolve node/page/slot/asset/export targets.
- reject missing and ambiguous targets.
- build `UpdateNode` for text/style/size/fill/layout patches.
- build `UpdatePage` for custom page size and background patches.
- compute `before`/`after` indexes correctly when moving within one parent.
- reject cycles and leaf parents.
- safe delete removes descendants and slot bindings.
- clone deep-copies subtree and clears computed geometry.
- clone rejects ID collisions before mutation.
- clone slot policies behave as specified.
- replace preserves parent/index and applies atomically.
- replace slot policy is explicit.

### DSL Compiler Tests

- `#headline text("...")` lowers to `UpdateNode`.
- `#page:ad size(1080,1080,px)` lowers to `UpdatePage`.
- `#slot:campaign.headline placeholder("...")` lowers to `UpsertSlot`.
- unsupported properties halt at one line.
- valid modify lines before a later halt remain applied.
- `before`, `after`, richer `parent`, and safe `delete` lower correctly.
- malformed target refs emit target diagnostics.
- locked target edits halt.
- clone and replace syntax emits either operations or explicit future
  diagnostics according to the implemented slice.
- `DslCompileSession` preserves context across create and modify blocks.

### Agent Runtime Tests

- visual issue with target node produces structured patch request.
- structured patch applies without re-emitting page IDs.
- patch failure is persisted with diagnostics.
- repair cannot modify undeclared unrelated nodes in strict mode.
- successful repair records touched targets and checkpoint label.

### Editor Tests

- layer reorder and DSL `before`/`after` produce equivalent operation batches.
- delete shortcut and DSL `delete` produce equivalent scene effects.
- duplicate action and clone builder preserve expected subtree fields.
- undo/redo frame labels can use checkpoint metadata.

### Conformance Fixtures

Create representative scenes:

- square LinkedIn ad with overflowing headline
- feature-card list needing clone/reorder
- logo/image replacement
- auto-layout CTA section needing text/style resize
- multi-page document where repair must touch only one page
- slot-bound headline replacement

Each fixture should prove:

- requested target changed
- unrelated targets preserved
- preflight/export still run after patch
- operation history is replayable

## Implementation Milestones

### D0. Planning, Fixtures, And Test Baseline

- Add this spec.
- Restore the product gap analysis reference doc on the Phase D branch if it is
  missing from `main`.
- Add Phase D memory file.
- Add failing fixtures and test names before implementation.

### D1. Target Resolution And Edit Batch Model

- Add `editing.rs`.
- Add `EditTargetRef`, `ResolvedEditTarget`, `EditPatch`, `EditBatch`,
  `EditError`.
- Implement target resolution.
- Add touched-target reporting.

### D2. Modify-Line Lowering For Node/Page Basics

- Lower `#node ...` visual/text/layout properties to `UpdateNode`.
- Lower `#page:...` properties to `UpdatePage`.
- Preserve cascade halt and partial valid operations.
- Add diagnostics for unsupported target/property combinations.

### D3. Slot And Asset Target Patches

- Lower slot metadata and bind/unbind edits.
- Lower asset metadata-only edits.
- Lower node asset replacement via `#image asset(asset_id)`.

### D4. Reorder, Rich Parent, And Safe Delete

- Lower `before(...)`.
- Lower `after(...)`.
- Expand `parent(...)` with relative anchors.
- Harden `delete(...)` through shared safe-delete rules.

### D5. Structured Agent Patch Tool

- Add Rust helper action for structured patches.
- Add Python DTOs and agent tool wrappers.
- Route targeted critic repairs through structured patch before DSL fallback.
- Persist touched-target and checkpoint metadata in traces.

### D6. Clone And Replace Semantics

- Implement clone subtree builder with deterministic ID map.
- Implement replace by existing subtree and policy flags.
- Add explicit diagnostics for unsupported block replace until implemented.
- Add override patch-group semantics if the base clone/replace model is stable.

### D7. Checkpoints And Undo/Redo

- Persist checkpoint labels with edit batches.
- Support history-context undo/redo in agent/editor sessions.
- Keep pure `compile_dsl` strict when no history context is available.

### D8. Editor/API Unification

- Refactor editor reorder/delete/duplicate/replace image helpers to use shared
  semantics where available.
- Add API patch route or helper-backed equivalent.
- Ensure operation logs retain patch metadata.

### D9. Conformance And Product Review

- Run native Rust tests.
- Run wasm check.
- Run API tests.
- Run editor tests/build.
- Run visual/export regression scenarios.
- Run at least one live or deterministic agent repair trace proving no
  duplicate-page regeneration occurs for a targeted repair.

## Acceptance Criteria

Phase D is ready when:

1. Agents can update a target node's text/style/size without re-creating the
   page.
2. Agents can reorder nodes with `before`/`after`.
3. Agents can safely delete a node and preserve scene validity.
4. Agents can replace an image asset on an existing image/logo node.
5. Agents can apply structured patch DTOs through Rust checked semantics.
6. Editor actions and agent patch actions produce equivalent operation effects.
7. Visual repair traces record target, patch, operations, diagnostics, preview,
   critique, and acceptance outcome.
8. Operation history remains canonical and replayable.
9. Tests prove unrelated pages/nodes/slots are preserved.
10. Unsupported advanced syntax fails with clear diagnostics rather than being
    ignored or causing full-regeneration fallback.

## Open Decisions (Resolved 2026-06-12)

All five decisions are resolved. The first four are implemented in V0; the
fifth ships as a V1 slice.

1. Should `CloneNode` and `ReplaceNode` become first-class core `Operation`
   variants?

   Decision: no. Clone and replace expand into existing canonical operations,
   with high-level intent preserved in `EditBatch` metadata and, after V1
   envelope persistence, in stored history envelopes. Revisit only if
   replay/audit tooling proves the expansion insufficient.

2. Should block replace syntax be implemented in Phase D V0?

   Decision: not in V0. Existing-node replace shipped first. Inline block
   replace is scheduled as a V1 slice now that V0 replacement semantics are
   tested. See `phase-d-v1-implementation-plan.md` slice V1.10.

3. Should undo/redo be available in pure DSL compilation?

   Decision: no. `undo(...)`/`redo(...)` lower only when a history adapter is
   supplied (V1.5). Pure `compile_dsl` emits a precise diagnostic.

4. Should clone copy slot bindings by default?

   Decision: no. Default is `slots:detach`; duplicated ABM personalization
   bindings must be explicit through `slots:copy` or `slots:suffix(...)`.
   Implemented in V0.

5. How strict should targeted repair scope enforcement be?

   Decision: strict fail-closed for agent repairs, advisory warnings for
   direct human editor edits. Agent repairs declare allowed targets and the
   whole batch is rejected before mutation if it touches targets outside the
   declared closure. Ships as V1.3.

## V0 Implemented Contract

As of the Phase D V0 implementation, the product-supported targeted edit
surface is:

- Shared Rust edit builders in `crates/lumen-core/src/editing.rs`.
- Sparse edit patch DTOs. Callers may send only the fields they want to
  change; missing fields default to `unchanged`.
- DSL modify-line lowering for:
  - `#node_id ...`
  - `#page:page_id ...`
  - `#slot:key.path ...`
  - `#slot_id:slot_id ...`
  - `#asset:asset_id ...`
- DSL directive lowering for:
  - `delete(node_id)`
  - `parent(node_id,parent_id[,index])`
  - `parent(node_id,page:page_id[,index])`
  - `before(node_id,anchor_id)`
  - `after(node_id,anchor_id)`
  - `clone(source_id,new_root_id,after:anchor_id[,slots:detach|copy|suffix:_x][,computed:clear|preserve])`
  - `clone(source_id,new_root_id,before:anchor_id[,slots:...][,computed:...])`
  - `clone(source_id,new_root_id,parent:page:page_id[,index:N][,slots:...][,computed:...])`
  - `clone(source_id,new_root_id,parent:node_id[,index:N][,slots:...][,computed:...])`
  - `replace(target_id,replacement_id[,slots:detach|preserve])`
- Helper action `apply_structured_edit`.
- FastAPI route `POST /documents/{document_id}/edits`.
- DeepAgent runtime tool `apply_structured_edit`.

The structured edit helper accepts:

```json
{
  "action": "apply_structured_edit",
  "scene": {},
  "edit": {
    "kind": "modify",
    "target": { "kind": "node", "id": "headline" },
    "patch": {
      "kind": "node",
      "value": {
        "text": {
          "content": { "kind": "set", "value": "A tighter headline" },
          "font_size": { "kind": "set", "value": 44 }
        }
      }
    }
  }
}
```

Successful helper/API responses return the updated scene, the exact canonical
operations that were applied, and edit metadata including touched targets. In
V0, API persistence stored only the canonical operations in operation history.
V1 supersedes this: history persists the full edit envelope around the
canonical operations (see Post-V0 Decision 0); replay still reads only the
operations.

Still deferred after V0 (every item is scheduled in
`docs/phase-d-v1-implementation-plan.md`; slice numbers in parentheses):

- `#document` and `#export:name` modify lowering. (V1.6)
- Safe delete for pages, slots, assets, and export profiles. (V1.7)
- `ungroup` and `override` lowering. (V1.9)
- `undo` and `redo` lowering with a history adapter. (V1.5)
- History-aware checkpoint execution. (V1.4)
- Inline block replace. (V1.10)
- Strict agent target-scope enforcement. (V1.3)
- A frontend TypeScript structured-edit DTO wrapper. The current editor already
  emits canonical operations for direct manipulation and inspector controls.
  (V1.11)

## Post-V0 Decisions (Resolved 2026-06-12)

The deferred items are still part of the broader Phase D product scope. They
were not implemented in V0 because the branch first established the shared edit
foundation: typed targets, sparse patches, checked edit batches, DSL modify
lowering, structured API/tooling, and basic move/delete/clone/replace
semantics.

All product/architecture decisions blocking the remaining scope were resolved
on 2026-06-12. Every item below is scheduled in
`docs/phase-d-v1-implementation-plan.md`. The records keep the rationale and
the rejected alternatives so future work does not re-litigate them.

### Decision 0: Persist The Edit-Batch Envelope In History

Decision: operation history persists the full edit envelope per batch —
intent, checkpoint label, actor, source, touched targets, base revision, the
canonical operations, and the inverse operation batch computed at apply time.
Replay continues to read only the canonical operations, so `Scene` remains
canonical state and `Operation` remains the sole mutation/replay surface.

Why: without stored batch boundaries and metadata there is no document-level
undo, no checkpoint anchors, no batch-grouped history UI, and no audit answer
to "why did this change". Envelope data cannot be backfilled: every batch
persisted without an envelope is permanently anonymous. Inverses are captured
at apply time because the pre-state scene is in hand then (the inverse of
`RemoveNode` needs the removed subtree — free at apply time, expensive later).

Alternatives rejected: operations-only storage (the V0 status quo; loses
intent and inverses forever), envelope-as-source-of-truth with derived
operations (re-derivation drift; operations would no longer be literal
history).

### Decision 1: Undo/Redo Model

Decision: document-level linear undo/redo implemented as inverse-batch
append. Undo applies the stored inverse batch as a new history envelope
(revert semantics, like `git revert`); history is never truncated or
rewritten. Snapshots remain performance/integrity anchors, not the undo
mechanism. The editor keeps a local optimistic undo stack for uncommitted
gestures and reconciles to document history on save. Pure `compile_dsl`
continues to reject `undo`/`redo` without a history adapter. Batches
containing non-invertible operations (`FinalizeTemplate`) are not undoable
and produce a precise diagnostic.

Why: Lumen history backs template revisions, audit, and replay. Brilliant can
rewind canvas state because it is a local-first desktop file tool; Lumen
history is shared product data, and truncation would break exactly the
guarantees the ABM lifecycle depends on.

Alternatives rejected: snapshot-restore (truncates or forks history),
event-sourced time travel (unbounded replay cost; the act of reverting is
never itself recorded), branching history (collaboration-era complexity).

### Decision 2: Checkpoints

Decision: checkpoints are named operation-history anchors recorded on batch
envelopes and surfaced in editor and agent history. They are not approval
states; approval remains exclusively the template-revision lifecycle. The
agent's `// label` narration comment becomes the checkpoint label of the next
batch, so narration, undo anchor, and trace label are one artifact.

### Decision 3: Page Delete

Decision: deleting the last page is forbidden. Page delete cascades node
deletion and unbinds slots bound to deleted nodes, but keeps the slot
definitions so preflight/finalization flags newly unbound required slots —
the personalization contract must shrink visibly, never silently. Active-page
selection is editor state, not core semantics. In strict agent mode page
deletion must be an explicitly targeted directive, never a side effect of a
node-level repair.

### Decision 4: Slot Delete

Decision: hard delete allowed in drafts; finalized revisions are immutable
(edits require a new revision). Deleting a slot unbinds nodes and never
deletes nodes. Slot removals are recorded with intent in the envelope so
Phase G can compute revision-compatibility diffs later without Phase D
building that checker now. Document-level undo makes draft hard-deletes
recoverable, which removes the need for slot archival machinery.

### Decision 5: Asset Delete

Decision: archive-first. Phase D implements the archive status and a
reference check that rejects hard delete while the asset is referenced by any
node, slot, or finalized revision. Byte storage lifecycle, GC, and library
semantics remain Phase E scope; building them in Phase D would be
speculative.

### Decision 6: Export Profile Delete

Decision: deleting the default/active export profile requires a named
replacement profile. Profiles referenced by finalized revisions follow the
same immutability rule as slots (new revision required). With lifecycle rules
decided, `#export:name` modify lowering and profile delete ship together in
V1.

### Decision 7: Override Semantics

Decision: `override(...)` is a patch group over cloned subtrees, validating
that every inner modify target is a descendant of the override root. True
component master/instance semantics wait for a component model. Clone lineage
(source root plus the deterministic ID map V0 already computes) is persisted
in the envelope so a future component model can be retrofitted without
archaeology. Patch-group override is not a stopgap: clone-per-item plus
per-item override is the intended Phase G repeater mechanic.

### Decision 8: Editor Edit Surface

Decision: backend `POST /documents/{document_id}/edits` is the authority for
committed editor edits. TypeScript helpers survive only as optimistic
preview. Cross-language parity fixtures — the same fixture scene plus the
same edit must produce identical operation batches from the Rust builders and
the TS helpers — are asserted in CI. WASM-in-browser (`lumen-wasm`) remains
the convergence target but is not a Phase D gate; the parity fixtures
neutralize the divergence risk until then.

### Contract Boundaries (Owned Elsewhere, Not Deferred)

With the decisions above, the only Phase D items that wait on other contracts
are these. Each is an explicit boundary with an owner, not an open question:

| Feature | Owning contract |
| --- | --- |
| True component `override` | Future component/master/instance workstream. Clone lineage metadata is persisted now (Decision 7) so it can be retrofitted. |
| Asset byte lifecycle, storage GC, library semantics | Phase E asset runtime. Phase D ships archive status plus reference checks only (Decision 5). |
| ABM runtime binding, conditionals, repeater execution | Phase G personalization runtime. Phase D delivers the clone/override primitive it consumes. |
| Print-grade text shaping and export fidelity | Export/print-fidelity workstream. |
| WASM editor core | `spike/wasm-browser-core` follow-up after parity fixtures land (Decision 8). |

### V1 Scope And Sequencing

The complete V1 scope — slice ordering, types, diagnostics, tests, and
acceptance gates — lives in `docs/phase-d-v1-implementation-plan.md`.
Everything in Phase D's charter is scheduled there to completion, including
history-aware undo/redo and checkpoints (unblocked by Decisions 0–2), all
lifecycle deletes, `#document`/`#export` lowering, `ungroup`, patch-group
`override`, inline block replace, strict agent scope enforcement, and full
editor unification. Nothing in the charter remains unowned.

## V1 Final Status (2026-06-12)

Phase D is complete. Every "Not done"/"Partial" row in the V0 coverage
matrix above shipped in V1 (commits `faa411e`..`a600472` on
`phase-d/targeted-editing-repair-semantics-v1`):

- Inverse operation batches and clone lineage on `EditBatch`; round-trip
  identity property-tested for every builder.
- Envelope-persisted history (intent, checkpoint, actor, touched targets,
  base revision, operations, inverses) with version-0 backfill; replay
  reads operations only.
- Document-level linear undo/redo as inverse-batch append, checkpoint
  anchors, and revert-to-checkpoint (`POST /undo`, `/redo`, `/revert`,
  `GET /history`, `/checkpoints`).
- Strict agent target-scope enforcement, fail-closed pre-mutation, with
  in_scope/rejected verdicts persisted to agent traces.
- `#document` and `#export:name` modify lowering; DSL `// label`
  checkpoint capture threaded into envelopes and traces.
- Lifecycle safe deletes for pages, slots, assets (archive-first), and
  export profiles per Decisions 3-6, all undoable.
- `append`/`prepend`, `delete(..., if_exists)`, `parent` relative anchors;
  locked-target authority is the recorded unlock-as-edit model (supersedes
  the bypass-flag design - strictly more auditable).
- `ungroup` (auto-layout protected behind `allow_layout`), `override`
  patch groups with containment enforcement, and history-adapter
  `undo("label")`/`redo` lowering (`DslHistoryAdapter`).
- Inline block replace with whole-directive atomic rollback - the last
  unimplemented spec syntax.
- Editor adoption: TypeScript structured-edit wrapper, `/edits` client
  with scope/base_version/checkpoint, envelope HistoryPanel, and the
  cross-language parity fixtures (`fixtures/edit-parity/cases.json`)
  asserted byte-for-byte from Rust and Vitest in CI.

Verification: 274 Rust, 71 Python, and 175 TypeScript tests pass; fmt,
clippy (-D warnings), wasm32 check, and the editor build are clean. The
deterministic agent repair proof is the scoped structured-edit trace
tests: a critic-targeted repair applies through `apply_structured_edit`
with an in_scope verdict and no page regeneration, and the out-of-scope
variant is rejected before mutation with the scene unchanged.
