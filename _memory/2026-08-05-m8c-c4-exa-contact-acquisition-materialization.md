# 2026-08-05 — M8C C4 durable Exa contact acquisition and materialization

## Outcome

C4 is mechanically complete. Exact selected-contact C3 plans now dispatch through the shared
external-research ledger outside claim transactions, persist immutable contact request/response/
normalization/result artifacts, and replay exact-target candidates through the existing governed
`fill_contact_field` path. The paid one-contact Exa canary remains separately authorization-gated;
no live provider call or provider spend occurred in this session.

## Implementation

- Added `ExaDeepContactAcquisitionService`; database compilation closes before coordinator/HTTP
  dispatch, and rejected authority produces zero calls.
- Extended the shared Exa coordinator with contact normalization and a C4 request artifact that
  freezes the intent digest, contact/employer target lock, field source plans, configuration, wire
  request, and durable lineage.
- Added exact-contact ready-snapshot verification/materialization. Replay integrity-checks every
  artifact, reconstructs the C3 preflight, recomputes normalization, and rejects scope, cost,
  provider-request, field, plan, or result-index drift.
- Added a provider-neutral offline `GroundedContactSnapshotResolver` and kept authoritative
  identity/use classification plus insertion in `fill_contact_field`.
- Added an exact effective-source-plan equality check and planning budget propagation to
  `fill_contact_field`; defaults preserve existing callers.
- No migration was needed because C2 already supplies contact subject/index/lineage durability.
- No fleet/composition change was made; C6 owns provider-neutral prepare/wait/resume production
  wiring. No email/phone reveal was added; C5 owns that work.

## Cost decision

Exa documents Search `costDollars` as an endpoint-dependent estimate. The C4 coordinator settles
that provider-reported response estimate exactly once with `pending_provider_billing`; the existing
reconciliation seam remains authoritative for later provider billing evidence. Replay performs no
second settlement.

## Verification

- 5 C4 real-Postgres tests passed on the populated synthetic development database.
- 23 combined C3/C4/E1/E2 tests passed.
- 86 contact/external-research/governance regression tests passed.
- Complete repository pytest reached 100%/exit 0 on a clean disposable database.
- Disposable Alembic head-to-base-to-head smoke passed with the single head `f9281fac77e1`; the
  database was deleted after verification.
- Repository Ruff passed.
- Targeted mypy passed for all six changed production modules.
- Import linter passed all 24 contracts over 596 files/4,913 dependencies.
- Full repository mypy is not a green baseline: 1,263 errors in 189 files. The C4 test-only check
  reaches one existing missing return annotation in `tests/profiling/conftest.py`; production C4 is
  clean.

## Failures exercised or corrected during implementation

- Corrected the C4 test to use the authoritative public-professional use class rather than an
  incorrect personal-public expectation.
- Corrected malformed-response inspection to read the response artifact from the attempt row,
  where response-first durability actually records it.
- Moved the offline resolver to API composition instead of the research profiling package after
  the import-contract gate identified an invalid worker-to-worker dependency.
- A malformed but potentially charged response is retained and ends spend-unknown with no invented
  receipt or ready snapshot.
- A post-dispatch process crash leaves one active operation; a fresh coordinator joins it without
  duplicate submit or charge.

## Next boundary

C5 owns separately gated selected-contact email/phone enrichment and validation. C6 owns production
composition, `WAITING_EXTERNAL`, wake/resume, and the live fleet path. A paid C4 live canary requires
separate authorization and must prove real provider traffic, durable provider artifacts/receipt,
governed claim output, and zero-traffic replay.
