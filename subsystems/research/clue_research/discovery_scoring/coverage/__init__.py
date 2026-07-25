"""Coverage-confidence estimator (M6.5 / ENG-150).

Open-ended discovery can never *prove* it found everyone (staged-flow §3; Doc C §7). This package
produces the honest alternative for **Output 1**: an estimated coverage **band** over the channels
actually searched ("~X–Y% of the addressable set found via these channels"), plus the named
account-scope channels **not** yet searched — so the client can ask for more rather than be misled
into believing the search was exhaustive.

Coverage is a **trust** statement, deliberately separate from M6.1's **cost**-control stopping rule:
the stopping rule decides *when to stop spending*; coverage reports *how much we likely found and
what we skipped*. It only *reads* the stopping reason — a budget-cap stop with still-high marginal
yield reads as low confidence + "raise the budget", distinct from a genuine saturation stop.

Public seam:
* :func:`estimate_coverage` — the **pure, deterministic** estimation core over per-channel yield
  counters; the saturation method sits entirely behind it, so it is swappable (saturation →
  capture-recapture → learned) without touching any consumer (D7).
* :func:`coverage_report` — ``(conn, run_id, spec) -> CoverageReport | None``: the durable read path
  that rebuilds the estimator's inputs from ``source_yield`` telemetry + the ``source_manifest``
  registry, so coverage is queryable by ``run_id`` (the M6.4 checkpoint + M13 obs consume it).
* :class:`CoverageReport` / :class:`CoverageBand` / :class:`CoverageConfidence` and the per-channel
  :class:`ChannelCurvePoint` / :class:`ChannelObservation` / :class:`UnsearchedChannel` shapes.

Read-only over run telemetry + the source registry; it computes and reports — writes no claims and
gates nothing, so it can be added/swapped/improved with zero impact on M6.1–M6.4.
"""

from __future__ import annotations

from clue_research.discovery_scoring.coverage.config import (
    DEFAULT_COVERAGE_CONFIG,
    CoverageConfig,
)
from clue_research.discovery_scoring.coverage.estimator import (
    estimate_coverage,
    saturation_coverage,
)
from clue_research.discovery_scoring.coverage.report import coverage_report
from clue_research.discovery_scoring.coverage.results import (
    ChannelCurvePoint,
    ChannelObservation,
    CoverageBand,
    CoverageConfidence,
    CoverageReport,
    UnsearchedChannel,
)

__all__ = [
    "estimate_coverage",
    "saturation_coverage",
    "coverage_report",
    "CoverageConfig",
    "DEFAULT_COVERAGE_CONFIG",
    "CoverageReport",
    "CoverageBand",
    "CoverageConfidence",
    "ChannelCurvePoint",
    "ChannelObservation",
    "UnsearchedChannel",
]
