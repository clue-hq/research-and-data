"""Design-session substrate (design note 2026-09-18) — the DB half.

``latest_written_version`` is the fact a continued session compares the document against, so
what it must get right is *which* run it believes: the newest **succeeded** run of THIS document
in THIS workspace that actually stamped a version. A failed run's stamp and another document's
stamp are both wrong answers, and "no agent turn yet" must be distinguishable from "version 0".

Writes run inside an explicitly rolled-back transaction, so the lane database keeps no rows.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import runs as design_runs
from clue_design.sessions import latest_written_version
from tests.design.conftest import run_async


async def _seed_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )


async def _seed_document(conn: AsyncConnection, *, workspace_id: str, document_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_document"
            " (id, workspace_id, title, status, doc_kind, current_scene_json, current_version)"
            " VALUES (:d, :w, 'T', 'draft', 'scene', '{}'::jsonb, 3)"
        ),
        {"d": document_id, "w": workspace_id},
    )


async def _terminalize(
    conn: AsyncConnection, *, run_id: str, status: str, result: str | None
) -> None:
    """Stamp a terminal status + result on a run, each write a wall-clock tick later.

    ``clock_timestamp()``, not ``now()``: inside one transaction ``now()`` is frozen, so every
    run would share an ``updated_at`` and "the newest succeeded run" would be a coin flip.
    """
    await conn.execute(
        text(
            "UPDATE design_agent_run SET status = CAST(:s AS design_run_status), "
            "result_json = CAST(:r AS jsonb), updated_at = clock_timestamp() WHERE run_id = :id"
        ),
        {"s": status, "r": result, "id": run_id},
    )


@pytest.mark.usefixtures("require_design_db")
def test_latest_written_version_reads_the_newest_succeeded_stamp() -> None:
    async def scenario() -> None:
        ws, doc = f"ws_test_sess_{uuid4().hex[:10]}", f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await _seed_workspace(conn, ws)
                await _seed_document(conn, workspace_id=ws, document_id=doc)

                # Before any agent turn there is no written version — not version 0.
                assert await latest_written_version(conn, workspace_id=ws, document_id=doc) is None

                # Oldest first. The two newest runs are the distractors: a FAILED run whose
                # stamp must never be believed, and a succeeded run that stamped nothing.
                for status, result in (
                    ("succeeded", '{"current_version": 2}'),
                    ("succeeded", '{"current_version": 3}'),
                    ("failed", '{"current_version": 9}'),
                    ("succeeded", '{"summary": "preview only"}'),
                ):
                    run_id = f"run_{uuid4().hex}"
                    await design_runs.create_run(
                        conn, workspace_id=ws, run_id=run_id, document_id=doc
                    )
                    await _terminalize(conn, run_id=run_id, status=status, result=result)

                assert await latest_written_version(conn, workspace_id=ws, document_id=doc) == 3
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_latest_written_version_is_scoped_to_its_own_document_and_workspace() -> None:
    async def scenario() -> None:
        ws, other_ws = f"ws_test_sess_{uuid4().hex[:10]}", f"ws_test_sess_{uuid4().hex[:10]}"
        doc, sibling = f"doc_{uuid4().hex}", f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await _seed_workspace(conn, ws)
                await _seed_workspace(conn, other_ws)
                await _seed_document(conn, workspace_id=ws, document_id=doc)
                await _seed_document(conn, workspace_id=ws, document_id=sibling)

                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(
                    conn, workspace_id=ws, run_id=run_id, document_id=sibling
                )
                await _terminalize(
                    conn, run_id=run_id, status="succeeded", result='{"current_version": 7}'
                )

                assert await latest_written_version(conn, workspace_id=ws, document_id=doc) is None
                assert (
                    await latest_written_version(conn, workspace_id=other_ws, document_id=sibling)
                    is None
                )
                assert await latest_written_version(conn, workspace_id=ws, document_id=sibling) == 7
            finally:
                await trans.rollback()

    run_async(scenario())
