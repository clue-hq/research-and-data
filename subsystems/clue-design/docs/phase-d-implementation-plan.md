# Phase D Implementation Plan

## Objective

Implement Phase D's targeted editing and repair semantics in a way that is
usable by agents, the editor, and API workflows without weakening the core
architecture.

The desired product behavior is:

```text
critic/user finds a concrete issue
  -> agent/editor identifies exact target
  -> target edit becomes a checked operation batch
  -> preflight/export/critic run again
  -> unrelated scene regions are preserved
```

The implementation must make full-page regeneration the fallback, not the
default repair strategy.

## Architectural Reading Of The Phase D Spec

Phase D is not "more DSL syntax" in isolation. It is a shared edit semantics
layer with multiple authoring surfaces:

- Lumen DSL modify lines: compact model-facing repair syntax.
- Structured patch DTOs: safer agent/API repair syntax.
- Editor controls: human-facing repair syntax.
- Canonical `Operation` batches: the only mutation/history surface.

This mirrors Brilliant's core insight: the agent and human editor should be
peers over the same design tree. Brilliant exposes this through Blueprint
modify lines and directives. Lumen should expose it through a typed edit layer
that lowers into `Operation`, because Lumen's source of truth is `Scene`, not
DSL text.

## Implementation Principles

1. **Build shared edit semantics first.**
   Do not put target/index/subtree logic directly in the DSL compiler, Python
   agent runtime, API route, or React editor. Add a core edit builder module and
   reuse it from every surface.

2. **Prefer operation expansion over new operation variants for V0.**
   `clone` and `replace` should initially produce normal `InsertNode`,
   `MoveNode`, `UpdateNode`, `RemoveNode`, slot, and asset operations. Preserve
   high-level intent in `EditBatch` metadata. Add first-class operation variants
   only if replay/audit/user history proves the low-level expansion inadequate.

3. **Targeted edits must be strict.**
   Missing targets, unsupported properties, locked targets, clone ID collisions,
   and undeclared target touches must fail before mutation.

4. **Computed geometry is generated, not hand-authored.**
   Authoring edits to transform, size, layout, text, fills/strokes, or asset
   placement should clear stale `computed` where appropriate and let preflight
   recompute.

5. **Agent repairs need scope enforcement.**
   A visual issue targeting `headline` should not silently rewrite the whole
   page. The repair loop should know touched targets and reject unrelated
   mutations in strict mode.

6. **Editor behavior should converge onto the same builders.**
   Phase F already has editor operation helpers. Phase D should unify their
   semantics with agent and DSL repair rather than inventing a second editor
   mutation model.

## Current Codebase Anchors

Relevant existing files:

- `crates/lumen-core/src/operations.rs`
  Existing canonical operations and patch structs.

- `crates/lumen-core/src/dsl.rs`
  Existing parser, `DslCompileSession`, parsed modify lines, parsed but
  unlowered directives.

- `crates/lumen-core/src/scene.rs`
  Canonical page, node, slot, asset, computed geometry, and page-size models.

- `crates/lumen-core/src/validation.rs`
  Structural validation that operation batches must preserve.

- `crates/lumen-core/tests/dsl_compiler.rs`
  DSL cascade halt, directives, page size, token, and text syntax tests.

- `crates/lumen-core/tests/core_engine.rs`
  Operation applier tests.

- `apps/agent_runtime/lumen_deepagent/*`
  Agent quality loop, repair request, trace persistence, edit-surface
  recommendation.

- `crates/lumen-api-helper/src/main.rs`
  Cross-language bridge used by Python/API/agent runtime.

- `apps/api/lumen_api/main.py`
  Persistence/API routes and helper integration.

- `apps/editor/src/engine/operations.ts`
  TypeScript operation helpers.

- `apps/editor/src/components/EditorApp.tsx`
  Editor gesture and history application.

## Deliverables

Phase D should leave behind:

1. `crates/lumen-core/src/editing.rs`
   Shared edit target, patch, directive, clone, replace, and edit-batch
   builders.

2. Core tests for target resolution, patch building, move index math, safe
   delete, clone, replace, and preservation.

3. DSL lowering for target modify lines and stable edit directives.

4. Agent structured patch DTOs and runtime tool wrappers.

5. Helper/API path for checked structured patches.

6. Editor operation helpers aligned with shared semantics.

7. Conformance fixtures proving targeted repairs preserve unrelated scene
   regions.

8. Documentation and memory updates capturing the final edit contract.

## Implementation Slices

### D0. Baseline Audit And Failing Fixtures

Purpose: establish evidence before code changes.

Tasks:

- Add `crates/lumen-core/tests/editing.rs` with failing tests for the shared
  edit layer.
- Add fixture builders for:
  - square ad with headline/body/logo/CTA.
  - auto-layout feature-card list.
  - slot-bound headline and logo.
  - multi-page document where only one page may be touched.
  - image node backed by `AssetRecord`.
- Add one DSL fixture for modify repair:

  ```text
  page linkedin_square size(1080,1080,px)
    hero fr p(40,40) s(1000,hug)
      headline text "Bad oversized text" p(0,0) s(fill,hug) font("Inter",72,800,left)

  #headline text("Let surgeons focus on surgery.") font_size(44) lh(1.08) s(fill,hug)
  ```

- Add initial ignored or failing tests for:
  - target resolution.
  - `#headline text(...)` lowering.
  - `before(cta, disclaimer)` lowering.
  - safe delete clearing slot bindings.
  - clone subtree clearing computed geometry.
  - structured patch DTO target preservation.

Acceptance gate:

- Tests must fail for missing implementation, not because fixtures are invalid.
- No production code changes yet except test scaffolding and helper builders
  required for fixture creation.

### D1. Core Edit Target And Batch Model

Purpose: create the shared foundation every other surface uses.

Files:

- Add `crates/lumen-core/src/editing.rs`.
- Export it from `crates/lumen-core/src/lib.rs`.

Types:

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

pub struct ResolvedEditTarget { ... }

pub struct EditBatch {
    pub operations: Vec<Operation>,
    pub touched_targets: Vec<EditTargetRef>,
    pub checkpoint_label: Option<String>,
    pub intent: Option<String>,
}

pub enum EditErrorKind {
    TargetNotFound,
    AmbiguousTarget,
    UnsupportedTarget,
    UnsupportedProperty,
    LockedTarget,
    WouldCreateCycle,
    AnchorNotFound,
    IdCollision,
    IncompatibleReplacement,
    ProtectedSlot,
    RevisionMismatch,
}
```

Implementation:

- Resolve every target kind.
- Report target's page, parent, index, node kind, slot bindings.
- Add `EditBatch::checked_apply_to(scene)` or a helper that applies operations
  through existing checked operation application.
- Add target-diagnostic conversion to stable `Diagnostic` values.

Important design detail:

- Keep this module independent from DSL source spans. It should know edit
  semantics, not parser syntax.

Tests:

- resolve existing/missing nodes.
- resolve pages.
- resolve slots by ID and key.
- resolve assets.
- reject ambiguous or malformed target refs where applicable.
- touched-target metadata is deterministic.

Acceptance gate:

- `editing.rs` compiles on native and `wasm32-unknown-unknown`.
- No DSL or API behavior changes yet.

### D2. Node And Page Patch Builders

Purpose: make the most common repair actions work before directives/clone.

Core API:

```rust
pub enum EditPatch {
    Node(NodeEditPatch),
    Page(PageEditPatch),
    Document(DocumentEditPatch),
    Slot(SlotEditPatch),
    Asset(AssetEditPatch),
    ExportProfile(ExportProfileEditPatch),
}

pub fn build_modify_operations(
    scene: &Scene,
    target: EditTargetRef,
    patch: EditPatch,
) -> Result<EditBatch, EditError>;
```

Node patch fields:

- text content.
- name.
- transform.
- size.
- fills.
- strokes.
- corner.
- opacity.
- clip.
- text style fields.
- layout props.
- source asset and placement.
- locked state.

Page patch fields:

- name.
- custom size.
- safe area.
- bleed.
- background.

Implementation details:

- Convert patches into narrow `NodePatch` / `PagePatch`.
- Clear stale `computed` when the patch affects rendered geometry, layout, text,
  asset placement, or typography.
- For text patches, require target node kind `Text`.
- For image asset patches, require target kind `Image` or `Vector` if source
  semantics allow it.
- For layout patches, require container node and existing or new
  `AutoLayoutProps`.

Tests:

- set text only modifies text node kind.
- set text on rect is rejected.
- resize clears computed.
- style changes clear computed where appropriate.
- page size update preserves page children.
- page background update lowers to `UpdatePage`.

Acceptance gate:

- Core patch builders can update text/style/size/page size without DSL.

### D3. DSL Modify-Line Lowering

Purpose: turn the model-facing syntax into operation batches.

Files:

- `crates/lumen-core/src/dsl.rs`
- `crates/lumen-core/tests/dsl_compiler.rs`

Parser/semantic tasks:

- Convert `DslModification { target_ref, properties }` into `EditTargetRef`.
- Reuse existing `DslProperty` parsing.
- Add missing property parsing only when needed for target edits:
  - `text("...")`
  - `content("...")`
  - page `background(...)`
  - page `safe_area(...)`
  - page `bleed(...)`
  - slot `placeholder(...)`
  - slot `sample(...)`
  - slot `required(...)`
  - slot `bind(...)`
  - slot `unbind(...)`
- Lower properties through `editing.rs`, not direct `Operation` construction.

Cascade behavior:

- Valid modify lines before a later failure remain applied.
- The failing line is not applied.
- Later lines are discarded.
- `DslCompileSession` must preserve only successful context.

Diagnostics:

- Map `EditError` into `LUMD09xx` DSL diagnostics with line spans.
- Unsupported target/property combos must halt precisely.

Tests:

- `#headline text("...")` lowers to `UpdateNode`.
- `#headline font_size(44) lh(1.08) s(fill,hug)` lowers to one or more narrow
  node patches.
- `#page:linkedin_square size(1080,1080,px)` lowers to `UpdatePage`.
- malformed target emits `LUMD0901` or equivalent.
- modify line for locked node halts.
- unsupported property on page halts.
- modify line after creation can target the created ID in the same session.

Acceptance gate:

- Agents can repair text/size/style/page dimensions in DSL without re-emitting
  page blocks.

### D4. Safe Delete, Before/After, And Rich Parent

Purpose: support targeted structure edits and ordering repairs.

Core builders:

```rust
pub fn build_safe_delete(scene: &Scene, node_id: NodeId) -> Result<EditBatch, EditError>;
pub fn build_move_before(scene: &Scene, target: NodeId, anchor: NodeId) -> Result<EditBatch, EditError>;
pub fn build_move_after(scene: &Scene, target: NodeId, anchor: NodeId) -> Result<EditBatch, EditError>;
pub fn build_move_to_parent(scene: &Scene, request: MoveToParentRequest) -> Result<EditBatch, EditError>;
```

Implementation details:

- Safe delete:
  - reject missing target.
  - reject protected/locked target unless edit authority later allows it.
  - remove descendants.
  - clear slot bindings.
  - preserve unrelated nodes/assets/slots.

- Move/reorder:
  - reject self-anchor.
  - reject parent cycles.
  - reject leaf parent.
  - compute indexes after detach for same-parent moves.
  - support destination page and container node.

DSL lowering:

- `delete(node_id)`
- `before(target, anchor)`
- `after(target, anchor)`
- `parent(target, parent_id, index)`
- `parent(target, page:page_id, index)`
- optional anchor form:

  ```text
  parent(logo, hero, before:headline)
  parent(logo, hero, after:brand_mark)
  ```

Tests:

- same-parent move to end never panics.
- before/after equivalent to expected `MoveNode`.
- move across parents preserves child lists.
- move to descendant rejected.
- delete clears slot bindings recursively.

Acceptance gate:

- The agent can fix ordering and remove bad elements without rewriting the
  whole page.

### D5. Slot, Asset, And Export/Profile Target Patches

Purpose: support non-visual but product-important repair targets.

Slot tasks:

- Update placeholder/sample/worst-case/common metadata already present in slot
  model.
- Bind/unbind nodes through existing slot operations.
- Reject incompatible node kinds where slot content type demands it.

Asset tasks:

- Metadata-only asset label/status/provenance patch if supported by current
  `AssetRecord`.
- Node image replacement via node patch should be the primary path.
- Do not implement upload/storage/provider runtime here.

Export profile tasks:

- Allow structured patch for existing export profile if it maps cleanly to
  `UpsertExportProfile` or `RemoveExportProfile`.

Tests:

- `#slot:campaign.headline placeholder("...")` updates slot metadata.
- `#slot:campaign.headline bind(headline)` binds node.
- `#slot:campaign.headline unbind(headline)` unbinds node.
- `#logo asset(asset_logo_alt)` replaces image source.
- missing asset ID is rejected before mutation.

Acceptance gate:

- ABM repair surfaces can target slots and image/logo refs precisely.

### D6. Structured Agent Patch DTO And Helper Bridge

Purpose: give agents a safe non-DSL repair surface.

Rust/helper:

- Add a `lumen-api-helper` action such as `apply_structured_patch` or
  `build_structured_patch_operations`.
- Request includes scene JSON, base revision if available, patch DTO, and
  strict target scope.
- Response includes operations, diagnostics, touched targets, preserved targets,
  and updated scene if applied.

Python agent runtime:

- Add DTOs:
  - `AgentStructuredPatchRequest`
  - `AgentStructuredEdit`
  - `PatchPrecondition`
  - `PatchResult`
- Add tool wrapper:

  ```text
  apply_structured_patch(...)
  ```

- Route critic issues with concrete target IDs through structured patch before
  whole-block DSL fallback.
- Persist:
  - patch request.
  - operation summary.
  - touched target list.
  - strict-scope result.
  - diagnostics.

Strict-scope policy:

- If repair was declared for `headline`, reject a patch that touches
  `page:linkedin_square` or unrelated nodes unless explicitly allowed.

Tests:

- critic issue targeting node creates structured patch request.
- structured patch applies and records operation count.
- unrelated target touch fails strict mode.
- failed patch writes trace/final diagnostics.

Acceptance gate:

- Visual repair loops can fix a concrete issue without duplicate page/node ID
  regeneration.

### D7. Clone And Replace

Purpose: support repeated structures and subtree swaps.

Clone builder:

```rust
pub struct CloneSubtreeRequest {
    pub source: NodeId,
    pub new_root_id: NodeId,
    pub placement: ClonePlacement,
    pub slot_policy: CloneSlotPolicy,
    pub computed_policy: ComputedClonePolicy,
}
```

Rules:

- Deep-copy subtree.
- Deterministically map child IDs.
- Reject collisions before mutation.
- Clear computed geometry by default.
- Preserve asset refs.
- Require explicit slot policy:
  - `detach` default.
  - `copy`.
  - `suffix`.

Replace builder:

```rust
pub struct ReplaceNodeRequest {
    pub target: NodeId,
    pub replacement: NodeId,
    pub slot_policy: ReplaceSlotPolicy,
}
```

Rules:

- Existing replacement subtree goes to target parent/index.
- Old target is removed.
- Replacement must not be descendant of target in invalid ways.
- Slot preservation must be explicit.

DSL:

- `clone(feature_card, as:feature_card_2, after:feature_card)`
- `clone(feature_card, as:feature_card_2, parent:feature_grid, index:2)`
- `replace(hero_visual, with:hero_visual_v2)`

Tests:

- clone creates deterministic ID map.
- clone clears computed geometry.
- clone rejects collision.
- replace preserves target index.
- replace is atomic on invalid replacement.
- slot policies behave as documented.

Acceptance gate:

- Agents can duplicate a good design structure and then override local content
  instead of manually rebuilding it.

### D8. Checkpoints, Undo, Redo, And Patch Metadata

Purpose: make edits traceable and reversible after stable patch semantics.

Implementation posture:

- Do not encode undo/redo as normal scene mutation operations.
- Keep pure `compile_dsl` strict when no history context is available.
- Store checkpoints in operation history/run trace/editor history.
- Add optional checkpoint label to `EditBatch`.

API/editor/agent tasks:

- Editor operation history can display `EditBatch.intent` and checkpoint label.
- Agent traces persist checkpoint label per repair.
- API operation log can store patch metadata if existing schema allows it; if
  not, plan a migration rather than hiding it in diagnostics.

DSL:

- `// label` records checkpoint metadata in session context.
- `undo("label")` / `redo("label")` only lower when a history adapter is
  supplied.
- Without history adapter, emit a precise diagnostic.

Tests:

- checkpoint labels attach to the next edit batch.
- pure compile rejects undo with repair hint.
- editor undo/redo continues to work over operation-backed history.

Acceptance gate:

- Phase D can explain and reverse targeted repairs in product traces, without
  pretending undo is a scene-level semantic.

### D9. Editor Unification

Purpose: align human edit workflows with the same semantics agents use.

Tasks:

- Replace duplicated editor reorder index math with shared helper behavior
  where the JS/Rust boundary permits it.
- Add parity tests proving editor reorder and DSL `before`/`after` produce the
  same final scene.
- Add duplicate/clone UI action only after the Rust clone builder is stable.
- Add replace image action backed by node asset patch.
- Keep undo/redo frames grouped around edit batches where available.

Pragmatic implementation:

- Full Rust-in-browser builder reuse may wait for a WASM boundary if not yet
  wired.
- Until then, TypeScript helpers should mirror the Rust test vectors exactly
  and be covered by cross-fixture tests.

Tests:

- editor delete equals safe delete behavior.
- editor layer move equals before/after final scene.
- editor duplicate equals clone builder final scene for fixture.
- editor replace image creates same operation effect as structured patch.

Acceptance gate:

- The product can use the same mental model for agent and human edits.

### D10. API/Persistence Patch Route

Purpose: make targeted patches durable product actions.

Route:

```text
POST /documents/{document_id}/patches
```

Request:

```json
{
  "schema_version": 1,
  "base_version": 12,
  "actor": "agent",
  "source": "visual_repair",
  "checkpoint": "repair headline overflow",
  "patch": {}
}
```

Behavior:

- load document scene.
- call Rust helper/edit builder.
- apply checked operations atomically.
- persist operations and diagnostics.
- persist patch metadata if schema supports it.
- return compact scene/document summary.

Tests:

- valid patch updates document and operation log.
- invalid patch leaves document unchanged.
- base-version mismatch rejected or clearly diagnosed.
- patch metadata visible in operation history/readback.

Acceptance gate:

- Agent/editor/API patches can be saved and replayed as product history.

### D11. Conformance, Review, And Live Repair Proof

Purpose: prove the whole Phase D surface behaves as a product system.

Conformance scenarios:

1. Text overflow repair:
   - target `headline`.
   - reduce font size, change text, set `s(fill,hug)`.
   - unrelated CTA/logo preserved.

2. Logo placement repair:
   - target `logo`.
   - move/resize.
   - page dimensions preserved.

3. Image replacement:
   - target `hero_image`.
   - replace asset ID.
   - slot metadata preserved.

4. Feature card clone:
   - clone first card.
   - override title/body/icon.
   - computed geometry recomputed by preflight.

5. Reorder CTA:
   - `before`/`after` within auto-layout container.
   - export order matches scene order.

6. Multi-page preservation:
   - repair page 1.
   - page 2 hash/summary unchanged.

7. Agent visual repair:
   - critic rejects preview.
   - agent applies structured patch.
   - no duplicate page IDs.
   - new preview generated.

Acceptance gate:

- At least one deterministic or live agent trace shows targeted repair through
  structured patch or modify DSL.
- `final.json`/trace artifacts contain target, patch, operations, diagnostics,
  preview, critique, and acceptance outcome.

## Test Matrix

Run before Phase D completion:

```bash
cargo fmt --check
cargo test -p lumen-core
cargo test -p lumen-agent
cargo test -p lumen-api-helper
cargo test -p lumen-export
cargo test
cargo clippy --all-targets -- -D warnings
cargo check --target wasm32-unknown-unknown
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests -q
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests -q
npm --prefix apps/editor run lint
npm --prefix apps/editor test
npm --prefix apps/editor run build
git diff --check
```

Add targeted tests as the implementation grows:

```bash
cargo test -p lumen-core --test editing
cargo test -p lumen-core --test dsl_compiler -- dsl_modify
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
npm --prefix apps/editor test -- operations sceneQueries EditorApp
```

## Suggested Commit Sequence

Keep commits reviewable:

1. `Add Phase D implementation tests and fixtures`
2. `Add core edit target and batch builders`
3. `Lower DSL modify lines for node and page patches`
4. `Add safe delete and relative move directives`
5. `Add slot and asset targeted patch support`
6. `Add structured agent patch helper and runtime tool`
7. `Add clone and replace edit builders`
8. `Add checkpoint metadata and undo diagnostics`
9. `Unify editor targeted edit helpers`
10. `Add API patch route and persistence coverage`
11. `Add Phase D conformance repair traces`

## Risk Register

### Risk: DSL compiler becomes too large

Mitigation:

- Put edit semantics in `editing.rs`.
- Keep `dsl.rs` responsible for parsing and converting DSL properties into
  edit patches.

### Risk: Clone/replace corrupts slot semantics

Mitigation:

- Make slot policy explicit.
- Default to `detach`.
- Add slot preservation tests.

### Risk: Computed geometry becomes stale after targeted edits

Mitigation:

- Clear computed geometry for geometry/layout/text/style/asset changes.
- Require preflight before export/acceptance.

### Risk: Editor and agent semantics diverge

Mitigation:

- Use shared fixture scenarios.
- Compare final scene state, not just operation names.
- Move logic to Rust/WASM where possible.

### Risk: Agent still regenerates full pages

Mitigation:

- Update repair prompts and tool policy to prefer structured patches when
  target IDs exist.
- Strictly reject duplicate page/node creation during repair unless the repair
  mode explicitly allows replacement.

### Risk: Undo/redo scope becomes ambiguous

Mitigation:

- Defer full history-context undo until stable edit batches exist.
- Treat checkpoint labels as metadata first.
- Keep pure DSL compile strict without history context.

## Implementation Readiness Checklist

Before starting code:

- [ ] Confirm `reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md` is
      either committed or intentionally restored in the worktree despite
      `.gitignore`.
- [ ] Confirm no unrelated dirty files in the Phase D worktree.
- [ ] Add `editing.rs` tests before implementation.
- [ ] Decide whether first work slice is node/page modify only or includes
      safe delete; recommendation: node/page modify first.

Before considering Phase D complete:

- [ ] `#target ...` node/page DSL works.
- [ ] structured patch tool works.
- [ ] `before`/`after` works.
- [ ] safe delete works.
- [ ] image replacement works.
- [ ] clone works for repeated card structures.
- [ ] replace works for existing subtree replacement.
- [ ] checkpoints are recorded as metadata.
- [ ] editor workflows align with core semantics.
- [ ] API/helper path can persist targeted patches.
- [ ] conformance fixture proves no unrelated page/node mutation.
- [ ] at least one agent repair trace uses targeted patch instead of whole-page
      regeneration.

## V0 Implementation Status

Implemented in this branch:

- `crates/lumen-core/src/editing.rs` with target refs, resolved targets,
  sparse patch DTOs, edit batches, node/page/slot/asset modify builders,
  safe node delete, before/after/parent move builders, deterministic clone
  subtree, and existing-node replace.
- DSL lowering for `#node`, `#page`, `#slot`, `#slot_id`, and `#asset` modify
  targets.
- DSL lowering for `delete`, `parent`, `before`, `after`, `clone`, and
  `replace`.
- `apply_structured_edit` in `lumen-api-helper`, returning updated scene,
  diagnostics, edit metadata, and the exact canonical operations applied.
- `CoreClient.apply_structured_edit`.
- `POST /documents/{document_id}/edits`, persisting generated canonical
  operations into operation history.
- DeepAgent tool `apply_structured_edit` and factory wiring.
- Tests for core edit builders, DSL modify/directive lowering, helper bridge,
  API persistence, and agent tool tracing.

Deferred after V0:

- Document/export-profile modify patches.
- Safe delete builders for pages, slots, assets, and export profiles.
- `ungroup`, `override`, history-aware `undo`/`redo`, and checkpoint execution.
- Block replace syntax where the replacement subtree is authored inline rather
  than staged as an existing node.
- Strict agent repair scope enforcement against reviewer-declared target sets.
- Refactoring React helpers into a TypeScript structured-edit DTO wrapper. The
  editor continues to use canonical operations, which preserves source-of-truth
  correctness for this V0.
