# 2026-08-09 — FI Lane D **D5-close**: the gates read route + the rich gate/task parts

Branch: `platform/frontend-integration` worktree `damascus`. Backend only —
`apps/frontend/**` untouched. No Alembic migration (every row already exists).
Charter: `docs/specs/FI-lane-D-production-chat-and-launch.md` §3.4 (part payload
floors). Input: the D5 deviation list in
`_memory/2026-08-09-lane-d-d5-frontend-chat-rebuild.md` (B1, B2, D1, D2, D9).

Everything closed here was **unimplemented already-ratified contract**, not new
design: the §3.4 floors existed in `GatePart`/`TaskPart` and the `thread_gates`
projection was complete; nothing filled them or served them.

## What landed

### 1. Rich gate part (D5 deviation B2 — the blocker)

`TurnStreamEmitter.emit_gate_parts(refs=…)` replaces the per-ref
`emit_gate_part(ref=…, gate_kind=ref.object_type)` call at
`conversation_turns.py::_project_turn_close`. It reads
`clue_projections.thread_gates` **once** per finalization (no duplicated join —
D4 owns that query) and, for every `open_gate_ref` that names a durable
`agent_gate` row, emits the full floor:

| §3.4 floor | emitted as |
|---|---|
| gate_id | `gate_ref.object_id` + `part_id = gate:agent_gate:<gate_id>` |
| kind | `gate_kind` = the **row's** kind (`directive_confirmation`), never `agent_gate` |
| state | `requested` when open, `responded` when answered (derived from the answer row) |
| subject refs + expected revision/hash | `subject_refs=[{workspace_id, object_type:"research_directive", object_id, version, sha256}]` + `expected_subject_sha256` |
| `{amount_cents, currency}` | `_cent_ceiling(max_spend_cents)` + `currency` |
| addressee | `addressee_user_id` |
| permitted decisions | `agent_gate.DECISIONS` (full vocabulary, open or closed) |
| answered decision/actor/time | `decision` / `answered_by_user_id` / `answered_at` |
| closed gate stays in history | emitted as `part.completed`, not deleted |

**Two deliberate omissions, reported not hidden.** `title`/`summary` stay unset —
§3.1/§3.4's standing rule is that the backend sends semantic state and the
adapter chooses words, and the shipped card already falls back to its own
`gateTitle(kind)`. `amount_cents` is the **ceiling** of the `numeric(20,4)`
column (a cap must never render smaller than it is); the authoritative amount an
approval echoes back is the durable `max_spend_cents` from the gates route, which
is what the frontend's `gateCardModel` prefers.

A ref with no matching row falls back to the thin `emit_gate_part` shape
(`open_gate_refs` is an open `DomainObjectRef` vocabulary), and a projection read
failure is counted in `emission_failures`, never raised — §3-P4 holds.

### 2. The gates read route (D5 deviation B1)

`GET /api/v1/projects/{project_id}/threads/{thread_id}/gates` on the chat router
(behind `settings.chat_enabled` + the same principal dependency; re-checks
`thread.read`). Returns `{"data": [GateWire, …]}`, one wire member per
`GateView` member, snake_case, **unpaginated** (a thread's gates are bounded by
the directives its conversation drafted; the message/thread reads that do grow
keep their cursors). Scope: a thread of another workspace or another project is
`404 THREAD_NOT_FOUND`, never 403 — existence is not leaked.

`max_spend_cents` crosses as its canonical **text** spelling (`money_text`) —
the frontend's schema already accepts `number | string` (its deviation D13).

### 3. Task emission (D5 deviation D1)

New projection `clue_projections/research_tasks.py`:
`research_tasks_for_action_refs(workspace_id, action_refs)` unions the two
launch-control tables (`entity_research_account_fleet`,
`entity_research_contact_launch`) on `source_action_ref`, joins
`entity_research_run`, and tallies `entity_research_job` by state and
finalization outcome.

`TurnStreamEmitter.emit_launched_task_parts()` is called unconditionally at turn
close with the turn's own `turn-action:<turn_id>` receipt — the exact string the
launcher persists — so "what did this turn launch?" is a durable-receipt read,
not something the agent/toolbelt had to carry. A turn that launched nothing emits
nothing.

`task_part_from_run`'s `_TASK_STATES` was **wrong** and is fixed: it mapped a
vocabulary `entity_research_run.state` does not use (`completed`/`partial`/
`failed`/`cancelled`/`suspended`) and had no entry for the two states it does use
(`waiting_external`, `terminal`), so every finished run rendered as `queued`.
Now: `queued→queued`, `running|waiting_external→deep_research`, and `terminal` is
derived from the counts (`_terminal_task_state`) — `partial` when any subject
exhausted / needs review / budget-stopped, `failed` when nothing completed.

### 4. Sources emission (D5 deviation D2) — **DELIBERATELY NOT IMPLEMENTED**

Recorded at the emission site in `_project_turn_close`. The project conversation
surface **withholds every fetching tool by policy** (`C6_SURFACE_POLICIES`: "you
do not … fetch external sources"), so no durable source receipt is produced in a
turn. The only remaining candidate — the finalization's `domain_refs` — is
*model-declared*, carries no URL/title/evidence ref, and projecting it would
manufacture provenance from a model's assertion (Doc A §3a; the emitter's own
"an honest gap beats an invented card"). `emit_sources_part` stays as the seam
for the first tool on this surface that produces a real source receipt.

### 5. Deviation D9 (`stream.hello` / connect-time `stream.reset` event ids) — **SKIPPED, reasoned**

Not done, on purpose. SSE `id:` *is* the `Last-Event-ID` reconnection cursor, and
only durable outbox rows have a position. Both frames are connection-scoped and
never stored (`TurnEventType`'s docstring already says `stream.hello` "is
generated at connect and never stored"). Giving them an id would either duplicate
a real cursor (two frames claiming one position) or invent one no
`after_event_id` query can resolve; a `sequence` in the payload would be a second
numbering that differs per connection and that no replay can reproduce, breaking
§3.2's "a frame is a projection of a durable receipt". The frontend's event
schema already accepts both as absent. Cost of skipping: zero.

## Files

- `platform/projections/clue_projections/research_tasks.py` (new) + `__init__.py` exports
- `platform/api/clue_api/chat/turn_stream.py` — `emit_gate_parts`, `_emit_durable_gate_part`, `emit_launched_task_parts`, `_cent_ceiling`, `_gate_subject_ref`
- `platform/api/clue_api/chat/turn_parts.py` — `_TASK_STATES` fix + `_terminal_task_state`
- `platform/api/clue_api/chat/schemas.py` — `GateWire`/`GateAnswerWire`/`GateLaunchWire`/`GateListResponse`/`gate_wire`
- `platform/api/clue_api/chat/router.py` — `list_gates_route`
- `platform/api/clue_api/conversation_turns.py` — the two calls + the sources note
- `tests/api/test_lane_d5_gate_read_and_rich_parts_db.py` (new, 11 tests)

## Verification

- New suite: 11/11.
- Every Lane D suite re-run green (chat thread surface, D1, D2 isolation + submission,
  D3 extractor + stream, D4 gate/route/kickoff/acceptance, B1 join, D5-close) — 160 tests.
- `tests/projections` green (47).
- `make lint` (ruff format --check + check), `make typecheck` (mypy, 619 files),
  `uv run lint-imports` (25 contracts kept) — all clean.
- DB: dedicated `clue-pg-damascus` on **localhost:55040** (`clue:clue@…/clue`),
  head `18541ff11335`. Never 5432 (a foreign native Postgres shadows it).
- **Full `tests/api` blame run — no regression introduced.** Running the whole
  `tests/api` against one shared DB fails ~40 tests
  (`test_frontend_read_account_detail`, `test_lane_bd_join_acceptance_db`,
  `test_lane_d1_turn_action`, `test_lane_d4_model_planned_kickoff_db`,
  `test_lane_d4_option_b_acceptance_db`, `test_o3_account_deep_context`,
  `test_toolbelt_wiring`). This is the **pre-existing unowned gate debt**
  recorded in `_memory/2026-08-09-lane-b-merge-and-suite-debt.md` (committing
  e2e tests polluting the shared DB). Proved by re-running the identical command
  on the parent commit with these files reverted: **the failure set is
  identical.** Every one of them passes per-file/per-group with these changes in
  place. Method for the next agent: `git checkout HEAD~1 -- <paths>`, move the
  new files aside, re-run, compare, restore.

## Open items / caveats

1. **Flag-on end-to-end browser pass still not run** (inherited from D5): no
   `.env`, no model key, no Clerk credentials in this worktree.
2. `TaskPart.title` is `run_kind.replace("_", " ")` — backend-authored display
   copy, pre-existing in `task_part_from_run` and mildly against §3.1's "the
   adapter chooses the words". Left alone; the frontend requires a non-null title.
3. The task card is a **snapshot at turn close**, not a live feed. A run outlives
   its turn; following it afterwards is the run projection's job, and no surface
   re-emits the task part as jobs progress.
4. If the gates route were unreachable and only the stream part existed, an
   approve would send the part's *ceiling* amount and be refused
   `GATE_AMOUNT_STALE` for a fractional-cent gate. Fail-closed, and unreachable
   now that the route exists; today's estimator produces integral cents anyway.
5. Contact-research launches are covered by the projection's union but not by a
   test (the `entity_research_contact_launch` FKs need an account run + a contact
   selection approval); account research is tested end to end.
