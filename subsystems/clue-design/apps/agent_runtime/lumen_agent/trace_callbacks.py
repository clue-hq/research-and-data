"""Structured message tracing via a LangChain callback (L3 of the tracing plan).

A per-role ``TraceCallbackHandler`` is attached to each of the three role model
instances in the harness by appending it to that model's own instance-level
``.callbacks`` field (see ``attach_trace_callback`` for the full rationale on why
instance-level attachment is required for per-role attribution and why
``.with_config`` is forbidden). Every
event this handler emits carries the ``role`` it was constructed with, so the
``python -m lumen_agent.trace`` viewer can colour and filter the timeline by
role without any cross-attribution.

Events go through the shared ``py_lumen_obs`` logger (``lumen_agent.trace``), so
they land on the console (mode-aware) AND in the per-run ``logs/run.jsonl``
(always full detail — the substrate the viewer renders). This module NEVER
configures logging; it only acquires a logger via ``obs.get_logger``.

Robustness: a callback must NEVER break a run. Every handler
method body is wrapped; the first failure is reported once as a single
``trace_callback_warning`` event and thereafter the handler degrades silently to
"no trace", never to a crashed turn.

────────────────────────────────────────────────────────────────────────────
EVENT SCHEMA (the contract read by the viewer and any future consumer)
────────────────────────────────────────────────────────────────────────────
Every event also carries the ambient contextvars bound by the run (``run_id``,
``turn``, ``round`` when set) plus ``level``/``timestamp``/``logger`` from the
shared chain. The fields listed below are the ones THIS handler adds.

llm_call_started
    role            : str    — orchestrator | author | reviewer
    model           : str    — resolved model id (best-effort; "unknown" if not
                               discoverable from serialized/metadata)
    message_count   : int    — number of messages in the prompt
    messages        : list   — (DEBUG mode only) the full prompt as
                               [{role, content, ...}]; EVERY image / base64
                               content block is replaced by an
                               "<image WxH?, ~NKB>" placeholder BEFORE logging.
                               The shared redaction chain exempts content keys,
                               so placeholdering here is mandatory, not optional.

llm_call_completed
    role            : str
    model           : str
    completion      : str    — the assistant's text output (full)
    tool_calls      : list   — [{name, args}] issued by the model this turn
    input_tokens    : int|None
    output_tokens   : int|None
    total_tokens    : int|None
    duration_ms     : int    — wall time from the matching started event
    finish_reason   : str|None

llm_call_failed
    role            : str
    model           : str
    error           : str    — "<ExceptionType>: <message>"
    duration_ms     : int

tool_started
    role            : str    — the role whose handler observed the tool
    name            : str    — tool name
    args            : Any     — tool input (dict when structured, else the raw
                               input string)

tool_completed
    role            : str
    name            : str
    result          : str    — stringified tool output
    duration_ms     : int

tool_failed
    role            : str
    name            : str
    error           : str
    duration_ms     : int

subagent_started            (emitted instead of tool_started for the `task` tool)
    role            : str    — the delegating role
    subagent        : str    — the delegated subagent name (from the task args)

subagent_completed
    role            : str
    subagent        : str
    duration_ms     : int

trace_callback_warning      (emitted at most once per handler)
    role            : str
    error           : str    — why tracing degraded

────────────────────────────────────────────────────────────────────────────
Run-summary accumulation (fast-loop v1 §7). An optional ``RunMetrics`` object
(``run_metrics.py``) may be handed to the handler at attach time. When present,
``on_llm_end``/``on_llm_error`` also fold the call into that run's per-role
counters — the same numbers, aggregated, so nobody has to hand-total 6000 log
lines again. It is pure in-process integer arithmetic inside the ALREADY-wrapped
handler body: no new event, no I/O, and a metrics failure degrades to the same
warn-once "no trace" path as any other callback failure. ``metrics=None`` (the
default) leaves every emitted event byte-identical to before.

────────────────────────────────────────────────────────────────────────────
Subagent boundaries. These handlers are attached to the MODEL instances only,
so in practice LangChain delivers `on_llm_*` events
to them but generally NOT sibling `on_tool_*`/`on_chain_*` events (those fire on
the graph's config-level callbacks, not a model instance). Therefore the primary
way the viewer derives subagent boundaries is the ``role`` field alone: the
orchestrator is the parent; every ``author``/``reviewer`` llm event is work done
inside a delegated subagent. The explicit ``subagent_started`` /
``subagent_completed`` events are still wired for the case where task-delegation
tool/chain events DO reach a handler (a future config-level attachment, or a
propagation path that surfaces them) — when a `task`-tool event arrives we emit
the subagent-boundary pair with the delegated name derived from the tool args
rather than a generic ``tool_*`` event.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler

from py_lumen_obs import get_logger

# The name of deepagents' subagent-delegation tool. When a tool/chain event for
# this tool reaches a handler we translate it into subagent-boundary events.
_TASK_TOOL_NAMES = frozenset({"task"})

_log = get_logger("lumen_agent.trace")


# --------------------------------------------------------------------------- #
# Usage extraction (moved here from the retired `usage_capture` module)
# --------------------------------------------------------------------------- #
def extract_usage(response: Any) -> Optional[dict]:
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

    Lane 3 slice 5: the same cached-prefill count is ALSO published under the
    ledger's own name, `cache_read_input_tokens`, so `usage_collector` can copy
    it onto a receipt without knowing this module's historical key. Both names
    describe the one number the provider reported; neither is computed here.

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
                        result["cache_read_input_tokens"] = cached
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
                    result["cache_read_input_tokens"] = cached
            completion_details = token_usage.get("completion_tokens_details")
            if isinstance(completion_details, dict):
                reasoning = completion_details.get("reasoning_tokens")
                if reasoning is not None:
                    result["reasoning_output_tokens"] = reasoning
            return result
    return None


# --------------------------------------------------------------------------- #
# Image / base64 placeholdering (mandatory: the redaction chain exempts content)
# --------------------------------------------------------------------------- #
def _b64_bytes(payload: str) -> Optional[bytes]:
    import base64

    try:
        return base64.b64decode(payload, validate=False)
    except Exception:
        return None


def _sniff_dims(raw: bytes) -> Optional[tuple[int, int]]:
    """Best-effort width×height from the header of PNG/GIF/JPEG bytes. Returns
    None when it cannot be read cheaply (never decodes the whole image)."""
    try:
        if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
            import struct

            w, h = struct.unpack(">II", raw[16:24])
            return int(w), int(h)
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            import struct

            w, h = struct.unpack("<HH", raw[6:10])
            return int(w), int(h)
        if raw[:2] == b"\xff\xd8":  # JPEG: scan for a SOF marker
            i, n = 2, len(raw)
            while i + 9 < n:
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h = (raw[i + 5] << 8) | raw[i + 6]
                    w = (raw[i + 7] << 8) | raw[i + 8]
                    return int(w), int(h)
                seg = (raw[i + 2] << 8) | raw[i + 3]
                if seg <= 0:
                    break
                i += 2 + seg
    except Exception:
        return None
    return None


def _image_placeholder(raw: Optional[bytes], n_bytes: int, kind: Optional[str]) -> str:
    dims = _sniff_dims(raw) if raw else None
    kb = round(n_bytes / 1024) if n_bytes >= 1024 else max(n_bytes, 0) / 1024
    size = f"~{round(n_bytes / 1024)}KB" if n_bytes >= 1024 else f"~{n_bytes}B"
    head = "image"
    if kind:
        head = f"image {kind}"
    if dims:
        return f"<{head} {dims[0]}x{dims[1]}, {size}>"
    return f"<{head} {size}>"


def _blob_from_url(url: str) -> Optional[tuple[Optional[bytes], int, Optional[str]]]:
    """(raw_bytes, byte_len, kind) for a data: URI or a bare base64 string."""
    s = url.strip()
    if s.startswith("data:") and ";base64," in s:
        header, _, payload = s.partition(";base64,")
        mime = header[len("data:") :]
        kind = mime.split("/", 1)[1] if "/" in mime else (mime or None)
        raw = _b64_bytes(payload)
        return raw, (len(payload) * 3) // 4, kind
    if len(s) > 256 and "/" not in s[:8] and s[:20].replace("+", "").replace(
        "/", ""
    ).replace("=", "").isalnum():
        raw = _b64_bytes(s)
        return raw, (len(s) * 3) // 4, None
    return None


def _sanitize_block(block: Any) -> Any:
    """Replace an image / base64 content block with a compact placeholder."""
    if not isinstance(block, dict):
        return block
    btype = block.get("type")
    # OpenAI-style: {"type":"image_url","image_url":{"url":"data:..."}}
    if btype == "image_url" or "image_url" in block:
        iu = block.get("image_url")
        url = iu.get("url") if isinstance(iu, dict) else iu
        info = _blob_from_url(url) if isinstance(url, str) else None
        if info:
            raw, n, kind = info
            return {"type": "image", "placeholder": _image_placeholder(raw, n, kind)}
        return {"type": "image", "placeholder": "<image>"}
    # LangChain v1 / Anthropic-style base64 image blocks.
    if btype == "image":
        data = block.get("data")
        if data is None and isinstance(block.get("source"), dict):
            data = block["source"].get("data")
        mime = block.get("mime_type") or (
            block.get("source", {}).get("media_type")
            if isinstance(block.get("source"), dict)
            else None
        )
        kind = mime.split("/", 1)[1] if isinstance(mime, str) and "/" in mime else None
        if isinstance(data, str):
            raw = _b64_bytes(data)
            return {
                "type": "image",
                "placeholder": _image_placeholder(raw, (len(data) * 3) // 4, kind),
            }
        return {"type": "image", "placeholder": "<image>"}
    if btype == "text":
        return {"type": "text", "text": block.get("text", "")}
    # Unknown block: pass through a base64-masked copy (key-based masking catches
    # data URIs under non-content keys as a safety net).
    from py_lumen_obs import redact_value

    return redact_value(block)


def _sanitize_content(content: Any) -> Any:
    if isinstance(content, list):
        return [_sanitize_block(b) for b in content]
    return content


def _message_to_dict(message: Any) -> dict:
    out: dict[str, Any] = {"role": getattr(message, "type", "unknown")}
    out["content"] = _sanitize_content(getattr(message, "content", ""))
    reasoning = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        # Founder ruling 2026-09-18: the model's own reasoning is part of the session RECORD.
        # It is recorded here (trace.jsonl / run.jsonl); re-sending it as context is a
        # per-provider decision the gateway owns (clue_gateway.openrouter_chat._retain_reasoning).
        out["reasoning_content"] = reasoning
    if out["role"] == "system":
        # Ephemeral advice must not become a second memory store through DEBUG
        # model-input logging. Keep ordinary guidance; only omit this data block.
        def redact_preferences(value):
            if isinstance(value, str):
                return re.sub(
                    r"<scoped_preference_data>.*?(?:</scoped_preference_data>|$)",
                    "<scoped_preference_data>[omitted; see scoped selection receipt]"
                    "</scoped_preference_data>",
                    value, flags=re.DOTALL,
                )
            if isinstance(value, list):
                return [redact_preferences(item) for item in value]
            if isinstance(value, dict):
                return {key: redact_preferences(item) for key, item in value.items()}
            return value

        out["content"] = redact_preferences(out["content"])
    name = getattr(message, "name", None)
    if name:
        out["name"] = name
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = [
            {"name": tc.get("name"), "args": tc.get("args")}
            for tc in tool_calls
            if isinstance(tc, dict)
        ]
    return out


# --------------------------------------------------------------------------- #
# LLMResult extraction helpers
# --------------------------------------------------------------------------- #
def _completion_text(response: Any) -> str:
    parts: list[str] = []
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            text = getattr(generation, "text", None)
            if text:
                parts.append(text)
                continue
            message = getattr(generation, "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                parts.append(content)
    return "".join(parts)


def _tool_calls(response: Any) -> list[dict]:
    calls: list[dict] = []
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            message = getattr(generation, "message", None)
            for tc in getattr(message, "tool_calls", None) or []:
                if isinstance(tc, dict):
                    calls.append({"name": tc.get("name"), "args": tc.get("args")})
    return calls


def _finish_reason(response: Any) -> Optional[str]:
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            info = getattr(generation, "generation_info", None)
            if isinstance(info, dict) and info.get("finish_reason"):
                return info["finish_reason"]
            message = getattr(generation, "message", None)
            meta = getattr(message, "response_metadata", None)
            if isinstance(meta, dict) and meta.get("finish_reason"):
                return meta["finish_reason"]
    return None


def _model_id(serialized: Any, metadata: Any) -> str:
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
    return "unknown"


def _subagent_name(inputs: Any, input_str: Any) -> str:
    if isinstance(inputs, dict):
        for key in ("subagent_type", "name", "subagent", "description"):
            val = inputs.get(key)
            if isinstance(val, str) and val:
                return val
    if isinstance(input_str, str) and input_str:
        return input_str[:80]
    return "subagent"


def _debug_enabled() -> bool:
    """Whether to attach the full (placeholdered) message list. Gated on debug —
    matching the plan (`cli.py` runs default to debug; server runs to info)."""
    import os

    from py_lumen_obs import LogMode

    return LogMode.coerce(os.environ.get("LUMEN_LOG_MODE")) is LogMode.DEBUG


# --------------------------------------------------------------------------- #
# The handler
# --------------------------------------------------------------------------- #
class TraceCallbackHandler(BaseCallbackHandler):
    """Emits structured trace events for one role's model instance.

    Attach ONE per role (the harness builds three model instances); the ``role``
    is stamped on every event so the viewer attributes cleanly. See the module
    docstring for the full event schema.
    """

    def __init__(self, role: str, metrics: Any = None) -> None:
        self._role = role
        # Optional per-run summary accumulator (run_metrics.RunMetrics). Shared by
        # all three role handlers of one run; None on every legacy/test path.
        self._metrics = metrics
        if metrics is not None:
            try:
                metrics.register_role(role)
            except Exception:  # noqa: BLE001 - metrics never break assembly
                self._metrics = None
        self._warned = False
        # run_id (UUID) → monotonic start time, for duration_ms.
        self._llm_started: dict[Any, float] = {}
        self._tool_started: dict[Any, float] = {}
        # run_id → subagent name, for task-delegation boundary pairing.
        self._subagents: dict[Any, str] = {}

    # -- LLM lifecycle ------------------------------------------------------ #
    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: Any = None, **kwargs: Any
    ) -> None:
        try:
            prompt = messages[0] if messages else []
            self._llm_started[run_id] = time.monotonic()
            event: dict[str, Any] = {
                "role": self._role,
                "model": _model_id(serialized, kwargs.get("metadata")),
                "message_count": len(prompt),
            }
            if _debug_enabled():
                event["messages"] = [_message_to_dict(m) for m in prompt]
            _log.info("llm_call_started", **event)
        except Exception as error:  # noqa: BLE001
            self._warn_once(error)

    def on_llm_start(
        self, serialized: Any, prompts: Any, *, run_id: Any = None, **kwargs: Any
    ) -> None:
        # Text-completion path (non-chat). Chat models fire on_chat_model_start.
        try:
            self._llm_started[run_id] = time.monotonic()
            event: dict[str, Any] = {
                "role": self._role,
                "model": _model_id(serialized, kwargs.get("metadata")),
                "message_count": len(prompts or []),
            }
            if _debug_enabled():
                event["messages"] = [
                    {"role": "user", "content": p} for p in (prompts or [])
                ]
            _log.info("llm_call_started", **event)
        except Exception as error:  # noqa: BLE001
            self._warn_once(error)

    def on_llm_end(self, response: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        try:
            usage = extract_usage(response) or {}
            duration_ms = self._duration_ms(self._llm_started.pop(run_id, None))
            _log.info(
                "llm_call_completed",
                role=self._role,
                model=self._model_of(response),
                completion=_completion_text(response),
                tool_calls=_tool_calls(response),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                duration_ms=duration_ms,
                finish_reason=_finish_reason(response),
            )
            if self._metrics is not None:
                self._metrics.record_llm_completed(
                    role=self._role,
                    duration_ms=duration_ms,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )
        except Exception as error:  # noqa: BLE001
            self._warn_once(error)

    def on_llm_error(self, error: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        try:
            duration_ms = self._duration_ms(self._llm_started.pop(run_id, None))
            _log.error(
                "llm_call_failed",
                role=self._role,
                model="unknown",
                error=f"{type(error).__name__}: {error}",
                duration_ms=duration_ms,
            )
            if self._metrics is not None:
                self._metrics.record_llm_failed(role=self._role, duration_ms=duration_ms)
        except Exception as err:  # noqa: BLE001
            self._warn_once(err)

    # -- Tool lifecycle (+ subagent boundaries) ----------------------------- #
    def on_tool_start(
        self,
        serialized: Any,
        input_str: Any,
        *,
        run_id: Any = None,
        inputs: Any = None,
        **kwargs: Any,
    ) -> None:
        try:
            name = (serialized or {}).get("name") if isinstance(serialized, dict) else None
            self._tool_started[run_id] = time.monotonic()
            if name in _TASK_TOOL_NAMES:
                sub = _subagent_name(inputs, input_str)
                self._subagents[run_id] = sub
                _log.info("subagent_started", role=self._role, subagent=sub)
                return
            _log.info(
                "tool_started",
                role=self._role,
                name=name or "tool",
                args=inputs if inputs is not None else input_str,
            )
        except Exception as error:  # noqa: BLE001
            self._warn_once(error)

    def on_tool_end(self, output: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        try:
            duration_ms = self._duration_ms(self._tool_started.pop(run_id, None))
            sub = self._subagents.pop(run_id, None)
            if sub is not None:
                _log.info(
                    "subagent_completed",
                    role=self._role,
                    subagent=sub,
                    duration_ms=duration_ms,
                )
                return
            _log.info(
                "tool_completed",
                role=self._role,
                name=kwargs.get("name") or "tool",
                result=str(getattr(output, "content", output)),
                duration_ms=duration_ms,
            )
        except Exception as error:  # noqa: BLE001
            self._warn_once(error)

    def on_tool_error(self, error: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        try:
            duration_ms = self._duration_ms(self._tool_started.pop(run_id, None))
            sub = self._subagents.pop(run_id, None)
            if sub is not None:
                _log.error(
                    "subagent_completed",
                    role=self._role,
                    subagent=sub,
                    duration_ms=duration_ms,
                    error=f"{type(error).__name__}: {error}",
                )
                return
            _log.error(
                "tool_failed",
                role=self._role,
                name=kwargs.get("name") or "tool",
                error=f"{type(error).__name__}: {error}",
                duration_ms=duration_ms,
            )
        except Exception as err:  # noqa: BLE001
            self._warn_once(err)

    # -- internals ---------------------------------------------------------- #
    @staticmethod
    def _duration_ms(started: Optional[float]) -> Optional[int]:
        if started is None:
            return None
        return int((time.monotonic() - started) * 1000)

    @staticmethod
    def _model_of(response: Any) -> str:
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            for key in ("model_name", "model"):
                val = llm_output.get(key)
                if isinstance(val, str) and val:
                    return val
        return "unknown"

    def _warn_once(self, error: Exception) -> None:
        if self._warned:
            return
        self._warned = True
        try:
            _log.warning(
                "trace_callback_warning",
                role=self._role,
                error=f"trace disabled: {type(error).__name__}: {error}"[:500],
            )
        except Exception:  # noqa: BLE001 - even the warning must not raise
            pass


def attach_trace_callback(model: Any, role: str, metrics: Any = None) -> Any:
    """Append a ``TraceCallbackHandler`` to ``model``'s own ``.callbacks`` field
    IN PLACE and return the SAME object.

    We append to the model's own declared ``callbacks`` field rather than wrapping
    it via ``.with_config(...)``: ``.with_config`` produces a ``RunnableBinding``,
    which is NOT a ``BaseChatModel``, and deepagents' ``resolve_model`` then routes
    it down a string-spec path that dies with
    ``AttributeError('ChatOpenAI' object has no attribute 'count')``, killing
    construction of every turn (probe-r9). ``callbacks`` is a declared pydantic
    field on ``BaseLanguageModel``, and ``BaseChatModel.generate`` passes it as
    ``local_callbacks``, so an instance-level handler fires on every invoke of THAT
    instance — which is why per-role attribution needs one instance per role (the
    harness builds three). A test sentinel without a writable ``callbacks`` field is
    left untouched; existing callbacks are appended to, never replaced.

    ``metrics`` is the run's optional ``run_metrics.RunMetrics`` accumulator,
    shared across the three role handlers so the run-end summary sees every
    role's calls. Omitting it (the default) is exactly the pre-existing
    behaviour."""
    handler = TraceCallbackHandler(role=role, metrics=metrics)
    if not hasattr(model, "callbacks"):
        return model
    try:
        existing = model.callbacks
        if existing is None:
            model.callbacks = [handler]
        elif isinstance(existing, list):
            existing.append(handler)
        else:
            add_handler = getattr(existing, "add_handler", None)
            if callable(add_handler):
                add_handler(handler)
            else:
                model.callbacks = [existing, handler]
    except Exception:  # noqa: BLE001 - never block assembly on wiring
        return model
    return model
