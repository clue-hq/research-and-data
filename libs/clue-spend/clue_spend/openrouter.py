"""Reading OpenRouter's own metering, and knowing when it refuses to sell.

These two functions are the provider-specific half of Appendix A laws 1 and 3 for the one provider
every subsystem shares: the cost reader a :class:`~clue_spend.calls.CallSpec` hands the wrapper so
a result row carries what OpenRouter says it charged, and the halt rule that latches the provider
when it will not sell. They live here rather than with a lane's client because the ledger they feed
is one ledger — the platform's ARV2 lane and the design subsystem read the same numbers the same
way, or the totals mean nothing.

Everything that *builds* an OpenRouter request stays with its caller: a request carries the
caller's headers, its attribution and its model choice, and none of that is shared.
"""

from __future__ import annotations

import json

from clue_core.openrouter_cost import openrouter_charged_usd

from .calls import CostReading
from .transport import HttpResponse

__all__ = ["openrouter_cost_reader", "openrouter_halt_rule"]


def openrouter_cost_reader(response: HttpResponse) -> CostReading:
    """Read OpenRouter's own metering off a chat/embeddings response (Appendix A law 1).

    ``usage.cost_details.upstream_inference_cost`` is preferred over ``usage.cost`` because a BYOK
    key reports ``cost: 0`` while the upstream provider still charged — reading ``cost`` alone
    would record a real spend as free.

    Takes the :class:`~clue_spend.transport.HttpResponse` the wrapper received; a body that is
    not JSON yields an empty reading rather than raising, because the wrapper treats an unreadable
    cost as "the provider did not tell us", never as zero.

    The model and the token counts (``prompt_tokens``, ``completion_tokens``,
    ``prompt_tokens_details.cached_tokens``) ride ``extras`` under the same keys the research
    agent's rows use.
    """
    try:
        body = json.loads(response.body)
    except (ValueError, AttributeError):
        return CostReading()
    if not isinstance(body, dict):
        return CostReading()
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    cost = openrouter_charged_usd(usage)
    request_id = body.get("id")
    # The model that answered and the token counts ride along as extras, under the same keys the
    # research agent writes on its ``round-*`` rows, so the per-model cost breakdown reads every
    # chat/completions row the same way. Only what the body actually said is written.
    extras: dict[str, object] = {}
    model = body.get("model")
    if isinstance(model, str) and model:
        extras["model"] = model
    prompt_details = usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    for key, value in (
        ("prompt_tokens", usage.get("prompt_tokens")),
        ("completion_tokens", usage.get("completion_tokens")),
        ("cached_prompt_tokens", prompt_details.get("cached_tokens")),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            extras[key] = value
    return CostReading(
        cost_usd=cost,
        provider_request_id=request_id if isinstance(request_id, str) else None,
        extras=extras,
    )


def openrouter_halt_rule(response: HttpResponse) -> str | None:
    """Money truth for OpenRouter (master plan §2 item 3): does this response refuse to sell?

    A 402 is the explicit refusal (key out of credit); any other non-2xx whose body names "credit"
    or "insufficient" is the same refusal in prose. Only non-2xx bodies are inspected — a
    successful completion about a bank names "credit" constantly, and latching the lane's model
    provider on the content of a good answer would be a self-inflicted outage. Returning a reason
    latches the provider in the wrapper.

    **403 is deliberately not a halt here.** In OpenRouter's error vocabulary a 403 is a
    *moderation verdict on the input*, not a refusal to sell — a per-request content decision. ARV2
    bundles are scraped open-web prose, so one flagged bundle would otherwise latch ``openrouter``
    process-wide and take structuring, short transcription, quote mining and embeddings down with
    it for the rest of the run: the same self-inflicted outage, arriving through a different door.
    Providers whose 403 really *is* denial (AI Ark's Cloudflare block, Exa's auth) keep latching on
    it in their own rules — the halt rule is per provider precisely so this can differ.
    """
    if response.status == 402:
        return "payment_required"
    if 200 <= response.status < 300:
        return None
    body = response.body.decode("utf-8", "replace").lower()
    if "credit" in body or "insufficient" in body:
        return "credit_exhausted"
    return None
