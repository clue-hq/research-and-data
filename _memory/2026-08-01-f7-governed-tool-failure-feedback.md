# F7 — a refused governed tool invocation is model-visible, not turn-killing (2026-08-01)

Branch `platform/clue-trial`, after the Stage-0 turn-routing-honesty work. Closes the last
Phase-B defect from `_memory/2026-07-31-stage0-structured-output-failure-chain.md`.

## What was wrong

Live turn 2: Terra called `record_interview_answer@1` with one claim `value` paraphrased instead
of quoted, and `clue_research/stage0/interview.py::_exact_quote` correctly raised
`ValueError("claim value is not textually entailed by the exact interview quote")`. **That verifier
is right and is untouched.** The defect is propagation: `GovernedAgentToolFactory._governed_tool`'s
wrapper raised a bare `RuntimeError(f"governed operation {address} failed")` on a non-`completed`
execution and let `AgentPlanRejected` propagate raw. Either exception escapes the LangChain
`StructuredTool` coroutine, kills the LangGraph run, and the turn ends `failed`/`runtime_error`
with **zero** feedback — for a defect the model could have fixed by re-quoting one string.
Task 3 built this feedback loop for `finalize_turn` (`_bounded_finalize`); governed tools were left
raising.

## The repair (three seams)

1. **The reason had to become reachable.** `C5AgentExecutionAdapter.execute` gathers operation
   exceptions away (`return_exceptions=True`) so one failed node cannot abort its siblings, and the
   durable records keep only *codes* (toolbelt journal: the exception class; plan journal:
   `operation_failed`). New `clue_agents.ports.OperationFailure` (`node_key`, `address`,
   `error_type`, `message`) rides the existing `ExecutionProgress` — the channel that already
   reports *which* node failed — as an additive, defaulted field. Not a side channel, and no
   durable record changed. `PreconditionFailed` is unfolded to `reason_code: message` pairs (its
   `str()` carries codes only, and the messages are the half a model can act on); every message is
   whitespace-collapsed and truncated at 600 chars so a traceback cannot dominate the next call.
2. **The wrapper converts instead of raising.** `AgentPlanRejected` → `{location: code: message}`
   per issue; a non-`completed` execution → `{error_type: message}` per failure. Returned as
   `GovernedToolFailure` JSON — the same shape discipline as the success path's
   `GovernedOperationReceipt` JSON — with `recorded: false` pinned and guidance that states plainly
   that nothing was recorded and it must not be reported as captured.
3. **Bounded + logged.** `_MAX_GOVERNED_TOOL_FAILURES = 3` per turn, shared across every governed
   tool (the factory is built once per turn). The 4th refusal raises the original exception, i.e.
   exactly today's fail-closed behaviour. Every conversion logs `agent.tool_repair`
   (address, node_key, error, error_type, reasons, attempt, exhausted) via `clue_obs.get_logger`,
   matching task 3's `agent.finalize_refused` convention.

**A hard per-turn bound already existed** — `DeepAgentTurnRuntime` sets
`recursion_limit = max_rounds * 2 + 4` (52 by default) plus `max_runtime_s=300`, so a repair loop
cannot run forever; a `GraphRecursionError` is caught by `run`'s `except BaseException` → FAILED.
The budget was added anyway because that ceiling is only reached after ~24 further *paid* model
calls, and because it mirrors `_bounded_finalize`'s precedent.

## Idempotency (why a retry cannot collide)

`node_key = agent_{tool}_{sha256(tool_call_id)[:24]}` → `plan_id = uuid5(ns, execution:node_key)` →
`operation_id = operation_id_for_plan_node(execution_id, node_key)`. A corrective retry is a new
`tool_call_id`, therefore a new node/plan/operation end to end: it cannot inherit the failed
attempt's A9 ledger identity, and the failed attempt's durable record stands untouched. Pinned by
`test_a_retry_is_a_new_operation_and_cannot_collide_with_the_refused_one`.

## Tests

* `tests/agents/test_governed_tool_feedback.py` (5) — scripted-model runs through the real
  deepagent loop: refusal → visible feedback → corrected args → commit → finalize; plan rejection
  same; new-operation-per-retry; 4th refusal fails closed (`runtime_error`, no envelope, 4 model
  calls, attempt ordinals 1–4 with `exhausted` only on the last); operator-visible log on a
  repaired refusal. **RED evidence:** with only `agent_runtime_wiring.py` reverted, the first test
  fails `assert 1 == 3` — one model call, no feedback, the exact live symptom.
* `tests/api/test_agent_execution_wiring.py` (+3) — the *real* adapter with a tool that raises:
  `ValueError` and `PreconditionFailed` reasons reach `ExecutionProgress.failures`, the durable
  side is untouched (no result row, `operation_failed` event), and a 5 kB message is bounded.

Green: `tests/agents`, all of `tests/api` (with the local DB), `mypy`, `lint-imports`, ruff
check/format on changed files.

## Residual (deliberate, not done)

`delegate_specialist` still raises `RuntimeError(f"governed {role} delegation failed")` on a failed
delegation, so a failed *specialist child turn* still kills the parent turn. Left out of scope: a
failed delegation is not a mis-typed argument the model can repair cheaply, and re-running a child
agent is an expensive retry. If the trial hits it, the same `_tool_failure` seam applies.
