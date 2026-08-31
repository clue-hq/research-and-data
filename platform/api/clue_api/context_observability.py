"""Privacy-safe production context composition metrics.

The context/card/tool paths carry exact customer facts, so observability is deliberately narrower
than their durable receipts: bounded kinds, versions, availability, counts, and outcomes only.
Identifiers and hashes belong in structured logs for correlation; claim values, evidence, bodies,
URLs, credentials, email, and tokens belong in neither logs nor metric attributes.
"""

from __future__ import annotations

from clue_obs.otel.metrics import MetricSink, get_metric_sink

__all__ = [
    "METRIC_CONTEXT_CARD_OMISSIONS",
    "METRIC_CONTEXT_CARDS",
    "METRIC_CONTEXT_RECEIPT_REFS",
    "METRIC_CONTEXT_RECEIPTS",
    "METRIC_CONTEXT_TOOL_OUTCOMES",
    "record_context_card",
    "record_context_receipt",
    "record_context_tool_outcome",
]

METRIC_CONTEXT_CARDS = "agent.context.cards.total"
METRIC_CONTEXT_CARD_OMISSIONS = "agent.context.card.omissions"
METRIC_CONTEXT_RECEIPTS = "agent.context.receipts.total"
METRIC_CONTEXT_RECEIPT_REFS = "agent.context.receipt.refs"
METRIC_CONTEXT_TOOL_OUTCOMES = "agent.context.tool.outcomes"


def record_context_card(
    *,
    card_kind: str,
    schema_version: str,
    available: bool,
    omitted_count: int,
    sink: MetricSink | None = None,
) -> None:
    if omitted_count < 0:
        raise ValueError("context card omission count cannot be negative")
    target = sink or get_metric_sink()
    attrs = {
        "card_kind": card_kind,
        "schema_version": schema_version,
        "availability": "available" if available else "unavailable",
    }
    target.add(METRIC_CONTEXT_CARDS, 1, attrs)
    target.gauge(METRIC_CONTEXT_CARD_OMISSIONS, omitted_count, attrs)


def record_context_receipt(
    *,
    schema_version: str,
    included_count: int,
    excluded_count: int,
    sink: MetricSink | None = None,
) -> None:
    if min(included_count, excluded_count) < 0:
        raise ValueError("context receipt counts cannot be negative")
    target = sink or get_metric_sink()
    attrs = {"schema_version": schema_version}
    target.add(METRIC_CONTEXT_RECEIPTS, 1, attrs)
    target.gauge(
        METRIC_CONTEXT_RECEIPT_REFS,
        included_count,
        {**attrs, "disposition": "included"},
    )
    target.gauge(
        METRIC_CONTEXT_RECEIPT_REFS,
        excluded_count,
        {**attrs, "disposition": "excluded"},
    )


def record_context_tool_outcome(
    *,
    tool_address: str,
    outcome: str,
    replayed: bool,
    sink: MetricSink | None = None,
) -> None:
    (sink or get_metric_sink()).add(
        METRIC_CONTEXT_TOOL_OUTCOMES,
        1,
        {
            "tool_address": tool_address,
            "outcome": outcome,
            "replayed": "true" if replayed else "false",
        },
    )
