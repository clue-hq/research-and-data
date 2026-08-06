# 2026-08-03 — M6A E1 targeted Exa enrichment

## Outcome

- Implementation commit: `e8270b4`.
- Implemented post-seal, import-only Exa enrichment for explicitly selected accounts.
- Added provider-neutral core contracts and a separate durable PostgreSQL ledger; E1 does not
  mutate the D5 seal or discovery costs.
- Added exact human-checkpoint, run, batch, seal, ICP, survivor, domain, account, field, and budget
  preflight gates.
- Added Exa CSV-import create/upload and import-only Webset adapter support. Presigned upload URLs
  are secret and only a redacted receipt is durable.
- Added polling, pagination, sourceEntityId binding, domain validation, terminal missing/import
  unresolved outcomes, typed claims, provenance/artifact binding, settlement, and zero-call replay.

## Decisions

- Imported items bind to canonical accounts by the original `sourceEntityId`, never name/order.
- The resolved company URL must remain on the selected input domain; drift becomes unknown spend
  and writes no claims.
- Same response bytes may appear at distinct lifecycle events. Artifact-event uniqueness is
  `(operation, kind, sha256, provider request id)`, while exact event replay reuses the row.
- PostgreSQL prevents request-lineage mutation, charge-over-reservation, success with pending or
  missing field rows, and mutation/deletion of a terminal field outcome.
- Concurrent starters join the one durable dispatch claim; ambiguous crash recovery is
  quarantined instead of issuing a second possibly-paid create.
- Pricing is zero discovery-search credits plus 2/resolved import, 2/ordinary enrichment row, and
  5/actual email or phone value.

## Verification

- Dedicated final DB: `clue_c8_e1_hardened_20260803`.
- E1 adapter + DB tests: 6 passed.
- D2-D6/E1/tier checkpoint: 71 passed.
- Exa D0-D4 adapter fixtures: 22 passed.
- Alembic head/base/head passed; single head `f2c0b2ed21dd`.
- Full mypy: 480 files; import-linter: 24/24 contracts.
- Repository fail-fast still reproduces the pre-existing C8 Stage-0
  `evaluate_stage0_readiness@1` schema-digest fixture failure. Not changed here.

## Open gate

Live E1 remains open. The D6 run has zero selected accounts (`hold=2`), so no paid call was made and
no hold was promoted for testing. Close with a genuinely human-approved selected account and an
explicitly capped live canary (minimum ordinary-field maximum: 4 credits), followed by a fresh
process zero-call replay.
