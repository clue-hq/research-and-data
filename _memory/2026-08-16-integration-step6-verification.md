# Integration Step 6 — complete verification

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`

## Outcome

The post-merge verification ladder is complete. Every focused merged path is green, the schema has
one Alembic head, a fresh full migration smoke passes, the complete frontend gate passes, and the
monolithic backend run matches the unchanged reviewed 32-node quarantine exactly.

## Verification fixes found by the ladder

- Canonically formatted four files that the first repository-wide Ruff check identified.
- Made the directive-gate presentation fail closed if budget controls are enabled but its computed
  spend cap is unexpectedly null; this also restores full mypy narrowing under the unified
  nullable gate substrate.
- Updated the derived Head-of-ABM v29 aggregate-manifest assertion after the reviewed v16 wording
  change. The immutable v16 skill hash and v29 pin were already correct.
- Changed a runtime test to open the Stage-0 skill disclosed by the active profile instead of
  hard-coding historical v12.
- Excluded nested `.venv` dependency trees from two root static source scans. The merged
  `subsystems/clue-design/` toolchain remains outside root source checks as required by the current
  integration boundary.

The frozen quarantine manifest was not edited or regenerated.

## Evidence

- Ruff format/check: 1,476 files clean.
- Mypy: 690 source files clean.
- Import-linter: 25 contracts kept, zero broken.
- Resource hashes, catalog loading, tool authority, and recipe compatibility: green.
- Unified gate model/route/projection/direct-SQL matrix: 83 passed.
- Focused frontend gate/model/handoff matrix: 57 passed.
- FI-2 Accounts/Contacts and selected-record chat handoff: 143 backend and 63 frontend passed.
- Stage-0 readiness, synthesis, ICP revise/approve, and confirmed execution: 81 passed.
- Client-KB/product-context S3-S6 matrix and quarantine guard tests: 96 passed.
- Official-site crawl, expansion, recovery, lock-order, deadlock, materialization, and setup: 222
  passed.
- Frontend: 301 passed; ESLint, design-token build, TypeScript/Next production build, and all 20
  routes passed.
- Alembic: sole head `f85ca69b93ba`; fresh database
  `clue_singapore_step6_20260816_c1` passed head -> base -> head.
- Complete backend run used fresh migrated database `clue_singapore_step6_20260816_c2` and the
  executable guard reported `exact reviewed quarantine observed: 32 failures`: zero additions and
  zero missing/repaired-but-stale entries. No S3-S6 context-composition test failed.

## Retention

The two Step-6 databases are test-only and are retained for merge review. No shared database was
reset, downgraded, or otherwise modified.
