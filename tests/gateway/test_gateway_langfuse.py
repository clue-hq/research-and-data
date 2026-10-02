"""Lane 3 slice 3b, Task 1: the gateway decorator reports every non-graph call to Langfuse as a
generation / embedding carrying the settled cost — and reports nothing when Langfuse is off."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from clue_config.gateway import GatewayConfig, ModelPrice
from clue_core.gateway import Message
from clue_gateway.factory import build_gateway
from tests._langfuse import finished_spans, langfuse_installed

_PROMPT = [Message(role="system", content="be brief"), Message(role="user", content="hi")]


def _priced() -> GatewayConfig:
    return GatewayConfig(
        prices={
            "anthropic/claude-3.5-sonnet": ModelPrice(
                prompt_cents_per_1k=Decimal(2), completion_cents_per_1k=Decimal(3)
            )
        }
    )


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_off_the_gateway_still_answers_and_emits_only_its_otel_span() -> None:
    gw = build_gateway(_priced())  # no key → stub, wrapped in TracingGateway
    out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
    assert out.text


def test_complete_exports_a_generation_with_usage_and_settled_cost() -> None:
    with langfuse_installed() as (exporter, _provider):
        gw = build_gateway(_priced())
        out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
        spans = finished_spans(exporter)
    generation = next(s for s in spans if s.name == "gateway.completion")
    attrs = _attrs(generation)
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == out.model
    usage = json.loads(attrs["langfuse.observation.usage_details"])
    assert usage == {
        "input": out.usage.prompt_tokens,
        "output": out.usage.completion_tokens,
        "cache_read_input": out.usage.cached_prompt_tokens,
    }
    cost = json.loads(attrs["langfuse.observation.cost_details"])
    assert cost == {"total": float(out.cost_cents / Decimal(100))}
    payload = json.loads(attrs["langfuse.observation.input"])
    assert payload == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    output = json.loads(attrs["langfuse.observation.output"])
    assert output["text"] == out.text
    assert attrs["langfuse.observation.metadata.requested_model"] == "anthropic/claude-3.5-sonnet"


def test_embed_exports_an_embedding_with_counts_never_the_texts() -> None:
    with langfuse_installed() as (exporter, _provider):
        gw = build_gateway(GatewayConfig())
        gw.embed(model="text-embed", inputs=["a private sentence", "another"])
        spans = finished_spans(exporter)
    embedding = next(s for s in spans if s.name == "gateway.embedding")
    attrs = _attrs(embedding)
    assert attrs["langfuse.observation.type"] == "embedding"
    assert json.loads(attrs["langfuse.observation.input"]) == {"inputs": 2, "characters": 25}
    assert "private" not in json.dumps(attrs)
