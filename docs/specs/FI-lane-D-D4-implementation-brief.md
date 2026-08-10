# Lane D slice D4 — implementation brief: the Option-B kickoff flow

**Charter (binding spec):** `docs/specs/FI-lane-D-production-chat-and-launch.md` §1.3–1.5,
§3-P5 (as amended by the ratified §6-D3/§6-D5 decisions), §3.4's `gate` part floor, §3.5's
gate-response rule, slice D4, §5's adversarial matrix. Ratified decisions you build under:
**§6-D3** — durable generic `agent_gate` as an **immutable gate row + insert-once answer
record** (open/answered derived, never a mutated status column); **§6-D5** — NO estimate tool;
one server-derived maximum-spend computed at gate creation, stored on the gate, re-verified at
launch; **§6-D4/Lane B** — identity contract. Read
`_memory/2026-08-08-lane-d-b1join-d2-review-verdict.md` and the as-built contract section in
`apps/frontend/docs/api-contracts/projects.md` (the turn endpoint's `gate_response` reservation
is yours to fill).

## Mission

The conversation can now launch research: the agent drafts a directive and opens a durable
confirmation gate carrying the exact maximum spend; the user's approval is a structured human
turn; the server invokes the human-only confirm tool with turn-derived authority; the deepagent
launches with that receipt; every refusal path refuses.

## Verified baseline (do not re-derive)

- The whole authority chain exists as governed tools (charter §1.5): draft
  (`draft_account_research_directive@2`, agent-seam-callable since D1), confirm
  (`confirm_account_research_directive@2`, human-only, persists `confirmed_by`/
  `confirming_action_ref`), launch (`launch_account_research@1`, verifies
  `expected_estimated_cost_cents` exact-match and persists
  `approval_refs = (source_action_ref, confirming_turn_ref)`). The launcher computes the
  estimate as Σ per-account `effort_policy.budget_cap_cents` — locate that computation and
  REUSE it for the gate's max-spend; never duplicate the formula.
- D1's `turn_action.py` resolves `turn-action:<turn_id>` and left an explicit seam comment for
  the gate-answer leg. D2's `agent_turn_submission` + `persist_user_turn` are the turn-write
  path; the router's turn POST currently accepts `{message}` only, with the `gate_response`
  seam commented. `PROJECT_CONVERSATION_SURFACE` exists with the launch tools withheld.
  `finalize_turn`'s `awaiting_input` requires `open_gate_refs` (un-flavoured today; nothing
  reads it back — your gate row becomes what it points at).
- The HTTP process composes the toolbelt with `gateway=None` — human-only confirm-tool
  invocation from the route works without touching the model plane (the isolation guard test
  must stay green).
- Trial latent bug (review verdict follow-up #2): `stage0_trial` calls
  `decide_gate(actor="agent")` against recipe0's HUMAN-authority gate; the production runner
  uses `"human"`. Reconcile it here.
- `entity_research_runtime_enabled` already gates worker composition (`fleet_main`). Default
  stays off; your launch AC runs with it on in the test environment; document the rollout in
  your memory entry.

## Deliverables

1. **The `agent_gate` substrate** (migration — chain off `uv run alembic heads` at authoring
   time; if the parallel D3 migration forks heads, do NOT merge, the orchestrator owns the
   join). Two tables, both immutable-by-trigger like the receipt tables:
   - `agent_gate` (immutable, written at presentation): id, workspace/project/thread anchors
     (composite FKs per house pattern), presenting `turn_id`, `kind` (closed vocabulary —
     `directive_confirmation` now, room for `plan_approval`/`budget_approval`), subject refs
     (the directive ref + revision/`expected_subject_sha256`), the server-derived
     `max_spend_cents` + currency, `addressee_user_id` (FK `platform_user`), `created_at`.
   - `agent_gate_answer` (insert-once: PK/UNIQUE on `gate_id`): answering `turn_id`,
     `action_ref`, `decision` (`approved|rejected|revised`), `answered_by_user_id`,
     `answered_at`. Open vs answered is derived from this row's existence — no status column
     anywhere.
2. **Gate creation as a governed tool** (agent-callable, e.g.
   `open_directive_confirmation_gate@1`): takes the drafted directive ref; computes the
   maximum spend by calling the launcher's own Σ computation over the directive + selected
   account set; persists the immutable gate; returns the flavored ref the agent places in
   `open_gate_refs` when it ends the turn `awaiting_input`. The number on the gate IS the
   number launch will verify — one source.
3. **The structured gate-response turn** (your file: `chat/router.py`, plus
   `conversation_capture.py`/`agent_turn_submission.py` as needed): the turn POST accepts
   exactly one of `message` or
   `gate_response={gate_id, decision, expected_subject_sha256, expected_estimated_cost_cents}`.
   Flow per P5(c): persist the human turn/capture first (the response's canonical bytes are the
   turn's captured bytes — capture-before-effect holds), derive `action_ref`, re-check gate
   addressee + expected digest + expected amount against the immutable gate, invoke
   `confirm_account_research_directive@2` outside the model surface with ambient
   `actor_id`/`action_ref` (approve path), insert the once-only answer record, then enqueue the
   deepagent turn over that same captured action. Reject/revise record answers and enqueue the
   follow-up turn without confirming. Every mismatch (stale digest, wrong amount, wrong
   addressee, already-answered gate, unknown gate, cross-workspace) is a typed refusal with a
   stable reason code and NO side effects.
4. **The gate-answer resolver leg** in `turn_action.py`'s seam: resolving a gate-answering
   turn's authority additionally proves the answer record (gate in this workspace, answered by
   this turn, actor = addressee). A turn receipt alone must not pass where gate authority is
   required.
5. **Surface widening**: `PROJECT_CONVERSATION_SURFACE` gains the drafting + launch tools
   (`launch_account_research@1`, `launch_contact_research@1` if in the flow's scope); human-only
   tools stay structurally absent from every model surface; re-check every skill's
   `required_tools` (the C8 regression trap) and update the surface-count/registry tests
   deliberately (the D0 disclosure-vs-hiding precedent: disclosed-and-refused).
6. **Launch narration facts, not streams**: record the durable linkage (gate → confirming turn
   → `approval_refs` → `entity_research_run` refs) so D3's part projections can render `task`/
   `gate` parts. Do NOT build SSE/parts/outbox emission — D3 owns all streaming; if D3's outbox
   exists when you land, emitting a gate-lifecycle event through its API is welcome but
   optional.
7. **Trial `decide_gate` actor fix** in `stage0_trial.py` (align to `"human"`; keep the trial
   dev-only semantics unchanged otherwise).
8. **`thread_status`**: you may extend `chat/schemas.py::thread_status` with the gate-derived
   states (`approval`/`needs-input`) — that one function only; a parallel D3 agent is also
   editing it (`running` from submissions/turns). Rebase around each other, never revert.

## Acceptance criteria

Charter slice D4's AC verbatim on the canonical two-account fixture with approved tier
checkpoints: draft → gate presented with the exact server-derived amount → `awaiting_input`
with a readable gate → structured Approve creates a visible human turn, the confirm tool runs
with server-derived authority, `confirmed_by`/`confirming_action_ref` equal the ambient values
→ the deepagent launches → `entity_research_run.source_action_ref` equals the confirming turn's
ref and `approval_refs` carries both refs → reject/revise leave answer records and do not
launch. Adversarial (charter §5): stale digest, stale amount, different actor than addressee,
double-answer (insert-once must refuse), non-confirming ordinary turn, client-supplied
`action_ref`/`confirmed_by`, replay determinism. Gates: `make db-smoke` (clean throwaway DB on
`clue-pg-damascus` localhost:**55040**, never 5432), `make lint`/`make typecheck` clean,
suites green, the HTTP-gateway isolation guard still green.

## Hard exclusions

Never touch: D3's files this round (`chat/stream*` modules, `conversation_turns.py`,
`agent_turn_fleet_wiring.py`, the outbox migration, the extractor/parts modules,
`clue_projections/threads.py`); `platform/auth/**`; `frontend_read/**`; `apps/frontend/**`;
`api-contracts/*.md` (the orchestrator records contract changes after review); FI-2 files;
quarantined M8D modules; the launcher's verification logic (call it; only touch it if the
exact-match seam is unreachable — then STOP and report). Composition roots: registration calls
only. No migrations beyond your gate migration.

## Process

Test-first where practical; commit locally at checkpoints; never push; no AI attribution;
explicit-path staging only (a parallel D3 agent is in this worktree). STOP-and-report rather
than improvise on: the launcher's estimate computation not being callable without spend; the
confirm tool needing composition the HTTP process can't have; `open_gate_refs` flavor not
fitting the existing closed ref vocabularies. Finish with a `_memory/` entry and a full final
report (files, migration id, the gate/answer DDL, the reason-code vocabulary, how the one-
source max-spend is guaranteed, surface-widening choices, test results, open items).
