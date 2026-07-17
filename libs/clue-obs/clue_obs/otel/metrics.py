"""Metric emission points for the Doc C §6 surfaces (M0.5).

The four live surfaces — per-source yield, verification health, cost burn-down, phase progress — are
*derived from claim provenance* (M0.2), which is the same data the source-intelligence learning loop
consumes (staged-flow §7e). Defining them off the claim store means observability and the learning
loop share one source of truth rather than a parallel pipeline.

M0.5 ships the emission **hooks** and a swappable :class:`MetricSink` (an in-memory default for
dev/CI/tests; an OTel-metrics sink plugs in for production without touching callers). The values
populate as later milestones actually produce and verify claims.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Protocol

from clue_core import Claim, EntityType, IdentityBinding, VerificationStatus
from clue_obs.otel.spans import CAMPAIGN_PHASES

# --- metric names -----------------------------------------------------------
METRIC_CLAIMS_TOTAL = "research.claims.total"  # by source
METRIC_CLAIMS_SURVIVING = "research.claims.surviving"  # by source (verified)
METRIC_TIER4_TOTAL = "research.verification.tier4.total"
METRIC_TIER4_PASSED = "research.verification.tier4.passed"
METRIC_CONTACT_CLAIMS_TOTAL = "research.verification.contact.total"
METRIC_CONTACT_STRONG_BINDING = "research.verification.contact.strong_binding"
# Use-class tag distribution (Doc D §2 / Doc C §6) — the *appropriateness* axis, kept separate from
# the accuracy axis above (Doc D §5: separately measurable). Labelled by use_class.
METRIC_USE_CLASS_TOTAL = "research.compliance.use_class.total"
METRIC_COST_CENTS = "research.cost.cents"
METRIC_COST_CAP_CENTS = "research.cost.cap_cents"
METRIC_PHASE_PROGRESS = "research.phase.progress"


class MetricSink(Protocol):
    """The swappable metrics backend. Production wires an OTel-metrics implementation; the default
    is in-memory (collects for tests/dev). Callers depend on this Protocol, not a concrete sink."""

    def add(self, name: str, value: float, attributes: Mapping[str, str]) -> None: ...
    def gauge(self, name: str, value: float, attributes: Mapping[str, str]) -> None: ...


def _key(name: str, attributes: Mapping[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted(attributes.items()))


class InMemorySink:
    """Default sink: accumulates counters and last-value gauges in memory (what tests read)."""

    def __init__(self) -> None:
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self.gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def add(self, name: str, value: float, attributes: Mapping[str, str]) -> None:
        self.counters[_key(name, attributes)] = (
            self.counters.get(_key(name, attributes), 0.0) + value
        )

    def gauge(self, name: str, value: float, attributes: Mapping[str, str]) -> None:
        self.gauges[_key(name, attributes)] = value

    def counter(self, name: str, **attributes: str) -> float:
        return self.counters.get(_key(name, attributes), 0.0)

    def gauge_value(self, name: str, **attributes: str) -> float:
        return self.gauges.get(_key(name, attributes), 0.0)


_default_sink: MetricSink = InMemorySink()


def get_metric_sink() -> MetricSink:
    return _default_sink


def set_metric_sink(sink: MetricSink) -> None:
    """Swap the metrics backend (e.g. install an OTel-metrics sink in production, or a fresh
    in-memory sink per test)."""
    global _default_sink
    _default_sink = sink


def _source_label(claim: Claim) -> str:
    """A per-source key read from claim provenance: the registry ``source_key`` the M4.1 waterfall
    stamps (preferred — M4 backlog invariant), falling back to ``source_url`` then tier for a
    claim written without one (a non-resolver writer / a pre-M4 row)."""
    return claim.source_key or claim.source_url or f"tier-{claim.source_tier}"


def record_source_yield(claims: Iterable[Claim], *, sink: MetricSink | None = None) -> None:
    """Per-source yield: how many claims survive verification, bucketed by source (Doc C §6).

    Keyed by :func:`_source_label`, which now prefers the registry ``source_key`` the M4.1 waterfall
    stamps (falling back to ``source_url`` then tier for claims without one). Dashboards and the
    learning loop (M13, staged-flow §7e) treat that as a re-keying, not a new source set.
    """
    sink = sink or get_metric_sink()
    for claim in claims:
        label = {"source": _source_label(claim)}
        sink.add(METRIC_CLAIMS_TOTAL, 1, label)
        if claim.verification_status is VerificationStatus.VERIFIED:
            sink.add(METRIC_CLAIMS_SURVIVING, 1, label)


def record_verification_health(claims: Iterable[Claim], *, sink: MetricSink | None = None) -> None:
    """Verification health: tier-4 faithfulness-judge pass-rate + strong-binding share of personal
    claims (Doc C §6 — the early warning that a model/resolver swap regressed quality)."""
    sink = sink or get_metric_sink()
    for claim in claims:
        if claim.source_tier == 4:
            sink.add(METRIC_TIER4_TOTAL, 1, {})
            if claim.verification_status is VerificationStatus.VERIFIED:
                sink.add(METRIC_TIER4_PASSED, 1, {})
        if claim.entity_type is EntityType.CONTACT:
            sink.add(METRIC_CONTACT_CLAIMS_TOTAL, 1, {})
            if claim.identity_binding is IdentityBinding.STRONG:
                sink.add(METRIC_CONTACT_STRONG_BINDING, 1, {})


def record_use_class_distribution(
    claims: Iterable[Claim], *, sink: MetricSink | None = None
) -> None:
    """Use-class tag distribution: per-use-class counts of personal claims (Doc D §2 / Doc C §6).

    The *appropriateness* surface — kept distinct from :func:`record_verification_health` (the
    accuracy axis) so "what share of personal claims are sensitive/locked" is separately measurable
    from "what share are strongly bound" (Doc D §5). Computed at-rest over the claim store: it reads
    the ``use_class`` M8 stamps born-correct at extraction (M8.4), so a claim with no ``use_class``
    (account / firmographic — not personal) is not counted. The share-sensitive surface is
    ``total{use_class=sensitive} / Σ total``.
    """
    sink = sink or get_metric_sink()
    for claim in claims:
        if claim.use_class is not None:
            sink.add(METRIC_USE_CLASS_TOTAL, 1, {"use_class": claim.use_class.value})


def record_cost_burndown(
    claims: Iterable[Claim], *, cap_cents: Decimal | None = None, sink: MetricSink | None = None
) -> None:
    """Cost burn-down: spend so far vs. the cap (Doc C §6 / D7)."""
    sink = sink or get_metric_sink()
    spent = sum((claim.cost_cents for claim in claims), Decimal(0))
    sink.gauge(METRIC_COST_CENTS, float(spent), {})
    if cap_cents is not None:
        sink.gauge(METRIC_COST_CAP_CENTS, float(cap_cents), {})


def record_phase_progress(
    phase: str, *, completed: int, total: int, sink: MetricSink | None = None
) -> None:
    """Phase progress 0..1 for a campaign-run phase (Doc C §6). M7 supplies the counts."""
    if phase not in CAMPAIGN_PHASES:
        raise ValueError(f"unknown campaign phase {phase!r}; expected one of {CAMPAIGN_PHASES}")
    sink = sink or get_metric_sink()
    fraction = completed / total if total else 0.0
    sink.gauge(METRIC_PHASE_PROGRESS, fraction, {"phase": phase})
