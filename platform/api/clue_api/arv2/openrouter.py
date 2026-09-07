"""The thin OpenRouter HTTP helpers the ARV2 LLM clients share — no SDK, by design.

The platform's other OpenRouter egress (``clue_gateway``) speaks the Responses API through the
OpenAI SDK. ARV2 does not: every ARV2 provider call, model calls included, goes over plain HTTP
through :class:`~clue_api.arv2.calls.ProviderCaller`, so one wrapper owns the raw record, the
ledger row and the retry arithmetic for the whole lane. That is why this module builds requests
and reads bodies, and never sends anything itself.

Base URL and key are parameters. The call site reads them from
``clue_config.GatewayConfig().base_url`` and ``Secrets.openrouter_api_key``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import SecretStr

from clue_api.arv2.calls import CostReading
from clue_api.arv2.transport import HttpRequest, HttpResponse, json_request

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


def _decimal(value: object) -> Decimal | None:
    """A provider-reported number as an exact Decimal, or ``None`` when it is not a number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def openrouter_cost_reader(response: Any) -> CostReading:
    """Read OpenRouter's own metering off a chat/embeddings response (Appendix A law 1).

    ``usage.cost_details.upstream_inference_cost`` is preferred over ``usage.cost`` because a BYOK
    key reports ``cost: 0`` while the upstream provider still charged — reading ``cost`` alone
    would record a real spend as free.

    Takes the :class:`~clue_api.arv2.transport.HttpResponse` the wrapper received; a body that is
    not JSON yields an empty reading rather than raising, because the wrapper treats an unreadable
    cost as "the provider did not tell us", never as zero.
    """
    try:
        body = json.loads(response.body)
    except (ValueError, AttributeError):
        return CostReading()
    if not isinstance(body, dict):
        return CostReading()
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("cost_details")
    details = details if isinstance(details, dict) else {}
    cost = _decimal(details.get("upstream_inference_cost"))
    if cost is None:
        cost = _decimal(usage.get("cost"))
    request_id = body.get("id")
    return CostReading(
        cost_usd=cost,
        provider_request_id=request_id if isinstance(request_id, str) else None,
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


def openrouter_halt_rule(response: HttpResponse) -> str | None:
    """Money truth for OpenRouter (master plan §2 item 3): does this response refuse to sell?

    A 402 is the explicit refusal (key out of credit); a 403 is a key that may not spend; any other
    4xx/5xx whose body names "credit" or "insufficient" is the same refusal in prose. Only non-2xx
    bodies are inspected — a successful completion about a bank names "credit" constantly, and
    latching the lane's model provider on the content of a good answer would be a self-inflicted
    outage. Returning a reason latches the provider in the wrapper.
    """
    if response.status == 402:
        return "payment_required"
    if response.status == 403:
        return "forbidden"
    if 200 <= response.status < 300:
        return None
    body = response.body.decode("utf-8", "replace").lower()
    if "credit" in body or "insufficient" in body:
        return "credit_exhausted"
    return None
