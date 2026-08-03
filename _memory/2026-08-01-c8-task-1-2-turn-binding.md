# 2026-08-01 — PC-C8 task 1.2: engine-side turn binding + L7 captured-turn envelope

Branch base `platform/c8-context-card` (worktree branch `worktree-agent-a9afc3767bab1664d`).
Implements spec `docs/specs/PC-C8-stage0-context-card.md` §6a **and** §6b (no fallback taken),
plus §8's versioning consequence. AC-6 covered.

## What landed

**New seam — `platform/api/clue_api/turn_binding.py`.** A tool-input field marked
`json_schema_extra={TRUSTED_TURN_FIELD: True}` is (a) stripped from the model-visible schema by
`agent_runtime_wiring._with_trusted_runtime` and (b) injected at the execution seam by
`agent_execution_wiring._trusted_tool_arguments` from a `CapturedTurn` binding. This *extends* the
existing `project_id`/`MODEL_FORBIDDEN_AUTHORITY_KEYS` mechanism rather than paralleling it; the
two differ only in where the trusted value comes from (constitution = whole execution, captured
turn = this turn). Marking is per-model, not per-field-name, because `artifact_key` is legitimately
model-authored on `submit_onboarding_input`.

**The binding is derived, never passed.** `CapturedTurnBinder.bind(request)` reads the turn's own
`user_message_artifact_ref`, verifies `sha256(bytes) == ref.sha256`, joins
`get_onboarding_input_for_artifact` (new read fn in `clue_research/stage0/governed.py`, newest-row
first with an `id` tie-break — artifact keys are content-addressed so two identical turns can share
one key), re-checks `content_sha256`, and decodes UTF-8. Every failure is `CapturedTurnUnavailable`
(a `ValueError`) → the existing `tool_input_invalid` plan-issue path → typed, model-visible refusal.
Because it derives, `stage0_trial.py` (forbidden to touch this task) needed **no changes**:
`build_head_of_abm_stage0_execution` and `build_agent_context_assembler` build the binder from what
they already receive.

**Model-facing `record_interview_answer` schema is now exactly:** `brand_id`, `client_entity_id`,
`product_id` (optional), `statements`. `answer`/`onboarding_input_id`/`artifact_key` joined
`project_id` behind the boundary; all four stay on the tool's own input model because the C4 recipe
path supplies them directly.

**L7 envelope (§6b).** `TurnLayerSource` takes an optional `captured_turn` describer and appends a
reference-only candidate (`900-captured-turn`, `required=False`) naming
`onboarding_input_id`/`artifact_key`/`sha256`/`byte_count`. A surface with no capture gets no
envelope (fail-soft at assembly; fail-closed only at the tool seam). Only `TurnLayerSource` was
touched in `context.py`; the two protocols sit immediately above it and are not exported in
`__all__` (1.3 owns the rest of that file).

## Versioning decision — MINIMAL BUMP TAKEN; 1.4 must fold into it

Investigated first: `_schema_sha256` hashes the **full** input model, and `AgentProfileRegistry`
`_resolve_tool` raises `tool ... schema digest changed` whenever a *selected* profile's (or its
skill's) pinned sha differs from the live descriptor. An honest F8 surface requires changing field
descriptions, which changes the sha, so staging without activating was structurally impossible —
the active head-of-abm@v7 / stage0-interview@v5 would have failed to resolve and reddened
everything. Took the established v4→v5 pattern (same tool `@1`, new skill + profile versions, old
untouched):

- added `platform/agents/catalog/skills/stage0-interview/v6/SKILL.md` (v5 + new sha + §3b prose:
  offsets index into the platform-loaded capture; the model no longer sends the body or the ids);
- added `platform/agents/catalog/profiles/head-of-abm/v8/profile.yaml` (v7 + skill v6 + new sha);
- flipped `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM]` v7 → **v8**.

New `record_interview_answer@1` input sha: `88099522cbee252faa229b48eb835b851d99a568e2af5421ca528de16c571c74`
(was `17e741cb…`). New head-of-abm resource-manifest aggregate:
`50827c756c7b5c7dab914f8399d3efb646aff845b2889d2a4d678b8f171d13bd`.

**Task 1.4 must fold its trial profile variant + skill cleanup into a further bump (v9/v7) rather
than editing v8/v6 in place** — immutability discipline; old versions are never touched.

## Deviations / follow-ups surfaced

1. **`brand_id`/`client_entity_id` stay model-authored.** Spec §6a's table lists "workspace/
   project/product/client authority" as engine-injected. `workspace_id`/`project_id` already are
   (constitution); `brand_id`/`client_entity_id` are *project* authority, not turn authority, and
   moving them means editing the frozen `MODEL_FORBIDDEN_AUTHORITY_KEYS` in `contracts.py` — which
   task 1.3 owns. Deliberately out of scope for 1.2; flagged for 1.3.
2. **Stale prose in `stage0_trial.py` (forbidden file).** The stage-snapshot `instruction`
   (~:741) still says "use its provided onboarding_input_id", and `NO_ROUTING_RECEIPT` (~:174) says
   "Call record_interview_answer for this turn's onboarding_input_id". Both are now wrong — the id
   is not a field the model fills. 1.3/1.4 should fix while rewriting those payloads.
3. **`get_onboarding_input_for_artifact` has no supporting index** (`onboarding_input_scope` is
   `(workspace_id, brand_id, product_id, project_id, created_at)`). One extra seq scan per turn
   (binder is cached per artifact key, and L7 + the tool seam share the instance only within their
   own composition). Fine at trial scale; index if the table grows.
4. **The 16 KB CLI message cap no longer exists for echo reasons.** Comments in
   `scripts/cli_multiline.py`, `scripts/README.md` and `tests/clue_trial/test_cli_multiline.py`
   updated; the cap itself is deliberately unchanged (relaxing it is a Slice-2 context-budget call).

## Tests

New `tests/api/test_c8_turn_binding.py` (13): binding derivation; unbound turn (fail-closed +
`describe` → None); digest mismatch refused before any DB read; a 4-way unicode/ASCII matrix
proving offsets stay **character** positions while sha/byte_count stay over **bytes**; a governed
call of offsets alone landing the statement (durable `quote_sha256` == hash of the engine-loaded
slice); out-of-range offsets and non-entailing claim values refused with nothing written; the
model-facing schema refusing each smuggled field (`extra='forbid'`); the seam refusing turn keys in
plan arguments; and a step needing turn authority with no binding refused.

Flipped `test_c8_slice0_evidence.py` test 4 →
`test_record_interview_answer_no_longer_lets_the_model_author_the_answer_or_trusted_ids`.
Added two L7 envelope tests to `tests/agents/test_context.py`. Updated F8 mapping rows in
`test_stage0_tool_guidance.py` (the three fields have no model-facing home; offset rows now require
"captured user message"). Updated `test_governed_tool_arguments`, `test_governed_tool_feedback`,
`test_stage0_routing_honesty` (both agent-path pin tests now inject the binding and assert the
`artifact_input` pin derives from the **engine-supplied** key), `test_agent_registry_wiring`,
`test_catalog`.

Green: `tests/api tests/agents tests/stage0` (only the pre-existing
`test_agent_runtime_wiring_db.py::test_delegation_is_durable_before_fresh_child_wake_and_rolls_up_reference_result`
fails — it hand-builds a registry pinning an old `evaluate_stage0_readiness` sha and fails on a
clean tree too). `uv run mypy` clean (455 files), `uv run lint-imports` 24/24, ruff clean on every
touched file.

## Security-review follow-up (second commit)

Reviewed APPROVED-WITH-MINORS. F2 (stale `stage0_trial.py` prose) belongs to 1.3 — untouched.

- **F1 (required) — the capture lookup was model-influenceable.** `get_onboarding_input_for_artifact`
  selected newest-first over `(workspace_id, artifact_key, kind)` only. `submit_onboarding_input`
  is on the agent's granted surface, its `content_sha256` is never verified against the artifact,
  the key is content-addressed, and the L7 envelope hands the model that exact key+sha — so the
  model could insert a newer `user_turn` row citing this turn's artifact and become the selected
  capture record (self-chosen attribution; also an unrepairable `Stage0RoutingReceiptGuard` loop).
  Two projects sharing a byte-identical short answer could likewise cross-select. Fixed: the query
  now also scopes by `project_id` (threaded from `request.constitution.project_id`) and
  `actor` (binder passes `'human'`; agent rows are `'agent'`). The binder cache key gained
  `project_id`.
- **F3 — honest failure attribution.** `CapturedTurnUnavailable` now raises a distinct
  `turn_binding_unavailable` plan issue located at `plan.steps[n]` (not `.arguments`), so an
  engine-side binding failure is no longer blamed on model arguments it cannot repair. Same
  fail-closed outcome.
- **F4 — the offset matrix now discriminates.** Added a governed call quoting `"administrators"`,
  which starts after the astral emoji; a byte-offset reading yields `"d the administ"`, and the
  test asserts the durable `quote_sha256` matches the character slice and *not* the byte slice.
- **F5 — silent seams.** `CapturedTurnUnavailable` carries a `reason_code`; `describe()` logs a
  structured `stage0.captured_turn.unavailable` warning for every reason except the ordinary
  `capture_not_found`. Both binder construction sites carry a comment noting they are independent
  instances with independent caches (consolidation is 1.3's wiring call). Removed
  `onboarding_input_id`/`artifact_key` from `RecordInterviewAnswerTool.parameter_policy.
  safe_display_fields` (a journal display summarises what the *caller* chose; the turn identity is
  no longer chosen). None of this touches `input_schema_sha256`, so **no further catalog bump**.

New tests: `test_a_row_the_model_could_write_cannot_become_this_turns_capture_record`,
`test_two_projects_answering_identically_each_bind_their_own_capture_record` (both plant a
`ffffffff-…` capture id that would win the `id DESC` tie-break — rows in one transaction share
`created_at` — so they genuinely discriminate),
`test_a_governed_quote_after_a_multi_byte_character_lands_the_characters_not_the_bytes`,
`test_an_integrity_disagreement_fails_soft_at_l7_but_never_silently`, and case (3) of
`test_the_agent_path_still_refuses_unresolvable_and_out_of_slot_pins` (asserts the
`turn_binding_unavailable` code and that no issue location ends in `.arguments`).

Pre-existing failures NOT caused here (verified by stashing): the above delegation test;
`tests/memory/test_memory_offline.py`; `tests/resolvers/test_static.py` secret-scanner;
`tests/execution/test_recipes.py` + `test_recipe1_cutover.py` (shared-DB recipe version conflicts);
`tests/toolbelt/test_runner.py` under cross-file selection; `tests/db/test_db_migrations.py`
up→down→up (needs a clean throwaway DB — running it left the shared dev DB degraded mid-session).
