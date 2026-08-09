# R1 SSE wire and terminal-lifecycle repair

Date: 2026-08-10
Branch: `platform/lane-d-chat-launch`

## Scope completed

Implemented Slice R1 only. No Home/project-bootstrap, sidebar, Gallery, or R2
work was started.

- Backend connect-generated `stream.hello` and `stream.reset` frames now carry
  schema/type/project/thread/turn identity; reset declares
  `rehydrate=transcript`.
- Backend replay and live-tail loops emit through the first terminal event and
  return immediately for completed, failed, cancelled, or awaiting-input turns.
- Frontend parsing now requires common frame identity, cross-checks SSE
  `event:` against JSON `type`, and treats version/identity/discriminator
  failures as fatal protocol errors.
- The HTTP reader cancels immediately on terminal/reset, does not reconnect
  after terminal, and reports a typed close reason to the controller.
- The controller rehydrates canonical state after terminal/reset, resumes a
  reset stream only when its durable turn remains live, and applies durable
  queued/running/terminal transitions on the same render cycle.
- Thread busy and running-turn state are separate: queued work stays visible,
  but Stop is rendered and targeted only for the exactly-running turn.
- Nonfatal parser diagnostics go to browser diagnostics instead of visible
  transcript notes; fatal recovery uses one controlled message.

## Verification

- Backend: complete `tests/api/test_lane_d3_turn_stream_db.py` — 27 passed.
  Added explicit assertions for control-frame identity/name equality, terminal
  replay closure, and terminal live-batch closure.
- Frontend: focused schema/transcript/repository suite — 47 passed.
- Frontend `tsc --noEmit` — passed.
- Focused frontend ESLint over all changed project-chat files — passed.
- Ruff over changed backend/test files — passed.
- `git diff --check` — clean before memory/commit handoff.

The shared local `clue` database was reachable but stamped with migration
`e79f192828b1` from another worktree, so it was not modified. Tests used a
fresh isolated `clue_r1_damascus_20260810` database, which was removed after
the green run.

## Live browser evidence

Used the authenticated in-app browser on
`/projects/prj_4bc999e4114f37e8` with the real HTTP repositories and restarted
backend.

- A running turn showed `Working — new messages will queue behind this turn.`
  and exactly one Stop button after `turn.started`.
- The final assistant response rendered, then Stop and Working both reached
  count zero without navigation or manual refresh.
- `malformed turn-stream frame` count stayed zero; no controlled recovery
  notice appeared on the healthy run.
- Cold reload preserved the final assistant response and still showed zero
  Stop/malformed-frame elements.
- Browser console had no chat-stream warnings/errors (only Clerk's existing
  development-key warning).

The existing frontend dev server remains on port 3000. The backend was
restarted from this worktree with `.env` and remains on `127.0.0.1:8000` for
continued manual inspection.

## Preserved state and next boundary

- User-owned untracked `.artifacts/` was not touched or staged.
- R2 remains the next separately authorized slice; this session stopped at R1.
