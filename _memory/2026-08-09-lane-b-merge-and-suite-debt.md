# 2026-08-09 — Lane B merged into the hub; pre-existing full-suite gate debt diagnosed

## Lane B merge: LANDED and gated
- `git merge platform/platformlane-b-auth` → `c087e654`, zero conflicts. Follow-ups: `c8149148` (ruff-format 10 files with pre-existing drift — pre-merge blobs already failed `ruff format --check`), `bbd835c6` (two test-isolation fixes, below).
- Alembic: **single head already** — Lane B's `9398ae4467e3` (B1 identity substrate) → `abbacac4df1f` (durable tool authority) chained directly off FI-2's `870fe4f2af87`. No `alembic merge` needed. `make db-smoke` (up→down→up) green on a throwaway DB.
- **Blame verdict (decisive baseline):** full suite at pre-merge `cd4f6453` fails **30**; post-merge fails **28**; failure sets identical minus the 2 I fixed. **Lane B introduced zero test failures.**

## Pre-existing full-suite gate debt — UNOWNED BACKLOG ITEM (28 deterministic failures)
`make check`'s test stage fails on any full run against one shared DB, and has for some time (agents ran green per-suite subsets; nobody ran the full alphabetical suite recently). Root cause chain, verified from tracebacks:
1. Commit-style e2e tests early in the suite **commit** durable rows and don't clean up (`fleet_task` rows; also `run_lineage` rows with `ws-b4-e2e-*` workspaces — B4 e2e among the writers).
2. `tests/db/test_db_migrations.py::test_up_down_up_is_clean` then downgrades the **shared** DB mid-suite and hits the M8D R2 data guard — "cannot downgrade M8D R2 while entity_research_job fleet tasks exist" — failing and leaving the schema mid-state.
3. Everything after cascades: discovery_scoring, durable, fleet, sources/waterfall (`SourceManifestRedefinitionError: 'apollo' already registered`), coverage_report, agent_registry_wiring, logging_discipline (28 total). All pass individually / per-module on a fresh DB (verified).
**Recommended fix (not started; needs an owner):** give `tests/db/test_db_migrations.py` its own scratch database (fixture-created per run) so the destructive up-down-up never touches the suite-shared DB; and/or make the committing e2e tests clean up after themselves. Small test-infra change; touches FI-2/fleet test territory.

## Fixed en route (`bbd835c6`)
- `tests/test_workspace_rename_guard.py`: guard now skips gitignored `.context/` dirs (untracked Conductor attachments quoting oauth `client_id` broke it locally; passed on clean checkouts — machine-dependent).
- `tests/test_project_lens_backfill.py`: two assertions scoped to their own workspaces (previously read global `run_lineage`/`project_account` → deterministic failure after any committed lineage writer ran earlier).

## Next steps (lane plan)
- Pull the hub into `damascus` (Lane D): `git merge platform/frontend-integration` there → re-run D1/D4 acceptance with the real principal → build D5.
- Pull the hub into `lima-v1` (Lane E): brings Lane B + the A+B toggle-compat change before E1.
- Full-suite gate debt: assign an owner (suggest FI-2 agent or a tiny dedicated task) before treating `make check` red/green as a merge signal again.
