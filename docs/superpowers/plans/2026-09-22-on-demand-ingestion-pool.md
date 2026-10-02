# On-demand ingestion workers

## Agreed behavior

Ingestion uses dedicated capacity, never the primary fleet's chat, design or research
slots. This is development infrastructure; preserving already-running ingestions is
not an acceptance requirement. Keep the existing durable fleet queue and leases.

The local pool controller is a small persistent process. When ingestion work exists it
starts one pipeline coordinator and four annotation worker processes. Each annotation
worker has ten image-task slots, giving forty slots for the ingestion backlog. The
coordinator has one independent slot so waiting for image results cannot deadlock the
image workers. All five execution processes stop after the queue remains idle. The
controller alone stays available to detect the next ingestion. Deployment on separate
machines/containers uses these same worker roles; the local process launcher does not
claim hard CPU/memory or provider-account isolation.

## Implementation sequence

1. **Strict routing.** Primary and embedded design workers claim only design turns.
   A coordinator claims ingestion envelopes; image workers claim new per-asset
   envelopes under the existing `design_job` fleet kind. Check routing inside SQL
   claims and again before execution. Missing routing discriminants fail closed.
2. **Durable image fan-out.** The existing ingestion pipeline queues one task per
   image and collects persisted results. Reuse the existing image analyzer, storage,
   overrides, fingerprints, spend seam and source context. Child writes require both
   the parent generation and their own live work lease; replay skips completed work.
   Failed children are reported explicitly rather than hanging the parent.
3. **On-demand lifecycle.** One database-elected controller per database launches
   bounded local children, replaces crashed children, scales to zero after idle, and
   stops children on controller exit. Children stop if their controller disappears.
   No provider calls, parsing or capture run in the controller or primary workers.
4. **Configuration and operation.** Document every new setting in both env examples;
   align local values. Add start/stop/status support to the workspace launcher, worker
   role logs and an operations note. Keep the annotation provider cap at forty across
   the pool. Preserve other workspace processes.
5. **Verification and activation.** Unit tests cover routing, 4x10 capacity and lifecycle;
   isolated database tests exercise real claims, parent/child fencing, failed children,
   replay and completion using mocked providers. Check existing ingestion/fleet suites.
   Restart only affected San Diego processes after verifying no primary work is active;
   verify idle zero and a no-spend isolated pool smoke. Commit locally; never push.

## Acceptance

- Primary workers cannot consume ingestion or image-analysis tasks, even with backlog.
- Four worker processes can execute forty distinct image tasks concurrently; one image
  per model request, without nested fifteen-thread fan-out.
- A coordinator waiting on children cannot starve their execution.
- Jobs share the same bounded pool; completed results and user overrides survive
  replay, and stale workers cannot overwrite newer work.
- Idle execution capacity reaches zero and new work wakes it again; controller failure
  cannot leave an unbounded orphan pool.
- Existing progress/status and stored analysis contracts remain intact.
- No paid regeneration or historical backfill is performed as part of verification.

## Completed 2026-09-22

Implemented and activated in San Diego. Verification: 57 root tests, 94 API tests
(one paid live test skipped), all 28 import contracts, focused static checks, and a
real controller lifecycle smoke against a temporary database. Four OS workers reached
forty simultaneous mocked image calls. The live controller is idle with no execution
children; APIs and primary workers are healthy. See `docs/runbooks/ingestion-pool.md`
for settings, lifecycle, recovery behavior and the local-resource isolation boundary.
