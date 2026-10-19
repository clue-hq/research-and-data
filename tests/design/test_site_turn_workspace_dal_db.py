"""The site turn's working copy and its prune (site-turn durability, Task 3).

``design_site_turn_workspace`` holds ONE row per running site turn, overwritten in place, written
only by the attempt that holds the run. Every terminal write of the run (``set_run_result``, the
reaper's ``fail_stranded_run``, the fleet plane's ``fail_dispatched_run``) deletes it and the run's
LangGraph checkpoints in the same transaction; a scene/web run's checkpoint thread (its document's
session) is never touched.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import runs as design_runs
from clue_design import site_turn_workspace as copies
from clue_design.enums import DesignRunKind
from tests.design.conftest import run_async

SHA = "a" * 64


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_copy_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _site_run(
    conn: AsyncConnection,
    ws: str,
    *,
    kind: DesignRunKind = DesignRunKind.SITE_TURN,
    thread: str | None = None,
    generation: int = 1,
) -> str:
    run_id = f"run_{uuid4().hex}"
    await design_runs.create_run(
        conn,
        workspace_id=ws,
        run_id=run_id,
        document_id=None,
        kind=kind,
        checkpoint_thread_id=thread,
    )
    claimed = await design_runs.claim_run_for_execution(
        conn,
        work_id=design_runs.work_id_for_run(run_id),
        worker_id="worker-a",
        lease_generation=generation,
    )
    assert claimed is not None
    return run_id


async def _put(
    conn: AsyncConnection, ws: str, run_id: str, *, checkpoint: str, gen: int | None
) -> bool:
    return await copies.put_site_turn_workspace(
        conn,
        workspace_id=ws,
        run_id=run_id,
        checkpoint_id=checkpoint,
        files={"page.json": "{}"},
        turn_state={"rounds": 2},
        files_sha256=SHA,
        attempt_generation=gen,
    )


async def _checkpoint(conn: AsyncConnection, thread: str) -> None:
    """One row in each LangGraph checkpoint table for ``thread``."""
    await conn.execute(
        text(
            "INSERT INTO checkpoints"
            " (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata)"
            " VALUES (:t, '', :c, '{}'::jsonb, '{}'::jsonb)"
        ),
        {"t": thread, "c": uuid4().hex},
    )
    await conn.execute(
        text(
            "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type)"
            " VALUES (:t, '', 'messages', '1', 'empty')"
        ),
        {"t": thread},
    )
    await conn.execute(
        text(
            "INSERT INTO checkpoint_writes"
            " (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob)"
            " VALUES (:t, '', 'c1', 'task', 0, 'messages', 'empty', ''::bytea)"
        ),
        {"t": thread},
    )


async def _counts(conn: AsyncConnection, run_id: str, thread: str) -> dict[str, int]:
    out = {
        "copy": (
            await conn.execute(
                text("SELECT count(*) FROM design_site_turn_workspace WHERE run_id = :r"),
                {"r": run_id},
            )
        ).scalar_one()
    }
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        out[table] = (
            await conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE thread_id = :t"), {"t": thread}
            )
        ).scalar_one()
    return out


def _in_rolled_back_txn(body) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await body(conn)
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_one_copy_per_run_overwritten_in_place_and_only_by_the_holder() -> None:
    async def body(conn: AsyncConnection) -> None:
        ws = await _seed_ws(conn)
        run_id = await _site_run(conn, ws, generation=2)
        assert await copies.get_site_turn_workspace(conn, workspace_id=ws, run_id=run_id) is None

        assert await _put(conn, ws, run_id, checkpoint="cp-1", gen=2)
        assert await _put(conn, ws, run_id, checkpoint="cp-2", gen=2)
        row = await copies.get_site_turn_workspace(conn, workspace_id=ws, run_id=run_id)
        assert row is not None
        assert (
            row["checkpoint_id"],
            row["files"],
            row["turn_state"],
            row["attempt_generation"],
        ) == (
            "cp-2",
            {"page.json": "{}"},
            {"rounds": 2},
            2,
        )
        assert (await _counts(conn, run_id, run_id))["copy"] == 1

        # A fenced-out attempt (generation 1) and a stranger (generation 3) write nothing.
        assert not await _put(conn, ws, run_id, checkpoint="zombie", gen=1)
        assert not await _put(conn, ws, run_id, checkpoint="stranger", gen=3)
        row = await copies.get_site_turn_workspace(conn, workspace_id=ws, run_id=run_id)
        assert row is not None and row["checkpoint_id"] == "cp-2"
        # Another workspace cannot read it.
        other = await _seed_ws(conn)
        assert await copies.get_site_turn_workspace(conn, workspace_id=other, run_id=run_id) is None

    _in_rolled_back_txn(body)


@pytest.mark.usefixtures("require_design_db")
def test_a_restamp_moves_the_checkpoint_and_turn_state_on_and_keeps_the_files() -> None:
    """A round that changed no file re-stamps the copy: checkpoint, turn state and writer move on,
    the files and their digest stay. Same fence as the full write, and never an insert."""

    async def restamp(conn, ws, run_id, *, checkpoint: str, gen: int | None, rounds: int) -> bool:
        return await copies.restamp_site_turn_workspace(
            conn,
            workspace_id=ws,
            run_id=run_id,
            checkpoint_id=checkpoint,
            turn_state={"rounds": rounds},
            attempt_generation=gen,
        )

    async def body(conn: AsyncConnection) -> None:
        ws = await _seed_ws(conn)
        run_id = await _site_run(conn, ws, generation=2)
        # Nothing to re-stamp before the first copy: no row is created.
        assert not await restamp(conn, ws, run_id, checkpoint="cp-0", gen=2, rounds=0)
        assert await copies.get_site_turn_workspace(conn, workspace_id=ws, run_id=run_id) is None

        assert await _put(conn, ws, run_id, checkpoint="cp-1", gen=2)
        assert await restamp(conn, ws, run_id, checkpoint="cp-2", gen=2, rounds=5)
        row = await copies.get_site_turn_workspace(conn, workspace_id=ws, run_id=run_id)
        assert row is not None
        assert (row["checkpoint_id"], row["turn_state"], row["files"], row["files_sha256"]) == (
            "cp-2",
            {"rounds": 5},
            {"page.json": "{}"},
            SHA,
        )

        # A fenced-out attempt, a stranger, and another workspace re-stamp nothing.
        assert not await restamp(conn, ws, run_id, checkpoint="zombie", gen=1, rounds=9)
        assert not await restamp(conn, ws, run_id, checkpoint="stranger", gen=3, rounds=9)
        other = await _seed_ws(conn)
        assert not await restamp(conn, other, run_id, checkpoint="other", gen=2, rounds=9)
        row = await copies.get_site_turn_workspace(conn, workspace_id=ws, run_id=run_id)
        assert row is not None and row["checkpoint_id"] == "cp-2"

        # A terminal run is not re-stamped.
        await conn.execute(
            text("UPDATE design_agent_run SET status = 'succeeded' WHERE run_id = :r"),
            {"r": run_id},
        )
        assert not await restamp(conn, ws, run_id, checkpoint="late", gen=2, rounds=9)

    _in_rolled_back_txn(body)


@pytest.mark.usefixtures("require_design_db")
def test_every_terminal_write_prunes_the_copy_and_keeps_the_conversation() -> None:
    async def body(conn: AsyncConnection) -> None:
        ws = await _seed_ws(conn)
        result = {"schema_version": 1, "status": "failed"}

        async def prepared() -> str:
            run_id = await _site_run(conn, ws)
            assert await _put(conn, ws, run_id, checkpoint="cp", gen=1)
            await _checkpoint(conn, run_id)
            return run_id

        # The working copy goes at once; the conversation is kept (deleted 96 h later by
        # prune_expired_site_turn_checkpoints, founder 2026-10-17: kept for debugging).
        empty = {"copy": 0, "checkpoints": 1, "checkpoint_blobs": 1, "checkpoint_writes": 1}

        fenced_complete = await prepared()
        await design_runs.set_run_result(
            conn,
            workspace_id=ws,
            run_id=fenced_complete,
            status="succeeded",
            result=result,
            expected_generation=1,
        )
        assert await _counts(conn, fenced_complete, fenced_complete) == empty

        unfenced_complete = await prepared()
        await design_runs.set_run_result(
            conn, workspace_id=ws, run_id=unfenced_complete, status="failed", result=result
        )
        assert await _counts(conn, unfenced_complete, unfenced_complete) == empty

        stranded = await prepared()
        assert await design_runs.fail_stranded_run(
            conn, work_id=design_runs.work_id_for_run(stranded), result=result
        )
        assert await _counts(conn, stranded, stranded) == empty

        dispatched = await prepared()
        assert await design_runs.fail_dispatched_run(
            conn, work_id=design_runs.work_id_for_run(dispatched), result=result, lease_generation=1
        )
        assert await _counts(conn, dispatched, dispatched) == empty

        # Idempotent: pruning a pruned run is a no-op that still answers "terminal".
        assert await copies.prune_site_turn_state(conn, run_id=dispatched)

    _in_rolled_back_txn(body)


@pytest.mark.usefixtures("require_design_db")
def test_a_finished_site_turns_conversation_is_deleted_only_after_its_retention() -> None:
    """Founder 2026-10-17: a finished site turn's conversation is kept for 96 hours (so a slow or
    odd turn can be traced from its own messages), then deleted. A running run, a run finished
    less than the retention ago, and a web turn's session thread are never touched."""

    async def body(conn: AsyncConnection) -> None:
        ws = await _seed_ws(conn)

        async def finished(age_s: float, kind: DesignRunKind = DesignRunKind.SITE_TURN) -> str:
            thread = None if kind == DesignRunKind.SITE_TURN else f"design-session-{uuid4().hex}"
            run_id = await _site_run(conn, ws, kind=kind, thread=thread)
            await _checkpoint(conn, thread or run_id)
            await design_runs.set_run_result(
                conn,
                workspace_id=ws,
                run_id=run_id,
                status="succeeded",
                result={},
                expected_generation=1,
            )
            await conn.execute(
                text(
                    "UPDATE design_agent_run SET updated_at = now() - make_interval(secs => :a)"
                    " WHERE run_id = :r"
                ),
                {"a": age_s, "r": run_id},
            )
            return run_id

        old = await finished(100 * 3600)
        young = await finished(10 * 3600)
        old_web = await finished(100 * 3600, kind=DesignRunKind.WEB_TURN)
        running = await _site_run(conn, ws)
        await _checkpoint(conn, running)

        deleted = await copies.prune_expired_site_turn_checkpoints(conn, retain_s=96 * 3600)
        assert deleted == 1
        assert (await _counts(conn, old, old))["checkpoints"] == 0
        assert (await _counts(conn, young, young))["checkpoints"] == 1
        assert (await _counts(conn, running, running))["checkpoints"] == 1
        web_thread = (
            await conn.execute(
                text("SELECT checkpoint_thread_id FROM design_agent_run WHERE run_id = :r"),
                {"r": old_web},
            )
        ).scalar_one()
        assert (await _counts(conn, old_web, web_thread))["checkpoints"] == 1
        # A second pass finds nothing left to delete.
        assert await copies.prune_expired_site_turn_checkpoints(conn, retain_s=96 * 3600) == 0

    _in_rolled_back_txn(body)


@pytest.mark.usefixtures("require_design_db")
def test_a_running_run_and_a_session_thread_are_never_pruned() -> None:
    async def body(conn: AsyncConnection) -> None:
        ws = await _seed_ws(conn)
        running = await _site_run(conn, ws)
        assert await _put(conn, ws, running, checkpoint="cp", gen=1)
        await _checkpoint(conn, running)
        assert not await copies.prune_site_turn_state(conn, run_id=running)
        assert await _counts(conn, running, running) == {
            "copy": 1,
            "checkpoints": 1,
            "checkpoint_blobs": 1,
            "checkpoint_writes": 1,
        }

        # A web turn's thread is its document's session: ending the run leaves it alone.
        session = f"design-session-{uuid4().hex}"
        web = await _site_run(conn, ws, kind=DesignRunKind.WEB_TURN, thread=session)
        await _checkpoint(conn, session)
        await design_runs.set_run_result(
            conn, workspace_id=ws, run_id=web, status="succeeded", result={}, expected_generation=1
        )
        counts = await _counts(conn, web, session)
        assert (counts["checkpoints"], counts["checkpoint_blobs"], counts["checkpoint_writes"]) == (
            1,
            1,
            1,
        )

    _in_rolled_back_txn(body)
