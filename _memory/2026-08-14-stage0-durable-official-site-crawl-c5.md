# Stage-0 durable official-site crawl C5

Date: 2026-08-14
Branch: `platform/onboarding-integration`
Outcome: C5 implemented, reviewed, and verified; C6 production run/checkpoint/fleet composition is
next. The existing Stage-0 resolver remains authoritative.

## Coordinator delivered

- `ConcurrentCrawlCoordinator` drains injected fast/background runs through a fixed-size logical
  worker pool. Work order is persistence recovery, reconciliation, then ordinary page claims.
- Every ordinary page clears C2 DNS/IP preflight before robots authorization or provider access.
  Provider responses are rechecked for redirects/final target, MIME, decompressed size, and link
  ceilings before durable persistence/discovery.
- C4 now exposes a replay-safe pre-completion hook. C5 records link/redirect observations while the
  page is still `persistence_pending`; a completion crash reuses the same artifact/snapshot and
  replays discovery under a fresh generation without refetching the original URL.
- Heartbeats renew with the full C1 fence. Graceful stop/caller cancellation prevents new claims
  while shielding already-dispatched bounded provider work until it returns.
- Idle workers stay alive while another local operation is active, so a slow homepage can reveal
  children to the full pool instead of silently collapsing recursive acquisition to one worker.

## PostgreSQL scheduling decisions

- Ordinary and reconciliation claims acquire the global advisory lock before a normalized-host
  advisory lock, then count active leases across all workspaces/runs. Host capacity is not run
  scoped. Mixed active run configs use the conservative minimum effective cap.
- Background ordinary and reconciliation claims yield to quota-eligible fast work across runs.
  The fairness check reclaims expired fast leases under the global lock before deciding.
- Fast category targets are homepage 1, product 3, pricing 1, customer proof 2, company 1, partner
  1, trust 1, and blog 1, bounded by the run's fast page ceiling. Ordering is priority, known depth,
  database discovery time, then persisted UUID.
- `retryable_no_spend` is bounded to three attempts under the V1 contract and then fails with
  `no_spend_retry_exhausted`. Possibly charged/ambiguous attempts never enter this loop.

## Failures found and corrected during acceptance

- The initial robots call was unconditional after preflight evaluation. It now runs only after a
  public-network preflight succeeds, preventing a live robots adapter from touching an unsafe host.
- Background fairness initially ignored expired fast leases and background reconciliation. Both
  paths now yield correctly.
- The first fake-provider concurrency fixture generated receipt IDs from a mutable global call
  count after delay, causing a false unique-receipt collision. It now captures call identity before
  awaiting; this was test-only, not product logic.
- Same-priority sitemap rows created in one transaction correctly use UUID as the final persisted
  tiebreaker; the acceptance assertion now tests category order without inventing input-order
  semantics.
- Multiprocess children must enter their own `db_lifespan`; the final test does so and exercises
  real spawned processes rather than asyncio-only concurrency.

## Verification

- Fresh isolated database retained: `clue_c5_official_site_20260814_final`.
- Complete C0-C5 official-site suite: 128/128 pass. C5 contributes 11/11 focused cases: two
  provider-free guards plus nine real-PostgreSQL cases, including two four-process claim races.
- Alembic: one head `6e7ba5968751`; isolated `head -> da5f3fe5a90f -> head` succeeds.
- Ruff format/check and focused official-site/tests mypy are green. Provider-free C0-C5 regression
  is green.
- No shared database, browser session, C4 retained live database/artifacts, or paid provider was
  used. No live C5 claim is made because C6 has not yet composed the product run/checkpoint/fleet
  lifecycle; hand-composing a paid crawl would not prove that lifecycle.

## C6 handoff

- Create/reuse one crawl run per recon and compose the live provider/operation-lookup/robots
  registry.
- Execute fast/background workers through the durable fleet, persist phase transitions/deadline,
  freeze immutable checkpoints, and continue the same frontier in background.
- Project committed crawl/checkpoint truth into onboarding progress and keep auth/setup polling
  responsive. Keep the feature default-off until browser/live acceptance passes.
