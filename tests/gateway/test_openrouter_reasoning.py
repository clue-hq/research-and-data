"""Wire regressions for the configured chat-completions route, with no provider spend."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage
from pydantic import SecretStr

from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import OpenRouterAgentModelProvider


def _stream_response(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/v1/chat/completions"
    payload = json.loads(request.content)
    assert payload["usage"] == {"include": True}
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["provider"] == {"sort": "throughput"}
    assert payload["stream_options"] == {"include_usage": True}
    frames = [
        {"delta": {"role": "assistant", "reasoning": "Check `a_long_identifier` "}},
        {
            "delta": {
                "reasoning": "then continue.",
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "then continue.", "index": 0}
                ],
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            }
        },
        {"delta": {}, "finish_reason": "tool_calls"},
    ]
    chunks = [
        {
            "id": "gen-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "x-ai/grok-4.6",
            "choices": [{"index": 0, **frame}],
        }
        for frame in frames
    ]
    chunks.append(
        {
            "id": "gen-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "x-ai/grok-4.6",
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 8,
                "total_tokens": 18,
                "cost": 0.002,
            },
        }
    )
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n",
    )


def _provider(respond: Any) -> Any:
    return OpenRouterAgentModelProvider(
        GatewayConfig(
            openrouter_chat_completions_fallback=True,
            openrouter_provider_sort="throughput",
            agent_reasoning={"effort": "medium"},
        ),
        SecretStr("test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ).build(
        model_id="x-ai/grok-4.6", timeout_s=10, max_retries=0, max_output_tokens=1024, temperature=0
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_reasoning_survives_real_stream_converter_with_tools_and_usage(asynchronous: bool) -> None:
    model = _provider(_stream_response)
    if asynchronous:

        async def collect() -> list[Any]:
            return [chunk async for chunk in model.astream("Inspect the project")]

        chunks = asyncio.run(collect())
    else:
        chunks = list(model.stream("Inspect the project"))
    assert (
        "".join(chunk.additional_kwargs.get("reasoning_content", "") for chunk in chunks)
        == "Check `a_long_identifier` then continue."
    )
    aggregate = sum(chunks[1:], chunks[0])
    assert aggregate.tool_calls[0]["name"] == "read"
    assert aggregate.tool_calls[0]["args"] == {}
    assert aggregate.usage_metadata["total_tokens"] == 18
    assert (
        next(chunk for chunk in chunks if chunk.usage_metadata).response_metadata[
            "clue_cost_source"
        ]
        == "metered"
    )
    assert (
        next(chunk for chunk in chunks if chunk.usage_metadata).response_metadata["clue_cost_cents"]
        == "0.200"
    )


def test_reasoning_continuation_metadata_survives_request_conversion() -> None:
    model = _provider(_stream_response).models[0]
    details = [{"type": "reasoning.encrypted", "data": "opaque", "id": "r1", "index": 0}]
    assistant = AIMessageChunk(
        content="",
        additional_kwargs={"reasoning_details": details},
        tool_calls=[{"name": "read", "args": {}, "id": "call-1"}],
    )
    payload = model._get_request_payload(
        [assistant, ToolMessage(content="result", tool_call_id="call-1")]
    )
    assert payload["messages"][0]["reasoning_details"] == details
