# C5.5 repository verification checkpoint

## Scope

- Branch: `platform/c5-recipe-execution`.
- Verification used disposable Postgres container `clue-c55-dar-es-salaam-db` on port 55435.
- The database schema was reset before both the final full-suite run and migration smoke.

## Result

- Repository Ruff format/lint passed across 793 project files, explicitly excluding the untracked
  user-local `.claude/` and `.codex/` directories.
- MyPy passed across 392 source files.
- Import-linter kept all 24 dependency contracts.
- Clean DB-enabled full pytest passed: `2432 passed, 20 skipped`.
- Clean migration smoke passed: upgrade to head, downgrade to base, upgrade to head.
- Alembic reports exactly one head/current revision: `ed7a01cd8845`.
- `git diff --check` passed.

## Failure triage and correction

- The first canonical `make check` stopped before tests because Ruff included 16 `print` findings
  in untracked `.claude/`/`.codex/` skill scripts plus one real unsorted import in the new C5.5
  migration. The migration import was fixed; the user-local files were preserved and excluded.
- The first clean DB-enabled full suite had one failure and otherwise passed 2,431 tests:
  `test_aggregate_snapshot_is_frozen_and_strict` had not supplied the C5.5-required
  `project_run_id`.
- The production model was intentionally left strict. The binding C5 contract requires aggregate
  snapshots to be run-specific and C1 aggregation to be keyed by project run. The test now supplies
  and asserts that coordinate. Its focused test, Ruff, and MyPy checks passed before the clean full
  rerun.

## Operational note

- The temporary database container was stopped after verification.
- C5.5 implementation changes remain uncommitted at this checkpoint; `.claude/` and `.codex/`
  remain untracked and must not be added to the C5.5 commit.
