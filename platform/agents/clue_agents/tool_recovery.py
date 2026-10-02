"""Budget corrective model rounds only after the entire native tool batch has settled."""

import json
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from clue_agents.state import ClueDeepAgentState
from clue_obs import get_logger

MAX_TOOL_REPAIR_ROUNDS = 10
log = get_logger(__name__)


class ToolRepairRoundsMiddleware(AgentMiddleware[Any, Any, Any]):
    state_schema = ClueDeepAgentState

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del runtime
        turn = str(state.get("turn_id"))
        if state.get("tool_repair_turn") != turn:
            return {"tool_repair_turn": turn, "tool_repair_rounds": 0, "tool_repair_batch": []}
        messages = state.get("messages", ())
        latest = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if latest is None or not latest.tool_calls:
            return None
        calls = tuple(sorted(str(c["id"]) for c in latest.tool_calls))
        # Model call identities survive retries; checkpoint state survives message compaction.
        if list(calls) == state.get("tool_repair_batch"):
            return None
        results = {
            m.tool_call_id: m
            for m in messages
            if isinstance(m, ToolMessage) and m.tool_call_id in calls
        }
        if len(results) != len(calls):
            return None
        failures = []
        for call_id, message in results.items():
            try:
                body = json.loads(message.content) if isinstance(message.content, str) else None
            except (ValueError, TypeError):
                continue
            if isinstance(body, dict) and body.get("governed_repair_budgeted") is True:
                failures.append(call_id)
        rounds = state.get("tool_repair_rounds", 0)
        if failures:
            rounds += 1
            exhausted = rounds > MAX_TOOL_REPAIR_ROUNDS
            log.warning(
                "agent.tool_repair_batch",
                failed_calls=len(failures),
                batch_calls=len(calls),
                repair_round=rounds,
                exhausted=exhausted,
            )
            if exhausted:
                raise RuntimeError(
                    "governed tool repair rounds exhausted after complete batch feedback"
                )
        return {"tool_repair_rounds": rounds, "tool_repair_batch": list(calls)}
