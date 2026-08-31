# Stage-0 confirmed discovery contract freeze

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`
Status: checkpoint 1 complete; runtime/persistence work intentionally not started

## Founder-ratified contract

- `product_context_version` is an immutable replay/audit receipt over the substantive Stage-0
  inputs that already exist, not a second knowledge-generation or research step.
- The exact input classes are company Client-KB, selected product, product profile, Product-KB,
  and approved ICP. Each is pinned by native reference/revision and canonical digest.
- The backend derives and idempotently inserts/reuses the receipt. Models and frontend clients do
  not author its opaque id or any other run-lineage id.
- `start_confirmed_project_run@2` has an empty model-authored input. The historical `@1` schema is
  preserved for immutable replay and must later leave the active resources rather than be edited.
- With `CLUE_BUDGET_CONTROLS_ENABLED=false`, the internal discovery boundary is record-only,
  allows execution, and cannot open a human gate or block the run.
- Provider-neutral discovery count/intent/criteria remain separate from receipt and budget
  authority. Deterministic values need no extra interruption; genuine ambiguity may use the
  existing directive-confirmation substrate.

## Files

- Added `docs/specs/FI-stage0-confirmed-discovery-run-contract.md` as the active source of truth.
- Cross-linked the amendment from the historical C0/C4 contracts, pilot budget-controls contract,
  and frontend project API contract without rewriting historical `@1` behavior.
- Extended `clue_api.stage0_project_contracts` with unregistered frozen receipt, internal boundary,
  discovery-configuration, and `start_confirmed_project_run@2` models.
- Added `tests/api/test_stage0_confirmed_discovery_contract.py` prevention gates.

## Verification

- Focused contract matrix: 23 passed.
- New checkpoint tests: 8 passed.
- Ruff format/check passed for both changed Python files.
- Mypy passed for both changed Python files.
- `git diff --check` is part of final closeout.

## Remaining boundary

No migration, receipt derivation service, readiness behavior, tool registration, resource bump,
Exa compiler, or browser behavior changed in this checkpoint. The next checkpoint should implement
trusted server-side receipt derivation/idempotency against immutable turn scope and the current
database lineage.
