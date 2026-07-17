"""``TracingGateway`` (M0.4) — wrap any ``LLMGateway`` to emit the ``llm.gateway_call`` span.

Tracing lives in **one** place (DRY): the factory wraps whichever backend it builds (stub or live),
so every *direct* LLM call emits the M0.5 ``llm.gateway_call`` span carrying ``model`` + token usage
+ ``cost_cents`` (conventions §4) regardless of backend. This decorator is why the stub path is
observable in CI exactly like production. It sits in ``gateway/`` (above ``obs → config → core``),
so importing ``obs`` here is allowed — ``core``/``config`` may not.

Post-call attributes (known only after the inner call returns) are set through the single
:func:`~clue_research.obs.apply_attributes` redaction seam — never an ad-hoc ``set_attribute`` — so
every gateway-span attribute passes the one redaction chokepoint.
"""

from __future__ import annotations

from decimal import Decimal

from clue_core.gateway import Completion, EmbeddingResult, LLMGateway, Message, TokenUsage
from clue_research.obs import (
    ATTR_COMPLETION_TOKENS,
    ATTR_COST_CENTS,
    ATTR_MODEL,
    ATTR_PROMPT_TOKENS,
    ATTR_TOTAL_TOKENS,
    SPAN_LLM_GATEWAY_CALL,
    apply_attributes,
    traced_step,
)


class TracingGateway:
    """Delegates to an inner gateway, emitting the ``llm.gateway_call`` span around each call."""

    def __init__(self, inner: LLMGateway) -> None:
        self._inner = inner

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        with traced_step(SPAN_LLM_GATEWAY_CALL, **{ATTR_MODEL: model}) as span:
            completion = self._inner.complete(model=model, messages=messages, **opts)
            apply_attributes(
                span, _result_attrs(completion.model, completion.usage, completion.cost_cents)
            )
            return completion

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        with traced_step(SPAN_LLM_GATEWAY_CALL, **{ATTR_MODEL: model}) as span:
            result = self._inner.embed(model=model, inputs=inputs)
            apply_attributes(span, _result_attrs(result.model, result.usage, result.cost_cents))
            return result


def _result_attrs(model: str, usage: TokenUsage, cost_cents: Decimal) -> dict[str, object]:
    """The post-call span attributes (the result is known only after the inner call returns)."""
    return {
        ATTR_MODEL: model,
        ATTR_PROMPT_TOKENS: usage.prompt_tokens,
        ATTR_COMPLETION_TOKENS: usage.completion_tokens,
        ATTR_TOTAL_TOKENS: usage.total_tokens,
        ATTR_COST_CENTS: cost_cents,
    }
