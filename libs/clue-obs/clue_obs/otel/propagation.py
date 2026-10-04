"""W3C trace-context propagation for the fleet payload (lane 3 slice 2, D1).

The API stamps the carrier of its current span into the task payload at enqueue. Since 2026-10-03
(agent-scoped tracing spec, R3) the worker does NOT join that trace: :func:`task_trace_start`
gives the ``fleet.task`` span a fresh root and a link to the enqueuing span, so every task is its
own trace that still says what launched it. Kept here so ``clue_fleet`` imports only ``clue_obs``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace import Link, format_trace_id

__all__ = [
    "CARRIER_KEYS",
    "TaskTraceStart",
    "carrier_from_current_span",
    "context_from_carrier",
    "task_trace_start",
]

#: The two W3C keys the carrier may hold.
CARRIER_KEYS: tuple[str, ...] = ("traceparent", "tracestate")


def carrier_from_current_span() -> dict[str, str]:
    """The current span's W3C carrier, or ``{}`` when no valid span is current."""
    if not trace.get_current_span().get_span_context().is_valid:
        return {}
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {key: value for key, value in carrier.items() if key in CARRIER_KEYS}


def context_from_carrier(carrier: Mapping[str, object]) -> Context | None:
    """The remote parent context a carrier names, or ``None`` when it holds no ``traceparent``."""
    subset = {
        key: value
        for key, value in carrier.items()
        if key in CARRIER_KEYS and isinstance(value, str)
    }
    if "traceparent" not in subset:
        return None
    return propagate.extract(subset)


@dataclass(frozen=True)
class TaskTraceStart:
    """How a fleet task's span starts: a fresh root context, the link to its launcher (empty when
    the payload carried none), and the launcher's trace id as 32 lowercase hex (or ``None``)."""

    context: Context
    links: list[Link] = field(default_factory=list)
    launched_by_trace_id: str | None = None


def task_trace_start(carrier: Mapping[str, object]) -> TaskTraceStart:
    """A new trace for one fleet task, linked to the span whose carrier the payload holds."""
    launcher = context_from_carrier(carrier)
    if launcher is None:
        return TaskTraceStart(context=Context())
    launched_by = trace.get_current_span(launcher).get_span_context()
    if not launched_by.is_valid:
        return TaskTraceStart(context=Context())
    return TaskTraceStart(
        context=Context(),
        links=[Link(launched_by)],
        launched_by_trace_id=format_trace_id(launched_by.trace_id),
    )
