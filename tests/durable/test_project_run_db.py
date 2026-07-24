"""DB-gated tests for the M7.3 persistence path — ``project_run`` / ``project_phase_checkpoint`` /
``adjustment_journal``.

These need a reachable, migrated Postgres and ``pytest.skip`` without one. They cover: the three
enum parities (``project_phase`` vs the *core* :class:`ProjectPhase`; the two durable-internal
lifecycle enums), the ``project_run`` repository round-trip + the granular setters, the checkpoint
upsert + read-back with its ``committed_at`` invariant, and the append-only ``adjustment_journal``
(insert/list + the immutability trigger). Repo calls run inside a rolled-back transaction, so no
committed rows leak.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectPhase, new_project_run_id
from clue_core.idempotency import phase_key
from clue_research.durable import (
    PhaseCheckpointStatus,
    ProjectRunStatus,
    ensure_project_run,
    get_checkpoint,
    get_project_run,
    insert_adjustment,
    list_adjustments,
    upsert_checkpoint,
)
from clue_research.durable.project_run import (
    ProjectRunIdentityConflict,
    ProjectRunProjectNotFound,
    set_budget_cap,
    set_icp_version,
    set_phase,
    set_run_status,
    set_tier_cutoffs,
)
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")


async def _enum_labels(conn: AsyncConnection, typname: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = :t ORDER BY e.enumsortorder"
        ),
        {"t": typname},
    )
    return [r[0] for r in rows.all()]


def test_project_phase_enum_matches_core() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "project_phase")
        assert labels == [p.value for p in ProjectPhase]

    run_async(_run())


def test_project_run_status_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "project_run_status")
        assert labels == [s.value for s in ProjectRunStatus]

    run_async(_run())


def test_phase_checkpoint_status_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "phase_checkpoint_status")
        assert labels == [s.value for s in PhaseCheckpointStatus]

    run_async(_run())


def test_project_run_round_trip() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "client-1")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="client-1",
                icp_key="default",
                icp_version=3,
                budget_cap_cents=Decimal("50000"),
                tier_cutoffs={"top": 0.8, "high": 0.6},
            )
            row = await get_project_run(conn, run_id)
        assert row is not None
        assert row.id == run_id
        assert row.project_id == project.project_id
        assert row.brand_id == project.brand_id
        assert row.workspace_id == "client-1"
        assert row.icp_key == "default"
        assert row.icp_version == 3
        assert row.phase is ProjectPhase.REVERSE_PROFILING  # default first phase
        assert row.status is ProjectRunStatus.ACTIVE  # default
        assert row.budget_cap_cents == Decimal("50000")
        assert row.spent_cents == Decimal(0)
        assert row.tier_cutoffs == {"top": 0.8, "high": 0.6}
        assert row.paused_at is None and row.resumed_at is None

    run_async(_run())


def test_ensure_project_run_is_idempotent() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            # a second ensure with different data is a no-op (ON CONFLICT DO NOTHING)
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="other",
                icp_version=9,
            )
            row = await get_project_run(conn, run_id)
        assert row is not None
        assert row.workspace_id == "a"  # the first write stands
        assert row.icp_version == 1

    run_async(_run())


def test_ensure_project_run_rejects_missing_or_foreign_project() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "owner")
            with pytest.raises(ProjectRunProjectNotFound, match="not found in workspace"):
                await ensure_project_run(
                    conn,
                    project_run_id=new_project_run_id(),
                    project_id="prj_missing",
                    workspace_id="owner",
                    icp_key="k",
                    icp_version=1,
                )
            with pytest.raises(ProjectRunProjectNotFound, match="not found in workspace"):
                await ensure_project_run(
                    conn,
                    project_run_id=new_project_run_id(),
                    project_id=project.project_id,
                    workspace_id="other",
                    icp_key="k",
                    icp_version=1,
                )

    run_async(_run())


def test_ensure_project_run_rejects_idempotency_key_context_drift() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            first = await seed_project(conn, "a", name="First")
            second = await seed_project(conn, "a", name="Second")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=first.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            with pytest.raises(ProjectRunIdentityConflict, match="already belongs"):
                await ensure_project_run(
                    conn,
                    project_run_id=run_id,
                    project_id=second.project_id,
                    workspace_id="a",
                    icp_key="k",
                    icp_version=1,
                )

    run_async(_run())


def test_setters_update_run_fields() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            await set_phase(conn, run_id, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE)
            await set_run_status(conn, run_id, status=ProjectRunStatus.PAUSED, stamp_paused=True)
            await set_icp_version(conn, run_id, 4)
            await set_budget_cap(conn, run_id, Decimal("99999"))
            await set_tier_cutoffs(conn, run_id, {"top": 0.95})
            row = await get_project_run(conn, run_id)
        assert row is not None
        assert row.phase is ProjectPhase.DEEP
        assert row.status is ProjectRunStatus.PAUSED
        assert row.paused_at is not None
        assert row.icp_version == 4
        assert row.budget_cap_cents == Decimal("99999")
        assert row.tier_cutoffs == {"top": 0.95}

    run_async(_run())


def test_checkpoint_upsert_read_back_and_committed_at_invariant() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        phase = ProjectPhase.TIER_CHECKPOINT
        key = phase_key(run_id, phase)
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            # stage in_progress → committed_at is NULL
            await upsert_checkpoint(
                conn,
                project_run_id=run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.IN_PROGRESS,
                payload={},
            )
            staged = await get_checkpoint(conn, run_id, phase)
            assert staged is not None
            assert staged.status is PhaseCheckpointStatus.IN_PROGRESS
            assert staged.committed_at is None
            assert staged.idempotency_key == key

            # suspend at the human gate → payload carried, still not committed
            review = {"proposed_cutoffs": {"top": 0.8}, "tier_distribution": {"top": 12}}
            await upsert_checkpoint(
                conn,
                project_run_id=run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.AWAITING_INPUT,
                payload=review,
            )
            awaiting = await get_checkpoint(conn, run_id, phase)
            assert awaiting is not None
            assert awaiting.status is PhaseCheckpointStatus.AWAITING_INPUT
            assert awaiting.committed_at is None
            assert awaiting.payload == review  # the M6↔M7 read-back payload round-trips
            assert awaiting.id == staged.id  # same row (UNIQUE on (run, phase))

            # commit → committed_at is stamped (the iff invariant)
            await upsert_checkpoint(
                conn,
                project_run_id=run_id,
                phase=phase,
                idempotency_key=key,
                status=PhaseCheckpointStatus.COMMITTED,
                payload={**review, "decision": {"action": "approve"}},
            )
            committed = await get_checkpoint(conn, run_id, phase)
            assert committed is not None
            assert committed.status is PhaseCheckpointStatus.COMMITTED
            assert committed.committed_at is not None
            assert committed.payload["decision"] == {"action": "approve"}
            assert committed.id == staged.id  # still one row

            # exactly one checkpoint row for this (run, phase)
            count = await conn.execute(
                text(
                    "SELECT count(*) FROM project_phase_checkpoint "
                    "WHERE project_run_id = :r AND phase = CAST(:p AS project_phase)"
                ),
                {"r": run_id, "p": phase.value},
            )
            assert count.scalar_one() == 1

    run_async(_run())


def test_checkpoints_for_distinct_phases_coexist() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            for phase in (ProjectPhase.DISCOVERY, ProjectPhase.SCORING):
                await upsert_checkpoint(
                    conn,
                    project_run_id=run_id,
                    phase=phase,
                    idempotency_key=phase_key(run_id, phase),
                    status=PhaseCheckpointStatus.COMMITTED,
                    payload={"phase": phase.value},
                )
            discovery = await get_checkpoint(conn, run_id, ProjectPhase.DISCOVERY)
            scoring = await get_checkpoint(conn, run_id, ProjectPhase.SCORING)
        assert discovery is not None and discovery.payload == {"phase": "discovery"}
        assert scoring is not None and scoring.payload == {"phase": "scoring"}

    run_async(_run())


def test_adjustment_journal_append_and_list_order() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            await insert_adjustment(
                conn, project_run_id=run_id, kind="icp_version", detail={"icp_version": 2}
            )
            await insert_adjustment(
                conn,
                project_run_id=run_id,
                kind="budget_cap",
                detail={"budget_cap_cents": "100000"},
            )
            rows = await list_adjustments(conn, run_id)
        assert [r.kind for r in rows] == ["icp_version", "budget_cap"]
        assert rows[0].detail == {"icp_version": 2}
        assert rows[1].detail == {"budget_cap_cents": "100000"}

    run_async(_run())


def test_adjustment_journal_is_immutable() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            await insert_adjustment(
                conn, project_run_id=run_id, kind="icp_version", detail={"icp_version": 2}
            )
            # the append-only trigger rejects any UPDATE
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(
                    text("UPDATE adjustment_journal SET kind = 'x' WHERE project_run_id = :r"),
                    {"r": run_id},
                )

    run_async(_run())


def test_adjustment_journal_rejects_delete() -> None:
    async def _run() -> None:
        run_id = new_project_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "a")
            await ensure_project_run(
                conn,
                project_run_id=run_id,
                project_id=project.project_id,
                workspace_id="a",
                icp_key="k",
                icp_version=1,
            )
            await insert_adjustment(
                conn, project_run_id=run_id, kind="icp_version", detail={"icp_version": 2}
            )
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(
                    text("DELETE FROM adjustment_journal WHERE project_run_id = :r"),
                    {"r": run_id},
                )

    run_async(_run())
