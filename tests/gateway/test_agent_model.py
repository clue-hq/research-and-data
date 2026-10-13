from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import APIStatusError
from openai.types.responses import ResponseError
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr, ValidationError

from clue_config.gateway import GatewayConfig, ModelPrice
from clue_gateway import OpenRouterAgentModelProvider
from clue_gateway import agent_model as agent_model
from clue_gateway.agent_model import (
    GenerationCostLookup,
    GovernedAgentChatModel,
    OpenRouterGenerationCost,
    provider_compatible_tool_schema,
    transient_upstream_failure,
    unsupported_schema_pattern,
)
from clue_obs.otel import SPAN_LLM_GATEWAY_CALL, collect_spans
from clue_research.proposals.models import SourceManifestDraft


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
        assert request.url == "https://openrouter.ai/api/v1/responses"
        assert request.headers["authorization"] == "Bearer test-openrouter-key"
        payload = json.loads(request.content)
        requests.append(payload)
        has_tool_output = any(
            item.get("type") == "function_call_output" for item in payload["input"]
        )
        output = (
            [
                {
                    "id": "msg-c6-complete",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "project read",
                            "annotations": [],
                        }
                    ],
                }
            ]
            if has_tool_output
            else [
                {
                    "id": "fc-c6-spike",
                    "type": "function_call",
                    "call_id": "call-read-project",
                    "name": "ReadProjectInput",
                    "arguments": '{"project_id":"project-1"}',
                    "status": "completed",
                }
            ]
        )
        return httpx.Response(
            200,
            json={
                "id": "resp-c6-spike",
                "object": "response",
                "created_at": 1_775_000_000,
                "model": "openai/gpt-5.6-terra",
                "output": output,
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "usage": {
                    "input_tokens": 11,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens": 7,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 18,
                },
                "status": "completed",
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
            "openai/gpt-5.6-terra": ModelPrice(
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
        model_id="openai/gpt-5.6-terra",
        timeout_s=10,
        max_retries=1,
        max_output_tokens=1_024,
        temperature=0,
    )

    # ``create_agent`` uses the provider-neutral spelling ``any`` for its structured-output
    # ToolStrategy.  The governed wrapper must restore the OpenAI Responses spelling rather than
    # forwarding an invalid wire value to OpenRouter.
    bound = model.bind_tools([ReadProjectInput], tool_choice="any")
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
    assert response.response_metadata["clue_requested_model"] == "openai/gpt-5.6-terra"
    assert response.response_metadata["clue_answering_model"] == "openai/gpt-5.6-terra"
    assert response.response_metadata["clue_cost_cents"] == "0.025"
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == [SPAN_LLM_GATEWAY_CALL]
    assert spans[0].attributes is not None
    assert spans[0].attributes["prompt_tokens"] == 11
    assert spans[0].attributes["completion_tokens"] == 7
    assert requests[0]["model"] == "openai/gpt-5.6-terra"
    assert requests[0]["reasoning"] == {"effort": "high"}
    assert requests[0]["max_output_tokens"] == 1_024
    assert "messages" not in requests[0]
    assert "max_completion_tokens" not in requests[0]
    assert requests[0]["input"][0]["type"] == "message"
    assert requests[0]["tools"][0]["type"] == "function"
    assert requests[0]["tools"][0]["name"] == "ReadProjectInput"
    assert requests[0]["tool_choice"] == "required"

    async def invoke_async() -> None:
        async_response = await bound.ainvoke(
            [
                HumanMessage(content="Read the project."),
                response,
                ToolMessage(content='{"name":"Project One"}', tool_call_id="call-read-project"),
            ]
        )
        assert async_response.text == "project read"

    import asyncio

    asyncio.run(invoke_async())
    assert len(requests) == 2
    assert "previous_response_id" not in requests[1]
    assert [item["type"] for item in requests[1]["input"]] == [
        "message",
        "function_call",
        "function_call_output",
    ]
    assert requests[1]["input"][1]["call_id"] == "call-read-project"
    assert requests[1]["input"][2] == {
        "type": "function_call_output",
        "output": '{"name":"Project One"}',
        "call_id": "call-read-project",
    }
    assert requests[1]["tool_choice"] == "required"


def test_openrouter_agent_model_normalizes_exact_function_choice() -> None:
    captured: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp-exact-tool",
                "object": "response",
                "created_at": 1_775_000_000,
                "model": "openai/gpt-5.6-terra",
                "output": [
                    {
                        "id": "fc-exact-tool",
                        "type": "function_call",
                        "call_id": "call-exact-tool",
                        "name": "ReadProjectInput",
                        "arguments": '{"project_id":"project-1"}',
                        "status": "completed",
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": {
                    "type": "function",
                    "name": "ReadProjectInput",
                },
                "tools": [],
                "usage": {
                    "input_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens": 1,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 3,
                },
                "status": "completed",
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenRouterAgentModelProvider(
        GatewayConfig(base_url="https://openrouter.ai/api/v1", timeout_s=30, max_retries=0),
        SecretStr("test-openrouter-key"),
        http_client=client,
        http_async_client=async_client,
    )
    model = provider.build(
        model_id="openai/gpt-5.6-terra",
        timeout_s=10,
        max_retries=0,
        max_output_tokens=128,
        temperature=0,
    )

    response = model.bind_tools([ReadProjectInput], tool_choice="ReadProjectInput").invoke(
        "Read the project."
    )

    assert response.tool_calls[0]["name"] == "ReadProjectInput"
    assert captured[0]["tool_choice"] == {
        "type": "function",
        "name": "ReadProjectInput",
    }


def test_openrouter_agent_model_falls_back_and_records_answering_model() -> None:
    requested_models: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://openrouter.ai/api/v1/responses"
        payload = json.loads(request.content)
        model = payload["model"]
        requested_models.append(model)
        if model == "primary/model":
            return httpx.Response(500, json={"error": "primary unavailable"}, request=request)
        return httpx.Response(
            200,
            json={
                "id": "resp-fallback",
                "object": "response",
                "created_at": 1_775_000_000,
                "model": "fallback/model",
                "output": [
                    {
                        "id": "msg-fallback",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "fallback answer",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "usage": {
                    "input_tokens": 4,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens": 2,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 6,
                },
                "status": "completed",
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
    assert response.text == "fallback answer"
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


class TwoModelChunksStreamingModel(StreamingChatModel):
    """A stream whose finish chunk AND usage chunk both carry ``model_name`` — what OpenRouter's
    stream looks like through langchain-openai — the source of the doubled answering model."""

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
                response_metadata={"model_name": "served/x", "finish_reason": "stop"},
            )
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                response_metadata={"model_name": "served/x"},
                usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                chunk_position="last",
            )
        )


def test_a_stream_whose_chunks_repeat_the_model_name_merges_to_one_answering_model() -> None:
    model = GovernedAgentChatModel(
        models=(TwoModelChunksStreamingModel(),),
        model_ids=("served/x",),
        requested_model="requested/model",
        gateway_config=GatewayConfig(),
    )
    chunks = list(model.stream("Stream the answer."))
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert merged.response_metadata["model_name"] == "served/x"
    assert merged.response_metadata["clue_answering_model"] == "served/x"
    assert merged.response_metadata["clue_requested_model"] == "requested/model"
    assert "".join(str(chunk.content) for chunk in chunks) == "streamed answer"


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


@pytest.mark.parametrize(
    "pattern",
    [
        r"^(?!^[-+.]*$)[+-]?0*\d*\.?\d*$",
        r"^(?=.*a).*$",
        r"(?<=x)y",
        r"(?<!x)y",
        r"(\w+)\s+\1",
    ],
)
def test_unsupported_schema_pattern_flags_lookaround_and_backreferences(pattern: str) -> None:
    assert unsupported_schema_pattern(pattern) is True


@pytest.mark.parametrize(
    "pattern",
    [
        r"^[a-z][a-z0-9_]*$",
        r"^\d{4}-\d{2}-\d{2}$",
        r"^(alpha|beta)$",
    ],
)
def test_supported_schema_patterns_are_kept(pattern: str) -> None:
    assert unsupported_schema_pattern(pattern) is False


def test_provider_compatible_tool_schema_drops_only_unsupported_patterns() -> None:
    schema = {
        "type": "function",
        "function": {
            "name": "example",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "amount": {
                        "anyOf": [
                            {"type": "number", "minimum": 0.0},
                            {"type": "string", "pattern": r"^(?!^[-+.]*$)[+-]?0*\d*\.?\d*$"},
                        ],
                        "title": "Amount",
                    },
                    "slug": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*$"},
                    "pattern": {"type": "string"},
                },
                "required": ["amount", "slug"],
            },
        },
    }

    transformed = provider_compatible_tool_schema(schema)

    assert transformed == {
        "type": "function",
        "function": {
            "name": "example",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "amount": {
                        "anyOf": [
                            {"type": "number", "minimum": 0.0},
                            {"type": "string"},
                        ],
                        "title": "Amount",
                    },
                    "slug": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*$"},
                    "pattern": {"type": "string"},
                },
                "required": ["amount", "slug"],
            },
        },
    }


def test_decimal_tool_schema_loses_lookahead_while_local_validation_still_rejects_negatives() -> (
    None
):
    raw = json.dumps(convert_to_openai_tool(SourceManifestDraft))
    assert "(?!" in raw

    model = GovernedAgentChatModel(
        models=(StreamingChatModel(),),
        model_ids=("served/streaming-model",),
        requested_model="requested/model",
        gateway_config=GatewayConfig(),
    )
    bound = model.bind_tools([SourceManifestDraft])

    emitted = json.dumps(bound.kwargs["tools"])
    assert "(?!" not in emitted
    assert '"cost_cents"' in emitted

    payload = {
        "source_key": "example_source",
        "modality": "text",
        "entity_scope": "account",
    }
    assert SourceManifestDraft.model_validate({**payload, "cost_cents": "1.5"}).cost_cents == (
        Decimal("1.5")
    )
    with pytest.raises(ValidationError):
        SourceManifestDraft.model_validate({**payload, "cost_cents": "-1"})


# --- P3.2 (PD-part3 delta 6): extra_body passthrough, role attribution, cache economics ---


def _responses_envelope(*, model: str, cached_tokens: int = 0) -> dict[str, Any]:
    return {
        "id": "resp-p32",
        "object": "response",
        "created_at": 1_775_000_000,
        "model": model,
        "output": [
            {
                "id": "msg-p32",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 40,
            "input_tokens_details": {"cached_tokens": cached_tokens, "cache_write_tokens": 0},
            "output_tokens": 2,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 42,
        },
        "status": "completed",
    }


def _p32_provider(config: GatewayConfig, respond: Any) -> OpenRouterAgentModelProvider:
    return OpenRouterAgentModelProvider(
        config,
        SecretStr("test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )


def test_openrouter_extra_body_carries_provider_sort_and_usage_accounting() -> None:
    """The OpenRouter economics knobs are config, not code: `provider.sort` pins one
    replica (the design runtime's ~95% cached-prefill invariant) and `usage.include`
    asks for the accounting block — including the credits the call actually cost.

    `provider.sort` still defaults off, so a call site that never asked for one replica
    ordering keeps its exact wire shape. `usage.include` defaults ON since the R2-close:
    a metered cost is the only cost that is not a guess, so every call asks for one."""
    seen_payloads: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_payloads.append(payload)
        return httpx.Response(
            200, json=_responses_envelope(model=payload["model"]), request=request
        )

    tuned = _p32_provider(
        GatewayConfig(
            openrouter_provider_sort="throughput",
            openrouter_usage_include=True,
        ),
        respond,
    ).build(
        model_id="probe/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )
    tuned.invoke("hi")
    assert seen_payloads[-1]["provider"] == {"sort": "throughput"}
    assert seen_payloads[-1]["usage"] == {"include": True}

    plain = _p32_provider(GatewayConfig(), respond).build(
        model_id="probe/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )
    plain.invoke("hi")
    assert "provider" not in seen_payloads[-1]
    assert seen_payloads[-1]["usage"] == {"include": True}

    opted_out = _p32_provider(GatewayConfig(openrouter_usage_include=False), respond).build(
        model_id="probe/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )
    opted_out.invoke("hi")
    assert "usage" not in seen_payloads[-1] or seen_payloads[-1]["usage"] is None


def test_role_attribution_stamps_metadata_and_usage_record() -> None:
    """One model instance per role is the design runtime's attribution mechanism; the
    governed wrapper carries the role so the usage record and response metadata name it
    — ONE authority, no design-local double count (PD-part3 delta 6)."""

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_responses_envelope(model=json.loads(request.content)["model"]),
            request=request,
        )

    model = _p32_provider(GatewayConfig(), respond).build(
        model_id="probe/model",
        timeout_s=10,
        max_retries=0,
        max_output_tokens=64,
        temperature=0,
        role="design_author",
    )
    with collect_spans() as exporter:
        response = model.invoke("hi")
    assert response.response_metadata["clue_role"] == "design_author"
    gateway_spans = [
        span for span in exporter.get_finished_spans() if span.name == SPAN_LLM_GATEWAY_CALL
    ]
    assert gateway_spans and gateway_spans[0].attributes.get("agent_role") == "design_author"


def test_cached_prompt_tokens_survive_into_usage() -> None:
    """The cached-prefill share is the economics the passthrough exists for; it must be
    measurable, not folded away (retires the 'deliberately absent' note in tracing)."""

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_responses_envelope(model=json.loads(request.content)["model"], cached_tokens=33),
            request=request,
        )

    model = _p32_provider(GatewayConfig(openrouter_usage_include=True), respond).build(
        model_id="probe/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )
    response = model.invoke("hi")
    usage, _served, _cost, _source = model._usage_and_cost(response)
    assert usage.prompt_tokens == 40
    assert usage.cached_prompt_tokens == 33


def test_supports_image_input_reads_the_models_catalog() -> None:
    """The pre-spend vision guard (replaces the design runtime's raw-key probe): True /
    False from the catalog's input modalities, None when the catalog is unreachable —
    the caller decides how hard to fail."""

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vision/model",
                        "architecture": {"input_modalities": ["text", "image"]},
                    },
                    {"id": "text/only", "architecture": {"input_modalities": ["text"]}},
                ]
            },
            request=request,
        )

    provider = _p32_provider(GatewayConfig(), respond)
    assert provider.supports_image_input("vision/model") is True
    assert provider.supports_image_input("text/only") is False
    assert provider.supports_image_input("unknown/model") is None

    def unreachable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"}, request=request)

    assert _p32_provider(GatewayConfig(), unreachable).supports_image_input("vision/model") is None


# --- bounded transient-failure retry (the live job-suspension defect) -------------------------


def _in_body_error_envelope(*, model: str, code: str) -> dict[str, Any]:
    """The exact live shape: HTTP 200 whose Responses body carries an ``error``.

    ``langchain_openai`` raises a bare ``ValueError(ResponseError(...))`` while parsing this, so
    the OpenAI SDK's own ``max_retries`` (transport/status only) never sees it — which is how an
    ``An error occurred while processing the request.`` blip suspended a live account-research job.
    """

    return {
        "id": "resp-transient",
        "object": "response",
        "created_at": 1_775_000_000,
        "model": model,
        "error": {"code": code, "message": "An error occurred while processing the request."},
        "output": [],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "failed",
    }


def _flaky_provider(
    *,
    failures: int,
    code: str,
    seen: list[str],
    config: GatewayConfig | None = None,
) -> OpenRouterAgentModelProvider:
    def respond(request: httpx.Request) -> httpx.Response:
        model = str(json.loads(request.content)["model"])
        seen.append(model)
        if len(seen) <= failures:
            return httpx.Response(
                200, json=_in_body_error_envelope(model=model, code=code), request=request
            )
        return httpx.Response(200, json=_responses_envelope(model=model), request=request)

    return _p32_provider(config or GatewayConfig(), respond)


def test_two_transient_server_errors_are_retried_and_the_model_call_still_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live crash, repaired: a momentary upstream fault is not job integrity.

    The caller sees ONE successful model call — so the agent turn (and the journal's single
    ``model_started``/``model_completed`` pair bracketing it) continues exactly as if the blip
    had not happened.
    """

    monkeypatch.setattr(agent_model, "_TRANSIENT_BACKOFF_S", (0.0, 0.0))
    seen: list[str] = []
    model = _flaky_provider(failures=2, code="server_error", seen=seen).build(
        model_id="primary/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )

    response = model.invoke("Research the account.")

    assert seen == ["primary/model"] * 3
    assert response.text == "ok"
    assert response.response_metadata["clue_requested_model"] == "primary/model"
    assert response.response_metadata["clue_answering_model"] == "primary/model"


def test_two_transient_server_errors_are_retried_on_the_async_path_the_agent_actually_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_model, "_TRANSIENT_BACKOFF_S", (0.0, 0.0))
    seen: list[str] = []
    model = _flaky_provider(failures=2, code="server_error", seen=seen).build(
        model_id="primary/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )

    response = asyncio.run(model.ainvoke("Research the account."))

    assert seen == ["primary/model"] * 3
    assert response.text == "ok"


def test_a_permanently_failing_upstream_still_fails_loudly_after_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry is bounded: an upstream that never recovers reaches the supervisor, as today."""

    monkeypatch.setattr(agent_model, "_TRANSIENT_BACKOFF_S", (0.0, 0.0))
    seen: list[str] = []
    model = _flaky_provider(failures=99, code="server_error", seen=seen).build(
        model_id="primary/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )

    with pytest.raises(ValueError) as raised:
        model.invoke("Research the account.")

    assert len(seen) == agent_model._MAX_TRANSIENT_ATTEMPTS == 3
    assert "server_error" in str(raised.value)


def test_a_deterministic_upstream_rejection_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``invalid_prompt`` cannot be repaired by asking again — one attempt, then loud."""

    monkeypatch.setattr(agent_model, "_TRANSIENT_BACKOFF_S", (0.0, 0.0))
    seen: list[str] = []
    model = _flaky_provider(failures=99, code="invalid_prompt", seen=seen).build(
        model_id="primary/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )

    with pytest.raises(ValueError):
        model.invoke("Research the account.")

    assert len(seen) == 1


def test_a_transient_failure_reaches_the_fallback_before_it_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One attempt = one pass over the candidates, so the fallback contract is unchanged: the
    fallback is tried immediately, and only a round whose LAST candidate failed transiently
    is retried."""

    monkeypatch.setattr(agent_model, "_TRANSIENT_BACKOFF_S", (0.0, 0.0))
    seen: list[str] = []
    model = _flaky_provider(
        failures=3,
        code="server_error",
        seen=seen,
        config=GatewayConfig(fallback_model="fallback/model"),
    ).build(
        model_id="primary/model", timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0
    )

    response = model.invoke("Research the account.")

    assert seen == [
        "primary/model",
        "fallback/model",
        "primary/model",
        "fallback/model",
    ]
    assert response.response_metadata["clue_answering_model"] == "fallback/model"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValueError(ResponseError(code="server_error", message="blip")), True),
        (ValueError(ResponseError(code="rate_limit_exceeded", message="slow down")), True),
        (ValueError(ResponseError(code="invalid_prompt", message="no")), False),
        (ValueError({"code": "server_error", "message": "blip"}), True),
        # Seen live twice on 2026-09-04 (design solo runs 2 and 3): OpenRouter answered a
        # 136 s and a 236 s grok generation with HTTP 200 and an in-body error whose
        # ``code`` is the INTEGER 502, not a Responses error-code string. Each one
        # discarded a whole web turn because nothing retried the model call.
        (ValueError({"message": "Auth context expired", "code": 502}), True),
        (ValueError({"message": "Auth context expired", "code": "502"}), True),
        (ValueError({"message": "no such model", "code": 404}), False),
        (ValueError("some other programming error"), False),
        (httpx.ConnectError("connection refused"), True),
        (httpx.ReadTimeout("timed out"), True),
        (
            APIStatusError(
                "server error",
                response=httpx.Response(503, request=httpx.Request("POST", "https://x/y")),
                body=None,
            ),
            True,
        ),
        (
            APIStatusError(
                "rate limited",
                response=httpx.Response(429, request=httpx.Request("POST", "https://x/y")),
                body=None,
            ),
            True,
        ),
        (
            APIStatusError(
                "bad request",
                response=httpx.Response(400, request=httpx.Request("POST", "https://x/y")),
                body=None,
            ),
            False,
        ),
    ],
)
def test_transient_upstream_failure_classifies_only_momentary_faults(
    error: BaseException, expected: bool
) -> None:
    assert transient_upstream_failure(error) is expected


def test_the_retry_bound_and_backoff_stay_small_enough_for_a_leased_agent_turn() -> None:
    """The turn holds a fleet lease whose heartbeat must keep landing, so the added wall clock
    is bounded and short by construction."""

    assert agent_model._MAX_TRANSIENT_ATTEMPTS == 3
    assert len(agent_model._TRANSIENT_BACKOFF_S) == agent_model._MAX_TRANSIENT_ATTEMPTS - 1
    assert sum(agent_model._TRANSIENT_BACKOFF_S) <= 5.0


# --- OpenRouter's own metered cost (R2-close task 2) -------------------------------------------
#
# ``usage.include`` makes OpenRouter answer with a ``usage`` block carrying the credits the call
# actually cost. ``langchain_openai``'s chat-completions path hands that block back verbatim as
# ``ChatResult.llm_output["token_usage"]``, so the governed wrapper prefers it over the local
# price sheet and says which of the two it used.


class _UsageChatModel(BaseChatModel):
    """An inner model shaped like ``langchain_openai``'s chat-completions result.

    ``llm_output["token_usage"]`` is the provider's raw usage block — including OpenRouter's
    ``cost`` key when usage accounting was asked for.
    """

    _usage: dict[str, Any] = PrivateAttr()
    _response_id: str | None = PrivateAttr()

    def __init__(self, usage: dict[str, Any], *, response_id: str | None = None) -> None:
        super().__init__()
        self._usage = usage
        self._response_id = response_id

    @property
    def _llm_type(self) -> str:
        return "c6-usage-test-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        message = AIMessage(
            content="answered",
            usage_metadata={
                "input_tokens": int(self._usage.get("prompt_tokens", 0)),
                "output_tokens": int(self._usage.get("completion_tokens", 0)),
                "total_tokens": int(self._usage.get("total_tokens", 0)),
            },
        )
        llm_output: dict[str, Any] = {
            "token_usage": dict(self._usage),
            "model_name": "x-ai/grok-4.6",
        }
        if self._response_id is not None:
            llm_output["id"] = self._response_id
        return ChatResult(generations=[ChatGeneration(message=message)], llm_output=llm_output)


#: A price table is NOT how this deployment prices a model (founder ruling 2026-09-08: the cost is
#: OpenRouter's number or nothing). ``GatewayConfig.prices`` survives as a pre-existing mechanism,
#: so these tests still pin its branch — with a made-up model id, so nothing reads as a rate we
#: maintain for a model we actually run.
_LISTED_PRICES = {
    "x-ai/grok-4.6": ModelPrice(
        prompt_cents_per_1k=Decimal("0.2"), completion_cents_per_1k=Decimal("0.6")
    )
}


class _RecordingLookup:
    """A ``GenerationCostLookup`` double: records what it was asked, answers what it was given."""

    def __init__(self, answer: Decimal | None) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def cost_cents(self, generation_id: str) -> Decimal | None:
        self.asked.append(generation_id)
        return self.answer

    async def acost_cents(self, generation_id: str) -> Decimal | None:
        return self.cost_cents(generation_id)


def _governed(
    usage: dict[str, Any],
    *,
    prices: dict[str, ModelPrice] | None = None,
    lookup: Any | None = None,
    response_id: str | None = None,
) -> GovernedAgentChatModel:
    return GovernedAgentChatModel(
        models=(_UsageChatModel(usage, response_id=response_id),),
        model_ids=("x-ai/grok-4.6",),
        requested_model="x-ai/grok-4.6",
        gateway_config=GatewayConfig(prices=prices or {}),
        cost_lookup=lookup,
    )


def test_openrouter_reported_cost_is_preferred_over_the_price_sheet_and_labelled_metered() -> None:
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost": 0.0123},
        prices=_LISTED_PRICES,
    )

    response = model.invoke("What did that cost?")

    # $0.0123 is 1.23 cents — the provider's number, not the sheet's 0.032.
    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal("1.23")
    assert response.response_metadata["clue_cost_source"] == "metered"


def test_without_a_reported_cost_the_price_sheet_answers_and_says_so() -> None:
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        prices=_LISTED_PRICES,
    )

    response = model.invoke("What did that cost?")

    # 100 prompt tokens at 0.2c/1k plus 20 completion tokens at 0.6c/1k.
    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal("0.032")
    assert response.response_metadata["clue_cost_source"] == "estimate"


def test_a_model_absent_from_the_price_sheet_reports_zero_as_unpriced_never_as_measured() -> None:
    model = _governed({"prompt_tokens": 100, "completion_tokens": 20})

    response = model.invoke("What did that cost?")

    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal(0)
    assert response.response_metadata["clue_cost_source"] == "unpriced"


def test_usage_accounting_is_asked_for_by_default_and_we_ship_no_price_table_of_our_own() -> None:
    """The R2 live run logged zero for every model call because OpenRouter was never asked to
    meter. Asking is now the default — and the answer to "what did this cost" is OpenRouter's,
    never a rate sheet of ours (founder ruling 2026-09-08), so the table ships empty."""

    config = GatewayConfig()

    assert config.openrouter_usage_include is True
    assert config.prices == {}


def test_a_response_without_its_own_cost_is_priced_by_the_generation_endpoint_as_metered() -> None:
    """The streaming and Responses paths drop OpenRouter's ``cost`` key, so the cost is fetched
    from its meter rather than estimated from rates we would have to keep current."""

    lookup = _RecordingLookup(Decimal("4.56"))
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20},
        prices=_LISTED_PRICES,
        lookup=lookup,
        response_id="gen-abc123",
    )

    response = model.invoke("What did that cost?")

    assert lookup.asked == ["gen-abc123"], "the response's own generation id, once"
    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal("4.56")
    # OpenRouter's meter, reached by a second route — still metered, never an estimate, even
    # though this model happens to be listed in the deployment's price table.
    assert response.response_metadata["clue_cost_source"] == "metered"


def test_a_response_that_already_carried_its_cost_is_never_looked_up() -> None:
    """Lazy by construction: the lookup is a network hop and a metered answer needs no second."""

    lookup = _RecordingLookup(Decimal("4.56"))
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0123},
        lookup=lookup,
        response_id="gen-abc123",
    )

    response = model.invoke("What did that cost?")

    assert lookup.asked == []
    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal("1.23")
    assert response.response_metadata["clue_cost_source"] == "metered"


def test_a_failed_generation_lookup_reports_unpriced_and_does_not_raise() -> None:
    lookup = _RecordingLookup(None)
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20}, lookup=lookup, response_id="gen-abc123"
    )

    response = model.invoke("What did that cost?")

    assert lookup.asked == ["gen-abc123"]
    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal(0)
    assert response.response_metadata["clue_cost_source"] == "unpriced"


def test_a_langchain_run_id_is_never_mistaken_for_a_generation_id() -> None:
    """LangChain stamps its own run id on a message when the provider gave none. Asking OpenRouter
    about one would be asking about a call it has never heard of."""

    lookup = _RecordingLookup(Decimal("4.56"))
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20},
        lookup=lookup,
        response_id="lc_run-0000-0",
    )

    response = model.invoke("What did that cost?")

    assert lookup.asked == []
    assert response.response_metadata["clue_cost_source"] == "unpriced"


def _generation_transport(
    responses: list[httpx.Response],
) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen) - 1, len(responses) - 1)]

    return httpx.Client(transport=httpx.MockTransport(respond)), seen


def test_the_generation_lookup_reads_total_cost_and_converts_usd_to_cents() -> None:
    client, seen = _generation_transport(
        [httpx.Response(200, json={"data": {"id": "gen-abc123", "total_cost": 0.0456}})]
    )
    lookup = OpenRouterGenerationCost(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("test-openrouter-key"),
        http_client=client,
    )

    assert lookup.cost_cents("gen-abc123") == Decimal("4.5600")
    assert seen[0].url.path == "/api/v1/generation"
    assert seen[0].url.params["id"] == "gen-abc123"
    assert seen[0].headers["authorization"] == "Bearer test-openrouter-key"


def test_the_generation_lookup_retries_an_upstream_fault_exactly_once() -> None:
    client, seen = _generation_transport(
        [
            httpx.Response(503, text="upstream"),
            httpx.Response(200, json={"data": {"total_cost": 0.01}}),
        ]
    )
    lookup = OpenRouterGenerationCost(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("k"),
        http_client=client,
    )

    assert lookup.cost_cents("gen-abc123") == Decimal("1.00")
    assert len(seen) == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"data": {}}),
        httpx.Response(200, text="not json"),
    ],
)
def test_the_generation_lookup_never_raises_and_answers_none_when_it_cannot_price(
    response: httpx.Response,
) -> None:
    """Pricing a call must never be able to fail the call it prices."""

    client, _ = _generation_transport([response])
    lookup = OpenRouterGenerationCost(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("k"),
        http_client=client,
    )

    assert lookup.cost_cents("gen-abc123") is None


def test_the_generation_lookup_swallows_a_transport_failure() -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    lookup = OpenRouterGenerationCost(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("k"),
        http_client=httpx.Client(transport=httpx.MockTransport(explode)),
    )

    assert lookup.cost_cents("gen-abc123") is None


def test_the_provider_injects_the_generation_lookup_so_a_built_model_can_price_itself() -> None:
    provider = OpenRouterAgentModelProvider(GatewayConfig(), SecretStr("k"))

    model = provider.build(
        model_id="x-ai/grok-4.6",
        timeout_s=10,
        max_retries=1,
        max_output_tokens=64,
        temperature=0,
    )

    assert isinstance(model, GovernedAgentChatModel)
    # Reads the reply's own usage block first, then OpenRouter's /generation record.
    assert isinstance(model.cost_lookup, GenerationCostLookup)


def test_the_async_path_awaits_the_generation_lookup_rather_than_blocking_the_loop() -> None:
    """The production path: the ARV2 account agent drives the graph with ``ainvoke``, so the
    lookup it triggers must be the awaited one."""

    class _AsyncOnlyLookup:
        def __init__(self) -> None:
            self.asked_async: list[str] = []

        def cost_cents(self, generation_id: str) -> Decimal | None:
            raise AssertionError("the async path must not call the blocking lookup")

        async def acost_cents(self, generation_id: str) -> Decimal | None:
            await asyncio.sleep(0)
            self.asked_async.append(generation_id)
            return Decimal("7.89")

    lookup = _AsyncOnlyLookup()
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20}, lookup=lookup, response_id="gen-async-1"
    )

    response = asyncio.run(model.ainvoke("What did that cost?"))

    assert lookup.asked_async == ["gen-async-1"]
    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal("7.89")
    assert response.response_metadata["clue_cost_source"] == "metered"


def _lagging_meter(*, backoff_s: float = 0.0, **kwargs: Any) -> OpenRouterGenerationCost:
    return OpenRouterGenerationCost(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("test-openrouter-key"),
        meter_lag_backoff_s=backoff_s,
        **kwargs,
    )


def test_the_generation_lookup_retries_a_404_once_because_the_meter_can_lag_the_response() -> None:
    """A 404 is the ordinary shape for a job's last round: the lookup runs the instant the
    completion returns, and OpenRouter has not finished recording the generation yet."""

    client, seen = _generation_transport(
        [
            httpx.Response(404, text="not found"),
            httpx.Response(200, json={"data": {"total_cost": 0.0456}}),
        ]
    )

    assert _lagging_meter(http_client=client).cost_cents("gen-abc123") == Decimal("4.5600")
    assert len(seen) == 2, "asked once, waited, asked again"


def test_a_meter_that_never_records_the_generation_gives_up_after_the_second_ask() -> None:
    client, seen = _generation_transport(
        [httpx.Response(404, text="not found"), httpx.Response(404, text="not found")]
    )

    assert _lagging_meter(http_client=client).cost_cents("gen-abc123") is None
    assert len(seen) == 2, "exactly one retry — never a third ask"


def test_a_lagging_meter_still_lands_a_metered_cost_on_the_message() -> None:
    """End to end over the real lookup: the 404 the first ask gets must not cost the job its
    money truth."""

    client, _ = _generation_transport(
        [
            httpx.Response(404, text="not found"),
            httpx.Response(200, json={"data": {"total_cost": 0.0456}}),
        ]
    )
    model = _governed(
        {"prompt_tokens": 100, "completion_tokens": 20},
        lookup=_lagging_meter(http_client=client),
        response_id="gen-abc123",
    )

    response = model.invoke("What did that cost?")

    assert Decimal(response.response_metadata["clue_cost_cents"]) == Decimal("4.56")
    assert response.response_metadata["clue_cost_source"] == "metered"


def test_the_async_lookup_awaits_the_lag_rather_than_blocking_and_still_retries_once() -> None:
    """The production path again: the ARV2 loop is async, so the second ask must come after an
    awaited pause, not a blocking one."""

    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(404, text="not found"),
        httpx.Response(200, json={"data": {"total_cost": 0.0456}}),
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen) - 1, len(responses) - 1)]

    async def ask() -> Decimal | None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await _lagging_meter(http_async_client=client).acost_cents("gen-abc123")

    assert asyncio.run(ask()) == Decimal("4.5600")
    assert len(seen) == 2


class OpenRouterShapedStreamingChatModel(BaseChatModel):
    """A stream shaped the way OpenRouter serves Grok: the finish chunk carries the model name
    and finish reason in its generation info, and the trailing usage chunk repeats both."""

    @property
    def _llm_type(self) -> str:
        return "openrouter-shaped-streaming-test-model"

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
        info = {"finish_reason": "stop", "model_name": "served/streaming-model"}
        yield ChatGenerationChunk(message=AIMessageChunk(content="streamed "))
        yield ChatGenerationChunk(message=AIMessageChunk(content="answer"), generation_info=info)
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                chunk_position="last",
            ),
            generation_info=dict(info),
        )


def test_the_merged_stream_carries_the_answering_model_exactly_once() -> None:
    """LangChain merges streamed chunks by concatenating equal string metadata, so a label stamped
    on every chunk reads back N times over on the merged message the turn runtime records from.
    The gateway therefore stamps the served model once, on the chunk that carries usage."""
    model = GovernedAgentChatModel(
        models=(OpenRouterShapedStreamingChatModel(),),
        model_ids=("served/streaming-model",),
        requested_model="requested/model",
        gateway_config=GatewayConfig(),
    )

    chunks = list(model.stream("Stream the answer."))
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk

    assert merged.response_metadata["clue_answering_model"] == "served/streaming-model"
    assert merged.response_metadata["clue_requested_model"] == "requested/model"
    # LangChain's own merge still doubles the provider's repeated fields; that is why readers
    # must prefer the gateway's stamp over ``model_name``.
    assert merged.response_metadata["model_name"] == "served/streaming-modelserved/streaming-model"


# --- Fallback chain + first-chunk / call deadlines (2026-10-04) -----------------------------------
# Production 2026-10-04: grok-4.6 accepted requests and sent nothing — 300 s with zero chunks on a
# streamed turn, and 13 minutes on a non-streamed exit-judge call — with no fallback configured.

_STARTED: list[str] = []
_CLOSED: list[str] = []


class _StallingModel(StreamingChatModel):
    """Accepts the request and never sends a chunk (or a non-streamed answer)."""

    name_tag: str = "stalling"

    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        _STARTED.append(self.name_tag)
        try:
            await asyncio.sleep(30)
            yield ChatGenerationChunk(message=AIMessageChunk(content="too late"))
        finally:
            _CLOSED.append(self.name_tag)

    async def _agenerate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        _STARTED.append(self.name_tag)
        await asyncio.sleep(30)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="too late"))])


class _AnsweringModel(StreamingChatModel):
    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        yield ChatGenerationChunk(message=AIMessageChunk(content="fallback "))
        yield ChatGenerationChunk(message=AIMessageChunk(content="answer", chunk_position="last"))

    async def _agenerate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="fallback answer"))]
        )


class _StartsThenPausesModel(StreamingChatModel):
    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        yield ChatGenerationChunk(message=AIMessageChunk(content="slow "))
        await asyncio.sleep(0.2)
        yield ChatGenerationChunk(message=AIMessageChunk(content="answer", chunk_position="last"))


def _chained(*models: BaseChatModel, **deadlines: Any) -> GovernedAgentChatModel:
    return GovernedAgentChatModel(
        models=models,
        model_ids=tuple(f"model/{i}" for i in range(len(models))),
        requested_model="model/0",
        gateway_config=GatewayConfig(),
        **deadlines,
    )


async def _collect(model: GovernedAgentChatModel) -> list[Any]:
    return [chunk async for chunk in model.astream("Hello.")]


def test_build_tries_the_configured_fallback_chain_in_order() -> None:
    provider = _p32_provider(
        GatewayConfig(fallback_models=("x-ai/grok-4.7", "meta/muse-spark-1.3")),
        lambda request: httpx.Response(500, request=request),
    )
    kwargs = {"timeout_s": 10, "max_retries": 0, "max_output_tokens": 64, "temperature": 0}
    model = provider.build(model_id="x-ai/grok-4.6", **kwargs)
    assert model.model_ids == ("x-ai/grok-4.6", "x-ai/grok-4.7", "meta/muse-spark-1.3")
    # A chain member equal to the primary is not tried twice.
    again = provider.build(model_id="x-ai/grok-4.7", **kwargs)
    assert again.model_ids == ("x-ai/grok-4.7", "meta/muse-spark-1.3")


def test_build_carries_the_first_chunk_deadline_and_an_optional_call_deadline() -> None:
    provider = _p32_provider(
        GatewayConfig(first_token_timeout_s=90.0), lambda r: httpx.Response(500, request=r)
    )
    kwargs = {"timeout_s": 10, "max_retries": 0, "max_output_tokens": 64, "temperature": 0}
    plain = provider.build(model_id="primary/model", **kwargs)
    assert plain.first_token_timeout_s == 90.0 and plain.call_deadline_s is None
    judged = provider.build(model_id="primary/model", call_deadline_s=45.0, **kwargs)
    assert judged.call_deadline_s == 45.0


def test_a_stream_with_no_first_chunk_falls_to_the_next_model() -> None:
    _STARTED.clear()
    _CLOSED.clear()
    model = _chained(_StallingModel(), _AnsweringModel(), first_token_timeout_s=0.05)
    chunks = asyncio.run(_collect(model))
    assert "".join(str(c.content) for c in chunks) == "fallback answer"
    assert chunks[-1].response_metadata["clue_answering_model"] == "model/1"
    assert _CLOSED == ["stalling"]  # the abandoned stream was closed, not leaked


def test_a_stream_that_has_started_is_not_cut_by_the_first_chunk_deadline() -> None:
    model = _chained(_StartsThenPausesModel(), _AnsweringModel(), first_token_timeout_s=0.05)
    chunks = asyncio.run(_collect(model))
    assert "".join(str(c.content) for c in chunks) == "slow answer"


def test_when_every_model_stalls_the_call_fails_fast_without_retrying_the_chain() -> None:
    _STARTED.clear()
    model = _chained(
        _StallingModel(name_tag="a"), _StallingModel(name_tag="b"), first_token_timeout_s=0.05
    )
    with pytest.raises(TimeoutError):
        asyncio.run(_collect(model))
    assert _STARTED == ["a", "b"]


def test_a_hung_non_streamed_call_moves_to_the_next_model_under_a_call_deadline() -> None:
    model = _chained(_StallingModel(), _AnsweringModel(), call_deadline_s=0.05)
    response = asyncio.run(model.ainvoke("Hello."))
    assert response.text == "fallback answer"
    assert response.response_metadata["clue_answering_model"] == "model/1"
