"""The account agent's loop: the caps, the finalization, and the failure law at the graph edge.

The model is scripted rather than live (Global Constraint 3 governs *provider bodies*; a model that
answers over the wire is exactly what a loop test must not do — the loop's shape is what is under
test, not the model's judgement). The tools are small doubles that count on the real
:class:`~clue_api.arv2.account_research_tools.ToolRuntime`, so the four caps are asserted against
the same object the twelve governed tools mutate.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, PrivateAttr

from clue_api.arv2.account_research_agent import AgentOutcome, run_account_agent
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_tools import ToolRuntime
from clue_api.arv2.gemini_media_client import MediaBudget
from clue_api.arv2.structuring_client import FieldCatalog, FieldSpec
from clue_config import Settings
from clue_core import EntityId

SCOPE = JobScope(
    workspace_id="ws-1",
    project_id="prj-1",
    project_run_id=uuid4(),
    run_id=uuid4(),
    job_id=uuid4(),
    account_id=EntityId(uuid4()),
    account_name="Probook",
    account_domain="probook.ai",
    icp_markdown="# icp",
    persona_markdown="# personas",
    already_established="",
    effort="full",
    committee_cap=4,
    today=date(2026, 9, 8),
)

CATALOG = FieldCatalog(account=(FieldSpec("core.industry", "Industry."),))


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class _NullConnFactory:
    """A connection factory whose connection is never spoken to."""

    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        yield object()


class _Artifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        raise AssertionError("the loop tests buffer no raw bodies")


def _runtime() -> ToolRuntime:
    return ToolRuntime(
        scope=SCOPE,
        settings=Settings(_env_file=None),
        clients=object(),  # type: ignore[arg-type]
        conn_factory=_NullConnFactory(),
        artifacts=_Artifacts(),
        writer=object(),  # type: ignore[arg-type]
        catalog=CATALOG,
        media_budget=MediaBudget(9000),
        now=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )


class _NoArgs(BaseModel):
    pass


def _counting_tool(
    runtime: ToolRuntime, *, name: str = "read_account_state", sleep_s: float = 0.0
) -> StructuredTool:
    """A tool shaped like a governed one: it counts on the runtime and returns a JSON string."""

    async def call() -> str:
        runtime.tool_calls += 1
        if sleep_s:
            await asyncio.sleep(sleep_s)
        return json.dumps({"ok": True})

    return StructuredTool.from_function(
        coroutine=call, name=name, description="a counted tool", args_schema=_NoArgs
    )


def _finalizing_tool(runtime: ToolRuntime) -> StructuredTool:
    async def call() -> str:
        runtime.tool_calls += 1
        runtime.finalization = {"summary": "done", "fit_verdicts": [], "gaps": []}
        return json.dumps({"accepted": True})

    return StructuredTool.from_function(
        coroutine=call, name="finalize_research", description="finish once", args_schema=_NoArgs
    )


class _ScriptedModel(BaseChatModel):
    """Deterministic model: one scripted reply per call, over the real LangGraph machinery."""

    _respond: Callable[[list[BaseMessage]], AIMessage] = PrivateAttr()
    _seen: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    def __init__(self, respond: Callable[[list[BaseMessage]], AIMessage]) -> None:
        super().__init__()
        self._respond = respond
        self._seen = []

    @property
    def _llm_type(self) -> str:
        return "arv2-account-scripted"

    @property
    def seen(self) -> list[list[BaseMessage]]:
        return self._seen

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        **kwargs: Any,
    ) -> _ScriptedModel:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self._seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self._respond(messages))])


def _call(name: str, index: int) -> dict[str, Any]:
    return {"name": name, "args": {}, "id": f"call-{index}", "type": "tool_call"}


async def _drive(
    model: BaseChatModel,
    tools: Sequence[StructuredTool],
    runtime: ToolRuntime,
    *,
    max_model_rounds: int = 4,
    max_tool_calls_per_round: int = 5,
    max_runtime_s: float = 30.0,
) -> AgentOutcome:
    return await run_account_agent(
        model=model,
        system_prompt="you research one account",
        tools=tools,
        runtime=runtime,
        max_model_rounds=max_model_rounds,
        max_tool_calls_per_round=max_tool_calls_per_round,
        max_runtime_s=max_runtime_s,
        task_instruction="Research this account in full.",
    )


def test_round_cap_ends_the_loop_and_reports_round_cap() -> None:
    runtime = _runtime()
    model = _ScriptedModel(
        lambda messages: AIMessage(content="", tool_calls=[_call("read_account_state", 1)])
    )

    outcome = _run(_drive(model, [_counting_tool(runtime)], runtime, max_model_rounds=3))

    assert outcome.reason == "round_cap"
    assert outcome.model_rounds == 3
    assert outcome.tool_calls == 3
    assert outcome.error is None
    assert runtime.finalization is None


def test_more_than_the_per_round_cap_refuses_the_excess_not_the_round() -> None:
    runtime = _runtime()
    rounds = {"n": 0}

    def respond(messages: list[BaseMessage]) -> AIMessage:
        rounds["n"] += 1
        if rounds["n"] == 1:
            return AIMessage(
                content="",
                tool_calls=[_call("read_account_state", index) for index in range(7)],
            )
        return AIMessage(content="I stop here.")

    model = _ScriptedModel(respond)

    outcome = _run(_drive(model, [_counting_tool(runtime)], runtime, max_tool_calls_per_round=5))

    assert runtime.tool_calls == 5, "only the calls within the ceiling run"
    delivered = [
        message
        for message in model.seen[-1]
        if isinstance(message, ToolMessage) and "too_many_parallel_calls" in str(message.content)
    ]
    assert len(delivered) == 2, "every dropped call comes back as its own refusal envelope"
    assert all(message.status == "error" for message in delivered)
    # The whole wave is answered: seven calls, seven tool messages, so the next model call is legal.
    assert len([m for m in model.seen[-1] if isinstance(m, ToolMessage)]) == 7
    assert outcome.reason == "round_cap"


def test_finalize_ends_the_loop() -> None:
    runtime = _runtime()
    rounds = {"n": 0}

    def respond(messages: list[BaseMessage]) -> AIMessage:
        rounds["n"] += 1
        if rounds["n"] == 1:
            return AIMessage(content="", tool_calls=[_call("finalize_research", 1)])
        raise AssertionError("the loop must end before a second model call")

    model = _ScriptedModel(respond)

    outcome = _run(_drive(model, [_finalizing_tool(runtime)], runtime, max_model_rounds=10))

    assert outcome.reason == "finalized"
    assert runtime.finalization is not None
    assert outcome.model_rounds == 1
    assert outcome.tool_calls == 1


def test_runtime_cap_ends_with_runtime_cap_after_inflight_tools_drain() -> None:
    runtime = _runtime()
    model = _ScriptedModel(
        lambda messages: AIMessage(content="", tool_calls=[_call("read_account_state", 1)])
    )

    outcome = _run(
        _drive(
            model,
            [_counting_tool(runtime, sleep_s=2.0)],
            runtime,
            max_model_rounds=50,
            max_runtime_s=0.5,
        )
    )

    assert outcome.reason == "runtime_cap"
    assert outcome.error is None
    assert outcome.model_rounds >= 1


def test_model_error_is_reported_not_raised() -> None:
    runtime = _runtime()
    rounds = {"n": 0}

    def respond(messages: list[BaseMessage]) -> AIMessage:
        rounds["n"] += 1
        if rounds["n"] == 1:
            return AIMessage(content="", tool_calls=[_call("read_account_state", 1)])
        raise RuntimeError("the provider hung up")

    model = _ScriptedModel(respond)

    outcome = _run(_drive(model, [_counting_tool(runtime)], runtime))

    assert outcome.reason == "model_error"
    assert outcome.error is not None and "RuntimeError" in outcome.error
    assert "hung up" in outcome.error
    assert outcome.tool_calls == 1
