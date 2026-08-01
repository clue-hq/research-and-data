"""Per-model-call token-usage capture (RIDER 2).

The D3 context-growth watch has had no data: run traces carried zero token-usage
events. This is the smallest reliable capture — a LangChain callback handler that
reads `usage_metadata` off each `on_llm_end` result and appends ONE trace event
per model call via `LumenDesignTools.record`. It is attached to the three role
model instances in the harness by appending the handler to each model's own
declared `callbacks` field (NOT via `.with_config`, which returns a
`RunnableBinding` that deepagents' `resolve_model` mishandles — see
`attach_usage_capture`), so every orchestrator / author / reviewer generation
logs its input/output/total tokens.

Attribution: LangChain does not pass a stable role identifier into `on_llm_end`.
Because instance-level callbacks fire only on THAT instance, per-role attribution
is achieved by building ONE model instance per role (the harness makes three,
even when the ids are identical) and tagging each with its role. A handler
carries `role` when it backs a single role instance; the value is recorded on
every event so the role IS cleanly attributable at the point of attachment.

Robustness: the callback must NEVER break a run. Any failure while reading usage
or recording is swallowed and reported once as a single `model_call_usage_warning`
event, so a broken callback degrades to "no usage data", never to a crashed turn.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler


def _extract_usage(response: Any) -> Optional[dict]:
    """Pull an `{input_tokens, output_tokens, total_tokens}` dict from an
    `LLMResult`, tolerating the shapes LangChain emits.

    Preference order:
      1. `usage_metadata` on the generation's message (the modern, provider-
         normalized field — present for OpenAI-compatible chat models, which is
         what our OpenRouter gateway builds).
      2. `llm_output["token_usage"]` / `["usage"]` (older aggregate shape).

    L0 (latency trace enrichment): when the provider reports them, the dict also
    carries `cached_input_tokens` (cached-prefill prompt tokens) and
    `reasoning_output_tokens` (extended-thinking output tokens). These are ADDED
    only when present — absent ⇒ the key is omitted, never a fabricated zero, so
    the `model_call_usage` payload keeps its "omit rather than null" shape.

    Returns None when no usage is present (a run must not fabricate zeros)."""
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, dict) and usage:
                inp = usage.get("input_tokens")
                out = usage.get("output_tokens")
                total = usage.get("total_tokens")
                if total is None and (inp is not None or out is not None):
                    total = (inp or 0) + (out or 0)
                result = {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "total_tokens": total,
                }
                # LangChain's provider-normalized detail sub-dicts (present for
                # OpenAI-compatible clients when the provider caches / reasons).
                input_details = usage.get("input_token_details")
                if isinstance(input_details, dict):
                    cached = input_details.get("cache_read")
                    if cached is not None:
                        result["cached_input_tokens"] = cached
                output_details = usage.get("output_token_details")
                if isinstance(output_details, dict):
                    reasoning = output_details.get("reasoning")
                    if reasoning is not None:
                        result["reasoning_output_tokens"] = reasoning
                return result

    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        token_usage = llm_output.get("token_usage") or llm_output.get("usage")
        if isinstance(token_usage, dict) and token_usage:
            inp = token_usage.get("prompt_tokens") or token_usage.get("input_tokens")
            out = token_usage.get("completion_tokens") or token_usage.get(
                "output_tokens"
            )
            total = token_usage.get("total_tokens")
            if total is None and (inp is not None or out is not None):
                total = (inp or 0) + (out or 0)
            result = {
                "input_tokens": inp,
                "output_tokens": out,
                "total_tokens": total,
            }
            # OpenRouter/OpenAI raw usage nests the cache + reasoning breakdowns
            # under `*_tokens_details` (the pre-normalization shape).
            prompt_details = token_usage.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                cached = prompt_details.get("cached_tokens")
                if cached is not None:
                    result["cached_input_tokens"] = cached
            completion_details = token_usage.get("completion_tokens_details")
            if isinstance(completion_details, dict):
                reasoning = completion_details.get("reasoning_tokens")
                if reasoning is not None:
                    result["reasoning_output_tokens"] = reasoning
            return result
    return None


def _model_id_from_start(serialized: Any, metadata: Any) -> Optional[str]:
    """Best-effort model id from the on_*_start callback args (LangChain stamps
    the resolved id onto `metadata['ls_model_name']` and the serialized kwargs).
    Used as the fallback when the completion's `llm_output` omits the slug."""
    if isinstance(metadata, dict):
        for key in ("ls_model_name", "model", "model_name"):
            val = metadata.get(key)
            if isinstance(val, str) and val:
                return val
    if isinstance(serialized, dict):
        kwargs = serialized.get("kwargs")
        if isinstance(kwargs, dict):
            for key in ("model", "model_name", "model_id"):
                val = kwargs.get(key)
                if isinstance(val, str) and val:
                    return val
    return None


def _response_model_id(response: Any) -> Optional[str]:
    """The model slug actually served for the call, read off the completion's
    `llm_output` (OpenAI-compatible clients echo the provider's `model` here —
    for OpenRouter this is the concrete routed slug). None when absent."""
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        for key in ("model_name", "model"):
            val = llm_output.get(key)
            if isinstance(val, str) and val:
                return val
    return None


class UsageCaptureHandler(BaseCallbackHandler):
    """Appends one `model_call_usage` trace event per LLM call.

    Args:
        tools: the `LumenDesignTools` whose `record(...)` writes the trace.
        role: an optional role label recorded on each event. Set per role since
            each role now backs its OWN model instance (harness builds three), so
            the label is unambiguous; left None only when no role is supplied.
    """

    def __init__(self, tools: Any, role: Optional[str] = None) -> None:
        self._tools = tools
        self._role = role
        self._warned = False
        # L0: per-call start bookkeeping, keyed by LangChain's run_id, so the
        # duration is the wall-clock of THAT invoke (start→end) and the model id
        # captured at start backstops a completion that omits the slug.
        self._started: dict[Any, float] = {}
        self._model_at_start: dict[Any, str] = {}

    # -- start callbacks: stamp the wall-clock + resolved model id ------------ #
    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: Any = None, **kwargs: Any
    ) -> None:
        self._mark_start(serialized, run_id, kwargs.get("metadata"))

    def on_llm_start(
        self, serialized: Any, prompts: Any, *, run_id: Any = None, **kwargs: Any
    ) -> None:
        # Text-completion path; chat models fire on_chat_model_start instead.
        self._mark_start(serialized, run_id, kwargs.get("metadata"))

    def _mark_start(self, serialized: Any, run_id: Any, metadata: Any) -> None:
        # Start bookkeeping must never break a run; a failure here only means the
        # event omits duration_ms/model_id, never a crashed turn.
        try:
            self._started[run_id] = time.monotonic()
            model_id = _model_id_from_start(serialized, metadata)
            if model_id:
                self._model_at_start[run_id] = model_id
        except Exception:  # noqa: BLE001 - degrade to no timing, never raise
            pass

    def on_llm_end(self, response: Any, *, run_id: Any = None, **kwargs: Any) -> None:  # noqa: D401
        try:
            started = self._started.pop(run_id, None)
            model_at_start = self._model_at_start.pop(run_id, None)
            usage = _extract_usage(response)
            if usage is None:
                return
            payload: dict = dict(usage)
            if self._role is not None:
                payload["role"] = self._role
            # L0 enrichment (all additive; absent ⇒ omitted, matching the
            # payload's "omit rather than null" convention).
            if started is not None:
                payload["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            model_id = _response_model_id(response) or model_at_start
            if model_id:
                payload["model_id"] = model_id
            self._tools.record(
                "model",
                "model_call_usage",
                output_summary=(
                    f"in={usage.get('input_tokens')} "
                    f"out={usage.get('output_tokens')} "
                    f"total={usage.get('total_tokens')}"
                ),
                payload=payload,
            )
        except Exception as error:  # noqa: BLE001 - callbacks must never break a run
            self._warn_once(error)

    def _warn_once(self, error: Exception) -> None:
        if self._warned:
            return
        self._warned = True
        try:
            self._tools.record(
                "model",
                "model_call_usage_warning",
                output_summary=f"usage capture disabled: {type(error).__name__}: {error}"[
                    :500
                ],
            )
        except Exception:  # noqa: BLE001 - even the warning must not raise
            pass


def attach_usage_capture(model: Any, tools: Any, role: Optional[str] = None) -> Any:
    """Attach a `UsageCaptureHandler` to `model` IN PLACE and return the SAME object.

    We append the handler to the model's own declared `callbacks` field rather
    than wrapping it via `.with_config(...)`. `.with_config` produces a
    `RunnableBinding`, which is NOT a `BaseChatModel`; deepagents' `resolve_model`
    only passes `isinstance(model, BaseChatModel)` objects through untouched and
    routes everything else down a string-spec path that calls `spec.count(":")` —
    on a `RunnableBinding` that dies with `AttributeError('ChatOpenAI' object has
    no attribute 'count')`, killing construction of every turn
    (probe-r9: CONSTRUCTION-FAILURE-traceback.txt). Returning the same
    `BaseChatModel` keeps the type deepagents demands.

    `callbacks` is a declared pydantic field on `BaseLanguageModel`
    (`langchain_core/language_models/base.py`: `callbacks: Callbacks =
    Field(default=None, exclude=True)`), and `BaseChatModel.generate` passes it as
    `local_callbacks` into `CallbackManager.configure(callbacks, self.callbacks,
    ...)`, so an instance-level handler fires on every invoke of THAT instance
    (verified live in langchain_core 1.4.8). Because the handler lives on the
    instance — not on a shared config — per-role attribution requires one instance
    per role (the harness builds three; see harness.py).

    Robustness (never breaks a run): if the model has no writable `callbacks`
    field (a stub/sentinel in tests, or a frozen model), we return it untouched
    after a single warning path. We APPEND to any existing list — never replace —
    so callbacks wired elsewhere survive.
    """
    handler = UsageCaptureHandler(tools, role=role)
    if not hasattr(model, "callbacks"):
        # Not a BaseChatModel (e.g. a test sentinel) — leave it untouched so
        # assembly and any identity-based dedupe are undisturbed. No warning:
        # this is an expected, benign shape, not a wiring failure.
        return model
    try:
        existing = model.callbacks
        if existing is None:
            model.callbacks = [handler]
        elif isinstance(existing, list):
            existing.append(handler)
        else:
            # `Callbacks` may also be a BaseCallbackManager; wrapping that in a
            # list here would drop its handlers. Add ours through its own API.
            add_handler = getattr(existing, "add_handler", None)
            if callable(add_handler):
                add_handler(handler)
            else:
                model.callbacks = [existing, handler]
    except Exception as error:  # noqa: BLE001 - never block assembly on wiring
        # Readonly/frozen field or an unexpected shape: degrade to no capture,
        # warn once through the tools trace, and hand back the untouched model.
        try:
            tools.record(
                "model",
                "model_call_usage_warning",
                output_summary=(
                    f"usage capture not wired ({role or 'unattributed'}): "
                    f"{type(error).__name__}: {error}"
                )[:500],
            )
        except Exception:  # noqa: BLE001 - even the warning must not raise
            pass
    return model
