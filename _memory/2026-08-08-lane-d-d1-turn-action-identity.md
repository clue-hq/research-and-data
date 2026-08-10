# 2026-08-08 — FI Lane D slice D1: turn-derived identity + `action_ref` (Lane-D half)

Branch: `platform/frontend-integration` (worktree *damascus*). Brief:
`docs/specs/FI-lane-D-D1-implementation-brief.md`. Charter: `FI-lane-D-production-chat-and-launch.md`
§3-P2 / slice D1. Identity law: `FI-lane-B-authenticated-principal-contract.md` §2/§7. Scope law:
`FI-lane-demarcation.md` §2.4. Commits: `5528e634` (implementation), `e024833a` (tests).

## What shipped

1. **`platform/api/clue_api/turn_action.py` (new)** — the single authority for the human action
   receipt.
   - `derive_turn_action_ref(turn_id)` → `turn-action:<turn_id>`; `parse_turn_action_ref` accepts
     **only** the canonical spelling (no `{...}`, `urn:uuid:`, uppercase, dashless, query suffix,
     whitespace) so one act never gets several names.
   - `resolve_turn_action(ref, *, workspace_id, actor_id, conn_factory)` → `ResolvedTurnAction`
     (`action_ref, turn_id, workspace_id, submitted_by_user_id, submitted_via_membership_id,
     onboarding_input_id, sha256`). Deny by default; pure read, so resolution is replay-safe.
   - Reason-code vocabulary (`TurnActionUnresolvable.reason_code`):
     `turn_action_ref_malformed`, `turn_action_turn_not_found` (cross-workspace lands here —
     existence is not leaked), `turn_action_project_scope_missing`,
     `turn_action_message_ref_missing`, `turn_action_capture_not_found`,
     `turn_action_capture_digest_mismatch`, `turn_action_submitter_missing`,
     `turn_action_actor_mismatch`.
   - The `agent_gate` answer leg is **D4's** — a seam comment, no stub.
2. **`CapturedTurn` extension (the §1.4 blocker fix)** — `turn_id`, `user_instruction` (byte-equal
   to `answer`, but under the field name the directive tools declare), `source_turn_ref` (derived
   ref). `draft_account_research_directive@2` marks the latter two `TRUSTED_TURN_FIELD`; neither was
   servable, so every agent-planned call raised `CapturedTurnUnavailable(unbindable_field)`.
   Fields are **required** (a binding never invents a value) — the two pre-existing test
   constructions were updated.
3. **`load_human_capture` (in `turn_binding.py`)** — the human-capture integrity join extracted once
   (capture exists for this artifact in this project by a human; digests agree) and reused by the
   binder and the resolver, so they cannot drift.
4. **Ambient identity at the four agent-execution/C5 `ToolContext` sites** —
   `C5AgentExecutionAdapter` derives `self._action_ref` once from its bound `turn_id` and stamps
   `actor_id=constitution.actor_id` + `action_ref` on (a) the pin-resolution ctx
   (`agent_execution_wiring.py`) and (b) `invoke_interaction_tool`; `RecipeExecutor.execute` and
   `invoke_interaction_tool` take optional `actor_id`/`action_ref` and thread them to their three
   `ToolContext` sites (`executor.py` ×3). Data-threaded, never global; `None` off-turn.

## Decisions / rationale worth keeping

- **Import direction:** `turn_binding` imports `derive_turn_action_ref` at module scope;
  `resolve_turn_action` imports the binder's capture helper **inside the function** to break the
  cycle (a human gate resolves far more rarely than a turn binds). Documented at the site.
- **No new type for the ambient pair** at the executor seams — two optional kwargs named exactly like
  the `ToolContext` fields, defaulted `None`, so every existing caller is untouched.
- **`user_instruction` is not persisted as a directive column** — it rides `draft_request_sha256`
  and the memory submission. The end-to-end test therefore asserts the durable `source_turn_ref`
  column plus a recomputed request digest (and that a tidied retype hashes differently).
- **`execute(actor_id=…, action_ref=…)` has no production caller yet.** Its consumer is D2's
  `AGENT_TURN` worker route; the trial's recipe drive was deliberately left unattributed (dev-only
  per §6-D6, and a recipe drive spans turns).

## Verification

- `make typecheck` clean (594 files); `make contracts` 25/25; ruff check + format clean on all nine
  touched files. Repo-wide `make lint` fails on **22 pre-existing** unrelated files (format drift
  that predates this slice); none of mine is in that list.
- Green: `tests/api/test_lane_d1_turn_action.py` (23), `tests/api/test_c8_turn_binding.py`,
  `tests/api/test_agent_execution_wiring.py`, `tests/api/test_stage0_routing_honesty.py`,
  `tests/api/test_account_research_directive_a2.py`, all of `tests/execution`.
- DB: the worktree Postgres is `localhost:55040` (`clue-pg-damascus`), at merged head
  `a21c4d290eb7`. **Never use `localhost:5432`** (foreign native Postgres).
- **Not mine, still failing** (all trace to Lane D D0's committed thread tools / paginated turn
  projection, which their own test updates have not caught up with):
  `tests/api/test_toolbelt_wiring.py::{test_build_toolbelt_registers_the_full_set,test_out_of_order_matrix}`
  (extra `create_thread`/`rename_thread`/`archive_thread`/`set_thread_pinned`),
  `tests/api/test_agent_registry_wiring.py::{test_head_resource_map_is_exhaustive…,test_resolved_snapshot…}`
  (59 vs 55 disclosures), `tests/api/test_agent_turn_wiring_db.py::test_durable_turn_history…`
  (`agent_turns_for_project` now returns a paginated tuple).
  `tests/fleet/test_b4_composed_run_db.py` failed once in a long combined run and passes in
  isolation and in smaller combinations — order/pollution, not this slice.

## Open / follow-ups

- **`AgentConstitution.actor_id` is still a literal on the trial path** (`"stage0-trial-user"`).
  D1 delivered the plumbing; the value becomes `platform_user.user_id` at the Lane-B join (B2/B4).
- **Nothing calls `resolve_turn_action` in production yet** — its callers are D2's turn route (which
  must also *write* `agent_turn.submitted_by_user_id`/`submitted_via_membership_id`; today only the
  test fixture stamps them) and D4's gate-response path.
- **`RecipeExecutor.execute`'s identity parameters have no production caller** (see above).
- D4 owns the `agent_gate` answer resolver; do not widen `turn_action.py`'s grammar to carry gate
  identity — add a second resolver over the gate/answer records.
