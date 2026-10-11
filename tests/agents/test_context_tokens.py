"""Conversation size is counted in the model's real tokens, not a character estimate.

Run 4 (2026-10-10, GPT-6.1-Sol): compaction set at 150k estimated tokens fired at about 128k real
ones — the character estimate overcounted Sol by ~17%, and LangChain's own correction never runs
for us (it only trusts a reply whose provider label equals the model's, and ours differ). Every
reply carries the provider's exact count of the request that produced it; that count, against our
estimate of the same request, calibrates every later count in the conversation.
"""

from __future__ import annotations

import asyncio
import math

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from clue_agents.compaction import CompactionSettings, build_compaction_middleware
from clue_agents.context_tokens import (
    PROMPT_ESTIMATE_KEY,
    ContextTokenCounter,
    estimate_tokens,
    real_token_ratio,
)


def _reply(sent_estimate: int | None, real_input: int | None, content: str = "ok") -> AIMessage:
    message = AIMessage(content)
    if sent_estimate is not None:
        message.response_metadata[PROMPT_ESTIMATE_KEY] = sent_estimate
    if real_input is not None:
        message.usage_metadata = {
            "input_tokens": real_input,
            "output_tokens": 10,
            "total_tokens": real_input + 10,
        }
    return message


def test_without_a_counted_reply_the_count_is_the_character_estimate():
    messages = [HumanMessage("x" * 4_000)]
    assert ContextTokenCounter()(messages) == estimate_tokens(messages)


def test_a_counted_reply_makes_the_already_sent_part_exact():
    sent = [HumanMessage("x" * 40_000)]
    estimate = estimate_tokens(sent)
    real = math.floor(estimate * 0.83)  # the estimate overcounts this model, as it did Sol's
    reply = _reply(estimate, real)
    tail = ToolMessage("y" * 8_000, tool_call_id="c1")
    counted = ContextTokenCounter()([*sent, reply, tail])
    # Exact for what the provider counted, calibrated for what was added since.
    assert counted == math.ceil(estimate_tokens([*sent, reply, tail]) * real / estimate)
    # That is: the provider's real count, plus the new part at this conversation's real rate.
    assert abs(counted - (real + real / estimate * estimate_tokens([reply, tail]))) <= 2


def test_the_newest_counted_reply_calibrates():
    messages = [
        HumanMessage("a" * 4_000),
        _reply(1_000, 2_000),
        HumanMessage("b" * 4_000),
        _reply(2_000, 1_500),
        HumanMessage("c" * 40),
    ]
    assert real_token_ratio(messages) == 0.75


def test_a_reply_without_usage_or_estimate_is_skipped():
    messages = [HumanMessage("a"), _reply(1_000, 900), _reply(None, 5_000), _reply(2_000, None)]
    assert real_token_ratio(messages) == 0.9


def test_the_calibration_carries_over_to_a_slice_without_a_reply():
    """The summariser measures its kept tail on slices that may hold no reply."""
    counter = ContextTokenCounter()
    counter([HumanMessage("a" * 4_000), _reply(1_000, 500)])
    tail = [ToolMessage("y" * 4_000, tool_call_id="c1")]
    assert counter(tail) == math.ceil(estimate_tokens(tail) * 0.5)


def test_tool_schemas_are_part_of_the_count():
    tools = [{"name": "read_file", "description": "d" * 4_000, "parameters": {}}]
    messages = [HumanMessage("a")]
    assert ContextTokenCounter()(messages, tools=tools) > ContextTokenCounter()(messages)


def _summariser(trigger_tokens: int):
    model = FakeMessagesListChatModel(responses=[AIMessage("summary")])
    settings = CompactionSettings(0.9, 0.1, trigger_tokens, 6, None)
    return build_compaction_middleware(model, None, settings)[0], model


def test_compaction_triggers_on_real_tokens_not_the_estimate():
    summariser, _ = _summariser(trigger_tokens=10_000)
    sent = [HumanMessage("x" * 44_000)]  # ~11k estimated: over the trigger by the estimate
    estimate = estimate_tokens(sent)
    messages = [*sent, _reply(estimate, int(estimate * 0.8))]  # ~8.8k real: under it
    total = summariser._count_tokens(messages, None, [])
    assert total < 10_000
    assert not summariser._should_summarize(messages, total)
    # And the other way round: an undercounting estimate still compacts on time.
    sent = [HumanMessage("x" * 36_000)]  # ~9k estimated: under the trigger by the estimate
    estimate = estimate_tokens(sent)
    messages = [*sent, _reply(estimate, int(estimate * 1.3))]  # ~11.7k real: over it
    total = summariser._count_tokens(messages, None, [])
    assert total > 10_000 and summariser._should_summarize(messages, total)


def test_every_reply_records_the_estimate_of_the_request_that_produced_it():
    summariser, model = _summariser(trigger_tokens=1_000_000)
    system = SystemMessage("s" * 2_000)
    messages = [HumanMessage("x" * 8_000)]
    tools = [{"name": "read_file", "description": "d" * 400, "parameters": {}}]
    reply = AIMessage(
        "done", usage_metadata={"input_tokens": 9, "output_tokens": 1, "total_tokens": 10}
    )

    async def handler(request):
        return ModelResponse(result=[reply])

    request = ModelRequest(
        model=model, messages=messages, system_message=system, tools=tools, state={}, runtime=None
    )
    asyncio.run(summariser.awrap_model_call(request, handler))
    assert reply.response_metadata[PROMPT_ESTIMATE_KEY] == estimate_tokens(
        [system, *messages], tools=tools
    )
