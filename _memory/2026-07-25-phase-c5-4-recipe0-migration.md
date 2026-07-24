# C5.4 — executable durable Recipe #0

## Final state

- Branch: `platform/c5-recipe-execution`.
- Added immutable system Recipe #0 v2; v1 is superseded, never mutated.
- V2 has a human-closeable `input_available` interaction gate, exact nine-tool allowlist, 125
  dynamic children, and 128 total nodes.
- `ToolbeltRecipeRunner.run_step` now materializes an artifact-backed execution child and invokes
  it through `RecipeExecutor`/`ToolInvoker`. The in-memory multi-step runner is removed.
- Dynamic children freeze stable operation id, actor, dependencies, exact tool/schema pins,
  workspace-local resource pins, and parameter artifact hash/ref. Graph/event JSON never stores
  interview/tool bodies.
- Child replay rejects actor/input/pin drift; exact replay remains valid after Recipe #0 is
  terminal. A worker can recover a child appended before invocation.
- Stage-0 pin adapters now cover brand/product/project, aggregate active field/source registries,
  exact Client-KB/ICP versions, product context, readiness decision, artifact input, source profile,
  prompt, memory switch, and optional memory-bundle journal refs.
- Optional disabled memory remains disabled and is pinned/rechecked as `disabled`; no old
  observation can re-enable it.
- Erased dynamic parameter artifacts render tombstones and worker recovery fails closed.
- `start_confirmed_project_run`'s node completion is the stable Recipe-#1 handoff record. It carries
  `project_run_id` plus Stage-0 lineage. Recipe #1 v1 remains a non-executable placeholder and no
  execution owner is claimed until C5.6 appends/starts the executable revision.
- Fleet boot now idempotently seeds/promotes system recipe assets before accepting graph work.

## Verification

- Ruff format/check (project paths; untracked `.claude/` and `.codex/` excluded from the latter).
- Mypy: 388 source files green.
- Import-linter: 24 contracts kept.
- Full non-DB suite green with DB deliberately unreachable.
- Focused DB suite: 68 execution/API/C4/C5.4 tests green.
- C5.4 parity fixture: direct C4 and durable Recipe #0 normalized outcomes match for URL-only
  onboarding, fast/background recon, product confirmation, interview, correction, readiness,
  human override, and confirmed-run entry.
- Fault injection green after domain commit for fast recon, background recon, interview routing,
  and confirmed-run creation.
- Clean disposable DB `make db-smoke` green; migration DB tests and the previously reported B4
  composed-run test green in isolation; one Alembic head: `d9b39fb407ed`.

## Verification caveat

Running the entire suite DB-enabled in one pytest process is order-contaminated by the existing
`tests/execution/test_graph_exit.py` subprocess harness, which intentionally commits
`ws-graph-exit-*` execution rows before the later migration downgrade tests. C5.3's downgrade then
correctly refuses live pre-materialized tool nodes. Verification used the repository-required clean
DB smoke plus isolated DB groups; no C5.4 migration was added.

## Next

- C5.5: run-specific aggregate reader, deterministic supervisor monitors, bounded diagnosis, and
  enforced run-local controls/canary health gate.
- C5.6 later appends executable Recipe #1, consumes Recipe #0's confirmed-run handoff, and
  atomically claims the single `project_run_execution_owner` for eligible new runs.
