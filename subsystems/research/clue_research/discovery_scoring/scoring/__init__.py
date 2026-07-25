"""Pass-A scoring engine (M6.3 / ENG-138).

Output 1: a decomposed, explainable, provenance-backed **fit + intent** score for every admitted
account, computed cheaply and deterministically (tiers 1–3, no LLM). The scoring math is M3.4's
(``icp.rubric``); this package is the Pass-A orchestration over the substrate — fill the ICP's
scoring proxies via the waterfall, score, persist the score object (two tenant-private claims on the
reserved ``account.scoring.fit`` / ``.intent`` fields) idempotently, and emit per-source yield. The
integrated ``SCORING`` :class:`PhaseHandler` lives in :mod:`clue_research.discovery_scoring.phases`.

Public seam:
* :func:`score_account` — fill + score + persist one account (``-> AccountScoringOutcome``).
* :func:`admitted_account_ids` — the campaign's admitted score set (store-derived).
* :func:`pass_a_fill_fields` — the tier-capped scoring proxies to fill (deterministic-first).
* :func:`aggregate_yield` — fold per-account yield into the run's per-source telemetry.
* :class:`AccountScore` / :class:`AccountScoringOutcome` / :class:`SourceYieldRow` — the results.
* :class:`ScoringConfig` — the run-shape policy (the no-tier-4 guard).
"""

from __future__ import annotations

from clue_research.discovery_scoring.scoring.config import (
    DEFAULT_SCORING_CONFIG,
    ScoringConfig,
)
from clue_research.discovery_scoring.scoring.engine import (
    FIT_FIELD,
    INTENT_FIELD,
    admitted_account_ids,
    aggregate_yield,
    pass_a_fill_fields,
    score_account,
)
from clue_research.discovery_scoring.scoring.results import (
    AccountScore,
    AccountScoringOutcome,
    SourceYieldRow,
)

__all__ = [
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
]
