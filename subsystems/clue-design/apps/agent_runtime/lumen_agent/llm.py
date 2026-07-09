"""LLM gateway for the lumen_agent deepagent (self-contained copy).

OpenRouter is the sole gateway (locked constraint). These functions are COPIES
from the archived pipeline's providers.py — the living deepagent world imports
nothing from the archive (share-by-copy directive, 2026-07-09).
"""

from __future__ import annotations

import json
import logging
from typing import Any

def init_model(
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    reasoning: str | None = None,
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
    if reasoning is not None:
        # OpenAI-compatible clients pass unknown top-level request fields via
        # extra_body; OpenRouter reads `reasoning` from the request body.
        kwargs["extra_body"] = {"reasoning": {"effort": reasoning}}
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
        logging.getLogger(__name__).warning(
            "Could not verify image-input support for model %r via %s/models (%s); "
            "proceeding without the check — an unknown model must not brick a run.",
            model,
            base_url,
            error,
        )
        return

    entry = next((m for m in data if m.get("id") == model_id), None)
    if entry is None:
        logging.getLogger(__name__).warning(
            "Model %r was not found in OpenRouter's model list; skipping the "
            "image-input check (unknown, not text-only).",
            model_id,
        )
        return

    modalities = _openrouter_model_input_modalities(entry)
    if modalities is None:
        # Entry found but carries neither modality shape → UNKNOWN. Do not cache:
        # caching False here would make the model pass on the first call and then
        # brick every later call from the poisoned cache (unknown ≠ text-only).
        logging.getLogger(__name__).warning(
            "Model %r has no recognizable modality metadata in OpenRouter's list; "
            "skipping the image-input check (unknown, not text-only).",
            model_id,
        )
        return
    supports_image = "image" in modalities
    _IMAGE_INPUT_SUPPORT_CACHE[cache_key] = supports_image
    if not supports_image:
        _raise_text_only(model)


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
