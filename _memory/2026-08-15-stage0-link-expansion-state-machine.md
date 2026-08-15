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

- A fixture-free browser canary subsequently ran with real Clerk authentication, local Scrapling
  acquisition, and live OpenRouter Luna extraction against retained database
  `clue_link_expansion_browser_20260815_c1` and retained root
  `/private/tmp/clue-link-expansion-browser-20260815-c1`.
- The browser automatically released to Home without `Continue anyway`: the immutable fast
  checkpoint froze 8 snapshots at 40.006 seconds and Client-KB extraction/materialization brought
  end-to-end release to roughly 48 seconds, accepted by the founder for this run.
- Background completed the same crawl with 52 fetched snapshots, 52 completed expansions, two
  quarantined ambiguous 90-second Scrapling calls, 245 durable progress events, and zero duplicate
  provider attempts. The fast/background checkpoints remained one each on browser replay; all 81
  retained content-addressed artifacts matched their hashes and durable references.
- Fast extraction published Client-KB v1; background advanced the current KB to v2 with partial,
  fail-closed extraction: 24 operations materialized, 4 were honest empty results, and 4 rejected
  all invalid citations/values. One internal user/identity/workspace/brand/membership/provision and
  one crawl run remained after replay; provisioning logged `created=false`.
- Live concurrency revealed a separate unresolved lock-order defect: PostgreSQL recorded 23
  deadlocks while concurrent workers alternated crawl-run FK/key-share locks and page-row locks.
  Recovery preserved correctness and provider dedupe, but it stretched background completion to
  598.8 seconds and generated 16 DBAPIError worker failures. Fix lock ordering before treating
  background latency/noise as production-ready.
- Browser diagnostics contained only Clerk development-key warnings. Retained logs contained no
  test identity, verification code, bearer/JWT material, raw claim values, or evidence spans.
