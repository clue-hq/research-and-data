"""`clue_research.discovery_scoring` — Discovery (mode M1) + Pass A Scoring (M6).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M6.

Beat-0 froze the cross-milestone seam in ``core`` (see ``docs/specs/_beat0-contract-freeze.md``):
M6's ``DISCOVERY``/``SCORING``/``TIER_CHECKPOINT`` phases *implement* ``PhaseHandler`` from
:mod:`clue_core.execution` (the checkpoint pauses via ``PhaseResult(status=PAUSED)``), the
Pass-A scorer returns ``core.Score``, and budget checks call the injected ``BudgetEngine``. Imported
accounts (M5) converge here through the claim store, not an import — M6 imports no sibling package.

Implemented so far:
* **M6.1 (ENG-128)** — Account Discovery (mode M1): :func:`discover` + the grounded
  :class:`DiscoveryChannel` seam, the *expand* orchestration, in-stream dedup, and the stopping
  rule. See :mod:`clue_research.discovery_scoring.discovery`.
* **M6.2 (ENG-133)** — Existence/identity gate + discovery-provenance: :func:`admit` (resolve →
  M2 disposition → discovery-provenance claim) and the integrated :class:`DiscoveryPhaseHandler`.
  See :mod:`clue_research.discovery_scoring.gate`.
* **M6.3 (ENG-138)** — Pass A scoring engine: :func:`score_account` (fill scoring proxies via the
  tier-1–3 waterfall → pure scorer → persist the decomposed, evidence-backed fit/intent score) and
  the integrated :class:`ScoringPhaseHandler`. See :mod:`clue_research.discovery_scoring.scoring`.
* **M6.4 (ENG-146)** — Tiering + human checkpoint: :func:`assign_tiers` (deterministic tier verdict)
  + :func:`estimate_cost` (pre-run cost estimate) and the integrated, interrupt-based
  :class:`TierCheckpointPhaseHandler` (durable suspend/resume before Pass-B spend). See
  :mod:`clue_research.discovery_scoring.tiering`.
"""

from __future__ import annotations

from clue_research.discovery_scoring.coverage import (
    DEFAULT_COVERAGE_CONFIG,
    ChannelCurvePoint,
    ChannelObservation,
    CoverageBand,
    CoverageConfidence,
    CoverageConfig,
    CoverageReport,
    UnsearchedChannel,
    coverage_report,
    estimate_coverage,
    saturation_coverage,
)
from clue_research.discovery_scoring.discovery import (
    DEFAULT_DISCOVERY_CONFIG,
    LOOKALIKE_CHANNEL,
    CandidateHypothesis,
    CandidateRecord,
    ChannelRegistry,
    ChannelYield,
    DiscoveryChannel,
    DiscoveryConfig,
    DiscoveryQuery,
    DiscoveryResult,
    DiscoveryStrategy,
    StoppingReason,
    discover,
)
from clue_research.discovery_scoring.gate import (
    AdmissionResult,
    AdmissionStatus,
    DefaultExistenceCheck,
    ExistenceCheck,
    ExistenceVerdict,
    admit,
)
from clue_research.discovery_scoring.phases import (
    DiscoveryPhaseHandler,
    ScoringPhaseHandler,
    TierCheckpointPhaseHandler,
    discovery_run_id,
    project_discovery_run_id,
)
from clue_research.discovery_scoring.score_projection import (
    AmbiguousFitProjection,
    FitProjection,
    exact_fit_projection,
)
from clue_research.discovery_scoring.scoring import (
    DEFAULT_SCORING_CONFIG,
    FIT_FIELD,
    INTENT_FIELD,
    AccountScore,
    AccountScoringOutcome,
    ScoringConfig,
    SourceYieldRow,
    admitted_account_ids,
    aggregate_yield,
    pass_a_fill_fields,
    score_account,
)
from clue_research.discovery_scoring.tiering import (
    DEFAULT_TIERING_CONFIG,
    TIER_FIELD,
    AccountScoreView,
    AccountTierView,
    CheckpointAction,
    CheckpointDecision,
    CheckpointReview,
    CheckpointStatus,
    TierAssignment,
    TieringConfig,
    assign_tiers,
    cutoff_version,
    estimate_cost,
    load_score_views,
    persist_tier,
    tier_distribution,
)

__all__ = [
    # M6.1 — discovery
    "discover",
    "DiscoveryResult",
    "ChannelYield",
    "CandidateHypothesis",
    "CandidateRecord",
    "DiscoveryChannel",
    "DiscoveryQuery",
    "ChannelRegistry",
    "DiscoveryStrategy",
    "DiscoveryConfig",
    "DEFAULT_DISCOVERY_CONFIG",
    "StoppingReason",
    "LOOKALIKE_CHANNEL",
    # M6.5 — coverage-confidence estimator
    "estimate_coverage",
    "saturation_coverage",
    "coverage_report",
    "CoverageReport",
    "CoverageBand",
    "CoverageConfidence",
    "CoverageConfig",
    "DEFAULT_COVERAGE_CONFIG",
    "ChannelCurvePoint",
    "ChannelObservation",
    "UnsearchedChannel",
    # M6.2 — existence/identity gate
    "admit",
    "AdmissionResult",
    "AdmissionStatus",
    "ExistenceCheck",
    "ExistenceVerdict",
    "DefaultExistenceCheck",
    # M6.3 — Pass A scoring
    "score_account",
    "admitted_account_ids",
    "pass_a_fill_fields",
    "aggregate_yield",
    "AccountScore",
    "AccountScoringOutcome",
    "SourceYieldRow",
    "ScoringConfig",
    "DEFAULT_SCORING_CONFIG",
    "FIT_FIELD",
    "INTENT_FIELD",
    "FitProjection",
    "AmbiguousFitProjection",
    "exact_fit_projection",
    # M6.4 — tiering + human checkpoint
    "assign_tiers",
    "tier_distribution",
    "estimate_cost",
    "cutoff_version",
    "load_score_views",
    "persist_tier",
    "TIER_FIELD",
    "AccountScoreView",
    "AccountTierView",
    "TierAssignment",
    "CheckpointReview",
    "CheckpointDecision",
    "CheckpointAction",
    "CheckpointStatus",
    "TieringConfig",
    "DEFAULT_TIERING_CONFIG",
    # M6 phase handlers
    "DiscoveryPhaseHandler",
    "ScoringPhaseHandler",
    "TierCheckpointPhaseHandler",
    "discovery_run_id",
    "project_discovery_run_id",
]
