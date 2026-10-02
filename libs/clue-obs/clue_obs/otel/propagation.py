"""W3C trace-context propagation for the fleet payload (lane 3 slice 2, D1).

The API stamps the carrier of its current span into the task payload at enqueue; the worker
restores it as the parent of its ``fleet.task`` span. Kept here so ``clue_fleet`` imports only
``clue_obs``.
"""

from __future__ import annotations

from collections.abc import Mapping

from opentelemetry import propagate, trace
from opentelemetry.context import Context

__all__ = ["CARRIER_KEYS", "carrier_from_current_span", "context_from_carrier"]

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
