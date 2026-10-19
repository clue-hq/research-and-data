"""Design-session substrate (design note 2026-09-18) — the DB half.

``latest_written_version`` is the fact a continued session compares the document against, so
what it must get right is *which* run it believes: the newest **succeeded** run of THIS document
in THIS workspace that actually stamped a version. A failed run's stamp and another document's
stamp are both wrong answers, and "no agent turn yet" must be distinguishable from "version 0".

Writes run inside an explicitly rolled-back transaction, so the lane database keeps no rows.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import runs as design_runs
from clue_design.sessions import (
    get_site_session,
    latest_session_manifest_sha256,
    latest_written_version,
    save_site_session,
)
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


@pytest.mark.usefixtures("require_design_db")
def test_latest_session_manifest_reads_the_newest_succeeded_stamp() -> None:
    """The session-folder manifest is read back with the same honesty as the version stamp.

    Task 8 (2026-09-18): the manifest digest is the only durable pointer to a session's memory,
    so the wrong answer here is a session that wakes up with amnesia (or, worse, with a FAILED
    turn's folder). Same three distractors: a failed run, a succeeded run that synced nothing,
    and another document's session.
    """

    async def scenario() -> None:
        ws, doc = f"ws_test_sess_{uuid4().hex[:10]}", f"doc_{uuid4().hex}"
        sibling = f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await _seed_workspace(conn, ws)
                await _seed_document(conn, workspace_id=ws, document_id=doc)
                await _seed_document(conn, workspace_id=ws, document_id=sibling)

                # Before any turn synced, there is nothing to restore — the first turn of a
                # session simply starts its folder fresh.
                assert (
                    await latest_session_manifest_sha256(conn, workspace_id=ws, document_id=doc)
                    is None
                )

                for status, result in (
                    ("succeeded", '{"session_manifest_sha256": "aa"}'),
                    ("succeeded", '{"session_manifest_sha256": "bb"}'),
                    ("failed", '{"session_manifest_sha256": "ff"}'),
                    ("succeeded", '{"summary": "no session"}'),
                ):
                    run_id = f"run_{uuid4().hex}"
                    await design_runs.create_run(
                        conn, workspace_id=ws, run_id=run_id, document_id=doc
                    )
                    await _terminalize(conn, run_id=run_id, status=status, result=result)

                sibling_run = f"run_{uuid4().hex}"
                await design_runs.create_run(
                    conn, workspace_id=ws, run_id=sibling_run, document_id=sibling
                )
                await _terminalize(
                    conn,
                    run_id=sibling_run,
                    status="succeeded",
                    result='{"session_manifest_sha256": "cc"}',
                )

                assert (
                    await latest_session_manifest_sha256(conn, workspace_id=ws, document_id=doc)
                    == "bb"
                )
                # Scoped to its own document, and to its own workspace.
                assert (
                    await latest_session_manifest_sha256(conn, workspace_id=ws, document_id=sibling)
                    == "cc"
                )
                assert (
                    await latest_session_manifest_sha256(
                        conn, workspace_id=f"ws_other_{uuid4().hex[:8]}", document_id=doc
                    )
                    is None
                )
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_include_failed_reads_a_failed_turns_manifest_and_the_default_does_not() -> None:
    """BV1a fix round 1: a Puck site turn writes its history and snapshots its memory on a
    conflicted, refused or stopped (``failed``) request too, so the site executor asks with
    ``include_failed=True``. The default (web and scene) is unchanged: a newer failed run's manifest
    is skipped. A failed run that stamped nothing (a crash) is skipped either way.
    """

    async def scenario() -> None:
        ws, doc = f"ws_test_sess_{uuid4().hex[:10]}", f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await _seed_workspace(conn, ws)
                await _seed_document(conn, workspace_id=ws, document_id=doc)
                for status, result in (
                    ("succeeded", '{"session_manifest_sha256": "aa"}'),
                    ("failed", '{"session_manifest_sha256": "ff"}'),
                    ("failed", '{"summary": "crashed before a snapshot"}'),
                ):
                    run_id = f"run_{uuid4().hex}"
                    await design_runs.create_run(
                        conn, workspace_id=ws, run_id=run_id, document_id=doc
                    )
                    await _terminalize(conn, run_id=run_id, status=status, result=result)

                assert (
                    await latest_session_manifest_sha256(conn, workspace_id=ws, document_id=doc)
                    == "aa"
                )
                assert (
                    await latest_session_manifest_sha256(
                        conn, workspace_id=ws, document_id=doc, include_failed=True
                    )
                    == "ff"
                )
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_a_site_session_pointer_moves_only_by_compare_and_set() -> None:
    """Site-turn durability (2026-10-16, K4-5): a website's session files are ONE versioned copy.
    The first save inserts version 1 only while there is no row; every later save moves the
    pointer only from the version it started from. A save that started from an older version (or
    from "no row" after someone created one) writes nothing, and the newer copy stays. The pointer
    is scoped to its own document and workspace."""
    sha = {
        name: hashlib.sha256(name.encode()).hexdigest() for name in ("r1", "r2", "stale", "other")
    }

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

                async def save(
                    expected: int | None, manifest: str, document: str = doc
                ) -> int | None:
                    return await save_site_session(
                        conn,
                        workspace_id=ws,
                        document_id=document,
                        expected_version=expected,
                        manifest_sha256=manifest,
                    )

                assert await get_site_session(conn, workspace_id=ws, document_id=doc) is None
                assert await save(None, sha["r1"]) == 1
                # A second "first save" (it also started from no row) is refused.
                assert await save(None, sha["stale"]) is None
                assert await save(1, sha["r2"]) == 2
                # A save that started from version 1 lost the race: nothing is written.
                assert await save(1, sha["stale"]) is None
                assert await get_site_session(conn, workspace_id=ws, document_id=doc) == {
                    "version": 2,
                    "manifest_sha256": sha["r2"],
                }

                # Scoped: another document and another workspace see no row.
                assert await get_site_session(conn, workspace_id=ws, document_id=sibling) is None
                assert await get_site_session(conn, workspace_id=other_ws, document_id=doc) is None
                assert await save(None, sha["other"], sibling) == 1
                assert (await get_site_session(conn, workspace_id=ws, document_id=doc))[
                    "version"
                ] == 2
            finally:
                await trans.rollback()

    run_async(scenario())
