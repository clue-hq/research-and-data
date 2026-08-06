# 2026-08-04 — M8B E0-R2 truthful response semantics

## Scope

Closed the E0 critical-review follow-up for truthful Exa Search Deep response handling. No live
provider call, durable acquisition, migration, claim materialization, or Sumble code was included.

## Changes

- Added recursive validation of every returned structured value against the exact admitted request
  schema, including nullable types, enums, numeric/string bounds, arrays, and closed nested objects.
- Accepted a reported-cost all-null response with no results/grounding as a settleable paid hard
  miss; non-null fields still require unique grounding and retained inspectable cited results.
- Added lossless per-citation attribution and conservative field/value-support passage selection.
  Unsupported or below-threshold citations remain attributable but do not become candidates.
- Removed the resolver package's live HTTP implementation/default. Production composition now
  binds a typed hard pre-dispatch placeholder until E1 supplies durable acquisition and a ready
  snapshot backend. The E0 response harness requires an explicitly injected transport double.
- Updated the A0/E0 acceptance records, M8B roadmap, and the superseded M11 sketch so they describe
  the same boundary.

## Verification

- Focused A0/E0/Exa: 28 passed, 6 database-dependent skips.
- Broader Exa/Parallel/A1/planner/source-profile regression set: passed with expected
  database-dependent skips.
- `mypy`: 501 source files, no issues.
- `lint-imports`: 24 contracts kept, 0 broken.
- Scoped Ruff check and format check: passed.
- Full `pytest -q`: only the two pre-existing unrelated branch failures remained:
  - DSAR test cannot connect to local Postgres from the sandbox (`PermissionError` on `::1:5432`).
  - memory-boundary test flags the existing `platform/api/clue_api/trial/stage0_runtime.py` import.

## Remaining boundary

E1 owns durable submit/persist/settle/replay and ready-snapshot composition. E2 owns governed claim
materialization and verification. A paid/live canary remains separately authorized work after both.
