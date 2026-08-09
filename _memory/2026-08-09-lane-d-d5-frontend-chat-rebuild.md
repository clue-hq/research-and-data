# 2026-08-09 — FI Lane D D5: the frontend chat rebuild (frontend-only slice)

Branch: `platform/frontend-integration` worktree `damascus` (Lane D lane).
Brief: `docs/specs/FI-lane-D-D5-implementation-brief.md`. Charter: `FI-lane-D-production-chat-and-launch.md` §3-P6, §3.1–§3.6.
Scope respected: `apps/frontend/**` only. **No backend Python touched.**

## What landed (2 commits)

1. Model layer (`src/features/projects/model/chat-*.ts`, `research-task.ts`,
   `streaming-markdown.ts`) — the amended Zod contracts, the pure transcript
   reducer, the gate-card state machine, task aggregation, incremental Markdown.
2. Data layer (`src/features/projects/data/chat-*.ts`) — threads / messages /
   turns / gates / **stream** repositories, each with a fixture and an HTTP
   adapter, composed by `chat-repositories.ts`.
3. Presentation (`components/chat-*.tsx` + `components/ai-elements/message-response.tsx`)
   — the §3.1 adapter map, the gate card, the research-execution task.
4. Tear-out — `build-project-messages.ts` and every consumer deleted; the
   hardcoded plan-approval card gone; `previewTimeline` / `reasoningTrace` /
   `conversationCopy` / `generationCopy` / `generationSteps` /
   `conversationActivity` / `threads` removed from the validated project
   payload; every phase timer deleted; the sidebar reads its repository.

## Env flag

**`CLUE_PROJECTS_API_BASE_URL`** — per-flow, matching `CLUE_ACCOUNTS_API_BASE_URL`.
Unset ⇒ fixtures. It is an **origin-relative path prefix** (normally `/api/clue`,
the authenticated BFF mount), and a non-relative value is refused at
configuration: the chat flow is browser-driven and must never call FastAPI
cross-origin. Resolved server-side in `(protected)/layout.tsx` via
`resolveChatTransport()` and handed to the browser as a serializable prop
through `ProjectsTransportProvider` — no component reads an environment variable.

## Contract deviations found while integrating (FOR FOUNDER REVIEW — not recorded in `api-contracts/projects.md`)

Blocking the D5 AC against a real backend:

- **B1. No HTTP route serves `thread_gates`.** The projection exists and is
  complete (`clue_projections/gates.py`), but the chat surface has no gates
  endpoint. Consequence: no durable gate payload reaches the client.
- **B2. The emitted `gate` part carries only `gate_ref`/`gate_kind`/`state`.**
  `conversation_turns.py::_project_turn_close` calls
  `emit_gate_part(ref=…, gate_kind=ref.object_type)` and passes nothing else,
  though `GatePart` already models `amount_cents`, `currency`,
  `expected_subject_sha256`, `permitted_decisions`, `title`… **`gate_kind` is
  therefore literally `"agent_gate"`, never `"directive_confirmation"`.**
  With B1, a gate can be *shown* and cannot be *answered*: `gate_response`
  requires `expected_subject_sha256` + `expected_estimated_cost_cents` and the
  server refuses a mismatch. The frontend renders an explicit `unavailable`
  card with disabled controls and the reason. Smallest fix: populate the part
  from `get_gate` at the emit site (B2 alone would close it).

Non-blocking but shaping the implementation:

- **D1. Nothing emits `task` parts.** `TurnStreamEmitter.emit_task_part` has
  zero production callers, so the Figma research-execution task never appears
  on a real wire. Modelled, rendered and tested; unreachable today.
- **D2. Nothing emits `sources` parts** (`emit_sources_part`: zero callers).
- **D3. `PartKind.ACTION` has no payload model and no emitter.** Deliberately
  not modelled here rather than inventing a shape.
- **D4. No part-projection read for cold load.** Charter §3.6 says cold load is
  "paginated messages + current projections", but the only source of tool /
  activity / task / gate parts is the per-turn SSE backlog. The client therefore
  attaches from cursor 0 for the last 3 turns (bounded), instead of from the
  `last_event_id` the turns list returns.
- **D5. No thread-level event read.** `list_turn_events` supports `thread_id`
  and `plan_turn_replay` accepts it, but the HTTP route is per-turn only, and
  the stream token is turn-scoped ⇒ one token mint + one connection per turn.
- **D6. No project catalog read.** `GET /api/v1/projects/sidebar`, `GET
  /api/v1/projects/:id`, `POST /projects`, artifacts and runs are unimplemented
  (as-built item 9). The sidebar is a **hybrid**: fixture project rows, real
  thread lists. Project rename in the sidebar dialog is local-only and says so.
- **D7. `review` is unemittable.** The frontend's proposed 5-value status enum
  contained `review` (no backend surface produces it) and lacked `archived`
  (the backend does produce it). Replaced by the pinned precedence vocabulary
  `archived > approval > needs-input > running > idle`.
- **D8. The chat wire is snake_case**, unlike the camelCase `/frontend/v1`
  accounts surface. Handled by wire-schema → camelCase transforms.
- **D9. Two frames carry no `event_id`/`sequence`** — `stream.hello` and the
  connect-time `stream.reset` (`_sse_frame` omits `id:`). The event schema
  accepts both as absent rather than forcing them into the durable shape.
- **D10. `EventSource` is structurally unusable**: the stream token is
  single-use and consumed at open, so `EventSource`'s automatic reconnect would
  always 401. The stream repository owns the loop (fresh token per attach,
  `Last-Event-ID` header, bounded backoff).
- **D11. `ThreadWire.status` is an open string on the wire** (`thread_status()`
  returns `str`); the frontend enum is closed. A new backend value would 422 at
  the repository boundary rather than render.
- **D12. A gate response's captured message is canonical JSON.** The durable
  user message for a gate turn is the `gate_response_message(...)` JSON, so a
  faithful transcript would render that JSON as the user's message. The client
  adds no optimistic user bubble for a gate answer; the card's recorded decision
  is the visible record instead.
- **D13. `GateView.max_spend_cents` is `numeric(20,4)`** ⇒ a JSON *string*,
  while `GatePart.amount_cents` is an `int`. Both accepted.

## Stream-adapter design (the load-bearing part)

`data/chat-stream.repository.ts` (transport) + `model/chat-transcript.ts` (pure
reducer) + `model/chat-events.ts` (envelope schema + incremental SSE reader).

- attach: `POST …/stream_token` → `GET …/events?stream_token=…` with
  `Last-Event-ID`; fresh token per attach; abortable handle.
- reconnect: bounded backoff (6 attempts, 250 ms→8 s), reset on a successful
  attach, from the highest cursor actually **applied**; 401/403/404 stop.
- dedup: by `event_id` in the reducer (a duplicate returns the *same* state
  object), so cross-connection duplicates behave like in-connection ones.
- replacement: `part.created|updated|completed|failed` carry a full snapshot;
  replace by `partId`, guarded by `revision` (never backwards).
- text: `text.start` opens, `text.delta` stored **by `delta_index`** and joined
  in index order (duplicates idempotent, out-of-order safe), `text.end` closes.
- attempt isolation: `part.reset` voids only that part; a retry's new part ids
  never splice; a cancelled/failed attempt keeps its partial text marked
  `failed` (never `streaming`).
- `stream.reset`: drop the turn's projections, raise `rehydrate`, **and reset
  the cursor to 0** (the connect-time reset restarts the backlog from zero — a
  reader that kept its cursor would skip what it was told to re-read).
- composition: a turn's prose renders from its streamed text part while one
  exists, and from the durable body otherwise (§3.3(5) makes them byte-equal),
  so neither doubles the other and a reset falls back cleanly.
- **one attach per turn per thread visit** — the reload that follows a closed
  stream changes `turns` by identity; without this the effect re-attached
  forever (found in the browser; fixed).

## Verification

- `npm run design-system:build && npm run lint && npm run build` — green.
- `npm test` — **90/90** (was 33 at baseline). New suites: stream/transcript
  reducer (16), schema round-trips, gate-card state machine, task aggregation,
  streaming Markdown (incl. "no prefix of a growing document ever leaks a
  delimiter"), repository/transport seam.
- **Browser pass — FIXTURE PATH ONLY, real Chromium at 1680×945**, dev server
  on :3111. Verified: streamed Markdown (bold + list, no raw syntax), tool
  disclosure with its seven-state copy, agent-activity disclosure, gate card
  showing "Confirm research launch — up to $240.00", **Approve round-trip** →
  card becomes "Approved — up to $240.00 / 1 research run launched" with
  controls gone and a launch-narration **task** part ("Partial results
  preserved — 2 of 2 accounts settled") in the next turn; sources disclosure;
  composer usable during work with a visible "Working — new messages will queue
  behind this turn." + Stop; queued turn visible; thread switching replaces the
  transcript and shows the `unavailable` gate state with disabled controls;
  sidebar rendered through its repository. **Zero console errors.**

## HANDED BACK — the flag-on end-to-end browser pass is NOT runnable here

Measured, not assumed:
- no `.env` at the repo root ⇒ no `CLUE_DATABASE_URL`, no model key (the fleet
  worker cannot execute a turn, so nothing would stream);
- no Clerk credentials ⇒ `CLUE_AUTH_ENABLED` cannot be turned on
  (`requireAuthenticationConfiguration()` throws), and with it off the BFF
  refuses every proxied request. Verified:
  `curl localhost:3111/api/clue/api/v1/projects/p/threads` →
  `503 {"error":{"code":"AUTHENTICATION_NOT_CONFIGURED"}}`.

The manual flag-on pass (projections app + fleet worker + dev auth + model key)
is an explicit open item for the orchestrator. Nothing was simulated.

## Open items

1. The flag-on browser pass above.
2. B1/B2 (the gate payload) — the only thing standing between the shipped card
   and a real approve round-trip.
3. Verify the Next BFF streams `text/event-stream` without buffering under
   `next start` (untestable without a backend).
4. D1/D2 — wire `emit_task_part` / `emit_sources_part` so the research task and
   sources appear on a real stream.
5. D4/D5 — a part-projection or thread-level replay read would let cold load
   stop re-attaching per turn.
6. Home submission still navigates with `?prompt=`; it prefills the composer
   rather than manufacturing a first turn. Real project creation is phase-2
   (`POST /projects` unimplemented).
