"""D2.1 acceptance tests: the DAL foundation's sequence allocators (PD contract §4/§7).

Three properties:

1. **Gapless per-parent allocation** — each allocator hands out ``MAX+1`` per parent, and the
   envelope/op-log counters are independent.
2. **Fail-closed tenancy** — a foreign-workspace parent and an absent parent raise the same
   :class:`DesignNotFoundError` (existence never leaks across workspaces).
3. **Serialization under concurrency** — a second transaction's allocation BLOCKS on the
   parent row lock until the first commits, then sees the committed row (no duplicate seq) —
   the exact race the SQLite ``MAX+1`` idiom lost.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from clue_db import db_lifespan
from clue_design import runs as design_runs
from clue_design.errors import DesignNotFoundError
from clue_design.sequences import (
    allocate_envelope_seq,
    allocate_operation_sequence,
    allocate_run_event_seq,
)
from tests.design.conftest import run_async


def _ws(tag: str) -> str:
    return f"ws_test_dal_{tag}_{uuid4().hex[:12]}"


async def _seed_doc(conn: AsyncConnection, doc_id: str, workspace_id: str) -> None:
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"),
        {"w": workspace_id},
    )
    await conn.execute(
        text(
            "INSERT INTO design_document (id, workspace_id, title, status, current_scene_json)"
            " VALUES (:d, :w, 'T', 'draft', '{}'::jsonb)"
        ),
        {"d": doc_id, "w": workspace_id},
    )


async def _insert_envelope(conn: AsyncConnection, doc_id: str, workspace_id: str, seq: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_edit_envelope "
            "(batch_id, workspace_id, document_id, seq, actor_kind, source, operations_json)"
            " VALUES (:b, :w, :d, :s, 'human', 'editor', '[]'::jsonb)"
        ),
        {"b": f"batch_{uuid4().hex[:12]}", "w": workspace_id, "d": doc_id, "s": seq},
    )


def test_allocators_are_gapless_and_independent_per_parent(require_design_db: None) -> None:
    async def _check() -> None:
        ws, doc = _ws("gapless"), f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_doc(conn, doc, ws)
            assert await allocate_envelope_seq(conn, document_id=doc, workspace_id=ws) == 1
            await _insert_envelope(conn, doc, ws, 1)
            assert await allocate_envelope_seq(conn, document_id=doc, workspace_id=ws) == 2
            # The op-log counter is independent of the envelope counter.
            assert await allocate_operation_sequence(conn, document_id=doc, workspace_id=ws) == 1
            await txn.rollback()

    run_async(_check())


def test_allocator_refuses_foreign_and_absent_parents_identically(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        ws_a, ws_b, doc = _ws("fc_a"), _ws("fc_b"), f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"),
                {"w": ws_b},
            )
            await _seed_doc(conn, doc, ws_a)
            with pytest.raises(DesignNotFoundError) as foreign:
                await allocate_envelope_seq(conn, document_id=doc, workspace_id=ws_b)
            with pytest.raises(DesignNotFoundError) as absent:
                await allocate_envelope_seq(
                    conn, document_id=f"doc_{uuid4().hex}", workspace_id=ws_b
                )
            # Same refusal shape either way: existence never leaks across workspaces.
            assert foreign.value.kind == absent.value.kind == "design_document"
            await txn.rollback()

    run_async(_check())


def test_run_event_allocator_locks_the_run_row(require_design_db: None) -> None:
    async def _check() -> None:
        ws, run = _ws("runev"), f"run_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"),
                {"w": ws},
            )
            await conn.execute(
                text(
                    # D5 columns are NOT NULL; this raw insert stands in for a run the DAL
                    # would have created, so it derives its work id the same way create_run
                    # does and makes the checkpoint thread the run id.
                    "INSERT INTO design_agent_run"
                    " (run_id, workspace_id, work_id, checkpoint_thread_id, kind, status)"
                    " VALUES (:r, :w, :work_id, :r, 'agent_turn', 'running')"
                ),
                {"r": run, "w": ws, "work_id": design_runs.work_id_for_run(run)},
            )
            assert await allocate_run_event_seq(conn, run_id=run, workspace_id=ws) == 1
            with pytest.raises(DesignNotFoundError):
                await allocate_run_event_seq(conn, run_id=f"run_{uuid4().hex}", workspace_id=ws)
            await txn.rollback()

    run_async(_check())


def test_concurrent_allocation_serializes_on_the_parent_lock(require_design_db: None) -> None:
    """Writer B blocks on the parent row lock until writer A commits, then sees A's row —
    the duplicate-seq race the SQLite idiom allowed is structurally gone."""

    async def _writer_b(engine: AsyncEngine, doc: str, ws: str) -> int:
        async with engine.connect() as conn, conn.begin():
            seq = await allocate_envelope_seq(conn, document_id=doc, workspace_id=ws)
            await _insert_envelope(conn, doc, ws, seq)
            return seq

    async def _check() -> None:
        ws, doc = _ws("conc"), f"doc_{uuid4().hex}"
        async with db_lifespan() as engine:
            # The parent must be COMMITTED before the writers race: an uncommitted parent is
            # (correctly) invisible to a concurrent writer, which gets the fail-closed
            # DesignNotFoundError instead of a lock wait.
            async with engine.connect() as seed_conn, seed_conn.begin():
                await _seed_doc(seed_conn, doc, ws)

            conn_a = await engine.connect()
            try:
                txn_a = await conn_a.begin()
                seq_a = await allocate_envelope_seq(conn_a, document_id=doc, workspace_id=ws)
                assert seq_a == 1
                await _insert_envelope(conn_a, doc, ws, seq_a)

                task_b = asyncio.create_task(_writer_b(engine, doc, ws))
                await asyncio.sleep(0.3)
                # B is parked on A's parent row lock — the serialization, observed.
                assert not task_b.done(), "writer B should block until A commits"

                await txn_a.commit()
                assert await task_b == 2
            finally:
                await conn_a.close()

            # Both writers committed: clean up (document cascade deletes the envelopes).
            async with engine.connect() as conn, conn.begin():
                await conn.execute(text("DELETE FROM design_document WHERE id = :d"), {"d": doc})
                await conn.execute(text("DELETE FROM workspace WHERE workspace_id = :w"), {"w": ws})

    run_async(_check())
