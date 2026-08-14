# 2026-08-14 — Stage-0 durable official-site crawl C8

## Outcome

C8 is implemented and verified. Crawl/extraction visibility now comes from stable at-least-once
events reduced over authoritative PostgreSQL rows; setup exposes a nullable additive body-free
projection; operators have exact scoped inspection, DB-time lease reclaim, fenced fetch-ambiguity
quarantine, and explicit extraction-ambiguity review surfaces. The rollout/release gate is
unchanged; C9 owns the full offline adversarial gate and C10 owns live browser/cutover acceptance.

## Implementation

- Added `official_site/progress.py` with the frozen C8 event/operator vocabulary, UUID5 event
  identities, idempotent sequence reduction, row-derived progress, workspace-scoped recovery
  items, DB-time reclaim, and generation-fenced fetch ambiguity quarantine.
- Lifecycle emits run/discovery/checkpoint/extraction/background events. The coordinator emits
  page claim/fetch/refusal events from actual transitions and counts stale completion fences.
  Visibility failure cannot fail or repeat provider/materialization work.
- `DbOfficialSiteProgressEmitter` writes the existing `run_event` outbox through autonomous
  transactions and emits privacy-safe structured logs. Page events use fetch-key hash + host;
  provider request/status free text is bounded or hashed. No URL/body/raw receipt/user credential
  field exists in the event model.
- The §17.4 metrics matrix is row-derived: frontier, claim latency/contention,
  page/snapshot/blob/duplicate ratio, provider/hashed-host concurrency and outcomes/latency/cost,
  spend-unknown count/age, checkpoint latency/category coverage, extraction outcomes, background
  completion latency, recovery items, and stale fence rejections. Tenant/run IDs are not labels.
- `GET /stage0/setup/current` adds nullable `official_site`; absence remains honest null. Frontend
  fixture and HTTP sources use the same tolerant Zod schema. Existing fast Client-KB release and
  fixture walkthrough are unchanged until C10.
- Added `scripts/18_official_site_c8_operator.py`, the local/production runbook, detailed C8
  contract, parent-plan status, scripts index, and onboarding API contract.
- Fetch recovery items are actionable only when unleased or expired. Extraction `spend_unknown`
  is a separate terminal item with operation/category/field/sanitized model and failure labels;
  its only action is billing/incident review with no automatic retry, preserving successful
  siblings.
- C8 adds no migration and reuses the C1/C7 ledger plus `run_event`.

## Verification

- Fresh isolated DB `clue_c8_official_site_20260814_v2` upgraded to sole head `a57463ec42ea`.
- Complete C0–C8 official-site, API wiring, and setup suite: 164 passed on that clean DB.
- Full frontend: 228 tests passed; ESLint, design-token build, TypeScript, and Next.js production
  build passed. The first sandboxed Turbopack build made no progress and was stopped; the same
  build outside the restricted sandbox compiled successfully in 3.6 seconds.
- Root Ruff: 1,390 files formatted/green; mypy: 658 source files; import-linter: 25 contracts kept,
  zero broken.
- Focused C8 pure/API tests: 7 passed. Focused C8 DB/setup tests: 11 passed. `git diff --check`
  was green during review.

## Failures and corrections

- Reusing the first diagnostic database across repeated C5 fixture runs caused four global
  provider-receipt uniqueness collisions. Those were fixture residue, not product failures. A new
  database was created and the complete suite passed once from a clean migration, as required by
  the plan. Both C8 databases are retained; no database was dropped or reset.
- Initial row metrics used the mutable page lease-acquired timestamp, which completion clears.
  Claim latency now falls back to the first durable attempt start and clamps anomalous fixture
  chronology at zero.
- Initial spend-unknown age covered fetch attempts only. It now takes the oldest active fetch or
  extraction ambiguity.
- Retained C7 inspection initially returned `recovery_required=true` with no item for its model
  ambiguity. Extraction ambiguity is now explicitly identified and documented without inventing
  unsafe replay semantics.
- The worker exception handler initially risked masking its original error if visibility lookup
  failed. Visibility read/emission is now fully contained and the original exception is preserved.

## Retained evidence

- C7 live DB/artifact root remain untouched.
- Read-only C8 inspection of crawl `be78aa55-874f-4808-aadf-31f0df3252aa` reconstructed 16 pages,
  15 snapshots, 14 unique blobs, two checkpoints, 19 materialized extraction operations, two
  failures, one extraction ambiguity, and partial+completed state with `event_count=0`.
- The ambiguity item identifies operation `b925fc0e-d241-550e-95e1-895a8df2ce4b`, field
  `client.icp_evidence`, and `review-billing-no-auto-retry`; model label is hashed. The inspection
  made zero provider calls and no retained-row mutation.

No secrets, raw page/model bodies, full URLs, full provider receipts, tokens, emails, Clerk
subjects, or claim values are recorded here.
