# Stage-0 fast-page deferral correction — 2026-08-15

**Status:** implemented and offline/database verified; fresh live Scrapling/browser rerun completed
with a failed release-time gate and successful durable/background semantics.

## Defect and decision

- Retained S6 evidence showed 11 useful snapshots acquired in about 6.1 seconds, followed by an
  87.7-second wait for one `/ehr-partnership` lease before fast v1 materialization.
- When local fast workers returned cleanly while another process still held a durable lease,
  `OfficialSiteCrawlLifecycle._run_fast` cancelled the DB-deadline task and treated the lease as a
  fast publication blocker.
- The fast deadline now remains armed whenever clean acquisition blockers exist. At cutoff, the
  completed snapshot set freezes; unresolved acquisition remains in the same run/frontier and is
  handled under background claiming, leases, retries, and generation fencing.
- A clean acquisition blocker no longer blocks `fast_closing -> fast_complete` after checkpoint
  creation. Real worker/fencing faults still follow the prior recovery/hard-failure contract, and
  every unfinished state still blocks final background completion.
- Already-dispatched provider calls remain uncancelled. A late safely persisted result cannot
  mutate fast v1 and is eligible only for the background checkpoint/v2.

## Verification

- `tests/official_site/test_lifecycle_c6.py`: 10 passed, including a simulated 87.7/90-second
  lease hint, authoritative v1/v2 separation with one background fetch, worker-fault behavior,
  and `fast_closing` cold replay.
- C0–C9 provider-free official-site/API matrix: 135 passed.
- Fresh isolated database `clue_fast_defer_20260815_c1` migrated to `df332fd7904c`; official-site
  C1/C2/C4/C5/C7/C8/C9 database suites: 61 passed.
- Ruff check/format, full mypy (679 source files), import-linter (25 contracts), and diff check pass.
- The first Alembic attempt was blocked by the filesystem/network sandbox; the approved rerun
  against the exact isolated local database succeeded. No shared or retained acceptance database
  was modified.

## Remaining release proof

- Preserve historical R5 evidence as failed: 103.759 seconds plus manual Continue-anyway.
- Run a fresh retained real Scrapling + Luna + browser journey and prove fast Client-KB/browser
  release at `<=40s`, no manual override, deferred-page exclusion from v1, same-frontier inclusion
  in background v2, and no duplicate provider acquisition.

## Browser acceptance continuation

- Retained diagnostic run `clue_fast_defer_browser_20260815_c1` and
  `/private/tmp/clue-fast-defer-browser-20260815-c1` proved the real Clerk profile/provisioning
  journey, but no provider call occurred: the newly provisioned workspace ID was random and did
  not match the fleet's pre-start allowlist. This is acceptance-harness sequencing, not a crawl
  result; retain the run as failed diagnostic evidence.
- Prepared and migrated fresh database `clue_fast_defer_browser_20260815_c2` with retained root
  `/private/tmp/clue-fast-defer-browser-20260815-c2`. The production API was run against it while
  the fleet remained stopped until the browser provisioned the new workspace.
- During the c2 restart the controllable in-app tab was left
  on Chromium's internal `data:` connection-error document during server restart. Browser safety
  policy refused both direct navigation and the error page's Reload action. The user must manually
  enter `http://localhost:3000` once; then the c2 journey can continue without reseeding or
  changing the retained database.
- The user manually completed the c2 profile and later clicked `Continue anyway` before the fleet
  was started. At that point the database held one `stage0_recon` fleet task in `queued` state with
  `attempts=0`, and zero `recon_run`, crawl-run, crawl-page, fetch-attempt, or page-snapshot rows.
  Therefore exactly zero pages had been scraped; the UI fallback was reached solely while queued
  work had no worker, not because a Scrapling page fetch was slow.
- Retained c3 as a correctly orchestrated but product-failed run:
  `clue_fast_defer_browser_20260815_c3` and
  `/private/tmp/clue-fast-defer-browser-20260815-c3`. The validated launcher resolved workspace
  `ws_3a8a18ba0fdb45a98ff05f643f9e47dd`, the fleet claimed the queued recon immediately, and crawl
  run `12260f9e-5600-4e2a-8108-62cd06965f56` started. Scrapling observed HTTP 301 for
  `https://insighthealth.ai/robots.txt`; the coordinator classified the root page as
  `robots_refused:robots_unavailable_fail_closed`, then froze empty fast/background checkpoints
  and wrote zero claims. Direct status verification confirmed the redirect target
  `https://www.insighthealth.ai/robots.txt` returns 200 and the canonical www homepage returns 200.
  This is a separate same-site robots-redirect handling defect, not stuck-page deferral evidence.
- Retained c4 as the first fully live canonical-host acceptance:
  `clue_fast_defer_browser_20260815_c4` and
  `/private/tmp/clue-fast-defer-browser-20260815-c4`. Real Clerk provisioning created workspace
  `ws_a6418d03a1754d1490fc1514f47633c2`; the allowlist-aware launcher then started the fleet and
  ran real Scrapling acquisition plus `openai/gpt-5.6-luna` extraction for recon
  `a7959f13-b902-5595-aa26-982720b9ef3e` / crawl
  `b0ee1995-5395-4788-a349-2614d700dbe1`.
- Fast acquisition persisted ten useful pages in about five seconds. Two more pages were
  `persistence_pending`, but the fleet requeued the whole task for the earliest lease expiry
  (86.57 seconds) instead of waking at the earlier 25-second fast deadline. The immutable fast
  checkpoint therefore did not freeze until 19:03:03, about 93 seconds after submit, and fast
  Luna materialization/Client-KB v1 completed at 19:03:11.973, 101.02 seconds after submit.
- The browser showed the timeout fallback at about 89 seconds. Once shown, that state stopped
  observing readiness: it remained on the fallback after the fast Client-KB commit and reached
  Home only after `Try again` was clicked. That action replayed `POST /stage0/setup` but remained
  idempotent (one recon run and one crawl run). This fails the automatic `<=40s` release gate.
- Fast checkpoint `d67fa630-81a5-4d84-92ff-9b8a62a6bc56` contains exactly ten HTTP-200 snapshots.
  The two late persistence recoveries were excluded from fast v1. Fast extraction wrote 15 claims
  (plus the KB-version marker) and synchronized seven products.
- Background continued the same durable frontier and completed at 19:06:43 with checkpoint
  `6e6ce8b9-ef42-4da4-8bd3-041c4843c080`, 52 snapshots, Client-KB v2, 34 background claims, and ten
  total synchronized product rows. The fast checkpoint remained unchanged at ten snapshots.
- Duplicate-provider proof passed: 54 attempt rows represented 52 persisted Scrapling acquisitions
  plus two quarantined ambiguous operations; no page had multiple attempt rows, multiple provider
  completions, or `attempt_count > 1`. The quarantined URLs were `/blog` and
  `/direct-access-colonoscopy`, both with `provider_operation_lookup_unavailable`; neither was
  blindly retried. All 52 snapshots resolved to artifacts with matching URL/hash/key provenance.
- The retained root contains 89 content-addressed artifacts because it also includes extraction
  artifacts; the crawl itself has 52 URL-level snapshots, 52 distinct content hashes, and 52
  distinct artifact keys. Logs contain no test email or verification code.
- Release blocker: detached-fleet recovery scheduling must choose the earliest relevant wake,
  including `fast_claim_deadline_at`, instead of only the lease/retry deadline. A second frontend
  blocker is that the timeout fallback must keep polling (or subscribe to durable progress) and
  auto-release when the fast Client-KB commit arrives. Background lease-aware waits remain noisy
  in wall-clock duration but are not duplicate provider calls.
