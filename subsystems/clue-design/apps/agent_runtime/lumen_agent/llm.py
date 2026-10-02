"""LLM gateway for the lumen_agent deepagent — on the PLATFORM gateway since P3.2.

OpenRouter is the sole provider (locked constraint), but as of P3.2 checkpoint 3
(PD-part3 delta 6) every role model is built through the platform's governed
``OpenRouterAgentModelProvider`` instead of a raw ``init_chat_model``:

* the economics knobs (``usage.include`` accounting, ``provider.sort`` replica
  pinning — the ~95% cached-prefill invariant, live-verified 4624/4636 tokens) ride
  ``GatewayConfig`` policy instead of hand-built extra_body;
* every call carries truthful requested/answering-model attribution, cost, and the
  per-role ``clue_role`` label on the ONE authoritative ``model_call_usage`` record;
* reasoning effort maps onto ``ReasoningRequest`` (the same Responses vocabulary the
  platform speaks);
* the pre-spend vision guard reads the provider's capability seam instead of a
  raw-key probe.

``init_model`` keeps its historical name and signature (plus ``role``) because it is
the seam both harnesses build through and the per-role tests monkeypatch.
"""

from __future__ import annotations

import json
from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.llm")

# One governed provider per distinct gateway policy — shared across the three role
# builds so the capability catalog is fetched once per process.
_PROVIDER_CACHE: dict[tuple, Any] = {}

# The design trio's max-output default when LUMEN_AGENT_MAX_TOKENS is unset. The
# governed build REQUIRES a bound (unbounded generation is ungoverned); this is
# damage limitation, generously above any observed author/reviewer output.
_DEFAULT_MAX_OUTPUT_TOKENS = 32_768

# The governed build requires a positive timeout; this is the ceiling when
# LUMEN_AGENT_LLM_TIMEOUT_S is unset (the config default is 60s, so this only
# applies when a deployment explicitly clears it).
_DEFAULT_TIMEOUT_S = 120.0


def _governed_provider(
    *,
    base_url: str,
    api_key: str,
    reasoning: str | None,
    provider_sort: str | None,
    timeout_s: float,
    fallback_model: str | None = None,
    chat_completions: bool = False,
):
    """The cached governed provider for one gateway policy fingerprint."""
    key = (
        base_url, api_key, reasoning, provider_sort, timeout_s, fallback_model, chat_completions
    )
    if key not in _PROVIDER_CACHE:
        from pydantic import SecretStr

        from clue_config.gateway import GatewayConfig, ReasoningRequest
        from clue_gateway.agent_model import OpenRouterAgentModelProvider

        config = GatewayConfig(
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=2,
            fallback_model=fallback_model,
            openrouter_provider_sort=provider_sort,  # type: ignore[arg-type]
            openrouter_usage_include=True,
            # 2026-09-04: non-OpenAI ids over chat-completions (the platform lane's
            # ruling); /responses' bridge dropped a 136s grok generation mid-stream.
            openrouter_chat_completions_fallback=chat_completions,
            agent_reasoning=(
                ReasoningRequest(effort=reasoning) if reasoning is not None else None
            ),
        )
        _PROVIDER_CACHE[key] = OpenRouterAgentModelProvider(config, SecretStr(api_key))
    return _PROVIDER_CACHE[key]

def init_model(
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    reasoning: str | None = None,
    max_tokens: int | None = None,
    provider_sort: str | None = None,
    timeout_s: float | None = None,
    role: str | None = None,
    fallback_model: str | None = None,
    chat_completions: bool = False,
):
    """Build a deep-agent LLM bound to the OpenRouter gateway.

    OpenRouter is the SOLE provider for every LLM call. Callers supply the
    OpenRouter `base_url` + `api_key` and a bare OpenRouter `model` id (the
    historical "openai:" prefix is tolerated and stripped). Since P3.2 the build
    goes through the platform's governed provider — see the module docstring.

    `reasoning` ("low" | "medium" | "high") rides OpenRouter's unified
    `reasoning: {effort}` request field — the gateway translates it for whatever
    provider serves the model, so it is one mechanism for every model id, never a
    per-vendor special case. None → no reasoning field on the request (provider
    default: no extended thinking).

    `max_tokens` (D10a) is the output-token bound. None → the governed default
    (_DEFAULT_MAX_OUTPUT_TOKENS): since P3.2 output is ALWAYS bounded — the
    governed build refuses unbounded generation.

    `provider_sort` (L1, cache locality) is the OpenRouter provider `sort`
    preference. When set it rides `extra_body["provider"] = {"sort": <value>}` and
    MERGES alongside the usage/reasoning fields (never clobbering them). `sort`
    disables OpenRouter's load-balancing and pins one provider replica, keeping the
    append-only ReAct prefix cache-warm (probe-proven 2/8 → 8/8 cache hits). None →
    no `provider` field on the request (byte-identical to pre-L1).

    `timeout_s` (L3, straggler watchdog) is the per-request timeout in seconds
    with max_retries=2; None → _DEFAULT_TIMEOUT_S (always bounded since P3.2).

    `fallback_model` (P3.2) is an OPTIONAL second OpenRouter id tried when the
    primary errors (e.g. an upstream 5xx mid-turn) — rides
    GatewayConfig.fallback_model with truthful answering-model attribution.
    Must be vision-capable; None → no fallback, a hard upstream failure fails
    the turn honestly.
    """
    if not (base_url and api_key):
        raise ValueError(
            "The deep-agent routes every LLM call through OpenRouter — set both "
            "LUMEN_AGENT_BASE_URL and LUMEN_AGENT_API_KEY. There is no native "
            "provider fallback."
        )
    if reasoning is not None and reasoning not in {"low", "medium", "high"}:
        raise ValueError(
            "LUMEN_AGENT_REASONING must be one of low|medium|high (or unset for "
            f"no reasoning field); got {reasoning!r}"
        )
    # The historical contract required an "openai:" prefix so init_chat_model chose
    # the OpenAI-compatible client. The governed provider IS that client; the prefix
    # is accepted for env back-compat and stripped to the bare OpenRouter id.
    model_id = model[len("openai:") :] if model.startswith("openai:") else model
    if ":" in model_id.split("/", 1)[0]:
        raise ValueError(
            f"LUMEN_AGENT_MODEL={model!r} carries a non-'openai:' client prefix; the "
            "governed gateway takes a bare OpenRouter id (an optional 'openai:' "
            "prefix is tolerated for back-compat)."
        )
    effective_timeout = timeout_s if timeout_s is not None else _DEFAULT_TIMEOUT_S
    provider = _governed_provider(
        base_url=base_url,
        api_key=api_key,
        reasoning=reasoning,
        provider_sort=provider_sort,
        timeout_s=effective_timeout,
        fallback_model=fallback_model,
        chat_completions=chat_completions,
    )
    # P3.2 rulings, restated where they bind: max output is BOUNDED by default (the
    # governed build refuses unbounded generation); temperature=1.0 approximates the
    # historical "unset" (the OpenAI default); max_retries=2 keeps the L3 watchdog's
    # retry posture. The provider owns extra_body (usage accounting + provider.sort
    # replica pinning) and the per-model reasoning block from GatewayConfig.
    return provider.build(
        model_id=model_id,
        timeout_s=effective_timeout,
        max_retries=2,
        max_output_tokens=max_tokens if max_tokens is not None else _DEFAULT_MAX_OUTPUT_TOKENS,
        temperature=1.0,
        role=role,
    )


def assert_model_supports_image_input(
    model: str, *, base_url: str, api_key: str
) -> None:
    """Slice 2 D4, on the capability seam since P3.2: fail LOUDLY, BEFORE a run
    starts, if a configured model is text-only. The loop is structurally
    mandatory-multimodal (the Director and visual reviewer attach images every
    turn); a text-only model instead authors, then dies mid-turn at the reviewer —
    burning the paid authoring call. This guard moves that failure to startup.

    Semantics preserved verbatim from the raw-key probe it replaces: only a
    POSITIVE "text-only" finding (False) raises; unknown — model unlisted, missing
    modality metadata, unreachable catalog (None) — logs a warning and returns
    (unknown ≠ text-only, and the guard must never brick a run). The catalog is
    fetched once per provider instance, shared with the role-model builds.
    """
    model_id = model[len("openai:") :] if model.startswith("openai:") else model
    provider = _governed_provider(
        base_url=base_url,
        api_key=api_key,
        reasoning=None,
        provider_sort=None,
        timeout_s=_DEFAULT_TIMEOUT_S,
    )
    supported = provider.supports_image_input(model_id)
    if supported is False:
        _raise_text_only(model)
    if supported is None:
        logger.warning(
            "image_input_check_skipped_capability_unknown",
            model=model_id,
            base_url=base_url,
        )


def assert_all_role_models_support_image_input(config: Any) -> None:
    """D10(c) companion: run the text-only guard over EVERY distinct configured
    role model (orchestrator / author / reviewer), not just LUMEN_AGENT_MODEL.

    Per-role model overrides mean a text-only id can hide on any one role and
    brick that mind mid-turn (all three attach images via `view`). Calling this
    from `create_design_deepagent` covers every entry path — CLI and API — with
    no per-callsite change, because both build the agent through the harness.
    The loud "text-only" raise is unchanged, and unknown findings still never
    brick a run.
    """
    for role_model in {
        config.orchestrator_model,
        config.author_model,
        config.reviewer_model,
    }:
        assert_model_supports_image_input(
            role_model,
            base_url=config.agent_base_url,
            api_key=config.agent_api_key,
        )


def _raise_text_only(model: str) -> None:
    raise ValueError(
        f"LUMEN_AGENT_MODEL={model!r} is a TEXT-ONLY model, but the Lumen deep-agent "
        "loop is mandatory-multimodal: the Director and the visual reviewer attach "
        "images on every turn. Configured as-is, the run would author and then die "
        "mid-turn at the reviewer with `404 No endpoints found that support image "
        "input`, wasting the paid authoring call. Set LUMEN_AGENT_MODEL to a model "
        "whose OpenRouter input modalities include `image` (e.g. a vision-capable "
        "Claude/GPT/Gemini id)."
    )


def try_structured_model(model: Any, schema: type[VisualCritique]):
    try:
        return model.with_structured_output(schema)
    except Exception:
        return model


def response_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)
