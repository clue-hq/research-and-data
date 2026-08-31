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

## Lock-order correction and final live acceptance

- Root cause was the discovery transaction taking `FOR UPDATE` on the crawl-run parent while
  attempt/snapshot transactions held page rows and then acquired the parent's FK `KEY SHARE`.
  The inverse parent-to-page versus page-to-parent acquisition order formed the observed cycle.
- Discovery now uses explicit `FOR NO KEY UPDATE`: it still serializes page-ceiling/discovery
  accounting, but it is compatible with child-FK `KEY SHARE`. Checkpoint transitions retain the
  stronger `FOR UPDATE` lock. A narrow transaction-only SQLSTATE `40P01` retry adds bounded
  jittered protection without ever wrapping provider or artifact I/O.
- Unexpected acquisition failures now perform immediate owner/generation-fenced handoff. A
  prepared/no-spend attempt requeues; a dispatched ambiguous attempt moves directly to
  reconciliation; persistence/reconciliation leases are released. Only the two forward-progress
  transitions keep a local worker alive. Repeat-prone or unresolved recovery remains fatal.
- Repository and coordinator tests cover lock compatibility, stale fences, each attempt-state
  handoff, no-spend replay, high-fanout ten-worker acquisition/expansion overlap, and one provider
  call per URL. The complete `tests/official_site` target passed 201 tests on retained isolated DB
  `clue_deadlock_fix_20260815_c1`; targeted Ruff/format/mypy and all 25 import contracts passed.
- Retain the first diagnostic DB/root `clue_deadlock_fix_browser_20260815_c2` and
  `/private/tmp/clue-deadlock-fix-browser-20260815-c2`: its apex robots redirect was refused before
  acquisition and therefore did not exercise the concurrency correction.
- Retain the intermediate DB/root `clue_deadlock_fix_browser_20260815_c3` and
  `/private/tmp/clue-deadlock-fix-browser-20260815-c3`: it proved zero deadlocks and immediate
  quarantine, but safely recovered exceptions still counted as worker errors and left the fleet
  task failed. That final composition flaw was corrected before the accepted run.
- Accepted fixture-free Clerk/Scrapling/Luna browser run is retained as
  `clue_deadlock_fix_browser_20260815_c4` with root
  `/private/tmp/clue-deadlock-fix-browser-20260815-c4`. Browser released automatically to Home.
  Crawl run `bffb2d2e-dbf4-4267-bf32-7c077cb931ad` completed in 23.569 seconds: immutable fast
  checkpoint froze 12 snapshots at 2.181 seconds, and background froze 52 at 13.003 seconds before
  Luna materialization completed.
- Final C4 state: 52 fetched pages, 52 generation-one completed expansions, 52 persisted attempts,
  two conservatively quarantined ambiguous Scrapling outcomes, zero page with multiple attempts,
  and both fleet tasks `done` in one attempt. The two validation failures moved immediately to
  reconciliation and did not emit `worker_failed` or stop the phase.
- Fleet logs contain zero `40P01`, deadlock, DBAPIError, repository-deadlock-retry, or fatal worker
  entries. PostgreSQL has no deadlock entry during the C4 window. Retained logs contain no test
  identity, verification code, bearer/JWT material, raw claim values, or evidence spans.

## Repeat browser acceptance (C5)

- Repeated the fixture-free profile-to-Home journey with the existing real Clerk session against
  retained isolated database `clue_deadlock_fix_browser_20260815_c5` and retained evidence root
  `/private/tmp/clue-deadlock-fix-browser-20260815-c5`. Provisioning created one internal user,
  identity, workspace, brand, and owner membership; every observed backend API response was 2xx.
- The setting-up screen released automatically to Home with no `Continue anyway`. Durable fast
  materialization completed in 10.688 seconds from recon start and about 40.3 seconds from auth
  provisioning start; fast Client-KB v1 contained 17 new claim refs from 12 snapshots.
- The same crawl run completed in 30.523 seconds: the immutable fast checkpoint froze 12 snapshots
  at 2.524 seconds and background froze 52 at 16.843 seconds. Final state was 52 fetched pages,
  52 generation-one completed expansions, 52 persisted attempts, zero multi-attempt pages, and
  both fleet tasks `done` on their first attempt.
- Two Scrapling calls (`/blog` and `/direct-access-colonoscopy`) returned HTTP 200 at the transport
  layer but raised result `ValidationError` before a durable receipt/snapshot could be retained.
  The immediate handoff conservatively quarantined both as `spend_unknown` with no retry. This did
  not delay fast release or fail the crawl, but remains a provider-adapter validation edge case.
- PostgreSQL and fleet logs contain zero deadlock, SQLSTATE `40P01`, DBAPIError, repository retry,
  or fatal worker entries. The final Client-KB reached v2 with 51 current official-site claims over
  15 fields and two linked product rows. Customer-evidence extraction remained honestly partial:
  one background field rejected invalid citations and two fields were empty.
- Retained logs contain no test identity, verification code, bearer/JWT material, or raw page and
  claim bodies. The backend and fleet were stopped after evidence capture; the verified Home tab
  remains open.
