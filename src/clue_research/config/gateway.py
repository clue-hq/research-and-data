"""LLM-gateway config — the policy-as-data half of the model-egress seam (M0.4, conventions §2/§4).

The gateway *client* lives in :mod:`clue_research.gateway` (it emits the ``llm.gateway_call`` span,
so it must sit above the ``obs → config → core`` layering); its *configuration* lives here, beside
every other "policy is data" surface, so a model swap — or an OpenRouter → another OpenAI-compatible
gateway swap — is a config change, never code. :class:`GatewayConfig` is folded into the layered
:class:`~clue_research.config.models.Config`, so it is per-client/per-ICP overridable through one
``get_config`` seam as merge policy, scoring, and budgets.

Pricing is config too: per-model cents-per-1k-token rates the gateway uses to compute a claim/call's
``cost_cents`` from the model-reported token usage. A model with no configured price costs ``0`` —
we report a real measured cost or zero, never a fabricated one.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from clue_research.core.gateway import TokenUsage
from clue_research.core.primitives import CostCents


class ModelPrice(BaseModel):
    """Per-model token pricing in cents per 1,000 tokens (prompt vs completion priced apart)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_cents_per_1k: Decimal = Field(default=Decimal(0), ge=0)
    completion_cents_per_1k: Decimal = Field(default=Decimal(0), ge=0)

    def cost_cents(self, usage: TokenUsage) -> CostCents:
        """Cost of one call given its token usage (exact ``Decimal`` arithmetic, never float)."""
        thousand = Decimal(1000)
        prompt = self.prompt_cents_per_1k * Decimal(usage.prompt_tokens) / thousand
        completion = self.completion_cents_per_1k * Decimal(usage.completion_tokens) / thousand
        return prompt + completion


class GatewayConfig(BaseModel):
    """Versioned config for the shared :class:`~clue_research.core.gateway.LLMGateway`.

    Every field is "policy as data": the per-call-site model ids, the base URL, timeout/retry, the
    fallback model, and the price table are all swappable without a code change. ``stub`` forces the
    offline gateway; even with ``stub=False`` the factory falls back to the stub when no
    ``OPENROUTER_API_KEY`` is present (so CI, which sets no key, never makes a live call).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "https://openrouter.ai/api/v1"
    # Per-call-site default model ids — config, not code. A call site passes one of these to
    # ``complete``/``embed``; swapping the model for that call site is editing the id here. The
    # defaults are illustrative real OpenRouter ids; deployments set their own.
    judge_model: str = "anthropic/claude-3.5-sonnet"
    planner_model: str = "openai/gpt-4o-mini"
    synthesis_model: str = "anthropic/claude-3.5-sonnet"
    embedding_model: str = "openai/text-embedding-3-small"
    # Optional fallback model id tried when the primary errors (config; ``None`` = no fallback).
    fallback_model: str | None = None
    timeout_s: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    # Force the deterministic stub (no live call). The factory ALSO stubs when no key is present.
    stub: bool = False
    # Per-model pricing (model id -> rates). Missing model -> cost 0 (measured-or-zero).
    prices: dict[str, ModelPrice] = Field(default_factory=dict)

    def cost_cents(self, model: str, usage: TokenUsage) -> CostCents:
        """Cost of a call to ``model`` with the given usage, from the configured price table.

        Returns ``Decimal(0)`` for a model with no configured price — the gateway reports a real
        measured cost or zero, and never invents one.
        """
        price = self.prices.get(model)
        return price.cost_cents(usage) if price is not None else Decimal(0)


DEFAULT_GATEWAY_CONFIG = GatewayConfig()
