# 2026-08-02 — M6A D0 durable discovery contract freeze

Branch: `platform/c8-exa-sumble-discovery`.

Implemented Slice D0 from `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`. This slice
is deliberately provider-offline: it freezes platform contracts and fixtures before D1 persistence
or D2 Exa spend.

## Delivered

- `libs/clue-core/clue_core/discovery.py`: shared ids/enums and immutable Pydantic contracts for
  discovery plan, operation, event, page, item snapshot, field resolution, error, readiness, and
  seal.
- Byte-canonical request identity with NFKC/whitespace normalization, ordered criteria/enrichments,
  workspace/policy/ICP/provider/observation scope, SHA-256 golden vectors, and deterministic
  `externalId`.
- Exact fourteen-condition seal decision with one stable blocker per condition. Every false
  condition independently blocks sealing; only all fourteen true is sealable.
- `discovery-envelope-v1`: hard identity for name/domain; required terminal attempts for LinkedIn,
  industry, employee count/range, headquarters, and revenue/ band; optional public company
  email/phone.
- Eight new core field definitions and real registry validation, including explicit annual-revenue
  estimate semantics and bounded revenue bands.
- Sanitized Exa Websets `v0` fixtures for async running, company items, all evaluation states, null
  enrichment, pagination, duplicate/out-of-order events, cancellation, and additive schema drift.
- `docs/specs/M06A-D0-contract-freeze.md`: exact scope, ownership/import map, contract details, D1
  schema refinements, tenancy, retention, DSAR, fixture matrix, and gate evidence.

## Design decisions

- Shared lifecycle/reference types live in `clue_core`; discovery policy remains M6-owned; D1 SQL
  implementations remain durable-owned. Composition across the independent packages belongs only
  at `clue_api`.
- D0 does not add `WAITING_EXTERNAL` to the running project state machine. D1 owns that state and
  scheduler wake-up delta together with the durable tables.
- A nullable first-page cursor is unsafe under a normal Postgres unique constraint. The shared page
  contract uses non-null `__first_page__`; D1 must use the same key.
- Every D1 discovery table must carry `workspace_id` and composite tenant foreign keys; every raw
  provider artifact is tenant-bound even if a materialized account claim is public-reusable.
- Required attempt is not a completeness guarantee. A sourced value or an honest terminal
  missing/conflict/policy disposition can finish a field; fabrication cannot.
- A terminal operation separates lifecycle state from spend outcome and requires durable receipt/
  artifact references. Unknown spend can exist only in `spend_outcome_unknown`.
- Plan fields are checked against the exact versioned envelope policy before execution.

## Verification

- Pure D0 contract/fixture/policy suite: `35 passed`.
- Real fixture-bearing Postgres registry suite: `16 passed` across field registry, existing
  synthesis routing, and discovery-envelope field validation.
- Full discovery suite on an ephemeral clean, migrated host Postgres: `150 passed in 2.46s`.
  The first attempt against the fixture-bearing database correctly exposed four legacy tests that
  assume an empty account/source catalog; those were rerun against the clean database rather than
  weakening tests or deleting fixture data.
- The temporary database `clue_d0_contract_test_019fc196` was checked for zero active connections,
  dropped, and the host `clue_discovery_fixture` was confirmed to remain.
- Full mypy: `Success: no issues found in 463 source files`.
- Import-linter: `24 kept, 0 broken`.
- Changed Python surface Ruff format/check: pass.
- Full repository pytest without an explicit DB had three unrelated/pre-existing failures: one
  sandbox-blocked localhost DSAR test that bypasses the suite's DB availability gate, one existing
  `clue_memory` private-import guard failure in `platform/api/clue_api/trial/stage0_runtime.py`, and
  one existing secret-shape false positive for `fixture-org-attributes-only-drift`. The D0 scoped
  suites and full discovery suite are green.
- No Exa or Sumble API call was made. Fixture tests monkeypatch network socket creation to fail.

## Next boundary

D1 may now add the reversible migration, workspace-scoped repositories, artifact lineage,
transactional fourteen-condition seal writer, `WAITING_EXTERNAL` runtime/checkpoint state, and
scheduler wake seam. D1 must remain provider-free and prove crash/resume, cross-workspace denial,
cursor/event/page/item idempotency, concurrent identical sealing, and DSAR enumeration with real
Postgres/object storage before D2 begins.
