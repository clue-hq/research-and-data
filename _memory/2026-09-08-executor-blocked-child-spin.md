# 2026-09-08 — C5 executor drive loop spins on a durably blocked dynamic child (verified)

**Context.** The o4-synthesis-split close-out reported a hang at `RecipeExecutor.execute`
(`platform/execution/clue_execution/executor.py`, drive loop ~L864) when a recipe gate is open and
its dynamic child never completes; the driver contains it with a 30-min `turn_hung` timeout
(`arv2/onboarding_driver.py`, `SYNTHESIS_TURN_HARD_TIMEOUT_S`). Fix is unowned. This session traced
and reproduced the exact mechanism on the base commit `6ed8a4642`.

**Verified mechanism (scratch DB test, rollback-scoped, deleted after).**
1. Gate opens → `AWAITING_INPUT`. Agent appends an interaction child (`node.scheduled`,
   `execution.resumed`), invokes it; the tool's preconditions refuse (`PreconditionFailed`, e.g.
   `exa_not_configured`) → invoker journals `node.blocked` → status `AWAITING_INPUT`.
   `invoke_interaction_tool` raises before `_return_to_interaction_slot`.
2. Turn completes → `decide_gate` → `gate.decided` (RUNNING) + gate `node.completed`.
3. `execute()` drive loop: `_completed_keys` = `node.completed` only, `_failed_keys` =
   `node.failed` only. A **blocked** child is neither, has no dependencies, so it is `ready` every
   iteration. `_execute_node` → `ToolInvoker.invoke` → `journal.begin` sees the durable
   `node.blocked` terminal → raises `PreconditionFailed` ("durably blocked") → swallowed by
   `except Exception: return` with **no event appended** → loop repeats. Measured: 232 iterations
   in 5 s, tool body never runs. No exit condition.
4. The transcript's wording ("finds no ready node, re-appends GATE_OPENED") is NOT the spin:
   with the gate still open and the child blocked, `execute()` returns `AWAITING_INPUT` at once
   (GATE_OPENED projects to AWAITING_INPUT). The spin needs the gate decided.

**Fix sketch (executor-owned, unassigned).** Treat `node.blocked` as terminal in the drive loop:
exclude blocked keys from `ready` (and from the completion count) — e.g. a `_blocked_keys()` via
`_event_node_keys(execution_id, "node.blocked")` — and decide whether a blocked child under a
decided interaction slot means execution `COMPLETED` (refusal was answered to the model) or
`FAILED(reason=node_blocked)`. Add the regression test: blocked child + decided gate + `execute()`
must return within the same drive. Note `journal.completed` already refuses "blocked → complete".
