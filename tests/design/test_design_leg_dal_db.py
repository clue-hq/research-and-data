"""P3.1 acceptance: the design-leg DAL (PD-part3 §2.1).

The leg row IS the materialized HITL state (ruling D1): these pin the state machine
(open_awaiting_user ⇄ running → closed(reason) → reopen), the at-most-one-open-leg-per-
thread invariant (D4's routing key), the engine-disposes exit shape (out_of_scope requires
a pending message ref), and the append-only exit journal that survives reopens.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import legs as design_legs
from clue_design.errors import DesignLegStateError
from tests._workspace import seed_project
from tests.design.conftest import run_async


async def _seed_thread_and_execution(conn: AsyncConnection) -> dict[str, Any]:
    ws = f"ws_test_leg_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="Leg DAL")
    thread_id = f"thr_leg_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": ws, "project": project.project_id},
    )
    execution_id = uuid5(NAMESPACE_URL, f"leg-dal:{ws}")
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :project, 'agent', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "project": project.project_id, "hash": "0" * 64},
    )
    return {"ws": ws, "thread_id": thread_id, "execution_id": execution_id}


def test_open_leg_roundtrip_and_open_lookup(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed_thread_and_execution(conn)
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
                brand_kit_id="brand_kit_x",
                brand_kit_version=3,
                document_id="doc_1",
                document_version_guard=7,
            )
            assert leg["state"] == "open_awaiting_user"
            found = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=seeds["ws"], thread_id=seeds["thread_id"]
            )
            assert found is not None and found["id"] == leg["id"]
            assert found["brand_kit_version"] == 3
            assert found["document_version_guard"] == 7
            await txn.rollback()

    run_async(scenario())


def test_at_most_one_open_leg_per_thread(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed_thread_and_execution(conn)
            await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            with pytest.raises(IntegrityError):
                await design_legs.open_leg(
                    conn,
                    workspace_id=seeds["ws"],
                    thread_id=seeds["thread_id"],
                    parent_execution_id=seeds["execution_id"],
                )

    run_async(scenario())


def test_state_machine_and_locked_close_journal(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed_thread_and_execution(conn)
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            await design_legs.mark_leg_running(conn, workspace_id=seeds["ws"], leg_id=leg["id"])
            await design_legs.mark_leg_awaiting_user(
                conn, workspace_id=seeds["ws"], leg_id=leg["id"]
            )
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["ws"],
                leg_id=leg["id"],
                reason="locked",
                summary_refs={"document_version": 9, "accepted_ops": ["op_1"]},
                decided_by_run_id="run_abc",
            )
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn, workspace_id=seeds["ws"], thread_id=seeds["thread_id"]
                )
                is None
            )
            closed = await design_legs.get_leg(conn, workspace_id=seeds["ws"], leg_id=leg["id"])
            assert closed["state"] == "closed" and closed["close_reason"] == "locked"
            journal = (
                (
                    await conn.execute(
                        text(
                            "SELECT reason, summary_refs FROM design_leg_exit_journal "
                            "WHERE leg_id = :leg"
                        ),
                        {"leg": leg["id"]},
                    )
                )
                .mappings()
                .all()
            )
            assert len(journal) == 1 and journal[0]["reason"] == "locked"
            # Closing an already-closed leg is a state error, not a silent no-op.
            with pytest.raises(DesignLegStateError):
                await design_legs.close_leg(
                    conn,
                    workspace_id=seeds["ws"],
                    leg_id=leg["id"],
                    reason="abandoned",
                    summary_refs={},
                )
            await txn.rollback()

    run_async(scenario())


def test_out_of_scope_requires_pending_message(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed_thread_and_execution(conn)
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            with pytest.raises(ValueError, match="pending_user_message_ref"):
                await design_legs.close_leg(
                    conn,
                    workspace_id=seeds["ws"],
                    leg_id=leg["id"],
                    reason="out_of_scope",
                    summary_refs={},
                )
            await txn.rollback()

    run_async(scenario())


def test_reopen_restores_open_state_and_keeps_journal(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed_thread_and_execution(conn)
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["ws"],
                leg_id=leg["id"],
                reason="out_of_scope",
                summary_refs={},
                pending_user_message_ref="artifact://pending-question",
            )
            await design_legs.reopen_leg(conn, workspace_id=seeds["ws"], leg_id=leg["id"])
            reopened = await design_legs.get_leg(conn, workspace_id=seeds["ws"], leg_id=leg["id"])
            assert reopened["state"] == "open_awaiting_user"
            assert reopened["close_reason"] is None
            journal_count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_leg_exit_journal WHERE leg_id = :leg"),
                    {"leg": leg["id"]},
                )
            ).scalar_one()
            assert journal_count == 1  # the mis-exit record survives the reopen
            # Reopening an OPEN leg is a state error.
            with pytest.raises(DesignLegStateError):
                await design_legs.reopen_leg(conn, workspace_id=seeds["ws"], leg_id=leg["id"])
            await txn.rollback()

    run_async(scenario())


def test_exit_journal_is_append_only(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed_thread_and_execution(conn)
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["ws"],
                leg_id=leg["id"],
                reason="abandoned",
                summary_refs={},
            )
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(
                    text(
                        "UPDATE design_leg_exit_journal SET reason = 'locked' WHERE leg_id = :leg"
                    ),
                    {"leg": leg["id"]},
                )

    run_async(scenario())
