# Phase D V1 Implementation Plan

Date: 2026-06-12

## Objective

Complete Phase D. V0 built the shared targeted-edit foundation; V1 finishes
every remaining item in Phase D's charter so that, at the end of this branch,
nothing in the Phase D scope is unimplemented, unowned, or silently deferred.

The product behavior this completes:

```text
critic/user finds a concrete issue
  -> agent/editor identifies exact target
  -> targeted edit becomes a checked, enveloped, invertible operation batch
  -> the batch is rejected before mutation if it exceeds its declared scope
  -> history records what changed, why, by whom, and how to undo it
  -> preflight/export/critic run again
  -> unrelated scene regions are provably preserved
```

## Relationship To V0

V0 delivered (committed as `3f655d6` on
`phase-d/targeted-editing-repair-semantics-v0`):

- `crates/lumen-core/src/editing.rs`: target refs, resolved targets, sparse
  patches, `EditBatch`, node/page/slot/asset modify builders, safe node
  delete, before/after/parent moves, deterministic clone, existing-node
  replace.
- DSL lowering for `#node`, `#page`, `#slot`, `#slot_id`, `#asset` modify
  targets and the `delete`, `parent`, `before`, `after`, `clone`, `replace`
  directives.
- `apply_structured_edit` in `lumen-api-helper`,
  `POST /documents/{document_id}/edits`, and the DeepAgent
  `apply_structured_edit` tool.

V1 is governed by the decision records in
`phase-d-targeted-editing-repair-semantics.md` under "Post-V0 Decisions
(Resolved 2026-06-12)" (Decisions 0–8). This plan does not restate the
rationale; it implements the decisions.

## Definition Of Done For Phase D

Phase D is complete when all of the following hold:

1. Every applied edit — agent, editor, API, or DSL — persists as an edit
   envelope with intent, checkpoint label, actor, source, touched targets,
   base revision, canonical operations, and inverse operations.
2. Document-level linear undo/redo works over that history, append-only.
3. Checkpoints are usable anchors: labeled, listed, and revert-to-checkpoint
   works.
4. Strict agent repairs fail closed when a batch touches targets outside the
   declared closure.
5. Every target kind in `EditTargetRef` has modify lowering: document, page,
   node, slot, slot key, asset, export profile.
6. Every lifecycle delete exists with the decided rules: node (V0), page,
   slot, asset (archive + reference check), export profile.
7. The full directive vocabulary lowers or diagnoses precisely: `delete`
   (with `if_exists`), `parent` (with `before:`/`after:` anchors), `before`,
   `after`, `clone`, `replace` (existing-node and inline block), `ungroup`,
   `override`, `undo`, `redo`, `// label` checkpoints.
8. The editor commits edits through `/edits`, renders envelope history
   (intent + checkpoint labels), and Rust/TS parity fixtures pass in CI.
9. Conformance fixtures prove unrelated scene regions are preserved, and at
   least one live or deterministic agent trace shows a targeted visual repair
   with no page regeneration.

Work that Phase D's charter assigns elsewhere (asset byte lifecycle → Phase E;
component master/instance model → future workstream; ABM runtime execution →
Phase G; print-grade shaping → export workstream; WASM editor core →
post-parity follow-up) is listed in the spec's "Contract Boundaries" section
with owners. Those are the only exclusions.

## Architecture Additions

### A1. The Edit Envelope

The envelope is the history unit. Rust side extends `EditBatch`
(`crates/lumen-core/src/editing.rs`, currently
`{ operations, touched_targets, checkpoint_label, intent }`):

```rust
pub struct EditBatch {
    pub operations: Vec<Operation>,
    pub inverse_operations: Option<Vec<Operation>>, // None => not invertible
    pub touched_targets: Vec<EditTargetRef>,
    pub checkpoint_label: Option<String>,
    pub intent: Option<String>,
    pub lineage: Option<CloneLineage>, // clone/override provenance
}

pub struct CloneLineage {
    pub source_root: NodeId,
    pub id_map: Vec<(NodeId, NodeId)>, // source id -> clone id
}
```

API side, the persisted envelope row (extend the operation-history storage in
`apps/api/lumen_api/database.py`; the request DTOs in `models.py` already
carry `ActorEnvelope` and `source`):

```json
{
  "envelope_version": 1,
  "batch_id": "uuid",
  "document_id": "doc_1",
  "seq": 14,
  "base_revision": 13,
  "actor": {},
  "source": "agent",
  "intent": "repair_text_overflow",
  "checkpoint_label": "headline fix",
  "touched_targets": [{ "kind": "node", "id": "headline" }],
  "operations": [],
  "inverse_operations": [],
  "lineage": null,
  "created_at": "..."
}
```

Rules:

- Replay reads `operations` only, in `seq` order. The envelope is metadata
  around the batch, never a second source of truth.
- Every write path produces an envelope: `/edits`, the raw operations route
  (`intent: "apply_operations"`), DSL compile application
  (`intent: "dsl_block"`), and editor commits.
- Migration backfills existing history rows as anonymous envelopes
  (`envelope_version: 0`, no intent/inverse). Anonymous envelopes are not
  undoable; the history UI labels them "(pre-envelope)".

### A2. Inverse Operation Construction

Inverses are computed where the pre-state scene is in hand: inside the edit
builders and inside checked application for raw operation batches. Mapping
per `Operation` variant:

| Operation | Inverse | Captured at apply time |
| --- | --- | --- |
| `AddPage { page }` | `RemovePage { page.id }` | nothing |
| `RemovePage { page_id }` | `AddPage { prior page }` plus re-bind ops for cleared slot bindings | full prior `Page` (subtree) + cleared bindings |
| `UpdateDocument { patch }` | `UpdateDocument { inverse patch }` | prior values of exactly the touched fields |
| `UpdatePage { patch }` | `UpdatePage { inverse patch }` | prior values of touched fields |
| `InsertNode { node, .. }` | `RemoveNode { node.id }` | nothing |
| `RemoveNode { node_id }` | `InsertNode { prior parent, prior index, prior subtree }` plus `BindNodeToSlot` for each cleared binding | subtree snapshot, parent, index, bindings |
| `MoveNode { .. }` | `MoveNode { prior parent, prior index }` | pre-move parent and index |
| `UpdateNode { patch }` | `UpdateNode { inverse sparse patch }` | prior values of touched fields |
| `UpsertSlot { slot }` | prior existed: `UpsertSlot { prior }`; else `RemoveSlot { slot.id }` | prior slot record |
| `RemoveSlot { slot_id }` | `UpsertSlot { prior slot }` | prior slot record (carries bindings) |
| `UpsertAsset { asset }` | prior existed: `UpsertAsset { prior }`; else `RemoveAsset { asset.id }` | prior record |
| `RemoveAsset { asset_id }` | `UpsertAsset { prior }` | prior record |
| `PlaceAssetInNode { .. }` | restore prior source/placement via `UpdateNode`/prior placement | prior node image source + placement |
| `PlaceAssetInSlot { .. }` | restore prior slot placement | prior placement |
| `BindNodeToSlot { .. }` | `UnbindNodeFromSlot { .. }` | nothing |
| `UnbindNodeFromSlot { .. }` | `BindNodeToSlot { .. }` | nothing |
| `SetBrandKitRef { .. }` | `SetBrandKitRef { prior }`; if no prior ref, clear via `UpdateDocument` patch | prior ref or absence |
| `UpsertExportProfile { profile }` | prior existed: `UpsertExportProfile { prior }`; else `RemoveExportProfile { name }` | prior profile |
| `RemoveExportProfile { name }` | `UpsertExportProfile { prior }` | prior profile |
| `FinalizeTemplate { .. }` | none — lifecycle, not invertible | batch marked `inverse_operations: None` |

Correctness property (the test that matters): for every builder and fixture,

```text
apply(ops); apply(inverse_ops)  ==  identity on the scene
```

asserted by structural scene equality, not operation-name comparison.

### A3. History, Checkpoints, Undo/Redo

Model: the envelope log is append-only; per-document undo/redo cursors are
mutable bookkeeping over the immutable log (like a branch ref over commits).

- Per document: `undo_stack: [batch_id]`, `redo_stack: [batch_id]`, updated
  transactionally with each envelope append.
- Undo: pop batch `B` from `undo_stack`; append a new envelope whose
  operations are `B.inverse_operations`, `intent: "undo:<B.intent|label>"`,
  with a `reverts: B.batch_id` field; push `B` onto `redo_stack`.
- Redo: pop from `redo_stack`; append a new envelope re-applying the original
  operations (`reapplies: batch_id`); push back onto `undo_stack`.
- A new ordinary edit clears `redo_stack` (linear model).
- Checkpoint: a label on an envelope. Listing checkpoints = scanning
  envelopes. Revert-to-checkpoint: compose inverses of every effective batch
  after the anchor, newest first, into one envelope
  (`intent: "revert_to_checkpoint:<label>"`); move those batches to
  `redo_stack` in order.
- Any batch in the revert range with `inverse_operations: None`
  (`FinalizeTemplate`, anonymous pre-envelope batches) makes the
  undo/revert reject with a precise diagnostic.
- DSL: core gains a `HistoryAdapter` trait (resolve checkpoint label →
  batches to invert; supply inverses). `DslCompileSession` accepts an
  optional adapter; `undo("label")`/`redo(...)` lower only when present.
  Pure `compile_dsl` keeps the existing rejection diagnostic.
- Editor: local optimistic stack covers uncommitted gestures only; committed
  history undo/redo calls the API. Server returns the new revision; client
  reconciles or refetches on mismatch.

### A4. Strict Scope Enforcement

Requests may carry a scope declaration:

```json
{ "scope": { "mode": "strict", "allowed": [{ "kind": "node", "id": "headline" }] } }
```

Allowed closure of declared targets `D`:

```text
closure(D) =
  D
  ∪ descendants of every node in D
  ∪ child-list adjustments on the structural parent of a moved/inserted/
    removed node that is itself in closure(D)
  ∪ slots whose binding changes reference only nodes in closure(D)
```

Rules:

- Every operation's primary target must resolve inside `closure(D)`;
  otherwise the entire batch is rejected before mutation with
  `LUMD0910` (proposed; see Diagnostics) and the violating targets listed.
- `mode: "strict"` is mandatory for agent repair turns; the agent runtime
  derives `allowed` from the critic issue's named targets. Rejected attempts
  persist to the agent trace (not to document history) with the scope
  verdict.
- `mode: "advisory"` (human/editor default): violations become warning
  diagnostics; the batch applies.
- Page deletion and document-level patches are never inside a node-level
  closure; they require their own declared targets.

### A5. Edit Authority (Locked Targets)

Requests carry `authority: "default" | "override_locks"`. Locked-target
mutations reject with `LUMD0904` under `default`. The editor sends
`override_locks` only from an explicit user unlock action; the agent runtime
never sends it.

### A6. Lifecycle Delete Rules (Decided)

| Target | Rule |
| --- | --- |
| Page | Reject deleting the last page. Cascade node deletion through safe-delete; unbind slots bound to deleted nodes; keep slot definitions. Strict mode requires an explicit page target. |
| Slot | Drafts: hard delete; unbind nodes, never delete nodes. Finalized revisions: reject (`LUMD0905`); a new revision is required. |
| Asset | `archive` sets `AssetStatus` to archived (add the variant if absent). Hard delete rejects while referenced by any node, slot, or finalized revision. Byte/storage lifecycle stays in Phase E. |
| Export profile | Reject deleting the default/active profile unless `replace_with:<name>` names an existing profile; references in finalized revisions force a new revision. |

## Implementation Slices

Each slice lands with its tests and leaves the tree green. Slices V1.6–V1.10
are engine-parallel after V1.1; V1.11 can proceed in parallel after V1.2.

### V1.0 Branch, Baseline, Failing Tests

Purpose: clean start with evidence before code.

Tasks:

- Commit the decision/plan documentation on
  `phase-d/targeted-editing-repair-semantics-v0` (requires user approval per
  workflow).
- Create branch `phase-d/targeted-editing-repair-semantics-v1` and worktree
  `/Users/aryankeshri/Documents/brilliant-design/phase-d-targeted-editing-repair-semantics-v1`.
- Add `.claude/memory/workstreams/phase-d-targeted-editing-repair-semantics-v1.md`
  entry for branch creation.
- Add failing/ignored tests naming the V1 surface: inverse round-trip,
  envelope persistence, undo/redo, scope enforcement, lifecycle deletes,
  document/export patches, ungroup, override, block replace, parity
  fixtures.
- Extend fixture builders with: a finalized-revision document, a two-page
  document with cross-page slot bindings, a locked node, an asset referenced
  by node and slot, multiple export profiles with a default.

Acceptance gate: tests fail for missing implementation, not invalid fixtures.

### V1.1 Inverse Operation Batches In Core

Purpose: make every edit invertible at the moment it is cheap.

Files: `crates/lumen-core/src/editing.rs`, `operations.rs`,
`tests/editing.rs`.

Tasks:

- Add `inverse_operations` and `lineage` to `EditBatch` (serde-compatible,
  defaulted, so V0 JSON still parses).
- Implement per-variant inverse construction (table A2) inside the builders;
  add a checked-apply helper that produces inverses for raw operation batches
  (used by the API operations route).
- Sparse inverse patches: capture prior values for exactly the fields a
  patch touches.
- `FinalizeTemplate` and any future non-invertible op set
  `inverse_operations: None` for the whole batch.

Tests: round-trip identity (`apply; apply-inverse; assert scene equality`)
for every builder over every fixture; move round-trips including same-parent
index shifts; remove/re-insert restores subtree, bindings, and order;
non-invertible batch is marked `None`.

Acceptance gate: round-trip property passes across the full fixture set;
native and `wasm32-unknown-unknown` compile.

### V1.2 API Envelope Persistence And Base-Revision Guard

Purpose: make the envelope the history unit (Decision 0).

Files: `apps/api/lumen_api/database.py`, `models.py`, `main.py`,
`crates/lumen-api-helper/src/main.rs`, API tests.

Tasks:

- Migrate history storage to envelope rows (A1 schema); backfill existing
  rows as `envelope_version: 0`.
- `/edits`, the raw operations route, and DSL application all persist
  envelopes; helper returns `inverse_operations` and `lineage` so Python
  never computes semantics.
- `base_revision` precondition: requests may pin the revision they were
  built against; mismatch rejects with `LUMD0911` before mutation.
- Finalized-revision guard: edit requests against a finalized revision
  reject with `LUMD0905` (drafts/new revisions are the edit surface).
- History readback route returns envelopes (intent, checkpoint, actor,
  touched targets), newest first, paginated.

Tests: envelope persisted for every write path; replay from operations alone
reproduces the scene; revision mismatch and finalized-revision rejections;
backfilled rows readable.

Acceptance gate: history readback shows enveloped batches for agent, editor,
API, and DSL writes; replay equivalence holds.

### V1.3 Strict Agent Target-Scope Enforcement

Purpose: make agent repairs fail closed (Decision in spec Open Decisions #5).

Files: `crates/lumen-core/src/editing.rs` (closure computation),
`lumen-api-helper`, `apps/api/lumen_api/main.py`,
`apps/agent_runtime/lumen_deepagent/*`.

Tasks:

- Implement `closure(D)` per A4 with a precise, fixture-backed definition.
- Helper and `/edits` accept the `scope` declaration; strict violations
  reject the whole batch pre-mutation with `LUMD0910` listing violating
  targets; advisory mode warns and applies.
- Agent runtime: repair turns always send `mode: "strict"` with targets from
  the critic issue; one retry is allowed with a narrowed patch; rejected
  attempts persist to the trace with the scope verdict.

Tests: in-closure edits pass; sibling/page/unrelated-slot touches reject;
move operations correctly allow the structural-parent child-list adjustment;
advisory mode warns without blocking; trace records verdicts.

Acceptance gate: a deterministic repair fixture shows a scope-violating
patch rejected with the scene unchanged.

### V1.4 Checkpoint Anchors

Purpose: named history anchors (Decision 2).

Files: `crates/lumen-core/src/dsl.rs`, API routes, agent runtime trace
persistence, editor history panel data.

Tasks:

- `// label` in a DSL block attaches the label to the next emitted batch in
  the session; structured requests pass `checkpoint` explicitly (already in
  the request shape).
- Checkpoint listing per document derived from envelopes.
- Agent traces and editor history surface labels.

Tests: label attaches to the correct batch; listing returns labels in order;
duplicate labels are allowed but resolve to the most recent on lookup (with
an info diagnostic).

Acceptance gate: a labeled repair is visible as a named anchor in history
readback.

### V1.5 Document-Level Undo/Redo

Purpose: Decision 1, end to end.

Files: API (`/documents/{id}/undo`, `/redo`,
`/revert?checkpoint=<label>`), core `HistoryAdapter` trait + session wiring,
editor wiring in V1.11.

Tasks:

- Implement cursors-over-log per A3; undo/redo/revert append envelopes,
  never truncate.
- New ordinary edit clears the redo stack.
- Non-invertible or pre-envelope batches in range reject with a precise
  diagnostic (`LUMD0912` proposed).
- `HistoryAdapter` implementation backed by the API history; DSL
  `undo("label")`/`redo(...)` lower through it in session contexts; pure
  compile keeps rejecting.

Tests: undo/redo round-trip restores scenes structurally; interleaved
edit/undo/edit clears redo; revert-to-checkpoint composes inverses newest
first; finalize blocks undo across it; DSL undo works only with adapter.

Acceptance gate: scripted sequence (edit, edit, checkpoint, edit, revert,
redo) produces the expected scene at every step with an append-only log.

### V1.6 `#document` And `#export:name` Modify Lowering

Purpose: complete modify coverage for every `EditTargetRef` kind.

Files: `editing.rs`, `dsl.rs`, helper/API DTOs, tests.

Tasks:

- Add `EditPatch::Document(DocumentEditPatch)` over `DocumentMeta`: `title`
  (`name("...")`), `artifact_type("...")`, `medium(print|digital|email|
  direct_mail|ad)`, `brand_kit(id, version)` (lowers to `SetBrandKitRef`).
  Document `status` is lifecycle-only, not patchable here.
- Add `EditPatch::ExportProfile(ExportProfileEditPatch)` sparse over the
  existing `ExportProfile` fields (confirm exact field list against the
  scene model at implementation); lowers to `UpsertExportProfile`.
- DSL: `#document ...` and `#export:print_pdf ...` modify lines; structured
  edit kinds `update_document`, `update_export_profile`.

Tests: each property lowers to the narrow patch; unknown properties halt with
the unsupported-property diagnostic; cascade behavior preserved.

Acceptance gate: all seven target kinds accept modify lines or reject with a
precise diagnostic — none fall through as parse errors.

### V1.7 Lifecycle Safe Deletes

Purpose: Decisions 3–6.

Files: `editing.rs`, `dsl.rs`, helper/API, tests.

Tasks:

- `build_safe_delete_page`, `build_safe_delete_slot`,
  `build_archive_asset` / `build_hard_delete_asset`,
  `build_delete_export_profile` per A6.
- DSL: extend `delete(...)` to target-ref forms — `delete(page:home)`,
  `delete(slot:campaign.headline)`, `delete(asset:asset_logo)` (archive),
  `delete(export:print_pdf, replace_with:web_png)`.
- Structured edit kinds: `delete_page`, `delete_slot`, `archive_asset`,
  `hard_delete_asset`, `delete_export_profile`.
- Diagnostics: last page (`LUMD0906`), finalized slot (`LUMD0905`),
  referenced asset (`LUMD0907`), default profile without replacement
  (`LUMD0908`).

Tests: last-page rejection; page delete unbinds but keeps slot definitions
and preflight flags the unbound required slot; slot delete preserves nodes;
referenced-asset hard delete rejects while archive succeeds; profile delete
with replacement rewires the default; every delete round-trips through its
inverse.

Acceptance gate: each lifecycle delete provably preserves unrelated targets
and is undoable.

### V1.8 DSL Conveniences And Edit Authority

Purpose: close the small authoring gaps the spec lists.

Tasks:

- `append("...")` / `prepend("...")` on text targets: build the full new
  content at build time (prior content captured for the inverse); reject on
  non-text kinds.
- `delete(target, if_exists)`: missing target emits no operation plus an
  info diagnostic; default stays strict.
- `parent(node, dest, before:anchor)` / `after:anchor` relative anchors,
  resolving inside the destination parent.
- `authority` per A5 honored across helper, API, and DSL session options;
  `LUMD0904` on locked violations.

Tests: append/prepend round-trip inverses restore prior text; `if_exists`
emits info not error; anchored reparent matches the equivalent
`before`/`after` batch; locked-node edit rejects under default authority and
applies under explicit override.

Acceptance gate: directive vocabulary matches the spec's authoring surface
exactly.

### V1.9 Ungroup And Override Patch Groups

Purpose: complete structural directives (Decision 7).

Tasks:

- `ungroup(group_id)`: move children to the group's parent at the group's
  index preserving order; delete the emptied group; clear computed geometry
  on moved children; reject non-containers and page roots; reject auto-layout
  containers unless `allow_layout` is passed (`LUMD0909` otherwise).
- `override(root_id)` block: subsequent indented modify lines form one
  `EditBatch` with `intent: "override:<root_id>"`; every inner target must be
  a descendant-or-self of the root (`LUMD0913` otherwise); checkpoint label
  attaches to the group.
- Persist `CloneLineage` on clone batches and thread it through helper/API
  envelopes (retrofit path for a future component model, and the Phase G
  repeater primitive).
- Structured edit kinds: `ungroup`, and grouped-edit submission for override.

Tests: ungroup preserves child order and sibling indexes; layout-container
guard; override rejects out-of-root targets atomically; lineage appears in
the persisted envelope.

Acceptance gate: clone → override flow works end to end as one traceable,
undoable group.

### V1.10 Inline Block Replace

Purpose: the last unimplemented spec syntax.

```text
replace(hero_visual)
  hero_visual_v2 fr p(40,40) s(1000,hug) fill($surface.card)
    headline text("New headline") s(fill,hug) style($type.headline)
```

Rules:

- The indented replacement subtree parses in creation context against a
  staging parent; nothing attaches to the scene until the batch builds.
- Exactly one root (`LUMD0914` otherwise); authored IDs collide-checked
  before mutation; root takes the old target's parent and index; old target
  is safe-deleted in the same atomic batch.
- Slot policy: `slots:detach` default (bindings cleared; preflight flags
  unbound required slots). `slots:preserve` requires the new subtree to carry
  matching slot annotations; bindings remap by slot key with node-kind
  compatibility checks (`LUMD0915` on mismatch). No implicit structural
  guessing.
- Cascade halt: a parse failure inside the block discards the whole replace
  (it is one directive), not half a subtree.

Tests: replacement preserves parent/index; atomicity on inner failure; both
slot policies; ID collision rejection; inverse restores the original subtree
and bindings.

Acceptance gate: block replace is expressible, safe, atomic, and undoable;
unsupported edge cases diagnose precisely instead of falling back to
full-page regeneration.

### V1.11 Editor Structured-Edit Adoption And Parity Fixtures

Purpose: Decision 8 — one semantics for humans and agents.

Files: `apps/editor/src/engine/structuredEdits.ts` (new),
`apps/editor/src/engine/operations.ts`,
`apps/editor/src/components/EditorApp.tsx`, `fixtures/edit-parity/*.json`
(new, shared), `crates/lumen-core/tests/edit_parity.rs` (new), editor tests.

Tasks:

- TS structured-edit DTO wrapper mirroring the Rust JSON shapes.
- Committed edits flow through `POST /documents/{id}/edits` with optimistic
  local apply; server response (applied operations + new revision)
  reconciles or triggers refetch on mismatch.
- Editor delete/duplicate/reorder/replace-image actions route through the
  shared semantics (structured edits), with TS helpers retained only for
  optimistic preview.
- History panel renders envelopes: intent, checkpoint label, actor; undo/redo
  buttons drive the API for committed history while local gesture undo stays
  local.
- Parity fixtures: each fixture is `{ name, scene, edit,
  expected_operations }`; a Rust test and a Vitest test both assert exact
  operation-batch equality; both run in CI.

Tests: parity across reorder, delete, duplicate/clone, replace-image, text
and style patches; optimistic reconcile on conflicting revision; history
panel snapshot.

Acceptance gate: editor and agent edits over the same fixture produce
identical final scenes and identical persisted envelopes.

### V1.12 Conformance, Live Repair Proof, And Closeout

Purpose: prove Phase D as a product system (the spec's D9/D11 obligations).

Scenarios (extends the V0 plan's seven):

1. Text overflow repair preserving CTA/logo.
2. Logo placement repair preserving page dimensions.
3. Image replacement preserving slot metadata.
4. Feature-card clone + override with recomputed geometry.
5. Reorder within auto-layout matching export order.
6. Multi-page repair leaving the other page hash-identical.
7. Agent visual repair: critic rejection → structured patch → no duplicate
   page IDs → new preview.
8. Undo/redo round-trip across every builder (property test).
9. Checkpoint revert mid-session.
10. Page delete with visible (not silent) personalization-contract gap.
11. Strict-scope rejection trace persisted with scene unchanged.
12. Block replace with `slots:preserve` remap.

Closeout tasks:

- Full test matrix run (below).
- At least one live or deterministic agent repair trace artifact persisted
  with target, patch, operations, envelope, diagnostics, preview, critique,
  and acceptance outcome.
- Update the Phase D spec's V0 Coverage Matrix statuses to final.
- Append memory entries (decisions already recorded on 2026-06-12; add the
  completion entry with verification commands).

Acceptance gate: the Definition Of Done checklist at the top of this plan is
fully satisfied.

## Diagnostics Allocation (Proposed)

`LUMD0900`, `LUMD0901`, `LUMD0903` are in use; the spec reserves `LUMD0902`
(ambiguous target), `LUMD0904` (locked), `LUMD0905` (finalized revision).
Proposed new codes — reconcile against the diagnostics registry at
implementation time:

| Code | Meaning |
| --- | --- |
| LUMD0906 | cannot delete the last page |
| LUMD0907 | asset is referenced; hard delete rejected |
| LUMD0908 | default/active export profile needs a replacement |
| LUMD0909 | ungroup of a layout container without `allow_layout` |
| LUMD0910 | batch touched targets outside the declared strict scope |
| LUMD0911 | base scene revision mismatch |
| LUMD0912 | undo/redo/revert range contains a non-invertible batch |
| LUMD0913 | override target outside the override root |
| LUMD0914 | block replace requires exactly one root |
| LUMD0915 | slot preserve remap incompatible with replacement subtree |

Every diagnostic carries severity, stable code, target, concise message,
repair hint, and the source DSL line when applicable.

## Completeness Matrix

| Phase D scope item | Status after V0 | V1 slice |
| --- | --- | --- |
| Target-reference model (all kinds) | Done | — |
| Edit batch model | Done | V1.1 extends (inverse, lineage) |
| Node/page/slot/asset modify lowering | Done | — |
| `#document` modify lowering | Missing | V1.6 |
| `#export:name` modify lowering | Missing | V1.6 |
| Structured agent patch tool + API route | Done | V1.2 envelopes |
| `before`/`after`/`parent`/node `delete` | Done | V1.8 anchors, `if_exists` |
| `clone` / existing-node `replace` | Done | V1.9 lineage |
| Inline block replace | Missing | V1.10 |
| `ungroup` | Missing | V1.9 |
| `override` patch groups | Missing | V1.9 |
| Checkpoints | Metadata only | V1.4 |
| Undo/redo | Missing | V1.1 + V1.5 |
| Envelope-persisted history | Missing | V1.2 |
| Lifecycle deletes (page/slot/asset/profile) | Missing | V1.7 |
| Text `append`/`prepend` | Missing | V1.8 |
| Locked-target authority | Resolution-only | V1.8 |
| Strict agent scope enforcement | Policy only | V1.3 |
| Editor structured-edit wrapper + `/edits` adoption | Missing | V1.11 |
| Rust/TS parity fixtures in CI | Missing | V1.11 |
| Envelope history UI (intent/checkpoint) | Missing | V1.11 |
| Conformance + live repair proof | Partial | V1.12 |

## Test Matrix

Run before declaring Phase D complete:

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

Targeted during development:

```bash
cargo test -p lumen-core --test editing --test dsl_compiler --test edit_parity
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests -q -k "envelope or undo or scope"
npm --prefix apps/editor test -- structuredEdits editParity EditorApp
```

## Suggested Commit Sequence

1. `Add Phase D V1 fixtures and failing tests`
2. `Add inverse operation batches and clone lineage to edit batches`
3. `Persist edit envelopes and base-revision guard in API history`
4. `Enforce strict agent target scope on structured edits`
5. `Add checkpoint anchors across DSL, API, and traces`
6. `Add document-level undo, redo, and checkpoint revert`
7. `Lower document and export-profile modify targets`
8. `Add lifecycle safe deletes for pages, slots, assets, and profiles`
9. `Add append/prepend, if_exists, parent anchors, and edit authority`
10. `Add ungroup and override patch groups`
11. `Add inline block replace`
12. `Adopt structured edits in the editor with parity fixtures`
13. `Add Phase D conformance scenarios and live repair trace`

## Risk Register

### Risk: incorrect inverses corrupt undo

Mitigation: round-trip identity property tests for every builder over every
fixture; structural scene equality, not operation comparison; inverses built
only where pre-state is in hand.

### Risk: history schema migration breaks existing documents

Mitigation: envelope `envelope_version` field; backfill as version 0;
replay reads operations only, so old rows replay unchanged; migration test
over a copied V0 database fixture.

### Risk: optimistic editor state diverges from committed history

Mitigation: server returns applied operations and new revision on every
commit; client reconciles or refetches on mismatch; `base_revision`
precondition rejects stale writes.

### Risk: scope closure blocks legitimate repairs

Mitigation: precise closure definition with fixtures for the
structural-parent and slot-unbind allowances; one narrowed retry in the agent
loop; scope verdicts persisted to traces so false positives are observable.

### Risk: block replace destabilizes the parser

Mitigation: last engine slice; isolated grammar path; whole-directive
atomicity; explicit diagnostics for every unsupported form.

### Risk: `SetBrandKitRef` and placement inverses have no clean prior-state op

Mitigation: flagged as implementation details in A2; resolve against the
scene model during V1.1 and record the resolution in the memory file — they
are design details, not open product decisions.

## Acceptance Criteria

Phase D V1 — and with it Phase D — is complete when:

1. The ten spec acceptance criteria all hold.
2. Every applied batch is enveloped, attributed, and (where invertible)
   undoable; history is append-only.
3. Checkpoints anchor revert; undo/redo is linear and document-level.
4. Strict agent repairs fail closed with persisted verdicts.
5. All seven target kinds modify-lower; all lifecycle deletes follow the
   decided rules; the full directive vocabulary is implemented.
6. Editor and agent produce identical operation batches for identical edits,
   asserted by CI parity fixtures.
7. Conformance scenarios 1–12 pass, including the live repair trace with no
   page regeneration.
