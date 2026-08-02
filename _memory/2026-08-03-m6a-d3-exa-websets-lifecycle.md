# 2026-08-03 — M6A D3 Exa Websets lifecycle

Branch: `platform/c8-exa-sumble-discovery`

Status: D3 mechanical/code boundary complete. Live-provider gate remains open because the current
Exa team cannot create Websets through the API.

## Delivered

- Pinned typed item/event page contracts and one-attempt lifecycle reads in
  `clue_research.adapters.exa_websets`.
- Exact raw-body Exa HMAC verification (`t` + `v1`, 300-second tolerance, constant-time match).
- Verified webhook body durability, event dedupe/out-of-order handling, and wake-only authority.
- D2 success now transactionally schedules one stable initial poll wake.
- Provider-neutral operation reconciliation lease; stale wake reclaim; source-filtered Exa wake
  drain that does not steal future provider wakes.
- Page-before-item transaction split, immutable cursor replay, raw item snapshots, paginated event
  tenancy filtering, final idle poll, request/search/enrichment/item/event reconciliation, and
  typed retryable drift failure.
- Versioned modeled credit settlement from public per-row formula, bounded by reservation and
  written once. It is not represented as provider billing telemetry.
- Default-off production fleet loop and conditional production webhook route. Enabling polling
  requires the Exa API key; webhook ingress requires its separate HMAC secret.
- D1 readiness corrections: webhook events must be signature-verified; page-item count checks apply
  only to item pages.
- Detailed record: `docs/specs/M06A-D3-exa-websets-lifecycle.md`.

D4 boundaries remain intact: D3 leaves item snapshots `raw`, writes no candidate/account/claim or
field-resolution rows, moves only to batch `identity_resolution`, and cannot advance the project to
scoring or seal the batch.

## Mechanical verification

- Real PostgreSQL + filesystem D3 acceptance: 7 passed.
- D1 wake/readiness plus D3: 12 passed, 1 expected opt-in D1 skip.
- D0-D3 + production projections/fleet selection: 59 passed, 1 expected D1 skip.
- Changed-surface `ruff format --check`, `ruff check`, and `mypy`: passed.
- Import-linter: 24 contracts kept, 0 broken.
- Migration database remained at single head `283ab57486e8`; no D3 migration was required.

The committed-page crash test used independent production-style transactions: the first item page
was visible in PostgreSQL while item count was still zero; a new lifecycle instance reclaimed the
expired operation lease, reused that page without another first-cursor call, fetched only page two,
wrote three unique raw items, and settled 66 modeled units once. Terminal replay made zero calls.

Other real-DB cases cover signed duplicate/out-of-order delivery, invalid endpoint signature,
missed webhook polling, two cursors, event page reconciliation, 429/Retry-After, breaking schema
drift with preserved body, cancellation before ingestion, and stale wake reclaim.

## Broad-suite evidence and unrelated baseline

The default-environment full suite reached three failures outside D3. The compliance DSAR failure
was sandbox-only localhost denial and passed when rerun with local DB access. The two actual
pre-existing failures are:

- `tests/memory/test_memory_offline.py::test_no_production_code_outside_memory_touches_the_substrate`
  (existing `clue_api/trial/stage0_runtime.py` memory import); and
- `tests/resolvers/test_static.py::test_no_secret_shaped_strings_in_source_or_fixtures`
  (existing Sumble fixture literal).

Repository-wide format check also names 14 unrelated pre-existing unformatted files. D3 files all
pass format. Do not edit those unrelated files as part of D3.

A DB-enabled full-suite attempt against the populated shared fixture database was intentionally not
treated as authoritative: destructive migration tests, active `.env` feature flags, and pre-seeded
source manifests caused order/environment collisions. The isolated real-DB D0-D3 gate is the valid
D3 evidence.

## Remaining live gate

Once an API-entitled Exa team is available, reuse a successful D2 provider operation and prove real
idle, real item/event cursor exhaustion, raw artifacts, billing comparison, restart, and zero
duplicate traffic/cost. The two prior 401/not-charged operations remain immutable and must not be
reused. Do not begin D4 until the requested pause/adversarial review is complete.
