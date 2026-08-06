# 2026-08-03 — M6A D4 Exa identity and field materialization

Status: D4 complete on `platform/c8-exa-sumble-discovery` in commit `e39aefe`. D5 has not started.

## Delivered

- Added the D4 contract, implementation, migration, replay CLI, and acceptance coverage.
- Materialization consumes only D3 durable artifacts; it performs no provider calls.
- Provider items are normalized into identity-admission inputs, canonical accounts, typed claims, provenance/artifact links, and terminal field-resolution rows.
- Domain deduplication, review continuation/exclusion, transitive survivor reads, and replay-safe claim reuse are enforced.
- The D3 success path schedules a stable D4 wake without advancing the batch beyond discovery. D5 still owns final sealing and phase advancement.
- Base company fields and supported enrichments preserve paid data. `foundedYear` and web-traffic metrics remain intentionally out of scope.

## Live artifact findings

- The already-paid Exa artifacts showed that an enrichment definition can declare `text` while a completed result specializes its format to `email` or `phone`. The normalizer permits only those two documented specializations and requires exact format agreement otherwise.
- The two-row live batch replay reused 12 claims, retained 14 stable claim references, and produced 14 terminal field resolutions: 10 resolved, 2 confirmed missing, and 2 failed terminal.
- The enriched live batch replay reused 8 claims, retained 9 stable claim references, and produced 9 terminal field resolutions: 7 resolved and 2 confirmed missing.
- Both live replays made zero provider calls in the process and remained pending final D5 sealing.

## Verification

- Combined D1-D4 and adjacent source/field suite: 157 passed, 1 expected opt-in skip.
- The skipped committed D1 database gate was run separately against a throwaway database: 4 passed.
- Ruff formatting/lint, mypy across 468 source files, import-linter (24 contracts), and scoped diff checks passed.
- Alembic has one head, `413e800f79b5`; a clean disposable database passed upgrade to head, downgrade to base, and upgrade to head.
- All disposable migration/test databases were dropped after verification. The named `clue_discovery_fixture` database retains the live D2-D4 evidence.

## Boundary and follow-up

- D5 must verify every planned acquisition/materialization operation is terminal, seal the account set, and only then advance the project out of discovery.
- Sumble account/contact enrichment, buying-committee work, intent signals, and Exa Search API integration are not part of D4.
