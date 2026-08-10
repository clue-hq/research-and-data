"""LLM-gateway config — the policy-as-data half of the model-egress seam (M0.4, conventions §2/§4).

The gateway *client* lives in :mod:`clue_gateway` (it emits the ``llm.gateway_call`` span,
so it must sit above the ``obs → config → core`` layering); its *configuration* lives here, beside
every other "policy is data" surface, so a model swap — or an OpenRouter → another OpenAI-compatible
gateway swap — is a config change, never code. :class:`GatewayConfig` is folded into the layered
:class:`~clue_config.models.Config`, so it is per-client/per-ICP overridable through one
``get_config`` seam as merge policy, scoring, and budgets.

Pricing is config too: per-model cents-per-1k-token rates the gateway uses to compute a claim/call's
``cost_cents`` from the model-reported token usage. A model with no configured price costs ``0`` —
we report a real measured cost or zero, never a fabricated one.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from clue_config.settings import DEFAULT_SYNTHESIS_MODEL, load_settings
from clue_core.gateway import TokenUsage
from clue_core.primitives import CostCents


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


class ReasoningRequest(BaseModel):
    """What the agent model asks the provider to do with its reasoning, as policy data.

    "Policy is data" applied to the one model parameter that is not a model id: whether a governed
    agent call requests an extended-thinking / reasoning-summary mode, and how deep. It is a
    *request* — every field is optional and a model with no reasoning mode simply ignores the whole
    block — so nothing downstream may assume a trace came back.

    The three members are the OpenAI-Responses reasoning vocabulary, which is what the OpenRouter
    gateway speaks (:class:`~clue_gateway.agent_model.OpenRouterAgentModelProvider` builds
    ``ChatOpenAI(use_responses_api=True)``). ``max_tokens`` is OpenRouter's unified spelling of a
    thinking budget and is passed through untouched for the providers that accept it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    effort: str | None = None
    summary: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)

    def as_provider_payload(self) -> dict[str, object]:
        """The provider ``reasoning`` block, omitting every member that was not asked for."""

        payload: dict[str, object] = {}
        if self.effort is not None:
            payload["effort"] = self.effort
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        return payload


class GatewayConfig(BaseModel):
    """Versioned config for the shared :class:`~clue_core.gateway.LLMGateway`.

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
    synthesis_model: str = DEFAULT_SYNTHESIS_MODEL
    embedding_model: str = "openai/text-embedding-3-small"
    # Optional fallback model id tried when the primary errors (config; ``None`` = no fallback).
    fallback_model: str | None = None
    timeout_s: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    # Force the deterministic stub (no live call). The factory ALSO stubs when no key is present.
    stub: bool = False
    # Per-model pricing (model id -> rates). Missing model -> cost 0 (measured-or-zero).
    # NOTE: like every config sub-tree, the gateway block is overlaid by *whole-subtree replace*
    # (ConfigOverlay semantics) — an overlay that swaps only ``judge_model`` must re-supply
    # ``prices`` too, or the inherited price table is dropped and costs read as 0. Carry the full
    # GatewayConfig (ids + prices) in any overlay that overrides the gateway.
    prices: dict[str, ModelPrice] = Field(default_factory=dict)
    # What a governed *agent* model call asks the provider to do with its reasoning. ``None`` (the
    # default) means "ask for nothing" and is byte-for-byte today's behaviour: the provider builder
    # keeps its own per-model baseline (GPT-5.6's governed ``effort: none``). A value overrides that
    # baseline for every agent model this config builds — which is why it is set from exactly one
    # place, ``default_gateway_config`` below, under the dev-only reasoning-trace setting.
    agent_reasoning: ReasoningRequest | None = None

    def cost_cents(self, model: str, usage: TokenUsage) -> CostCents:
        """Cost of a call to ``model`` with the given usage, from the configured price table.

        Returns ``Decimal(0)`` for a model with no configured price — the gateway reports a real
        measured cost or zero, and never invents one.
        """
        price = self.prices.get(model)
        return price.cost_cents(usage) if price is not None else Decimal(0)


def default_gateway_config() -> GatewayConfig:
    """Return gateway defaults with deploy-time env overrides (``CLUE_SYNTHESIS_MODEL``,
    ``CLUE_JUDGE_MODEL``, …).

    This is also where the FI Lane D dev-lens reasoning request enters the gateway, and the only
    place it can: ``CLUE_CHAT_REASONING_TRACE_MODE=raw`` is refused at settings construction outside
    a dev deployment (``Settings._refuse_dev_lens_in_production``), so a production process cannot
    reach the ``raw`` branch below — it does not start.
    """

    settings = load_settings()
    reasoning = (
        ReasoningRequest(
            # ``effort`` is what makes a reasoning model actually reason; ``summary`` is what makes
            # it *emit* anything about that reasoning. Asking for one without the other is the
            # common way to get a trace-free "reasoning" run, so the dev lens asks for both.
            effort="medium",
            summary="auto",
            max_tokens=settings.chat_reasoning_thinking_budget_tokens,
        )
        if settings.chat_reasoning_trace_mode == "raw"
        else None
    )
    if settings.judge_model:
        return GatewayConfig(
            synthesis_model=settings.synthesis_model,
            judge_model=settings.judge_model,
            agent_reasoning=reasoning,
        )
    return GatewayConfig(synthesis_model=settings.synthesis_model, agent_reasoning=reasoning)


DEFAULT_GATEWAY_CONFIG = default_gateway_config()
