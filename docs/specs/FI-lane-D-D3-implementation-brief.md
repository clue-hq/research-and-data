# Lane D slice D3 — implementation brief: complete streaming

**Charter (binding spec — most of this slice IS the charter):**
`docs/specs/FI-lane-D-production-chat-and-launch.md` §1.6, §3-P4, **§§3.1–3.6 in full** (event
vocabulary, token contract, part floors, turn controls, reconnect), slice D3, §5's streaming
suite. §6-D2 is founder-ratified: genuine token streaming, no post-hoc animation. Read
`_memory/2026-08-08-lane-d-b1join-d2-review-verdict.md` (the two-phase turn identity and the
follow-ups this slice inherits) and the ratified as-built contract section at the end of
`apps/frontend/docs/api-contracts/projects.md`.

## Mission

Make the turn visible while it runs: a turn-scoped durable event outbox, an authenticated SSE
endpoint, typed parts as projections of durable receipts, genuine incremental
`finalize_turn.user_message` token extraction with byte-equality reconciliation, reconnect/
rehydration, stop/retry turn controls — plus three inherited follow-ups (submissions-union
reads, stranded-dispatch self-heal, message-body hydration).

## Verified baseline (do not re-derive)

- D2 landed `ConversationTurnEngine` (single execution path, worker-composed once; trial uses
  the same builder), `agent_turn_submission` (queued turns visible only there until the worker
  creates `agent_turn`), and chained per-thread dispatch. `tool_choice="required"` puts all
  user-visible prose inside the streamed `finalize_turn.user_message` tool-call argument.
- B4's SSE machinery: the token store is reusable verbatim (nullable `run_id` = workspace-wide
  tokens), `Last-Event-ID`/`plan_replay`/`_sse_frame` reusable; the `run_event` outbox is NOT
  (`run_id NOT NULL`) — hence the new turn outbox.
- The per-turn LangChain callback `DurableAgentModelCallHandler` is already installed
  (`on_chat_model_start`/`on_llm_end` today; `on_llm_new_token`/`on_tool_start`/`on_tool_end`
  open). The gateway chat model's `_astream` exists, uncalled. Locate both before designing.
- Lane B contract §5.5: SSE auth = an authenticated request mints a short-lived, single-use,
  principal/workspace/turn-scoped stream token; no bearer token in a URL; expiry/replay cannot
  extend domain authority.

## Deliverables

1. **Outbox migration**: `agent_turn_event_stream` mirroring `run_event`'s proven shape but
   turn-scoped, carrying the §3.2 envelope fields (`event_id`, monotonic `sequence`,
   `generation_attempt_id`, `part_id`, `delta_index`, type, payload). Chain off
   `uv run alembic heads` at authoring time (currently `fba208917f89`); if the parallel D4
   migration forks heads, do NOT merge — the orchestrator owns the join. Retention: an explicit
   pruning policy behind a setting (document the replay window; §3.3.7's backpressure story —
   the outbox is the buffer).
2. **SSE endpoint + stream tokens** in a NEW module (`chat/stream.py` or sibling — you own it;
   do NOT add routes to `chat/router.py`, D4 owns that file this round): mint per §5.5 from an
   authenticated request (principal seam), attach by cursor, `Last-Event-ID` replay,
   `stream.hello`/`stream.reset` per §§3.2/3.6, at-least-once delivery deduped by `event_id`.
   Errors use the shared envelope; never raw provider exceptions.
3. **The extractor**: provider-neutral incremental `FinalizeTextDeltaExtractor` meeting §3.3(2)
   exactly — decodes only the `user_message` JSON string field across arbitrary chunk
   boundaries (escapes, `\uXXXX`, split multibyte UTF-8), emits only newly decoded bytes, never
   surrounding JSON/other arguments/provider reasoning. Pure, unit-testable, its own module.
4. **Emission wiring**: engine/worker hooks (your files: `conversation_turns.py`,
   `agent_turn_fleet_wiring.py`, the callback handler) emit turn lifecycle, part lifecycle from
   durable receipts (`agent_plan_operation`/`agent_tool_result` → `tool` parts; model rounds →
   safe `reasoning`/`agent_activity`; fleet/run projections → `task`; durable objects → `plan`/
   `sources`; `gate` parts arrive with D4's table — leave the projection seam, do not build the
   gate object), and token deltas via the extractor, micro-batched per §3.3(3). Every part
   snapshot honors the §3.4 floors and §3.2 replacement semantics. Parts are projections,
   never stores; part ids derive from their durable receipt identity.
5. **Reconciliation + attempt identity**: §3.3(4–6,8) — deltas persisted with attempt + index;
   on finalization `join(deltas)` must byte-equal the durable assistant message (mismatch →
   loud failure + `stream.reset` + canonical rehydration; never rewrites the turn); crash/retry
   closes the old attempt (`part.reset`/`turn.retrying`), new attempt = new part identity, no
   splicing.
6. **Turn controls** (§3.5): **stop** = a durable stop request the worker observes, cancelling
   only the active generation attempt (bounded cancellation latency; committed tool effects and
   detached runs untouched; terminal event emitted; partial attempt preserved for audit, never
   masquerading as a completed message). **Retry** = new attempt tied to `retry_of_turn_id`,
   never mutating the prior transcript. Endpoints live in your stream/controls module, not
   `router.py`.
7. **Inherited follow-ups**: (a) **submissions-union** — thread/turn read surfaces (your
   `chat/schemas.py`, `clue_projections/threads.py`) present queued submissions unioned with
   turn events, and `thread_status` derives `idle|running` from them (D4 will extend that one
   function with gate states — if you both touch it, rebase, don't revert). (b) **stranded-
   dispatch self-heal** — dispatch-on-attach (call `dispatch_next_thread_turn` when a stream
   attaches/cold read finds queued-but-undispatched submissions) plus a periodic sweep in the
   worker wiring; import the dispatcher, do not edit `agent_turn_submission.py` (D4's file).
   (c) **body hydration** — the ratified contract's D3 rehydration read: extend the paginated
   message list with an explicit opt-in (`?include=bodies`) that hydrates the page's artifact
   bodies server-side, workspace-scoped, bounded by the page size. Cold load = paginated
   messages (+bodies) + current projections, never SSE-history replay (§3.6).

## Acceptance criteria

Charter slice D3's AC verbatim, proven by the §5 streaming suite **in full** — every listed
case (first delta before finalization; escape/multibyte chunk splits; disconnect at every event
boundary + cursor replay; duplicated delivery; slow-client backpressure; stop; worker death
after partial text; `part.reset` + distinct retry; byte equality; Markdown split across tokens;
the negative leak assertions). Plus: submissions-union visible in reads; a stranded queued turn
heals on attach; `include=bodies` hydrates correctly and stays bounded. Gates: `make db-smoke`
(clean throwaway DB on `clue-pg-damascus`, localhost:**55040**, never 5432), `make lint`/
`make typecheck` clean on touched packages, suites green.

## Hard exclusions

Never touch: `chat/router.py`, `conversation_capture.py`, `agent_turn_submission.py`,
`turn_action.py`, `agent_registry_wiring.py`, `stage0_trial.py` (ALL D4's this round);
`platform/auth/**`, `frontend_read/**`, `apps/frontend/**` (P6/D5 owns the frontend),
`api-contracts/*.md`, FI-2 files, quarantined M8D modules. Composition roots: registration
calls only. No raw provider reasoning ever reaches the wire (§3.3's closing rule).

## Process

Test-first where practical; commit locally at checkpoints; never push; no AI attribution;
explicit-path staging only (a parallel D4 agent is in this worktree). STOP-and-report rather
than improvise on: the callback/streaming attachment point not supporting incremental tool-call
chunks; outbox write volume forcing a design change; stop requiring fleet-lease surgery.
Finish with a `_memory/` entry and a full final report (files, migration id, extractor design,
emission architecture, how byte-equality and attempt isolation are proven, retention policy,
test results, open items).
