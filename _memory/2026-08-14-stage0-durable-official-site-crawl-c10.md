# 2026-08-14 — Stage-0 durable official-site crawl C10

## Outcome

C10 is accepted. Two isolated real-Clerk browser journeys completed authoritative onboarding with
real Firecrawl and Scrapling acquisition, grounded Client-KB materialization, same-frontier
background completion, and zero-call replay. Fast release measured 30.800605 seconds for Firecrawl
and 28.785543 seconds for Scrapling, both under 40 seconds. The capability is merge-ready but stays
default-off and allowlisted; retained evidence must not be removed before review sign-off.

## Live corrections

- Authoritative Stage-0 no longer invokes the historical field resolver before the durable crawl.
  It prepares the client entity/recon, enqueues crawl work, and finalizes Client-KB/lane truth only
  after checkpoint-grounded claim commit. Shadow behavior remains historical.
- Fast materialization begins immediately after the immutable fast checkpoint freezes while
  already-dispatched calls drain safely. Late calls do not mutate fast and are not cancelled.
- The frontend stall signature now includes committed official-site counters/events.
- `PageFetchRequest` carries registrable-domain/subdomain policy so the real apex-to-`www`
  redirect is allowed without accepting hostile suffix domains.
- Discovery batches now use the same immutable unique-URL category quota vocabulary as fast
  claims before the run-wide page ceiling applies. Root+sitemap seeds and recursive links share
  the ordering; duplicates and excess pages remain as provenance/background tail.
- URL path category now wins before link-text fallback. This prevented a long blog-card sentence
  containing “plans” from forging pricing coverage; final real Scrapling canary selected exact
  `/pricing`, `/about-us`, `/become-a-partner`, `/privacy`, `/blog`, and three product/use-case URLs.

## Retained evidence

- Accepted Firecrawl DB/root: `clue_c10_firecrawl_tuned_20260814` and
  `/private/tmp/clue-c10-firecrawl-tuned-20260814`.
- Accepted Scrapling DB/root: `clue_c10_scrapling_retry_20260814` and
  `/private/tmp/clue-c10-scrapling-retry-20260814`.
- Post-review canary DB/root: `clue_c10_scrapling_priority_20260814` and
  `/private/tmp/clue-c10-scrapling-priority-20260814`; retained JSON under `evidence/`.
- Diagnostic Firecrawl/Scrapling databases and roots, regression DB
  `clue_c10_cutover_tests_20260814`, and migration DB `clue_c10_migration_smoke_20260814` also
  remain untouched.
- Firecrawl: 30 unique pages, 10 persisted/20 conservatively ambiguous attempts, ten unique
  provider request IDs, ten cents, ten snapshots/nine blobs, fast 8/background 10 snapshots,
  20 materialized/2 failed operations, 22 official-site claims.
- Scrapling: 30 unique pages, 29 persisted no-spend/one ambiguous attempt, 29 snapshots/28 blobs,
  fast 7/background 29 snapshots, 20 materialized/2 failed operations, 24 official-site claims.
- Both runs: one internal user/identity/workspace/membership/brand/provisioning row; provision
  replay created nothing; crawl replay created no page/attempt/snapshot/checkpoint/extraction/claim;
  no duplicate fetch-key attempts, absent checkpoint refs, or artifact hash mismatch.
- Final third browser repeat was refused by the in-app browser URL security policy and was not
  bypassed. The earlier two complete browser runs remain the browser evidence; post-fix closure is
  real Scrapling acquisition + pure/lifecycle/real-PostgreSQL tests.

## Verification

- Complete affected backend official-site/setup/auth target passed after implementation.
- Final category policy/lifecycle target: 51 passed.
- Final PostgreSQL graph/coordinator/lifecycle target: 14 passed.
- Frontend: 229 tests, design-system build, ESLint, TypeScript, Next production build, 19 routes.
- Ruff passed; mypy 658 files; import-linter 25/25; diff whitespace clean.
- Alembic sole head `a57463ec42ea`; fresh upgrade/downgrade/upgrade passed.
- Detailed source of truth:
  `docs/specs/FI-stage0-durable-official-site-crawl-C10-live-acceptance.md`.

## Typed follow-ups

- Firecrawl returned 20 HTTP 429 outcomes without receipts; retain `spend_unknown` quarantine and
  tune provider rate/concurrency or add receipt reconciliation before broad enablement.
- Real Luna operations carried token counts but provider-reported cost zero; do not treat model
  monetary telemetry as enforcement-grade until billing attribution is monitored.
- Fleet recovery wakes were sub-second while leases drained; post-C10 migration `9aacba7cea99`
  closes this with DB-clock delayed requeue, lease/retry-aware timing, and exponential fallback.
- Both model phases honestly preserved two failed field operations alongside 20 successes.

No secret, email, raw Clerk subject/token/code, raw provider receipt, page body, model response, or
claim value is stored in this note.
