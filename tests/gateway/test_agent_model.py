from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from clue_config.gateway import GatewayConfig
from clue_gateway import OpenRouterAgentModelProvider


class ReadProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)


def test_openrouter_agent_model_parses_standard_tool_calls_offline() -> None:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-openrouter-key"
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "id": "gen-c6-spike",
                "object": "chat.completion",
                "created": 1_775_000_000,
                "model": "openai/gpt-4.1",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-read-project",
                                    "type": "function",
                                    "function": {
                                        "name": "ReadProjectInput",
                                        "arguments": '{"project_id":"project-1"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    config = GatewayConfig(
        base_url="https://openrouter.ai/api/v1",
        timeout_s=30,
        max_retries=2,
    )
    provider = OpenRouterAgentModelProvider(
        config,
        SecretStr("test-openrouter-key"),
        http_client=client,
        http_async_client=async_client,
    )
    model = provider.build(
        model_id="openai/gpt-4.1",
        timeout_s=10,
        max_retries=1,
        max_output_tokens=1_024,
        temperature=0,
    )

    bound = model.bind_tools([ReadProjectInput])
    response = bound.invoke("Read the project.")

    assert response.tool_calls == [
        {
            "name": "ReadProjectInput",
            "args": {"project_id": "project-1"},
            "id": "call-read-project",
            "type": "tool_call",
        }
    ]
    assert response.usage_metadata is not None
    assert response.usage_metadata["input_tokens"] == 11
    assert response.usage_metadata["output_tokens"] == 7
    assert requests[0]["model"] == "openai/gpt-4.1"
    assert requests[0]["max_completion_tokens"] == 1_024
    assert requests[0]["tools"][0]["function"]["name"] == "ReadProjectInput"

    async def invoke_async() -> None:
        async_response = await bound.ainvoke("Read the project asynchronously.")
        assert async_response.tool_calls[0]["name"] == "ReadProjectInput"

    import asyncio

    asyncio.run(invoke_async())
    assert len(requests) == 2


def test_agent_model_policy_cannot_exceed_gateway_timeout_or_retries() -> None:
    provider = OpenRouterAgentModelProvider(
        GatewayConfig(timeout_s=10, max_retries=1),
        SecretStr("unused"),
    )
    common = {
        "model_id": "openai/gpt-4.1",
        "max_output_tokens": 100,
        "temperature": 0,
    }

    try:
        provider.build(timeout_s=11, max_retries=1, **common)
    except ValueError as exc:
        assert "timeout" in str(exc)
    else:
        raise AssertionError("timeout escalation must fail")

    try:
        provider.build(timeout_s=10, max_retries=2, **common)
    except ValueError as exc:
        assert "retries" in str(exc)
    else:
        raise AssertionError("retry escalation must fail")
