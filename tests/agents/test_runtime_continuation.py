"""A continued turn that crashes is redelivered without duplicating history (spec 2026-09-29 §3.3).

The rule lives in :class:`DeepAgentTurnRuntime`: once a turn's own saved state exists, a re-run
resumes it and re-inserts nothing — neither the continued conversation nor this turn's additions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, cast
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from clue_agents import AgentTurnRequest, AssembledAgentContext, DeepAgentTurnRuntime
from clue_agents.model import ScriptedAgentChatModel
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ExecutionId
from tests.agents.test_contracts import context_manifest
from tests.agents.test_runtime import _CaptureModelInput, _Execution, _request
from tests.db.conftest import run_async

RESUMED_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-00000000e0a1"))
ANSWER_A = "Turn A's answer: start with the GI groups."
MESSAGE_B = "Turn B: what about ambulatory centers?"


class _SharedSaverExecution(_Execution):
    """One saver for every run — the durable checkpoint store a redelivered turn finds again."""

    def __init__(self, saver: InMemorySaver) -> None:
        super().__init__()
        self._saver = saver

    def checkpointer(
        self, *, execution_id: ExecutionId
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]:
        del execution_id

        @asynccontextmanager
        async def opened() -> AsyncIterator[BaseCheckpointSaver[str]]:
            yield self._saver

        return opened()

    async def recover(self, *, execution_id: ExecutionId) -> Any:
        del execution_id
        self.recover_calls += 1
        return self.recovered


class _CrashingModel(ScriptedAgentChatModel):
    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("worker died mid-turn")


class _Models:
    def __init__(self, model: ScriptedAgentChatModel) -> None:
        self.model = model

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        return self.model


class _FirstRequest(_CaptureModelInput):
    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        if not self.messages:
            super().on_chat_model_start(serialized, messages, **kwargs)


def _run(
    request: AgentTurnRequest,
    resolved: Any,
    execution: _SharedSaverExecution,
    model: ScriptedAgentChatModel,
    messages: tuple[BaseMessage, ...],
    *,
    continuation_config: dict[str, Any] | None,
    capture: _CaptureModelInput | None = None,
) -> Any:
    runtime = DeepAgentTurnRuntime(
        models=_Models(model),
        execution=execution,
        max_runtime_s=10,
        continuation_config=continuation_config,
    )
    tools = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    ).build()
    return run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,
            context=AssembledAgentContext(
                manifest=context_manifest().model_copy(
                    update={"execution_id": request.constitution.execution_id}
                ),
                messages=messages,
            ),
            backend=None,
            governed_tools=tools,
            callbacks=(capture,) if capture is not None else (),
        )
    )


def test_a_redelivered_continued_turn_resumes_without_duplicating_history() -> None:
    request_b, resolved = _request()
    saver = InMemorySaver()
    execution = _SharedSaverExecution(saver)

    # Turn A: an earlier turn of the thread, settled, under its own execution id.
    constitution_a = request_b.constitution.model_copy(update={"execution_id": RESUMED_EXECUTION})
    request_a = request_b.model_copy(
        update={"constitution": constitution_a, "turn_id": UUID(int=0xA)}
    )
    _run(
        request_a,
        resolved,
        execution,
        # Two plain answers: the first is refused and repaired away, the second ends the graph
        # settled (the shape of ``test_real_deepagent_normal_stop_is_failed_without_finalize_…``),
        # so the second is what A's saved conversation holds.
        ScriptedAgentChatModel(
            responses=(AIMessage(content="A draft the repair drops."), AIMessage(content=ANSWER_A))
        ),
        (HumanMessage(content="Turn A: who first?"),),
        continuation_config=None,
    )
    continuation = {"configurable": {"thread_id": str(RESUMED_EXECUTION), "checkpoint_ns": ""}}

    # Turn B continues A — and its worker dies at the first model call, after the merged state
    # was seeded.
    crashed = _run(
        request_b,
        resolved,
        execution,
        _CrashingModel(responses=(AIMessage(content="never"),)),
        (HumanMessage(content=MESSAGE_B),),
        continuation_config=continuation,
    )
    assert crashed.status.value == "failed"

    # Redelivery: the same turn, same execution, same continuation.
    capture = _FirstRequest()
    _run(
        request_b,
        resolved,
        execution,
        ScriptedAgentChatModel(
            responses=(AIMessage(content="Turn B's answer."), AIMessage(content="Done."))
        ),
        (HumanMessage(content=MESSAGE_B),),
        continuation_config=continuation,
        capture=capture,
    )
    sent = [str(getattr(message, "content", "")) for message in capture.messages[0]]
    assert sent.count(ANSWER_A) == 1
    assert sent.count(MESSAGE_B) == 1
