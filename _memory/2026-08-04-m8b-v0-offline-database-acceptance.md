# M8B V0 — offline and database acceptance

Date: 2026-08-04
Branch: `platform/c8-account-profiling-integration`
Status: complete mechanically; no live provider call; V1 remains separately authorized

## Implemented

- Added `tests/fixtures/account_deep/v0_fault_matrix.json` plus a structural manifest test. The
  manifest freezes all 32 required V0 cases and points each to an existing executable test.
- Added a disposable-database child-process harness and acceptance test. It runs
  `head -> base -> head`, seeds one exact launch and eligible account, drives recorded Sumble
  Teams/People through pending/running/succeeded, materializes three committee claims, folds
  operation/snapshot/receipt/claim refs, verifies every live artifact, races two launch processes,
  and replays in a new process with a transport that raises on any call.
- Expanded S2D to reject personal-data, jurisdiction, use-class, and identity-acquisition failures
  independently before any paid operation; the existing budget and fresh-snapshot cases remain.
- Expanded Exa E1 transport coverage to hard 401/403/404 and spend-unknown 429/500/503 in addition
  to timeout/400/402/malformed-success cases.
- Added Sumble crash cases before dispatch, after response before snapshot fold, terminal People
  failure replay, charged schema drift, and post-DSAR no-resurrection replay.

## Production defect and correction

V0 found that `SumbleCommitteeAcquisitionCoordinator` normalized provider rows before persisting
the response. A charged response with a valid envelope but drifted row could lose its raw response,
provider id, credits, and observed cost before quarantine.

The coordinator now records and subject-binds the immutable raw response and terminally updates the
attempt before normalization. Snapshot folding is a second step. A fresh process can hash-verify,
revalidate, normalize, and fold a committed response without provider traffic. Failed recovery or
charged row drift preserves response evidence and known charge in terminal
`spend_outcome_unknown`; possible dispatch without a recorded response remains no-retry unknown.

## Full-gate compatibility corrections

The first full-suite run used the long-lived development DB and produced registry/migration
contamination failures. A clean disposable DB reduced the real residual set to ten earlier-slice
compatibility failures. They were corrected without weakening governed behavior:

- the C6 delegation regression uses current immutable profile/tool pins;
- the missing-Sumble-secret test explicitly supplies `sumble_api_key=None` and ignores `.env`;
- Recipe #1 re-enters its tier handler with the approval and asserts two handler invocations;
- the composed fleet test submits checkpoint input through the exact per-run composition;
- the fleet-only kill harness records its fixed synthetic tier preauthorization explicitly;
- the S1-only trial enables the C7 reader but expects `subject_not_found` because it intentionally
  has no account profiler/committee source and must not fabricate a dossier;
- the memory structural guard allows only `clue_api.memory_wiring` as the public composition root;
- `capture_events` revives and restores logger disabled flags so Alembic `fileConfig` cannot make
  later logging tests order-dependent.

Ruff formatting drift in 15 already-clean tracked files was restored in separate commit `c4c6bf8`.
User-owned untracked `.claude/`, `.codex/`, `.artifacts/`, and `.superpowers/` trees were not edited.

## Verification

- New V0 core set: `31 passed`.
- Complete frozen V0 matrix: `110 passed`.
- Residual full-gate set after correction: `10 passed` together.
- Complete suite on untouched disposable DB `roseau_v0_f09c1e6a4b72`:
  `3337 passed, 11 skipped, 1 existing Starlette/httpx deprecation warning`.
- Disposable databases `roseau_v0_82a4c7d109f3` and `roseau_v0_f09c1e6a4b72` were dropped after
  their owned runs; no shared database was reset or dropped.
- Canonical mypy: 515 source files, zero issues.
- Ruff: all repository files excluding user-owned untracked skill/artifact roots pass; 1,073 files
  formatted.
- Import-linter: 24 contracts kept, zero broken.
- Alembic: one head, `a83e52bebc7c`.
- No live Exa or Sumble call was made in V0.

## Remaining boundary

Only V1 remains for this roadmap: separately authorized, hard-capped successful Exa Deep, Sumble
Teams/People, combined account-deep, and fresh-process zero-spend live canaries. Contact reveal is
still out of scope.
