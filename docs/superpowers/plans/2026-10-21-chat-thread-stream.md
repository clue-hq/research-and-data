# Live thread stream (CRM trial 1, finding F2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An open chat shows every turn in its thread live — including turns it did not start (the
`crm_connected` and `discovery_finished` wakes, a second tab, a teammate) — without a reload.

**Architecture:** A thread-level SSE stream (`GET …/threads/{thread_id}/events`) sends only the turn
lifecycle frames of any turn in the thread, read from the existing `agent_turn_event_stream` table by
`thread_id` (indexed by `agent_turn_event_stream_thread_cursor`). It uses the existing single-use
stream tokens with a new subject kind `agent_thread`, the same server-side poll reader as the
per-turn stream, and a keep-alive comment. The chat holds one thread stream while its tab is
visible; a frame for a turn it is not attached to makes it re-read the thread, and the existing
turns effect attaches the turn's own per-turn stream. The discovery 5 s timer and the CRM card's
re-read nudge are removed.

**Tech Stack:** FastAPI StreamingResponse (SSE), SQLAlchemy async / asyncpg, Alembic (raw SQL);
Next.js client hooks, Zod, `node:test` + JSDOM.

**Spec:** Finding F2 and the decision in `docs/superpowers/specs/crm-integration/2026-10-21-trial-1-findings.md`
and `docs/superpowers/specs/crm-integration/rulings.md` (R-10.1).

## Global Constraints

- Works across processes and machines: no in-memory pub/sub, no sticky sessions — events and tokens
  are read from Postgres by whichever API process serves the request.
- Option (a): the thread stream is open only while the tab is visible; hidden → closed, shown →
  reopened from its cursor.
- Thread stream poll interval `CLUE_CHAT_THREAD_STREAM_POLL_INTERVAL_S=1.0`; keep-alive
  `CLUE_CHAT_THREAD_STREAM_KEEPALIVE_S=15.0` — both in `.env.example` with these defaults (env parity
  rule), and in the local `.env`.
- Lifecycle frames only on the thread stream: `turn.accepted`, `turn.started`,
  `turn.awaiting_input`, `turn.completed`, `turn.failed`, `turn.cancelled`, `turn.retrying` (plus
  the stream's own `stream.hello` / `stream.reset`). Never parts, text or tool frames.
- Token: single-use, `subject_kind = 'agent_thread'`, `subject_id = thread_id`, TTL
  `chat_stream_token_ttl_s`; minted only after `_scope` proves the thread is this workspace's.
- Alembic: random-hash id, `down_revision = "3b800d603402"`, raw `op.execute`, named CHECK,
  reversible; `make db-smoke` green.
- DB tests only on the throwaway DB (`clue_nashville_crm_test`); never broad suites with keys.
- Frontend gate: `npm run lint` and `npm run build` in `apps/frontend` (stack down for the build).
- Commits: no AI attribution; never push.

## Review Focus

1. **A proxy or load balancer cuts an idle stream** → the keep-alive comment prevents it, and a cut
   connection reconnects with a fresh token from the last cursor, never replaying old frames.
   (Task 2 test `test_reconnect_after_drop_mints_a_fresh_token_and_resumes_from_the_cursor`.)
2. **A tab hidden longer than the replay horizon (24 h)** → reopening gets `stream.reset`, and the
   chat re-reads the thread instead of trusting its stale cursor. (Task 1
   `test_a_cursor_older_than_the_horizon_resets`; Task 3 `test_a_reset_rereads_the_thread`.)
3. **Switching threads quickly** → the old thread's stream is closed and its late frames are ignored;
   nothing attaches to a turn of a thread no longer shown. (Task 3
   `test_switching_threads_closes_the_old_stream`.)
4. **One turn produces several lifecycle frames** (accepted, started, retrying…) → one re-read per
   unknown turn, not one per frame. (Task 3 `test_one_reread_per_unknown_turn`.)
5. **A token minted for one thread, or a per-turn token, used on another thread's stream** → 401.
   (Task 1 `test_a_thread_token_opens_only_its_thread`.)

---

## File Structure

| File | Responsibility |
|---|---|
| `alembic/versions/<hash>_stream_token_agent_thread_subject.py` | widen `stream_token_subject_kind_known` with `'agent_thread'` |
| `platform/execution/clue_execution/stream_tokens.py` | `AGENT_THREAD_SUBJECT_KIND = "agent_thread"` |
| `platform/api/clue_api/chat/turn_events.py` | `list_turn_events(..., event_types=)` filter; `LIFECYCLE_EVENT_TYPES` |
| `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env` | the two thread-stream settings |
| `platform/api/clue_api/chat/stream.py` | the thread token route and the thread events route |
| `apps/frontend/src/features/projects/data/chat-sse.ts` (new) | the token → fetch → parse → reconnect loop, shared by both streams |
| `apps/frontend/src/features/projects/data/chat-stream.repository.ts` | per-turn stream, now built on `chat-sse.ts` |
| `apps/frontend/src/features/projects/data/chat-thread-stream.repository.ts` (new) | thread stream (HTTP + fixture no-op) |
| `apps/frontend/src/features/projects/data/chat-repositories.ts` | expose `threadStream` |
| `apps/frontend/src/features/projects/hooks/use-page-visible.ts` (new) | `document.visibilityState` as a hook |
| `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts` | open/close the thread stream; re-read on unknown turns; remove the discovery timer and `rereadThread` |
| `crm-connect-card.tsx`, `chat-message-part.tsx`, `conversation-content.tsx` | remove the `onConnected` nudge (its job moves to the thread stream) |

---

### Task 1: Backend — thread token and thread events route

**Files:**
- Create: `alembic/versions/<hash>_stream_token_agent_thread_subject.py`
- Modify: `platform/execution/clue_execution/stream_tokens.py`, `platform/api/clue_api/chat/turn_events.py`, `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env`, `platform/api/clue_api/chat/stream.py`
- Test: `tests/api/test_chat_thread_stream_db.py` (new; reuse the SSE reading helpers of `tests/api/test_lane_d3_turn_stream_db.py`, e.g. its `_open_stream` pattern), `tests/db/test_stream_token_agent_thread_migration.py`

**Interfaces:**
- Produces:
  - `AGENT_THREAD_SUBJECT_KIND = "agent_thread"` (exported from `clue_execution.stream_tokens`, re-exported by `clue_api.stream_tokens`).
  - `LIFECYCLE_EVENT_TYPES: frozenset[str]` in `clue_api.chat.turn_events` (the seven `turn.*` values above).
  - `list_turn_events(conn, *, workspace_id, turn_id=None, thread_id=None, after_event_id=0, limit=1000, event_types: Collection[str] | None = None)` — filters in SQL when given.
  - `Settings.chat_thread_stream_poll_interval_s: float = 1.0`, `Settings.chat_thread_stream_keepalive_s: float = 15.0`.
  - `POST /projects/{project_id}/threads/{thread_id}/stream_token` → `{"data": {"schema_version", "stream_token", "thread_id"}}` (requires `PERMISSION_THREAD_READ`; `_scope` without a turn; `mint_stream_token(subject_kind=AGENT_THREAD_SUBJECT_KIND, subject_id=thread_id, ttl_s=settings.chat_stream_token_ttl_s)`).
  - `GET /projects/{project_id}/threads/{thread_id}/events?stream_token=…[&last_event_id=N]` (+ `Last-Event-ID` header, header wins as in the turn route) → SSE:
    - consume with `consume_stream_token(subject_kind=AGENT_THREAD_SUBJECT_KIND, subject_id=thread_id)`; a per-turn token never matches, because that statement already requires `turn_id IS NULL` (keep it);
    - first frame `stream.hello` (same shape as the turn route's, with `thread_id`, no `turn_id`);
    - **no cursor** → start after the thread's current max `event_id` (no backlog);
    - **cursor** → `plan_turn_replay(turn_id=None, thread_id=…, last_event_id=cursor, horizon_s=settings.sse_replay_horizon_s)`; if `plan.reset`, send `stream.reset` (`reason: "cursor_older_than_horizon"`, `rehydrate: "transcript"`); then the backlog filtered to `LIFECYCLE_EVENT_TYPES`;
    - then forever: every `chat_thread_stream_poll_interval_s`, `list_turn_events(thread_id=…, after_event_id=last_seen, event_types=LIFECYCLE_EVENT_TYPES)` → frames (same `_event_frame` as the turn route); when nothing was sent for `chat_thread_stream_keepalive_s`, send the SSE comment `: keepalive\n\n`. The thread stream has no terminal event; it ends when the client disconnects.

- [ ] **Step 1: Failing tests** — in `tests/api/test_chat_thread_stream_db.py`:
  - `test_a_thread_token_opens_only_its_thread` — a token minted for thread A: 401 on thread B's events; second use 401; a per-turn token (`mint_turn_stream_token`) 401 on the thread route.
  - `test_only_lifecycle_frames_of_any_turn_in_the_thread_are_sent` — seed frames for two turns of thread A (`turn.accepted`, `part.created`, `text.delta`, `turn.completed`) and one turn of thread B; reading A with `last_event_id=0` yields exactly A's four `turn.*` frames in `event_id` order.
  - `test_no_cursor_starts_at_the_tail` — existing frames are not sent; a `turn.accepted` appended after open is.
  - `test_a_cursor_older_than_the_horizon_resets` — with `sse_replay_horizon_s` small and an old cursor, the first data frame after `stream.hello` is `stream.reset`.
  - `test_an_idle_stream_sends_keepalive_comments` — with `chat_thread_stream_keepalive_s=0.05`, a `: keepalive` comment arrives before any data.
  - `test_a_server_queued_wake_turn_is_announced` — `queue_crm_connected_turns(...)` then a `turn.accepted` frame for the wake turn (as the worker writes it) reaches the open thread stream.
  - In `tests/db/test_stream_token_agent_thread_migration.py`: `test_agent_thread_tokens_are_allowed_and_the_downgrade_removes_them` (insert an `agent_thread` token after upgrade; downgrade deletes `agent_thread` rows first, then restores the old CHECK).
- [ ] **Step 2:** Run them — FAIL (route 404, CHECK violation).
- [ ] **Step 3:** Implement the migration (`ALTER TABLE stream_token DROP CONSTRAINT stream_token_subject_kind_known` / re-add with `'project_run', 'design_run', 'agent_thread'`; downgrade deletes `subject_kind = 'agent_thread'` rows then restores the two-value CHECK), the constant, the `event_types` filter, the settings (+ `.env.example`, `.env`), and the two routes per the Interfaces block.
- [ ] **Step 4:** `CLUE_DATABASE_URL=<throwaway> uv run pytest tests/api/test_chat_thread_stream_db.py tests/db/test_stream_token_agent_thread_migration.py tests/api/test_lane_d3_turn_stream_db.py -q` → PASS; `make db-smoke` → green; `uv run alembic heads` → one head.
- [ ] **Step 5:** Commit `feat(chat): live thread stream of turn lifecycle events`.

---

### Task 2: Frontend — shared SSE reader and the thread stream repository

**Files:**
- Create: `apps/frontend/src/features/projects/data/chat-sse.ts`, `apps/frontend/src/features/projects/data/chat-thread-stream.repository.ts`, `apps/frontend/src/features/projects/data/chat-thread-stream.repository.test.ts`
- Modify: `apps/frontend/src/features/projects/data/chat-stream.repository.ts` (use `chat-sse.ts`; behaviour unchanged), `apps/frontend/src/features/projects/data/chat-repositories.ts`

**Interfaces:**
- Consumes: Task 1's two routes (through the same `/api/clue/api/v1` prefix the turn stream uses).
- Produces:
  ```ts
  // chat-sse.ts — the loop chat-stream.repository.ts has today, parameterised by its two URLs
  export function openTokenStream(options: {
    mintPath: string; eventsPath: string; lastEventId: number | null;
    onFrame(raw: unknown, eventId: number | null): "continue" | "stop";
    onError(error: unknown): void; clueFetch?: typeof fetch;
  }): ChatStreamHandle
  // chat-thread-stream.repository.ts
  export interface ChatThreadStreamAttachment {
    projectId: string; threadId: string; lastEventId: number | null;
    onTurnEvent(event: ChatStreamEvent): void;   // lifecycle frames only
    onReset(): void;                             // stream.reset — caller re-reads the thread
    onError?(error: unknown): void;              // reconnects exhausted
  }
  export interface ChatThreadStreamRepository { open(a: ChatThreadStreamAttachment): ChatStreamHandle }
  export function createHttpChatThreadStreamRepository(...): ChatThreadStreamRepository
  export function createFixtureChatThreadStreamRepository(): ChatThreadStreamRepository  // never emits
  ```
  `chat-repositories.ts` exposes it as `repositories.threadStream`.
- Rules: a fresh token per connect (single-use); reconnect with the same backoff as today
  (`[250, 500, 1000, 2000, 4000, 8000]`, then `onError`) from the last delivered `event_id`; SSE
  comment lines (`:` prefix) are ignored; frames whose `threadId` is not the attachment's are
  dropped.

- [ ] **Step 1: Failing tests** (`chat-thread-stream.repository.test.ts`, fake `fetch`):
  `test_lifecycle_frames_reach_on_turn_event`, `test_keepalive_comments_are_ignored`,
  `test_reconnect_after_drop_mints_a_fresh_token_and_resumes_from_the_cursor` (second events request
  carries `last_event_id` = last delivered id and a new token), `test_a_reset_calls_on_reset`,
  `test_frames_for_another_thread_are_dropped`.
- [ ] **Step 2:** `npx tsx --test src/features/projects/data/chat-thread-stream.repository.test.ts` → FAIL.
- [ ] **Step 3:** Extract `openTokenStream` from `createHttpChatStreamRepository` (no behaviour change for the turn stream), then build the thread repository on it, plus the fixture no-op and the `repositories.threadStream` field.
- [ ] **Step 4:** The new test file PASS, and the existing stream tests unchanged:
  `npx tsx --test src/features/projects/data/chat-repositories.test.ts src/features/projects/hooks/use-project-chat-controller-*.test.ts` → PASS; `npx eslint src/features/projects/data` clean.
- [ ] **Step 5:** Commit `feat(chat): thread stream repository on a shared SSE reader`.

---

### Task 3: Frontend — the chat holds the thread stream while visible; timers and nudges removed

**Files:**
- Create: `apps/frontend/src/features/projects/hooks/use-page-visible.ts`
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts`; remove the nudge from `crm-connect-card.tsx`, `chat-message-part.tsx`, `conversation-content.tsx`, `use-crm-connect.ts` (`connectedLive`)
- Test: `apps/frontend/src/features/projects/hooks/use-project-chat-controller-thread-stream.test.ts` (new, built on the discovery test's JSDOM + fake-`fetch` harness); `use-project-chat-controller-discovery.test.ts` (updated)

**Interfaces:**
- Consumes: `repositories.threadStream.open(...)` (Task 2).
- Produces: `usePageVisible(): boolean` (true when `document.visibilityState === "visible"`; listens to `visibilitychange`). The controller loses `rereadThread()` and the `DISCOVERY_HOLD_REREAD_MS` effect.
- Behaviour:
  - While `activeThreadId !== null && pageVisible`: open the thread stream with `lastEventId = threadCursor.current.get(activeThreadId) ?? null`; on every frame store its `event_id` as that thread's cursor.
  - `onTurnEvent`: if the turn is neither attached nor already re-read for (a `Set` of turn ids), add it and `void Promise.all([loadThreads(), loadConversation(threadId)])` — the existing turns effect then attaches it. A terminal frame on a thread with a held discovery also calls `loadThreads()` (the hold may have ended).
  - `onReset`: clear that thread's cursor and re-read the thread.
  - Close the stream on thread change, on hidden, and on unmount; ignore frames that arrive after close.
  - Remove: the discovery `setInterval` effect (every discovery end queues a `discovery_finished` wake turn and releases the hold when it completes — `discovery_wake.py` — so the thread stream's frames plus the existing terminal-frame `loadThreads()` cover it), `rereadThread`, and the CRM card's `onConnected` / `connectedLive` nudge. The card's own Connected flip (`BroadcastChannel` + its 3 s check while authorizing) stays.

- [ ] **Step 1: Failing tests** (`use-project-chat-controller-thread-stream.test.ts`):
  - `test_a_turn_the_server_started_attaches_without_a_reload` — the fake thread stream emits `turn.accepted` for an unknown turn; the controller re-reads and opens that turn's per-turn stream.
  - `test_one_reread_per_unknown_turn` — `turn.accepted`, `turn.started`, `turn.retrying` for one unknown turn → exactly one conversation re-read.
  - `test_a_hidden_tab_closes_the_stream_and_reopens_from_its_cursor` — `visibilitychange` to hidden closes it; back to visible reopens with `last_event_id` = last seen.
  - `test_switching_threads_closes_the_old_stream` — late frames of the old thread trigger nothing.
  - `test_a_reset_rereads_the_thread`.
  - In the discovery test: `test_the_hold_ends_when_the_wake_turn_completes` replaces the timer-based expectation (no `setInterval` re-reads).
- [ ] **Step 2:** `npx tsx --test src/features/projects/hooks/use-project-chat-controller-thread-stream.test.ts src/features/projects/hooks/use-project-chat-controller-discovery.test.ts` → FAIL.
- [ ] **Step 3:** Implement `usePageVisible`, the controller effect and handlers, and the removals.
- [ ] **Step 4:** All `src/features/projects/hooks/*.test.ts` and `src/features/integrations/**/*.test.ts` PASS; `npm run lint` clean; with the stack down, `npm run design-system:build && npm run build` green.
- [ ] **Step 5:** Commit `feat(chat): open chats follow turns they did not start; drop the discovery timer`.

---

### Task 4: Live check on the local stack and the record

**Files:** Modify `docs/superpowers/specs/crm-integration/2026-10-21-trial-1-findings.md` (F2 → fixed, with evidence), `docs/superpowers/specs/crm-integration/status.md`, `_memory/2026-10-20-crm-integration-phase1.md`.

- [ ] **Step 1:** `alembic upgrade head` on the stack DB; restart the stack (`./scripts/dev_stack_nashville.sh restart-api`, `restart-workers`, frontend picks up changes).
- [ ] **Step 2:** In the in-app browser, open the trial chat in **two tabs**. Send a message in tab 1 → it appears and streams live in tab 2 without reload.
- [ ] **Step 3:** Server-started turn: with tab 2 visible, queue a `crm_connected` wake for the chat (reconnect through the card, or `queue_crm_connected_turns` from a one-off script) → the turn appears and streams in the open tab within ~2 s, no reload.
- [ ] **Step 4:** Hide tab 2 (switch tabs), confirm in the API log that its thread stream closed; return to it → it reopens from its cursor and shows anything that ran meanwhile.
- [ ] **Step 5:** Record results (and any new findings) in the trial findings doc, status and memory; commit `Docs: CRM trial 1 — F2 fixed (live thread stream)`.
