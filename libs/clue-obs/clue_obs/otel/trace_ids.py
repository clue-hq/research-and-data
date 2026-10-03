"""The trace a log line or an error belongs to (2026-10-03 agent-scoped tracing spec, R4/R5).

One id across tools: the OpenTelemetry trace id, which Langfuse already uses as its own. Every log
line carries ``trace_id``/``span_id`` (32/16 lowercase hex) from the current span, and Sentry
events carry the same. An error is often logged or reported after the span it was raised under
has closed (the fleet worker's ``worker.work_error``), so the span stamps its ids on the exception
as it escapes (:func:`remember_trace`) and both readers fall back to that stamp.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import MutableMapping
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id

__all__ = ["add_trace_ids", "current_trace_ids", "remember_trace", "remembered_trace"]

#: The attribute an escaping exception carries its ``(trace_id, span_id)`` under. The design
#: subsystem's log chain reads the same literal (the two obs packages share no imports).
EXCEPTION_TRACE_ATTR = "__clue_trace_ids__"


def current_trace_ids() -> tuple[str, str] | None:
    """The current span's ``(trace_id, span_id)`` in hex, or ``None`` outside any valid span."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format_trace_id(context.trace_id), format_span_id(context.span_id)


def remember_trace(exc: BaseException) -> None:
    """Stamp the current span's ids on ``exc``; the first stamp (the innermost span) wins."""
    ids = current_trace_ids()
    if ids is None or remembered_trace(exc) is not None:
        return
    # An exception type that refuses new attributes keeps no stamp.
    with contextlib.suppress(AttributeError, TypeError):
        setattr(exc, EXCEPTION_TRACE_ATTR, ids)


def remembered_trace(exc: BaseException) -> tuple[str, str] | None:
    ids = getattr(exc, EXCEPTION_TRACE_ATTR, None)
    if isinstance(ids, tuple) and len(ids) == 2 and all(isinstance(i, str) for i in ids):
        return ids[0], ids[1]
    return None


def _logged_exception(event_dict: MutableMapping[str, Any]) -> BaseException | None:
    exc_info = event_dict.get("exc_info")
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        return exc_info[1] if isinstance(exc_info[1], BaseException) else None
    if exc_info is True:
        return sys.exc_info()[1]
    return None


def add_trace_ids(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: stamp ``trace_id``/``span_id`` from the current span, else from the
    logged exception's stamp; a line with neither is left alone."""
    del logger, method_name
    ids = current_trace_ids()
    if ids is None:
        logged = _logged_exception(event_dict)
        ids = remembered_trace(logged) if logged is not None else None
    if ids is not None:
        event_dict.setdefault("trace_id", ids[0])
        event_dict.setdefault("span_id", ids[1])
    return event_dict
