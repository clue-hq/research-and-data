"""Per-model-call token-usage capture (RIDER 2).

The D3 context-growth watch has had no data: run traces carried zero token-usage
events. This is the smallest reliable capture — a LangChain callback handler that
reads `usage_metadata` off each `on_llm_end` result and appends ONE trace event
per model call via `LumenDesignTools.record`. It is attached to the three role
model instances in the harness (`.with_config(callbacks=[...])`), so every
orchestrator / author / reviewer generation logs its input/output/total tokens.

Attribution: LangChain does not pass a stable role identifier into `on_llm_end`,
and all three roles frequently share ONE deduped model instance, so we do NOT try
to attribute an event to a role from inside the callback (that would need brittle
run-tree plumbing the rider explicitly forbids). Events are recorded WITHOUT a
`role`; the `role` key is present only when a handler is constructed for a single
distinct model id (the deduped-to-one-model case), where it is unambiguous.

Robustness: the callback must NEVER break a run. Any failure while reading usage
or recording is swallowed and reported once as a single `model_call_usage_warning`
event, so a broken callback degrades to "no usage data", never to a crashed turn.
"""

from __future__ import annotations

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
                return {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "total_tokens": total,
                }

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
            return {
                "input_tokens": inp,
                "output_tokens": out,
                "total_tokens": total,
            }
    return None


class UsageCaptureHandler(BaseCallbackHandler):
    """Appends one `model_call_usage` trace event per LLM call.

    Args:
        tools: the `LumenDesignTools` whose `record(...)` writes the trace.
        role: an optional role label recorded on each event. Set ONLY when this
            handler backs a single unambiguous model id; left None otherwise so
            we never mis-attribute a shared model instance.
    """

    def __init__(self, tools: Any, role: Optional[str] = None) -> None:
        self._tools = tools
        self._role = role
        self._warned = False

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: D401
        try:
            usage = _extract_usage(response)
            if usage is None:
                return
            payload: dict = dict(usage)
            if self._role is not None:
                payload["role"] = self._role
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
    """Return `model` with a `UsageCaptureHandler` bound as a config callback.

    Falls back to the untouched model if the runnable does not support
    `with_config` (a stub in tests, say) — capture is best-effort and must never
    block agent assembly.
    """
    handler = UsageCaptureHandler(tools, role=role)
    with_config = getattr(model, "with_config", None)
    if not callable(with_config):
        return model
    try:
        return with_config(callbacks=[handler])
    except Exception:  # noqa: BLE001 - never block assembly on a capture wiring failure
        return model
