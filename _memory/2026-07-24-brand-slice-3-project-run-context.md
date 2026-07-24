# Brand slice 3 — project-run context pinning (2026-07-24)

## Decision implemented

- Every project run executes for one required `project_id`.
- The caller supplies `project_id` plus its authenticated `workspace_id`; it never supplies
  `brand_id`.
- The run insert selects `brand_id` from the same-workspace project and persists the exact
  `(project_id, workspace_id, brand_id)` tuple.
- `project_run.project_id` and `project_run.brand_id` are `NOT NULL`. The composite
  `project_run_project_context_fk` prevents a foreign-workspace project or another brand from the
  same workspace being attached to a run.
- `ProjectRunRow` and `PhaseContext` carry both pinned ids, so every phase gets sender context from
  durable run state.
- `start_project_run` requires `project_id` and fails closed as `project_not_found` for an absent
  or foreign-workspace project.
- There is no invented `brand_version`: the current brand-kit model has identity/ownership but no
  versioned payload contract. This slice pins brand identity; version pinning waits for that schema.

## Implementation

- Migration: `b366c985ca12_pin_project_brand_on_project_runs.py`, down revision
  `068426c5ea34`.
- The migration derives existing brands only for same-workspace project/run pairs, then fails loud
  with a development-reset instruction if any legacy run lacks valid project context.
- The durable repository rejects missing/foreign projects and rejects reuse of a supplied run id
  with a different project/workspace context.
- Runtime/API callers, phase fixtures, DB seed helpers, projection/fleet tests, and architecture
  docs were updated to the new required contract.

## Verification

- Focused live-DB tests passed for durable runs/budgets/orchestration, object spine, toolbelt,
  composition, review, handoff, observability, and projections.
- Negative tests cover missing project, cross-workspace project, supplied-run-id context drift, and
  a different same-workspace brand.
- Manual migration probe: downgrade one revision, insert a synthetic `project_run` with no project,
  verify upgrade refuses it with the intended fail-loud message, remove the probe, upgrade to head.
- Live catalog inspection confirmed both columns `NOT NULL`, the triple UNIQUE anchor, and the
  composite FK.
- `make check` with live Postgres: 2254 passed, 20 skipped (external-service-gated).
- `make db-smoke`: head → base → head passed; exactly one head at `b366c985ca12`.
- Full live-DB pytest ran green from the post-smoke fresh schema and green again immediately.

## Notable development failure

- The first focused unit run found one direct `ProjectRun(...).start(...)` caller that the initial
  variable-name-based call-site scan missed. It was updated, then an AST scan over every Python
  call confirmed all run-start and `ensure_project_run` callers provide `project_id`.
