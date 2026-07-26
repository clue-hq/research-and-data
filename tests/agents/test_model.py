from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from clue_agents import ScriptedAgentChatModel


class _ReadInput(BaseModel):
    project_id: str


def test_scripted_agent_model_is_deterministic_and_supports_tool_binding() -> None:
    model = ScriptedAgentChatModel(
        responses=(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "_ReadInput",
                        "args": {"project_id": "project-1"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="finalized"),
        )
    )
    bound = model.bind_tools([_ReadInput])

    first = bound.invoke("read")
    second = asyncio.run(bound.ainvoke("finish"))

    assert first.tool_calls[0]["args"] == {"project_id": "project-1"}
    assert second.content == "finalized"
    with pytest.raises(RuntimeError, match="exhausted"):
        bound.invoke("extra")


def test_scripted_agent_model_can_repeat_last_response_explicitly() -> None:
    model = ScriptedAgentChatModel(
        responses=(AIMessage(content="same"),),
        repeat_last=True,
    )
    assert model.invoke("one").content == "same"
    assert model.invoke("two").content == "same"
