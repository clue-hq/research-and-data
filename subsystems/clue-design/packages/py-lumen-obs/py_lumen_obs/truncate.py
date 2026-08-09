"""Mode-aware truncation for console/info output.

At ``info`` the shared chain keeps events skimmable: any string longer than
``limit`` (~400 chars) is cut with a ``… (+N chars)`` suffix so a giant tool
result or LLM completion does not drown the timeline. At ``debug`` truncation
is a no-op (you asked for every detail). The per-run ``run.jsonl`` handler never
installs this processor at all, so the on-disk trace is always full — disk is
cheap, console verbosity is the knob.

This lives as a *per-handler* processor (built into each output's
``ProcessorFormatter``) rather than the shared pre-chain precisely so the same
event can be truncated for the console yet written whole to the run file.
"""
from __future__ import annotations

from typing import Any, Callable

from .config_types import LogMode

DEFAULT_LIMIT = 400

# Short structural fields — never worth truncating.
_SKIP_KEYS = frozenset({"level", "timestamp", "logger", "logger_name"})


def _truncate_str(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"… (+{len(value) - limit} chars)"


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _truncate_str(value, limit)
    if isinstance(value, dict):
        return {
            k: (v if k in _SKIP_KEYS else _truncate(v, limit))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_truncate(v, limit) for v in value]
    return value


def make_truncate_processor(
    mode: LogMode, limit: int = DEFAULT_LIMIT
) -> Callable[[Any, str, dict], dict]:
    """Return a structlog processor that truncates long strings at ``info`` and
    passes everything through untouched at ``debug``."""
    if mode is LogMode.DEBUG:
        def _noop(logger: Any, method_name: str, event_dict: dict) -> dict:
            return event_dict

        return _noop

    def _processor(logger: Any, method_name: str, event_dict: dict) -> dict:
        for key in list(event_dict.keys()):
            if key in _SKIP_KEYS:
                continue
            event_dict[key] = _truncate(event_dict[key], limit)
        return event_dict

    return _processor
