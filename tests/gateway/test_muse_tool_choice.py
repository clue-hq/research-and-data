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


def test_deep_schema_keeps_full_guidance_and_local_validation():
    import json

    from langchain_core.utils.function_calling import convert_to_openai_tool
    from pydantic import ValidationError

    from clue_api.arv2.quality_owned_narrative import WriteNarrativeInput

    schema = convert_to_openai_tool(WriteNarrativeInput)
    original = json.loads(json.dumps(schema))
    client = OpenRouterChatModel(
        model="meta/muse-spark-1.3", api_key="test-unused", use_responses_api=False
    )
    p = client._get_request_payload(
        [HumanMessage(content="Write the narrative")], tools=[schema], tool_choice="required"
    )

    def depth(x):
        if isinstance(x, (dict, list)):
            return 1 + max(
                (depth(v) for v in (x.values() if isinstance(x, dict) else x)), default=0
            )
        return 0

    adapted = p["tools"][0]["function"]["parameters"]
    assert depth(adapted) <= 10
    assert "Full schema for this value" in json.dumps(adapted)
    assert "finding_ids" in json.dumps(adapted)
    assert "account_finding_ids" in json.dumps(adapted)
    assert p["tools"][0]["function"]["strict"] is False
    assert (
        schema == original
    )  # Provider payload transformation must not mutate authoritative input.
    with pytest.raises(ValidationError):
        WriteNarrativeInput.model_validate(
            {
                "dossier_version": 1,
                "pages": [
                    {
                        "page": "overview",
                        "sections": [
                            {
                                "key": "what-they-do",
                                "items": [
                                    {"h2": "Invalid empty statement", "body": [{"text": ""}]}
                                ],
                            }
                        ],
                    }
                ],
            }
        )
