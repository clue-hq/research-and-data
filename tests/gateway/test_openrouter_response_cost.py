"""A governed model call is priced from OpenRouter's own usage block, on every route.

Sol smoke test (2026-10-09): every ``openai/gpt-6.1-sol`` call was recorded ``unpriced`` at $0.
The Responses reply carried its cost (``usage.cost``, and for a call made with the account's own
OpenAI key, ``cost: 0`` plus ``cost_details.upstream_inference_cost``), but LangChain drops that
block on the Responses route, and the ``/generation`` fallback answers 404 for about twelve seconds.
"""

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from clue_config.gateway import GatewayConfig
from clue_core.openrouter_cost import openrouter_charged_usd
from clue_gateway.agent_model import OpenRouterAgentModelProvider, OpenRouterGenerationCost

#: An own-key (BYOK) call: OpenRouter charges nothing, OpenAI charges the upstream cost.
BYOK_USAGE = {
    "input_tokens": 40915,
    "input_tokens_details": {"cached_tokens": 36434},
    "output_tokens": 357,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 41272,
    "cost": 0,
    "is_byok": True,
    "cost_details": {"upstream_inference_cost": 0.0183529},
}


def _response(usage: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
    return {
        "id": "gen-sol-1",
        "object": "response",
        "created_at": 1_791_562_000,
        "model": "openai/gpt-6.1-sol",
        "status": status,
        "output": []
        if status != "completed"
        else [
            {
                "id": "msg-1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": usage,
    }


def _model(respond: Any, model_id: str = "openai/gpt-6.1-sol", **config: Any) -> Any:
    return OpenRouterAgentModelProvider(
        GatewayConfig(**config),
        SecretStr("test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ).build(model_id=model_id, timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0)


def _priced(chunks: list[Any]) -> dict[str, Any]:
    return next(c for c in chunks if c.usage_metadata).response_metadata


def test_a_responses_reply_is_priced_from_its_own_usage_block_on_the_research_path() -> None:
    """``ainvoke`` is the research agents' path: ``with_raw_response.create`` then ``parse()``."""
    lookups: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            lookups.append(request)
            return httpx.Response(404, request=request)
        return httpx.Response(200, json=_response(BYOK_USAGE), request=request)

    metadata = asyncio.run(_model(respond).ainvoke("hi")).response_metadata

    assert metadata["clue_cost_source"] == "metered"
    assert Decimal(metadata["clue_cost_cents"]) == Decimal("1.83529")
    assert lookups == []  # priced from the reply, not the slow /generation record


def test_a_sync_responses_reply_is_priced_from_its_own_usage_block() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, request=request)
        return httpx.Response(200, json=_response(BYOK_USAGE), request=request)

    metadata = _model(respond).invoke("hi").response_metadata

    assert metadata["clue_cost_source"] == "metered"
    assert Decimal(metadata["clue_cost_cents"]) == Decimal("1.83529")


def test_a_streamed_chat_completions_reply_counts_the_upstream_charge_of_an_own_key_call() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        chunks = [
            {
                "id": "gen-x",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
            {
                "id": "gen-x",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": payload["model"],
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                    "cost": 0,
                    "is_byok": True,
                    "cost_details": {"upstream_inference_cost": 0.002},
                },
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n",
        )

    model = _model(respond, model_id="x-ai/grok-4.6", openrouter_chat_completions_fallback=True)
    metadata = _priced(list(model.stream("hi")))

    assert metadata["clue_cost_source"] == "metered"
    assert Decimal(metadata["clue_cost_cents"]) == Decimal("0.2")


def test_the_generation_record_counts_the_upstream_charge_of_an_own_key_call() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"total_cost": 0, "is_byok": True, "upstream_inference_cost": 0.0183529}},
            request=request,
        )

    lookup = OpenRouterGenerationCost(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr("test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    assert lookup.cost_cents("gen-sol-1") == Decimal("1.83529")


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (
            {"cost": 0, "is_byok": True, "cost_details": {"upstream_inference_cost": 0.00123}},
            "0.00123",
        ),
        ({"cost": 0.5}, "0.5"),
        ({"cost": 0.5, "cost_details": {"upstream_inference_cost": None}}, "0.5"),
        ({}, None),
        (None, None),
        ({"cost": True}, None),
    ],
)
def test_the_charged_amount_prefers_the_upstream_charge_then_the_openrouter_cost(
    usage: Any, expected: str | None
) -> None:
    charged = openrouter_charged_usd(usage)
    assert charged == (Decimal(expected) if expected is not None else None)
