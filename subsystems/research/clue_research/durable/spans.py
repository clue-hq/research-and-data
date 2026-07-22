"""Span names for the durable-execution layer (M7) — owned here, not in ``obs`` (frozen, M0.5).

``obs/spans.py`` is the frozen shared surface: it owns the *campaign-phase* tokens
(``phase_span`` / ``PROJECT_PHASES``, derived from ``core.ProjectPhase``) that every milestone's
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
# M7.3 project-run state-machine attributes: the phase being run and the run-level status it
# resolved to. The phase *span name* comes from the frozen ``obs.phase_span``; these ride as
# attributes on it so a phase's outcome is queryable.
ATTR_PHASE = "phase"
ATTR_PHASE_STATUS = "phase_status"
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

# --- cost governance spans (M7.5 budget engine) ---------------------------------------------
# The budget engine is the single chokepoint for spend authorisation + the live cost accounting.
# A pre-spend ``check`` and the pre-run ``estimate`` are traced; a governance ``budget_event``
# (deny / graceful-stop / breach-pending / cap-raised) is both a durable audit row and a span.
SPAN_BUDGET = "budget"
SPAN_BUDGET_CHECK = "budget.check"
SPAN_BUDGET_ESTIMATE = "budget.estimate"
SPAN_BUDGET_EVENT = "budget.event"

# M7.5 budget attributes (ride on the budget spans; redacted/stringified like any extra attr —
# numeric values read back as their string form, per the M7.2 obs-redaction note).
ATTR_BUDGET_SCOPE = "budget_scope"
ATTR_BUDGET_VERDICT = "budget_verdict"
ATTR_BUDGET_KIND = "budget_kind"
ATTR_PROJECTED_CENTS = "projected_cents"
ATTR_CAP_CENTS = "cap_cents"
ATTR_SPENT_CENTS = "spent_cents"
ATTR_REMAINING_CENTS = "remaining_cents"


def graph_node_span(node: str) -> str:
    """Span name for one per-account graph node, e.g. ``account.graph.plan``.

    ``node`` is the node boundary (``plan`` | ``fan_out`` | ``collect`` | ``handoff``); per-aspect
    detail rides on the ``aspect`` attribute, not the span name, so a query for all planning across
    accounts is ``span.name = 'account.graph.plan'``.
    """
    return f"{SPAN_ACCOUNT_GRAPH}.{node}"
