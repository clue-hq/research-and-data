# 2026-07-26 — C6.0 contract freeze and dependency spikes

## Outcome

C6.0 is complete on `platform/c6-deepagent-runtime`. It froze the agent/runtime contracts and
proved the four external dependency assumptions. It added no Alembic migration, API route,
production workspace/executor, agent catalog, or feature routing. C6.1 is next.

## Implemented

- Added strict frozen agent value contracts:
  `AgentProfile`, `SkillBundle`, `AgentConstitution`, `AgentTurnRequest`, `AgentPlan`,
  `ValidatedPlan`, `DelegationRequest`, `DelegationResult`, `ContextBundleManifest`, and
  `AgentFinalizeEnvelope`.
- Added exact resource/tool/artifact/domain refs, model/workspace policies, seven ordered context
  layers, stable operation ids, plan graph/budget invariants, relative-path validation, and a
  body-free honest finalization envelope.
- Added injected `AgentModelProvider`, `AgentWorkspaceBackend`, `AgentHistoryStore`,
  `AgentContextAssembler`, and `AgentExecutionAdapter` protocols. The workspace protocol has no
  host-path, shell, process, environment, or execute surface.
- Added `ClueDeepAgentState` for trusted constitution/context propagation.
- Pinned `deepagents==0.6.12` and `langchain-openai==1.4.1`; lock resolution selected
  `langchain-core==1.5.1`.
- Added `OpenRouterAgentModelProvider` inside `clue_gateway`, using the existing base URL, secret,
  timeout, and retry policy. `clue_agents` remains provider/gateway independent.
- Tightened the agents import contract to forbid direct execution/storage/locks/spine access and
  included `clue_agents` in provider-SDK checks.
- Updated the binding child spec and implementation plan with schema digests, dependency findings,
  spike results, the 32-tool replay/authority matrix, filesystem threat matrix, and C6.0 close-out.

## Executable spike evidence

- Real `create_deep_agent` parent/child construction passed with explicit tools and deterministic
  fake models. A child received only its task message while trusted constitution/context state
  propagated.
- Real `ChatOpenAI` sync and async tool calling passed against an offline `httpx.MockTransport`
  through `clue_gateway`; standard tool args and usage metadata parsed correctly.
- Real `AsyncPostgresSaver` failure/resume passed against local Postgres: a completed node was not
  replayed, the failed node retried after a fresh graph compilation, and framework tables were
  removed afterward.
- A real deepagent wrote/read a relative model-visible path through a disposable
  content-addressed backend; a new backend resumed the artifact and another execution could not
  see it.
- Normal framework termination produced no finalization key, proving that a later adapter must
  commit a valid `AgentFinalizeEnvelope` before success.

## Binding findings

- The stock deepagents `FilesystemBackend` is not a production API sandbox. C6.1 must implement
  the hardened artifact-backed backend.
- Deepagents normalizes relative file-tool input to a virtual leading-slash path before backend
  invocation. C6.1 must validate relative syntax at the agent-facing tool boundary before that
  normalization, then adapt the single virtual slash internally.
- The deepagents backend must not implement its execution/sandbox protocol, or code-execution
  tooling can appear. C6 exposes file operations only.
- Subagents share the backend, so C6 must apply a narrower child permission view over the shared
  artifact namespace.
- Steering tools remain human-only. Seven replay-uncertified tools are absent from agent profiles:
  `propose_field`, `decide_field_proposal`, `propose_source`, `decide_source_proposal`,
  `research_account_gaps`, `submit_ingestion`, and `retry_ingestion`.
- Field/source proposal tools remain intended agent capabilities after truthful replay
  certification. `research_account_gaps` must be certified or replaced by a governed C5 operation
  before C6.7; do not introduce a second coverage evaluator.

## Verification

- Focused C6/gateway suite with real Postgres: 28 passed.
- Source-tree Ruff format/lint: green across 811 files.
- Mypy: 397 source files, green.
- Import-linter: 24 contracts kept, 0 broken.
- Repository pytest without DB opt-in: 1,414 passed, 1,070 skipped.
- `git diff --check`: green.

`make check` itself is obstructed before source testing by pre-existing untracked `.claude/` and
`.codex/` skill copies: Ruff reports 16 `T201` findings in their CLI scripts. Those unrelated files
were preserved. The same gate was run explicitly over `libs`, `platform`, `subsystems`, `tests`,
`scripts`, and `alembic` and passed.

## Next session

Proceed with C6.1 only: production isolated workspace factory/backend and immutable folder-resource
materialization. Close the full traversal/symlink/no-follow/quota/atomic-write/root-validation
battery before C6.2. Do not add a database migration or production agent executor in C6.1 unless a
demonstrated artifact-metadata need requires an additive record.
