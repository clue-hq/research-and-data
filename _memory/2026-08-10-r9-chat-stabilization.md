# 2026-08-10 — R9 chat stabilization

## Scope

Implemented only the four defects ratified for R9 after the R1–R8 browser
audit: queued-turn prompt isolation, durable cancellation rendering, sidebar
preview-to-pin interaction, and live Home/thread reconciliation. Unrelated
work and the untracked `.artifacts/` directory were preserved.

## Changes

- The context assembler now labels candidate origin and requires exactly one
  current-user instruction at L7. The accepted submission body is the final
  `HumanMessage`; capture and attachment receipts are system context. This
  prevents a queued turn from treating an earlier history message as its
  current prompt.
- Added durable agent-turn journal state `cancelled` with reversible Alembic
  revision `5d7ab295742b`. Stop waits for the model task to stop, records the
  terminal state, and then emits `turn.cancelled`. Cold turn reads derive
  cancelled/failed state from the latest journal event if stream frames have
  aged out.
- The submissions-union can hydrate a workspace-scoped `submission_message`
  for turns whose canonical user message does not exist yet. The frontend
  prefers canonical history, then this accepted stand-in, then local optimistic
  state, so Home text is visible before the worker begins but never duplicated.
- Live stream events update the active turn/thread summary synchronously.
  Terminal/reset reconciliation refreshes canonical messages, turns, threads,
  and the shared sidebar project catalog.
- The project header trigger now remains above the hover-preview overlay.
  Pointer click, Enter, and Space pin/reflow the shell; Escape dismisses an
  unpinned preview.
- Browser testing exposed two additional manifestations within the ratified
  scope: a cold-cancelled turn had no terminal receipt when no stream projection
  replayed, and keyboard activation did not pin. Both were repaired before the
  final browser pass.

## Verification

- `tests/agents/test_context.py`: 10 passed.
- DB acceptance on isolated `clue_r9_damascus_test_20260810`:
  - Home/bootstrap, D3 stream, D2 submission suites: 45 passed.
  - Thread projection and runtime wiring suites: 12 passed.
  - migration `head -> 39513bbba38a -> head` passed; Alembic reports one head.
- Frontend unit suite: 137 passed.
- `npm run lint`, `npx tsc --noEmit`, `npm run design-system:build`, and
  `npm run build -- --webpack` passed.
- Ruff over every changed Python/migration/test file and `git diff --check`
  passed.

## Browser evidence

Used an isolated runtime database `clue_r9_damascus_browser_20260810`, API on
port 8019, and isolated artifact/agent roots under `/private/tmp`.

- Queued B/C turns stored and returned distinct exact answers
  `R9_QUEUE_B_DONE` and `R9_QUEUE_C_DONE`; artifact digests and submission
  bodies matched their own prompts.
- Stopping turn `4138f261-8d4b-5ddf-be5b-32622b82c846` produced journal
  sequence `abandoned -> cancelled`; live and cold views showed `Stopped`, no
  `Thinking`, and no Stop button.
- With the worker paused, Home turn
  `9f0015f5-3677-5ab4-b8ea-a73414230d18` showed the exact accepted user text and
  `Queued` with no Stop. After restart it completed with
  `R9_HOME_RECONCILED`; the running suffix disappeared live and the sidebar
  catalog re-read without a browser reload.
- Sidebar hover opened an overlay without reflow; pointer click and Enter both
  pinned/reflowed it; Escape collapsed a preview.
- Final browser diagnostics contained no application errors. Clerk emitted
  only its expected development-key warnings.

## Environment notes

- The first isolated frontend attempt could not acquire Next's single dev lock
  while the user's frontend was running. Per explicit authorization, that
  frontend process was stopped and replaced by the isolated R9 frontend. The
  user's existing backend/fleet processes and source database were not killed
  or mutated because the isolated API/worker were healthy.
- PostgreSQL 17 server cloning required the Homebrew v17 `pg_dump`; the default
  v15 client was incompatible.
- The fleet workspace root needed mode 0700 before the isolated worker would
  start.
- A final Next restart bound explicitly to `127.0.0.1`; Clerk's same-origin
  middleware then targeted `localhost:3000`, which resolved through a different
  loopback binding and made requests hang. Restarting with Next's default
  localhost/all-interface binding fixed it. Final handoff is frontend port
  3000 -> isolated API port 8019; `/sign-in` returns 200 and unauthenticated
  `/api/v1/home` returns the expected 403 workspace refusal.
