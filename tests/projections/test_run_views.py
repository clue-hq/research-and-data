"""B4 slice-3 — the ``clue_projections`` run views over a live (DB-seeded) run.

Covers the slice exit gates that live at the projection layer:

* ``run_overview`` surfaces the HANDOFF **``narrative_emit_skipped``** gap marker (spec §2 slice-3
  amendment / slice-1 review #10) — a gap-completed run is distinguishable from a truly-handed-off
  one, built from the exact checkpoint payload the slice-1 ``_NarrativeGapHandoffHandler`` writes.
* the accounts-by-state histogram + per-account progress (filled-vs-planned aspects).
* the readiness projection tallies.
* tenant scoping — a cross-tenant run resolves to ``None`` everywhere (fail-closed, no leak).
* **projection reads issue no writes** — asserted by diffing the DB's row-modification counters
  across every projection read (the D7 MVCC-only discipline).

DB-backed (skips without one); every test runs inside an always-rolled-back transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectPhase, new_entity_id, new_project_run_id
from clue_projections import account_progress, run_overview, run_readiness
from clue_research.durable import (
    NARRATIVE_EMIT_SKIPPED_KEY,
    AccountRunStatus,
    PhaseCheckpointStatus,
    save_plan,
    save_references,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.projections._helpers import (
    build_surface,
    seed_account_run,
    seed_checkpoint,
    seed_run,
)

_WS = "ws-acme"
_OTHER = "ws-other"

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _commit_all_phases(conn: AsyncConnection, run_id, *, handoff_payload: dict) -> None:
    """Commit a checkpoint for every phase (the shape a completed drive leaves), the HANDOFF one
    carrying ``handoff_payload`` — exactly what the slice-1 composer's gap handler writes."""
    for phase in ProjectPhase:
        await seed_checkpoint(
            conn,
            project_run_id=run_id,
            phase=phase,
            status=PhaseCheckpointStatus.COMMITTED,
            payload=handoff_payload if phase == ProjectPhase.HANDOFF else {},
        )


def test_run_overview_surfaces_narrative_emit_skipped_for_gap_completed_run() -> None:
    """THE amendment gate: a run whose HANDOFF checkpoint carries the slice-1 gap marker
    (``narrative_emit_skipped: true`` — the ``_NarrativeGapHandoffHandler`` payload) surfaces it in
    the run projection; a truly-handed-off run (no marker) reads ``False``."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            surface = build_surface(conn)
            cf = conn_session_factory(conn)
            # The gap-completed run: the exact payload run_composition._NarrativeGapHandoffHandler
            # writes (narrative_emit_skipped + reason).
            gap_run = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.HANDOFF)
            await _commit_all_phases(
                conn,
                gap_run,
                handoff_payload={
                    NARRATIVE_EMIT_SKIPPED_KEY: True,
                    "reason": "no production HandoffCommitteeReader",
                },
            )
            # The truly-handed-off run: a HANDOFF checkpoint with no gap marker.
            real_run = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.HANDOFF)
            await _commit_all_phases(conn, real_run, handoff_payload={"emitted": 3})

            gap_view = await run_overview(
                surface=surface, conn_factory=cf, project_run_id=gap_run, workspace_id=_WS
            )
            real_view = await run_overview(
                surface=surface, conn_factory=cf, project_run_id=real_run, workspace_id=_WS
            )
        assert gap_view is not None and real_view is not None
        assert gap_view.handoff_reached and real_view.handoff_reached
        assert gap_view.narrative_emit_skipped is True
        assert real_view.narrative_emit_skipped is False
        # The two runs are distinguishable by exactly this flag.
        assert gap_view.narrative_emit_skipped != real_view.narrative_emit_skipped

    run_async(_run())


def test_run_overview_accounts_by_state_and_phases() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            surface = build_surface(conn)
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.DEEP)
            await seed_account_run(conn, project_run_id=run_id, status=AccountRunStatus.DONE)
            await seed_account_run(conn, project_run_id=run_id, status=AccountRunStatus.RUNNING)
            await seed_account_run(conn, project_run_id=run_id, status=AccountRunStatus.RUNNING)
            view = await run_overview(
                surface=surface, conn_factory=cf, project_run_id=run_id, workspace_id=_WS
            )
        assert view is not None
        assert view.current_phase == ProjectPhase.DEEP
        assert view.accounts_total == 3
        assert view.accounts_by_state == {"done": 1, "running": 2}
        assert len(view.phases) == len(ProjectPhase)
        assert view.narrative_emit_skipped is False  # no HANDOFF checkpoint yet
        assert not view.handoff_reached

    run_async(_run())


def test_account_progress_filled_vs_planned() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.DEEP)
            entity = new_entity_id()
            from clue_core import new_run_id
            from clue_research.durable import insert_account_run

            account_run_id = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=account_run_id,
                project_run_id=run_id,
                entity_id=entity,
                tier="top",
                status=AccountRunStatus.RUNNING,
            )
            await save_plan(
                conn,
                account_run_id,
                plan_json={
                    "aspects": [
                        {"aspect": "operational_pain", "field_keys": ["a.x"]},
                        {"aspect": "resonance", "field_keys": ["a.y"]},
                        {"aspect": "strategic_moves", "field_keys": ["a.z"]},
                    ]
                },
                status=AccountRunStatus.RUNNING,
            )
            await save_references(
                conn,
                account_run_id,
                references_index={
                    "operational_pain": ["11111111-1111-1111-1111-111111111111"],
                    "resonance": [],
                },
                cost_cents=0,
                status=AccountRunStatus.DONE,
            )
            view = await account_progress(
                conn_factory=cf,
                project_run_id=run_id,
                workspace_id=_WS,
                account_entity_id=entity,
            )
        assert view is not None
        assert view.aspects_planned == 3
        assert view.aspects_filled == 1
        assert view.filled_aspects == ("operational_pain",)
        assert view.claim_count == 1
        assert view.status == "done"
        assert view.tier == "top"

    run_async(_run())


def test_readiness_tallies_across_accounts() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            surface = build_surface(conn)
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.DEEP)
            await seed_account_run(conn, project_run_id=run_id, status=AccountRunStatus.DONE)
            await seed_account_run(conn, project_run_id=run_id, status=AccountRunStatus.PENDING)
            view = await run_readiness(
                surface=surface, conn_factory=cf, project_run_id=run_id, workspace_id=_WS
            )
        assert view is not None
        assert len(view.accounts) == 2
        # No plans/references seeded → zero tallies, honestly reported (never fabricated).
        assert view.aspects_planned_total == 0
        assert view.aspects_filled_total == 0
        assert view.coverage is None  # no tier-checkpoint coverage payload → honest None

    run_async(_run())


def test_cross_tenant_resolves_to_none_everywhere() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            surface = build_surface(conn)
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS)
            entity = await seed_account_run(conn, project_run_id=run_id)
            assert (
                await run_overview(
                    surface=surface, conn_factory=cf, project_run_id=run_id, workspace_id=_OTHER
                )
                is None
            )
            assert (
                await account_progress(
                    conn_factory=cf,
                    project_run_id=run_id,
                    workspace_id=_OTHER,
                    account_entity_id=entity,
                )
                is None
            )
            assert (
                await run_readiness(
                    surface=surface, conn_factory=cf, project_run_id=run_id, workspace_id=_OTHER
                )
                is None
            )
            # A missing run is indistinguishable from a cross-tenant one.
            assert (
                await run_overview(
                    surface=surface,
                    conn_factory=cf,
                    project_run_id=new_project_run_id(),
                    workspace_id=_WS,
                )
                is None
            )

    run_async(_run())


async def _row_write_counter(conn: AsyncConnection) -> int:
    """The DB-wide row-modification counter (inserts+updates+deletes across user tables) — the
    write-detection surface for the no-writes gate. Read within the open transaction so any write
    this transaction performed is already visible in pg_stat_xact_* (transaction-local counters)."""
    return (
        await conn.execute(
            text(
                "SELECT COALESCE(SUM(n_tup_ins + n_tup_upd + n_tup_del), 0) "
                "FROM pg_stat_xact_user_tables"
            )
        )
    ).scalar_one()


def test_projection_reads_issue_no_writes() -> None:
    """D7 exit gate: every projection read is MVCC-only — the transaction-local row-modification
    counters do not move across the full set of projection reads."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            surface = build_surface(conn)
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.HANDOFF)
            entity = await seed_account_run(conn, project_run_id=run_id)
            await seed_checkpoint(
                conn,
                project_run_id=run_id,
                phase=ProjectPhase.HANDOFF,
                payload={"narrative_emit_skipped": True},
            )
            from clue_projections import run_manifest

            before = await _row_write_counter(conn)
            assert (
                await run_overview(
                    surface=surface, conn_factory=cf, project_run_id=run_id, workspace_id=_WS
                )
                is not None
            )
            assert (
                await account_progress(
                    conn_factory=cf,
                    project_run_id=run_id,
                    workspace_id=_WS,
                    account_entity_id=entity,
                )
                is not None
            )
            assert (
                await run_readiness(
                    surface=surface, conn_factory=cf, project_run_id=run_id, workspace_id=_WS
                )
                is not None
            )
            assert (
                await run_manifest(conn_factory=cf, project_run_id=run_id, workspace_id=_WS)
                is not None
            )
            after = await _row_write_counter(conn)
        assert after == before, (
            "a projection read modified rows — the D7 read-only discipline broke"
        )

    run_async(_run())
