from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from clue_config.gateway import GatewayConfig, ModelPrice
from clue_gateway import OpenRouterAgentModelProvider
from clue_gateway.agent_model import GovernedAgentChatModel
from clue_obs.otel import SPAN_LLM_GATEWAY_CALL, collect_spans


class ReadProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)


class StreamingChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "c6-streaming-test-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="complete"))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Any:
        del messages, stop, run_manager, kwargs
        yield ChatGenerationChunk(message=AIMessageChunk(content="streamed "))
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="answer",
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 3,
                    "total_tokens": 8,
                },
                chunk_position="last",
            )
        )


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
        prices={
            "openai/gpt-4.1": ModelPrice(
                prompt_cents_per_1k=Decimal(1),
                completion_cents_per_1k=Decimal(2),
            )
        },
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
    with collect_spans() as exporter:
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
    assert response.response_metadata["clue_requested_model"] == "openai/gpt-4.1"
    assert response.response_metadata["clue_answering_model"] == "openai/gpt-4.1"
    assert response.response_metadata["clue_cost_cents"] == "0.025"
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == [SPAN_LLM_GATEWAY_CALL]
    assert spans[0].attributes is not None
    assert spans[0].attributes["prompt_tokens"] == 11
    assert spans[0].attributes["completion_tokens"] == 7
    assert requests[0]["model"] == "openai/gpt-4.1"
    assert requests[0]["max_completion_tokens"] == 1_024
    assert requests[0]["tools"][0]["function"]["name"] == "ReadProjectInput"

    async def invoke_async() -> None:
        async_response = await bound.ainvoke("Read the project asynchronously.")
        assert async_response.tool_calls[0]["name"] == "ReadProjectInput"

    import asyncio

    asyncio.run(invoke_async())
    assert len(requests) == 2


def test_openrouter_agent_model_falls_back_and_records_answering_model() -> None:
    requested_models: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        model = payload["model"]
        requested_models.append(model)
        if model == "primary/model":
            return httpx.Response(500, json={"error": "primary unavailable"}, request=request)
        return httpx.Response(
            200,
            json={
                "id": "gen-fallback",
                "object": "chat.completion",
                "created": 1_775_000_000,
                "model": "fallback/model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "fallback answer"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenRouterAgentModelProvider(
        GatewayConfig(
            base_url="https://openrouter.ai/api/v1",
            timeout_s=30,
            max_retries=0,
            fallback_model="fallback/model",
        ),
        SecretStr("test-key"),
        http_client=client,
        http_async_client=async_client,
    )
    model = provider.build(
        model_id="primary/model",
        timeout_s=10,
        max_retries=0,
        max_output_tokens=100,
        temperature=0,
    )

    response = model.invoke("Use the fallback.")

    assert requested_models == ["primary/model", "fallback/model"]
    assert response.content == "fallback answer"
    assert response.response_metadata["clue_requested_model"] == "primary/model"
    assert response.response_metadata["clue_answering_model"] == "fallback/model"


def test_governed_agent_stream_preserves_usage_cost_and_answering_model() -> None:
    model = GovernedAgentChatModel(
        models=(StreamingChatModel(),),
        model_ids=("served/streaming-model",),
        requested_model="requested/model",
        gateway_config=GatewayConfig(
            prices={
                "served/streaming-model": ModelPrice(
                    prompt_cents_per_1k=Decimal(2),
                    completion_cents_per_1k=Decimal(3),
                )
            }
        ),
    )

    with collect_spans() as exporter:
        chunks = list(model.stream("Stream the answer."))

    assert "".join(str(chunk.content) for chunk in chunks) == "streamed answer"
    final = chunks[-1]
    assert final.response_metadata["clue_requested_model"] == "requested/model"
    assert final.response_metadata["clue_answering_model"] == "served/streaming-model"
    assert final.response_metadata["clue_cost_cents"] == "0.019"
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == [SPAN_LLM_GATEWAY_CALL]
    assert spans[0].attributes is not None
    assert spans[0].attributes["model"] == "served/streaming-model"
    assert spans[0].attributes["prompt_tokens"] == 5
    assert spans[0].attributes["completion_tokens"] == 3


def test_agent_model_policy_cannot_exceed_gateway_timeout_or_retries() -> None:
    provider = OpenRouterAgentModelProvider(
        GatewayConfig(timeout_s=10, max_retries=1),
        SecretStr("unused"),
    )
    try:
        provider.build(
            model_id="openai/gpt-4.1",
            timeout_s=11,
            max_retries=1,
            max_output_tokens=100,
            temperature=0,
        )
    except ValueError as exc:
        assert "timeout" in str(exc)
    else:
        raise AssertionError("timeout escalation must fail")

    try:
        provider.build(
            model_id="openai/gpt-4.1",
            timeout_s=10,
            max_retries=2,
            max_output_tokens=100,
            temperature=0,
        )
    except ValueError as exc:
        assert "retries" in str(exc)
    else:
        raise AssertionError("retry escalation must fail")
