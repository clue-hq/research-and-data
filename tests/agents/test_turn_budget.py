"""Turn limits end through ``finalize_turn``, never by a crash (founder ruling 2026-09-27).

Offline: a real deepagent graph, a fake model and the Head-of-ABM tool surface. The model asks for
the cheap framework tool ``write_todos`` every round and calls ``finalize_turn`` only once it is
the one tool offered. So the round count it reaches is the round count the runtime really allows:
if a new middleware hook costs another graph step per round, ``superstep_ceiling`` stops the graph
early and these tests fail instead of the budget quietly shrinking.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, cast

import pytest
from langchain.tools import tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

import clue_agents.runtime as runtime_module
from clue_agents import AgentExecutionStatus, AssembledAgentContext, DeepAgentTurnRuntime
from clue_agents.runtime import (
    WRAP_UP_WARNING_ROUNDS,
    TurnBudgetMiddleware,
    superstep_ceiling,
)
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.conftest import artifact
from tests.agents.test_contracts import context_manifest
from tests.agents.test_runtime import _Execution, _NeverRespondingModels, _request
from tests.db.conftest import run_async

_NOTICE = "Platform notice (not from the user)"


class _Call:
    def __init__(self, tools: Sequence[str], tool_choice: object, notice: str | None) -> None:
        self.tools = tuple(tools)
        self.tool_choice = tool_choice
        self.notice = notice


class _ProbeModel(BaseChatModel):
    """Works (``write_todos``) while it may; finalizes when only ``finalize_turn`` is offered."""

    _calls: list[_Call] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "turn-budget-probe"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: object = None, **kwargs: Any):
        del kwargs
        names = [getattr(t, "name", None) or t.get("name") or t["function"]["name"] for t in tools]
        return self.bind(probe_tools=names, probe_tool_choice=tool_choice)

    def _generate(self, messages: list[BaseMessage], stop: Any = None, **kwargs: Any) -> ChatResult:
        raise NotImplementedError

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        del stop, run_manager
        tools = kwargs.get("probe_tools", ())
        last = messages[-1]
        notice = (
            str(last.content)
            if isinstance(last, HumanMessage) and str(last.content).startswith(_NOTICE)
            else None
        )
        self._calls.append(_Call(tools, kwargs.get("probe_tool_choice"), notice))
        index = len(self._calls)
        if list(tools) == ["finalize_turn"]:
            call = {"name": "finalize_turn", "args": {}, "id": f"finalize-{index}"}
        else:
            call = {"name": "write_todos", "args": {"todos": []}, "id": f"todo-{index}"}
        message = AIMessage(content="", tool_calls=[{**call, "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=message)])


class _ProbeModels:
    def __init__(self) -> None:
        self.model = _ProbeModel()

    def build(self, **kwargs: Any) -> _ProbeModel:
        del kwargs
        return self.model


def _run_probe(
    *,
    max_rounds: int,
    wrap_up_status: str = "blocked",
    refusals: int = 0,
    long_turn_alert_s: float | None = None,
) -> tuple[Any, list[_Call]]:
    """Run one turn; the stand-in ``finalize_turn`` refuses ``refusals`` times, then commits."""
    request, resolved = _request()
    execution = _Execution()
    models = _ProbeModels()
    attempts = {"n": 0}

    @tool(return_direct=True)
    async def finalize_turn() -> str:
        """Commit the test finalization with the status the wrap-up asks for."""
        attempts["n"] += 1
        if attempts["n"] <= refusals:
            raise ValueError("refused for the test: repair and finalize again")
        ref = artifact("turn-budget-finalization.json")
        execution.recovered = {"finalization_status": wrap_up_status, "finalization_ref": ref}
        return ref.model_dump_json()

    runtime = DeepAgentTurnRuntime(
        models=cast(Any, models),
        execution=execution,
        max_runtime_s=None,
        max_rounds=max_rounds,
        wrap_up_status=cast(Any, wrap_up_status),
        long_turn_alert_s=long_turn_alert_s,
    )
    governed = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    ).build()
    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content="Research until told to stop."),),
            ),
            backend=None,
            governed_tools=(*governed[:-1], finalize_turn),
        )
    )
    return outcome, models.model._calls


@pytest.mark.parametrize("max_rounds", [12, 350])
def test_an_agent_reaches_every_configured_round_and_ends_through_finalize(
    max_rounds: int,
) -> None:
    # Two refused finalizations use the two repair rounds kept inside the budget, so the turn
    # makes exactly ``max_rounds`` model calls — and still ends committed, not crashed.
    outcome, calls = _run_probe(max_rounds=max_rounds, refusals=2)

    assert outcome.status is AgentExecutionStatus.BLOCKED
    assert outcome.finalization_ref is not None
    assert len(calls) == max_rounds

    finalize_round = max_rounds - 2
    warned = range(finalize_round - WRAP_UP_WARNING_ROUNDS, finalize_round)
    for number, call in enumerate(calls, start=1):
        if number < warned.start:
            assert call.notice is None, number
            assert "write_todos" in call.tools and len(call.tools) > 1
        elif number in warned:
            left = finalize_round - number
            assert call.notice is not None and f"{left} model round" in call.notice, number
            assert "write_todos" in call.tools, number
        else:
            assert call.tools == ("finalize_turn",), number
            assert call.tool_choice == "finalize_turn"
            assert call.notice is not None and "reached its round limit" in call.notice
            assert 'status "blocked"' in call.notice


def test_the_fuse_leaves_room_above_the_round_limit() -> None:
    # Five graph steps a round today; the fuse allows six, plus headroom.
    assert superstep_ceiling(350) == 350 * 6 + 10


def test_a_chat_turn_wraps_up_by_asking_the_human_to_continue() -> None:
    outcome, calls = _run_probe(max_rounds=6, wrap_up_status="awaiting_input")

    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    notices = [call.notice for call in calls if call.notice]
    assert notices and all('status "awaiting_input"' in n for n in notices)
    assert all('reply "continue"' in n for n in notices)


class _Request:
    """The four members ``TurnBudgetMiddleware.awrap_model_call`` reads."""

    def __init__(self, round_number: int) -> None:
        self.state = {"turn_budget_rounds": round_number, "turn_id": "t"}
        self.tools = [{"name": "write_todos"}, {"name": "finalize_turn"}]
        self.messages: list[BaseMessage] = [HumanMessage(content="work")]
        self.tool_choice: object = "required"

    def override(self, **fields: Any) -> _Request:
        clone = _Request(self.state["turn_budget_rounds"])
        clone.tools, clone.messages, clone.tool_choice = self.tools, self.messages, self.tool_choice
        for key, value in fields.items():
            setattr(clone, key, value)
        return clone


def _seen(middleware: TurnBudgetMiddleware, round_number: int) -> _Request:
    seen: list[_Request] = []

    async def handler(request: _Request) -> None:
        seen.append(request)

    asyncio.run(middleware.awrap_model_call(_Request(round_number), handler))
    return seen[0]


def test_near_a_time_limit_the_agent_is_warned_three_times_then_finalizes() -> None:
    now = {"t": 0.0}
    middleware = TurnBudgetMiddleware(
        max_rounds=350, wrap_up_status="blocked", max_runtime_s=1200, clock=lambda: now["t"]
    )

    now["t"] = 100  # 1100 s left: nothing to say
    assert _seen(middleware, 5).tool_choice == "required"
    for elapsed in (1030, 1040, 1050):  # under 180 s left: three warned calls
        now["t"] = elapsed
        request = _seen(middleware, 6)
        assert "minutes of its time limit" in str(request.messages[-1].content)
        assert len(request.tools) == 2
    now["t"] = 1060
    request = _seen(middleware, 7)
    assert [t["name"] for t in request.tools] == ["finalize_turn"]
    assert "reached its time limit" in str(request.messages[-1].content)


def test_under_a_minute_left_the_next_call_is_finalize_only() -> None:
    now = {"t": 0.0}
    middleware = TurnBudgetMiddleware(
        max_rounds=350, wrap_up_status="blocked", max_runtime_s=1200, clock=lambda: now["t"]
    )
    now["t"] = 1150
    assert [t["name"] for t in _seen(middleware, 3).tools] == ["finalize_turn"]


def test_a_short_turn_scales_its_time_windows_down() -> None:
    # A 60 s turn warns in its last 15 s (a quarter) and is finalize-only in its last 6 s.
    now = {"t": 0.0}
    middleware = TurnBudgetMiddleware(
        max_rounds=24, wrap_up_status="blocked", max_runtime_s=60, clock=lambda: now["t"]
    )
    now["t"] = 1
    assert _seen(middleware, 1).tool_choice == "required"
    now["t"] = 50
    assert len(_seen(middleware, 2).tools) == 2
    now["t"] = 55
    assert [t["name"] for t in _seen(middleware, 3).tools] == ["finalize_turn"]


def test_without_a_time_limit_only_the_round_budget_applies() -> None:
    middleware = TurnBudgetMiddleware(max_rounds=350, wrap_up_status="blocked", max_runtime_s=None)
    assert _seen(middleware, 300).tool_choice == "required"


def test_a_long_turn_alerts_once_and_is_not_stopped_by_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        runtime_module, "sentry_warn", lambda message, **kw: alerts.append((message, kw))
    )
    request, resolved = _request()
    execution = _Execution()
    runtime = DeepAgentTurnRuntime(
        models=cast(Any, _NeverRespondingModels()),
        execution=execution,
        max_runtime_s=0.3,
        long_turn_alert_s=0.05,
    )
    governed = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    ).build()
    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(), messages=(HumanMessage(content="Wait."),)
            ),
            backend=None,
            governed_tools=governed,
        )
    )

    # The alert fired while the turn was still running; the turn then ended on its own timeout.
    assert len(alerts) == 1
    message, fields = alerts[0]
    assert "turn still running" in message
    assert fields["fingerprint"][0] == "agent-long-turn"
    assert fields["tags"]["turn_id"] == str(request.turn_id)
    assert outcome.failure_code == "agent_timeout"


def test_a_turn_that_ends_early_never_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(runtime_module, "sentry_warn", lambda message, **kw: alerts.append(message))
    outcome, _ = _run_probe(max_rounds=6, long_turn_alert_s=60)
    assert outcome.finalization_ref is not None
    assert alerts == []
