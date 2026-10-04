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
from typing import Literal

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
    # The agent models' fallback CHAIN (founder ruling 2026-10-04), tried in order after the
    # primary (and after ``fallback_model``) when a call fails before answering.
    # Env: CLUE_AGENT_FALLBACK_MODELS.
    fallback_models: tuple[str, ...] = ()
    # How long a STREAMED agent model call may wait for its first chunk before the next model in
    # the chain is tried; ``None`` = no first-chunk deadline. Env: CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S.
    first_token_timeout_s: float | None = Field(default=None, gt=0)
    # P3.2 (PD-part3 delta 6) — OpenRouter economics knobs, policy as data. ``provider.sort``
    # pins routing to one replica ordering, which is what makes a stable prompt-cache prefix
    # actually HIT (the design runtime's ~95% cached-prefill invariant); ``usage.include``
    # asks OpenRouter for the usage-accounting block — cached/reasoning token detail *and* the
    # credits the call actually cost.
    #
    # ``usage.include`` defaults ON since the ARV2 R2-close (2026-09-08). It was OFF, so no call
    # site ever asked OpenRouter to meter and the R2 live run booked ``cost_cents = 0`` for all
    # twenty-nine of its Grok rounds. Founder ruling, 2026-09-08: a model's cost comes from
    # OpenRouter and from nowhere else — either this accounting block, or (when a path does not
    # carry it back) OpenRouter's ``/generation`` endpoint. We do not maintain a price table of
    # our own; ``prices`` below survives only for the roles that already populate it.
    openrouter_provider_sort: Literal["price", "throughput", "latency"] | None = None
    openrouter_usage_include: bool = True
    timeout_s: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    # Force the deterministic stub (no live call). The factory ALSO stubs when no key is present.
    stub: bool = False
    # Per-model pricing (model id -> rates). Missing model -> cost 0 (measured-or-zero).
    # PRE-EXISTING MECHANISM, NOT A DEFAULT: nothing in this repo populates it, and per the
    # founder ruling of 2026-09-08 nothing new may — a governed agent call's cost is OpenRouter's
    # number (``usage.cost``, else the ``/generation`` lookup), never one we derive from rates we
    # would have to keep current. A model that happens to be listed here by a deployment still
    # reports its computed cost, labelled ``estimate`` so it can never be mistaken for a meter.
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
    # Route non-OpenAI agent models over chat-completions instead of the Responses endpoint.
    # OpenRouter's ``/responses`` translation for non-OpenAI providers rejects array-shaped
    # message content (grok-4.6 400s ``invalid_union: expected string, received array`` on the
    # platform conversation's tool-result follow-ups — live, 2026-08-27). Default OFF so the
    # design deepagent, whose plain-string turns are proven on the Responses path, keeps its
    # exact wire shape; the platform's ``default_gateway_config`` opts in.
    openrouter_chat_completions_fallback: bool = False

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
    # The agent fallback chain and first-chunk deadline (founder ruling 2026-10-04): production
    # 2026-10-04, grok-4.6 accepted requests and sent nothing, with no fallback configured.
    fallback_models = settings.agent_fallback_models
    first_token_timeout_s = settings.agent_first_token_timeout_s or None
    if settings.judge_model:
        return GatewayConfig(
            synthesis_model=settings.synthesis_model,
            judge_model=settings.judge_model,
            timeout_s=settings.gateway_timeout_s,
            agent_reasoning=reasoning,
            openrouter_chat_completions_fallback=True,
            fallback_models=fallback_models,
            first_token_timeout_s=first_token_timeout_s,
        )
    return GatewayConfig(
        synthesis_model=settings.synthesis_model,
        timeout_s=settings.gateway_timeout_s,
        agent_reasoning=reasoning,
        openrouter_chat_completions_fallback=True,
        fallback_models=fallback_models,
        first_token_timeout_s=first_token_timeout_s,
    )


DEFAULT_GATEWAY_CONFIG = default_gateway_config()
