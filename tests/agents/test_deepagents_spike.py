"""Executable C6.0 compatibility spike for the selected deepagents release."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from deepagents import DeepAgentState, create_deep_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr


class SpikeState(DeepAgentState):
    constitution_marker: str
    context_manifest_marker: str


class ScriptedToolCallingModel(BaseChatModel):
    """Small deterministic fake that still runs through real deepagents/LangGraph machinery."""

    _respond: Callable[[list[BaseMessage]], AIMessage] = PrivateAttr()
    _bound_tool_names: tuple[str, ...] = PrivateAttr(default=())

    def __init__(self, respond: Callable[[list[BaseMessage]], AIMessage]) -> None:
        super().__init__()
        self._respond = respond

    @property
    def _llm_type(self) -> str:
        return "c6-scripted-tool-calling-spike"

    @property
    def bound_tool_names(self) -> tuple[str, ...]:
        return self._bound_tool_names

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> ScriptedToolCallingModel:
        del tool_choice, kwargs
        names: list[str] = []
        for item in tools:
            if isinstance(item, BaseTool):
                names.append(item.name)
            elif isinstance(item, dict):
                function = item.get("function", {})
                names.append(str(function.get("name", item.get("name", ""))))
            else:
                names.append(getattr(item, "__name__", type(item).__name__))
        self._bound_tool_names = tuple(names)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=self._respond(messages))])


def test_real_deepagent_constructs_and_subagent_wakes_fresh_with_shared_state() -> None:
    observed: dict[str, object] = {}

    @tool
    def inspect_constitution(runtime: ToolRuntime) -> str:
        """Inspect only the trusted state supplied to this fresh child wake."""

        observed["constitution_marker"] = runtime.state["constitution_marker"]
        observed["context_manifest_marker"] = runtime.state["context_manifest_marker"]
        observed["child_messages"] = tuple(
            (message.type, str(message.content)) for message in runtime.state["messages"]
        )
        return "trusted state inspected"

    def parent_response(messages: list[BaseMessage]) -> AIMessage:
        if any(isinstance(message, ToolMessage) for message in messages):
            return AIMessage(content="Parent received the durable child receipt.")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {
                        "description": "Inspect the constitution and return only a receipt.",
                        "subagent_type": "research",
                    },
                    "id": "delegate-1",
                    "type": "tool_call",
                }
            ],
        )

    def child_response(messages: list[BaseMessage]) -> AIMessage:
        if any(isinstance(message, ToolMessage) for message in messages):
            return AIMessage(content="Child completed with a reference-only receipt.")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "inspect_constitution",
                    "args": {},
                    "id": "inspect-1",
                    "type": "tool_call",
                }
            ],
        )

    parent_model = ScriptedToolCallingModel(parent_response)
    child_model = ScriptedToolCallingModel(child_response)
    graph = create_deep_agent(
        model=parent_model,
        tools=[],
        system_prompt="C6 construction spike.",
        subagents=[
            {
                "name": "research",
                "description": "Fresh-wake governed research specialist.",
                "system_prompt": "Inspect the trusted constitution.",
                "model": child_model,
                "tools": [inspect_constitution],
            }
        ],
        state_schema=SpikeState,
        name="c6-spike-parent",
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="parent-only private conversation")],
            "constitution_marker": "constitution-sha-601",
            "context_manifest_marker": "context-sha-601",
        }
    )

    assert "task" in parent_model.bound_tool_names
    assert "inspect_constitution" in child_model.bound_tool_names
    assert observed["constitution_marker"] == "constitution-sha-601"
    assert observed["context_manifest_marker"] == "context-sha-601"
    child_messages = observed["child_messages"]
    assert isinstance(child_messages, tuple)
    assert child_messages[0] == (
        "human",
        "Inspect the constitution and return only a receipt.",
    )
    assert all("parent-only private conversation" not in content for _, content in child_messages)

    # Framework termination is observable but is not an honest C6 success by itself.  Only a
    # later AgentFinalizeEnvelope adapter may write this key.
    assert result["messages"][-1].content == "Parent received the durable child receipt."
    assert "finalize_envelope_artifact_key" not in result
