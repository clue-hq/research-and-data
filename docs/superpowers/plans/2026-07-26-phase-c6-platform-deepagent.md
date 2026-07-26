# Phase C6 — implementation plan

**Date:** 2026-07-26
**Branch:** `platform/c6-deepagent-runtime`
**Base checkpoint:** `f25e9b5` (`feat(execution): adopt Recipe 1 with reproducible run views`)
**Binding child spec:** [PC-C6](../../specs/PC-C6-platform-deepagent-and-skills.md)
**Current checkpoint:** C6.0–C6.8 implemented and verified; C6 is complete. C6.7 added the governed
per-account research-agent unit, replay-safe `research_account_gaps@2`, and the explicit ruling
that C1's `GoalJudge` remains the sole independent coverage evaluator. C6.6 adds fresh-wake
research, content-drafter, and reviewer specialists behind the governed C5 delegation operation.
It freezes typed task/file/ref transfer, per-role prompts/skills/tools/workspaces/models/time and
round limits, distinct child executions, empty child history, durable-before-return output
contracts, human-gate propagation, and parent/child spend rollup. The framework's generic `task`
tool remains filtered. C6.8 added default-off durable ownership routing, production API-root
composition, read projections, telemetry, cleanup, canary evaluation, and the C7 handoff.

This plan is the cross-session execution record for C6. Complete and verify one slice before
starting the next. Do not begin database migration or production executor work until C6.0 closes
the framework, tool-calling, workspace, resource-version, and replay-safety unknowns.

## 1. Fixed implementation posture

- Technical/senior-engineering execution; no product-management workflow is needed.
- Use the real Doc-A deepagent framework.
- Preserve C5 as the durable graph/tool execution spine.
- Keep all model-controlled files in an isolated external per-execution workspace.
- Require `virtual_mode=True`; expose only virtual-root-relative paths.
- Put no application code or executable skills in runtime workspaces.
- Use folder-backed prompt/skill/profile catalogs in V1.
- Keep LangSmith/Langfuse and prompt hubs out of scope.
- Keep C1 `GoalJudge` as the sole independent, non-authoritative evaluator.
- Keep C4/C5 fallback behavior behind default-off C6 routing.

## 2. Planned checkpoints

| Slice | Purpose | May add migration? | Required checkpoint |
|---|---|---:|---|
| C6.0 | **Complete** — freeze contracts and prove external runtime assumptions | No | architecture/spike tests green |
| C6.1 | **Complete** — isolated workspace, virtual backend, resource materialization | No migration added | isolation battery green |
| C6.2 | **Complete** — folder catalogs, profiles, registry, tool-calling model seam | No migration added | exact resource/allowlist/import gates green |
| C6.3 | **Complete** — typed turns, seven-layer context, history, receipts | Yes | migration smoke + body-free replay green |
| C6.4 | **Complete** — plan compiler, governed tools, delegation, finalize | Additive only | crash/authority/replay matrix green |
| C6.5 | **Complete** — Head-of-ABM Stage-0 vertical | No migration added | C4 parity + agent-quality eval |
| C6.6 | **Complete** — fresh-wake specialist subagents | No migration added | delegation/authority parity |
| C6.7 | **Complete** — governed per-account worker agent | Yes | fleet/evaluator/quality parity |
| C6.8 | **Complete** — composition, canary, hardening, close-out | Yes | full repository gate |

Each completed slice receives:

1. focused unit/integration/adversarial tests;
2. `ruff`, `mypy`, and import-linter checks proportionate to the change;
3. DB tests and migration smoke whenever schema changes;
4. a concise `_memory/` checkpoint;
5. a local, well-scoped commit.

## 3. C6.0 — contract freeze and executable spikes

### Deliverables

1. Confirm the current `deepagents` API and pin a compatible version.
2. Build disposable tests proving:
   - real orchestrator construction;
   - explicit tool registration;
   - injected provider-neutral tool-calling model;
   - `virtual_mode=True`;
   - relative virtual paths;
   - fresh-wake subagent construction;
   - shared workspace with narrowed child permissions;
   - LangGraph checkpoint/resume;
   - interception of normal model termination without a finalize envelope.
3. Freeze strict types for:
   - resource addresses/manifests;
   - profile and effective tool policy;
   - constitution;
   - workspace policy/layout;
   - context receipt;
   - plan proposal/validation;
   - delegation;
   - finalization.
4. Inventory the existing 32-tool registry and assign first-version Head-of-ABM/research/content/
   review allowlists. A tool that has no valid C6 use is absent.
5. Produce the replay/authority matrix for every model-triggerable operation.
6. Confirm the minimal tool-calling gateway delta. Do not let `clue_agents` import
   `clue_gateway` or provider SDKs.

### Stop conditions

Stop before production work if the selected framework cannot prove virtual isolation, injected
tool authority, fresh-wake delegation, or required finalization. Resolve the mismatch in the
contract or select the framework-supported adapter; do not emulate missing agency with a
hand-written loop.

### Verification

- spike tests are deterministic and offline;
- dependency lock resolves;
- import contracts remain green;
- no migration or production routing exists;
- child spec and threat/replay matrices match the executable evidence.

### C6.0 close-out — 2026-07-26

Implemented:

- strict frozen contracts in `clue_agents.contracts`, injected protocols in `clue_agents.ports`,
  and trusted `ClueDeepAgentState`;
- exact `deepagents==0.6.12` and `langchain-openai==1.4.1` pins;
- `OpenRouterAgentModelProvider` inside the sole `clue_gateway` provider boundary;
- deterministic real-framework, tool-call, artifact-workspace, and honest-finalize spikes;
- real async-Postgres failure/resume proof with a newly compiled graph;
- JSON Schema digest, path/scope/plan/finalize, port-shape, and complete 32-tool authority gates;
- the binding dependency, replay/authority, and filesystem-threat record in the child spec.

Resolved decisions:

- stock `FilesystemBackend` is compatibility evidence only and is rejected for production;
- C6.1 supplies a hardened artifact-backed backend and validates relative model paths before the
  framework converts them to virtual leading-slash form;
- the model adapter stays in `clue_gateway`; `clue_agents` sees only `BaseChatModel`;
- normal framework termination is never success without a valid finalization envelope;
- steering tools remain human-only and seven replay-uncertified tools remain absent until audited.

Exit gate result: **passed**. No Alembic migration, API composition, production workspace,
executor, or feature routing was added. Proceed to C6.1 only.

## 4. C6.1 — isolated workspace and resource materializer

### Package work

Add focused modules under `clue_agents` for logical contracts/policies and production adapters at
the `clue_api` composition root:

```text
platform/agents/clue_agents/
  resources.py
  workspace.py
  workspace_policy.py

platform/api/clue_api/
  agent_workspace_wiring.py
```

Names may refine during implementation; ownership may not.

### Workspace creation

- add explicit `CLUE_AGENT_WORKSPACE_ROOT`;
- validate it is a dedicated root outside and unrelated to the source worktree/home;
- create `<workspace>/<project>/<execution>` using validated typed ids;
- create directories with owner-only permissions;
- create files atomically with owner-only permissions and no executable bits;
- use anchored/no-follow operations;
- reject pre-existing unexpected files, links, and type mismatches;
- never return host paths from an agent-facing method or error.

### Virtual backend

- expose `list`, `read`, `write`, `edit`, and `stat` only as needed;
- accept normalized relative POSIX paths only;
- enforce readable/writable prefix policy on every operation;
- enforce file-count, per-file, and total-byte quotas;
- remove/omit shell, subprocess, code execution, environment, network, and package tools;
- bind `virtual_mode=True` in one constructor with a regression assertion.

### Materialization

- validate exact catalog resources;
- copy bytes—never links—under `.deepagent/`;
- materialize context/input resources read-only;
- write the aggregate manifest last;
- freeze the resource tree before model construction;
- finalize output files through `StorageBackend` and return artifact refs;
- cleanup according to retention only after durable finalization.

### Adversarial matrix

Cover absolute paths, `..`, repeated separators, backslashes, control characters, Unicode
confusables, symlink swaps, file replacement races, cross-execution ids, hard-link attempts,
oversized files, too many files, executable extensions/bits, read-only mutation, repository reads,
secret/env reads, and cleanup-before-finalization.

### C6.1 close-out — 2026-07-26

Implemented:

- `CLUE_AGENT_WORKSPACE_ROOT` composition with a dedicated-root policy that rejects source/home
  ancestors and descendants, links and dot components, permissive modes, wrong types, and
  unexpected scope entries;
- one-shot `<workspace>/<project>/<execution>` creation with validated ASCII identity segments,
  opaque agent root ids, mode `0700` directories, and no host paths in the agent-facing surface;
- a real Deep Agents `BackendProtocol` implementation with `virtual_mode=True`, relative
  list/read/stat/write/edit/glob/grep/upload/download support, prefix and data-extension authority,
  and no execute/shell/process/environment/package surface;
- descriptor-anchored `O_NOFOLLOW` traversal, regular/private/non-executable/single-link checks,
  process and filesystem locking, atomic no-replace writes, atomic compare-and-swap edits, crash
  residue rejection, and per-file/total/count quotas;
- exact resource snapshot validation and byte-copy materialization beneath `.deepagent/`, plus
  immutable context/input seeds, canonical manifest-last write, digest verification, and frozen
  `0500`/`0400` trees before a lease becomes model-ready;
- single-flight output freezing and workspace-scoped content-addressed `StorageBackend` handoff;
  cleanup remains impossible until outputs are snapshotted and a same-workspace durable
  finalization ref authorizes retention cleanup.

The folder catalog schemas/loaders and real role resources remain C6.2 work. C6.1 deliberately
implemented their exact immutable snapshot/materialization consumer without pre-empting that
catalog ownership. No migration, agent construction, executor, route, or feature flag was added.

Verification:

- C6.1/root/resource/API adversarial suite: 49 passed;
- all agent tests: 67 passed, 1 skipped;
- Ruff format/lint over the repository excluding unrelated untracked `.claude/` and `.codex/`
  copies: green across 820 files;
- mypy: 401 source files, green;
- import-linter: 24 contracts kept, 0 broken;
- repository pytest: 1,461 passed, 1,070 skipped;
- `git diff --check`: green.

The literal `make check` remains obstructed only by the preserved untracked `.claude/` and
`.codex/` structural-humanizer CLI copies (16 `T201` findings). Its source-controlled equivalent
was run explicitly and passed.

## 5. C6.2 — catalogs, profiles, registry, and model seam

### Catalog

Create:

```text
platform/agents/catalog/
  prompts/head-of-abm/v1/SYSTEM.md
  prompts/research-specialist/v1/SYSTEM.md
  prompts/content-drafter/v1/SYSTEM.md
  prompts/reviewer/v1/SYSTEM.md
  skills/stage0-interview/v2/SKILL.md
  profiles/head-of-abm/v1/profile.yaml
  profiles/research-specialist/v1/profile.yaml
  profiles/content-drafter/v1/profile.yaml
  profiles/reviewer/v1/profile.yaml
```

Migrate the C4 Stage-0 skill semantically; do not mutate its used V1 bytes in place. Keep
resource files declarative and non-executable.

Implement strict catalog loaders, semantic-version validation, canonical hashing, duplicate
address detection, cross-resource resolution, and aggregate manifests. Use a generic catalog
protocol so a future remote provider can supply the same descriptors without changing consumers.

### Profiles and registry

- define fixed V1 roles and status;
- resolve prompt, skills, model policy, memory policy, delegation policy, file policy, and exact
  tool allowlist;
- intersect child/delegated policy with the parent and engine ceiling;
- generate the exhaustive resource map from resolved facts, not hand-maintained prose;
- expose a projection-safe registry/profile descriptor without prompt bodies or host paths.

### Model seam

- extend the shared provider-neutral contract only as much as real framework tool-calling needs;
- keep provider construction and credentials in `clue_api`/`clue_gateway`;
- preserve usage, answering-model, cost, timeout, retry, and trace attribution;
- provide deterministic scripted tool-call/finalize responses for tests.

### Structural enforcement

Tighten the `clue_agents` import contract to forbid `clue_execution`, `clue_storage`, and other
runtime/domain packages in addition to existing forbidden modules. All concrete dependencies are
injected as narrow protocols.

### C6.2 close-out — 2026-07-26

Implemented:

- immutable folder resources for four V1 roles and the additive Stage-0 interview V2 skill;
- strict, eager prompt/skill/profile catalogs behind provider-neutral protocols, with exact
  version, schema, file-shape, UTF-8, mode, link, digest, and folder-identity validation;
- reviewed active-role resolution, exact live tool-schema pins, engine ceilings, separate
  delegation grants, parent/child tool and workspace intersection, stable aggregate manifests,
  body-free/host-free projections, and a planned account-research registry entry;
- progressive skill disclosure: profile projections expose bounded metadata and an exact
  materialized path, while the body opens only by a disclosed immutable address;
- a deterministic scripted `BaseChatModel` and a production OpenRouter model provider preserving
  standard tool calls, sync/async and streaming behavior, primary/fallback identity, token usage,
  configured cost, timeout/retry ceilings, and the shared model-call trace/event surface;
- production composition at `clue_api`, while `clue_agents` remains independent of gateway,
  provider, storage, execution, fleet, research, memory, and content implementations.

Resolved decisions:

- the used C4 flat Stage-0 V1 bytes remain frozen; C6 owns a semantically migrated V2 resource;
- direct parent tools and delegated child grants are distinct authority envelopes, so the Head
  does not receive specialist tools merely because it may delegate them;
- `account_research` remains registry-visible but planned until C6.7, with no prematurely active
  profile;
- human steering and all seven replay-uncertified tools remain structurally absent;
- folder catalogs are the V1 provider only; registry consumers depend on catalog protocols so a
  later prompt hub can replace the provider without changing runtime contracts.

No database migration, turn/history store, context assembler, deepagent construction, executor,
route, or feature flag was added. C6.3 may now add durable turns and seven-layer context against
these exact resource/profile/model contracts.

## 6. C6.3 — durable turns and seven-layer context

### Schema first

After C6.0 contracts are frozen, add one reversible random-hash Alembic revision for the minimal
durable surfaces not already expressible as C5 refs/events:

- agent turn identity/status and parent execution;
- exact agent/profile/resource-manifest refs;
- model-call receipt;
- context-bundle receipt with layer rows or a normalized equivalent;
- append-only conversation message refs;
- finalization identity/status;
- artifact/ref links and tombstone/retention fields.

Prefer C5 execution events/pins where they already satisfy the contract. Do not add body columns.
Delegation data belongs to C6.4 and should use the same migration only if its contract is already
frozen; otherwise use a later additive revision.

### Context assembler

Implement L1–L7 as independent deterministic layer providers with:

- typed input/output;
- per-layer budgets;
- stable ordering;
- workspace/project scoping;
- explicit included/excluded refs;
- compiled card versions and provenance;
- materialized read-only files where appropriate;
- aggregate receipt hashing.

The agent may request more context through allowed tools after turn start. Opening context is
never gathered ad hoc by the model.

### History and privacy

- history is append-only;
- large/canonical bodies remain artifacts/files by ref;
- journals store ids/hashes/counts/reasons only;
- DSAR reaches materialized personal-data outputs and context artifacts;
- tombstoned inputs fail closed on replay;
- context compaction cannot erase the only durable copy.

### C6.3 close-out — 2026-07-26

Implemented:

- one reversible random-hash migration, `7e9269ed8a81`, with a single head and normalized,
  append-only agent-turn, event, artifact-ref/subject/tombstone, context-bundle/layer/ref,
  thread-message, model-call, finalization, and privacy-event records;
- structural execution/workspace/thread/resource/artifact constraints, including parent execution,
  exact profile and resource-manifest identities, content-addressed artifact checks, and no body
  columns;
- deterministic independent L1–L7 providers with canonical ordering, versioned hard budgets,
  conservative versioned counting, required-authority fail-closed behavior, exact included and
  excluded refs, read-only materializations, compiled-card versions, and aggregate hashing;
- append-only, advisory-lock-serialized history by durable artifact ref;
- a durable workspace-scoped artifact store/reader that records the DB row before the blob,
  verifies exact bytes/metadata, binds privacy subjects, and refuses tombstone resurrection;
- body-free cold replay reporting the exact turn/profile/resource manifest, context policy,
  per-layer budgets, source refs, hashes, artifact states, and blockers without loading bodies;
- DSAR propagation from explicit artifact and scoped-memory subject bindings to artifact
  tombstones, physical blob purge, replay failure, and privileged deletion of affected isolated
  execution workspaces after closing live backends;
- idempotent turn, context, history, model-call, artifact-ref, and finalization receipt writes.

Boundaries preserved:

- raw attachments are pointers only in opening context;
- prompt, card, message, memory, model-output, and workspace-output bodies remain in their owning
  resource/domain/artifact stores;
- no model loop, plan compiler, governed tool execution, delegation record, finalize authority,
  route, or feature flag was added.

Exit gate result: **passed**. Cross-workspace reads fail closed; erased refs and scoped-memory
tombstones block replay; append-only mutation is rejected; a DB-backed cold replay explains exact
resources and context without reading bodies. The 2,559-test repository suite, Ruff, Mypy, all 24
import contracts, one-head check, and clean isolated up→down→up migration smoke are green.

## 7. C6.4 — plan compiler, governed tool bridge, delegation, finalize

### Tool bridge

Wrap the effective tool descriptors for the framework. The adapter:

- obtains trusted identity from `AgentConstitution`;
- accepts model-controlled domain parameters only;
- derives stable operation ids from execution + plan node/tool position;
- validates exact input/output schemas;
- appends accepted nodes through C5;
- invokes through `ToolInvoker`;
- returns bounded typed receipts and refs.

No direct capability implementation enters `clue_agents`.

### Plan compiler

Compile a strict proposal into C5 `RecipeGraph`/dynamic nodes. Reuse C5 validators and add
agent-specific checks:

- effective tool/resource/profile allowlist;
- gate closure;
- externalization boundary;
- parameter/reference scope;
- max nodes/depth/fan-out/rounds;
- estimated envelope;
- child delegation constraints.

Reject the entire invalid proposal before partial domain execution.

### Delegation

- create one parent delegation record before child execution;
- derive a child envelope;
- materialize a task artifact and explicit path/ref grants;
- construct the child fresh from pinned resources;
- journal child execution and roll up spend/status;
- require durable file/domain refs before accepting substantive returns.

### Honest finalize

Expose one required finalize mechanism. Validate and durably commit its artifact and refs before
marking the turn successful. Model stop, malformed finalize, timeout, cancellation, crash, or
storage failure produces failed/abandoned state. Retrying a finalized operation is a no-op.

Run fault injection across model-call, plan-append, pre-tool, post-domain-commit,
post-tool-complete, child-start, child-complete, artifact-store, finalize-event, and cursor-update
boundaries.

### C6.4 implementation record

- `clue_agents.execution` owns bounded proposal policy, stable operation identities, authority
  digests, and reference-only receipts without importing infrastructure.
- `clue_agents.runtime` constructs the real deepagents graph with exact injected model, isolated
  backend, governed tools, durable checkpointer, callback receipts, timeout, and round ceilings.
  Normal framework stop has no success authority.
- `clue_api.agent_execution_wiring` compiles the entire proposal into C5's graph/binding language,
  validates it against the live interaction slot before effects, appends accepted tool nodes
  through `RecipeExecutor`, and therefore invokes only through C5's mandatory `ToolInvoker`.
- Delegations persist parent authority, narrowed resource/budget/path grants, and `child_started`
  before fresh wake. Stable child execution identity plus persisted result recovery prevents
  duplicate child execution after completion.
- `clue_api.agent_runtime_wiring` exposes only exact effective descriptors and one required
  `finalize_turn` mechanism. Model-controlled input cannot set trusted identity, operation ids,
  output snapshots, or timestamps.
- Finalization verifies all refs and the frozen output snapshot, commits the envelope and terminal
  turn event atomically, treats exact retry as a no-op, rejects a different retry, and authorizes
  workspace cleanup only after durable authority.
- Fault tests cover the C6-owned model, plan-append, post-tool-complete, child-start,
  child-complete, artifact-store, finalize-event, and cursor-update boundaries. Existing C5
  executor recovery tests remain authoritative for pre-tool, post-domain-commit, and completion
  event recovery.

## 8. C6.5 — Stage-0 Head-of-ABM vertical

Compose the Head-of-ABM with only the Stage-0 tools required by the promoted profile. Use:

- C4 onboarding/recon/interview/product/readiness/ICP/start tools;
- C1 coverage and gap projections where relevant;
- C2 field/source proposal paths;
- C3 ingestion paths;
- C5 Recipe #0 and confirmed Recipe #1 handoff.

The Stage-0 skill must:

- start from current recon/product truth;
- ask material gaps rather than follow a questionnaire;
- preserve exact user statements through C4 routes;
- distinguish claims, memory, project intent, proposals, and artifacts;
- reason about motion-specific sufficiency;
- surface assumptions and missing evidence;
- require human product/ICP confirmation and readiness override;
- never treat confident prose as deterministic readiness.

Run direct C4 vs C6 normalized outcome parity plus qualitative evals for URL-only, known-product,
stale-product, contradictory correction, uploads, novel fields/sources, missing floors, override,
and confirmed start.

### C6.5 implementation record

- `head-of-abm@v2`, its pinned `SYSTEM.md`, and `stage0-interview@v3` are additive immutable
  resources. Production selection is explicit; the C6.2 v1 resources remain available for
  historical replay without mutation.
- The effective Head profile contains exactly nine direct tools: onboarding, recon, interview
  evidence, readiness, ICP synthesis, field/source proposals, ingestion, and confirmed-run start.
  Product/ICP confirmation, readiness override, proposal approval, budget/checkpoint authority,
  post-Stage-0 execution, and specialist delegation are structurally absent.
- The registry generates one host-free resource/capability map from exact resolved facts. It names
  all 32 platform tools as available, human-only, replay-blocked, or role/profile unavailable;
  discloses the bounded framework filesystem/finalize tools; and explicitly names missing shell,
  execution, network, host, secret, provider, and C6.6 delegation capabilities.
- Progressive disclosure puts only the Stage-0 skill summary and immutable path in opening
  context. The full skill is materialized read-only under `.deepagent/skills/...` and opened only
  when Stage 0 is active.
- `DeepAgentTurnRuntime` still uses the real `create_deep_agent`. Its exact-surface middleware
  removes DeepAgents 0.6's default general-purpose `task` tool; C6.6 supplies the separately
  governed `delegate_specialist` operation. It rejects fabricated or backend-contributed
  capabilities and appends the generated resource map after framework prompt middleware so the
  authoritative map is always the final system-prompt section.
- `HeadOfAbmStage0Runtime` binds the promoted profile, context, isolated workspace lease, durable
  turn journal, per-role governed model construction, exact tools, C5 adapter, and finalization
  authority for one turn. It constructs the model loop with the same execution adapter used by
  its governed tools; no second or bypass executor exists.
- Recipe #0 v3 adds replay-certified `propose_field`, `propose_source`, and `submit_ingestion`
  operations plus proposal/ingestion policy pins without mutating v1/v2. Proposal rows are
  domain-idempotent by complete scope and immutable payload hash; ingestion is at-least-once with
  a workspace/content/context durable identity.
- The agent C5 compiler resolves the same Stage-0 pin provider used by direct Recipe #0, validates
  pin kinds against the active interaction slot, and forwards exact pin requests into dynamic
  nodes before invocation. Every domain effect still flows through `RecipeExecutor` and
  `ToolInvoker`; confirmed Recipe #1 remains reachable only through
  `start_confirmed_project_run`.
- Offline tests cover the real framework construction, exact tool filtering, governed descriptor
  invocation, missing-finalize failure, durable finalize acceptance, all ten qualitative Stage-0
  fixtures, C4/direct versus Recipe #0 normalized outcome parity, resource-pin parity, human gate
  absence, and historical C6.4 delegation compatibility.

## 9. C6.6 — specialist subagents

Implement each profile against a bounded task:

- **Research specialist:** gap/source strategy and dossier questions; domain findings must become
  claim/proposal refs through tools.
- **Content drafter:** exemplar/workspace artifact drafting only; it does not create claim truth or
  scaled production runs.
- **Reviewer:** critique/verdict artifact only; it cannot edit another agent's canonical artifact
  or promote claims.

For each, freeze:

- allowed tools;
- readable/writable workspace prefixes;
- accepted task/ref shape;
- model and token/time budget;
- maximum delegation depth/count;
- final return shape;
- refusal/precondition behavior.

Prove fresh wake, no hidden history, no paraphrase substitution for canonical sources,
parent-child budget rollup, gate parity, and durable-before-return behavior.

## 10. C6.7 — governed per-account research agent

Integrate one small agent per admitted account slot. Keep the existing:

- tier-priority fleet;
- generated leases and fencing;
- per-account budget;
- pre-spend gates;
- waterfall;
- claim/provenance/verification paths;
- coverage ledger;
- circuit breakers/quarantine/canary;
- LangGraph/C5 recovery semantics.

The agent chooses gap subsets, query/source-family strategy hints, and when to propose stopping
within engine limits. Depth-one facet agents are optional and count-capped.

Keep the C1 independent `GoalJudge` as the only evaluator. Remove or prohibit any agent-local
duplicate. Journal its typed advice as non-authoritative and test that malformed advice and
`propose_stop` cannot terminate the run.

Compare governed-agent vs current mechanical-unit outcomes on coverage, promotable evidence,
verification, cost bands, rounds, terminal gaps, and failure recovery. Do not cut over a tier
where agency adds no measured value.

### C6.7 implementation record

- An active immutable `account-research@v1` role now uses the real C6 deepagent runtime with one
  progressively disclosed skill, one exact tool (`research_account_gaps@2`), no direct provider
  access, and no delegation in v1.
- `GovernedAccountProfiler` substitutes only the existing `ProfileAccountFn` inside an admitted
  fleet slot. The mechanical scheduler, account plan, leases/fencing, budget envelope,
  waterfall, claim path, verification, committee/contact continuation, controls, and recovery
  remain the owning shell.
- `account-research-unit@v1` is a standing internal C5 recipe with one-child fan-out and exact
  project/account/registry/coverage pins. Explicit round plus operation identity makes model
  retries converge, while the external boundary remains truthfully at-least-once.
- `c1.engine.goal_judge` is frozen as the sole evaluator owner. Advice is stored append-only and
  non-authoritatively; an agent stop proposal creates neither attempts nor terminal decisions,
  and malformed advice cannot stop research.
- The account finalization guard accepts `completed` only after every initially planned field has
  an engine-authored terminal decision. Partial/failed turns cannot advance later deep stages,
  and C1-booked spend is zero-anchored rather than charged twice by the outer orchestrator.
- C6.8 retains the default-off product-routing decision and must compare this unit against the
  mechanical baseline before enabling a tier/workspace cohort.

## 11. C6.8 — integration and close-out

- build C6 production composition in `clue_api`;
- add default-off enable flag, workspace allowlist, deterministic canary percentage, and explicit
  ownership routing;
- expose registry, turn status, progress, artifact refs, delegation, context receipts, and failure
  projections required by the later shell;
- add telemetry for model usage, tool yield, context size/cache behavior, workspace quota, child
  spend, finalize failures, and cleanup;
- add cleanup/retention operational jobs and runbook;
- retain C4/C5 fallback and prove no dual ownership;
- run adversarial prompt/authority/workspace tests;
- run full DB-enabled suite, formatting, lint, mypy, import contracts, scripts 01–06, migration
  head→base→head smoke, and one-head check;
- update built-vs-planned docs and write the C7 handoff.

### C6.8 implementation record

- The API root composes active profiles, per-role governed models, isolated workspaces, durable
  artifact/turn/history/replay/privacy adapters, the exact L1–L7 context assembler, and one
  durable ownership router.
- The fleet prepares the real account turn and promoted C5 account-unit recipe under stable
  identities, injects it into the existing DEEP slot, and securely reopens/re-hashes its frozen
  workspace on crash recovery. Sticky deepagent-owned routes remain composable after rollout
  switches are reduced.
- Master/surface switches default off. Allowlisted and deterministic percentage subjects are
  claimed once in an immutable route ledger; the selected owner never falls through to the other
  after a failure.
- Authenticated body-free registry, turn, project-turn, progress, telemetry, and route projections
  expose the later shell's backend contract without leaking prompt/skill/artifact bodies or host
  paths.
- Model cache tokens and final workspace quota usage are durable. The combined projection reports
  model/tool/context/workspace/child/finalization signals. Terminal roots are purged after an
  inspection window by a non-fatal fleet job with append-only receipts; live `awaiting_input`
  roots are excluded. DSAR remains immediate and stronger.
- Stage-0/account canary comparison fails closed on invisible failures, duplicate effects,
  evidence regression, or cost/round overruns. The production runbook and C7 prerequisite handoff
  are committed with the implementation.

## 12. Parallelization ruling

Do not parallelize C6.0–C6.4. They freeze or modify shared contracts across the agent package,
resource catalog, workspace backend, gateway seam, C5 journal, and schema.

After C6.4 is green:

- profile/prompt authoring and eval-fixture construction may proceed alongside C6.5/C6.6;
- specialist profiles may be implemented independently only after their common delegation
  contract is frozen;
- C6.7 may prepare eval fixtures in parallel, but production fleet integration waits for the
  Stage-0 runtime and shared agent contracts;
- C6.8 integration, migrations, API wiring, and final verification remain serial.

## 13. Cross-session continuation checklist

At the start of every C6 session:

1. read `_memory/README.md`, the newest C6 note, this plan, and the binding child spec;
2. verify branch and current commit;
3. inspect uncommitted changes and preserve unrelated work;
4. state the active C6 slice and its exit gate;
5. do not pull later-slice work forward unless it closes a demonstrated blocker;
6. record failures and changed decisions in `_memory/`;
7. finish with verification evidence and one coherent local commit.

The next implementation session is **C7.0 contract freeze and prerequisite audit**, starting from
`docs/superpowers/plans/2026-07-26-phase-c7-handoff.md`.
