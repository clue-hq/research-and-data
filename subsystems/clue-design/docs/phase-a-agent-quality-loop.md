# Phase A: Product-Grade Agent Quality Loop

This branch builds the production agent-quality loop above the deterministic
engine contracts that already exist in `lumen-core`, `lumen-agent`,
`lumen-export`, and the FastAPI persistence surface.

The goal is not to add new scene semantics. The goal is to make the agent a
real design collaborator: it should retrieve the right knowledge, write Lumen
DSL, compile and preview the result, visually critique it, repair it, and store
the full trace.

## Product Objective

Turn:

```text
prompt -> DSL -> compile/preflight/export
```

into:

```text
user request
  -> orchestrator loads task knowledge and makes a plan
  -> DSL author writes a small block
  -> deterministic tools compile/apply/preflight/export preview
  -> visual reviewer inspects the rendered SVG/PNG and structured diagnostics
  -> orchestrator passes reviewer feedback verbatim to the DSL author
  -> author repairs through DSL or structured operations
  -> loop repeats until accepted or stopped
  -> full trace is persisted
```

## Branch Boundary

This branch owns the LLM runtime and orchestration boundary.

It may add:

- DeepAgents runtime wrapper.
- Model-provider configuration.
- Agent prompts and skills.
- Knowledge retrieval/indexing over local product docs.
- Tool adapters around existing engine/API/export calls.
- Structured critique/result DTOs.
- Run trace persistence for prompts, knowledge, DSL, operations, previews,
  diagnostics, critique, repair, and acceptance.

It must not add:

- New scene model fields.
- New core operation semantics.
- New layout semantics.
- New slot runtime semantics.
- Production asset storage/provider behavior.
- Editor UI productization.

If the agent needs a capability the engine cannot express, record that as a
gap for later phases rather than adding hidden runtime mutation.

## DeepAgents Shape

Use a top-level coordinator and focused subagents.

### Coordinator

Responsibilities:

- Interpret the user request.
- Select and load relevant knowledge docs.
- Decide the task plan and artifact target.
- Call the DSL author subagent with the loaded context.
- Run deterministic compile/preflight/export tools.
- Call the visual reviewer subagent with the rendered preview.
- Pass reviewer findings verbatim to the DSL author for repair.
- Maintain a todo/checklist for each run.
- Stop only on acceptance, max iterations, unrecoverable tool failure, or user
  interruption.

The coordinator should not directly mutate the scene. All design changes go
through DSL blocks or structured operation tools.

### DSL Author Subagent

Responsibilities:

- Read the Lumen DSL skill and relevant knowledge snippets.
- Produce conservative, compiler-valid Lumen DSL.
- Keep authoring blocks small enough for cascade-halt repair.
- Use stable IDs, two-space indentation, semantic slot keys, and brand tokens
  where appropriate.
- Prefer DSL for initial composition.
- Prefer structured operations only when the coordinator identifies a precise
  node/slot/page target.
- Repair the smallest failing block after compiler/preflight/critic feedback.

The DSL author should receive reviewer findings verbatim plus the current
diagnostics and run summary. It should not receive hidden paraphrases that lose
specific visual targets.

### Visual Reviewer Subagent

Responsibilities:

- Inspect SVG/PNG preview artifacts.
- Compare output against the original user request, artifact goal, brand
  context, page dimensions, and layout expectations.
- Produce structured issues with severity, category, target page/node if known,
  and concrete repair guidance.
- Decide whether the design is accepted.

Review categories:

- hierarchy
- spacing
- alignment
- contrast
- clipping
- overflow
- brand fit
- visual balance
- semantic/slot coverage
- request satisfaction

The reviewer should be strict. A design that merely compiles is not accepted if
it looks visibly broken, clipped, off-brand, unreadable, or incomplete.

## Skill Files

Add a local skill for Lumen DSL authoring:

```text
agents/skills/lumen-dsl-design/SKILL.md
```

It should contain:

- Lumen scene/operation/DSL source-of-truth rules.
- Supported DSL grammar and properties.
- Supported directive status.
- Token guidance.
- Slot guidance.
- Layout guidance.
- Diagnostic/repair behavior.
- Design quality checklist.
- Agent behavior rules.

Add a reviewer skill:

```text
agents/skills/lumen-visual-review/SKILL.md
```

It should contain:

- Review rubric.
- Acceptance criteria.
- Common failure modes from the product gap analysis.
- How to produce structured visual issues.
- How to distinguish engine limitations from authoring mistakes.

Skills are runtime prompt assets. They do not replace reference docs or engine
tests.

## Knowledge Documents

Every nontrivial design run should load relevant local knowledge before DSL
authoring.

Baseline knowledge:

- `reference_docs/ABM-Design-Engine-Temporary-Spec.md`
- `reference_docs/Brilliant-Reverse-Engineering-Report.md`
- `docs/dsl-compiler.md`
- `docs/agents-design-loop.md`
- `docs/preflight-pipeline.md`
- `docs/slots-layout.md`
- `docs/assets-pipeline.md`
- `docs/phase4-integration.md`

Quality benchmark knowledge:

- `reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md` when available.

Task-specific retrieval should prefer small excerpts over dumping whole files
into every prompt. The coordinator owns retrieval and should record which
knowledge snippets were loaded.

## Lumen Agent Documentation System

The current two skills are only the Phase A runtime scaffold. The next step is
to build a Lumen app-level and agent-level documentation system modeled on the
Brilliant documentation tree at:

```text
/Users/aryankeshri/Documents/brilliant-design/brilliant
```

Brilliant's useful pattern is not just one `SKILL.md`; it is a structured
knowledge filesystem that agents can retrieve from:

```text
knowledge/
  blueprint/
  design/
  design-systems/
  images/
  reference/
  svg/
  webgl/
skills/
```

Lumen should adopt the same shape in product terms, while translating the
content to Lumen's actual architecture:

```text
apps/agent_runtime/knowledge/
  lumen-dsl/
  design/
  design-systems/
  assets/
  reference/
  export/
  agent-loop/
  future/
apps/agent_runtime/skills/
  lumen-dsl-design/
  lumen-visual-review/
  lumen-design-system-authoring/
  lumen-asset-guidance/
  lumen-agent-repair/
```

The docs should distinguish three states clearly:

- **Supported now**: features implemented in Lumen's DSL, scene model, layout,
  brand-kit, export, and agent loop.
- **Recognized but not lowered**: syntax or concepts the compiler parses or
  warns about but does not fully implement yet.
- **Future scaffold**: product-grade features that Brilliant documents and
  Lumen plans to build later, such as richer edit directives, advanced effects,
  charts, WebGL/shader effects, richer image tools, sophisticated design-system
  authoring, and print-grade typography.

Do not omit a documentation category just because Lumen does not support the
full feature yet. Create the scaffold and mark the current capability level.
This prevents the DeepAgent from learning an incomplete map of the product and
gives future workstreams a place to fill in details as the engine matures.

During the documentation migration session, the DeepAgent runtime should be able
to read both:

- the new Lumen knowledge tree in this worktree, and
- the Brilliant reference tree above for comparison while authoring Lumen docs.

Production runs should rely on Lumen-authored docs, not raw Brilliant docs, so
the agent does not assume unsupported Brilliant-only semantics.

## Tool Surface

The DeepAgents runtime should call tools around existing deterministic
boundaries.

Required tools:

- `read_knowledge(query)`: return selected local docs/snippets with provenance.
- `compile_dsl_block(source)`: compile through `DslCompileSession`.
- `apply_operations(operations)`: apply checked core operations.
- `preflight_scene()`: choose effective brand kit and run canonical preflight.
- `export_preview(format)`: export SVG/PNG preview for critic.
- `review_preview(preview, context)`: call visual reviewer.
- `summarize_scene()`: document/page/slot/node/geometry summaries.
- `persist_trace(event)`: store run trace events.

Later tools:

- `select_fixture_asset(...)`
- `generate_image(...)`
- `vectorize_image(...)`
- `structured_patch(...)`

The runtime can start with local file/process-backed tools and later move the
same contract behind FastAPI routes.

## Authoring Protocol

The coordinator should enforce block-by-block authoring:

1. Load knowledge.
2. Ask DSL author for one page or one coherent region at a time.
3. Compile block.
4. If compile halts, pass line/code/hint/applied-count to the author and repair.
5. If compile succeeds, preflight.
6. If preflight fails, pass diagnostics to the author and repair.
7. Export preview.
8. If preview is invalid, stop with export failure.
9. Reviewer inspects preview.
10. If accepted, finish.
11. If rejected, pass reviewer feedback verbatim to author and repair.

Maximum iterations should be configurable. The default should be conservative
for cost and debugging, for example three visual repair iterations after the
first preview.

## Structured Critique Schema

The visual reviewer should return a machine-readable result:

```json
{
  "accepted": false,
  "summary": "The headline overflows the right edge and the CTA is too low.",
  "issues": [
    {
      "severity": "error",
      "category": "clipping",
      "target": {
        "page_id": "page_square",
        "node_id": "headline"
      },
      "message": "Headline text is clipped on the right edge.",
      "suggested_repair": "Reduce headline font size to 48 and width to 920, or wrap into two lines."
    }
  ],
  "repair_instruction": "Keep the existing square layout. Repair only the headline and CTA spacing.",
  "acceptance_notes": []
}
```

Reviewer text should be persisted exactly as returned. The coordinator may add a
summary, but should not replace the verbatim reviewer feedback sent to the DSL
author.

## Trace Persistence

Persist a trace event for each meaningful step:

- run started
- knowledge loaded
- plan created
- DSL block requested
- DSL block produced
- compile result
- operations applied
- preflight result
- preview exported
- critique result
- repair requested
- run accepted/failed/max-iteration

Each event should include:

- run ID
- iteration
- timestamp
- actor/subagent
- input summary
- output summary
- diagnostics
- artifact refs or local paths
- raw DSL/critique where relevant

This trace is required because Phase A is meant to reveal what engine gaps are
actually blocking product-quality output.

## Model Configuration

Use `.env` for runtime configuration:

```text
LUMEN_AGENT_MODEL=openai:anthropic/claude-opus-4.8
LUMEN_AGENT_BASE_URL=https://openrouter.ai/api/v1
LUMEN_AGENT_API_KEY=...
LUMEN_AGENT_MAX_ITERATIONS=3
LUMEN_AGENT_PREVIEW_FORMAT=svg
```

OpenRouter is the sole LLM gateway — every call routes through it and there is no
native-provider fallback. `LUMEN_AGENT_MODEL` selects the model only and must be an
`openai:<openrouter-model-id>` value. See the README's "Choosing a model / provider"
section for the full contract; `init_model` rejects a missing key or a non-`openai:`
prefix loudly.

Provider-agnosticism sits behind a single adapter (`providers.init_model`) that
binds the chosen model to the OpenRouter gateway.

## Acceptance Criteria

This branch is ready when:

- A user prompt can run through DeepAgents orchestration.
- The coordinator loads knowledge before authoring.
- The DSL author produces Lumen DSL.
- The compiler/session path preserves cascade-halt repair behavior.
- Preflight/export diagnostics are fed back into repair.
- SVG or PNG preview is generated before visual acceptance.
- The visual reviewer can reject a bad preview and produce structured repair
  feedback.
- Reviewer feedback is passed verbatim to the DSL author.
- At least one rejected first draft can be repaired into an accepted output.
- The full run trace is persisted locally or through the API.
- Tests cover compile failure, preflight failure, preview failure, reviewer
  rejection, successful repair, and max-iteration stop.

## Current Implementation Baseline

The branch currently has the first scaffold for Phase A:

- `apps/agent_runtime/lumen_deepagent` defines a DeepAgents runtime package.
- `create_lumen_design_agent(...)` creates a coordinator with DSL-author and
  visual-reviewer subagents.
- `lumen-dsl-design` and `lumen-visual-review` skills exist.
- Local knowledge retrieval now prioritizes a Lumen-authored knowledge tree and
  keeps product/reference docs as secondary context.
- Python tools call the Rust/API bridge for DSL compile, preflight, SVG/PNG
  export preview, scene summary, and JSONL trace writing.
- `lumen-api-helper` exposes `compile_dsl_into_scene` and `export_preview`.
- Runtime tools now return stable DTO-shaped JSON for knowledge, compile,
  operations, preflight, export, critique, repair, summaries, and gaps.
- The runtime defines `AgentRunState`, `AgentIteration`,
  `AuthoringBlockRequest`, `AuthoringBlockResult`, `CompileRepairContext`,
  `PreviewTarget`, `QualityGateResult`, and `StopReason` DTOs for typed
  orchestration state.
- Preview export validates SVG/PNG byte shape before critique can proceed.
- The typed loop also compares square/aspect-ratio requests against actual
  exported page dimensions when the request is known.
- `get_latest_preview_for_critique` returns reviewer-ready preview payloads:
  SVG text for SVG artifacts and base64 for PNG artifacts, with page/dimension
  metadata.
- `export_preview_bundle` stores canonical SVG and, when configured, a separate
  raster/PNG critic preview beside it.
- `LumenQualityLoop` provides a deterministic block-by-block loop over author
  and reviewer protocols so Phase A behavior can be tested without live model
  calls.
- `LangChainDslAuthor` and `LangChainVisualReviewer` can plug live model calls
  into the typed loop. The CLI supports:

```text
python -m lumen_deepagent.cli --mode quality-loop "<prompt>"
```

The original DeepAgents coordinator path remains available with:

```text
python -m lumen_deepagent.cli --mode deepagent "<prompt>"
```

- `lumen-core` and `lumen-api-helper` now expose a serializable
  `DslCompileSessionSnapshot`, so separate Python/helper calls can preserve
  parser context and parent-stack continuation across successful DSL blocks.
- Run traces now write `input.json`, `knowledge.json`, per-iteration files,
  `gaps.json`, and `final.json`.
- Phase A fixture prompts live at
  `apps/agent_runtime/evaluation/fixture_prompts.json`.
- `python -m lumen_deepagent.eval_traces --trace-root .lumen-runs` summarizes
  accepted/failed counts, stop reasons, issue/gap categories, and preview
  paths.
- Tests prove the scaffold, DeepAgents factory wiring, helper bridge, local
  tool state, compile repair, preflight repair, preview validation, critic
  preview payload loading, visual rejection/repair, invalid-preview fail-closed
  behavior, requested-aspect-ratio mismatch, trace evaluation, and
  max-iteration stop without using a live model provider.

Phase A A0-A9 is implemented in this branch. The deterministic runtime now
enforces the production quality gate, and the provider path has been smoke
tested with a live Anthropic model when `.env` enables it.

Current implementation notes:

- Session snapshots intentionally advance only after successful checked
  application. If a block halts or produces an operation error, the helper
  returns the previous session snapshot so the runtime does not believe
  unapplied partial lines exist in the canonical scene. Agents should repair
  the failed block rather than continue from unapplied partial state.
- Authoring requests include selected knowledge excerpts, not only document
  paths. This is required because provider models otherwise guess unsupported
  brace-based DSL syntax.
- PNG/raster previews are passed to vision-capable reviewers as image content
  blocks with compact text metadata. Base64 bytes must not be embedded in the
  JSON text prompt.
- Normal deterministic verification should set `LUMEN_AGENT_RUN_LIVE=0`. The
  live provider smoke is gated by `LUMEN_AGENT_RUN_LIVE=1` and
  `LUMEN_AGENT_API_KEY` (the OpenRouter key).

## Production Implementation Plan

Phase A should be implemented as a sequence of small but complete product
surfaces. Each step should keep deterministic design semantics in Rust and keep
the DeepAgents runtime as orchestration only.

### A0. Freeze The Phase A Boundary

Goal:

- Make it impossible for this branch to solve agent failures by adding hidden
  scene mutation or ad hoc renderer behavior.

Deliverables:

- Keep all design mutations behind DSL compilation or structured core operation
  tools.
- Keep generated previews behind `lumen-export` or explicit preview adapters.
- Add a short runtime boundary note in `apps/agent_runtime/AGENTS.md`.
- Add tests or assertions that tool methods update `self.scene` only from core
  helper responses.

Done when:

- The runtime can explain every scene change as a compiled DSL block or a core
  operation batch.
- No DeepAgents prompt or Python helper directly edits node/page/slot fields.

### A1. Build The Lumen Agent Knowledge System

Goal:

- Replace the current one-skill grammar prompt with a retrieved documentation
  system modeled on Brilliant's knowledge tree, but translated to Lumen's
  actual capabilities.

Why:

- Brilliant's output quality comes partly from mandatory task-specific
  knowledge loading. The model is not expected to remember every layout,
  typography, color, image, and DSL convention.

Deliverables:

- Create a Lumen-authored knowledge tree:

```text
apps/agent_runtime/knowledge/
  lumen-dsl/
  design/
  design-systems/
  assets/
  reference/
  export/
  agent-loop/
  future/
```

- Add docs for:
  - DSL grammar and supported authoring patterns.
  - Layout recipes for ads, one-pagers, brochures, cards, email headers, and
    direct mail artifacts.
  - Typography rules for readable hierarchy with current Lumen text limits.
  - Brand/token usage and fallback behavior.
  - Visual critique rubric and repair patterns.
  - Asset placement guidance using fixture or registered assets.
  - Unsupported/future capabilities explicitly marked as future scaffolds.
- Every doc should label features as:
  - `supported now`
  - `recognized but not lowered`
  - `future scaffold`
- Extend `read_knowledge(...)` so it indexes these docs first and uses the
  product gap analysis/reference docs as secondary context.
- Record loaded knowledge snippets in the run trace with path, title, score,
  excerpt, and why they were selected.

Done when:

- A nontrivial design run loads at least one artifact/layout doc, one DSL doc,
  and one quality/critique doc before authoring.
- The DSL author receives Lumen-specific knowledge, not raw Brilliant docs as
  primary instructions.
- Tests prove retrieval priority, provenance, and missing-doc tolerance.

### A2. Define A Real Run State And Authoring Protocol

Goal:

- Make the coordinator run a deterministic block-by-block workflow instead of
  asking for one whole design and hoping it passes.

Why:

- The product gap analysis identifies Brilliant's one-block-at-a-time protocol
  as the missing control surface. This is what makes cascade halt, parent-stack
  continuation, and visual repair useful to the model.

Deliverables:

- Add DTOs for:
  - `AgentRunState`
  - `AgentIteration`
  - `AuthoringBlockRequest`
  - `AuthoringBlockResult`
  - `CompileRepairContext`
  - `PreviewTarget`
  - `QualityGateResult`
  - `StopReason`
- Add a coordinator loop that executes:

```text
load knowledge
plan artifact and preview targets
request one DSL block
compile/apply block
repair compile errors if needed
preflight
repair preflight errors if needed
export preview
validate preview artifact
critique preview
repair visual issues if needed
accept or stop
```

- Preserve `DslCompileSession` behavior through the core/session tool path so
  a repair block can continue from the last valid parent context.
- Include preview target IDs in authoring requests, for example page ID and
  intended node/region IDs.
- Add explicit max-iteration handling with a persisted `max_iterations_reached`
  stop reason.

Done when:

- The runtime has a typed loop object, not only a generic DeepAgents prompt.
- A compile-halt repair can continue from the failed block without restarting
  the whole design.
- Tests cover first-block success, compile halt, repair success, and
  max-iteration stop.

### A3. Harden Deterministic Tool Contracts

Goal:

- Make every model-facing tool return stable, boring JSON with enough
  information for repair and audit.

Why:

- Raw helper responses are useful internally, but product orchestration needs
  consistent summaries that do not leak Rust internals or omit repair-critical
  context.

Deliverables:

- Add normalized tool DTOs for:
  - knowledge loaded
  - DSL compile summary
  - operation application summary
  - preflight summary
  - export summary
  - scene/page/node/slot/geometry summary
  - diagnostics summary
- Include diagnostic severity, code, message, line/span if available, target
  page/node/slot when available, and suggested repair when available.
- Add preview artifact validation before the reviewer is called:
  - at least one artifact exists
  - artifact format matches configured visual format
  - bytes are non-empty
  - SVG has an `<svg` root or PNG has a valid PNG header
  - page IDs and byte lengths are recorded
- If preview validation fails, stop as `preview_invalid` or `export_failed`;
  do not call the visual reviewer.
- Add read-only query helpers:
  - `summarize_document`
  - `summarize_page`
  - `summarize_slots`
  - `summarize_node_tree`
  - `query_geometry`
  - `query_slot_bindings`

Done when:

- The coordinator can make repair decisions without parsing arbitrary helper
  output.
- Tests cover malformed preview artifacts and prove the critic is not called.
- Tool JSON is stable enough for API persistence to store as trace events.

### A4. Add Raster/Screenshot Preview For Visual Critique

Goal:

- Give the visual critic a real rendered artifact, not only a success flag or
  raw SVG text.

Why:

- The demo failures were visual failures: clipping, scale mismatch, awkward
  hierarchy, and unreadable composition. Structural validation alone cannot
  catch these.

Deliverables:

- Keep SVG export as the canonical preview artifact.
- Add a raster-preview path for critic input:
  - preferred: render SVG to PNG through an adapter available in CI/dev
  - fallback: provide SVG plus a deterministic screenshot/raster reference when
    PNG rendering is unavailable
- Store both:
  - original export artifact
  - critic preview artifact
- Add metadata:
  - page ID
  - requested dimensions/aspect ratio
  - actual viewport/canvas dimensions
  - render scale
  - byte length
  - local path or API asset ref
- Add a visual-preview validator that can detect:
  - missing artifact
  - empty artifact
  - invalid image/SVG format
  - page-size mismatch against the user request when known

Done when:

- The visual reviewer is called with a usable SVG/PNG artifact and dimension
  metadata.
- A square-ad request can be flagged if preview dimensions are not square.
- Tests cover SVG preview and, where dependencies allow, PNG/raster preview.

### A5. Implement The Real Visual Critic Gate

Goal:

- Replace no-op acceptance with a strict visual acceptance decision.

Why:

- Phase A exists specifically to prevent "export succeeded" from becoming
  "design accepted."

Deliverables:

- Keep `VisualCritique` as the stable schema, but harden it:
  - severity: `info`, `warning`, `error`, `blocker`
  - category enum aligned with the product gap analysis
  - target page/node/slot fields
  - suggested repair
  - acceptance decision
  - confidence
  - requirement coverage notes
- Add an adapter for a vision-capable model call. It should receive:
  - original user request
  - loaded knowledge summary
  - scene summary
  - diagnostics from current iteration
  - preview artifact(s)
  - page/artifact constraints
  - previous critique/repair attempts
- The reviewer must reject when:
  - critical clipping/overflow is visible
  - requested artifact dimensions are wrong
  - required message/CTA/brand concept is missing
  - contrast/readability is unacceptable
  - obvious composition balance is poor
- Persist the critic's raw structured response verbatim.
- The coordinator may summarize the critique for the user, but the DSL author
  must receive the exact reviewer findings.

Done when:

- A mocked critic rejection causes a repair request and another compile/preview
  pass.
- A mocked critic acceptance ends the run successfully.
- A malformed critic response fails closed and is persisted as a critic error.
- Optional provider smoke test can run when API keys are present.

### A6. Add Verbatim Repair Handoff And Edit-Surface Recommendation

Goal:

- Turn diagnostics and visual issues into repair work without losing the
  precise target or accidentally regenerating unrelated parts of the design.

Why:

- The product needs repairable iterations. The author should fix the smallest
  failing block, not rewrite the whole page every time.

Deliverables:

- Add a conservative edit-surface recommendation helper:
  - creation/composition -> DSL
  - known node/page/slot target -> structured operations when available
  - asset generation/selection -> asset tool
  - unsupported/future behavior -> external planner/gap record
- Add `RepairRequest` DTO with:
  - original user request
  - exact reviewer feedback
  - current diagnostics
  - target page/node/slot IDs
  - current scene summary
  - allowed edit surface
  - forbidden changes
- Add trace events:
  - `repair_requested`
  - `repair_block_produced`
  - `repair_compile_result`
  - `repair_preview_result`
- Keep current DSL limitations explicit. If repair needs an unsupported
  directive, record it as a gap rather than inventing runtime mutation.

Done when:

- Reviewer feedback is passed verbatim to the DSL author in tests.
- A targeted repair does not remove unrelated existing nodes.
- Unsupported repair needs produce a clear stop/gap event.

### A7. Persist Product-Grade Run Traces

Goal:

- Make every generated design auditable and useful for later engine/product
  improvement.

Why:

- Phase A is also a discovery system: it should reveal which layout/text/DSL
  gaps actually block quality output.

Deliverables:

- Extend local JSONL trace persistence into a complete run directory:

```text
.lumen-runs/<run_id>/
  trace.jsonl
  input.json
  knowledge.json
  iterations/
    001/
      author_request.json
      dsl.lumen
      compile.json
      preflight.json
      preview.svg
      preview.png
      critique.json
      repair_request.json
  final.json
```

- Each event should include:
  - run ID
  - iteration
  - actor/subagent
  - event type
  - timestamp
  - input/output summaries
  - diagnostics
  - artifact refs
  - raw DSL/critique where relevant
- Add final run summary:
  - accepted/rejected/max-iteration/tool-failed
  - final preview path
  - final scene summary
  - unresolved diagnostics
  - unresolved visual issues
  - gaps discovered
- Keep the local format compatible with later API persistence.

Done when:

- A full design run can be debugged from the trace without rerunning the model.
- Tests verify trace files and final summary are written for success and
  failure paths.

### A8. Add CLI, Evaluation Fixtures, And Quality Gates

Goal:

- Make Phase A runnable and testable repeatedly, not only through ad hoc
  manual prompts.

Deliverables:

- Keep the CLI:

```text
python -m lumen_deepagent.cli "<prompt>"
```

- Add fixture prompts covering:
  - square LinkedIn ad
  - A4 one-pager section
  - email hero
  - direct-mail postcard or letter header
  - brand-token-heavy card
  - intentionally bad/repair-triggering prompt
- Add mocked model scenarios:
  - compile failure then repair
  - preflight failure then repair
  - preview failure
  - critic rejection then accepted repair
  - max iterations
- Add optional real-provider smoke test gated by environment:
  - `LUMEN_AGENT_API_KEY` (the OpenRouter key)
  - `LUMEN_AGENT_MODEL`
  - `LUMEN_AGENT_RUN_LIVE=1`
- Add a local evaluation script that prints:
  - accepted count
  - failed count
  - unresolved issue categories
  - generated preview paths

Done when:

- Deterministic tests pass without network/model access.
- A live smoke command can run when keys are configured.
- The branch can produce at least one visually reviewed and trace-backed
  artifact from a realistic prompt.

### A9. Feed Discovered Gaps Back Into The Product Roadmap

Goal:

- Use Phase A as the evidence source for the next product phases.

Deliverables:

- Add a `gap_recorded` trace event type.
- Map gap records to product-gap areas:
  - agent protocol
  - knowledge loading
  - DSL/edit language
  - layout
  - text/typography
  - design system
  - rendering/export/preview
  - assets
  - scene model
- Update branch memory with durable gaps that need Phase B/C/D work.
- Do not patch around core gaps inside prompts when an engine fix is required.

Done when:

- A failed run can explain whether the blocker is an authoring mistake, missing
  knowledge, missing DSL feature, layout/text engine limitation, preview/export
  issue, or model/provider failure.

## Implementation Order

1. Complete A0 boundary hardening.
2. Build A1 Lumen knowledge tree and retrieval priority.
3. Implement A2 typed run state and block-by-block coordinator loop.
4. Harden A3 deterministic tool DTOs and preview validation.
5. Add A4 raster/screenshot preview support.
6. Implement A5 visual critic gate.
7. Add A6 repair handoff and edit-surface recommendation.
8. Expand A7 trace persistence.
9. Add A8 evaluation fixtures and optional live smoke path.
10. Use A9 gap records to drive Phase B and later product work.

All A0-A9 items above are implemented for the Phase A product loop. Later
product phases should improve the engine capabilities surfaced by the traces,
for example richer DSL edit directives, stronger text/layout behavior, custom
page dimensions, deeper design-system authoring, and production asset runtime.
Those are downstream product gaps, not unfinished Phase A orchestration work.

## Known Risks

- The current DSL still lacks some product-grade layout/text affordances. Phase
  A should surface these as structured failures, not hide them.
- Provider-specific multimodal transport can regress. The runtime must keep
  rendered SVG/PNG preview input available to the reviewer without embedding
  large raster bytes in ordinary text prompts.
- Knowledge loading can bloat prompts. Retrieval should be selective and
  provenance-backed.
- DeepAgents orchestration must not become a second source of scene truth.
