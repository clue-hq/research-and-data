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
        (403, b"forbidden", "forbidden"),
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
