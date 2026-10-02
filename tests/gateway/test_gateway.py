"""M0.4 acceptance: the shared LLMGateway (OpenRouter) — stub determinism, tracing, cost, swap.

CI runs entirely on the deterministic stub (no live LLM call). The live ``OpenRouterGateway`` logic
(message mapping, usage/cost, fallback) is exercised hermetically through an injected fake client —
the ``openai`` SDK is never imported or called here.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from clue_config import (
    ConfigOverlay,
    GatewayConfig,
    ModelPrice,
    default_gateway_config,
    get_config,
)
from clue_config.loader import OverlayStore
from clue_core import Completion, EmbeddingResult, LLMGateway, Message, Role, TokenUsage
from clue_gateway import (
    EVENT_MODEL_CALL_USAGE,
    GatewayError,
    OpenRouterGateway,
    StubGateway,
    TracingGateway,
    build_gateway,
)
from clue_obs import capture_events
from clue_obs.otel import SPAN_LLM_GATEWAY_CALL, collect_spans
from tests._model_ids import assert_well_formed_model_id

# --- fixtures ---------------------------------------------------------------

_PROMPT = [Message(role=Role.USER, content="hello there")]


def _priced_config(**overrides: Any) -> GatewayConfig:
    """A config that prices ``judge_model`` so cost assertions are non-zero and exact."""
    base: dict[str, Any] = {
        "prices": {
            "anthropic/claude-3.5-sonnet": ModelPrice(
                prompt_cents_per_1k=Decimal(300), completion_cents_per_1k=Decimal(1500)
            )
        }
    }
    base.update(overrides)
    return GatewayConfig(**base)


# --- the stub: determinism + model passthrough + cost -----------------------


def test_stub_is_deterministic() -> None:
    gw = StubGateway(GatewayConfig())
    a = gw.complete(model="m", messages=_PROMPT)
    b = gw.complete(model="m", messages=_PROMPT)
    assert a == b  # frozen models compare by value: same input -> identical output
    assert a.text.startswith("stub:")
    assert a.usage.total_tokens == a.usage.prompt_tokens + a.usage.completion_tokens


def test_stub_honors_requested_model() -> None:
    gw = StubGateway(GatewayConfig())
    assert gw.complete(model="A", messages=_PROMPT).model == "A"
    assert gw.complete(model="B", messages=_PROMPT).model == "B"


def test_stub_computes_cost_from_price_table() -> None:
    gw = StubGateway(_priced_config())
    out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
    expected = Decimal(300) * Decimal(out.usage.prompt_tokens) / Decimal(1000) + Decimal(
        1500
    ) * Decimal(out.usage.completion_tokens) / Decimal(1000)
    assert out.cost_cents == expected
    assert out.cost_cents > 0


def test_stub_unpriced_model_costs_zero() -> None:
    # measured-or-zero: a model with no configured price reports 0, never a fabricated cost.
    out = StubGateway(GatewayConfig()).complete(model="unpriced", messages=_PROMPT)
    assert out.cost_cents == Decimal(0)


def test_stub_embed_is_deterministic_and_shaped() -> None:
    gw = StubGateway(GatewayConfig())
    a = gw.embed(model="e", inputs=["x", "y"])
    b = gw.embed(model="e", inputs=["x", "y"])
    assert a == b
    assert len(a.vectors) == 2
    assert all(0.0 <= v <= 1.0 for vec in a.vectors for v in vec)


# --- tracing: every call emits llm.gateway_call with model/tokens/cost ------


def test_complete_emits_gateway_span_with_usage_and_cost() -> None:
    gw = build_gateway(_priced_config())  # no key -> stub, wrapped in TracingGateway
    with collect_spans() as exporter:
        out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == SPAN_LLM_GATEWAY_CALL
    assert span.attributes is not None
    assert span.attributes["model"] == "anthropic/claude-3.5-sonnet"
    assert span.attributes["prompt_tokens"] == out.usage.prompt_tokens  # count NOT redacted
    assert span.attributes["completion_tokens"] == out.usage.completion_tokens
    assert span.attributes["total_tokens"] == out.usage.total_tokens
    assert span.attributes["cost_cents"] == str(out.cost_cents)  # Decimal -> str on the span


def test_embed_emits_gateway_span() -> None:
    gw = build_gateway(GatewayConfig())
    with collect_spans() as exporter:
        gw.embed(model="text-embed", inputs=["a"])
    span = exporter.get_finished_spans()[0]
    assert span.name == SPAN_LLM_GATEWAY_CALL
    assert span.attributes is not None
    assert span.attributes["model"] == "text-embed"


def test_no_api_key_value_appears_in_span_attributes() -> None:
    secret = "sk-or-supersecret-0123456789abcdef"
    gw = build_gateway(GatewayConfig(stub=True), SecretStr(secret))  # stub even with a key
    with collect_spans() as exporter:
        gw.complete(model="m", messages=_PROMPT)
    attrs = exporter.get_finished_spans()[0].attributes
    assert attrs is not None
    assert all(secret not in str(v) for v in attrs.values())


# --- the model_call_usage structured event (Doc R §4 / Doc A §1.3) ----------


def test_complete_emits_model_call_usage_event() -> None:
    gw = build_gateway(_priced_config())  # no key -> stub, wrapped in TracingGateway
    with capture_events() as cap:
        out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
    events = cap.events(EVENT_MODEL_CALL_USAGE)
    assert len(events) == 1  # exactly one usage event per gateway call
    ev = events[0]
    assert ev["call_kind"] == "completion"
    assert ev["requested_model"] == "anthropic/claude-3.5-sonnet"
    assert ev["served_model"] == out.model  # the id that actually answered
    assert ev["prompt_tokens"] == out.usage.prompt_tokens
    assert ev["completion_tokens"] == out.usage.completion_tokens
    assert ev["total_tokens"] == out.usage.total_tokens
    assert isinstance(ev["duration_ms"], float)
    assert ev["duration_ms"] >= 0


def test_embed_emits_model_call_usage_event() -> None:
    gw = build_gateway(GatewayConfig())
    with capture_events() as cap:
        out = gw.embed(model="text-embed", inputs=["a", "b"])
    events = cap.events(EVENT_MODEL_CALL_USAGE)
    assert len(events) == 1
    ev = events[0]
    assert ev["call_kind"] == "embedding"
    assert ev["requested_model"] == "text-embed"
    assert ev["served_model"] == out.model
    assert ev["total_tokens"] == out.usage.total_tokens


def test_model_call_usage_event_never_carries_api_key_material() -> None:
    secret = "sk-or-supersecret-0123456789abcdef"
    gw = build_gateway(GatewayConfig(stub=True), SecretStr(secret))  # stub even with a key
    with capture_events() as cap:
        gw.complete(model="m", messages=_PROMPT)
    ev = cap.first(EVENT_MODEL_CALL_USAGE)
    assert ev is not None
    assert all("api_key" not in str(k).lower() for k in ev)  # no key-ish field name
    assert all(secret not in str(v) for v in ev.values())  # no key value leaks


# --- the factory: stub/live toggle (decision #3 — hermetic CI) --------------


def test_factory_stubs_when_no_key() -> None:
    gw = build_gateway(GatewayConfig())  # stub=False default, but no key
    assert isinstance(gw, TracingGateway)
    assert isinstance(gw._inner, StubGateway)


def test_factory_stubs_when_stub_flag_set_even_with_key() -> None:
    gw = build_gateway(GatewayConfig(stub=True), SecretStr("sk-or-x"))
    assert isinstance(gw._inner, StubGateway)


def test_factory_builds_live_when_key_present_and_not_stubbed() -> None:
    gw = build_gateway(GatewayConfig(stub=False), SecretStr("sk-or-x"))
    assert isinstance(gw._inner, OpenRouterGateway)


def test_stub_path_does_not_import_openai() -> None:
    # The hermetic-CI guarantee: the stub path never imports the model SDK.
    sys.modules.pop("openai", None)
    build_gateway(GatewayConfig()).complete(model="m", messages=_PROMPT)
    assert "openai" not in sys.modules


# --- the live gateway logic, hermetic via an injected fake client -----------


class _FakeOpenRouter:
    def __init__(
        self,
        fail_models: set[str],
        empty_models: set[str] | None = None,
        error_models: set[str] | None = None,
    ) -> None:
        self._fail_models = fail_models
        self._empty_models = empty_models or set()
        self._error_models = error_models or set()
        self.calls: list[str] = []
        self.inputs: list[list[Any]] = []
        self.options: list[dict[str, Any]] = []

    @property
    def responses(self) -> Any:
        return SimpleNamespace(create=self._create)

    @property
    def embeddings(self) -> Any:
        return SimpleNamespace(create=self._embed)

    def _create(self, *, model: str, input: list[Any], **opts: Any) -> Any:
        self.calls.append(model)
        self.inputs.append(input)
        self.options.append(opts)
        if model in self._fail_models:
            raise RuntimeError(f"boom: {model}")
        if model in self._empty_models:
            return SimpleNamespace(
                model=model,
                output_text="",
                output=[],
                status="completed",
                incomplete_details=None,
                error=None,
                usage=None,
            )
        if model in self._error_models:
            return SimpleNamespace(
                model=model,
                output_text="",
                output=[],
                status="failed",
                incomplete_details=None,
                error=SimpleNamespace(message=f"upstream error: {model}"),
                usage=None,
            )
        return SimpleNamespace(
            model=model,
            output_text=f"answer from {model}",
            output=[],
            status="completed",
            incomplete_details=None,
            error=None,
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )

    def _embed(self, *, model: str, input: list[str], **opts: Any) -> Any:
        return SimpleNamespace(
            model=model,
            data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
        )


def _live(
    config: GatewayConfig,
    fail_models: set[str] | None = None,
    empty_models: set[str] | None = None,
    error_models: set[str] | None = None,
) -> OpenRouterGateway:
    fake = _FakeOpenRouter(fail_models or set(), empty_models, error_models)
    gw = OpenRouterGateway(config, SecretStr("sk-or-test"), client_factory=lambda: fake)
    gw._fake = fake  # type: ignore[attr-defined]  # stash for assertions
    return gw


def test_live_maps_response_to_completion() -> None:
    gw = _live(_priced_config())
    out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
    assert out.text == "answer from anthropic/claude-3.5-sonnet"
    assert out.model == "anthropic/claude-3.5-sonnet"
    assert out.usage == TokenUsage(prompt_tokens=11, completion_tokens=7)
    assert out.finish_reason == "completed"
    assert out.cost_cents == Decimal(300) * Decimal(11) / Decimal(1000) + Decimal(1500) * Decimal(
        7
    ) / Decimal(1000)
    assert gw._fake.inputs == [
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello there"}],
            }
        ]
    ]


def test_live_maps_provider_neutral_max_tokens_to_responses_option() -> None:
    gw = _live(GatewayConfig())

    gw.complete(model="only/model", messages=_PROMPT, max_tokens=1200, temperature=0)

    assert gw._fake.options == [{"max_output_tokens": 1200, "temperature": 0}]


def test_live_refuses_ambiguous_token_limits() -> None:
    gw = _live(GatewayConfig())

    with pytest.raises(ValueError, match="only one"):
        gw.complete(
            model="only/model",
            messages=_PROMPT,
            max_tokens=1200,
            max_output_tokens=700,
        )


def test_live_falls_back_on_primary_error() -> None:
    config = GatewayConfig(fallback_model="backup/model")
    gw = _live(config, fail_models={"primary/model"})
    out = gw.complete(model="primary/model", messages=_PROMPT)
    assert out.model == "backup/model"  # the model that actually answered
    assert gw._fake.calls == ["primary/model", "backup/model"]  # primary tried first, then fallback


def test_live_reraises_when_no_fallback() -> None:
    gw = _live(GatewayConfig(), fail_models={"only/model"})
    with pytest.raises(RuntimeError, match="boom"):
        gw.complete(model="only/model", messages=_PROMPT)


def test_live_empty_output_raises_typed_error() -> None:
    gw = _live(GatewayConfig(), empty_models={"only/model"})
    with pytest.raises(GatewayError, match="no output text") as raised:
        gw.complete(model="only/model", messages=_PROMPT)
    assert raised.value.failure_code == "gateway_no_output_completed"
    assert raised.value.completion is not None
    assert raised.value.completion.model == "only/model"
    assert raised.value.completion.finish_reason == "completed"


def test_live_empty_output_falls_back() -> None:
    config = GatewayConfig(fallback_model="backup/model")
    gw = _live(config, empty_models={"primary/model"})
    out = gw.complete(model="primary/model", messages=_PROMPT)
    assert out.model == "backup/model"  # empty primary response routed to the fallback
    assert gw._fake.calls == ["primary/model", "backup/model"]


def test_live_response_error_falls_back() -> None:
    config = GatewayConfig(fallback_model="backup/model")
    gw = _live(config, error_models={"primary/model"})
    out = gw.complete(model="primary/model", messages=_PROMPT)
    assert out.model == "backup/model"
    assert gw._fake.calls == ["primary/model", "backup/model"]


def test_live_extracts_text_from_response_output_items() -> None:
    gw = _live(GatewayConfig())
    fake = gw._fake

    def create(*, model: str, input: list[Any], **opts: Any) -> Any:
        del input, opts
        return SimpleNamespace(
            model=model,
            output_text=None,
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", text="item text")],
                )
            ],
            status="completed",
            incomplete_details=None,
            error=None,
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )

    fake._create = create
    out = gw.complete(model="only/model", messages=_PROMPT)
    assert out.text == "item text"


def test_live_embed_maps_vectors() -> None:
    gw = _live(GatewayConfig())
    out = gw.embed(model="emb", inputs=["a", "b"])
    assert out.vectors == ([0.1, 0.2, 0.3], [0.1, 0.2, 0.3])
    assert out.usage.prompt_tokens == 5


# --- the contract + config-as-data swap -------------------------------------


def test_build_gateway_returns_protocol_conformant() -> None:
    gw = build_gateway(GatewayConfig())
    assert isinstance(gw, LLMGateway)  # runtime_checkable structural conformance


def test_model_id_is_config_swappable() -> None:
    # The "model swap is a config change" property: get_config carries the gateway config, and an
    # overlay changes the per-call-site model id with no code change.
    store = OverlayStore()
    store.set_client_overlay(
        "acme", ConfigOverlay(gateway=GatewayConfig(judge_model="openai/gpt-4o"))
    )
    default_model = get_config("nobody").gateway.judge_model
    swapped_model = get_config("acme", store=store).gateway.judge_model
    # The base layer is `default_gateway_config()`, which applies the deploy-time env overrides
    # (`CLUE_SYNTHESIS_MODEL`, and since PC-C8 §6c-b `CLUE_JUDGE_MODEL`) — and `Settings` reads the
    # on-disk `.env` through `env_file`, so a hardcoded id here asserts a *deployment's* config
    # rather than this test's property. The property is "an overlay swaps the id with no code
    # change": the base is whatever the deployment resolved, and the overlay differs from it.
    assert default_model == default_gateway_config().judge_model
    assert swapped_model == "openai/gpt-4o"
    assert swapped_model != default_model
    # The unoverlaid *code* default is a well-formed id; WHICH model it is belongs to the
    # deployment (``CLUE_JUDGE_MODEL``), not to this test.
    assert_well_formed_model_id(GatewayConfig().judge_model)


def test_completion_cost_is_returned_to_caller() -> None:
    # The caller (M7 budget surface) reads cost_cents off the Completion, not just the span.
    out = build_gateway(_priced_config()).complete(
        model="anthropic/claude-3.5-sonnet", messages=_PROMPT
    )
    assert isinstance(out, Completion)
    assert out.cost_cents > 0


def test_model_price_arithmetic_is_exact_decimal() -> None:
    price = ModelPrice(prompt_cents_per_1k=Decimal("12.5"), completion_cents_per_1k=Decimal("40"))
    cost = price.cost_cents(TokenUsage(prompt_tokens=2000, completion_tokens=500))
    assert cost == Decimal("45.0")  # 12.5*2 + 40*0.5


def test_embedding_result_is_typed() -> None:
    out = build_gateway(GatewayConfig()).embed(model="e", inputs=["a"])
    assert isinstance(out, EmbeddingResult)
