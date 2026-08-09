# 2026-08-09 — Lane D D3: complete streaming (the turn outbox, the extractor, the SSE surface)

Brief: `docs/specs/FI-lane-D-D3-implementation-brief.md`. Charter §3-P4 + §§3.1–3.6, ratified
§6-D2. Branch `platform/platformlane-d-chat-launch`. Commits `c7d23ce9` (substrate), `c4298ef5`
(emission), `7a5805f9` (read surface), `3faf0a39` (tests). Session was interrupted by an API limit
and resumed; nothing was committed before the resume.

## What shipped

- **Migration `98a5ddafa21b`** (chains off D2's `fba208917f89`): `agent_turn_event_stream` (the
  turn-scoped outbox), `agent_turn_control_request` (stop/retry receipts), `stream_token.turn_id`.
- **`chat/turn_events.py`** — outbox writer/reader, the closed §3.2 vocabulary, `plan_turn_replay`,
  `prune_turn_events`, `next_generation_attempt`.
- **`chat/finalize_stream.py`** — the pure §3.3(2) extractor (no DB, no LangChain).
- **`chat/turn_parts.py`** — §3.4 payload floors + part-id derivation from durable receipts.
- **`chat/turn_stream.py`** — `TurnStreamEmitter` + `TurnStreamCallbackHandler`.
- **`chat/turn_controls.py`** — insert-once stop/retry rows; `stop_requested`.
- **`chat/stream.py`** — SSE attach, stop, retry, the union turn list, `…/messages/bodies`.
- **`chat/message_bodies.py`** — bounded server-side body hydration.
- Wiring: `agent_runtime_wiring`, `head_of_abm_wiring`, `conversation_turns`,
  `agent_turn_fleet_wiring`, `fleet_main` (two sweeps), `projections_app` (registration only),
  `stream_tokens` (turn-scoped mint/consume), `clue_projections/threads.py` (submissions-union),
  `chat/schemas.py` (`thread_status(running=…)`, hydrated `body`), settings (8 new keys).

## The three decisions worth remembering

1. **How the model is made to stream.** LangChain takes a chat model's `_astream` path when a
   callback handler attached to the run structurally satisfies its (runtime-checkable, private)
   `_StreamingCallbackHandler` protocol — i.e. defines `tap_output_aiter`/`tap_output_iter`.
   `TurnStreamCallbackHandler` defines both as pass-throughs. Verified empirically before building
   anything (`langchain-core 1.5.1`: `_should_stream` → `_agenerate_with_cache` iterates `_astream`
   and calls `on_llm_new_token(chunk.message.content, chunk=chunk)` per chunk, with
   `tool_call_chunks` carrying incremental `args`). **No gateway or shared-runtime change was
   needed**, and a turn with no stream attached keeps exactly its old path. If a LangChain upgrade
   changes the mechanism, `test_the_first_delta_is_durable_while_the_model_is_still_generating`
   fails loudly (the fake model's `_generate` asserts).
2. **`turn.accepted` is emitted by the worker, not the route.** The route lives in `chat/router.py`,
   which was D4's file this round, so the outbox writer could not be added there. The worker emits
   `turn.accepted` when it opens attempt 1. The queued window is covered by the submissions-union
   read instead of by the stream — coherent with §3.6 (cold load is messages + projections, never
   SSE history), but **worth revisiting**: emitting `turn.accepted` at the route is more faithful
   and is now a one-line change for whoever next owns that file.
3. **`?include=bodies` is served at its own path.** Same reason: the message-list route is in
   `router.py`. `GET …/messages/bodies` is the same page/cursor/element shape with bodies resolved.
   When `router.py` is free, its `include` parameter should delegate to
   `chat.message_bodies.hydrate_message_bodies` rather than growing a second implementation.

## Design notes

- The outbox is **DELETE-able by design** (append-only trigger on UPDATE only). It is a transport
  buffer; the turn journal, the finalization commit and `agent_thread_message` are the authority.
  Retention prunes **whole terminal turns** past `chat_turn_event_retention_s` (default 24h, and it
  should stay ≥ `sse_replay_horizon_s`); a live turn is never pruned at any age.
- Reconciliation reads the deltas **back out of the outbox** (not an in-memory buffer) and compares
  UTF-8 bytes, because the claim being proved is about what a consumer received.
- Attempt identity is derived from the outbox (`uuid5(turn_id, "generation-attempt:N")`), so a
  re-claimed task computes the same id for the same ordinal. Text part ids are
  `text:{attempt}:{round}:{call_index}` — attempt-scoped for §3.3(6), round-scoped because a
  repaired `finalize_turn` is a different continuation, not an extension.
- Retry = a **new turn** (`uuid5` of `retry-of:<turn>`), re-capturing the original bytes through
  `persist_user_turn` + `insert_submission`, with the link recorded on the insert-once control row.
  The prior transcript is never touched.
- Stop = a durable row the worker polls (`chat_turn_stop_poll_interval_s`, default 0.25s = the
  cancellation-latency bound). It finalizes the fleet task **DONE** with outcome `cancelled`, not
  FAILED — a FAILED task means "retried only by explicit requeue" and would misreport a deliberate
  stop as an error.

## Gates

- **db-smoke**: up→down→up on a clean throwaway DB `d3_smoke` (localhost:**55040**), run to **my
  head explicitly** (`alembic upgrade 98a5ddafa21b`) because heads are forked with D4's
  `3caa27516b81` — the orchestrator owns the join, and `make db-smoke` (which says `head`) cannot
  run until then. Green.
- `uv run mypy` clean (611 files). `ruff check` clean. `ruff format --check` clean on all 41 files
  this slice touches (the ~15 repo-wide unformatted files are pre-existing). `lint-imports` 25/0.
- Suites: `tests/api/test_lane_d3_turn_stream_db.py` (23) + `test_lane_d3_finalize_extractor.py`
  (32) green; the whole Lane D family (chat shell + D1 + D2 + B1-join + D3) = **106 green**;
  `tests/projections` + `tests/fleet` = 115 green.

## Trap hit — the forked heads break every DB test, for everyone

`tests/profiling/conftest.py::migrated_db` calls `command.upgrade(cfg, "head")`, which raises
`Multiple head revisions are present` while D3 and D4 are unmerged. Every DB-backed test in the
repo errors at setup as a result — not just Lane D's. My green runs above were taken while the
graph was momentarily resolvable; the final confirmation run was taken with D4's (committed)
migration file temporarily moved aside and restored immediately after. **After the orchestrator's
`alembic merge`, re-run `uv run pytest tests/api/test_lane_d3_*` to confirm on the joined graph.**
Also pre-existing-and-unrelated: `test_agent_registry_wiring::…c61_backend` (recorded in the D0/D1
verdict) and `test_account_deep_v0_fresh_process` (proved pre-existing by reverting this slice's
three shared files and re-running).

## Open items

1. **`turn.accepted` at the route** and **`?include=bodies` as a query parameter** — both blocked
   only by D4's ownership of `chat/router.py` this round (see decisions 2 and 3).
2. **The thread *listing* does not pass `running` yet.** `thread_wire(view, running=…)` and
   `threads_running(...)` exist and are tested, but the listing route is in `router.py`. One line
   there completes the sidebar badge.
3. **`task` / `plan` / `sources` / `gate` parts are projection seams with no production emitter.**
   `plan` and `gate` emit from the finalization's `domain_refs`/`open_gate_refs` today; `task` has
   `task_part_from_run` (states mapped from `entity_research_run`) but nothing calls it until a
   launch happens in a turn — D4's flow plus Lane C's status read-back are what light it up.
4. **Live tail is polling** (`chat_stream_poll_interval_s`). LISTEN/NOTIFY is the upgrade when poll
   cost matters — the same follow-up B4 recorded for the run stream.
5. **Micro-batching is opportunistic**, with no background flusher: the first delta of a part always
   flushes immediately and thereafter a batch closes on chars/interval *evaluated at the next
   token*. A long pause mid-generation therefore holds a partial batch until the next token or the
   end. Bounded and deliberate; a background flusher is the fix if it ever shows.
6. `emission_failures` is counted, logged and asserted empty in tests, but nothing surfaces it as a
   metric yet.
