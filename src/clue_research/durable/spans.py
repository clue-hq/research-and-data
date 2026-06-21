"""Span names for the durable-execution layer (M7) — owned here, not in ``obs`` (frozen, M0.5).

``obs/spans.py`` is the frozen shared surface: it owns the *campaign-phase* tokens
(``phase_span`` / ``CAMPAIGN_PHASES``, derived from ``core.CampaignPhase``) that every milestone's
phase handler shares. The *per-account graph* node spans (``plan`` / ``fan_out`` / ``collect``) and
the budget ``cap_hit`` event are M7-internal, so their names live here and are passed to the stable
``obs.traced_step`` seam — exactly the pattern the spec prescribes (M7.1 "named trace spans
per node"; the cost surface reads claim provenance, not span hierarchies, so M7 owning these names
changes nothing downstream).

Naming mirrors the ``obs`` hierarchy convention (dot-separated ``area.stage[.tag]``): the M7 root is
``account.graph`` for the per-account orchestrator-worker graph, ``budget`` for cost governance.
"""

from __future__ import annotations

# --- per-account graph node spans (M7.1 plan → fan_out → collect; M7.2 facet recursion) -----
SPAN_ACCOUNT_GRAPH = "account.graph"
# The bounded-recursion cap-hit event (M7.2) — emitted when the SpawnGuard denies a facet spawn, so
# "the hard limit held even when the model misbehaved" is queryable and feeds M7.5/M13.
SPAN_CAP_HIT = "account.graph.cap_hit"
# The per-aspect fan-out summary (M7.2) — facets actually spawned + deepest level reached. A
# distinct span (not a ``graph_node_span`` node, which is the plan→fan_out→collect→handoff cycle).
SPAN_FANOUT_SUMMARY = "account.graph.fanout_summary"

# M7-specific attribute keys (passed through ``obs.traced_step``; not in the frozen
# ``obs`` STANDARD_ATTRIBUTES, so they are value-shape-redacted like any extra attribute).
ATTR_ASPECT = "aspect"
ATTR_TIER = "tier"
ATTR_GAP_FIELD_COUNT = "gap_field_count"
ATTR_ASPECT_COUNT = "aspect_count"
ATTR_WORKER_COUNT = "worker_count"
ATTR_CLAIM_REF_COUNT = "claim_ref_count"
ATTR_DEPTH = "depth"
ATTR_WORKER_STATUS = "worker_status"
# M7.2 fan-out telemetry: facet sub-workers actually spawned for an aspect, the deepest level
# reached, and (on a cap_hit span) the SpawnGuard deny reason.
ATTR_FACET_COUNT = "facet_count"
ATTR_DEPTH_REACHED = "depth_reached"
ATTR_CAP_HIT_REASON = "cap_hit_reason"


def graph_node_span(node: str) -> str:
    """Span name for one per-account graph node, e.g. ``account.graph.plan``.

    ``node`` is the node boundary (``plan`` | ``fan_out`` | ``collect`` | ``handoff``); per-aspect
    detail rides on the ``aspect`` attribute, not the span name, so a query for all planning across
    accounts is ``span.name = 'account.graph.plan'``.
    """
    return f"{SPAN_ACCOUNT_GRAPH}.{node}"
