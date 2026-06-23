"""``clue_research.api.deep`` — campaign-run deep orchestration (M8A).

The composition-layer package that sequences the M8 deep-research worker families per high-tier
account (``account → committee → contact``) under the M7 durable substrate — the milestone
that makes Pass B run end-to-end. It is the one home the import-linter independence contract permits
for work that co-composes ``durable`` + ``profiling`` (+ ``verification`` at M8A.6), since only the
``api`` composition root is import-exempt.

M8A.1 ships the trunk — :class:`AccountDeepOrchestrator` (the per-account sequence, resumable on the
M8A.0 ``account_run.sub_phase`` marker) + its injectable :class:`AccountRunIO` cursor seam. M8A.2
adds :class:`DeepPhaseHandler` — the ``CampaignPhase.DEEP`` handler that resolves the high-tier set
and drives the scheduler with the orchestrator bound as the per-account callback. M8A.3 adds the
fan-out budget admission in the contact loop. M8A.4 adds exactly-once spend
(:class:`ExactlyOnceSpend` / :class:`DbExactlyOnceSpend`): each stage's claim writes + charge +
ledger ``succeed`` commit in one transaction, with a concurrent-admit reservation. M8A.5 adds the
references-only handoff skeleton (:func:`build_handoff_skeleton`) that proves an account is
M12-ready. The composition root that injects the concretes (M8A.6) builds against these interfaces.
"""

from __future__ import annotations

from clue_research.api.deep.composition import (
    DeepPhaseComposition,
    build_account_axis_registry,
    build_deep_phase_handler,
    build_high_tier_resolver,
    load_research_packs,
    register_deep_phase_handler,
)
from clue_research.api.deep.handler import (
    CheckpointerFactory,
    DeepAccountOrchestrator,
    DeepAccountScheduler,
    DeepPhaseHandler,
    FinalizeFailedAccount,
    HighTierResolver,
    db_finalize_failed_account,
)
from clue_research.api.deep.handoff_skeleton import (
    AccountHandoffSkeleton,
    DeepCompleteManifest,
    build_handoff_skeleton,
)
from clue_research.api.deep.orchestrator import (
    AccountDeepOrchestrator,
    AccountDeepResult,
    DiscoverCommitteeFn,
    ProfileAccountFn,
    ProfileContactFn,
    deep_account_run_id,
)
from clue_research.api.deep.run_io import (
    AccountRunIO,
    DbAccountRunIO,
    DeepRunState,
)
from clue_research.api.deep.spend import (
    DbExactlyOnceSpend,
    ExactlyOnceSpend,
    Spendable,
    StepInfo,
    already_done,
    deep_step_key,
)

__all__ = [
    # the per-account orchestrator trunk (M8A.1)
    "AccountDeepOrchestrator",
    "AccountDeepResult",
    "deep_account_run_id",
    "ProfileAccountFn",
    "DiscoverCommitteeFn",
    "ProfileContactFn",
    # the account_run persistence seam (M8A.1)
    "AccountRunIO",
    "DbAccountRunIO",
    "DeepRunState",
    # exactly-once spend (M8A.4)
    "ExactlyOnceSpend",
    "DbExactlyOnceSpend",
    "Spendable",
    "StepInfo",
    "already_done",
    "deep_step_key",
    # the CampaignPhase.DEEP handler (M8A.2)
    "DeepPhaseHandler",
    "HighTierResolver",
    "CheckpointerFactory",
    "FinalizeFailedAccount",
    "DeepAccountScheduler",
    "DeepAccountOrchestrator",
    "db_finalize_failed_account",
    # the references-only handoff skeleton (M8A.5)
    "AccountHandoffSkeleton",
    "DeepCompleteManifest",
    "build_handoff_skeleton",
    # the DEEP-phase composition root (M8A.6)
    "DeepPhaseComposition",
    "build_deep_phase_handler",
    "register_deep_phase_handler",
    "build_high_tier_resolver",
    "build_account_axis_registry",
    "load_research_packs",
]
