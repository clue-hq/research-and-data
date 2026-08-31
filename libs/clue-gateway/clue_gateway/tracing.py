"""``TracingGateway`` (M0.4) — wrap any ``LLMGateway`` to emit the ``llm.gateway_call`` span.

Tracing lives in **one** place (DRY): the factory wraps whichever backend it builds (stub or live),
so every *direct* LLM call emits the M0.5 ``llm.gateway_call`` span carrying ``model`` + token usage
+ ``cost_cents`` (conventions §4) regardless of backend. This decorator is why the stub path is
observable in CI exactly like production. It sits in ``gateway/`` (above ``obs → config → core``),
so importing ``obs`` here is allowed — ``core``/``config`` may not.

Post-call attributes (known only after the inner call returns) are set through the single
:func:`~clue_obs.otel.apply_attributes` redaction seam — never an ad-hoc ``set_attribute`` — so
every gateway-span attribute passes the one redaction chokepoint.

Alongside the span, every call emits the structured ``model_call_usage`` structlog event (Doc R
§4) — the per-call telemetry Doc A §1.3's per-tier agency-vs-coverage measurement reads.
"""

from __future__ import annotations

import time
from decimal import Decimal

from opentelemetry.trace import Span

from clue_core.gateway import Completion, EmbeddingResult, LLMGateway, Message, TokenUsage
from clue_obs import get_logger
from clue_obs.otel import (
    ATTR_AGENT_ROLE,
    ATTR_COMPLETION_TOKENS,
    ATTR_COST_CENTS,
    ATTR_MODEL,
    ATTR_PROMPT_TOKENS,
    ATTR_TOTAL_TOKENS,
    SPAN_LLM_GATEWAY_CALL,
    apply_attributes,
    traced_step,
)

#: The structured usage event name (Doc R §4) — one per gateway completion/embedding call.
EVENT_MODEL_CALL_USAGE = "model_call_usage"

_log = get_logger("clue_gateway")


class TracingGateway:
    """Delegates to an inner gateway, emitting the ``llm.gateway_call`` span around each call."""

    def __init__(self, inner: LLMGateway) -> None:
        self._inner = inner

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        with traced_step(SPAN_LLM_GATEWAY_CALL, **{ATTR_MODEL: model}) as span:
            started = time.perf_counter()
            completion = self._inner.complete(model=model, messages=messages, **opts)
            duration_ms = (time.perf_counter() - started) * 1000.0
            record_model_call(
                span=span,
                call_kind="completion",
                requested_model=model,
                served_model=completion.model,
                usage=completion.usage,
                cost_cents=completion.cost_cents,
                duration_ms=duration_ms,
            )
            return completion

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        with traced_step(SPAN_LLM_GATEWAY_CALL, **{ATTR_MODEL: model}) as span:
            started = time.perf_counter()
            result = self._inner.embed(model=model, inputs=inputs)
            duration_ms = (time.perf_counter() - started) * 1000.0
            record_model_call(
                span=span,
                call_kind="embedding",
                requested_model=model,
                served_model=result.model,
                usage=result.usage,
                cost_cents=result.cost_cents,
                duration_ms=duration_ms,
            )
            return result


def record_model_call(
    *,
    span: Span,
    call_kind: str,
    requested_model: str,
    served_model: str,
    usage: TokenUsage,
    cost_cents: Decimal,
    duration_ms: float,
    role: str | None = None,
) -> None:
    """Record one direct or agentic call through the shared model-observability seam.

    ``served_model`` is the id that actually answered — it may differ from ``requested_model``
    under the configured fallback. ``role`` (P3.2) is the agent-role attribution label — the
    ONE per-role usage authority (PD-part3 delta 6); ``cached_prompt_tokens`` is the
    provider-reported cached-prefill share (0 unless the OpenRouter ``usage.include``
    passthrough is on), the measurable form of the design runtime's prefill economics.
    """
    attrs = _result_attrs(served_model, usage, cost_cents)
    if role is not None:
        attrs[ATTR_AGENT_ROLE] = role
    apply_attributes(span, attrs)
    _log.info(
        EVENT_MODEL_CALL_USAGE,
        call_kind=call_kind,
        requested_model=requested_model,
        served_model=served_model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_prompt_tokens=usage.cached_prompt_tokens,
        total_tokens=usage.total_tokens,
        cost_cents=cost_cents,
        duration_ms=round(duration_ms, 3),
        **({"role": role} if role is not None else {}),
    )


def _result_attrs(model: str, usage: TokenUsage, cost_cents: Decimal) -> dict[str, object]:
    """The post-call span attributes (the result is known only after the inner call returns)."""
    return {
        ATTR_MODEL: model,
        ATTR_PROMPT_TOKENS: usage.prompt_tokens,
        ATTR_COMPLETION_TOKENS: usage.completion_tokens,
        ATTR_TOTAL_TOKENS: usage.total_tokens,
        ATTR_COST_CENTS: cost_cents,
    }
