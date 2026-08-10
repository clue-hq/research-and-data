# 2026-08-10 — R5 queue, busy, and Stop semantics

## Scope

- Implemented repair Slice R5 only on `platform/lane-d-chat-launch`.
- Preserved the unrelated untracked `.artifacts/` directory and did not begin
  R6.
- Reused the D2 single-flight dispatcher and D3 worker-finalization handoff;
  no schema migration was needed.

## Decisions and changes

- Added one frontend queue selector that returns three separate values from the
  effective durable turn list: `threadBusy`, the exactly-running turn, and
  queued turns in durable submission order.
- Stop now renders only for the running turn and sends only that turn id. A
  queued-only thread stays visibly busy but has no Stop control, and the
  composer remains editable while another turn runs.
- Added an exact-message in-flight guard. A duplicate click for the same
  thread/message is ignored, while a different message can still be accepted
  and queued.
- Added stream state overrides over potentially stale list reads. A terminal
  frame cannot be overwritten by a delayed `running` response and therefore
  cannot resurrect Stop; an override is retired once the canonical read reaches
  the same or a later terminal state.
- Added a one-turn projection read so the Stop route derives state from the
  same submissions union as `GET .../turns`. New Stop requests for queued or
  terminal turns return `409 TURN_NOT_RUNNING`; an existing Stop receipt remains
  an idempotent replay.
- Added a database-backed three-turn acceptance covering A running, B/C queued,
  Stop A, strict B-then-C dispatch, cold reload during B, and rejection of Stop
  for queued or terminal turns.
- Recorded R5 as implemented in
  `apps/frontend/docs/api-contracts/projects.md`.

## Verification

- `npm test` — 128 passed, 0 failed/skipped. The five new R5 model tests cover
  the three selectors, queued-only Stop absence, terminal-over-stale-state
  precedence, durable-terminal reconciliation, and exact-message duplicate
  protection.
- `npm run lint` — pass.
- `npx tsc --noEmit` — pass.
- `npm run design-system:build` — pass earlier in this session.
- Database-backed R5 regression suite — 46 passed:
  `test_lane_d2_turn_submission_db.py`, `test_lane_d3_turn_stream_db.py`, and
  `test_thread_shell_db.py`.
- Focused Ruff and `git diff --check` — pass.
- Repository-wide mypy still reports the four pre-existing R3 read-model errors
  at `threads.py:348` and `chat/router.py:567,829,851`; no R5-added type error is
  present. They were kept out of this scoped commit.
- The first sandboxed frontend test attempt could not create the tsx IPC socket
  (`listen EPERM`). The same exact suite passed with the already-approved local
  test permission.

## In-app browser evidence

- Created isolated project `prj_cd234b2e7ec553f991b0b326eba103c2`
  and thread `thr_0b10208f5e9a5f64bef4ac1cc4e8fbc6` through the real Home
  HTTP flow.
- Turn A `42fb5315-b750-5d80-b745-87ea71f84002` was durably running while
  B `0f8bb04b-3e13-59e1-85f1-792f7261cf4f` and
  C `f71d56e8-d7b2-58c8-8e08-b8b744c33078` were submitted through the
  still-enabled project composer. A double click for B produced exactly one
  durable B submission; the database held exactly A, B, C in that order.
- The browser showed one Stop control, two queued assistant rows, and the
  `Working` status. The durable control receipt targeted A only.
- After cancelling A and dispatching B, the live view changed to one queued row
  and one Stop. A cold navigation reload reconstructed the same state. Clicking
  Stop after reload wrote the receipt for B, never C.
- Cancelling B dispatched C. Stop moved to C, and after C became terminal the
  browser reported zero Stop controls with no application errors in the browser
  log.
- The verification backend/frontend remained local and used the isolated
  `clue_r2_damascus_20260810` database. The helper advanced durable fleet/event
  state without making a paid model-provider call.

## Follow-up outside R5

- The thread selector's project-read label still carries a stale `running`
  suffix after all turn rows are terminal. The conversation's R5 state is
  correct (no busy status and no Stop), but that separate project/sidebar
  summary lifecycle belongs to a later repair slice and was not changed here.

## Closing state

- R5 implementation, verification, and this session note are ready for the
  focused local commit `fix(chat): align queue and Stop semantics`.
- No remote push was performed.
