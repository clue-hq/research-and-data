"""Tiering + human checkpoint (M6.4 / ENG-146).

Convert the M6.3 Pass-A scores into **tier assignments** and present the designed **human
checkpoint** — the durable ``interrupt()``-style gate where the client reviews provisional scores,
sees the pre-run cost estimate (``~N discovered → at these cutoffs ~M go deep → ~$X``), and adjusts
cutoffs / raises the budget / approves before any Pass-B spend (substrate §5a/§10, Doc C §5). Where
the cutoffs land *is the spend decision*, so tiering is a **pure policy over the stored score
object**, not an agent.

Public seam:
* :func:`assign_tiers` — the deterministic tier verdict (``scores × cutoffs -> {account -> tier}``).
* :func:`estimate_cost` / :func:`tier_distribution` / :func:`cutoff_version` — the pure
  cost-estimate and versioning helpers.
* :func:`load_score_views` — read the M6.3 score object back (D5-safe, per scoring run).
* :func:`persist_tier` — write the approved per-account decision (idempotent, ICP-scoped supersede).
* :class:`CheckpointReview` / :class:`CheckpointDecision` / :class:`AccountScoreView` /
  :class:`AccountTierView` / :class:`TierAssignment` — the review payload, the ``resume(...)``
  decision, and the result rows.
* :class:`TieringConfig` — the per-tier Pass-B budget bands (policy as data, D7).

The integrated ``TIER_CHECKPOINT`` :class:`~clue_core.PhaseHandler` (the durable
suspend/resume behaviour M7 schedules) lives in :mod:`clue_research.discovery_scoring.phases`.
"""

from __future__ import annotations

from clue_research.discovery_scoring.tiering.config import (
    DEFAULT_TIERING_CONFIG,
    TieringConfig,
)
from clue_research.discovery_scoring.tiering.engine import (
    ACCOUNT_RESEARCH_ELIGIBLE_TIERS,
    TIER_CLAIM_MAX_SOURCE_TIER,
    TIER_FIELD,
    assign_tiers,
    cutoff_version,
    estimate_cost,
    load_score_views,
    persist_discovery_selection_tier,
    persist_tier,
    tier_distribution,
)
from clue_research.discovery_scoring.tiering.results import (
    CHECKPOINT_DECISION_PARAM,
    AccountScoreView,
    AccountTierView,
    CheckpointAction,
    CheckpointDecision,
    CheckpointReview,
    CheckpointStatus,
    DiscoveryCriteriaCheckpointReview,
    TierAssignment,
)
from clue_research.discovery_scoring.tiering.selection import (
    DiscoveryCriteriaAccountView,
    DiscoveryCriteriaSelection,
    DiscoverySelectionDisposition,
    DiscoverySelectionPolicy,
    ScoringMode,
    SelectionMode,
    classify_required_criteria_claims,
    load_discovery_criteria_selection,
    selection_decision_version,
)

__all__ = [
    # pure tiering + estimate
    "assign_tiers",
    "tier_distribution",
    "estimate_cost",
    "cutoff_version",
    # store read / write
    "load_score_views",
    "persist_tier",
    "persist_discovery_selection_tier",
    "TIER_FIELD",
    "ACCOUNT_RESEARCH_ELIGIBLE_TIERS",
    "TIER_CLAIM_MAX_SOURCE_TIER",
    # results + decision
    "AccountScoreView",
    "AccountTierView",
    "TierAssignment",
    "CheckpointReview",
    "CheckpointDecision",
    "CheckpointAction",
    "CheckpointStatus",
    "DiscoveryCriteriaCheckpointReview",
    "DiscoveryCriteriaAccountView",
    "DiscoveryCriteriaSelection",
    "DiscoverySelectionDisposition",
    "DiscoverySelectionPolicy",
    "ScoringMode",
    "SelectionMode",
    "classify_required_criteria_claims",
    "load_discovery_criteria_selection",
    "selection_decision_version",
    "CHECKPOINT_DECISION_PARAM",
    # config
    "TieringConfig",
    "DEFAULT_TIERING_CONFIG",
]
