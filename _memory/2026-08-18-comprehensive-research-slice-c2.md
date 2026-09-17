# 2026-08-18 — Comprehensive research Slice C2: durable thread research-task read

**Branch:** `platform/comprehensive-account-contact-research-v1`
**Base:** C1 commit `23193aee`
**Scope:** Task C2 only. C3 polling/UI work has not started.

## Landed

- Added `GET /api/v1/projects/{project_id}/threads/{thread_id}/research-tasks`, guarded by
  `thread.read` and the gates route's workspace/project-scoped 404 behavior.
- Added the thread projection over both `agent_turn` and `agent_turn_submission`, so a gate-answer
  launch is visible before a worker creates the matching `agent_turn` row.
- Reused `research_tasks_for_action_refs` for live job counts. Each task is decorated in one
  batched statement with the run's global job-event high-water mark and latest-per-settled-job
  account coverage totals. Contact field progress remains `null` for Slice F.
- The HTTP wire is built from canonical `task_part_from_run` / `TaskCounts` / `TaskState`, then adds
  `field_progress`. Revision is `>= 1`: launch writes queued job events atomically, so an eventless
  visible task is treated as corruption instead of emitting an invalid revision the frontend
  cannot parse.
- Added eight rollback-only DB tests: three-account counts, revision advance, latest coverage
  aggregation, empty thread, submission-only launch, action-ref drift, tenancy/project scoping,
  and permission enforcement.

## Two implementation-level adaptations to the authored plan

- `clue_projections` cannot import `clue_api` (enforced by import-linter), so it cannot call
  `derive_turn_action_ref`. The projection mirrors the closed `turn-action:` prefix and the test
  proves byte equality with the API authority for UUID and string inputs.
- `read_account_coverage_in_run` exposes coverage identity/refs but not completed/unresolved field
  keys. C2 therefore performs the required batched aggregate directly, using the helper's exact
  latest-row order (`created_at DESC, coverage_id DESC`) rather than adding an N+1 API-layer call.

## Verification

- Red proof in a disposable detached worktree: with projection/schema/test applied but the route
  omitted, the first DB test failed `404 != 200`; worktree removed.
- Focused C2 + sibling D5: 20/20 green.
- Projections + chat thread surface + D5 + C2: 84/84 green.
- Full repo `make lint`; full repo `make typecheck` (728 modules); `uv run lint-imports` (26/26
  contracts) all green.
- Live HTTP proof: fresh disposable DB migrated to `a1c5b9842f0e`, Uvicorn served a seeded
  3-account run as HTTP 200 with revision 4 and counts `queued=2`, `completed=1`; server stopped,
  DB and temporary `.context` harness removed.
- The shared `.env` browser DB was not changed. Normal DB tests used the dedicated
  `clue_slicec_bujumbura` database at branch head `a1c5b9842f0e`.
- Required Fable review was attempted twice. The wrapper returned no text first, then an explicit
  429 session-limit response (reset at 03:00 IST), so no Fable verdict is claimed.

## Handoff

C2 is the durable backend source. C3 should add the 3-second frontend poller, parse this exact wire,
and merge by `(runRef.objectId, revision)` without changing the existing task-card component.
