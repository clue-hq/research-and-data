# Phase 2b — Show-work streaming: async turns + persistent SSE

The one structural backend change of Phase 2. The turn was synchronous
(`POST /agent/turn-preview` ran the whole quality loop inside the request); 2b
makes it async and observable, streaming progress to a Moda-style plan
checklist that survives a tab reload.

## The store decision — SETTLED as SQLite (not Redis/Postgres)

The plan locked "SSE with a PERSISTENT event store — Redis or Postgres, NOT
filesystem JSON" and left the Redis-vs-Postgres pick to be "decided against
deployment reality when 2b starts." The deployment reality decides it:

- The API is a **single-process `uvicorn`** (no `--workers` in dev-setup.sh
  or setup_local_dev.sh).
- The document store is **SQLite** (`apps/api/lumen-api.sqlite3`); there is
  **no Redis, no Postgres, no SQLAlchemy** in requirements — just FastAPI +
  uvicorn.

Standing up Redis (a broker for pub/sub fan-out) buys nothing a
single-process app can use, and migrating to Postgres is out of 2b's scope.
**SQLite** satisfies the actual locked constraint — persistent, survives a
reload and a process restart, and is *not* filesystem JSON — while adding
zero infra, living in the same transactional store as the documents, and
doing `Last-Event-ID` replay trivially (a `WHERE seq > ?` read). The event
store sits behind the `Repository` seam, so if deployment ever goes
multi-process, swapping to Redis/Postgres is localized.

## Backend (`41a899f`)

- **migration 006** — `agent_runs` (run status + final result JSON) and
  `run_events` (one row per progress event, monotonic per-run `seq`, the SSE
  event id). Mirrors the `operation_log` / `edit_envelopes` per-key `MAX+1`
  sequencing. Race-free because only the run's own thread writes its events.
- **`Repository`** gains `create_run`, `append_run_event`, `set_run_result`,
  `get_run`, `list_run_events(after_seq)`.
- **`POST /agent/turns`** starts the run in a daemon thread and returns
  `{run_id}` immediately. The thread opens its own connection, wires the
  loop's `event_sink` to `append_run_event`, and writes the final result +
  a terminal marker (`result`/`error`) on completion. Honors the
  `app.state.agent_turn_runner` test override.
- **`GET /agent/runs/{id}/events`** — SSE (`text/event-stream`). Reads the
  resume point from `Last-Event-ID` (or `?after=`), replays events after it,
  then polls the store live (~1s) and yields `progress` frames until the
  terminal marker, which it emits as a `done` frame carrying the stored
  result, then closes. `id:` = seq for replay.
- **`GET /agent/runs/{id}`** — JSON snapshot `{status, events, result}`.
- **`POST /agent/turn-preview`** stays a synchronous wrapper — tests, CLI,
  and fixtures unchanged.
- **The loop hook is one integration point.** `tools.record()` already
  funnels every progress event (`run_started`, `dsl_compiled`,
  `preflight_completed`, `critique_result`, …), so `LumenDesignTools` gained
  an optional `event_sink` (threaded through `create_provider_quality_loop`)
  that `record()` also calls, best-effort (a sink failure never aborts the
  run). agent_runtime never imports the API/DB layer — the sink is a plain
  `Callable[[str, dict], None]`.
- **`connect()` gains `PRAGMA busy_timeout=5000`** so the background writer
  and the SSE reader never hit an instant "database is locked". Strictly
  safer, no semantic change.

## Frontend (`320628d`)

- **`createStreamingAgentRunner` + `subscribeToAgentRun`** (agentRunner.ts):
  POST `/agent/turns` → run_id → `EventSource` on the SSE endpoint. Live
  events go to `request.onEvent`; the promise resolves with the same
  `EditorAgentResult` on the terminal `done` frame, so Accept/Reject is
  untouched. EventSource is injected (`EventSourceLike` factory) so jsdom
  drives it with a fake and the browser API is never stored bare
  (frontend-practices #8). The synthetic `run_started` frame carries the
  run_id for resume. `createApiAgentRunner` (sync) stays for back-compat.
- **`engine/agentChecklist`** — pure derivation of the granular per-iteration
  events into six forward-only stages (plan → author → apply → preflight →
  review → finalize) so a repair iteration never un-ticks an earlier stage,
  plus friendly "Show work" labels. Panel stays a renderer
  (frontend-practices #2).
- **`useAgentTurn`** owns `runEvents` + the checklist. `handleTurnResult` is
  extracted and shared by the live path and the **reload-resume** path: the
  in-flight run id is stashed in `sessionStorage`; on mount, if one is
  present, the hook rejoins the SSE stream (the run keeps executing
  server-side) — replaying the checklist and then either resuming live ticks
  or settling immediately from the stored result. Refs keep the mount-only
  effect calling the latest handlers.
- **`AgentChatPanel`** renders the checklist (live spinner ticks, collapsing
  behind "Show work" once settled). CSS reuses the existing agent palette —
  no new token values (frontend-practices #3).

## Gates

- API suite green, +4 async-turn/SSE tests (lifecycle, failed-status,
  404, and SSE framing incl. `Last-Event-ID` replay). agent_runtime
  tools/providers tests green.
- Editor suite **384 / 385** (+7 new: 5 checklist derivation, 2 streaming
  runner/subscribe); the 1 failure is the known pre-existing `EditorCanvas`
  env-split case. tsc at baseline. (Note: a stale rolldown transform cache
  produced spurious cross-file "Unexpected JSX expression" parse errors mid-
  session; `rm -rf node_modules/.vite` cleared it — not a code issue.)
- Browser e2e (live ticks + reconnect replay): see below.

## Browser e2e evidence (PASS, both primary gates)

Real stack (API :8002, editor :3002, both at `320628d`, handshake OK),
driven via Playwright MCP by a claude-opus-4.8 agent. Run
`run_46ab0452…`, 41 events, settled `failed` (known max-iterations
quality flakiness — orthogonal to 2b). Zero console errors throughout.
Screenshots in `browser-e2e/`.

- **Live checklist (primary gate):** after a poster-generation prompt the
  `.agent-run-checklist` appeared with "Planning the design" active +
  spinner, canvas designing banner up; ~18s later it had advanced to 5
  steps (4 done / 1 active). Server events grew 2 → 11 while running
  (`2b-e2e-1-checklist-early.png`, `2b-e2e-2-checklist-progress.png`).
- **Reload-reconnect (primary gate):** a full page reload mid-run rebuilt
  the checklist from the replayed stream, banner up again, composer in
  queue mode, `sessionStorage['lumen.activeAgentRun']` carried the SAME
  run id, and server events kept climbing 11 → 23 → 26 post-reload — the
  run kept executing server-side and the tab rejoined the live stream
  (`2b-e2e-3-resumed-after-reload.png`).
- **HTTP corroboration:** snapshot events progressed 2→11→23→26→41;
  `Last-Event-ID: 1` replay returned frames from `id: 2` (seq 1 skipped).
- **Terminal + Show work:** run settled `failed` → banner gone, active-run
  cleared, all six stages `done`, honest repair-budget system message, no
  review bar (correct for failed). "Show work" expanded to 39 granular
  event lines (`2b-e2e-4-settled.png`, `2b-e2e-5-show-work.png`).

The in-browser **proposed → Accept** branch was not hit (this run failed on
quality flakiness — the same non-determinism seen in the 2a/2a.5 gates). It
is covered instead by: the streaming-runner unit test (resolves a proposed
result from the `done` frame), the fact that `handleTurnResult` is shared
and behavior-preserving vs the pre-2b inline body, and 2a.5's browser proof
of the proposal→Accept→persist path (unchanged by 2b).
