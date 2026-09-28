"""Muse wire compatibility does not change governed completion authority."""

import pytest
from langchain_core.messages import HumanMessage

from clue_gateway.openrouter_chat import OpenRouterChatModel

TOOLS = [
    {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object", "properties": {}}},
    }
    for name in ("read_file", "finalize_turn")
]


def payload(choice, model="meta/muse-spark-1.3"):
    client = OpenRouterChatModel(model=model, api_key="test-unused", use_responses_api=False)
    return client._get_request_payload(
        [HumanMessage(content="Complete the task")], tools=TOOLS, tool_choice=choice
    )


@pytest.mark.parametrize("choice", ["required", "any", "auto"])
def test_muse_offers_tools_with_auto(choice):
    p = payload(choice)
    assert p["tool_choice"] == "auto"
    assert p["tools"] == TOOLS


def test_muse_finalize_only_cannot_offer_other_tools():
    p = payload({"type": "function", "function": {"name": "finalize_turn"}})
    assert p["tool_choice"] == "auto"
    assert p["tools"] == [TOOLS[1]]


def test_muse_disabled_tools_remain_disabled():
    p = payload("none")
    assert "tools" not in p and "tool_choice" not in p


def test_muse_unknown_named_choice_fails_before_request():
    with pytest.raises(ValueError, match="exactly one"):
        payload({"type": "function", "function": {"name": "unknown"}})


def test_other_models_keep_required_choice():
    assert payload("required", "x-ai/grok-4.6")["tool_choice"] == "required"
