# Agent Design Loop

This workstream adds the deterministic engine-facing agent loop. It is not the
LLM runtime, model-provider bridge, queue worker, FastAPI route layer, or asset
storage service.

The intended platform split is:

```text
Python/FastAPI agent runtime
  -> calls engine-facing design loop
  -> receives operations, diagnostics, preview artifacts, and repair state

lumen-agent
  -> compiles DSL through DslCompileSession
  -> applies structured operations through checked core operation APIs
  -> chooses/passes an effective Brand Kit
  -> runs canonical preflight
  -> exports an AgentCritique preview through an injected ExportAdapter
  -> calls an injected VisualCritic
  -> calls injected AssetTool stubs/contracts
```

`lumen-agent` depends on `lumen-core`. It consumes the `ExportAdapter` trait but
does not depend on `lumen-export` at runtime.

## Canonical Turn Pipeline

Each `AgentDesignLoop::run_turn` starts with one `AgentEdit`:

- `DslBlock`
- `StructuredOps`
- `AssetTool`

`AgentTurnInput` keeps the legacy plain `prompt` for compatibility, but the
agent-facing boundary is `AgentInstructionContext`. It separates:

- `user_request`
- trusted system/developer context
- untrusted uploaded/source material
- brand notes
- artifact goal
- generated critique notes

Brand guides, website text, uploaded files, and account/contact research should
enter through the untrusted/source fields, not as instructions.

DSL blocks are compiled through the session's `DslCompileSession::compile_block`.
Successful lines are preserved before a cascade halt. If the DSL has an error,
the loop stops before preflight/export/critique and returns the partial
operations plus DSL diagnostics for repair.

Successful preview/preflight passes sync the DSL session's internal scene while
preserving parser context and parent-stack continuation. This keeps
Brilliant-style repair blocks valid after a render-preview critique. Structured
operation edits still reset the DSL session because targeted operation batches
can invalidate indentation assumptions.

Structured operations are applied with `Scene::apply_operations_checked`. A
failed operation batch stops before preflight/export/critique and leaves the
session scene unchanged.

Asset requests are delegated to an injected `AssetTool`. V0 includes
`UnavailableAssetTool`, which returns a typed failure. Real upload, generation,
vectorization, provenance storage, licensing, and binary processing belong to
`assets/pipeline-v0`.

After a successful edit:

```text
choose effective Brand Kit
  -> preflight_scene
  -> commit preflight-derived operations by default
  -> export preview with ExportPurpose::AgentCritique
  -> call VisualCritic
  -> apply critic repair edit until pass or max_iterations
```

The effective Brand Kit rule is:

- use the provided kit when supplied
- if the scene has token references and no kit was supplied, load
  `platform_default_brand_kit()`
- keep the selected kit active for later repair iterations, even after tokens
  have been resolved into concrete styles
- if a scene already carries a brand-kit reference and no actual kit is needed
  for token resolution, report the reference to the critic as document context
- concrete non-token scenes may preflight without a kit

The visual critic is only called after successful preflight and preview export.
The critic receives rendered artifacts, page IDs, scene/page/slot summary,
diagnostic views, prompt context, and full brand-kit summary.

Preview artifacts are validated before the critic is called:

- at least one artifact must exist
- visual critique previews must be PNG or SVG
- every preview artifact must contain non-empty bytes

Invalid previews stop the loop with `ExportFailed` and an `AgentDiagnostic`
instead of sending unusable data to the critic.

## Operation Boundary

Agents do not directly mutate scenes through hidden paths.

- DSL emits operations through the compiler.
- Structured edits are core `Operation` batches.
- Asset tools may return operations, which are checked before commit.
- Preflight-derived brand/token/layout changes are returned as operations and
  committed by default so computed geometry and brand resolution are visible to
  downstream persistence.

If a caller wants to keep preflight as a read-only preview gate, set
`AgentLoopOptions::commit_preflight_operations` to `false`.

For V0, automatic visual repair loops are disabled when
`commit_preflight_operations` is `false`. A preview can still be generated, but
critic-requested repair edits stop with `CritiqueFailed` unless
`allow_visual_repairs_without_preflight_commit` is explicitly enabled. This
avoids applying repairs to an authoring scene that differs from the preflighted
preview scene the critic saw.

## Edit Surface Recommendation

`recommend_edit_surface(intent, context)` is a conservative helper, not a mature
policy engine. It returns:

- `AssetTool` for asset generation or placement intent
- `StructuredOps` for known node, slot, page, export, or brand targets
- `Dsl` for creation/composition
- `ExternalPlanner` for ambiguous or explicitly planner-required requests

The richer DSL-versus-ops policy is intentionally deferred until real agent
usage and future DSL edit-directive work clarify targeted edit semantics.

## Read And Query Helpers

The crate exposes read-only summaries for agent tools and future API wrappers:

- `summarize_document(scene)`
- `summarize_page(scene, page_id)`
- `summarize_slots(scene)`
- `summarize_node_tree(scene, page_id)`
- `query_geometry(scene, node_id)`
- `query_slot_bindings(scene, slot_key)`

These helpers expose node hierarchy, per-page summaries, slot bindings, computed
geometry, and fit/overflow state where present. They do not replace core scene
semantics.

## Result DTOs

`AgentTurnResult` remains the rich Rust-side result. `AgentTurnResult::to_dto()`
produces a stable JSON-style envelope for API/runtime use. It includes:

- schema version
- status and stop reason
- iteration traces
- DSL compile summary
- operation application summaries
- preview artifact summaries
- diagnostic views
- final/effective brand-kit summary
- repair-loop status

The DTO is intentionally boring and summary-oriented. Persistence should store
canonical scene JSON, operation JSON, snapshots, template revisions, diagnostics
JSON, and asset refs through `api/persistence-v0`; the agent DTO is an
orchestration response, not the source of truth.

Diagnostic views are split into:

- `audit`: all diagnostics accumulated during the turn
- `current`: diagnostics from the current pass/iteration
- `latest`: deduped latest diagnostics by source/code/subject

Critic requests receive current/latest views so stale warnings from earlier
iterations do not dominate repair suggestions.

## Stop Reasons

`AgentStopReason` is the stable high-level state for orchestration:

- `Completed`: visual critic passed, or visual critique was disabled after a
  successful preview.
- `DslHalted`: DSL compile/parse/lower diagnostics contain an error.
- `OperationFailed`: checked structured operation application failed.
- `AssetToolFailed`: asset tool was unavailable or failed.
- `PreflightFailed`: scene, brand, token, slot, or layout preflight failed.
- `ExportFailed`: preview export failed or returned export errors.
- `CritiqueFailed`: critic rejected the design or requested repair without an
  edit.
- `MaxIterations`: critic kept requesting repair until the loop limit.

Agent-specific issues use `AgentDiagnostic`. Core diagnostics pass through
unchanged as `Diagnostic`; no new `Phase::Agent` is added to `lumen-core`.

## Tool Contracts

`VisualCritic` is intentionally synchronous and mockable in V0. The Python
runtime can wrap an LLM/multimodal provider and implement this trait or call an
equivalent serialized boundary.

`AssetTool` is also synchronous and mockable. It returns:

- status
- optional asset ID
- MIME type
- provenance and license hints
- operations to place/replace/update scene nodes
- agent diagnostics

This lets the agent loop validate asset-placement operations now without
owning storage or generation.

## Verification

The crate-level tests cover:

- DSL cascade halt stopping before preflight/export/critique
- platform default Brand Kit selection for tokenized scenes
- sticky full brand-kit summary across visual repair iterations
- preflight errors blocking preview and critic calls
- preview artifact validation before critic calls
- structured operation failure blocking preview
- visual critic repair loops and max-iteration stop
- visual repairs guarded when preflight operations are not committed
- unavailable asset tool behavior
- asset tool placement operations applied through checked core operations
- conservative edit-surface recommendation
- read/query helper summaries
- DTO and diagnostic-view summaries
