# C6 — platform deepagent, isolated workspace, and skills

**Status:** IN PROGRESS — C6.0 contract freeze and dependency spikes complete (2026-07-26)
**Layer:** Phase C / harness build step 6
**Depends on:** C1–C5 complete; C4 governed Stage 0; C5 durable execution
**Branch:** `platform/c6-deepagent-runtime`
**Detailed plan:** [2026-07-26 Phase C6 implementation plan](../superpowers/plans/2026-07-26-phase-c6-platform-deepagent.md)

**Architecture authority:** [Doc A](../architecture/clue-hq-platform-agent-runtime.md), especially
§1.4, Parts II–III, and §3a; the
[harness architecture](../architecture/clue-hq-harness-architecture-and-requirements.md), especially
§2.5, REQ-02, REQ-18–REQ-22, and build step 6; the
[Phase C parent](./PC-phase-c-agentic-layer.md) §3.6 and C6; the
[C5 child spec](./PC-C5-run-graph-recipes-executor.md).

This child spec records the engineering contract for C6. It may refine file placement and
implementation types while work proceeds, but it may not weaken the authority, isolation,
durability, or honest-agency decisions below.

---

## 1. Outcome

C6 builds the real Head-of-ABM deepagent over the platform's existing governed substrate:

- a real `deepagents`/LangGraph orchestrator, not a scripted questionnaire or renamed pipeline;
- explicit, minimal tool surfaces over the existing toolbelt;
- fresh-wake research, content, and review subagents;
- deterministic seven-layer context assembly;
- an isolated filesystem workspace that is the record of the agent's work;
- versioned, folder-backed prompts, skills, and profiles;
- plan validation and authority enforcement before execution;
- tool, context, delegation, resource, and finalization history anchored in C5;
- honest turn finalization;
- a governed per-account research-agent unit inside the existing fleet shell.

The agent decides which permitted tools to call, in what order, and with what parameters. Engine
code and humans continue to own spend, gates, source trust, claim promotion, policy, fan-out, and
durable domain truth.

### 1.1 Explicitly not C6

- the frontend project/thread/tab shell;
- a new claim, memory, recipe, fleet, or domain-state store;
- a second orchestration engine competing with C5;
- arbitrary user-authored agents or executable skills;
- arbitrary shell, subprocess, Python, JavaScript, or source-code execution;
- provider SDK or credentials inside `clue_agents`;
- prompt bodies stored in a database, LangSmith, Langfuse, or another hosted prompt hub;
- copying application source code, Python packages, migrations, or repository implementation into
  an agent workspace;
- weakening C4 readiness, C5 replay, compliance, verification, or human-gate behavior.

---

## 2. Baseline C6 may assume

- `platform/agents/clue_agents` exists as an import-contracted scaffold.
- C4 provides a metadata-only Stage-0 skill loader and a governed Stage-0 workload.
- C5 provides exact-version tool descriptors, strict typed results, stable operation ids,
  append-only execution history, immutable recipes, exact pins, dynamic tool-child append,
  crash-resumable execution, supervision, and complete run views.
- Recipe #0 v2 and Recipe #1 v2 are executable through C5.
- The toolbelt is the sole domain write path and is composed in `clue_api`.
- The current `LLMGateway` supports completion and embedding, but does not yet provide the
  tool-calling model interface required by a real deepagent.
- The `deepagents` framework and its model adapter are not yet production dependencies.
- There are no C6 turn, context-bundle, delegation, resource-materialization, or honest-finalize
  records yet.
- Recipe #1 routing remains disabled by default and legacy unowned runs remain supported.

C6 must extend these seams. It must not route around them.

---

## 3. Binding C6 decisions

### C6-D1 — use the real deepagent runtime

The Head-of-ABM and governed worker agents use the real `deepagents`/LangGraph construction
described by Doc A. A hand-written `while model → tool → model` loop, a fixed questionnaire, or a
deterministic call chain named "agent" is rejected.

The framework owns the conversational reasoning loop and checkpointable mind state. C5 continues
to own durable domain-operation graphs, tool execution, pins, attempts, gates, and replay. These
are complementary layers, not competing orchestrators.

### C6-D2 — every agent execution receives a dedicated external workspace

All model-controlled filesystem activity occurs inside one dedicated runtime workspace:

```text
<CLUE_AGENT_WORKSPACE_ROOT>/<workspace_id>/<project_id>/<execution_id>/
```

`CLUE_AGENT_WORKSPACE_ROOT` is a dedicated production data root. It must be outside the Git
worktree, must not be the worktree's parent, child, or the user's home directory, and must not be
used for application imports. The concrete host root is configuration known only to trusted
backend code.

One execution may never reuse another execution's directory. Workspace identity is derived from
validated typed ids, not free-form agent input.

### C6-D3 — `virtual_mode=True` and relative paths are mandatory

The deepagent filesystem backend always runs with `virtual_mode=True`.

The model sees only normalized POSIX-style paths relative to its virtual root, for example:

```text
context/project-card.json
work/research-plan.md
outputs/final-report.md
```

It never receives the host root or an absolute host path. The backend rejects:

- absolute paths;
- drive-qualified or backslash paths;
- empty, `.` or `..` path components;
- NUL/control characters;
- symlinks, hard-link materialization, device files, sockets, and FIFOs;
- canonical paths that escape the execution root;
- access to another workspace, project, or execution;
- access to the repository, process environment, credentials, or host filesystem.

Validation occurs both when the logical path is accepted and when the host path is opened. File
operations must be anchored to the already-open execution root and must not follow links.

### C6-D4 — the runtime workspace contains resources and work, never application code

The first-version workspace layout is:

```text
<execution-root>/
  .deepagent/
    manifest.json
    prompts/
      <role>/<version>/SYSTEM.md
    skills/
      <skill>/<version>/SKILL.md
    profiles/
      <role>/<version>/profile.yaml
  inputs/
  context/
  work/
  delegations/
  outputs/
```

- `.deepagent/`, `inputs/`, and `context/` are materialized read-only.
- `work/`, `delegations/`, and `outputs/` are writable only according to the active role policy.
- No repository package, source file, migration, provider SDK, executable, or implementation
  module is copied or mounted into this tree.
- Prompt and skill resources are text/policy resources, not executable code.
- Executable bits are removed. The V1 file-type allowlist is data/document oriented and rejects
  source-code and executable extensions.
- The runtime exposes no shell, subprocess, package installation, arbitrary-code, or module-import
  tool.

An agent may create research notes, plans, reports, and content artifacts. It may not create or
execute application code in this runtime.

### C6-D5 — prompts, skills, and profiles are folder-backed in V1

The canonical V1 resource catalog is repository-owned and folder-based:

```text
platform/agents/catalog/
  prompts/<role>/<version>/SYSTEM.md
  skills/<skill>/<version>/SKILL.md
  profiles/<role>/<version>/profile.yaml
```

Each resource has an explicit semantic version, strict schema, content SHA-256, declared role,
tool allowlist, and compatibility metadata. Mutable aliases such as `latest` are not valid run
pins.

Prompt or skill bodies are not stored in `config_revision`. Existing config ledgers may govern
profile/reference promotion metadata, but the canonical body remains the versioned folder
resource. LangSmith/Langfuse prompt hubs are future provider adapters and are out of C6 scope.

Catalog access is behind:

- `PromptCatalog`;
- `SkillCatalog`;
- `ProfileCatalog`;
- `AgentResourceMaterializer`.

V1 supplies `FolderPromptCatalog`, `FolderSkillCatalog`, and `FolderProfileCatalog`. A future hub
adapter must return the same validated resource descriptors and materialize the same immutable
runtime layout, so the agent runtime does not change.

### C6-D6 — a run consumes an immutable resource snapshot

At execution start, trusted backend code:

1. resolves exact profile, prompt, and skill versions;
2. validates their schemas and cross-references;
3. verifies the requested tools exist at exact compatible versions;
4. calculates content digests and one aggregate resource-manifest digest;
5. creates a fresh execution root;
6. copies bytes into `.deepagent/` as new read-only files—never symlinks or bind mounts;
7. writes `.deepagent/manifest.json`;
8. pins resource addresses and digests in C5 before the first model call.

The runtime refuses a missing version, digest mismatch, changed body under an existing version,
retired tool, invalid profile, or writable resource snapshot before model spend.

### C6-D7 — files are the work record; Postgres remains domain truth

Workspace files contain the agent's reasoning trail and artifact work. They are not a claim,
memory, project-state, readiness, score, budget, or policy store.

All domain reads use projection/ref tools. All domain writes use toolbelt tools. A fact written
only to a workspace note is not a platform fact. Tool output is a compact receipt of typed refs;
full durable results remain in their owning stores.

Before cleanup, every durable final output is copied through the existing `StorageBackend` and
represented by an artifact/reference. C5 and C6 journals contain ids, hashes, labels, status, and
safe summaries—never raw prompt, context, upload, memory, or personal-data bodies.

### C6-D8 — the tool surface is structural authority

Every role receives a resolved allowlist of exact tool addresses. The deepagent framework is
constructed with only those tools. A disallowed or unavailable tool is absent, not merely
discouraged in a prompt.

Agent-facing tools are adapters over `ToolInvoker` and projections. They:

- derive actor, workspace, project, execution, and operation identity from trusted constitution
  state;
- never accept those authorities from model-controlled arguments;
- validate typed arguments and outputs;
- append/execute through C5;
- return references and bounded receipts;
- propagate precondition, gate, budget, and authority errors without silent degradation.

Subagents receive a strict subset of the delegator's effective authority.

### C6-D9 — model egress remains single and injected

`clue_agents` does not import `clue_gateway`, provider SDKs, API composition, fleets, or
subsystems. C6 adds the smallest provider-neutral tool-calling model contract needed by the real
deepagent, with a deterministic test implementation. `clue_api` injects the concrete gateway/model
adapter and credentials.

The C6.0 framework spike must prove streaming/tool-call behavior, usage/cost attribution,
timeouts, retry semantics, checkpoint compatibility, and deterministic offline tests before the
production dependency is selected.

### C6-D10 — C5 is the durable execution spine

Every agent turn has one durable execution identity. Model calls, compiled plan nodes, tool
invocations, context receipts, delegation nodes, artifacts, and finalization records correlate to
that identity.

The agent may propose a bounded plan, but trusted code compiles it into C5's closed graph language.
Validation rejects unknown tools, bad schemas, cycles, unbounded expansion, ungated externalizing
paths, gate bypass, invalid refs, excessive depth/fan-out, or estimated spend above the envelope
before work is accepted.

The deepagent checkpoint is conversational state only. It cannot claim a domain effect that C5
does not contain.

### C6-D11 — C1's coverage evaluator remains the one independent engine leaf

C6 retains the current C1 `GoalJudge` as the sole advisory coverage evaluator.

- The governed research agent plans gaps, strategies, and whether it believes more work is useful.
- The independent evaluator challenges that proposal at the round boundary.
- Engine code alone enforces evidence, policy, budget, round limits, idempotency, and terminal
  states.
- The agent does not run a second evaluator.
- Evaluator advice is journaled as non-authoritative typed advice and cannot itself set
  `propose_stop`, `filled`, or another terminal state without engine validation.

This preserves one evaluator and avoids a mind grading its own stopping decision.

### C6-D12 — subagents are fresh-wake and filesystem/ref coordinated

V1 registers:

- `research-specialist`;
- `content-drafter`;
- `reviewer`.

Each invocation starts from its pinned system prompt, skills, typed constitution, task prompt, and
explicitly granted files/refs. It receives no hidden prior conversation or private memory.

Small source material may be passed verbatim in the task. Large/canonical content is passed by
workspace-relative path. Domain objects are passed by typed refs. Paraphrase may not replace an
available original.

Durable output lands in an allowed workspace path or through a tool before the subagent returns a
reference. Delegation depth and count are engine-capped. A human gate reached by a child remains a
human gate.

### C6-D13 — rollout is feature-gated and preserves fallback

The C6 runtime is disabled by default. Activation supports an explicit workspace allowlist and a
deterministic percentage canary. A failed/non-finalized C6 turn is visible as failed and does not
fall through to fabricate a successful agent answer.

The existing governed C4 Stage-0 actor and C5 unowned-run behavior remain the fallback until a
separate retirement/backfill decision. The two paths may not concurrently own the same turn or
project execution.

---

## 4. Core contracts

All runtime contracts are strict, frozen, extra-field-forbidden types.

### 4.1 Resource identity

```text
AgentResourceAddress
  kind: prompt | skill | profile
  name
  version
  sha256

AgentResourceManifest
  schema_version
  role
  profile
  prompt
  skills[]
  tools[]              # exact name@version + schema digests
  aggregate_sha256
```

No run accepts a resource by mutable alias or path supplied by the model.

### 4.2 Typed constitution

```text
AgentConstitution
  workspace_id
  project_id
  execution_id
  actor_id
  role
  brand_id
  product_id
  stage_snapshot_ref
  readiness_snapshot_ref
  budget_envelope_ref
  profile_ref
  resource_manifest_ref
  focus_refs[]
```

The constitution is assembled by trusted code and injected into every mind. The model cannot
mutate it. Optional domain ids remain explicit `null`; they are never inferred from a path or
prompt.

### 4.3 Workspace contract

```text
AgentWorkspacePolicy
  virtual_mode = true
  max_total_bytes
  max_file_bytes
  max_file_count
  allowed_extensions
  readable_prefixes_by_role
  writable_prefixes_by_role
  retention_class

AgentWorkspace
  workspace_root_id       # opaque, never host path
  execution_id
  resource_manifest_ref
  created_at
  expires_at
```

The implementation seam is split into:

- `AgentWorkspaceFactory` — validates the configured root and creates an execution workspace;
- `AgentWorkspaceBackend` — normalized relative read/list/write/edit operations;
- `AgentResourceMaterializer` — copies validated catalog resources and context inputs;
- `AgentWorkspaceFinalizer` — freezes outputs, stores durable artifacts, and applies retention.

### 4.4 Context receipt

The deterministic assembler emits a model-ready bundle and a separate durable receipt:

```text
ContextBundleReceipt
  context_bundle_id
  execution_id
  layer_receipts[1..7]
    layer
    source_refs[]
    materialized_paths[]
    sha256s[]
    token_count
    excluded_refs[]
    exclusion_reason_codes[]
  aggregate_sha256
```

Only the receipt is journaled. Bodies are materialized read-only under `context/` or passed in
the model request and remain governed by their owning stores.

### 4.5 Delegation and finalization

```text
DelegationRequest
  parent_execution_id
  subagent_role
  task_artifact_ref
  granted_paths[]
  domain_refs[]
  child_envelope_ref
  resource_manifest_ref

AgentFinalizeEnvelope
  execution_id
  status: completed | awaiting_input | blocked | failed
  user_message_artifact_ref
  output_refs[]
  open_gate_refs[]
  assumption_refs[]
  next_action_refs[]
```

The finalization envelope is validated and written by trusted code. A model stop, timeout,
exception, malformed payload, or process death before successful finalization makes the turn
failed or abandoned; it never implies success.

---

## 5. Seven-layer context assembly

The assembler is deterministic engine code:

| Layer | Contents | Runtime representation |
|---|---|---|
| L1 identity | pinned role prompt, resource map, skill names/descriptions | `.deepagent/` resources + bounded system frame |
| L2 workspace/product | product profile and brand-voice cards | `context/product-card.json`, `context/brand-voice-card.json` |
| L3 project | readiness/stage, ICP, counts, active runs/gates | `context/project-card.json` |
| L4 memory | Doc-M deterministic scoped-memory bundle | refs + a capped read-only context file |
| L5 focus | active typed object refs and requested cards | `context/focus/` |
| L6 conversation | append-only history | injected by history store; large canonical items offloaded by ref |
| L7 turn | current message and attachment refs | bounded current-turn frame + `inputs/` refs |

Each layer has a versioned hard token budget. Exclusion is explicit in the receipt. Full claim
tables, raw uploads/pages, full brand kits, worker transcripts, and another mind's paraphrase do
not enter the opening context.

---

## 6. Package and ownership plan

### `platform/agents/clue_agents` owns

- framework-neutral strict contracts;
- folder resource catalogs and validation;
- resource materialization policy;
- workspace-relative backend interfaces and role policies;
- context assembly;
- role registry and effective allowlist resolution;
- plan proposal/compiler validation;
- deepagent construction and subagent profiles;
- finalize/delegation orchestration against injected ports.

It may import shared base contracts, `clue_toolbelt`, and `clue_projections`. The import contract is
tightened to forbid direct access to `clue_execution`, `clue_fleet`, `clue_gateway`,
`clue_storage`, `clue_api`, and every subsystem.

### `platform/execution/clue_execution` owns

- generic C5 execution/journal additions required for agent turns;
- context/delegation/finalization event/reference shapes;
- dynamic plan-node append and replay;
- exact resource pins and attempt history;
- execution views.

It does not import or know the deepagent framework.

### `platform/api/clue_api` owns

- production composition and settings;
- concrete tool/projection adapters;
- the concrete model-gateway adapter;
- durable workspace root and storage wiring;
- DB repositories and C5 bridges;
- feature-gated routing and legacy fallback;
- API-facing turn/progress projections.

### Catalog directories own

- reviewed prompt, skill, and profile files only;
- no Python implementation and no secrets;
- immutable versions—editing an existing version after use is a compatibility failure; changes
  create a new version directory.

---

## 7. Implementation slices

### C6.0 — contract freeze and dependency spikes

- freeze the contracts and decisions in this spec;
- prove the real deepagent construction, `virtual_mode=True` backend, fresh-wake delegation,
  checkpointing, injected tool-calling model, and honest-finalize interception in isolated tests;
- choose exact dependency versions only after the spikes pass;
- add the initial replay, authority, and filesystem threat matrices;
- add no migration or production executor behavior.

**Gate:** all unknowns that could invalidate the architecture are answered with executable spikes;
the workspace and model contracts are accepted before durable schema work.

### C6.1 — isolated virtual workspace and immutable materialization

- production `AgentWorkspaceFactory` and relative-path backend;
- root validation, no-follow operations, quotas, permissions, atomic writes, and retention hooks;
- folder catalogs and immutable resource materialization;
- durable-output handoff to `StorageBackend`;
- isolation/adversarial tests.

**Gate:** traversal, symlink, absolute-path, cross-execution, repository, code/materialization,
resource-mutation, quota, and virtual-mode tests all fail closed.

### C6.2 — profiles, skills, role registry, and model seam

- strict folder schemas and version/digest resolution;
- Head-of-ABM plus research/content/review profiles;
- effective per-role tool allowlists and resource map;
- progressive skill disclosure;
- provider-neutral tool-calling model seam and deterministic test adapter;
- import-contract tightening.

**Gate:** exact resources reproduce one aggregate digest; unavailable tools are structurally
absent; `clue_agents` has no forbidden provider/domain imports.

### C6.3 — agent turns, context, history, and durable receipts

- typed constitution;
- seven-layer assembler with budgets/cards/refs;
- append-only conversation-history port;
- C5-correlated agent-turn, model-call, context-receipt, artifact, and finalization records;
- DSAR/retention behavior for workspace artifacts and body-free journals.

**Gate:** a cold replay can answer what resources and refs the model saw without journal bodies;
cross-workspace and erased-ref reads fail closed.

### C6.4 — governed tools, plan compiler, delegation, and honest finalize

- agent-facing projection/tool adapters;
- stable operation identities and C5 dynamic-node append;
- plan compiler and authority validator;
- child-envelope and delegation-node contract;
- required finalization envelope and failure recovery.

**Gate:** attempted gate/spend/fan-out/toolbelt bypass is rejected before domain execution;
crashes at model, plan-append, tool, delegation, artifact, and finalize boundaries recover without
duplicate effects or false success.

### C6.5 — Head-of-ABM Stage-0 vertical

- real orchestrator with Stage-0 prompt/skill/profile;
- C4 Recipe #0 and readiness projections/tools;
- open-ended sufficiency reasoning and useful questioning;
- human confirmation/override authority preserved;
- C5 journaling and current C4 actor fallback.

**Gate:** URL-only, known-product refresh, upload, correction, missing-readiness, human override,
and confirmed-run fixtures complete with equivalent governed outcomes. The agent improves the
conversation but cannot bypass deterministic readiness.

### C6.6 — fresh-wake specialist subagents

- research, content-drafter, and reviewer profiles;
- task/file/ref transfer policies;
- role-specific writable prefixes, tools, budgets, depth, and return contracts;
- parent/child context and spend rollups.

**Gate:** children wake without hidden history, cannot broaden authority, persist durable work
before returning refs, and propagate human gates identically to direct invocation.

### C6.7 — governed per-account research-agent unit

- replace the mechanical open-ended planning inside each admitted deep-research slot with one
  bounded governed worker agent;
- retain the existing fleet scheduler, per-account envelope, waterfall, gates, checkpoints,
  canary, controls, and claim-writing path;
- allow depth-one, count-capped facet delegation where justified;
- retain C1's sole independent evaluator and remove any duplicate evaluator path;
- preserve deterministic terminal-state enforcement.

**Gate:** quality/coverage improves or holds on the golden set within tier budgets; kill/restart,
idempotency, coverage, verification, and evaluator-one-owner tests pass.

### C6.8 — integration, canary, and hardening

- API-root composition, turn/progress projections, settings, and workspace routing;
- allowlist/percentage feature gate, telemetry, cleanup/retention jobs, and operational runbook;
- Stage-0 and per-account canaries;
- complete repository, migration, import, DSAR, adversarial, and eval batteries;
- documentation and C7 handoff.

**Gate:** a canaried workspace completes the Stage-0 and governed research verticals; a failed
turn is visibly failed; non-canaried work retains current behavior; one migration head and the
full repository gate are green.

---

## 7A. C6.0 implementation record

C6.0 is a contract and evidence checkpoint only. It adds no database migration, API route,
production executor, runtime workspace factory, catalog implementation, or feature routing.

### 7A.1 Selected dependencies and ownership

| Dependency | C6.0 pin | Owner/use |
|---|---|---|
| `deepagents` | `0.6.12` exact | `clue_agents` framework construction and state vocabulary |
| `langchain-core` | `>=1.5,<2` | provider-neutral model/messages/tools protocol |
| `langchain-openai` | `1.4.1` exact | `clue_gateway` only; OpenRouter-compatible tool-call adapter |
| `langgraph-checkpoint-postgres` | existing `3.1.0` lock | async durable mind-state checkpoint/resume |

`clue_agents` imports neither `clue_gateway` nor `langchain_openai` nor a vendor SDK. The concrete
`OpenRouterAgentModelProvider` lives in `clue_gateway`, consumes the existing `GatewayConfig` and
secret, and returns the standard `BaseChatModel` required by `deepagents`. Its requested timeout
and retry count cannot exceed the gateway policy.

The import contract now also forbids `clue_agents` from directly importing `clue_execution`,
`clue_storage`, `clue_locks`, or `clue_spine`. Those implementations bind only through injected
ports at the future API composition root.

### 7A.2 Frozen contract surface

The implementation lives in:

- `platform/agents/clue_agents/contracts.py`;
- `platform/agents/clue_agents/ports.py`;
- `platform/agents/clue_agents/state.py`.

Every value contract is strict, frozen, and extra-field-forbidden. Plan arguments cannot supply
trusted workspace, project, actor, execution, parent-execution, or operation identity. Plans are
acyclic; validated operations carry stable operation ids, exact tool addresses, artifact-backed
parameters, authority hashes, and a budget-total invariant. All durable bodies are referenced,
not embedded.

The JSON Schema digest test freezes these C6.0 shapes:

| Contract | Schema SHA-256 |
|---|---|
| `AgentProfile` | `30ea90d77ca95751adb6acc020059b206bb96ef1ca6c1580ff58cc880d4e5f4b` |
| `SkillBundle` | `ddbffd59d074ffd70880fd0398b7bc0a9aab2163e55aa8527c930f5866b24521` |
| `AgentConstitution` | `b3fa6888af9a1a7d427877a426943b2c959944edcf8c4203bfbd1720887de1a5` |
| `AgentTurnRequest` | `fd8dc5c626099b24442aefa3f71eb5ba2c715cb565f60e5fef41c670991f4ebb` |
| `AgentPlan` | `a954471a676c23101629f3babe2e523a6de96d21f7cc96de7983c8f265073c4e` |
| `ValidatedPlan` | `4708b42a3a98619f52056ed93dad842852955bd82551a974b788969274de2026` |
| `DelegationRequest` | `421ad5b96a036115f492c687bab8d8fc46dafd57991b80ce0718a8bfa3f65be3` |
| `DelegationResult` | `956ec6033fa560ba7704031a0df4b5aa3aa98ebbb0702bc137018ab3adafb36c` |
| `ContextBundleManifest` | `1d2f8ce14873a9413ac525d022a48de1fc72c9061bc28130ce0c12da3344a488` |
| `AgentFinalizeEnvelope` | `ee5a8ac990a3329fce7f1d6acd5160cfdb6eb243bcdcc4dc4f647a9188030dae` |

Changing one of these shapes requires an explicit contract revision and an updated digest gate
before a migration consumes it.

The injected ports are:

| Port | Frozen responsibility | Deliberately absent |
|---|---|---|
| `AgentModelProvider` | build a bounded `BaseChatModel` | provider client, credential, or domain access |
| `AgentWorkspaceBackend` | relative text list/read/write/edit and output snapshot | host paths, links, environment, shell, subprocess, execute |
| `AgentHistoryStore` | append/load body refs in thread order | mutable transcript bodies |
| `AgentContextAssembler` | deterministic request/profile/history → messages + manifest | ad-hoc model retrieval |
| `AgentExecutionAdapter` | validate/execute/delegate/finalize/recover and supply checkpointer | domain implementation or tool bypass |

`ClueDeepAgentState` extends the framework state with the trusted constitution, context manifest,
turn id, and optional finalize-artifact key. These compatible custom fields propagate to
declarative children; parent messages, todos, and structured response do not.

### 7A.3 Executable spike results

| Spike | Executable evidence | Result |
|---|---|---|
| Real framework and fresh wake | real `create_deep_agent`; explicit parent and child fake models/tools; child tool inspects runtime state | child receives only its task message while constitution/context markers propagate |
| Governed OpenRouter tool call | real `ChatOpenAI` built by `clue_gateway`; `httpx.MockTransport`; sync and async calls | standard tool arguments and usage metadata parse without network or secrets |
| Async Postgres checkpoint/resume | real `AsyncPostgresSaver`; first node commits, next node fails; fresh graph resumes same thread | completed node runs once, failed node retries, final state is restored; framework tables cleaned |
| Artifact-backed filesystem | real deepagent file tools over a disposable content-addressed backend | relative model path writes/reads; a new backend resumes bytes; another execution cannot see them |
| Honest finalization | real deepagent terminates normally without a finalize adapter | no finalize key exists; framework stop is not treated as successful C6 completion |

All model/framework tests are deterministic and offline. The Postgres spike uses a reachable local
Postgres and creates only LangGraph-owned checkpoint tables at runtime; it drops them after the
test. No Alembic state changes.

### 7A.4 Framework findings that bind C6.1

1. `deepagents` can consume an injected model, backend, checkpointer, custom state schema, explicit
   tools, and explicit subagents. Declarative subagents inherit the compatible custom state schema.
2. The stock `FilesystemBackend(root_dir=..., virtual_mode=True)` is not a production sandbox for
   an API service. `virtual_mode` is a path-semantic guardrail, not process or host isolation.
   Production must use the hardened C6 backend; the stock backend is rejected.
3. The framework file middleware normalizes a relative model argument such as `work/report.md` to
   the virtual form `/work/report.md` before calling its backend. That erases whether the model
   supplied a leading slash. Therefore C6.1 must validate relative syntax in the agent-facing file
   tool before framework normalization, then adapt the single virtual slash internally. The public
   C6 workspace port remains relative-only.
4. A single backend instance is shared with framework subagents. C6 must layer narrowed child
   path permissions over that shared artifact namespace; sharing bytes must not imply sharing
   authority.
5. A backend implementing an execution/sandbox protocol would cause the framework to expose code
   execution. The C6 backend must implement file operations only.

### 7A.5 Initial 32-tool replay and authority audit

This is the C6.0 admission decision, not production routing. C6.2 writes reviewed folder profiles;
C6.4 creates adapters for only the admitted addresses. Codes: `H` = Head-of-ABM, `R` = research
specialist, `A` = account-research worker, `C` = content drafter, `V` = reviewer. `—` means the
tool is structurally absent from every initial agent profile.

| Tool | Effect | Replay / external boundary | Operation id | Initial agent roles or disposition |
|---|---|---|---:|---|
| `adjust_budget@1` | steering | domain-idempotent / none | no | — human authority |
| `compose_handoff@1` | read | effect-free / none | no | H, C, V |
| `confirm_icp@1` | write | domain-idempotent / none | no | — explicit human confirmation |
| `confirm_project_product@1` | steering | domain-idempotent / none | no | — explicit human confirmation |
| `decide_field_proposal@1` | write | uncertified / none | no | — human decision and replay-blocked |
| `decide_source_proposal@1` | write | uncertified / none | no | — human decision and replay-blocked |
| `discover_accounts@1` | spend | domain-idempotent / at-least-once | no | H |
| `estimate_project@1` | read | effect-free / none | no | H |
| `evaluate_stage0_readiness@1` | write | operation-idempotent / none | yes | H |
| `import_accounts@1` | spend | operation-idempotent / at-least-once | yes | H |
| `override_stage0_readiness@1` | steering | domain-idempotent / none | no | — human override |
| `pause_run@1` | steering | domain-idempotent / none | no | — human control |
| `profile_contact@1` | spend | operation-idempotent / at-least-once | yes | R, A |
| `propose_field@1` | write | uncertified / none | no | — replay-blocked; intended H/R/A after audit |
| `propose_source@1` | write | uncertified / none | no | — replay-blocked; intended H/R/A after audit |
| `record_interview_answer@1` | spend | operation-idempotent / at-least-once | yes | H |
| `research_account_gaps@1` | write | uncertified / none | no | — replay-blocked before C6.7 |
| `resolve_committee@1` | spend | operation-idempotent / at-least-once | yes | R, A |
| `resume_run@1` | steering | domain-idempotent / none | no | — human control |
| `retry_ingestion@1` | write | uncertified / none | no | — replay-blocked |
| `reverse_profile@1` | spend | operation-idempotent / at-least-once | yes | H |
| `run_deep_account@1` | spend | operation-idempotent / at-least-once | yes | R, A |
| `run_verification@1` | spend | domain-idempotent / at-least-once | no | R, A |
| `score_accounts@1` | write | domain-idempotent / none | no | H |
| `start_confirmed_project_run@1` | write | operation-idempotent / none | yes | H, after the human gate |
| `start_project_run@1` | write | operation-idempotent / none | yes | — legacy/unconfirmed entry path |
| `start_recon@1` | spend | at-least-once / at-least-once | yes | H |
| `submit_ingestion@1` | write | uncertified / none | no | — replay-blocked |
| `submit_onboarding_input@1` | write | operation-idempotent / none | yes | H |
| `submit_project_checkpoint@1` | steering | domain-idempotent / none | no | — human checkpoint |
| `submit_tier_checkpoint@1` | steering | domain-idempotent / none | no | — human checkpoint |
| `synthesize_icps@1` | spend | at-least-once / at-least-once | no | H |

The executable audit fails if the registry no longer contains exactly these 32 decisions, if an
uncertified tool is admitted, or if a steering tool is admitted. The C5 execution-control tools
are not exposed directly to the model: the future `AgentExecutionAdapter` compiles validated plans
and invokes C5 under trusted authority.

Seven current tools are replay-blocked:

- `propose_field@1`;
- `decide_field_proposal@1`;
- `propose_source@1`;
- `decide_source_proposal@1`;
- `research_account_gaps@1`;
- `submit_ingestion@1`;
- `retry_ingestion@1`.

This is an explicit residual gate, not an implicit promise. The field/source proposal tools are
still part of the intended agent surface, but C6 must first add truthful durable identity/replay
contracts. `research_account_gaps@1` must be certified or replaced by an equally governed C5
operation before C6.7; two competing gap evaluators remain forbidden.

### 7A.6 Initial filesystem threat matrix

| Threat | C6.0 decision/evidence | Production closure |
|---|---|---|
| absolute, drive, backslash, dot, traversal, control path | frozen path contract rejects | pre-normalization tool validation in C6.1 |
| host-path disclosure/escape | host path absent from contracts and artifact spike | opaque root factory + anchored no-follow I/O |
| cross-execution access | artifact index is keyed by opaque execution root | per-execution directory and authorization checks |
| write to prompt/input/context | writable prefixes exclude them | immutable materialization + permission tests |
| source/executable file creation | data/document extension allowlist rejects it | file-type, mode, and content/materialization checks |
| shell/process/environment/package access | absent from workspace protocol; no sandbox execute | construction regression asserting no execution tool |
| symlink, hard link, device, socket, FIFO | impossible in artifact spike | no-follow host checks and type rejection |
| quota exhaustion | quota fields frozen | atomic per-file/total/count enforcement |
| resource mutation after pin | exact version and content digests frozen | copy, verify, read-only, manifest-last materialization |
| concurrent path swap/TOCTOU | not claimed by C6.0 | directory-fd anchored operations and adversarial test |
| child authority widening | explicit granted paths/roles/budget refs | effective-subset compiler and shared-backend permission view |
| secret/repository exposure | neither appears in any agent port | dedicated external root validation and negative scans |

The threat matrix does not claim that the disposable in-memory backend is production-ready. It
defines the acceptance battery the C6.1 backend must satisfy.

---

## 8. Verification matrix

### Workspace isolation

- configured root is rejected if equal to, above, or below the source worktree or user home;
- host absolute paths never occur in model-visible prompts, state, events, or errors;
- absolute, traversal, Unicode/confusable separator, symlink, and concurrent-swap attacks fail;
- one execution cannot list/read/write another execution;
- read-only resources/context reject writes and edits;
- no executable bit, source package, secret, environment, socket, or device is exposed;
- quotas and atomic-write behavior hold under concurrency and crash;
- finalized outputs survive workspace cleanup through durable artifact refs.

### Resources and profiles

- duplicate name/version with different bytes fails;
- missing, retired, wrong-hash, malformed, or incompatible resource fails before model spend;
- profile/skill/tool allowlists intersect correctly;
- progressive disclosure exposes metadata before bodies;
- a future catalog fake can replace folder catalogs without runtime changes.

### Authority and tools

- unregistered/disallowed tools are absent;
- model arguments cannot override actor/workspace/project/execution ids;
- no direct domain/storage/gateway imports from `clue_agents`;
- gate, trust, spend, fan-out, recursion, verification, and promotion override attempts fail;
- human and agent invocation of the same operation reach the same tool/journal path.

### Context, privacy, and durability

- all seven layers are ordered and capped deterministically;
- context receipts contain ids/hashes/counts/reason codes, never bodies;
- another workspace's claims/memory/cards cannot assemble;
- erased/tombstoned refs fail closed and do not leak through journal/history/workspace artifacts;
- append-only history is not rewritten;
- tool results remain lossless by durable refs after context compaction.

### Delegation and finalization

- subagents are fresh-wake;
- child paths/tools/budget are strict subsets;
- every child has one parent delegation record and its spend rolls up;
- no return is the only durable copy of substantive work;
- missing/malformed finalize, timeout, exception, and process death are failed/abandoned;
- retry cannot double-execute a completed tool or emit two successful finalizations.

### Outcome and evals

- Stage-0 questions are material, gap-driven, and product-aware;
- known-product kickoff confirms/refreshes rather than repeats fresh evidence;
- the agent's sufficiency judgment never bypasses deterministic readiness;
- exactly one independent coverage evaluator executes;
- evaluator advice cannot create terminal state;
- governed account research remains within hard envelopes and verification floors;
- fixed fixtures meet C4/C5 outcome-parity and crash-recovery expectations.

---

## 9. Completion definition

C6 is complete only when:

1. the real deepagent framework fronts a feature-gated Head-of-ABM turn;
2. all model-controlled filesystem work is confined to an external, per-execution,
   `virtual_mode=True` workspace using relative paths;
3. no application code or executable capability exists inside that workspace;
4. folder-backed resources are exact-versioned, hashed, immutable per run, and pinned through C5;
5. the seven context layers assemble deterministically and journal ids/hashes rather than bodies;
6. every domain effect uses an allowed toolbelt tool and has a C5 operation record;
7. plan validation and runtime enforcement preserve the authority table;
8. research/content/review subagents satisfy the fresh-wake delegation contract;
9. Stage 0 demonstrates open-ended agent judgment without readiness bypass;
10. the governed per-account unit retains fleet/backstop/replay semantics;
11. one C1 evaluator path remains and advice stays non-authoritative;
12. every successful turn has one valid finalize record and every non-finalized turn is failed;
13. feature-off work retains the C4/C5 fallback behavior;
14. the full repository, DB migration, import-contract, DSAR, adversarial, crash, and eval gates are
    green.
