# Stage-0 fast-page deferral correction — 2026-08-15

**Status:** implemented and offline/database verified; fresh live Scrapling/browser rerun remains.

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

