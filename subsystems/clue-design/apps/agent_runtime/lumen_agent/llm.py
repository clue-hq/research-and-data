"""LLM gateway for the lumen_agent deepagent (self-contained copy).

OpenRouter is the sole gateway (locked constraint). These functions are COPIES
from the archived pipeline's providers.py — the living deepagent world imports
nothing from the archive (share-by-copy directive, 2026-07-09).
"""

from __future__ import annotations

import json
from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.llm")

def init_model(
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    reasoning: str | None = None,
    max_tokens: int | None = None,
    provider_sort: str | None = None,
    timeout_s: float | None = None,
):
    """Build a deep-agent LLM bound to the OpenRouter gateway.

    OpenRouter is the SOLE gateway for every LLM call — there is no native-provider
    fallback. Callers must supply the OpenRouter `base_url` + `api_key`, and `model`
    must be an "openai:<openrouter-model-id>" string so LangChain selects the
    OpenAI-compatible client. Any other shape is a misconfiguration and raises here,
    before a request goes out, rather than failing later as an opaque transport
    error (e.g. an Anthropic client aimed at the OpenRouter base URL that 404s).

    `reasoning` ("low" | "medium" | "high") rides OpenRouter's unified
    `reasoning: {effort}` request field — the gateway translates it for whatever
    provider serves the model, so it is one mechanism for every model id, never a
    per-vendor special case. None → no reasoning field on the request (provider
    default: no extended thinking).

    `max_tokens` (D10a) is the OPTIONAL output-token bound. When set it is passed
    straight to `init_chat_model`, which lands it on `ChatOpenAI.max_tokens`
    (serialized as `max_completion_tokens` in the request) — one bound for every
    model routed through this gateway, damage-limiting runaway generation. None →
    no `max_tokens` kwarg on the model (today's behavior, byte-identical).

    `provider_sort` (L1, cache locality) is the OpenRouter provider `sort`
    preference. When set it rides `extra_body["provider"] = {"sort": <value>}` and
    MERGES alongside the usage/reasoning fields (never clobbering them). `sort`
    disables OpenRouter's load-balancing and pins one provider replica, keeping the
    append-only ReAct prefix cache-warm (probe-proven 2/8 → 8/8 cache hits). None →
    no `provider` field on the request (byte-identical to pre-L1).

    `timeout_s` (L3, straggler watchdog) is the OPTIONAL per-request timeout in
    seconds. When set it installs BOTH `timeout` (ChatOpenAI.request_timeout, passed
    to the OpenAI SDK client) and `max_retries=2` (explicit = SDK default) — the SDK
    retries a timed-out request with exponential backoff, then propagates
    openai.APITimeoutError. It kills the 60–97s stragglers without touching genuine
    calls. None → neither kwarg (today's behavior, byte-identical).
    """
    if not (base_url and api_key):
        raise ValueError(
            "The deep-agent routes every LLM call through OpenRouter — set both "
            "LUMEN_AGENT_BASE_URL and LUMEN_AGENT_API_KEY. There is no native "
            "provider fallback."
        )
    if not model.startswith("openai:"):
        raise ValueError(
            "LUMEN_AGENT_MODEL must be an 'openai:<openrouter-model-id>' value so "
            f"LangChain selects the OpenAI-compatible client. Got {model!r}. Prefix "
            "it with 'openai:' — e.g. 'openai:anthropic/claude-opus-4.8'. A bare "
            "'anthropic:' prefix builds the Anthropic client against the OpenRouter "
            "base URL and 404s."
        )
    if reasoning is not None and reasoning not in {"low", "medium", "high"}:
        raise ValueError(
            "LUMEN_AGENT_REASONING must be one of low|medium|high (or unset for "
            f"no reasoning field); got {reasoning!r}"
        )
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as error:
        raise RuntimeError(
            "LangChain model dependencies are missing. Install apps/api/requirements.txt "
            "or add langchain and langchain-openai to the active environment."
        ) from error
    kwargs: dict = {"base_url": base_url, "api_key": api_key}
    # L0 (latency trace enrichment): ask OpenRouter to include full usage
    # accounting in the response so the cached-prefill breakdown
    # (`prompt_tokens_details.cached_tokens` → usage_metadata.input_token_details.
    # cache_read) is reported when the provider caches. This is measurement-only:
    # it changes ONLY the returned usage object, never generation. OpenAI-
    # compatible clients pass unknown top-level request fields via extra_body;
    # OpenRouter reads `usage` from the request body.
    extra_body: dict = {"usage": {"include": True}}
    if reasoning is not None:
        # OpenRouter reads the unified `reasoning` field from the request body.
        extra_body["reasoning"] = {"effort": reasoning}
    if provider_sort is not None:
        # L1 (cache locality): OpenRouter reads `provider` prefs from the request
        # body. This MERGES into extra_body alongside usage/reasoning — never
        # clobbers them. `sort` alone pins one replica (we deliberately do NOT set
        # allow_fallbacks:false: sort already disables load-balancing, and keeping
        # fallbacks means a dead replica degrades to a cache miss, not a failed turn).
        extra_body["provider"] = {"sort": provider_sort}
    kwargs["extra_body"] = extra_body
    if max_tokens is not None:
        # ChatOpenAI.max_tokens (langchain-openai 1.3.3) is the max-output-tokens
        # field; it serializes to the request as `max_completion_tokens`.
        kwargs["max_tokens"] = max_tokens
    if timeout_s is not None:
        # L3 (straggler watchdog): ChatOpenAI.request_timeout (alias `timeout`) and
        # max_retries pass straight into the OpenAI SDK client. The SDK retries a
        # timed-out request (exponential backoff) then raises openai.APITimeoutError.
        # Both are installed together so "timeout unset" stays byte-identical to
        # today; max_retries is fixed at 2 (explicit = the SDK default).
        kwargs["timeout"] = timeout_s
        kwargs["max_retries"] = 2
    return init_chat_model(model, **kwargs)


# Slice 2 D4: cache of the multimodal-capability probe, keyed by (base_url, model id).
# Both outcomes are cached (passed / raised) so repeat turns in one process never
# re-hit the network — the model is fixed for the life of a run.
_IMAGE_INPUT_SUPPORT_CACHE: dict[tuple[str, str], bool] = {}


def _openrouter_model_input_modalities(model_entry: dict) -> list[str] | None:
    """Extract a model's input modalities from an OpenRouter `/models` entry,
    handling BOTH observed shapes: `architecture.input_modalities` (a list) and
    `architecture.modality` (a string like `text+image->text` or `text->text`).
    Returns None when neither is present (the caller treats that as unknown)."""
    architecture = model_entry.get("architecture") or {}
    modalities = architecture.get("input_modalities")
    if isinstance(modalities, list):
        return [str(m).lower() for m in modalities]
    modality = architecture.get("modality")
    if isinstance(modality, str) and modality:
        # `text+image+file->text` — the INPUT side is everything before `->`.
        input_side = modality.split("->", 1)[0]
        return [part.strip().lower() for part in input_side.split("+") if part.strip()]
    return None


def assert_model_supports_image_input(
    model: str, *, base_url: str, api_key: str
) -> None:
    """Slice 2 D4: fail LOUDLY, BEFORE a run starts, if LUMEN_AGENT_MODEL is a
    text-only model. The loop is structurally mandatory-multimodal (the Director and
    visual reviewer attach images every turn); a text-only model instead authors,
    then dies mid-turn at the reviewer with `404 No endpoints found that support
    image input` — burning the paid authoring call. This probe moves that failure to
    startup.

    Only a POSITIVE "text-only" finding raises. A model missing from the list, a
    non-OpenRouter gateway, or any network error must NEVER brick a run — those log a
    warning and return (unknown ≠ text-only)."""
    model_id = model[len("openai:") :] if model.startswith("openai:") else model
    cache_key = (base_url, model_id)
    if cache_key in _IMAGE_INPUT_SUPPORT_CACHE:
        if not _IMAGE_INPUT_SUPPORT_CACHE[cache_key]:
            _raise_text_only(model)
        return

    import httpx

    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json().get("data") or []
    except Exception as error:  # network down, non-OpenRouter gateway, bad JSON.
        logger.warning(
            "image_input_check_skipped_probe_failed",
            model=model,
            base_url=base_url,
            error=str(error),
        )
        return

    entry = next((m for m in data if m.get("id") == model_id), None)
    if entry is None:
        logger.warning(
            "image_input_check_skipped_model_not_found",
            model=model_id,
        )
        return

    modalities = _openrouter_model_input_modalities(entry)
    if modalities is None:
        # Entry found but carries neither modality shape → UNKNOWN. Do not cache:
        # caching False here would make the model pass on the first call and then
        # brick every later call from the poisoned cache (unknown ≠ text-only).
        logger.warning(
            "image_input_check_skipped_no_modality_metadata",
            model=model_id,
        )
        return
    supports_image = "image" in modalities
    _IMAGE_INPUT_SUPPORT_CACHE[cache_key] = supports_image
    if not supports_image:
        _raise_text_only(model)


def assert_all_role_models_support_image_input(config: Any) -> None:
    """D10(c) companion: run the text-only guard over EVERY distinct configured
    role model (orchestrator / author / reviewer), not just LUMEN_AGENT_MODEL.

    Per-role model overrides mean a text-only id can hide on any one role and
    brick that mind mid-turn (all three attach images via `view`). Calling this
    from `create_design_deepagent` covers every entry path — CLI and API — with
    no per-callsite change, because both build the agent through the harness.

    Each distinct id is checked once (the per-model probe also caches by
    (base_url, id)); the loud "text-only" raise is unchanged, and unknown /
    network-error findings still never brick a run.
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
