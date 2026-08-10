# Lane D slice D1 — implementation brief: turn-derived identity + `action_ref` (Lane-D half)

**Charter:** `docs/specs/FI-lane-D-production-chat-and-launch.md` (RATIFIED — read §1.3–1.5,
§3-P2, slice D1, §5 before coding). **Scope law:** `docs/specs/FI-lane-demarcation.md` §2.4.
**Identity law:** `docs/specs/FI-lane-B-authenticated-principal-contract.md` (esp. §2, §7).
Branch: current branch of this worktree. **No migrations in this slice** (D0 owns them).

## Mission

Make the confirming-turn receipt real: extend the PC-C8 turn binding so a turn carries its own
durable identity, mint the canonical opaque `action_ref = turn-action:<turn_id>`, thread ambient
`actor_id`/`action_ref` into the C5 executor's `ToolContext` sites, and fix the §1.4 latent
blocker so `draft_account_research_directive@2` is callable through the agent seam.

## Verified baseline (do not re-derive)

- `ToolContext` (`platform/toolbelt/clue_toolbelt/envelope.py:221-261`) already carries optional
  `actor_id`/`action_ref` with non-empty validation. Doctrine: human gates derive receipts from
  these **ambient** values; caller-authored arguments never choose who approved.
- Production `ToolContext` construction sites: `platform/execution/clue_execution/executor.py`
  :1385, :1672, :1723; `platform/api/clue_api/agent_execution_wiring.py:1418`; plus
  `projections_app.py:494`, `supervisor_wiring.py:281`, `research_view_wiring.py:200`,
  `ingestion_tools.py:401`, `research_view_api.py:286`. **Lane D touches only the four
  agent-execution/C5 sites** — the rest are Lane B's half (its B4 slice).
- The turn-binding seam: `platform/api/clue_api/turn_binding.py` — `CapturedTurn` (frozen; fields
  `onboarding_input_id, artifact_key, sha256, byte_count, answer`; `value_for` refuses unknown
  fields with `unbindable_field`), `CapturedTurnBinder.bind` (fail-closed integrity: artifact
  digest ↔ ref digest ↔ capture record digest, UTF-8, `actor='human'` + project scope on the
  lookup — read its class docstring for why), cache keyed on the *turn*.
- The trusted-argument merge: `agent_execution_wiring.py::_trusted_tool_arguments` (:235-282) —
  fields marked `TRUSTED_TURN_FIELD` are stripped from model-visible schemas, model-proposed
  values rejected, values served via `captured_turn.value_for(field)`.
- **The blocker:** `DraftAccountResearchDirectiveInput`
  (`platform/api/clue_api/research_directive_tools.py:74-81`) declares `user_instruction` and
  `source_turn_ref` as `TRUSTED_TURN_FIELD`; neither is a `CapturedTurn` field, so the agent-plan
  path raises `CapturedTurnUnavailable(unbindable_field)` today. `head-of-abm/v22` pins the tool.
- The confirm tool (`confirm_account_research_directive@2`, human-only) requires ambient
  `actor_id`+`action_ref` and persists `confirmed_by`/`confirming_action_ref`; the launcher
  persists `approval_refs = (source_action_ref, confirming_turn_ref)`. Locate and read it before
  designing the end-to-end test.
- The `AgentConstitution` already carries `actor_id` (see `_trusted_authority`,
  `agent_execution_wiring.py:225-232`); the trial sets it to a literal (`"stage0-trial-user"`) —
  fine for now, the value upgrades at the Lane-B join; D1 delivers the **plumbing**.
- A parallel D0 agent is adding `agent_turn.submitted_by_user_id` / `submitted_via_membership_id`
  (nullable text) in its migration.

## Deliverables

### 1. `CapturedTurn` extension (the blocker fix)

Add to `CapturedTurn`: `turn_id: str`, `user_instruction: str` (the exact decoded turn bytes —
same value as `answer`; it exists so the *field name* tools declare is servable), and
`source_turn_ref: str` (the canonical `turn-action:<turn_id>`). `CapturedTurnBinder.bind`
populates them from `request.turn_id` and the derivation helper (below). `value_for` serves them;
everything stays frozen/`extra="forbid"`; the binder's fail-closed integrity rules and cache
semantics are untouched.

### 2. Canonical turn-action module — new `platform/api/clue_api/turn_action.py`

- `derive_turn_action_ref(turn_id) -> str` → `turn-action:<turn_id>` (single authority for the
  format; `turn_binding` uses it).
- `resolve_turn_action(ref, *, workspace_id, conn_factory) -> ResolvedTurnAction` — server-side
  resolution per charter P2: parse/refuse malformed refs (opaque prefix, exact match, no
  client-extensible grammar); load the `agent_turn` row **in that workspace only**; re-verify the
  human capture integrity join (reuse the `CapturedTurnBinder`/`get_onboarding_input_for_artifact`
  machinery — do not duplicate the digest logic; refactor a shared helper if needed inside these
  two modules); read the turn's `submitted_by_user_id`/`submitted_via_membership_id`. Deny by
  default (Lane B ruling 10): a missing turn, cross-workspace ref, failed integrity join, or NULL
  submitter → typed refusal with a stable reason code. The resolved value exposes
  `{turn_id, workspace_id, submitted_by_user_id, submitted_via_membership_id,
  onboarding_input_id, sha256}`.
- Actor-match rule: resolution takes the acting principal's `actor_id` and refuses when it differs
  from the turn's submitter (a receipt proves *this user's* turn authorized the effect).
- Gate-answer resolution (charter P2's `agent_gate` leg) is **D4's** — leave a seam comment, do
  not build it.

### 3. Ambient identity through the C5 executor

At the four agent-execution `ToolContext` sites (`executor.py` ×3,
`agent_execution_wiring.py:1418`): populate `actor_id` from the constitution and `action_ref`
from the current turn's derived `turn-action:<turn_id>`. Investigate how the turn identity flows
to each site (the wiring has the `AgentTurnRequest`; the executor may need the value threaded via
its existing parameters — thread it as data, never a global). Where a site executes outside any
turn (if any), the fields stay `None` — never fabricate. Keep the change surgical; do not
restructure the executor.

### 4. Tests (the slice's acceptance)

DB-gated per house conventions, on the canonical fixture (charter §5):

- **Blocker-fix proof:** `draft_account_research_directive@2` drives through the agent seam
  (plan → `_trusted_tool_arguments` with the extended binding): `user_instruction` equals the
  turn's exact bytes, `source_turn_ref` equals the derived ref; a plan proposing either field is
  rejected (`plan arguments carry trusted turn authority`).
- **End-to-end receipt:** persist a human turn (stamp the D0 submitter columns in the fixture),
  derive its `action_ref`, invoke `confirm_account_research_directive@2` via the toolbelt with
  `ToolContext(actor="human", actor_id=<principal user>, action_ref=<derived>)`:
  `confirmed_by`/`confirming_action_ref` equal the ambient values exactly.
- **Adversarial negatives:** malformed ref; ref from another workspace; actor mismatch
  (principal ≠ turn submitter); NULL-submitter turn; client/plan-supplied `action_ref`
  structurally rejected; a second resolution of the same ref is deterministic (same resolved
  identity — replay-safe, no state mutated by resolution).
- Executor threading: a governed tool invoked through an agent turn observes
  `ctx.actor_id`/`ctx.action_ref` matching the turn's constitution/derived ref.

**Sequencing note:** the two integration tests above need D0's `agent_turn` submitter columns.
Build and unit-test everything else first (extension, module, threading — none need the columns);
before writing the DB-backed tests, check `git log`/schema for D0's migration. If it has not
landed when you reach that point, stop, commit what is done, and report — do not write the
migration yourself.

## Hard exclusions

**No Alembic migrations.** Never touch: D0's files (`context.py`,
`projections/clue_projections/agents.py`, `thread_tools.py`/`thread_wiring.py`, the `chat/`
package, the D0 migration), composition-root app files (D1 registers no routes),
`frontend_read/**`, `apps/frontend/**`, either `api-contracts/*.md`, FI-2 files (per demarcation
§1.2), Lane B territory (`platform/auth/**`, the non-agent `ToolContext` sites), Lane E/F/G files.
Do not modify any human-only-tool surface policy or model-visible schema beyond what the
`TRUSTED_TURN_FIELD` stripping already does.

## Process

Work test-first where practical. Commit locally at coherent checkpoints; **never push; no
AI/Claude attribution anywhere.** A parallel agent (D0) works in this same worktree — commit only
your own files; leave foreign uncommitted changes alone. Finish with: a `_memory/` session entry
(what/why/verification/follow-ups) and a final report listing every file changed, the exact
reason-code vocabulary you introduced, test output, and anything left open.
