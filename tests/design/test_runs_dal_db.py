"""D2.5A + D7 acceptance tests: the agent-run DAL and the run's durable event stream.

Covers the semantics the port either preserves or deliberately changes:

* **the ported round trip** — create → claim → stream events → terminal result, with the
  ``agent_run_from_row`` shape the endpoints serve and the ``{seq, type, data, created_at}`` event
  shape the editor consumes. Since D5 a run is born ``queued`` and only the claim CAS moves it to
  ``running``; the pre-fleet in-process path does both back to back
  (``HybridRepository.create_run``), which is what :func:`_start` reproduces here.
* **fail-closed tenancy** — another workspace's run is invisible to every read and unwritable by
  every write, with the same refusal an absent run gets.
* **the documented FK concession** — a ``document_id`` that names no document of this workspace
  is stored as NULL instead of tripping ``design_agent_run_document_fk`` (the async agent-turn
  route legitimately carries an unstored id).
* **the D7 substrate swap** — events land on the platform ``run_event`` outbox under
  ``subject_kind='design_run'``, keyed by the DB's own global seq. Concurrent emitters therefore
  need no parent-row lock at all (the D2.1 ``FOR UPDATE`` allocator is gone with its table); what
  must still hold is that each emitter gets a distinct, increasing seq and the run's
  ``updated_at`` — the reaper's staleness clock — is bumped by every one of them.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from lumen_api import run_stream
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


async def _start(
    conn: AsyncConnection, ws: str, run_id: str, document_id: str | None = None
) -> dict[str, Any]:
    """Create a run and claim it — the pre-fleet in-process path, in one helper.

    Tests written before D5 assumed ``create_run`` alone left a run in flight. It now leaves it
    ``queued``; anything that means "a run someone is executing" must claim it, exactly as the
    shipped daemon-thread path does.
    """
    await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=document_id)
    claimed = await design_runs.claim_run_for_execution(
        conn,
        work_id=design_runs.work_id_for_run(run_id),
        worker_id="test-worker",
        lease_generation=1,
    )
    assert claimed is not None
    return claimed


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
                # D5: born queued — nobody is executing it yet.
                assert created["status"] == "queued"
                assert created["document_id"] == doc_id
                assert created["result"] is None
                # ISO strings, not datetimes — the shape the API has always served.
                assert isinstance(created["created_at"], str)

                claimed = await design_runs.claim_run_for_execution(
                    conn,
                    work_id=design_runs.work_id_for_run(run_id),
                    worker_id="test-worker",
                    lease_generation=1,
                )
                assert claimed is not None and claimed["status"] == "running"

                first = await run_stream.emit_progress(
                    conn,
                    workspace_id=ws,
                    run_id=run_id,
                    event_type="dsl_compiled",
                    data={"operations": [{"kind": "add_page"}]},
                )
                second = await run_stream.emit_progress(
                    conn, workspace_id=ws, run_id=run_id, event_type="result", data={}
                )
                # D7: the seq is the platform outbox's GLOBAL identity column, so the assertion is
                # monotonicity within the run — not 1, 2. That is exactly the property the editor
                # depends on (it never assumed gaplessness).
                assert first < second

                events = await run_stream.run_snapshot_events(conn, workspace_id=ws, run_id=run_id)
                assert [event["seq"] for event in events] == [first, second]
                assert events[0]["type"] == "dsl_compiled"
                # The sink stores whatever dict it is handed, verbatim.
                assert events[0]["data"] == {"operations": [{"kind": "add_page"}]}
                assert isinstance(events[0]["created_at"], str)

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
                await _start(conn, ws, with_doc, web_doc)
                await _start(conn, ws, without_doc)

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
                await _start(conn, owner, run_id)
                first = await run_stream.emit_progress(
                    conn, workspace_id=owner, run_id=run_id, event_type="progress", data={}
                )

                # Reads: absent, not forbidden — existence never leaks.
                assert (
                    await design_runs.get_run(conn, workspace_id=intruder, run_id=run_id)
                ) is None
                assert (
                    await run_stream.run_snapshot_events(conn, workspace_id=intruder, run_id=run_id)
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
                    await run_stream.emit_progress(
                        conn,
                        workspace_id=intruder,
                        run_id=run_id,
                        event_type="error",
                        data={},
                    )
                still = await design_runs.require_run(conn, workspace_id=owner, run_id=run_id)
                assert still["status"] == "running"
                assert still["result"] is None
                owned = await run_stream.run_snapshot_events(
                    conn, workspace_id=owner, run_id=run_id
                )
                assert [event["seq"] for event in owned] == [first]
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_the_boot_sweep_read_is_gone() -> None:
    """``list_running_runs_across_workspaces`` is DELETED (D7).

    It was the module's one unscoped read, justified by the API's startup orphan sweep. That
    caller died at D5 Round B — a leased durable job needs no boot sweep, and one would now
    destroy recoverable work — leaving the function unwired for two slices. D7 removes it rather
    than keeping an unscoped cross-tenant read alive for nobody. The stranded-work surface the
    reaper actually uses (:func:`list_dispatched_running_runs`) is unaffected and still unscoped,
    for the reason that one genuinely is.
    """
    assert not hasattr(design_runs, "list_running_runs_across_workspaces")
    assert hasattr(design_runs, "list_dispatched_running_runs")


@pytest.mark.usefixtures("require_design_db")
def test_concurrent_emitters_get_distinct_increasing_seqs_and_both_bump_the_clock() -> None:
    """The D7 successor to the ``FOR UPDATE`` seq-allocation race test.

    Under ``design_run_event`` two appenders had to serialize on the parent run's row lock or
    collide on ``design_run_event_seq_unique``. The platform outbox assigns seq from its own
    identity column, so there is no allocation to race and no lock to take — but two properties
    still have to hold, and both are load-bearing: every emitter gets a **distinct, increasing**
    seq (the editor's cursor), and every emitter **bumps the run's ``updated_at``** (the reaper's
    staleness clock, the side effect ``append_run_event`` used to carry and ``touch_run`` now
    does). A chatty-but-healthy run that stopped refreshing its clock would be reaped alive.
    """

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

            async with engine.connect() as probe:
                born = (
                    await probe.execute(
                        text("SELECT updated_at FROM design_agent_run WHERE run_id = :r"),
                        {"r": run_id},
                    )
                ).scalar_one()

            async def emit(kind: str) -> int:
                async with engine.connect() as conn, conn.begin():
                    return await run_stream.emit_progress(
                        conn, workspace_id=ws, run_id=run_id, event_type=kind, data={}
                    )

            seqs = await asyncio.gather(emit("a"), emit("b"))
            assert len(set(seqs)) == 2

            async with engine.connect() as conn:
                cleanup = await conn.begin()
                events = await run_stream.run_snapshot_events(conn, workspace_id=ws, run_id=run_id)
                assert [event["seq"] for event in events] == sorted(seqs)
                touched = (
                    await conn.execute(
                        text("SELECT updated_at FROM design_agent_run WHERE run_id = :r"),
                        {"r": run_id},
                    )
                ).scalar_one()
                assert touched > born
                # Committed rows, so clean up explicitly (this test cannot roll back).
                await conn.execute(
                    text("DELETE FROM run_event WHERE subject_id = :r"), {"r": run_id}
                )
                await conn.execute(
                    text("DELETE FROM design_agent_run WHERE run_id = :r"), {"r": run_id}
                )
                await conn.execute(text("DELETE FROM workspace WHERE workspace_id = :w"), {"w": ws})
                await cleanup.commit()
        finally:
            await engine.dispose()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_runs_for_execution_lists_the_executions_runs_oldest_first() -> None:
    """Spec 2026-09-19 §3.3/§3.9: one leg turn may dispatch MANY runs, and the batch of that turn
    is exactly the runs stamped with the turn's execution id."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "runexec")
                other_ws = await _seed_ws(conn, "runexecother")
                execution_id = uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO execution (id, workspace_id, project_id, started_by,"
                        " parameter_manifest_hash, pin_manifest_hash)"
                        " VALUES (:id, :w, NULL, 'agent', :hash, :hash)"
                    ),
                    {"id": execution_id, "w": ws, "hash": "0" * 64},
                )
                for run_id in ("run_a", "run_b"):
                    await design_runs.create_run(
                        conn,
                        workspace_id=ws,
                        run_id=run_id,
                        document_id=None,
                        payload={},
                        execution_id=execution_id,
                    )
                # A run of the same workspace under NO execution is not part of the batch.
                await design_runs.create_run(
                    conn, workspace_id=ws, run_id=f"run_{uuid4().hex}", document_id=None
                )

                rows = await design_runs.runs_for_execution(
                    conn, workspace_id=ws, execution_id=execution_id
                )
                assert [row["run_id"] for row in rows] == ["run_a", "run_b"]
                # The ported DTO shape, not the durable-job view.
                assert set(rows[0]) == {
                    "run_id",
                    "status",
                    "document_id",
                    "result",
                    "created_at",
                    "updated_at",
                }
                # Fail-closed tenancy: the same execution id read from another workspace is empty.
                assert (
                    await design_runs.runs_for_execution(
                        conn, workspace_id=other_ws, execution_id=execution_id
                    )
                    == []
                )
            finally:
                await trans.rollback()

    run_async(scenario())
