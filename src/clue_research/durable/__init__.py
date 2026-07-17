"""`clue_research.durable` — Durable Execution (M7).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M7.

Beat-0 froze this package's cross-milestone seam in ``core`` (see
``docs/specs/_beat0-contract-freeze.md``): M7 *implements* the ``PhaseHandler`` dispatch,
``AspectWorker`` spawning and ``BudgetEngine`` from :mod:`clue_core.execution`, and uses
the pure key helpers in :mod:`clue_core.idempotency`. It imports those contracts from
``core``, never the phase packages — concrete handlers are registered at the ``api`` root.

**M7.1 (ENG-131) — per-account orchestrator-worker graph.** :class:`AccountResearchGraph` runs one
LangGraph orchestrator-worker graph per account (``plan → fan_out → collect → handoff``) with
``AsyncPostgresSaver`` checkpointing; aspect workers (the :class:`~clue_core.AspectWorker`
contract, bodies owned by M8) write claims and return *references only*. The ``account_run`` table
is the resumable execution cursor whose id is the ``claim.run_id`` provenance.
"""

from __future__ import annotations

from clue_research.durable.account_run import (
    AccountRunRow,
    ReferencesIndex,
    ensure_account_run,
    fold_references,
    get_account_run,
    insert_account_run,
    list_account_runs,
    save_plan,
    save_references,
    set_account_sub_phase,
    set_status,
)
from clue_research.durable.budget import (
    BudgetEngine,
    BudgetError,
    BudgetStateNotFound,
    BudgetStore,
    DbBudgetStore,
    project_spend,
)
from clue_research.durable.budget_event import (
    AccountBudgetState,
    BudgetEventRow,
    RunBudgetState,
    add_account_spend,
    add_run_spend,
    get_account_budget_state,
    get_run_budget_state,
    insert_budget_event,
    list_budget_events,
    set_account_budget_cap,
    set_estimated_cents,
)
from clue_research.durable.campaign import (
    PHASE_SEQUENCE,
    BudgetEngineNotConfigured,
    CampaignRun,
    CampaignRunError,
    CampaignRunNotFound,
    CampaignRunStore,
    CheckpointNotAwaiting,
    DbCampaignRunStore,
    NoPhaseHandlerRegistered,
    next_phase,
)
from clue_research.durable.campaign_run import (
    AdjustmentRow,
    CampaignPhaseCheckpointRow,
    CampaignRunRow,
    TierCutoffs,
    ensure_campaign_run,
    get_campaign_run,
    get_checkpoint,
    insert_adjustment,
    list_adjustments,
    upsert_checkpoint,
)
from clue_research.durable.enums import (
    AccountRunStatus,
    AccountRunSubPhase,
    BudgetEventKind,
    CampaignRunStatus,
    IdempotencyStatus,
    PhaseCheckpointStatus,
)
from clue_research.durable.graph import (
    AccountResearchGraph,
    AccountRunResult,
    AccountRunStore,
    DbAccountRunStore,
    postgres_checkpointer,
)
from clue_research.durable.idempotency import (
    DEFAULT_STALE_AFTER,
    ClaimOutcome,
    ClaimResult,
    DbIdempotencyStore,
    IdempotencyConflict,
    IdempotencyLedgerRow,
    IdempotencyStore,
    IdempotentStep,
    claim_idempotency_step,
    finish_idempotency_step,
    get_idempotency_ledger,
    idempotent,
    retry_async,
)
from clue_research.durable.phases import (
    PhaseHandlerRegistry,
    default_phase_handler_registry,
    register_phase_handler,
)
from clue_research.durable.planning import (
    AspectPlan,
    ResearchPlan,
    build_plan,
    compute_gap_fields,
)
from clue_research.durable.recursion import (
    SpawnDecision,
    SpawnDenyReason,
    SpawnGuard,
)
from clue_research.durable.scheduler import (
    AccountScheduler,
    AccountSpec,
    LockFactory,
    RunOne,
    account_entity_lock_factory,
)
from clue_research.durable.workers import (
    WorkerRegistry,
    default_worker_registry,
    register_aspect_worker,
)

__all__ = [
    # enums
    "AccountRunStatus",
    "AccountRunSubPhase",
    "CampaignRunStatus",
    "PhaseCheckpointStatus",
    "IdempotencyStatus",
    "BudgetEventKind",
    # idempotency ledger + context manager (M7.4)
    "idempotent",
    "IdempotencyStore",
    "DbIdempotencyStore",
    "IdempotencyLedgerRow",
    "IdempotencyConflict",
    "IdempotentStep",
    "ClaimResult",
    "ClaimOutcome",
    "DEFAULT_STALE_AFTER",
    "claim_idempotency_step",
    "finish_idempotency_step",
    "get_idempotency_ledger",
    "retry_async",
    # account_run repository
    "AccountRunRow",
    "ReferencesIndex",
    "insert_account_run",
    "ensure_account_run",
    "fold_references",
    "get_account_run",
    "list_account_runs",
    "save_plan",
    "save_references",
    "set_account_sub_phase",
    "set_status",
    # planning (orchestrator/lead)
    "AspectPlan",
    "ResearchPlan",
    "build_plan",
    "compute_gap_fields",
    # bounded recursion knob (M7.2)
    "SpawnGuard",
    "SpawnDecision",
    "SpawnDenyReason",
    # worker registry
    "WorkerRegistry",
    "default_worker_registry",
    "register_aspect_worker",
    # the per-account graph (M7.1/M7.2)
    "AccountResearchGraph",
    "AccountRunResult",
    "AccountRunStore",
    "DbAccountRunStore",
    "postgres_checkpointer",
    # campaign-run state machine (M7.3)
    "CampaignRun",
    "CampaignRunStore",
    "DbCampaignRunStore",
    "PHASE_SEQUENCE",
    "next_phase",
    "CampaignRunError",
    "CampaignRunNotFound",
    "NoPhaseHandlerRegistered",
    "CheckpointNotAwaiting",
    "BudgetEngineNotConfigured",
    # campaign_run / checkpoint / journal repository (M7.3)
    "CampaignRunRow",
    "CampaignPhaseCheckpointRow",
    "AdjustmentRow",
    "TierCutoffs",
    "ensure_campaign_run",
    "get_campaign_run",
    "get_checkpoint",
    "upsert_checkpoint",
    "insert_adjustment",
    "list_adjustments",
    # phase-handler registry (M7.3)
    "PhaseHandlerRegistry",
    "default_phase_handler_registry",
    "register_phase_handler",
    # deep-phase scheduler (M7.3)
    "AccountScheduler",
    "AccountSpec",
    "LockFactory",
    "RunOne",
    "account_entity_lock_factory",
    # budget caps & cost-governance engine (M7.5)
    "BudgetEngine",
    "BudgetStore",
    "DbBudgetStore",
    "BudgetError",
    "BudgetStateNotFound",
    "project_spend",
    # budget_event / cost-accounting repository (M7.5)
    "BudgetEventRow",
    "RunBudgetState",
    "AccountBudgetState",
    "insert_budget_event",
    "list_budget_events",
    "get_run_budget_state",
    "get_account_budget_state",
    "add_run_spend",
    "add_account_spend",
    "set_estimated_cents",
    "set_account_budget_cap",
]
