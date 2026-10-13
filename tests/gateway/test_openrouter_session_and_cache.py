"""Prompt-cache routing on the wire, with no provider spend.

Run 3 (2026-10-09): ten Grok calls re-sent a byte-identical prompt and still missed the cache,
because nothing kept a conversation on one server. A session id bound to the call must reach
OpenRouter as ``x-session-id`` on both request routes, and an Anthropic model, which caches only
when asked, must ask.
"""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import OpenRouterAgentModelProvider


def _responses_reply(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "id": "resp-session",
            "object": "response",
            "created_at": 1_775_000_000,
            "model": payload["model"],
            "output": [
                {
                    "id": "msg-session",
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
                "input_tokens": 4,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 1,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 5,
            },
            "status": "completed",
        },
        request=request,
    )


def _chat_reply(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    chunks = [
        {
            "id": "gen-session",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}}],
        },
        {
            "id": "gen-session",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": payload["model"],
            "choices": [],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        },
    ]
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n",
    )


def _model(*, chat_route: bool, model_id: str, seen: list[httpx.Request]) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method != "POST":  # the cost lookup that follows a call, not the call
            return httpx.Response(404, request=request)
        seen.append(request)
        return _chat_reply(request) if chat_route else _responses_reply(request)

    return OpenRouterAgentModelProvider(
        GatewayConfig(openrouter_chat_completions_fallback=chat_route),
        SecretStr("test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ).build(model_id=model_id, timeout_s=10, max_retries=0, max_output_tokens=64, temperature=0)


@pytest.mark.parametrize("chat_route", [False, True], ids=["responses", "chat-completions"])
def test_a_session_id_bound_to_the_call_reaches_openrouter_as_x_session_id(
    chat_route: bool,
) -> None:
    seen: list[httpx.Request] = []
    model = _model(chat_route=chat_route, model_id="x-ai/grok-4.6", seen=seen)

    reply = model.bind(extra_headers={"x-session-id": "execution-1"})
    if chat_route:
        list(reply.stream("hi"))
    else:
        reply.invoke("hi")

    assert seen[-1].headers["x-session-id"] == "execution-1"


def test_a_call_without_a_session_sends_no_session_header() -> None:
    seen: list[httpx.Request] = []
    _model(chat_route=False, model_id="x-ai/grok-4.6", seen=seen).invoke("hi")

    assert "x-session-id" not in seen[-1].headers


@pytest.mark.parametrize("chat_route", [False, True], ids=["responses", "chat-completions"])
def test_an_anthropic_model_asks_openrouter_to_cache_the_prompt(chat_route: bool) -> None:
    """Anthropic caches only when the request carries ``cache_control``; the top-level form lets
    OpenRouter place the breakpoint at the end of the prompt on every call."""
    seen: list[httpx.Request] = []
    model = _model(chat_route=chat_route, model_id="anthropic/claude-opus-5-5", seen=seen)
    if chat_route:
        list(model.stream("hi"))
    else:
        model.invoke("hi")

    assert json.loads(seen[-1].content)["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize("model_id", ["x-ai/grok-4.6", "openai/gpt-6.1-sol"])
def test_models_that_cache_on_their_own_get_no_cache_control(model_id: str) -> None:
    seen: list[httpx.Request] = []
    _model(chat_route=False, model_id=model_id, seen=seen).invoke("hi")

    assert "cache_control" not in json.loads(seen[-1].content)
