# 2026-08-05 — M8C V0 offline/database acceptance

## Completed

- Froze a 55-gate executable C0–C7 matrix plus all eleven roadmap categories, prerequisite seed,
  support checks, migration/static commands, and M8B regressions.
- Created an isolated fixture database and seeded the real synthetic Stage-0/ICP/discovery/tier/
  directive/launch/account-run/Sumble snapshot shape before running contact tests.
- Proved fresh-process replay retained the ready operation, snapshots, receipt, launch digest,
  nine claims, and 21 verified artifacts with zero fake-provider calls on replay.

## Populated-database findings fixed

- Recorded Sumble fake transports reused globally unique provider operation ids. Each fake
  operation now receives unique provider-like ids; the database uniqueness constraint is unchanged.
- S2D/O2 tests counted every tenant's committee rows. Assertions now scope to the exact workspace
  and account, so a valid pre-existing fixture cannot create false failures.

## Verification

- Populated prerequisite database focused matrix: 324 passed.
- Final untouched clean database full suite: 3,412 passed, 25 skipped, one existing deprecation
  warning.
- Migration tests: 3 passed; one Alembic head `4d9b02f218dc`.
- Mypy: 539 source files; import-linter: 24/24 contracts; Ruff lint green.
- V0-owned format is green. Two unrelated pre-existing tracked formatting drifts remain in
  `profiling/committee/sources.py` and `tests/api/test_c7_handoff_cutover.py`.
- All test-owned V0 databases were dropped after evidence capture; shared development state was
  not modified.
- No live Exa, Sumble, channel-provider, validator, or model traffic; V1 remains separate.
