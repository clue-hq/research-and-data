"""The describer's output cap (2026-09-29).

A describe call carried no ``max_tokens``, so a looping answer ran to the model's own 131072-token
ceiling at $0.157 a call; 35 of them were $5.02 of a $6.46 describe bill. The cap is per asset,
generous against a measured p99 of ~15k, and it is on the wire — the transport sees it.
"""

from __future__ import annotations

import json

from lumen_ingestion import describe as describe_module
from lumen_ingestion.describe import (
    MAX_DESCRIBE_TOKENS,
    DescribeItem,
    OpenRouterDescriber,
    describe_max_tokens,
)
from py_lumen_config import settings

from clue_spend import HttpResponse


def _item(asset_id: str = "ast_1") -> DescribeItem:
    return DescribeItem(
        asset_id=asset_id, kind="photo", image_b64="iVBORw0KGgo=", filename="a.png", context=""
    )


def test_the_cap_is_per_asset_and_never_above_the_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(settings, "lumen_ingestion_describe_max_tokens_per_asset", 32768)
    assert describe_max_tokens(1) == 32768
    assert describe_max_tokens(0) == 32768  # an empty call still asks for a bounded answer
    assert describe_max_tokens(3) == 98304
    assert describe_max_tokens(5) == MAX_DESCRIBE_TOKENS  # 163840 would exceed the ceiling


def test_the_describe_request_carries_max_tokens(monkeypatch) -> None:
    monkeypatch.setattr(settings, "lumen_ingestion_describe", True)
    monkeypatch.setattr(settings, "lumen_ingestion_describe_max_tokens_per_asset", 4096)
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    sent: list[dict] = []

    def fake_openrouter_call(**kw):
        sent.append(kw["body"])
        content = json.dumps([])  # no descriptions: the body shape is what this test pins
        return HttpResponse(
            status=200,
            body=json.dumps({"choices": [{"message": {"content": content}}]}).encode(),
        )

    from lumen_api import spend

    monkeypatch.setattr(spend, "openrouter_call", fake_openrouter_call)
    describer = OpenRouterDescriber()
    results = describer.describe([_item()])

    assert results == [None]  # nothing described, nothing invented
    assert len(sent) == 1
    assert sent[0]["max_tokens"] == 4096
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert describe_module.MAX_DESCRIBE_TOKENS == 131072
