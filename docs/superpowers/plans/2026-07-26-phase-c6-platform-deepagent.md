# Phase C6 — implementation plan

**Date:** 2026-07-26
**Branch:** `platform/c6-deepagent-runtime`
**Base checkpoint:** `f25e9b5` (`feat(execution): adopt Recipe 1 with reproducible run views`)
**Binding child spec:** [PC-C6](../../specs/PC-C6-platform-deepagent-and-skills.md)
**Current checkpoint:** C6.0 implemented and verified; C6.1 is next. No C6 migration or production
runtime exists yet.

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
| C6.1 | Isolated workspace, virtual backend, resource materialization | Only if artifact metadata needs an additive record; prefer no | isolation battery green |
| C6.2 | Folder catalogs, profiles, registry, tool-calling model seam | Profile metadata only if proven necessary | exact resource/allowlist/import gates green |
| C6.3 | Typed turns, seven-layer context, history, receipts | Yes | migration smoke + body-free replay |
| C6.4 | Plan compiler, governed tools, delegation, finalize | Additive only | crash/authority/replay matrix green |
| C6.5 | Head-of-ABM Stage-0 vertical | No new domain tables expected | C4 parity + agent-quality eval |
| C6.6 | Fresh-wake specialist subagents | No new domain tables expected | delegation/authority parity |
| C6.7 | Governed per-account worker agent | Add only if checkpoint ownership requires it | fleet/evaluator/quality parity |
| C6.8 | Composition, canary, hardening, full close-out | Operational settings only | full repository gate |

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

The next implementation session is **C6.0 only**.
