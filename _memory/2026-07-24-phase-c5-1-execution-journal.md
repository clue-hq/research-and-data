# 2026-07-24 — Phase C5.1 execution journal and toolbelt choke point

## Scope and branch

- Implemented on `platform/c5-recipe-execution` after C5.0 commit `07aad71`.
- C5.1 is complete and deliberately stops before recipe mutation/promotion, compatibility loading,
  the executor/fleet generalization, Recipe-#0 migration, and supervisor runtime behavior.
- The new Alembic head is random revision `128c83d5e151`, chained from C4 head `1b71451d48cd`.

## Durable schema and ownership

- The migration creates all 15 C5 tables in one coherent schema: recipes/revisions/events;
  execution/cursor/nodes/edges/pins/attempts/events/artifact refs; project-run ownership; and the
  dormant supervisor observation/diagnosis/control ledgers.
- History tables have database UPDATE/DELETE rejection triggers. `execution_cursor` is the one
  normal mutable execution table and is rebuildable solely from ordered execution events.
- Composite workspace/context foreign keys prevent cross-workspace execution, project-run, and
  artifact links. `run_event.execution_id` links transport rows to their authoritative execution.
- Every journal append, cursor compare-and-swap advancement, and corresponding `run_event` outbox
  insert shares one transaction. A transport failure or stale cursor rolls the event back.

## Tool invocation and replay

- Added required `ToolInvoker` composition over exact registry resolution, validated canonical
  parameter snapshotting, `DbInvocationJournal`, and the existing A9 idempotency store.
- Ad-hoc HTTP/human calls receive an execution root derived from the stable `operation_id`.
  Execution-owned calls join an explicit node. Completed and blocked operations replay permanently
  from the journal, independent of the A9 TTL.
- The A9 cache key is always derived from `(execution_id, operation_id)`; a caller cannot create a
  second cache identity for the same logical operation. HTTP idempotency keys still derive the
  stable operation id at the route.
- A failed attempt records `node.failed` but does not terminalize the execution, so the same
  operation may retry as the next numbered attempt and later complete. A blocked precondition is a
  durable terminal outcome for that operation; retry after satisfying it requires a new operation.
- Failure events contain only exception-class-derived codes and fixed redacted summaries. Steering
  tools journal actor-attributed before/after display-safe snapshots.
- The HTTP tool route, ingestion submission route, and C4 narrow Recipe-#0 runner now require
  `ToolInvoker`. A static test rejects any bare `invoke_tool` call in API/execution/subsystem
  production code.

## Parameter and read surfaces

- Validated input models serialize as canonical sorted compact JSON, hash with SHA-256, and persist
  at `{workspace_id}/{digest}` through the governed artifact store.
- Graph/event rows contain only the artifact key/hash, schema hashes, safe-display allowlist, and
  reference-only result. Raw parameter bodies never enter graph/event JSON.
- Authorized resolution verifies workspace and content hash. Missing or erased bodies return
  metadata-only tombstones. The API-root storage bridge exposes an explicit execution-ref-checked
  erasure seam and reports success only when physical purge completed.
- Added workspace-scoped execution graph/activity read models and a read-only recipe-revision
  shape. Recipe lifecycle writes intentionally wait for C5.2.

## Verification and operational notes

- Focused real-Postgres C5/API suite: `32 passed`.
- Full DB-backed suite: `2365 passed, 20 skipped`.
- Mypy: `Success: no issues found in 381 source files`.
- Import-linter: `24 kept, 0 broken`.
- Ruff format/lint passed over tracked source roots (`alembic`, `libs`, `platform`, `subsystems`,
  `tests`, `scripts`).
- Raw `make check` reached Ruff and was blocked only by pre-existing T201 findings inside
  user-owned untracked `.claude/` and `.codex/` helpers; those directories were not edited or
  staged. The equivalent tracked-source lint, typecheck, contracts, and full test gates all passed.
- Clean isolated migration smoke passed: head upgrade → downgrade base → head upgrade. The
  temporary smoke databases were removed afterward. `alembic heads` reports only `128c83d5e151`.
- Initial smoke attempt targeted a temporary database created inside Docker, but localhost:5432 is
  served by Homebrew Postgres on IPv6; the attempt failed before migration with
  `InvalidCatalogNameError`. A separate temporary Homebrew database was then used successfully.

## C5.2 handoff

- Implement immutable recipe proposal/promotion/retirement/supersession behavior over the existing
  dormant tables.
- Add the closed graph/binding validator and exact compatibility/pin resolver registry with
  API-root adapters.
- Seed Recipe #0/#1 identities through an idempotent API-root boot function, never a migration.
- Do not begin executor or fleet changes until the C5.2 promotion/compatibility gate is green.
