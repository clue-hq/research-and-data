"""The thin OpenRouter HTTP helpers the ARV2 LLM clients share — no SDK, by design.

The platform's other OpenRouter egress (``clue_gateway``) speaks the Responses API through the
OpenAI SDK. ARV2 does not: every ARV2 provider call, model calls included, goes over plain HTTP
through :class:`~clue_spend.calls.ProviderCaller`, so one wrapper owns the raw record, the
ledger row and the retry arithmetic for the whole lane. That is why this module builds requests
and reads bodies, and never sends anything itself.

Base URL and key are parameters. The call site reads them from
``clue_config.GatewayConfig().base_url`` and ``Secrets.openrouter_api_key``.

Lane 3 slice 5 moved the two provider-agnostic halves — reading OpenRouter's own metering off a
response, and knowing when it refuses to sell — into :mod:`clue_spend.openrouter`, because the
design subsystem reads the same numbers onto the same ledger. They are re-exported here so
``from clue_api.arv2.openrouter import openrouter_cost_reader`` keeps working. What *builds* a
request stays: the headers, the attribution and the model choice are this lane's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import SecretStr

from clue_spend.openrouter import openrouter_cost_reader, openrouter_halt_rule
from clue_spend.transport import HttpRequest, json_request

__all__ = [
    "OPENROUTER_REFERER",
    "OPENROUTER_TITLE",
    "openrouter_chat_request",
    "openrouter_cost_reader",
    "openrouter_embeddings_request",
    "openrouter_halt_rule",
    "openrouter_message_text",
]

#: Sent on every ARV2 OpenRouter call so the provider's own dashboards attribute the spend.
OPENROUTER_REFERER = "https://cluehq.ai/arv2"
OPENROUTER_TITLE = "Clue ARV2"


def _headers(api_key: SecretStr) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key.get_secret_value()}",
        "HTTP-Referer": OPENROUTER_REFERER,
        "X-Title": OPENROUTER_TITLE,
    }


def openrouter_chat_request(
    *,
    base_url: str,
    api_key: SecretStr,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    response_format: Mapping[str, Any] | None = None,
    reasoning: Mapping[str, Any] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    extra: Mapping[str, object] | None = None,
    timeout_s: float,
) -> HttpRequest:
    """Build one chat-completions request.

    ``usage.include`` is always on: without it OpenRouter reports no cost, and law 1 requires the
    ledger row to carry the provider's own metering rather than a guess.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [dict(message) for message in messages],
        "usage": {"include": True},
    }
    if response_format is not None:
        body["response_format"] = dict(response_format)
    if reasoning is not None:
        body["reasoning"] = dict(reasoning)
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    if extra:
        body.update(dict(extra))
    return json_request(
        "POST",
        f"{base_url.rstrip('/')}/chat/completions",
        headers=_headers(api_key),
        json_body=body,
        timeout_s=timeout_s,
    )


def openrouter_embeddings_request(
    *,
    base_url: str,
    api_key: SecretStr,
    model: str,
    inputs: Sequence[str],
    dimensions: int | None = None,
    timeout_s: float,
) -> HttpRequest:
    """Build one embeddings request (text embeddings only — Appendix A law 11)."""
    body: dict[str, Any] = {"model": model, "input": list(inputs)}
    if dimensions is not None:
        body["dimensions"] = dimensions
    return json_request(
        "POST",
        f"{base_url.rstrip('/')}/embeddings",
        headers=_headers(api_key),
        json_body=body,
        timeout_s=timeout_s,
    )


def openrouter_message_text(body: object) -> str:
    """The first choice's assistant text, or ``""`` when the model returned none.

    An empty string is an honest outcome (a model that spent its whole budget on reasoning returns
    no content); the caller decides whether that is a zero-yield result or a defect.
    """
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""
