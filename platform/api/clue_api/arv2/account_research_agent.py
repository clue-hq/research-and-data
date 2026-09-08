"""The account-research agent loop: one ``create_agent`` graph under four honest caps.

The founder's stop policy (2026-09-08) is "no pre-emptive caps": a hundred model rounds, fifty tool
calls in one round, thirty minutes, and **no** total-call or zero-yield ceiling. What matters here
is not the numbers (they are settings) but the *shape* of every ending:

* **Every cap ends the graph; none of them raises.** ``ModelCallLimitMiddleware`` is built with
  ``exit_behavior="end"`` so the round ceiling ends the run gracefully instead of throwing
  ``ModelCallLimitExceededError`` into the driver — the M8D lane's ``"error"`` behaviour is exactly
  what made a capped job *fail* rather than finish honestly.
* **A finalization stops the loop before the next model call**, so the one decision this job is
  allowed to make cannot be re-made or talked past.
* **The per-round ceiling refuses the excess calls, never the round.** The calls within the
  ceiling run; each call beyond it comes back as its own ``too_many_parallel_calls`` envelope, so
  every tool call in the wave is answered (a wave with an unanswered call is a malformed
  conversation to every provider) and the model reads the manual's reaction for that code.
* **A runtime cap waits for in-flight provider hops to drain** before it reports, because a hop
  that already happened has already been paid for, and money truth must reach the ledger.

The loop returns an :class:`AgentOutcome`; it never raises. Deciding what an outcome *means* for
the job row belongs to the driver, not here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    InputAgentState,
    ModelCallLimitMiddleware,
    hook_config,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from clue_api.arv2.account_research_refusals import refusal_json
from clue_api.arv2.account_research_tools import ToolRuntime
from clue_obs import get_logger

log = get_logger("clue_api.arv2.account_research_agent")

__all__ = ["AgentOutcome", "AgentStopReason", "run_account_agent"]

#: How long the loop waits for provider hops that were still in flight when a cap fired. They are
#: shielded from cancellation precisely so their ledger rows land, so this is the bound on
#: *waiting*, never on the hop.
_INFLIGHT_DRAIN_S = 60.0

#: How much of an unexpected exception is recorded on the outcome. Enough to name the failure in
#: the job row without turning a stack trace into a database column.
_ERROR_CHARS = 500

AgentStopReason = Literal["finalized", "round_cap", "runtime_cap", "model_error"]


@dataclass(frozen=True)
class AgentOutcome:
    """How one account job's loop ended, and what it spent getting there.

    ``reason`` is the whole vocabulary: the agent finalized, it ran out of rounds, it ran out of
    time, or the graph raised. There is no fifth ending, and none of them is an exception.
    """

    reason: AgentStopReason
    model_rounds: int
    tool_calls: int
    error: str | None


class _RoundCounter(AgentMiddleware[Any, Any, Any]):
    """Counts the model calls that actually happened, for the job row and the receipt."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        self.count += 1
        return await handler(request)


class _RoundShapeMiddleware(AgentMiddleware[Any, Any, Any]):
    """Cap the parallel wave: the first ``limit`` calls of a round run, the rest are refused.

    The cap is applied at the *tool* boundary rather than by truncating the model's message,
    because a truncated ``AIMessage`` leaves tool calls that never receive a result, and a
    provider replaying that history rejects the whole conversation. Refusing each excess call
    keeps the wave complete: N calls, N results, of which the last few say
    ``too_many_parallel_calls`` and name the ceiling.
    """

    def __init__(self, *, limit: int, runtime: ToolRuntime) -> None:
        super().__init__()
        self._limit = limit
        self._runtime = runtime

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = dict(request.tool_call)
        position = self._position(request.state, str(call.get("id") or ""))
        if position is not None and position >= self._limit:
            detail = (
                f"this call is number {position + 1} of the round; the first {self._limit} ran and "
                "the rest are refused"
            )
            log.info(
                "arv2.account_round_shape_refused",
                tool=str(call.get("name") or ""),
                position=position,
                limit=self._limit,
            )
            return ToolMessage(
                content=refusal_json("too_many_parallel_calls", detail),
                tool_call_id=str(call.get("id") or ""),
                name=str(call.get("name") or ""),
                status="error",
            )
        return await handler(request)

    @staticmethod
    def _position(state: Any, call_id: str) -> int | None:
        """Where this call sits in the wave its own model turn proposed."""
        messages = state.get("messages", ()) if isinstance(state, dict) else ()
        for message in reversed(tuple(messages)):
            if isinstance(message, AIMessage) and message.tool_calls:
                ids = [str(item.get("id") or "") for item in message.tool_calls]
                return ids.index(call_id) if call_id in ids else None
        return None


class _FinalizeEndsMiddleware(AgentMiddleware[Any, Any, Any]):
    """End the graph as soon as the job has a finalization, before another model call."""

    def __init__(self, runtime: ToolRuntime) -> None:
        super().__init__()
        self._runtime = runtime

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del state, runtime
        return {"jump_to": "end"} if self._runtime.finalization is not None else None


async def run_account_agent(
    *,
    model: BaseChatModel,
    system_prompt: str,
    tools: Sequence[StructuredTool],
    runtime: ToolRuntime,
    max_model_rounds: int,
    max_tool_calls_per_round: int,
    max_runtime_s: float,
    task_instruction: str,
) -> AgentOutcome:
    """Run one account job's agent to one of its four endings. Never raises.

    A graph that ends with no finalization is reported as ``round_cap`` whether the ceiling fired
    or the model simply stopped calling tools: both are "the job ended without the one decision it
    was asked for", which is what the receipt and the reviewer need to know.
    """

    rounds = _RoundCounter()
    agent = create_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        middleware=[
            rounds,
            _RoundShapeMiddleware(limit=max_tool_calls_per_round, runtime=runtime),
            _FinalizeEndsMiddleware(runtime),
            ModelCallLimitMiddleware(run_limit=max_model_rounds, exit_behavior="end"),
        ],
        name="clue-arv2-account",
    )
    opening = InputAgentState(messages=[HumanMessage(content=task_instruction)])
    # The graph takes one step per node, so the ceiling has to cover every round's model call, its
    # tool wave and the middleware hops around them, plus the entry and exit nodes. Below this the
    # graph would raise GraphRecursionError long before the round cap it is supposed to defer to.
    config = RunnableConfig(recursion_limit=max_model_rounds * (max_tool_calls_per_round + 2) + 4)
    try:
        await asyncio.wait_for(
            agent.ainvoke(opening, config=config),
            timeout=max_runtime_s,
        )
    except TimeoutError:
        await runtime.wait_for_inflight(timeout_s=_INFLIGHT_DRAIN_S)
        log.info(
            "arv2.account_agent_runtime_cap",
            model_rounds=rounds.count,
            tool_calls=runtime.tool_calls,
        )
        return AgentOutcome("runtime_cap", rounds.count, runtime.tool_calls, None)
    except Exception as error:  # noqa: BLE001 — the graph's failures are outcomes, never raises
        await runtime.wait_for_inflight(timeout_s=_INFLIGHT_DRAIN_S)
        log.exception("arv2.account_agent_failed", model_rounds=rounds.count)
        detail = f"{type(error).__name__}: {error}"[:_ERROR_CHARS]
        return AgentOutcome("model_error", rounds.count, runtime.tool_calls, detail)
    if runtime.finalization is not None:
        return AgentOutcome("finalized", rounds.count, runtime.tool_calls, None)
    return AgentOutcome("round_cap", rounds.count, runtime.tool_calls, None)
