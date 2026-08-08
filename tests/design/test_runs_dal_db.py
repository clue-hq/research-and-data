"""D2.5A acceptance tests: the agent-run + run-event DAL port (PD contract §7).

Covers the semantics the port either preserves or deliberately changes:

* **the ported round trip** — create → append events → terminal result, with the
  ``agent_run_from_row`` / ``run_event_from_row`` shapes the endpoints serve.
* **race-free seq allocation** — two concurrent appenders (separate connections, real
  transactions) serialize on the parent run's ``FOR UPDATE`` lock and produce 1 and 2, never a
  duplicate that would trip ``design_run_event_seq_unique``.
* **fail-closed tenancy** — another workspace's run is invisible to every read and unwritable by
  every write, with the same refusal an absent run gets.
* **the documented FK concession** — a ``document_id`` that names no document of this workspace
  is stored as NULL instead of tripping ``design_agent_run_document_fk`` (the async agent-turn
  route legitimately carries an unstored id).
* **the unscoped sweep read** — ``list_running_runs_across_workspaces`` sees every tenant's
  orphans and labels each with its owner, which is the whole point of a restart sweep.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import create_engine, db_lifespan
from clue_design import documents as design_documents
from clue_design import runs as design_runs
from clue_design.errors import DesignNotFoundError
from tests.design.conftest import run_async


async def _seed_ws(conn: AsyncConnection, tag: str) -> str:
    ws = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _seed_document(conn: AsyncConnection, ws: str, *, doc_kind: str = "web") -> str:
    doc_id = f"doc_{uuid4().hex}"
    scene = {"meta": {"id": doc_id, "title": "T", "status": {"kind": "draft"}}, "nodes": []}
    web_doc = {"id": doc_id, "title": "T", "schema_version": 1, "pages": []}
    await design_documents.create_document(
        conn,
        workspace_id=ws,
        scene=web_doc if doc_kind == "web" else scene,
        doc_kind=doc_kind,
    )
    return doc_id


@pytest.mark.usefixtures("require_design_db")
def test_run_round_trip_events_and_terminal_result() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "runrt")
                doc_id = await _seed_document(conn, ws)
                run_id = f"run_{uuid4().hex}"

                created = await design_runs.create_run(
                    conn, workspace_id=ws, run_id=run_id, document_id=doc_id
                )
                assert created["status"] == "running"
                assert created["document_id"] == doc_id
                assert created["result"] is None
                # ISO strings, not datetimes — the shape the API has always served.
                assert isinstance(created["created_at"], str)

                first = await design_runs.append_run_event(
                    conn,
                    workspace_id=ws,
                    run_id=run_id,
                    event_type="dsl_compiled",
                    data={"operations": [{"kind": "add_page"}]},
                )
                second = await design_runs.append_run_event(
                    conn, workspace_id=ws, run_id=run_id, event_type="result", data={}
                )
                assert (first, second) == (1, 2)

                events = await design_runs.list_run_events(conn, workspace_id=ws, run_id=run_id)
                assert [event["seq"] for event in events] == [1, 2]
                assert events[0]["type"] == "dsl_compiled"
                # The sink stores whatever dict it is handed, verbatim.
                assert events[0]["data"] == {"operations": [{"kind": "add_page"}]}
                # after_seq is the SSE resume point.
                resumed = await design_runs.list_run_events(
                    conn, workspace_id=ws, run_id=run_id, after_seq=1
                )
                assert [event["seq"] for event in resumed] == [2]

                await design_runs.set_run_result(
                    conn,
                    workspace_id=ws,
                    run_id=run_id,
                    status="succeeded",
                    result={"status": "applied"},
                )
                done = await design_runs.require_run(conn, workspace_id=ws, run_id=run_id)
                assert done["status"] == "succeeded"
                assert done["result"] == {"status": "applied"}
                # A terminal run no longer shows up as running.
                assert await design_runs.list_running_runs(conn, workspace_id=ws) == []
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_running_runs_carry_their_document_kind() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "runkind")
                web_doc = await _seed_document(conn, ws, doc_kind="web")
                with_doc = f"run_{uuid4().hex}"
                without_doc = f"run_{uuid4().hex}"
                await design_runs.create_run(
                    conn, workspace_id=ws, run_id=with_doc, document_id=web_doc
                )
                await design_runs.create_run(
                    conn, workspace_id=ws, run_id=without_doc, document_id=None
                )

                running = await design_runs.list_running_runs(conn, workspace_id=ws)
                by_id = {row["run_id"]: row for row in running}
                assert by_id[with_doc]["doc_kind"] == "web"
                # The ported LEFT JOIN shape: no document -> no kind, not an error.
                assert by_id[without_doc]["doc_kind"] is None
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_unknown_document_id_is_stored_as_null_not_rejected() -> None:
    """The documented FK concession: ``POST /agent/turns`` carries the editor's document id with
    the scene inline, and that document need not be stored — so an unresolvable reference is
    dropped rather than failing the run row that the SQLite era happily created."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "runfk")
                other_ws = await _seed_ws(conn, "runfkother")
                foreign_doc = await _seed_document(conn, other_ws)

                ghost_run = f"run_{uuid4().hex}"
                created = await design_runs.create_run(
                    conn, workspace_id=ws, run_id=ghost_run, document_id="doc_never_stored"
                )
                assert created["document_id"] is None

                # A document that exists, but in ANOTHER workspace, is equally unresolvable —
                # the tenancy predicate, not just existence, decides.
                cross_run = f"run_{uuid4().hex}"
                created_cross = await design_runs.create_run(
                    conn, workspace_id=ws, run_id=cross_run, document_id=foreign_doc
                )
                assert created_cross["document_id"] is None
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_reads_and_writes_are_fail_closed_across_workspaces() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                owner = await _seed_ws(conn, "runown")
                intruder = await _seed_ws(conn, "runint")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(
                    conn, workspace_id=owner, run_id=run_id, document_id=None
                )
                await design_runs.append_run_event(
                    conn, workspace_id=owner, run_id=run_id, event_type="progress", data={}
                )

                # Reads: absent, not forbidden — existence never leaks.
                assert (
                    await design_runs.get_run(conn, workspace_id=intruder, run_id=run_id)
                ) is None
                assert (
                    await design_runs.list_run_events(conn, workspace_id=intruder, run_id=run_id)
                    == []
                )
                assert await design_runs.list_running_runs(conn, workspace_id=intruder) == []
                with pytest.raises(DesignNotFoundError):
                    await design_runs.require_run(conn, workspace_id=intruder, run_id=run_id)

                # Writes: refused with the same not-found, and nothing changes.
                with pytest.raises(DesignNotFoundError):
                    await design_runs.set_run_result(
                        conn,
                        workspace_id=intruder,
                        run_id=run_id,
                        status="failed",
                        result={"hijacked": True},
                    )
                with pytest.raises(DesignNotFoundError):
                    await design_runs.append_run_event(
                        conn,
                        workspace_id=intruder,
                        run_id=run_id,
                        event_type="error",
                        data={},
                    )
                still = await design_runs.require_run(conn, workspace_id=owner, run_id=run_id)
                assert still["status"] == "running"
                assert still["result"] is None
                owned = await design_runs.list_run_events(conn, workspace_id=owner, run_id=run_id)
                assert [event["seq"] for event in owned] == [1]
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_the_orphan_sweep_read_spans_every_workspace() -> None:
    """The one unscoped read, and why it must be: a restart orphans every tenant's in-flight
    turns, so a workspace-scoped sweep would strand all but one of them."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws_a = await _seed_ws(conn, "sweepa")
                ws_b = await _seed_ws(conn, "sweepb")
                run_a = f"run_{uuid4().hex}"
                run_b = f"run_{uuid4().hex}"
                finished = f"run_{uuid4().hex}"
                await design_runs.create_run(
                    conn, workspace_id=ws_a, run_id=run_a, document_id=None
                )
                await design_runs.create_run(
                    conn, workspace_id=ws_b, run_id=run_b, document_id=None
                )
                await design_runs.create_run(
                    conn, workspace_id=ws_b, run_id=finished, document_id=None
                )
                await design_runs.set_run_result(
                    conn,
                    workspace_id=ws_b,
                    run_id=finished,
                    status="succeeded",
                    result={"status": "applied"},
                )

                everything = await design_runs.list_running_runs_across_workspaces(conn)
                owners = {
                    row["run_id"]: row["workspace_id"]
                    for row in everything
                    if row["run_id"] in {run_a, run_b, finished}
                }
                # Both tenants' orphans are visible, each labelled with its OWNER so the caller
                # can fail it through a workspace-correct store; the terminal run is not.
                assert owners == {run_a: ws_a, run_b: ws_b}
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_concurrent_appenders_serialize_on_the_parent_run_lock() -> None:
    """SQLite's ``MAX(seq)+1`` was race-free only under its single-writer assumption. Two real
    concurrent transactions must still produce 1 and 2 — the second blocks on the parent run's
    ``FOR UPDATE`` lock rather than reading a stale MAX and colliding on the seq unique."""

    async def scenario() -> None:
        engine = create_engine()
        try:
            async with engine.connect() as setup:
                trans = await setup.begin()
                ws = await _seed_ws(setup, "runrace")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(
                    setup, workspace_id=ws, run_id=run_id, document_id=None
                )
                await trans.commit()

            async def append(kind: str) -> int:
                async with engine.connect() as conn, conn.begin():
                    return await design_runs.append_run_event(
                        conn, workspace_id=ws, run_id=run_id, event_type=kind, data={}
                    )

                # (both transactions commit; the cleanup below removes them)

            seqs = await asyncio.gather(append("a"), append("b"))
            assert sorted(seqs) == [1, 2]

            async with engine.connect() as conn:
                cleanup = await conn.begin()
                events = await design_runs.list_run_events(conn, workspace_id=ws, run_id=run_id)
                assert [event["seq"] for event in events] == [1, 2]
                # Committed rows, so clean up explicitly (this test cannot roll back).
                await conn.execute(
                    text("DELETE FROM design_run_event WHERE run_id = :r"), {"r": run_id}
                )
                await conn.execute(
                    text("DELETE FROM design_agent_run WHERE run_id = :r"), {"r": run_id}
                )
                await conn.execute(text("DELETE FROM workspace WHERE workspace_id = :w"), {"w": ws})
                await cleanup.commit()
        finally:
            await engine.dispose()

    run_async(scenario())
