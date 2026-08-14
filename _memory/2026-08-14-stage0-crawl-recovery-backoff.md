# 2026-08-14 — Stage-0 crawl recovery backoff

## Problem and evidence

The retained C10 Scrapling fleet log showed five durable page blockers followed by repeated
`recovery_pending` task wakes roughly every 0.4–0.6 seconds. Provider uniqueness held, but each wake
reclaimed the top-level task and re-read PostgreSQL while the same page leases were not yet
recoverable.

## Decision and implementation

- Recovery delay is durable queue state, not an `asyncio.sleep` inside a worker and not a
  Scrapling-specific branch.
- Migration `9aacba7cea99` adds non-null DB-clock `fleet_task.available_at`. Queue claims require a
  queued task to be mature, while stale claimed-task takeover remains unchanged.
- Holder-fenced requeue accepts an optional delay and persists `available_at = now() + delay`.
  Ready lower-priority tasks remain claimable while a higher-priority recovery task is delayed.
- `WorkResult.requeue_after` carries scheduling intent; `WorkContext.task_attempt` supplies the
  durable fleet attempt number.
- Official-site phase blocker reads now return count plus the DB-time seconds until the earliest
  page lease expiry or no-spend retry timestamp.
- Recovery uses that timed boundary plus 250ms grace and never less than exponential backoff.
  Untimed work uses 1, 2, 4, 8... seconds capped at 30; lease-derived waits cap at 120 seconds.
- Privacy-safe recovery logs include attempt, delay, and scheduling basis, never URL/body/receipt.

## Verification state

- Pure worker/wiring/lifecycle regression target passed: 16 tests.
- Fresh isolated database retained for review: `clue_recovery_backoff_20260814`.
- Migration smoke passed on that database: upgrade to `9aacba7cea99`, downgrade to
  `a57463ec42ea`, then upgrade back to the single head `9aacba7cea99`.
- The full affected fleet, official-site, C6 wiring, and setup-DB matrix passed: 267 tests, zero
  failures/errors/skips.
- Static gates passed: Ruff format/check, mypy over 658 source files, import-linter 25/25, and
  `git diff --check`.
- The retained C10 evidence/log/database/artifact roots remain untouched. This fix uses a separate
  named database and does not issue another provider request merely to test queue scheduling.

## Review outcome

- Delayed high-priority recovery work does not starve a ready lower-priority task.
- Stale claimed-task takeover remains independent of queued `available_at` eligibility.
- Holder fencing remains enforced on delayed requeue.
- No provider-specific coordinator branch, process-local timer, or worker-blocking sleep was added.
- No unresolved P1/P2 finding remains for this issue.

No secret, URL, response body, provider receipt, user identity, email, or token is stored here.
