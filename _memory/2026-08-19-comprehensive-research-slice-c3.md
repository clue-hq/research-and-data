# 2026-08-19 — Comprehensive research Slice C3: the card polls the durable read

**Branch:** `platform/comprehensive-account-contact-research-v1`
**Base:** C2 commit `8c5d2909`
**Scope:** Task C3 only (frontend poller + transcript merge). C4/C5 not started.

## Landed (one commit)

- `apps/frontend/.../data/chat-research-tasks.repository.ts` — `list({projectId, threadId})` over
  `GET /projects/{p}/threads/{t}/research-tasks`; 404 (route absent on an older deployment) is an
  empty poll, never an error; fixture adapter returns `[]` so the demo stream stays authoritative
  and a fixture poll can never regress a card.
- `model/chat-parts.ts` — factored `toTaskPart` (shared by the stream union transform),
  `PolledResearchTask` domain type, `ResearchTaskListResponseSchema` (task-part wire + required
  `revision` + `field_progress` + `source_turn_id`).
- `model/research-task.ts` — `withPolledResearchTasks(messages, polled)`: pure,
  reference-preserving merge by `(runRef.objectId, revision)`. Fresher poll advances a card in
  place; stale poll never regresses; a run shown nowhere is re-materialized on its launch turn's
  assistant message (cold-load fix past `REHYDRATED_TURNS`); a task naming no visible turn is
  dropped, not misplaced.
- `hooks/use-research-task-poller.ts` — email-lookup poll pattern: `POLL_DELAY_MS = 3_000`,
  re-armed `window.setTimeout` after each completed read while any task is non-terminal
  (ACTIVE/BLOCKED), cleared on unmount, 401 → `/sign-in?reason=session_expired`; non-401 failure
  keeps the last snapshot and stops until the next wake. `streamTaskWakeSignature` (task part ids
  only, revisions ignored) is the wake key.
- `hooks/use-project-chat-controller.ts` — poller mounted; enabled once the conversation loaded and
  no access/route refusal; transcript memo wraps `composeTranscript` with
  `withPolledResearchTasks`. `chat-research-task.tsx` untouched — no visual change.

## Two implementation-level adaptations to the authored plan

- **Wire gained `source_turn_id` (backend, additive, nullable).** The C2 wire carried no turn
  identity, but cold-load re-materialization must place a card on the message of the turn that
  launched the run. The projection already holds the durable `turn-action:` receipt
  (`ThreadResearchTaskView.task.source_action_ref`); `research_task_wire` now derives the turn id
  through the canonical `parse_turn_action_ref` (never a hand parse; unparseable → honest `None`,
  and the frontend then merges by run but never places). Extended the existing C2 counts test with
  the round-trip assertion (red-proved: `KeyError: 'source_turn_id'` before the field existed).
- **`field_progress` is parsed but unrendered.** The card has no designed slot for it
  (dummy-frontend visual-parity rule, plan decision 5); it rides `PolledResearchTask` awaiting a
  designed home. The plan's "parse the wire" step is satisfied without inventing UI.

## Deliberate semantics worth knowing

- Poll revision (job-event `event_seq` high-water mark) always outranks the stream part's local
  emission counter (1, 2, …) — **by design** (C2 spec wording: "a fresher poll always outranks the
  turn-close snapshot"). A poll fetched just before a turn-close snapshot can therefore briefly
  outrank fresher stream counts; the wake-triggered refetch and the 3s cadence self-heal within one
  poll. The two revision spaces are not comparable in general; the durable read is the authority.
- Polling stops when every task settles and when a thread has no launches; a later launch resumes
  it via the stream `part.created` wake. A launch committed mid-turn becomes pollable at turn close
  (when its part first streams), matching the plan.

## Verification

- TDD red proofs: backend `KeyError: 'source_turn_id'`; frontend `withPolledResearchTasks is not a
  function`; poller module missing — each then implemented to green.
- Frontend: `npm test` 365/365 (16 research-task, 4 poller); `npm run design-system:build`,
  `npm run lint`, `npm run build` all green.
- Backend: C2 suite 8/8 + sibling D5 = 20/20 on the dedicated `clue_slicec_bujumbura` DB (shared
  `.env` browser DB untouched); full `make lint`, `make typecheck` (728 modules), `lint-imports`
  26/26.
- No separate reviewer pass was run this session (the implementing agent is Fable); flag for the
  Slice C exit gate's founder browser test.

## C4 addendum (same session, commit `902d4342`)

The settle-advance acceptance proof landed as one appended test:
`test_the_task_read_advances_truthfully_at_every_job_transition`. A `_transition` helper moves one
job one lifecycle step the way the fleet does — row update honoring the lease/terminal CHECK
shapes, the matching ledger event, then the fleet's own (private, deliberately borrowed)
`_refresh_run_state`. Nine steps across three jobs ending completed / needs_review / failed; after
each, the C2 route is polled and the test asserts exact counts + task state, the monotone laws,
`sum(counts) == 3`, a strictly rising revision, and the pinned defect verbatim (never
"Queued — 0 of N" once any job left queued; final state is `partial` per `_terminal_task_state`).
Mutation-proofed: removing the ledger append fails the revision assertion (`379 > 379`).
Suite 9/9 on `clue_slicec_bujumbura`; full `make lint` + `make typecheck` green (one `cast` needed
for the poll helper's json destructure).

## C5 addendum (same session, commit `9cfe7d5c`) — newest-first pagination

The founder-ratified chat-loading fix. Step-1 inventory (recorded before changing anything): the
route already accepted `cursor` and already returned `meta.next_cursor` — the frontend parsed and
ignored it; the only oldest-first consumers were the projection's own tests, so the default
flipped with no compatibility mode.

- **Projection** (`thread_messages`): newest page first (`sequence < cursor … ORDER BY sequence
  DESC LIMIT n+1`, reversed per page to ascending display order); `next_cursor` is a
  before-cursor = the page's oldest sequence. Under-one-page threads byte-identical to the old
  read. Route + wire unchanged. Red proof: the 120-message HTTP walk failed `[1..50] != [71..120]`
  before the flip; after, pages walk 71-120 / 21-70 / 1-20 to exact exhaustion.
- **Model**: `mergeThreadMessages` (chat-transcript.ts) — union by message id, sorted by the
  gap-free `sequence`, reference-preserving; handles both the scrollback prepend and a reload's
  newest page landing over older loaded history. `composeTranscript`'s identity guards remain the
  optimistic/streamed dedupe seam (4 new model tests, red-proved `is not a function` first).
- **Controller**: newest-page load seeds `olderCursor` once per mount (thread change = remount);
  `loadOlderMessages`/`hasOlderMessages` walk backward, in-flight-guarded; `loadConversation` now
  MERGES instead of replacing (consequence: an erased message would persist client-side until
  remount — noted, acceptable).
- **Scrollback**: `useTranscriptAutoScroll` gains a top sentinel (48px) + anchor-based restore —
  the anchor is the oldest message's `data-message-id` element (attribute added to the existing
  article, zero visual change), so restoration is immune to bottom growth during the fetch; the
  restore layout-effect keeps waiting until the anchor actually moves. One eslint rule hit
  (`react-hooks/refs`: no ref writes during render) — fixed by mirroring props into the ref
  inside a layout effect.
- **Verification**: frontend 369/369 + lint + build; backend 74/74 across the six touched DB
  suites; full repo ruff/mypy/lint-imports green. Two seeding gotchas for future agents: the
  message FK is composite `(turn_id, workspace_id, thread_id)` (each thread needs its own turn),
  and `tests/projections/test_thread_shell_db.py`'s `_turn`/`_message` helpers are importable
  from API-level tests.

## Slice C status

C1–C5 all landed. Remaining: the Slice C exit gate's founder browser test — launch a
multi-account run, watch the card advance to settled with no interaction; reload mid-run and see
the same live card; reload a >50-message thread and see the newest messages with older history
loading on upward scroll. The Slice
C exit gate's founder browser test should confirm: card advances to settled with no interaction;
reload mid-run shows the same live card; a card older than the rehydration window reappears on its
own message.
