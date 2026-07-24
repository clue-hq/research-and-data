# Phase C5 — Run-graph, recipes, executor, and supervisor implementation plan

**Date:** 2026-07-24

**Branch:** `platform/c5-recipe-execution`

**Base:** `08c1998 feat(stage0): implement governed Recipe 0`

**Binding spec:** `docs/specs/PC-C5-run-graph-recipes-executor.md`

## 1. Delivery posture

C5 is one serial integration lane. Its first four slices change the shared execution choke
points—tool descriptors, journaling, compatibility, fleet dispatch—and should not be developed as
independent merge branches. After those contracts are green, Recipe #0 migration and supervisor
aggregate/control adapters may be implemented in parallel worktrees only if they do not both edit
the toolbelt, execution schema, fleet shell, or API composition root.

No C5 runtime code starts until the C5.0 contract/replay audit is committed and reviewed.

The implementation proceeds in seven locally committed checkpoints. Each checkpoint ends with
focused tests, `make check`, migration status where applicable, and an `_memory/` update.

## 2. C5.0 — Freeze contracts and replay identities

**Status:** implemented and verified on 2026-07-24. The checked-in evidence is
[`PC-C5-0-replay-safety-audit.md`](../../specs/PC-C5-0-replay-safety-audit.md). No database
migration or executor code is part of this checkpoint.

### 2.1 Add execution-domain contracts

Create:

- `libs/clue-core/clue_core/execution_graph.py` only for cross-package ids, closed value objects,
  and protocols genuinely shared by toolbelt/execution/projections;
- `platform/execution/pyproject.toml`;
- `platform/execution/clue_execution/{__init__,models}.py`;
- test package `tests/execution/`.

Define:

- `ExecutionId`, `ExecutionNodeId`, `ExecutionAttemptId`, `RecipeId`, `RecipeRevisionId`;
- recipe/node/event/control status vocabularies;
- `PinRequest`, `ResolvedPin`, `Incompatibility`;
- `RunAggregateSnapshot`;
- `ExecutionRunViewReader` projection seam.

Keep lifecycle enums local to `clue_execution` unless another package exchanges them. Do not put
recipe or journal repositories in `clue_core`.

Update:

- root uv workspace typing/source paths;
- Ruff first-party list;
- import-linter roots and contracts;
- `platform/api/pyproject.toml` workspace dependencies.

### 2.2 Make tool contracts recipe-addressable

In `platform/toolbelt/clue_toolbelt/`:

- add a frozen `ToolDescriptor`;
- add `ToolOutput` and typed reference-model support;
- add `ReplayPolicy`;
- add `JournalParameterPolicy`;
- add `ToolEffectClass` and require steering tools to expose a display-safe before/after snapshot
  hook;
- add optional declared pin requests;
- make the registry key `(name, version)`;
- retain an explicit active/default alias per name for `registry.get(name)`;
- make duplicate `(name, version)` and multiple active aliases loud.

Do not use lexical/semantic sorting to infer the active version. Composition declares it.

For the Recipe-#0/#1 tool set, add typed output models at the API root. A tool may retain a
permissive legacy output descriptor for ad-hoc use, but the recipe validator refuses an output
edge from a tool without a typed reference model.

### 2.3 Replay audit

Build a table-driven test inventory for every Recipe-#0/#1 effectful tool:

| Tool class | Durable natural key | Stable id required | External-call residual |
|---|---|---|---|
| onboarding/recon/interview/readiness | existing C4 dedupe keys | verify | resolver at-least-once |
| ICP synthesize/confirm | client/ICP lineage | verify | LLM at-least-once |
| project-run start | none in tool today | derive from operation id | none |
| discovery/scoring/tier gate | project phase/domain ledgers | verify | resolver at-least-once |
| deep/verification/handoff | account/phase ledgers | verify | provider at-least-once |
| pause/resume/adjust | diff/status guards | verify | none |

Add `operation_id` to `ToolContext`. Adapt start tools first so a retry supplies the same
`ProjectRunId`. Any other tool that cannot prove replay safety is marked non-recipe-safe and blocks
the next slice.

**Checkpoint:** `feat(execution): freeze recipe and replay contracts`

**Gate:**

- descriptor/registry/operation-id unit tests;
- standing toolbelt matrix remains green;
- architecture test lists zero uncertified tools in standing recipes;
- `make check`.

## 3. C5.1 — Append-only journal at the toolbelt boundary

### 3.1 Migration

Create one random-hash Alembic revision from the current head for:

- `recipe`;
- `recipe_revision`;
- `recipe_revision_event`;
- `execution`;
- `execution_cursor`;
- `execution_node`;
- `execution_edge`;
- `execution_pin`;
- `execution_attempt`;
- `execution_event`;
- `execution_artifact_ref`;
- `project_run_execution_owner`;
- `supervisor_observation`;
- `supervisor_diagnosis`;
- `run_control_event`.

Use named checks, indexes, composite workspace/context FKs where anchors exist, and reversible
downgrade. Add append-only triggers to immutable/event tables. The cursor is the only normal
mutable execution table.

Hot indexes:

- `(workspace_id, started_at DESC)` execution history;
- `(execution_id, node_key)` nodes;
- `(execution_id, seq)` events;
- `(execution_id, event_type, seq DESC)` effective-state reads;
- `(recipe_id, version)` revisions;
- effective recipe-status event lookup;
- `(execution_id, control_kind, subject_ref, seq DESC)` controls.

### 3.2 Repository and cursor projection

Implement:

- `clue_execution/recipes.py`;
- `clue_execution/journal.py`;
- `clue_execution/views.py`;
- in-memory fakes only where a protocol has a real second implementation.

Event appends and cursor advancement share one transaction and expected `state_version`. A stale
writer fails its compare-and-swap; the journal event remains the source for rebuilding.

Add a rebuild test that drops/reinitializes cursor rows from events and produces identical
effective state.

### 3.3 Parameter snapshots

Implement `clue_execution/parameters.py` behind injected storage/artifact seams:

1. canonical JSON serialization after input validation;
2. workspace-scoped, content-addressed parameter artifact;
3. artifact row + `execution_artifact_ref`;
4. safe display subset from the descriptor;
5. no tool execution if snapshot establishment fails.

Extend artifact retention/DSAR reach to execution refs. A journal read resolves a live artifact or
returns a tombstone; it never embeds the body in an event.

Failure events contain only stable error codes, redacted summaries, and affected refs. Provider
bodies, stack traces, prompts, and validated parameters remain in their governed owner stores and
must not enter execution events.

### 3.4 Tool invoker

Replace scattered production calls to bare `invoke_tool` with a composed `ToolInvoker`:

- exact descriptor resolution;
- input validation;
- parameter snapshot;
- `InvocationJournal.begin`;
- estimate/preconditions;
- idempotency reservation;
- tool call;
- completed/blocked/failed event;
- transactional `run_event` append.

Keep the pure function as an internal/test-compatible wrapper around the same implementation.
Production API startup requires the durable writer. HTTP invocations without a recipe create an
ad-hoc execution root; an explicitly supplied execution context joins an existing node.

Update:

- `platform/api/clue_api/toolbelt_wiring.py`;
- the HTTP tool route in `projections_app.py` or its current owner;
- `stage0_recipe.py`;
- manifest operation execution;
- any direct production `invoke_tool` call found by a static grep.

Add a static test that permits direct runner use only in toolbelt internals/tests.

**Checkpoint:** `feat(execution): journal every tool invocation`

**Gate:**

- migration smoke and one head;
- invocation success/precondition/failure/replay coverage;
- no-orphan structural query;
- cross-workspace negative matrix;
- parameter-body/DSAR negative tests;
- SSE disconnect/replay with node events;
- `make check` and DB rerun.

## 4. C5.2 — Recipe revisions, pins, and compatibility

### 4.1 Recipe repository

Implement proposed → promoted/retired/superseded events. Promotion validates the full graph and
pins before appending the promoted event. A promoted revision cannot change.

Seed system recipe identities through an idempotent API-root boot function, not through a migration
that imports Python models. The seed compares definition digest and refuses an in-place mismatch;
a change requires the next version.

### 4.2 Compatibility registry

Implement `clue_execution/compatibility.py` and register API-root adapters for:

- tool registry descriptors;
- field/source registry `active + version`;
- ICP version;
- source profile version;
- C4 readiness/stage0 policy;
- skill metadata/body digest;
- model/prompt policy;
- product-context manifest;
- artifact input;
- memory switch/bundle journal.

Each adapter returns a canonical payload digest. The loader:

1. resolves every execution-wide requirement;
2. resolves node-local requirements;
3. sorts and records pins deterministically;
4. returns all incompatibilities together;
5. creates no runnable task if any requirement fails.

Re-check node-local pins immediately before dispatch to catch retirement after initial load.

### 4.3 Graph and binding validator

Implement:

- closed binding AST (`literal`, `parameter`, `node_reference`);
- cycle/missing dependency checks;
- input/output JSON-schema compatibility;
- output-reference path validation;
- map cardinality/depth/node ceilings;
- authority/gate/tool allowlists;
- canonical graph digest.

No Jinja, eval, callable import path, or arbitrary JSONPath.

### 4.4 Standing recipe definitions

Add version-controlled definitions under:

```text
platform/execution/recipes/recipe0-stage0-v1.json
platform/execution/recipes/recipe1-classic-v1.json
```

They are build-time assets loaded into typed models; JSON is chosen so digests and operator review
are stable. Tests compare the checked-in digest with the promoted seed.

**Checkpoint:** `feat(execution): add immutable recipes and compatibility loading`

**Gate:**

- every pin adapter exact/missing/retired/version-mismatch;
- retirement between load and dispatch;
- graph fuzz/property tests;
- system-recipe seed replay;
- no graph body-content fixtures;
- `make check`.

## 5. C5.3 — Durable executor and fleet work-handler extraction

### 5.1 Preserve fleet behavior before generalizing

First add characterization tests around:

- `ProjectRunWorker` claim/lease/heartbeat/fencing outcomes;
- drive-task reopen behavior;
- account-job tier ordering and replay;
- graceful stop and stale takeover.

Then refactor `clue_fleet`:

- create a second random-hash Alembic migration chained from the C5.1 head;
- introduce local `WorkId`;
- rename fleet-internal top-level key vocabulary from project run to work id;
- migrate `run_lease` to a generic work lease and add monotone generation;
- add `execute_graph` task kind;
- extract `WorkHandler` and generic leased drain;
- implement the old project driver as a compatibility handler;
- keep exported project-run helpers/signatures as adapters.

Do not change research project/account tables or phase behavior in this refactor.

### 5.2 Executor

Implement `clue_execution/executor.py`:

- deterministic ready-node selection;
- bounded concurrency;
- node attempt reservation;
- execution-scoped idempotency;
- expected lease-generation checks on cursor writes;
- gate/pause/resume/failure policies;
- bounded map expansion with append-only child nodes/edges;
- stable result ordering;
- cursor rebuild and abandoned-attempt recovery.

Implement `clue_execution/worker.py` as the `execute_graph` work handler and compose it in
`fleet_main`. A worker process may drain both project-drive and graph tasks through the handler
registry; deployment may later split queues without changing executor contracts.

### 5.3 Control tools

Register:

- `start_recipe_execution`;
- `pause_recipe_execution`;
- `resume_recipe_execution`;
- `decide_recipe_gate`;
- `pin_execution_as_recipe`;
- `advance_project_phase` for Recipe #1.

Every tool returns typed refs. Human-required/destructive actions declare loud preconditions.
C5 intentionally omits cancellation: it cannot yet prove cancellation of already accepted
provider/domain work, so exposing a cancel control would overstate the guarantee. Pause prevents
new scheduling and lets in-flight attempts settle visibly.

Add the single project-run drive-routing lookup:

- a Recipe-#1 execution atomically claims `project_run_execution_owner`;
- `resume_run`, tier-checkpoint submission, and review-finalize re-enqueue the owning graph
  execution when that link exists;
- unowned legacy runs continue to enqueue `drive_run`;
- a second owner or an attempt to drive an owned run through the legacy worker fails loud.

All steering tools record actor plus display-safe before/after state. Add a descriptor-level test
that refuses to register a steering tool without its audit snapshot implementation.

### 5.4 Crash matrix

Use real OS worker processes and SIGKILL, modeled on `tests/fleet/test_exit_gate.py`. Inject crash
hooks at:

- attempt-start commit;
- immediately before tool call;
- immediately after domain commit;
- completion-event commit;
- cursor update;
- map child expansion;
- gate decision;
- worker lease loss.

Assert normalized database effects, ledger rows, graph attempts/events, and provider call counts.

**Checkpoint:** `feat(execution): add crash-resumable graph executor`

**Gate:**

- unchanged B1/B4 fleet suite;
- execution kill/restart suite;
- no duplicate database effects for certified tools;
- truthful provider retries;
- migration smoke/rerun;
- `make check`.

## 6. C5.4 — Migrate Recipe #0

### 6.1 Formal graph

Translate C4's step shape into the promoted Recipe-#0 revision:

- onboarding input;
- fast/background recon child activities;
- repeated interview child-node slot;
- product confirmation gate;
- readiness evaluation/override gate;
- ICP synthesize/confirm;
- product-context pin;
- confirmed project-run start;
- Recipe-#1 execution attachment.

The executor may dynamically append only the allowed Stage-0 child tool nodes and only within the
recipe's interaction/node ceiling.

### 6.2 C4 adapter

Change `ToolbeltRecipeRunner.run_step` to submit/execute one durable node and return its
`ToolResult`. Preserve its protocol during migration. Once all C4 tests use the durable execution
and the in-memory `run()` has no production caller, remove the implementation or keep only a
deprecated test helper with an explicit null journal.

### 6.3 Pins and links

Record:

- onboarding and interview artifact refs;
- recon Recipe/skill/policy/tool/model/source pins;
- Client-KB and product-context versions;
- readiness spec/decision/override refs;
- ICP key/version and source profile;
- memory enabled state and `memory_bundle_journal` id when assembled.

Never copy Client-KB claims, memory labels, artifact bodies, or interview text into C5 tables.
Treat the memory kill switch as live safety authority: an old enabled-state observation can never
turn memory back on. A revision that requires memory fails pre-dispatch with `memory_disabled`
while the switch is off; an optional-memory revision pins the disabled state and runs without a
bundle.

### 6.4 Parity and recovery

Run the existing C4 end-to-end test both ways against isolated schemas, compare the normalized
outcome fingerprint, then kill during fast recon, background recon, interview routing, and
confirmed-run creation.

**Checkpoint:** `feat(execution): migrate Recipe 0 to the durable executor`

**Gate:**

- all C4 focused tests;
- Recipe-#0 parity fingerprint;
- Stage-0 crash/resume;
- DSAR/tombstone and workspace-locality;
- `make check`.

## 7. C5.5 — Supervisor, controls, and canary enforcement

### 7.1 Run-specific aggregate reader

At the API root, compose an injected `RunAggregateReader` over:

- M13.4 progress/burn-down/verification/coverage;
- C1 attempts and decisions queried by `project_run_id`;
- run-specific source yield/error/latency telemetry;
- fleet/account-job state and stall ages;
- execution failures/precondition blocks.

Where existing telemetry is not run-specific enough, add the smallest owned read/index/field
delta. Do not use workspace/ICP lifetime aggregates as if they described one canary.

### 7.2 Monitor and triage

Implement versioned supervisor policy in `clue_config`:

- canary size;
- sample floors;
- verification/yield/error/stall thresholds;
- cooldowns;
- permitted automatic actions;
- maximum quarantine/breaker/envelope scope;
- triage model/prompt versions.

Implement deterministic observations first. Add one injected LLM triage leaf only for triggered,
grouped anomalies. Parse through a closed Pydantic model and journal requested/answering model.

### 7.3 Runtime controls

Account:

- inject an admission callback into `QueueBackedScheduler`;
- quarantined accounts finish/park with an explicit governed-partial result;
- release reoffers the account through an idempotent task transition.

Source:

- extend `PreSpendRequest` or add a sibling source-call gate so the exact `source_key` and execution
  coordinate are present before provider I/O;
- wrap the production pre-spend/source boundary with run-control enforcement;
- a tripped breaker rejects only that source in that execution.

Envelope:

- persist an effective tightening overlay;
- apply it at scheduler fan-out/depth/account admission;
- automatic action may only reduce the original approved envelope.

Escalation:

- append the control event;
- pause the relevant execution/deep gate;
- attach observation/diagnosis/affected refs and safe choices.

Register action/release/override tools so all state changes ride the toolbelt and journal.

### 7.4 Deep canary

Add an injected cohort/supervisor seam to the existing deep handler:

- stable tier-priority sort;
- run top `N`;
- supervisor snapshot/gate;
- only then run remainder;
- pause deep on failure.

The same `AccountDeepOrchestrator`, budget engine, queue, locks, and ledgers execute both cohorts.
No second deep implementation is allowed.

**Checkpoint:** `feat(execution): enforce supervisor controls and deep canary`

**Gate:**

- bad-source fault injection;
- canary pass/fail;
- account quarantine/release;
- source breaker/release before provider call;
- envelope monotonic tightening;
- malformed/injected triage cannot act;
- unrelated run/workspace isolation;
- `make check`.

## 8. C5.6 — Recipe #1 cutover and run views

### 8.1 Phase graph

Implement Recipe #1 with one `advance_project_phase(expected_phase=...)` node per real enum member.
The phase tool calls one `ProjectRun.advance`, then returns the exact checkpoint/run refs.

Gate handling:

- tier checkpoint waits for the existing `submit_tier_checkpoint` tool;
- review waits for the existing review/finalize path;
- deep canary waits for supervisor/human decision when unhealthy.

Recipe-#0 confirmed entry marks reverse/ICP nodes `pre_satisfied` only after validating the
immutable C4 lineage pins. Legacy entry starts at reverse profiling.

### 8.2 Routing and coexistence

Add settings:

- Recipe-#1 routing disabled by default;
- workspace allowlist or percentage canary;
- supervisor policy version;
- executor worker limits.

New eligible starts create Recipe-#1 executions. Existing project runs with no execution continue
through `ProjectRunWorker`. Do not backfill live executions.

### 8.3 Projections

Add DTOs/read functions for:

- execution overview;
- graph/timeline;
- recipe library and compatibility;
- supervisor/control history.

Modify A4 manifest:

1. locate attached C5 execution in workspace;
2. render journal nodes/edges/pins when present;
3. otherwise use the existing synthetic phase/account view.

Extend SSE topics and replay tests. Event emission from C5 journal transitions is transactional,
not best-effort.

### 8.4 Golden outcome gate

Create one canonical fingerprint builder used only by tests/evals. Compare:

- legacy fixed driver vs Recipe #1;
- two Recipe-#1 runs in isolated fixture workspaces;
- pre- and post-Recipe-#0 migration.

Exclude generated ids, timestamps, prose, ordering of semantically unordered claim refs, and raw
token counts. Include pins, attempted/filled fields, terminal gaps, gates, verification categories,
control decisions, and budget/yield bands.

Only after parity:

- enable Recipe #1 for the controlled canary workspace;
- retain fallback for legacy runs;
- update docs/status from planned to implemented.

**Checkpoint:** `feat(execution): adopt Recipe 1 with reproducible run views`

**Gate:**

- legacy/recipe parity;
- same-recipe two-run fingerprint;
- scripts 01–06;
- historical run-view completeness/no orphans;
- SSE reconnect zero-gap;
- full configured test suite rerun;
- migration up/down/up and one head;
- adversarial review findings closed.

## 9. Review checklist before each checkpoint

1. Is any body or mutable domain truth copied into graph JSON?
2. Can a tool be retried after the A9 TTL without changing its durable identity?
3. Can a lease-lost worker still update the C5 cursor?
4. Does every control change real scheduler/source behavior?
5. Can a recipe begin spend before all compatibility refs resolve?
6. Does a new version float into a running execution?
7. Is any supervisor/LLM output being treated as authority?
8. Can a cross-workspace id reveal existence?
9. Does a historical view have an orphan invocation, missing dependency, or missing pin?
10. Does Recipe #1 call the existing phase/account implementation or accidentally fork it?

Any “yes” to questions 1–3 or 5–10, or “no” to question 4, blocks the checkpoint.

## 10. Final handoff

At completion:

- update `PC-C5-run-graph-recipes-executor.md`, the Phase-C parent, and specs index to implemented;
- record exact migration head, test counts, fault-injection evidence, and remaining external-call
  residuals in `_memory/`;
- commit locally in coherent checkpoints;
- do not push or open a PR without explicit instruction;
- hand C6 the stable graph-append, profile/skill pin, context-bundle link, authority, and finalize
  contracts. C6 must not bypass or replace the C5 executor.
