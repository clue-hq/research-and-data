# Stage-0 page publication and link-expansion state machine

## Problem and decision

- Live Scrapling evidence showed provider results and snapshots persisted promptly, but outgoing-
  link discovery could fail afterward and leave the page in `persistence_pending` until its page
  lease expired. The worker swallowed the exception and onboarding waited roughly 90 seconds.
- Acquisition and recursive discovery are now separate durable outcomes. `complete_page` atomically
  publishes the page as `fetched`, releases its acquisition lease, and inserts one snapshot-keyed
  `official_site_link_expansion` job. Expansion has its own lease generation, heartbeat, retry,
  terminal partial-failure state, progress, and recovery cadence.
- Expansion never calls a provider. A failed or abandoned expansion cannot roll back a fetched page
  or hide its snapshot from a fast corpus checkpoint. The background phase resumes the same job.
- Expired expansion leases enter DB-clock exponential retry wait instead of causing sub-second fleet
  wake churn. The fast scheduler's retry hint is capped by the persisted fast deadline.
- The setup screen's `stalled` fallback remains recoverable and keeps polling durable state; later
  progress clears the fallback and a later fast commit still releases the browser automatically.

## Implementation

- Added reversible Alembic revision `2500c418396f` and the frozen expansion contracts/repository
  primitives: atomic enqueue, concurrent claim, renew, fenced complete/fail, reclaim, progress, and
  corpus coverage.
- Coordinator workers process expansion independently, emit privacy-safe structured events/logs,
  durably classify expected failures, and now log previously swallowed unexpected worker failures.
- Added expansion rows to reference-only DSAR reach and additive setup/operator progress fields.
- Updated the C0/C4/C5/C8 contracts, main crawl plan, and frontend onboarding API contract.

## Verification

- Retained isolated database: `clue_link_expansion_20260815`.
- Empty upgrade, `2500c -> df332 -> 2500c` downgrade/upgrade, and one-head check passed.
- Complete affected backend gate passed: 210 official-site/setup tests.
- Frontend passed: 235 tests, lint, design-system build, and production build.
- Static gates passed: Ruff check/format, mypy over 679 files, and 25/25 import contracts.
- New DB acceptance proves: one winner from ten concurrent expansion claimers; stale renewal,
  completion, and failure writes rejected; snapshot usable during expansion retry/failure; three-
  attempt terminal partial outcome; background continuation on the same run; root provider called
  once; fast wake capped by its deadline.
- The monolithic suite reached 33 failures, all outside official-site/setup and matching existing
  shared-state/order contamination families (source-manifest redefinition, migration teardown,
  discovery/tier/fleet/lane-E). `make check` also sees three pre-existing formatting violations in
  `platform/api/clue_api/chat/turn_events.py`, `scripts/19_production_context_release_gate.py`, and
  `tests/api/test_lane_d3_turn_stream_db.py`. These unrelated baselines were not modified.

## Remaining release evidence

- No paid live provider call was made for this internal state-machine correction. Existing
  Firecrawl/Scrapling single-page adapters are unchanged; the zero-refetch property is proven by
  provider counters and the durable database path. A later browser canary can validate latency in
  production-like conditions without changing this contract.
