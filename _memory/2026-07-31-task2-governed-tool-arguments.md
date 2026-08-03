# Task 2 — governed tool arguments (defects 2 and 2b) — 2026-07-31

Branch `platform/clue-trial`. Commits `a2541f9` (defect 2), `088eb8d` (defect 2b). No push.

## Defect 2 — JSON normalization (as briefed)

`_governed_tool.invoke` passed LangChain-validated kwargs straight into `PlanToolStep.arguments`
(`dict[str, JsonValue]`), so a nested `InterviewStatement` failed with
`arguments.statements.list.0: input was not a valid JSON value`. Fixed with one seam:
`_json_arguments(kwargs) = pydantic_core.to_jsonable_python(kwargs)` in
`platform/api/clue_api/agent_runtime_wiring.py`.

Why `to_jsonable_python` and not `model_dump(mode="json")` on the args model: the args model is the
`_with_trusted_runtime` subclass carrying the injected, unserializable `runtime` object — dumping it
would fail or leak trusted authority. `runtime` binds to the coroutine's own parameter, so it never
reaches `kwargs`. `to_jsonable_python` raises on an unrepresentable value (fail-closed), and the
executor's re-validation into `descriptor.input_model` (lax) accepts the JSON representation.

## Defect 2b — discovered while fixing 2 (was NOT in the diagnosis memo)

With the JSON error gone, the same call failed with
`model plan arguments cannot supply trusted authority: ['project_id']`. Cause: LangChain's
`StructuredTool._parse_input` materializes **every defaulted field** into the coroutine kwargs, so a
tool model's own `project_id: str | None = None` reached the plan step even though the model never
supplied it. Blast radius: `record_interview_answer`, `submit_onboarding_input`, `start_recon`,
`evaluate_stage0_readiness`, `start_confirmed_project_run` (head_of_abm) and `get_research_view`
(4 profiles) — the whole Stage-0 governed surface.

Ruling taken (coordinator, not discretionary): authority has one source, the `AgentConstitution`.

1. `_with_trusted_runtime` removes every `MODEL_FORBIDDEN_AUTHORITY_KEYS` field from the
   model-visible schema (field removal on the throwaway subclass — the shared `input_model` and its
   validators are untouched). `extra="forbid"` then turns an invented `project_id` into a normal
   validation error that ToolNode renders as an error `ToolMessage` the model can repair.
2. `PlanToolStep.arguments` unchanged — still rejects those keys. No None-dropping heuristics; the
   forbidden-key set was not weakened (it was only renamed public:
   `clue_agents.contracts.MODEL_FORBIDDEN_AUTHORITY_KEYS`).
3. `C5AgentExecutionAdapter.validate_plan` computes `_trusted_tool_arguments` once per tool step
   (before plan-review validation) and every consumer reads that mapping: the review validate, the
   C5 graph parameters/bindings, and the persisted operation-parameter artifact the executed body is
   materialized from. Authority the constitution does not carry (`operation_id`,
   `parent_execution_id`) is never synthesized; arguments that already carry an authority key fail
   loudly (defence in depth).

Non-agent callers (recipes, HTTP) are untouched — they pass full inputs directly.

## Verification

`make check`-equivalent: full `.venv/bin/pytest -q` green except the pre-existing, unrelated
`tests/memory/test_memory_offline.py::test_no_production_code_outside_memory_touches_the_substrate`
(fails identically on a stashed tree). Full `mypy` (454 files) clean; ruff clean on changed files.

## Follow-ups / caveats

- `_with_trusted_runtime` mutates `subclass.__pydantic_fields__` (semi-private pydantic API) and
  calls `model_rebuild(force=True)`. Guarded by `test_no_pinned_tool_exposes_trusted_authority_to_
  any_profile` and `test_hiding_authority_does_not_mutate_the_shared_tool_input_model`, which would
  fail loudly on a pydantic upgrade that changes field-collection behavior.
- A tool that declares a **required** authority field would now depend entirely on the injection; if
  the constitution lacks that key the input model rejects it (correct, fail-closed) — but no such
  tool exists today.
- Defect 3 (`ModelFinalizeRequest` looser than `AgentFinalizeEnvelope`) is untouched; it is task 3.
