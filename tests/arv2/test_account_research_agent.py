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
from decimal import Decimal
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
from clue_core.provider_failures import ProviderFailure

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
    attempt: int = 1,
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
        attempt=attempt,
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


def test_a_provider_timeout_inside_the_graph_is_a_model_error_not_the_runtime_cap() -> None:
    """The gateway's own timeout and our runtime cap are the same exception type and opposite
    endings: one is the provider failing, the other is us stopping. A job whose provider timed out
    must not be recorded as a job that ran out of time."""
    runtime = _runtime()

    def time_out(messages: list[BaseMessage]) -> AIMessage:
        del messages
        raise TimeoutError("the provider did not answer in 600s")

    model = _ScriptedModel(time_out)

    outcome = _run(_drive(model, [_counting_tool(runtime)], runtime, max_runtime_s=30.0))

    assert outcome.reason == "model_error"
    assert outcome.error is not None and outcome.error.startswith("TimeoutError: ")
    assert "did not answer" in outcome.error


# --- the agent's own model spend (R2-close task 2) ---------------------------------------------
#
# Every provider hop the tools make already lands on ``provider_call_ledger``. The model calls the
# loop itself makes are spend too, and until this they were invisible: the job's ``cost_usd`` was
# the tools' number alone.


def _metered_message(tool_calls: list[dict[str, Any]] | None = None) -> AIMessage:
    """An assistant turn stamped the way the governed gateway stamps one."""
    return AIMessage(
        content="" if tool_calls else "I stop here.",
        tool_calls=tool_calls or [],
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        response_metadata={
            "clue_cost_cents": "0.5",
            "clue_cost_source": "metered",
            "clue_answering_model": "x-ai/grok-4.6",
            "model_name": "x-ai/grok-4.6",
        },
    )


def test_every_model_round_lands_one_ledger_row_with_its_cost_and_tokens() -> None:
    runtime = _runtime()
    rounds = {"n": 0}

    def respond(messages: list[BaseMessage]) -> AIMessage:
        rounds["n"] += 1
        if rounds["n"] == 1:
            return _metered_message([_call("read_account_state", 1)])
        return _metered_message()

    outcome = _run(_drive(_ScriptedModel(respond), [_counting_tool(runtime)], runtime))

    rows = runtime.model_ledger.drain()
    assert len(rows) == outcome.model_rounds == 2
    first = rows[0]
    assert first.row_id == f"model:{SCOPE.job_id}:1:1"
    assert first.phase == "result"
    assert first.provider == "openrouter"
    assert first.operation == "agent_completion"
    assert first.label == "round-1"
    assert first.outcome == "ok"
    assert first.http_status == 200
    assert first.attempts == 1
    assert first.latency_ms is not None and first.latency_ms >= 0
    assert first.recorded_at == datetime(2026, 9, 8, tzinfo=UTC)
    assert first.cost_usd == Decimal("0.005")
    assert first.extras["model"] == "x-ai/grok-4.6"
    assert first.extras["prompt_tokens"] == 100
    assert first.extras["completion_tokens"] == 20
    assert first.extras["cached_prompt_tokens"] == 0
    assert first.extras["cost_source"] == "metered"
    assert [row.row_id for row in rows] == [
        f"model:{SCOPE.job_id}:1:1",
        f"model:{SCOPE.job_id}:1:2",
    ]
    # The receipt's summary is derived from the same rows.
    assert outcome.model_spend.calls == 2
    assert outcome.model_spend.usd == Decimal("0.010")
    assert outcome.model_spend.prompt_tokens == 200
    assert outcome.model_spend.completion_tokens == 40
    assert outcome.model_spend.cost_source == "metered"


def test_an_unpriced_model_call_records_no_money_rather_than_a_zero_it_invented() -> None:
    runtime = _runtime()

    def respond(messages: list[BaseMessage]) -> AIMessage:
        return AIMessage(
            content="nothing to do",
            usage_metadata={"input_tokens": 7, "output_tokens": 1, "total_tokens": 8},
            response_metadata={"clue_cost_cents": "0", "clue_cost_source": "unpriced"},
        )

    outcome = _run(_drive(_ScriptedModel(respond), [_counting_tool(runtime)], runtime))

    (row,) = runtime.model_ledger.drain()
    assert row.cost_usd is None, "an unpriced call is blank, never a fabricated zero"
    assert row.extras["cost_source"] == "unpriced"
    assert outcome.model_spend.cost_source == "unpriced"
    assert outcome.model_spend.usd == Decimal(0)


def test_a_model_call_that_raises_lands_a_transport_error_row_and_still_reports_model_error() -> (
    None
):
    runtime = _runtime()

    def respond(messages: list[BaseMessage]) -> AIMessage:
        raise RuntimeError("the provider hung up")

    outcome = _run(_drive(_ScriptedModel(respond), [_counting_tool(runtime)], runtime))

    assert outcome.reason == "model_error"
    (row,) = runtime.model_ledger.drain()
    assert row.outcome == "transport_error"
    assert row.error_code == "RuntimeError"
    assert row.cost_usd is None
    assert row.http_status is None
    assert "provider_failure" not in row.extras, "a fault nobody can classify names no provider"
    assert outcome.provider_failure is None


def test_a_re_driven_jobs_rounds_do_not_collide_with_its_first_attempts_rows() -> None:
    """The drain dedups on the row id, so a second attempt numbering its rounds from one again
    would silently drop them. The job's own attempt counter keeps the two runs disjoint."""

    def rows_for(attempt: int) -> list[str]:
        runtime = _runtime()
        _run(
            _drive(
                _ScriptedModel(lambda messages: _metered_message()),
                [_counting_tool(runtime)],
                runtime,
                attempt=attempt,
            )
        )
        return [row.row_id for row in runtime.model_ledger.drain()]

    first, second = rows_for(1), rows_for(2)

    assert first == [f"model:{SCOPE.job_id}:1:1"]
    assert second == [f"model:{SCOPE.job_id}:2:1"]
    assert not set(first) & set(second)


class _Denied(Exception):
    """A refusal shaped the way the OpenAI-compatible SDKs raise one: a status and a repr body."""

    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)',"
            " 'code': 403}}"
        )


def test_a_round_that_is_refused_stamps_the_provider_failure_on_its_ledger_row() -> None:
    """A refusal is the provider's decision, so the round row carries its verdict, not just a
    class name — that stamp is what the drain reads to open one durable incident."""

    runtime = _runtime()

    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        raise _Denied()

    outcome = _run(_drive(_ScriptedModel(respond), [_counting_tool(runtime)], runtime))

    assert outcome.reason == "model_error"
    (row,) = runtime.model_ledger.drain()
    assert row.error_code == "_Denied"
    assert row.extras["provider_failure"] == {
        "kind": "refusal",
        "reason": "key_limit",
        "message": "Key limit exceeded (weekly limit)",
    }
    assert outcome.provider_failure == ProviderFailure(
        "openrouter", "refusal", "key_limit", "Key limit exceeded (weekly limit)"
    )
