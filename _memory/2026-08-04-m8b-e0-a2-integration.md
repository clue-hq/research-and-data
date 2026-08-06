# 2026-08-04 — M8B E0 + A2 account-profiling integration

## Merge

- Destination worktree: `/Users/aryankeshri/conductor/workspaces/research-and-data/roseau`.
- Destination branch: `platform/c8-account-profiling-integration` at A2 hardening commit
  `940fbc0` before merge.
- Source branch: `codex/m8b-e0-exa-deep-wire` at E0-R2 commit `98538d4`.
- Local no-fast-forward merge commit: `be73cb0`. Nothing was pushed.
- The shared M8B roadmap merged without textual conflicts; unrelated tracked/untracked worktree
  changes were left untouched.

## Integration audit

- Reconciled stale roadmap summary/table language with the already-closed A2 section and newly
  closed E0 section. A2 durable directive state is complete; the remaining Sumble work is the
  production `SumbleCommitteeInputResolver` adapter/binding in serial O2 composition, not a reopened
  A2 slice. Exa E1/E2 and the full launch surface remain open.
- The destination had a configured Exa credential, which exposed that E0's negative credential test
  used environment-loading `Secrets()`. The test now explicitly disables dotenv and overrides
  `exa_api_key=None`; it deterministically proves the pre-dispatch failure without depending on a
  developer environment. No provider transport ran.

## Verification

- Combined E0/A0, Parallel, A2 core/context/API, deep composition, and Sumble S2B/S2D/O2 regression
  matrix: passed with expected database-dependent skips.
- `mypy`: 506 source files, no issues.
- `lint-imports`: 24 contracts kept, 0 broken.
- Scoped Ruff check and format check: passed.
- Merge and follow-up diffs pass `git diff --check`.

## Remaining boundary

Proceed from the integrated branch with E1 durable Exa acquisition, then E2 snapshot-backed
materialization and serial O2/O3/full-launch composition. Paid/live canaries remain separately
authorized work.
