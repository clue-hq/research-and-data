# 2026-08-09 — Lane D D3+D4 mid-flight adversarial review (Fable) — INCOMPLETE, paused

## Situation

Both D3 and D4 Opus agents were terminated by the API session limit (evening 2026-08-08,
reset 22:30) mid-wiring. **Neither committed anything**: all work is UNCOMMITTED in the tree
(12 modified + 14 new files). Two forked Alembic heads exist as expected
(`98a5ddafa21b` D3 outbox, `3caa27516b81` D4 gate) — orchestrator merges after completion.
Founder asked for a critical completeness/correctness review, then pause; green history pushed
to origin per explicit founder instruction.

## Correctness review of what exists — NO DEFECTS FOUND in the durable artifacts

- **D4 gate migration `3caa27516b81`** matches the ratified §6-D3 shape exactly: immutable
  `agent_gate` (uuid PK, workspace anchor, presenting-turn composite FK, addressee FK to
  `platform_user`) + `agent_gate_answer` with **PK on gate_id** (insert-once by construction),
  answering turn FK → `agent_turn_submission` (correct: a gate answer is a submission), both
  immutable-by-trigger. Also adds the `agent_turn_submission` workspace anchor it FKs.
- **D3 outbox migration `98a5ddafa21b`**: `UNIQUE (turn_id, sequence)` enforces monotonicity in
  the DB; tight CHECKs (`delta_index` present iff `text.delta`); `generation_attempt_id`
  isolation; deliberately DELETE-allowed with documented transport-buffer rationale + cursor
  indexes. Matches §§3.2–3.3.
- **`finalize_stream.py` extractor**: handles split escapes, `\uXXXX` incl. surrogate pairs,
  half-read surrogates, mid-UTF-8-codepoint chunk boundaries; emits a char only when fully
  decoded; fail-closed `failed` flag on malformed content. Matches §3.3(2).
- **One-source max-spend GENUINELY achieved**: the Σ per-account `budget_cap_cents` loop was
  moved VERBATIM from `account_research_fleet_launch.py` into
  `account_research_estimate.py::compute_account_research_estimate`; launcher and
  `agent_gate_tools` both call it; launcher's exact-match verification unchanged.
- **`turn_action.py` gate-answer leg**: `resolve_gate_answer_action` with deny-by-default codes
  (`gate_answer_not_found`, `gate_answer_turn_mismatch`, `gate_addressee_mismatch`).

Mechanical issues (fine for WIP, must clear before landing): 1× E501 (`turn_stream.py:652`);
2× mypy override-signature errors on `on_llm_new_token` (`turn_stream.py:889`); 2× mypy errors
in `chat/router.py` (schemas made `message` optional; route not yet wired — exactly where D4
stopped).

## Completeness matrix (vs briefs)

**D3 built:** outbox migration; `chat/turn_events.py` (writer); `chat/turn_stream.py` (SSE +
callback handler); extractor; `chat/turn_parts.py`; `chat/turn_controls.py` (stop/retry);
`conversation_turns.py` emission hooks; partial `agent_turn_fleet_wiring.py`; projection
exports. **D3 missing:** settings additions (mid-flight when killed); the fleet sweep loop
registration (stranded-dispatch self-heal); submissions-union completion (threads.py
untouched); `?include=bodies` hydration (unverified/likely absent); the ENTIRE §5 streaming
test suite; memory entry; commits.

**D4 built:** gate migration; `agent_gate.py` store; `agent_gate_tools.py` (creation tool);
`agent_gate_wiring.py`; the shared estimate module + launcher extraction; turn_action gate leg;
surface widening (`agent_registry_wiring`/`toolbelt_wiring`/`head_of_abm_wiring` + NEW
`head-of-abm/v23` profile + `account-deep-steering/v3` skill — profile mint needs review at
completion); `clue_projections/gates.py`; partial `chat/schemas.py`. **D4 missing:** the
gate-response route wiring in `chat/router.py` (P5(c) — THE core flow); `thread_status` gate
states; the `stage0_trial` `decide_gate(actor="agent")` fix; ALL tests; memory entry; commits.

## Actions taken

- Green history (through `0253377c` + this memory commit) pushed to origin per explicit founder
  instruction. The incomplete WIP stays UNCOMMITTED and unpushed — publishing an untested,
  mypy-red, test-less state would be dishonest.
- PAUSED per founder instruction: D3/D4 agents NOT resumed. On founder's go: resume both from
  transcripts (they retain full context), then orchestrator merges the two Alembic heads, then
  full adversarial review + combined suite run.

## Resume checklist (for the next session)

1. Resume `laneD-D3-impl`: finish settings + sweep registration, submissions-union, body
   hydration, fix the callback override signature + E501, write the FULL §5 streaming suite.
2. Resume `laneD-D4-impl`: wire the gate-response route (clear the 2 router mypy errors),
   thread_status gate states, stage0_trial fix, full adversarial gate/launch suite.
3. Orchestrator: `alembic merge` the two heads; review the head-of-abm v23 profile mint; run
   everything; verdict memo.
