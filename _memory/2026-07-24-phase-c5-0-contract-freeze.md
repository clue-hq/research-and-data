# 2026-07-24 — Phase C5.0 contract and replay freeze

## Scope and branch

- Implemented on `platform/c5-recipe-execution` from planning commit `5687584`.
- This checkpoint is deliberately contract-only. It adds no Alembic revision, execution
  repository, journal writer, recipe loader, scheduler, executor, or production runtime route.
- Binding implementation evidence:
  `docs/specs/PC-C5-0-replay-safety-audit.md`.

## Implemented contracts

- Added shared execution identities in `clue_core.execution_graph`:
  `ExecutionId`, `ExecutionNodeId`, `ExecutionAttemptId`, `RecipeId`, `RecipeRevisionId`, and
  `OperationId`, including stable workspace/key derivation.
- Added the contract-only `platform/execution/clue_execution` package with closed recipe scope,
  node, edge, status, event, and control vocabularies plus pin/incompatibility/aggregate value
  objects. Import-linter enforces that execution cannot reach subsystem/API implementations.
- Expanded the toolbelt with immutable `ToolDescriptor`, strict `ToolOutput`, input/output schema
  SHA-256 digests, `ReplaySafety`, `ToolEffectClass`, `JournalParameterPolicy`, declared pin kinds,
  and steering snapshot capability.
- Reworked `ToolRegistry` to store exact `(name, version)` implementations with one explicit
  composition-selected default. Duplicate exact versions and multiple defaults fail loud; no
  lexical version selection exists.
- The runner accepts an exact version, records `name@version` in the existing A9 cache, refuses
  cross-version replay, validates tool identity and typed output before cache completion, and
  stamps `operation_id` on invocation spans.
- C4's narrow `RecipeStep` now requires `tool_version`; standing recipes do not float to a default.
- Added strict output models for all 31 tools currently registered by `build_toolbelt`; the
  Recipe-#0/#1 audit covers 24 unique exact addresses.

## Replay decisions and implementation changes

- Added required `ToolContext.operation_id`; ad-hoc roots mint one, HTTP idempotency keys derive a
  stable workspace-scoped one, and the narrow Recipe-#0 runner derives one from recipe + step.
- Project-run starts, confirmed-run starts, onboarding inputs, readiness decisions, import batches,
  reverse-profile runs, deep runs, committee runs, contact runs, and interview runs derive their
  durable identities from `operation_id`.
- Recon fast/background run ids derive from the recon id. `start_recon` and readiness evaluation
  accept supplied ids and validate immutable context on exact replay.
- `start_recon` is intentionally certified overall `at_least_once`, not
  `operation_idempotent`: its cross-operation TTL dedupe can share a pre-existing equivalent recon,
  whose primary key is not the newer operation id. C5.1's durable completion journal must close
  that replay window.
- Provider-facing tools keep an explicit at-least-once external residual. No database identity is
  described as provider-boundary exactly-once.
- Pause/resume/tier checkpoint/budget adjustment/product confirmation/readiness override expose
  display-safe snapshot hooks. Resume accepts already-active desired state; budget adjustment
  avoids rewriting an unchanged cap.
- The audit is executable in `clue_api.recipe_contracts`; it fails on an untyped output,
  uncertified replay policy, empty pins, or missing steering snapshot.

## Verification

- DB-backed full suite:
  `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5432/clue uv run pytest`
  → `2354 passed, 20 skipped`.
- Ruff passed over the repository with unrelated untracked `.claude/` and `.codex/` local helper
  directories excluded. Raw `ruff check .` would inspect those user-owned helpers and fail their
  pre-existing `T201` prints; they were not edited or staged.
- Mypy: `Success: no issues found in 375 source files`.
- Import-linter: `24 kept, 0 broken`.
- `git diff --check` passed.
- `uv run alembic heads` remains the single head `1b71451d48cd`.
- No file under `alembic/` changed.

## Next slice

C5.1 is now unblocked: add the migration-backed append-only execution journal, governed parameter
artifacts, and required production toolbelt writer. Do not begin the recipe loader or executor
until the C5.1 journal/choke-point gate is complete.
