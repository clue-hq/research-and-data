# 2026-08-01 — PC-C8 task 1.0: Slice-0 evidence fixtures (tests only)

Branch `platform/c8-context-card`. One new file, **no production code touched**:
`tests/api/test_c8_slice0_evidence.py` — five characterization tests that PASS against today's
code and freeze the defects in `docs/specs/PC-C8-stage0-context-card.md` §1. Tasks 1.1–1.5 must
**flip** each one into a guard of the fix, not delete it (stated in the module docstring).

## What each test freezes
1. `test_required_l3_bundle_exceeds_its_hard_budget_at_a_normal_interview_length` — DB-gated.
   Seeds a real Stage-0 project (workspace/brand/product/project/client + N captured onboarding
   inputs, `volunteered_statement` rows, `readiness_decision` rows via the real
   `evaluate_readiness`), calls the real `Stage0Trial.snapshot()`, composes the three required L3
   artifacts exactly as `stage0_trial.py:729/756/766` do, and asserts the real
   `build_agent_context_assembler` (production `ProjectLayerSource` + `stage0_trial_context_policy`)
   raises `required l3_project context exceeds its hard layer budget`.
2. `test_the_readiness_ledger_is_serialized_twice_into_required_l3` — byte-identical ledger in both
   artifact bodies (read back through the artifact store, not just equal Python objects).
3. `test_required_l3_bytes_grow_with_every_material_turn` — composes at N and N+8 material turns;
   asserts ≥900 B of required L3 growth per turn (floor, not an exact rate).
4. `test_record_interview_answer_still_makes_the_model_author_the_answer_and_trusted_ids` — no DB;
   introspects the real model-facing schema (`_with_trusted_runtime` + provider transform, reusing
   `tests/api/test_stage0_tool_guidance._model_facing_parameters`). `answer`,
   `onboarding_input_id`, `artifact_key` are required of the model; `project_id` is already
   stripped — the seam 1.2 extends.
5. `test_the_identity_prompt_is_injected_into_every_model_call_twice` — no DB; runs the **real**
   `DeepAgentTurnRuntime` with a callback capturing the model input, proving the prompt reaches the
   model twice. Fixed in Slice 2, only recorded here.

## Measured numbers (this fixture, 22 statements / 20 decisions)
stage 33,671 B + readiness 16,942 B + budget 140 B = **50,753 B** vs the 48,000 B `l3_project`
budget; duplicated ledger = 16,832 B (~35% of the layer budget); growth ≈ **2,324 B per material
turn**. Historical failing run (spec §1) was 32,178 + 15,889 + 140 = 48,207 at ~20/18. Our
synthetic rows are slightly smaller, so 20/18 measures ~46 KB here and 22/20 crosses the cliff —
the shape reproduces exactly; the counts are two turns later. Byte figures live in docstrings as
reference; the assertions are relational (over budget / identical / growing), never equalities.

## Verification
`uv run pytest tests/api/test_c8_slice0_evidence.py` — 5 passed with `CLUE_DATABASE_URL` sourced
from `.env` (`set -a; source .env; set +a`); the three DB tests skip cleanly without a DB.
Also green: `tests/api/test_stage0_trial.py`, `tests/api/test_stage0_tool_guidance.py`,
`tests/agents/test_context.py`, `tests/agents/test_runtime.py`. `mypy` clean, `lint-imports` 24/24,
`ruff` clean on the new file.

## Pre-existing failures on this branch (NOT caused by this work — reproduced with the new file
removed)
- `tests/memory/test_memory_offline.py::test_no_production_code_outside_memory_touches_the_substrate`
- `tests/resolvers/test_static.py::test_no_secret_shaped_strings_in_source_or_fixtures`
  (`'fixture-org-attributes-only-drift'` in `tests/adapters/test_sumble.py` trips the
  secret-shaped-literal scanner)
- repo-wide `ruff format --check` wants 17 tracked files reformatted and `ruff check` reports 16
  errors, none in the new module. `make check`'s lint gate is therefore already red on this branch.

## Notes for 1.1–1.5
- The snapshot→artifact payload literals are duplicated in the test helper `_required_l3_artifacts`
  because `run_turn` needs a live model call. When 1.3 flips the constitution to
  `project_card_ref`, that helper is the single place to update.
- `snapshot()` reproduces faithfully with a shell `Stage0Trial` (`object.__new__` + `state`,
  `paths`, `_components.artifacts`, `_conn_factory`) — the same idiom `tests/api/test_stage0_trial.py`
  already uses.
