# 2026-08-04 — E1/E2 adversarial remediation

## Scope

Closed the seven P1/P2 findings from the E1/E2 review without advancing later M8B slices.

## Changes

- Added a semantic `reuse_fingerprint`, transaction-scoped advisory serialization, and immutable
  `external_research_snapshot_use` rows. Fresh equivalent requests across project runs/windows now
  share one provider operation while each consuming run receives a durable snapshot adoption.
- Kept unresolved `spend_outcome_unknown` reservations in the provider budget calculation until an
  append-only `external_research_cost_reconciliation` settles the charge. Raw malformed/over-cost
  responses and provider request ids are retained on the terminal attempt when available.
- Added immediate best-effort quarantine for post-dispatch persistence failures and corrected known
  dispatched HTTP rejection call accounting.
- Added `read_verified_artifact`; E2 now proves request, response, normalization, and every result
  blob against live workspace-local artifact metadata and the content-addressed hash before claims.
- Added a claim trigger that proves Exa operation/snapshot/request/result-artifact/account/source
  lineage relationally at insert time.
- Made provider preparation explicit (`ready`, `not_applicable`, `waiting_external`,
  `required_missing`) and made the raw snapshot-resolver builder private. Non-applicable Exa yields
  a zero-cost empty override; required/mid-acquisition states fail through a typed composition error.
- Budget-skipped paid sources no longer terminate the waterfall before a later zero-cost snapshot.
  The coverage precheck preserves ordinary budget enforcement and constrains the fallback walk to
  zero spend when only already-owned evidence remains authorized.

## Verification

- `alembic heads`: one head (`fa28c91abc3c`).
- New disposable Roseau database: full migrate succeeded; `make db-smoke` up → base → up succeeded.
- Focused E1/E2/HTTP/waterfall suite: 45 passed.
- Full A2/E0/E1/E2 regression selection: 91 passed against the isolated migrated Postgres DB.
- Migration + storage selection: 44 passed, 8 skipped by their optional-backend gates.
- `make typecheck contracts`: mypy clean; all 24 import contracts kept.
- Repository-wide `make lint` remains blocked by 15 pre-existing formatting drifts outside this
  slice; every file changed in this remediation passes targeted Ruff and `git diff --check` (with
  the user's unrelated architecture edit excluded).

## Workspace hygiene

- The pre-existing content/artifact architecture edit and unrelated untracked files were not
  modified or staged.
