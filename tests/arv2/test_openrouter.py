"""The shared OpenRouter helpers' pure rules: the halt rule and the cost reader. No double."""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_api.arv2.openrouter import openrouter_cost_reader, openrouter_halt_rule
from clue_api.arv2.transport import HttpResponse


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (402, b'{"error":"Insufficient credits"}', "payment_required"),
        # 403 is OpenRouter's MODERATION verdict on the input, not a refusal to sell. Latching on
        # it would let one flagged bundle take the whole run's model calls down.
        (403, b'{"error":{"message":"flagged by moderation"}}', None),
        (
            429,
            b'{"error":{"message":"insufficient credits to run this model"}}',
            "credit_exhausted",
        ),
        (500, b'{"error":"credit system unavailable"}', "credit_exhausted"),
        (429, b'{"error":"rate limited"}', None),
        (404, b"no such model", None),
        (
            200,
            b'{"choices":[{"message":{"content":"the credit union raised insufficient capital"}}]}',
            None,
        ),
    ],
)
def test_the_halt_rule_latches_only_on_a_refusal_to_sell(
    status: int, body: bytes, expected: str | None
) -> None:
    assert openrouter_halt_rule(HttpResponse(status, {}, body)) == expected


def test_a_moderation_403_never_latches_but_a_403_naming_credit_still_does() -> None:
    """The 403 carve-out is about the *status*, not about ignoring a stated money refusal.

    ARV2 bundles are scraped open-web prose, so a moderation 403 is an ordinary event and must
    cost only the one call. A 403 whose body says the account is out of credit is still a refusal
    to sell and still latches, through the body test every non-2xx goes through.
    """
    moderation = HttpResponse(403, {}, b'{"error":{"message":"Input flagged: violence"}}')
    assert openrouter_halt_rule(moderation) is None

    money = HttpResponse(403, {}, b'{"error":{"message":"insufficient credits on this key"}}')
    assert openrouter_halt_rule(money) == "credit_exhausted"


def test_the_cost_reader_prefers_upstream_inference_cost_and_keeps_the_request_id() -> None:
    body = b'{"id":"gen-1","usage":{"cost":0,"cost_details":{"upstream_inference_cost":0.00123}}}'
    reading = openrouter_cost_reader(HttpResponse(200, {}, body))
    assert reading.cost_usd == Decimal("0.00123")
    assert reading.provider_request_id == "gen-1"


def test_the_cost_reader_falls_back_to_cost_and_then_to_nothing() -> None:
    assert openrouter_cost_reader(HttpResponse(200, {}, b'{"usage":{"cost":0.5}}')).cost_usd == (
        Decimal("0.5")
    )
    assert openrouter_cost_reader(HttpResponse(200, {}, b"not json")).cost_usd is None


def test_the_cost_reader_stamps_the_model_and_the_token_counts() -> None:
    """Slice 1b: every OpenRouter row carries what the research agent's rows already carry, so
    the cost read's per-model view covers the structuring, media and reconcile calls too."""
    body = (
        b'{"id":"gen-2","model":"x-ai/grok-4.6","usage":{"cost":0.01,"prompt_tokens":900,'
        b'"completion_tokens":200,"prompt_tokens_details":{"cached_tokens":300}}}'
    )
    reading = openrouter_cost_reader(HttpResponse(200, {}, body))
    assert reading.cost_usd == Decimal("0.01")
    assert reading.extras == {
        "model": "x-ai/grok-4.6",
        "prompt_tokens": 900,
        "completion_tokens": 200,
        "cached_prompt_tokens": 300,
    }


def test_a_body_without_usage_or_model_counts_zero_and_names_no_model() -> None:
    reading = openrouter_cost_reader(HttpResponse(200, {}, b'{"id":"gen-3"}'))
    assert reading.extras == {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    assert openrouter_cost_reader(HttpResponse(200, {}, b"not json")).extras == {}
