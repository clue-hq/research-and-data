"""`clue_research.durable` — Durable Execution (M7).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M7.

Beat-0 froze this package's cross-milestone seam in ``core`` (see
``docs/specs/_beat0-contract-freeze.md``): M7 *implements* the ``PhaseHandler`` dispatch,
``AspectWorker`` spawning and ``BudgetEngine`` from :mod:`clue_research.core.execution`, and uses
the pure key helpers in :mod:`clue_research.core.idempotency`. It imports those contracts from
``core``, never the phase packages — concrete handlers are registered at the ``api`` root.

**M7.1 (ENG-131) — per-account orchestrator-worker graph.** :class:`AccountResearchGraph` runs one
LangGraph orchestrator-worker graph per account (``plan → fan_out → collect → handoff``) with
``AsyncPostgresSaver`` checkpointing; aspect workers (the :class:`~clue_research.core.AspectWorker`
contract, bodies owned by M8) write claims and return *references only*. The ``account_run`` table
is the resumable execution cursor whose id is the ``claim.run_id`` provenance.
"""

from __future__ import annotations

from clue_research.durable.account_run import (
    AccountRunRow,
    ReferencesIndex,
    ensure_account_run,
    get_account_run,
    insert_account_run,
    save_plan,
    save_references,
    set_status,
)
from clue_research.durable.enums import AccountRunStatus
from clue_research.durable.graph import (
    AccountResearchGraph,
    AccountRunResult,
    AccountRunStore,
    DbAccountRunStore,
    postgres_checkpointer,
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
from clue_research.durable.workers import (
    WorkerRegistry,
    default_worker_registry,
    register_aspect_worker,
)

__all__ = [
    # enums
    "AccountRunStatus",
    # account_run repository
    "AccountRunRow",
    "ReferencesIndex",
    "insert_account_run",
    "ensure_account_run",
    "get_account_run",
    "save_plan",
    "save_references",
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
    # the graph
    "AccountResearchGraph",
    "AccountRunResult",
    "AccountRunStore",
    "DbAccountRunStore",
    "postgres_checkpointer",
]
