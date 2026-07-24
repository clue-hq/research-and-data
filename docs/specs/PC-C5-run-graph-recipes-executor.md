# Phase C5 — Run-Graph Journal, Recipes, Durable Executor, and Supervisor

**Status:** C5.2 implemented; C5.3 next on `platform/c5-recipe-execution` (2026-07-24)

**Parent:** [`PC-phase-c-agentic-layer.md`](./PC-phase-c-agentic-layer.md)

**Requirements:** harness REQ-10, REQ-11, REQ-12, and REQ-13

**Authority:** the harness architecture v1.2, Doc A, Doc M §§10–11, the Phase-B fleet/toolbelt
specs, and the implemented C1–C4 contracts.

---

## 1. Outcome

C5 turns successful work from an ephemeral call sequence into a durable, inspectable,
outcome-reproducible execution:

```text
versioned recipe + immutable inputs + resolved compatibility pins
                              |
                              v
                    durable graph execution
                              |
                 toolbelt writes every invocation
                              |
          append-only nodes / edges / pins / lifecycle events
                              |
        run view + activity feed + safe restart + recipe re-run
```

It also introduces the non-agentic run supervisor required for fleet-scale execution:
deterministic monitors read progress, gap, spend/yield, verification, stall, and source-failure
signals; a bounded LLM triage leaf may diagnose grouped anomalies; only typed, policy-permitted
control tools can quarantine an account, trip a run-local source breaker, tighten an envelope, or
escalate to a human.

C5 does not add a planner mind. C6's deepagent will author and extend plans through the C5
contracts. C5 owns the execution substrate that makes those future plans durable and auditable.

---

## 2. Starting code reality

C5 starts from the following implemented surfaces:

- `clue_toolbelt` is the one typed capability entry point, but its `tool_invocation` row is a
  24-hour HTTP idempotency cache, not a permanent execution journal.
- `ToolRegistry` currently resolves only one live implementation per tool name; it cannot load a
  pinned historical tool version.
- `ToolResult.references` is an untyped dictionary, so graph data edges cannot yet be validated
  against an output schema.
- `ToolbeltRecipeRunner` is an in-memory topological runner used only as C4's narrow Recipe-#0
  seam. It has no durable execution, journal, pins, pause/gate state, or crash recovery.
- `ProjectRunWorker`, `run_lease`, and `fleet_task` already prove detached execution, stale
  takeover, heartbeat fencing, tier-priority account work, and phase-level replay.
- `ProjectRun` already owns the fixed phase sequence and phase/account idempotency ledgers. C5
  must generalize around it, not copy its research behavior.
- `run_event` and the SSE surface already provide workspace-scoped ordered transport, but
  phase-event emission is best-effort and is not the authoritative run graph.
- the current A4 manifest synthesizes a fixed phase DAG rather than rendering a journaled
  execution.
- C4's `recon_run` records Recipe-#0 compatibility and independent fast/background cursors, but
  no general execution id.
- Doc M's `memory_bundle_journal` already records included/excluded memory ids and labels without
  bodies; C5 must link that journal id into the graph rather than duplicate memory content.
- field and source registries expose `active` and `version`, while ICPs, source profiles,
  readiness policies, product contexts, artifacts, and skills expose version or immutable digest
  surfaces that can be pinned through adapters.
- no account-quarantine or run-local source-circuit-breaker enforcement exists yet. Logging a
  supervisor recommendation without enforcing it would not satisfy REQ-10.

---

## 3. Binding design decisions

### 3.1 One platform execution owner

Add `platform/execution/clue_execution`. It owns recipe definitions, compatibility loading,
execution state, graph journaling, the durable executor, supervisor policy/state, and execution
read models.

It may import the shared base, `clue_toolbelt`, and the generic fleet contracts. It may not import
research, memory, content, agents, projections, gateway implementations, or `clue_api`.
Subsystem-specific pin resolvers, phase bridges, aggregate readers, control enforcement, and
storage bind only at `clue_api`, the existing composition root.

The research `durable` package continues to own research phase/account state. C5 does not move
claims, project phases, account graphs, budgets, or verification into `clue_execution`.

### 3.2 Journal and cursor are different species

The run graph is append-only:

- logical nodes;
- dependency/data edges;
- resolved pins;
- invocation attempts;
- lifecycle/steering/supervisor events.

A small mutable execution cursor may cache effective status and scheduling position for efficient
worker claims. It is a rebuildable materialization, never the historical authority.

### 3.3 HTTP idempotency is not execution idempotency

The existing `tool_invocation` table remains the short-lived A9 HTTP replay cache.

C5 adds execution-scoped invocation reservation/replay over the graph journal. It does not expire
while the execution is live or retained. A node uses a stable operation id across retries. A tool
is schedulable in a durable recipe only when its descriptor declares and tests a replay strategy:

- effect-free;
- domain-idempotent under the stable operation id;
- or replayed from a durably completed execution invocation.

An effectful tool that only happens to be safe during a 24-hour cache window is not recipe-safe.

The honest guarantee remains:

- database effects are exactly-once where the existing domain ledger/unique key proves it;
- external provider acceptance is at-least-once across the provider-accept/commit crash window
  unless that provider accepts an idempotency key;
- the journal records retries and never overstates provider-boundary exactly-once.

### 3.4 Parameters are durable, but bodies do not enter the journal

Every validated tool input is content-addressed through `StorageBackend` inside the owning
workspace's artifact namespace. The graph stores:

- the parameter artifact key;
- its SHA-256;
- safe display/reference fields declared by the tool;
- the tool input-schema digest.

It never stores raw interview answers, uploads, scraped text, personal fields, memory bodies, or
prompt bodies in graph JSON. `execution_artifact_ref` makes parameter snapshots reachable by
retention/DSAR machinery. An erased body renders as a tombstone while its id/hash audit survives.

Tool outputs remain reference-only and may be stored directly in completion events.

### 3.5 Recipes are immutable revisions

A recipe has a stable identity. Every revision is immutable and carries:

- parameter schema;
- graph template;
- tool/input/output schema digests;
- exact config/reference pins;
- compatibility requirements;
- executor protocol version;
- node/edge/node-count envelopes;
- memory types requested, if any;
- creator/source execution and canonical digest.

Proposal, promotion, retirement, and supersession are append-only revision events. A running
execution never floats to a newer recipe or config.

### 3.6 Compatibility fails before execution

Loading a recipe resolves all declared requirements through registered `PinResolver`s. The loader
collects every incompatibility and fails before any node is scheduled. Errors name:

```text
kind + key + requested version/digest + observed status/version + reason
```

Exact pins are required for tools, ICPs, source profiles, skills, prompts/models, policies, and
immutable inputs. Field/source requirements additionally require the named version to be active.
If a registry retains only a newer current version, the old exact pin is unavailable and the old
recipe fails honestly; creating an upgraded recipe revision is explicit.

The memory kill switch remains live safety authority rather than reproducibility data. Recipe
loading records the currently observed switch state, but it never re-enables memory from an older
pin. If memory is currently disabled and the revision requires it, loading fails before execution
with `memory_disabled`. If the revision declares memory optional, it runs with an explicit
disabled-state pin and no memory bundle. This prevents either silent outcome drift or an old recipe
overriding a current safety decision.

### 3.7 C5 executes DAGs and bounded maps, not agent loops

The C5 recipe language supports:

- `tool` nodes;
- explicit human/deterministic `gate` nodes;
- bounded `map` expansion over a sorted reference set;
- `barrier` nodes;
- data bindings from recipe parameters or prior typed outputs.

No arbitrary expression language, Python callbacks, unbounded cycle, prompt-authored SQL, or
free-form user graph editor ships in C5. C1's one-round research tool remains one bounded tool
invocation. C6 may append validated nodes dynamically under C5's node/depth/fan-out ceilings.

### 3.8 Recipe #1 preserves the phase machine

Recipe #1 expresses the live `ProjectPhase` sequence as graph nodes. A phase node invokes one
versioned `advance_project_phase` capability with an `expected_phase`; it does not reimplement a
phase handler.

The phase enum therefore survives inside Recipe #1 exactly as the harness architecture requires.
Existing project/account checkpoints, budgets, claim writes, and idempotency ledgers remain the
authorities.

Existing active runs finish through `ProjectRunWorker`. New-run routing moves behind a feature
flag/canary to Recipe #1 only after golden parity. No in-flight run is converted.

Every resume surface first checks the run's execution-owner link: an owned run re-enqueues its
graph execution; an unowned legacy run re-enqueues `drive_run`. This applies to `resume_run`,
tier-gate submission, and the review-finalize hook, preventing both drivers from racing one run.

### 3.9 The supervisor is an engine, not another agent

Continuous monitor rules are deterministic versioned policy. LLM triage:

- runs only on a bounded aggregate digest;
- groups/diagnoses anomalies;
- returns typed advice;
- cannot write controls, truth, budgets, or terminal status;
- is journaled with requested/answering model and prompt versions.

The deterministic supervisor policy validates any proposed action, and the action executes through
the toolbelt with `actor=agent` and a supervisor principal. Human override remains explicit.

---

## 4. Package and seam shape

### 4.1 `clue_execution`

```text
clue_execution/
  models.py          immutable recipe/graph/pin/event value types
  recipes.py         recipe revision repository and promotion/retirement events
  compatibility.py   PinResolver registry and fail-before-run loader
  journal.py         append-only graph repository + execution cursor materializer
  parameters.py      parameter snapshot/ref policy
  executor.py        deterministic DAG/map/gate scheduling
  worker.py          fleet task handler for graph executions
  supervisor.py      monitor policy, aggregate snapshots, action validation
  controls.py        account/source/envelope/escalation control events and effective reads
  views.py           workspace-scoped execution/run-view reader
```

### 4.2 Toolbelt deltas

Add:

- version-aware `ToolRegistry.resolve(name, version)` while preserving `get(name)` as the one
  active/default version for ad-hoc callers;
- `ToolDescriptor`: input/output schema, schema digests, replay policy, effect class, safe display
  fields, declared pin requirements, and steering-audit requirements;
- typed `ToolOutput`/reference models for tools used by Recipe #0/#1;
- stable `operation_id` plus optional execution/node/parent refs in `ToolContext`;
- required `InvocationJournal` and parameter-snapshot seams on the production invoker;
- a single composed `ToolInvoker` used by HTTP, recipes, supervisor actions, and later agents.

`clue_toolbelt` defines the protocols but never imports `clue_execution`. `clue_execution`
implements them; `clue_api` binds them.

An explicit null/in-memory journal is allowed only in unit fixtures. Production composition must
fail at startup if the durable journal is absent.

### 4.3 Pin resolver seam

```python
class PinResolver(Protocol):
    kind: str

    async def resolve(
        self, request: PinRequest, context: CompatibilityContext
    ) -> ResolvedPin | Incompatibility: ...
```

The resolver registry is open by registration. C5 production adapters cover at least:

- `tool`;
- `field_definition`;
- `source_manifest`;
- `icp_spec`;
- `source_profile`;
- `readiness_policy`;
- `stage0_policy`;
- `skill`;
- `prompt`;
- `model_policy`;
- `product_context`;
- `artifact_input`;
- `memory_switch`.

Profile pins are supported by the schema/resolver registry but are absent from Recipe #0/#1 unless
a profile is actually consumed. C6 registers the real agent-profile resolver; C5 does not invent a
fake agent profile.

### 4.4 Aggregate/control seams

`clue_execution` consumes injected protocols, not research packages:

```python
class RunAggregateReader(Protocol):
    async def snapshot(self, request: AggregateRequest) -> RunAggregateSnapshot: ...

class RunControlReader(Protocol):
    async def account_allowed(self, execution_id, account_id) -> bool: ...
    async def source_allowed(self, execution_id, source_key) -> bool: ...
```

`clue_api` implements the aggregate reader over M13.4, C1 coverage attempts/decisions,
run-specific source telemetry, fleet/account state, and budget state.

The account control reader is injected into `QueueBackedScheduler`. The source control reader
wraps the pre-spend/source-resolution boundary. An action is not considered applied until the
relevant runtime gate reads it.

---

## 5. Durable model

One random-hash Alembic revision is created from the current single head. It is additive except for
the separately reviewed fleet generalization in §8.

### 5.1 Recipes

`recipe`

```text
id                       uuid PK
recipe_key               text
scope_type               system | workspace
workspace_id             nullable only for system recipes
created_at
UNIQUE NULLS NOT DISTINCT (scope_type, workspace_id, recipe_key)
```

`recipe_revision`

```text
id                       uuid PK
recipe_id                uuid
version                  integer >= 1
executor_protocol        integer
parameter_schema_json    jsonb object
graph_json               jsonb object
compatibility_json       jsonb object
requested_memory_types   jsonb array
max_nodes/depth/fanout    positive integer ceilings
source_execution_id      nullable
definition_sha256        text
created_by / created_at
UNIQUE (recipe_id, version)
UNIQUE (recipe_id, definition_sha256)
```

`recipe_revision_event`

```text
seq                      bigserial PK
recipe_revision_id
event_type               proposed | promoted | retired | superseded
actor
reason_code
created_at
```

Effective status is the latest valid event. A promoted revision is immutable.

### 5.2 Execution and graph

`execution`

```text
id                       uuid PK
workspace_id
project_id               nullable
project_run_id           nullable
recipe_revision_id       nullable for ad-hoc invocation executions
parent_execution_id      nullable
started_by / started_at
parameter_manifest_hash
pin_manifest_hash
```

`project_run_execution_owner`

```text
project_run_id           PK
execution_id             UNIQUE
routing_mode             recipe
attached_at
```

This is a platform routing link, not alternate project-run state. A project run has at most one
recipe execution owner. Recipe #0 may reference the child run/execution in an event, but only
Recipe #1 owns its drive routing.

`execution_cursor` is the mutable, rebuildable scheduler materialization:

```text
execution_id             PK
status                   queued | running | awaiting_input | paused | completed | failed
state_version            monotone integer
active_node_count
last_event_seq
updated_at
```

`execution_node`

```text
id                       uuid PK
execution_id
node_key
kind                     tool | gate | map | barrier | activity
tool_name/version        nullable outside tool nodes
operation_id             uuid, stable across retries
parameter_artifact_key   nullable
parameter_sha256         nullable
input_schema_sha256      nullable
output_schema_sha256     nullable
display_params_json      refs/safe scalars only
declared_by_node_id      nullable for bounded dynamic expansion
created_at
UNIQUE (execution_id, node_key)
UNIQUE (execution_id, operation_id)
```

`execution_edge`

```text
execution_id
from_node_id
to_node_id
binding_json             typed reference path, never body
edge_kind                dependency | data | parent
PRIMARY KEY (execution_id, from_node_id, to_node_id, edge_kind)
```

`execution_pin`

```text
id                       uuid PK
execution_id
node_id                  nullable for execution-wide pins
kind / key / version
digest
resolved_status
metadata_json            labels/refs only
UNIQUE NULLS NOT DISTINCT (execution_id, node_id, kind, key)
```

`execution_attempt`

```text
id                       uuid PK
execution_id / node_id
attempt                  integer >= 1
worker_id
lease_generation
started_at
UNIQUE (node_id, attempt)
```

`execution_event`

```text
seq                      bigserial PK
execution_id
node_id                  nullable
attempt_id               nullable
event_type
actor
payload_json             refs, reason codes, estimates, outcomes
created_at
```

Events include execution/node scheduled, started, blocked, completed, failed, abandoned, paused,
resumed, gate-opened/decided, steering before/after, supervisor observation/diagnosis/action, and
terminal state. Partial unique constraints prevent more than one accepted terminal completion for
a node and more than one terminal execution event. Failure events store stable error codes,
redacted summaries, and affected references only; raw provider bodies, stack traces, prompts, and
validated parameter bodies remain outside the journal.

`execution_artifact_ref` links parameter/input artifacts for retention and DSAR.

### 5.3 Supervisor controls

`supervisor_observation`

```text
id / execution_id / project_run_id
policy_version
aggregate_snapshot_json  counts/rates/refs only
trigger_codes_json
created_at
```

`supervisor_diagnosis`

```text
id / observation_id
requested_model / answering_model / prompt_version
diagnosis_codes_json
affected_refs_json
confidence
created_at
```

`run_control_event`

```text
seq / execution_id
control_kind             account_quarantine | source_breaker | envelope | escalation
subject_ref
action                   apply | release | acknowledge
before_json / after_json
reason_code
observation/diagnosis refs
actor
created_at
```

The latest valid event determines effective control state. Controls are workspace/run-local; no
source is globally disabled by a supervisor action.

---

## 6. Journaled invocation lifecycle

For every production invocation:

1. resolve the exact tool version;
2. validate the body through its input model;
3. content-address the canonical validated input in the owning workspace's artifact namespace and
   establish `execution_artifact_ref`;
4. create/resolve an execution and logical node;
5. validate all dependency nodes and pins;
6. append the attempt-start event before preconditions or spend;
7. run estimate and preconditions;
8. reserve execution idempotency with the node's stable operation id;
9. invoke the tool;
10. append completion/failure plus reference-only result, cost estimate, replay status, and actor;
11. transactionally append the corresponding `run_event` transport event and advance the cursor.

Precondition failures are terminal blocked attempts, not successful empty nodes. A caller may
append a new node after satisfying the prerequisite; history is never rewritten.

Tools classified as steering additionally snapshot their display-safe effective state before and
after invocation through an injected audit seam. Pause, resume, budget adjustment, gate decisions,
manifest operations, supervisor controls, and human overrides cannot complete without an
actor-attributed before/after journal event.

Unknown tools or failed compatibility never reach step 3 and create no executable node. The
recipe-load failure itself is an execution-level event with the full named incompatibility list.

Every invocation belongs to exactly one execution. An ad-hoc HTTP/human call creates or joins an
ad-hoc execution root, so the "no orphan invocation" acceptance criterion is structural.

---

## 7. Recipe validation and dataflow

Bindings use a closed expression shape:

```text
literal(value)
parameter(name)
node_reference(node_key, reference_path)
```

The loader validates:

- unique node keys;
- all dependencies exist;
- acyclic graph;
- map bounds are within the recipe envelope;
- every tool/version exists and is active;
- every required input is bound once;
- bound source type is compatible with the destination tool's input schema;
- referenced output paths exist in a typed tool output model;
- every config/input requirement resolves exactly;
- gates have a real decision authority and resume condition;
- no node exceeds the recipe's tool/authority allowlist;
- no raw body appears in graph/compatibility JSON.

The executor repeats the relevant validation at dispatch, because config may be retired between
recipe load and a delayed node. A mismatch pauses/fails before invoking the tool and records the
incompatibility.

Pinning a completed ad-hoc execution creates a new proposed recipe revision by parameterizing only
explicitly selected safe input references. It never infers variables from secret/body content.

---

## 8. Durable executor and fleet integration

### 8.1 Generic fleet shell

The current fleet worker logic is reusable, but its public vocabulary is tied to project runs.
C5 performs one reviewed generalization:

- make the top-level queue/lease key `work_id` internally;
- add `execute_graph` as a top-level task kind;
- extract the lease/heartbeat/stale-reclaim/drain shell behind a `WorkHandler` protocol;
- retain `ProjectRunWorker`, `enqueue_drive`, and account-job APIs as compatibility adapters;
- add `RecipeExecutionHandler` for `execute_graph`;
- keep account jobs scoped under their owning project run/work id;
- add a monotone lease generation/fence value and require it on C5 cursor/journal materialization
  writes.

The migration renames only fleet-internal soft-identifier columns; project-run domain tables and
public `ProjectRunId` contracts do not change. Existing fleet exit tests must pass before the graph
handler is added.

### 8.2 Scheduling semantics

Within one execution lease:

1. read the append-only graph plus effective cursor;
2. mark stale started attempts abandoned;
3. find dependency-satisfied nodes in stable `(ordinal, node_key)` order;
4. dispatch up to the recipe's bounded concurrency;
5. use the node's stable operation id for all retries;
6. append terminal events;
7. stop at a human gate, explicit pause, incompatibility, failure policy, or execution terminal.

Parallel-ready nodes may run concurrently only when the recipe allows it. Result ordering remains
deterministic by node key, not completion time.

Crash recovery reclaims the task/lease, rebuilds the cursor from events, replays completed nodes,
and retries abandoned nodes through execution idempotency. It never trusts an in-memory result.

### 8.3 Tool replay certification

Before Recipe #0/#1 cut over, every included effectful tool receives a crash matrix:

```text
before journal start
after attempt start / before tool
after domain commit / before completion event
after completion event / before cursor update
```

Tools that mint identifiers use `ToolContext.operation_id` or caller-supplied stable ids. In
particular, `start_project_run` and `start_confirmed_project_run` stop minting a fresh run id on
each retry. The same treatment applies to any proposal, ingestion, recon, or readiness operation
whose existing natural key is insufficient.

---

## 9. Recipe #0 migration

Recipe #0 becomes a promoted system recipe revision. It preserves C4's actual Stage-0 behavior:

- fast and background recon remain independent child activities;
- interview turns may occur between recon/readiness nodes;
- human product confirmation and readiness override remain human-only;
- the graph records repeated interview/tool nodes as append-only dynamic children under the
  recipe's bounded Stage-0 interaction slot;
- C1/C2/C3 refs remain references;
- the memory bundle journal id is pinned/linked, never copied;
- the live memory kill switch overrides any older enabled-state observation as specified in §3.6;
- product context, Client-KB, ICP, readiness, skill, policy, tool, model/prompt, and artifact input
  versions/digests are recorded;
- `start_confirmed_project_run` creates or reuses its stable run id and launches/attaches Recipe #1
  at `DISCOVERY`.

`ToolbeltRecipeRunner` remains temporarily as a compatibility adapter that submits one explicit
step to the durable executor. Once C4 parity and crash tests pass, direct in-memory `run()` use is
removed. C4's recon cursor remains the domain state for recon; C5 does not duplicate its lane
statuses in recipe payloads.

---

## 10. Recipe #1 migration and canary

Recipe #1's promoted system revision contains the actual phase spine, including the existing
`REVIEW` phase:

```text
reverse_profiling
  → icp_confirmed
  → discovery
  → scoring
  → tier_checkpoint (human gate)
  → deep
       ├─ top-cohort canary
       ├─ supervisor health gate
       └─ remaining tier-priority fleet
  → verification
  → review (human gate)
  → handoff
```

Each phase node advances exactly one expected phase through the existing `ProjectRun`. If Recipe #0
already created a confirmed run at `DISCOVERY`, the immutable Stage-0 pins satisfy the first two
nodes and the journal records `pre_satisfied`; those phase handlers are not rerun.

The deep phase gains an injected cohort/supervisor seam rather than a second deep implementation:

1. resolve the same human-approved, tier-priority account set;
2. run the configured top `N` canary accounts through the existing
   `AccountDeepOrchestrator`/queue;
3. snapshot verification, gap, cost/yield, stall, and source-failure health;
4. invoke the journaled deterministic supervisor gate;
5. on pass, drain the unchanged remaining queue;
6. on fail, pause at the deep checkpoint, apply permitted quarantine/breaker controls, and
   escalate with diagnosis; do not open the remainder.

Account-job activity rows are linked as child graph nodes under the deep phase. They are engine
activities, not fake tool invocations.

Parity means equal normalized outputs, gates, and costs within configured bounds. C5 does not hide
the pre-existing narrative-emission gap at handoff; C7 owns that production reader.

---

## 11. Supervisor behavior

### 11.1 Deterministic monitors

At canary completion and configured account/phase boundaries, monitor:

- accounts by state and stalled duration;
- C1 remaining-gap and terminal-empty ratios;
- spend vs cap and cost per surviving claim;
- run-specific source attempts, failures, empty yield, and latency;
- faithfulness, corroboration, and strong-binding shares with sample floors;
- coverage confidence and unsearched channels;
- repeated tool/precondition/incompatibility failures.

Thresholds, minimum sample sizes, windows, cooldowns, and actions are versioned policy pins.
Insufficient sample size produces `insufficient_signal`, never a pass manufactured from no data.

### 11.2 Bounded triage

Triage receives only the aggregate snapshot, stable error codes, affected refs, and policy
envelope. It returns a closed diagnosis/action-candidate schema. Invalid, injected, or
out-of-allowlist output is discarded and cannot block/continue a run.

### 11.3 Enforced actions

- **Account quarantine:** scheduler admission skips/parks the account and records a governed partial
  result. Releasing quarantine explicitly reoffers that account.
- **Source breaker:** the source/pre-spend boundary rejects that source for this execution before
  provider I/O. A source key is added to `PreSpendRequest` or an equivalent injected source gate;
  the current source-agnostic request is insufficient and must not be worked around with logs.
- **Tighten envelope:** lowers future fan-out/depth/account limits within the original human-approved
  cap; it cannot raise spend or authority.
- **Escalate:** pauses the relevant gate/scope and attaches observation, diagnosis, affected refs,
  and safe recommended choices.

All apply/release/override actions record actor plus before/after state and stream within one
scheduling cycle.

---

## 12. Read projections and events

Extend run-event topics with versioned execution events such as:

```text
run.recipe.started
run.node.started/completed/blocked/failed
run.gate.opened/decided
run.supervisor.observed/action
run.recipe.completed/failed
```

Journal event and transport outbox append in one database transaction. SSE remains at-least-once;
consumers deduplicate by `seq`.

Add workspace-scoped read projections:

- execution overview;
- complete graph/run view with dependencies, pins, attempts, costs, gates, and outcomes;
- activity feed;
- recipe library/revision detail;
- compatibility report;
- supervisor observations/actions and effective controls.

The existing A4 manifest first prefers a C5 journal execution attached to the project run and
falls back to its synthetic fixed-phase view for legacy runs. Chat narration and later agent
messages are views; neither writes alternate execution truth.

Historical memory context is represented by `memory_bundle_journal.journal_id`. Dereferencing a
live journal returns labels/ids; erased memories render tombstones.

---

## 13. Implementation slices and gates

### C5.0 — Contract and replay freeze

- freeze graph/recipe/pin/event/tool-descriptor types;
- enumerate Recipe-#0/#1 tools and replay identities;
- freeze output schemas and parameter body/ref policies;
- add no runtime route yet.

**Gate:** architecture tests prove every standing recipe node has typed outputs, pin requirements,
and a replay strategy; unsafe tools are rejected.

**Implemented:** see the
[versioned tool contract and replay-safety audit](./PC-C5-0-replay-safety-audit.md). This slice
intentionally contains no migration, journal repository, scheduler, or executor.

### C5.1 — Journal and toolbelt choke point

- migration + `clue_execution` repositories;
- version-aware tool registry;
- typed output descriptors;
- parameter snapshots/artifact refs;
- required production journal writer;
- ad-hoc invocation roots.

**Gate:** every HTTP/human/Recipe-#0 test invocation has exactly one graph node, actor, pins, params
ref, and reference-only result; no orphan invocation; cross-workspace reads fail closed.

**Implemented:** random-hash migration `128c83d5e151` creates the full execution/recipe/control
schema, append-only history guards, one rebuildable cursor, and the transactional
`execution_event` → `run_event` projection. The required production `ToolInvoker` now owns exact
descriptor resolution, validated content-addressed parameter snapshots, permanent
operation-scoped replay, actor-attributed terminal/steering events, and the existing short A9 cache.
The HTTP tool route, ingestion route, and narrow Recipe-#0 runner cannot call the bare runner.
Parameter bodies resolve only through the workspace-scoped artifact seam and become metadata-only
tombstones after erasure. Database tests cover success, durable replay/blocking, retry after a
failed attempt, operation conflicts, no-orphan failures, CAS rollback, cursor rebuild, append-only
guards, cross-workspace reads, parameter privacy/erasure, and gapless SSE replay of node events.
No recipe mutation/compatibility behavior, executor, fleet generalization, or supervisor runtime
behavior is included; those remain C5.2+.

### C5.2 — Recipes and compatibility loader

- immutable recipe revisions/events;
- pin resolver registry and production adapters;
- closed binding language and graph validator;
- Recipe #0/#1 definitions seeded as system recipes.

**Gate:** all incompatibilities are named before execution; retired field/source and unavailable
tool versions never reach a tool body.

**Implemented boundary (2026-07-24):** the two checked-in v1 assets establish promoted, immutable
system identities with `migration_state=placeholder`. A placeholder is structurally limited to
barriers and therefore cannot claim that the C4/C5 phase cutovers already happened. C5.4 and C5.6
must append newer executable revisions containing the formal Recipe #0 and Recipe #1 graphs; they
must not mutate these promoted seeds. C5.2 creates no runnable task. The same promotion validator is
already live for executable definitions and requires exact tool/schema/config pins before promotion.

### C5.3 — Durable executor and fleet generalization

- generic leased work handler with legacy adapter;
- second random-hash fleet migration for the reviewed work-id/lease-generation generalization;
- graph task handler;
- execution cursor/event scheduling;
- stable operation ids and crash recovery;
- pause/resume/gate/steer tools; true domain cancellation is explicitly out of scope.

**Gate:** existing fleet exit suite stays green; kill/restart at every crash boundary completes
without duplicate database effect; provider retries are accurately journaled.

### C5.4 — Recipe #0 migration

- durable Stage-0 graph;
- repeated interview child nodes;
- memory/artifact/policy/skill/product/ICP pins;
- stable handoff into Recipe #1;
- compatibility adapter removal after parity.

**Gate:** the C4 URL-only, interview, correction, readiness, override, and run-entry fixture yields
the same normalized outcomes before/after migration and resumes after kill.

### C5.5 — Supervisor and enforced controls

- aggregate reader;
- deterministic monitors;
- bounded triage;
- scheduler/source/envelope enforcement;
- canary health gate and escalation.

**Gate:** fault-injected bad source trips a run-local breaker, quarantines affected accounts, blocks
the remainder, and attaches a diagnosis without pausing unrelated executions.

### C5.6 — Recipe #1 cutover and outcome reproducibility

- phase graph and pre-satisfied Stage-0 nodes;
- canary/deep integration;
- manifest/run-view fallback;
- feature-flagged new-run routing;
- golden outcome fingerprint and two-run comparison.

**Gate:** fixed driver and Recipe #1 produce equivalent claims/gaps/decisions/gates/verification
floors and bounded cost on the golden set; active legacy runs remain resumable; scripts 01–06 stay
green until parity is signed off.

---

## 14. Verification matrix

### Structure and schema

- migration up → down → up; exactly one Alembic head;
- enum/check/index/FK parity;
- append-only recipe/node/edge/pin/event enforcement;
- cursor rebuild from events;
- import-linter package boundaries;
- no graph/journal body columns.

### Tenancy, privacy, and DSAR

- every execution/recipe/read is workspace-scoped;
- system recipes are readable but not tenant-mutable;
- cross-workspace project/input/node/artifact/pin references reject;
- journal parameter artifacts are included in retention/DSAR reach;
- erased parameter/memory artifacts render tombstones with no personal substring;
- raw prompts, turns, uploads, pages, and memory bodies never occur in graph/event JSON.

### Compatibility and typing

- missing/retired/wrong-version tool, field, source, policy, skill, model, profile, or input;
- changed input/output schema digest;
- invalid edge path/type;
- cycle, missing dependency, duplicate node, unbounded map, excess node/depth/fan-out;
- retirement between load and dispatch.

### Execution and idempotency

- concurrent claim, stale takeover, heartbeat loss, and fence generation;
- crash at every lifecycle boundary;
- stable run/recon/proposal/job ids across replay;
- completed-node replay is spend-free;
- precondition failure is visible and never cached as success;
- external-call retry is counted honestly;
- pause/resume and human gate decisions are actor-attributed with before/after.

### Supervisor

- no-sample and low-sample behavior;
- source error-rate breaker with cooldown/release;
- account quarantine/reoffer;
- canary pass and fail;
- envelope can only tighten automatically;
- malformed/injected triage cannot act;
- no turn-by-turn LLM judging;
- unrelated run/workspace remains unaffected.

### Outcome reproducibility

The normalized fingerprint includes:

- recipe/config/input pin manifest;
- field keys attempted and filled;
- claim identity/provenance/verification categories, excluding stochastic prose and generated ids;
- coverage terminal gaps/reason codes;
- readiness, tier, canary, review, and supervisor decisions;
- verification floors and pass/fail categories;
- cost/yield bands and hard-cap compliance.

Two isolated fixture workspaces run the same pinned recipe/config/input set. Their normalized
fingerprints must match. Generated prose and model token counts are explicitly excluded.

---

## 15. Out of scope

- the C6 deepagent, subagent profiles, plan compiler, agent constitution, or open-ended sufficiency
  reasoning;
- free-form user graph editing;
- arbitrary graph cycles or unbounded dynamic expansion;
- transcript-identical replay;
- true cancellation of already accepted provider/domain work; C5 pause prevents new scheduling
  and lets in-flight attempts settle visibly;
- global autonomous source retirement;
- a second truth store for claims, memory, recon, project phases, or account graphs;
- production handoff reader/dossier work owned by C7;
- full provider-boundary exactly-once where providers expose no idempotency key;
- C8's hard fencing of every pre-existing research-domain write path.

---

## 16. Completion definition

C5 is complete only when:

1. every production tool invocation has a non-orphan graph node written by the toolbelt;
2. Recipe #0 and Recipe #1 run through the durable executor;
3. crash recovery and stable-operation replay are proven at the riskiest boundaries;
4. pinned compatibility fails before spend with named reasons;
5. historical runs render complete dependencies, attempts, pins, gates, controls, and outcomes;
6. supervisor actions are enforced by scheduler/source boundaries, not merely logged;
7. the canary blocks a bad fleet with diagnosis and permits a healthy fleet;
8. the golden outcome fingerprint matches across pinned reruns;
9. legacy active runs and scripts remain green through cutover;
10. `make check`, focused DB rerun, migration smoke, SSE replay, DSAR, and adversarial review are
    green.

### Requirement traceability

| Requirement | C5 proof |
|---|---|
| REQ-10 fleet quality/supervision | run-specific aggregate monitor, bounded triage, enforced quarantine/source/envelope controls, canary fault injection |
| REQ-11 live progress/steering | transactional journal→SSE events; actor + before/after for every steering tool; owner-aware resume routing |
| REQ-12 repeatability | toolbelt-authored append-only graph; exact pins/compatibility; complete historical view; Recipe-#0/#1 golden reruns |
| REQ-13 two-pass economics | existing scoring + human tier checkpoint preserved; deep top-cohort canary before the remaining tier-priority fleet |
