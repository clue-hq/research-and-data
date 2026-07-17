"""The deterministic offline ``LLMGateway`` stub (M0.4) — the CI / eval-harness path.

No network, no key, no ``openai`` import: the acceptance criterion is that CI and the M0.6 eval
harness make **no live LLM calls**. The stub is *deterministic* — identical inputs yield identical
outputs across runs and processes (a hash of the prompt) — so eval/regression assertions are stable.
It honors the requested ``model`` (echoed on the result and the span) so a config model-swap is
observable, and it computes ``cost_cents`` from the configured price table exactly like the live
client, so cost assertions are exercised offline too.
"""

from __future__ import annotations

import hashlib

from clue_core.gateway import Completion, EmbeddingResult, Message, TokenUsage, Vector
from clue_research.config.gateway import GatewayConfig

# Dimensionality of a stub embedding vector — small, deterministic, enough for a candidate-set test.
_EMBED_DIM = 8


class StubGateway:
    """A deterministic, offline :class:`~clue_core.gateway.LLMGateway` (no live call)."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        prompt_text = "\n".join(m.content for m in messages)
        # A stable canned answer derived from the prompt (same prompt -> same text, any process).
        digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        text = f"stub:{digest}"
        usage = TokenUsage(
            prompt_tokens=_token_estimate(prompt_text),
            completion_tokens=_token_estimate(text),
        )
        return Completion(
            model=model,
            text=text,
            usage=usage,
            cost_cents=self._config.cost_cents(model, usage),
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        vectors = tuple(_stub_vector(text) for text in inputs)
        usage = TokenUsage(prompt_tokens=sum(_token_estimate(t) for t in inputs))
        return EmbeddingResult(
            model=model,
            vectors=vectors,
            usage=usage,
            cost_cents=self._config.cost_cents(model, usage),
        )


def _token_estimate(text: str) -> int:
    """A crude deterministic token proxy (~4 chars/token) — stable usage/cost in tests."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _stub_vector(text: str) -> Vector:
    """A deterministic unit-range vector derived from the text (stable across runs)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:_EMBED_DIM]]
