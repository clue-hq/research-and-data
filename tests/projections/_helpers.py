"""Shared seed + wiring helpers for the B4 read-side projection tests (PB-B4 slice 3)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.observability_wiring import build_observability_surface
from clue_core import (
    EntityId,
    ProjectPhase,
    ProjectRunId,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.durable import (
    AccountRunStatus,
    BudgetEngine,
    DbBudgetStore,
    PhaseCheckpointStatus,
    ProjectRunStatus,
    ensure_project_run,
    insert_account_run,
    upsert_checkpoint,
)
from clue_research.review import ObservabilitySurface
from tests._workspace import seed_project
from tests.profiling.conftest import conn_session_factory


def build_surface(conn: AsyncConnection) -> ObservabilitySurface:
    """An M13.4 observability surface bound to the test's rolled-back connection (the durable-backed
    readers + a BudgetEngine over the same connection)."""
    cf = conn_session_factory(conn)
    return build_observability_surface(
        budget=BudgetEngine(store=DbBudgetStore(conn_factory=cf)), conn_factory=cf
    )


async def seed_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId | None = None,
    icp_key: str = "default",
    icp_version: int = 1,
    phase: ProjectPhase = ProjectPhase.REVERSE_PROFILING,
    status: ProjectRunStatus = ProjectRunStatus.ACTIVE,
    budget_cap_cents: Decimal | None = None,
) -> ProjectRunId:
    """Seed a ``project_run`` row and return its id."""
    run_id = project_run_id if project_run_id is not None else new_project_run_id()
    project = await seed_project(conn, workspace_id)
    await ensure_project_run(
        conn,
        project_run_id=run_id,
        project_id=project.project_id,
        workspace_id=workspace_id,
        icp_key=icp_key,
        icp_version=icp_version,
        phase=phase,
        status=status,
        budget_cap_cents=budget_cap_cents,
    )
    return run_id


async def seed_checkpoint(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    phase: ProjectPhase,
    status: PhaseCheckpointStatus = PhaseCheckpointStatus.COMMITTED,
    payload: dict | None = None,
) -> None:
    """Seed a ``project_phase_checkpoint`` row (e.g. the HANDOFF gap-marker payload)."""
    await upsert_checkpoint(
        conn,
        project_run_id=project_run_id,
        phase=phase,
        idempotency_key=f"{project_run_id}:{phase.value}",
        status=status,
        payload=payload if payload is not None else {},
    )


async def seed_account_run(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    entity_id: EntityId | None = None,
    tier: str = "top",
    status: AccountRunStatus = AccountRunStatus.DONE,
) -> EntityId:
    """Seed an ``account_run`` row under a project run and return its entity id."""
    eid = entity_id if entity_id is not None else new_entity_id()
    await insert_account_run(
        conn,
        account_run_id=new_run_id(),
        project_run_id=project_run_id,
        entity_id=eid,
        tier=tier,
        status=status,
    )
    return eid
