# Task 3 — finalize-contract parity + model-visible finalize feedback (2026-07-31)

Phase-A defect 3 from `_memory/2026-07-31-stage0-structured-output-failure-chain.md`. Branch
`platform/clue-trial`, after tasks 1–2 (`1f2f1f4..cef55c9`).

## What was actually wrong (two stacked causes, not one)

1. **Contract asymmetry.** `ModelFinalizeRequest` (`platform/api/clue_api/agent_runtime_wiring.py`)
   accepted `status=awaiting_input` + `failure_code`; `AgentFinalizeEnvelope.terminal_shape_is_honest`
   (`platform/agents/clue_agents/contracts.py`) rejects it. The model got a green light for a
   proposal the durable envelope would refuse.
2. **The refusal was invisible.** `finalize_turn` is `return_direct=True`. LangGraph's `ToolNode`
   already converts a finalize refusal into an *error* `ToolMessage` (a pydantic `ValidationError`
   raised **inside** the coroutine is caught by `_execute_tool_async`'s `except ValidationError` →
   `ToolInvocationError` → the default handler returns its message), but
   `_make_tools_to_model_edge` then routes to END because every executed tool call was
   `return_direct`. The model never saw the error; the turn died `missing_finalize`. This is why the
   live symptom was `missing_finalize` and not `validation_error`.

## Repair

- `ModelFinalizeRequest.terminal_shape_is_honest` (`model_validator(mode="after")`) mirrors the
  envelope: `failure_code` required iff `status == failed`; `completed` requires `user_message`;
  `awaiting_input`/`blocked` must supply `next_actions`, `open_gate_refs`, **or** a `user_message`
  (the last because `_finalize_tool` deliberately repairs an omitted `next_actions` from the durable
  user message — that repair is preserved and now covered twice). Envelope-only rules over trusted
  injected fields (`output_refs`, identity, time) stay envelope-only. Direction is one-way: the
  model boundary is at least as strict, never looser.
- The finalize tool description now states the status contract, because a Responses function
  `parameters` must stay a plain object schema and cannot express "failure_code iff failed".
- `ExactAgentToolSurfaceMiddleware._bounded_finalize` (`platform/agents/clue_agents/runtime.py`):
  a refused finalize is returned to the model as an error `ToolMessage` **once**, with
  `return_direct` cleared for that one call so the corrected proposal can come back;
  `return_direct` is re-set to `True` before every attempt so a commit still ends the turn
  immediately. A `ValueError` raised *inside* the tool (envelope construction, the account-research
  completion guard) is converted to the same error message instead of crashing the graph.

**Fail-closed by omission, not by a new terminal path.** Once the single repair is spent
(`_MAX_FINALIZE_REPAIRS = 1`), `return_direct` stays `True`, so the second refusal ends the graph
exactly as before and the runtime still reports the stable `missing_finalize`. No new failure code,
no retry loop, nothing committed.

## Notes / residuals

- `_bounded_finalize` mutates `BaseTool.return_direct` on the live tool object. Safe today: the
  governed tools are built per turn by `GovernedAgentToolFactory.build()` and the middleware
  instance is constructed per `DeepAgentTurnRuntime.run`, and each attempt re-sets the flag so a
  reused tool self-heals. It would race if one tool instance were ever shared by two concurrent
  turns.
- Catching `ValueError` also catches `AgentFinalizationAuthority`'s own guards ("finalization
  crosses the workspace execution", "execution already has a different finalization authority").
  Those now cost one visible retry before the turn fails — still fail-closed, still FAILED.
- Tests: `tests/agents/test_finalize_contract.py` (21). Pre-existing, unrelated failures on this
  branch: `tests/api/test_projections_app.py` (14), `test_c7_activation.py` (4),
  `test_phase_c_integration.py` (1), `test_toolbelt_wiring.py::test_out_of_order_matrix` —
  identical before and after this change.
