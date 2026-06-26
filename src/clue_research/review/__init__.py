"""`clue_research.review` — Review, Feedback & Observability (M13).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M13.

Shipped so far:

* **M13.4 — the client-facing cost & progress surface** (:mod:`clue_research.review.observability`):
  the read-only :class:`ObservabilitySurface` (phase progress, cost burn-down, pre-run estimate,
  per-source yield, verification health, coverage confidence), its panel projections, the injected
  reader Protocols whose concrete impls are wired at the ``api`` composition root, and their
  in-memory fakes.
"""

from __future__ import annotations

from clue_research.review.observability import (
    COST_STATUS_GRACEFUL_STOP,
    COST_STATUS_NEAR_CAP,
    COST_STATUS_OK,
    CampaignProgress,
    CampaignStateReader,
    CostBurnDown,
    CostBurnDownReader,
    CoverageReportReader,
    InMemoryCampaignStateReader,
    InMemoryCostBurnDownReader,
    InMemoryCoverageReportReader,
    InMemoryPreRunEstimator,
    InMemoryVerificationHealthReader,
    ObservabilitySurface,
    PhaseProgress,
    PreRunEstimate,
    PreRunEstimator,
    RunPhaseState,
    VerificationHealth,
    VerificationHealthCounts,
    VerificationHealthReader,
    observability_is_client_facing,
)

__all__ = [
    # M13.4 observability surface
    "ObservabilitySurface",
    "observability_is_client_facing",
    # panel projections
    "CampaignProgress",
    "PhaseProgress",
    "CostBurnDown",
    "PreRunEstimate",
    "VerificationHealth",
    "VerificationHealthCounts",
    "RunPhaseState",
    # cost-status tokens
    "COST_STATUS_OK",
    "COST_STATUS_NEAR_CAP",
    "COST_STATUS_GRACEFUL_STOP",
    # injected reader protocols (concrete impls at the api root)
    "CampaignStateReader",
    "CostBurnDownReader",
    "PreRunEstimator",
    "VerificationHealthReader",
    "CoverageReportReader",
    # in-memory fakes
    "InMemoryCampaignStateReader",
    "InMemoryCostBurnDownReader",
    "InMemoryPreRunEstimator",
    "InMemoryVerificationHealthReader",
    "InMemoryCoverageReportReader",
]
