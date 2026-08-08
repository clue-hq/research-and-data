"""Agent-run DAL (Part II slice D2.5A) — the port of the design API's ``agent_runs`` /
``run_events`` domain, and the LAST SQLite domain to move.

Faithful port of ``lumen_api.database.Repository``'s run methods onto ``design_agent_run`` +
``design_run_event`` (PD contract §5 rows 16–17). Both tables keep their **temporary shape** —
the D1/D2 port of the daemon-thread run row and its polled SSE log. D5 reshapes the run onto the
durable job pattern (lease generation, checkpoint thread, subject columns) and D7 retires
``design_run_event`` entirely in favour of ``design.*`` topics on the platform ``run_event``
stream. Nothing here should be built on as if it were the final shape.

What the port changes, and why:

* **Fail-closed tenancy.** Every read and write is keyed ``(run_id, workspace_id)``, so a run
  belonging to another tenant is indistinguishable from one that does not exist
  (:class:`DesignNotFoundError` either way — the D2 error-taxonomy rule).
* **Race-free sequence allocation.** SQLite assigned ``run_events.seq`` with
  ``SELECT COALESCE(MAX(seq),0)+1``, race-free only under its single-writer assumption; the
  comment at that call site ("only the run's own background thread appends") was already fragile,
  and the orphan sweep appends from a *different* thread than the worker. :func:`append_run_event`
  now allocates through :func:`clue_design.sequences.allocate_run_event_seq`, which takes a
  ``FOR UPDATE`` lock on the parent run row — **inside the caller's single transaction**, the
  binding O5 atomicity rule. Allocation and insert can never be split across bridge calls.
* **``document_id`` is a real FK, so a dangling id is stored as NULL.**
  ``design_agent_run_document_fk`` references ``design_document (id, workspace_id)`` (SQLite
  deliberately had no FK). The live ``POST /agent/turns`` route passes the *editor's* document id
  with the scene inline in the payload — that document need not exist in the store at all — so
  refusing the insert would break a shipped route. :func:`create_run` therefore stores the
  reference only when the document exists in this workspace, and NULL otherwise. This is
  behaviour-preserving at the API surface: the only consumer of ``document_id`` was the
  ``LEFT JOIN documents`` that resolved ``doc_kind`` for the startup sweep, which yielded NULL
  for a dangling id anyway, and no endpoint echoes ``document_id`` back to a client. (D5's
  reshape owns the real answer: subject columns instead of a document pointer.)

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``agent_run_from_row`` / ``run_event_from_row`` exactly, with
ISO-string timestamps.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json, load_json_opt
from clue_design.errors import DesignNotFoundError
from clue_design.sequences import allocate_run_event_seq


def _agent_run_from_row(row: Any) -> JsonObject:
    return {
        "run_id": row.run_id,
        "status": row.status,
        "document_id": row.document_id,
        "result": load_json_opt(row.result_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _run_event_from_row(row: Any) -> JsonObject:
    return {
        "seq": row.seq,
        "type": row.event_type,
        "data": load_json(row.data_json),
        "created_at": iso(row.created_at),
    }


# --- runs -------------------------------------------------------------------------------------


async def get_run(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> JsonObject | None:
    """The optional read (the run-snapshot endpoint's probe): ``None``, never a raise."""
    row = (
        await conn.execute(
            text("SELECT * FROM design_agent_run WHERE run_id = :r AND workspace_id = :w"),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    return None if row is None else _agent_run_from_row(row)


async def require_run(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> JsonObject:
    """Fetch or raise. ``kind='agent_run'`` keeps the ported ``NotFoundError`` detail string."""
    run = await get_run(conn, workspace_id=workspace_id, run_id=run_id)
    if run is None:
        raise DesignNotFoundError("agent_run", run_id)
    return run


async def create_run(
    conn: AsyncConnection, *, workspace_id: str, run_id: str, document_id: str | None
) -> JsonObject:
    """Open one 'running' turn row and read it back (the ported shape).

    ``document_id`` is retained only when it names a document of THIS workspace; an unknown id
    is stored as NULL rather than rejected by ``design_agent_run_document_fk`` — see the module
    docstring for why (the async agent-turn route legitimately carries an unstored id).
    """
    resolved: str | None = None
    if document_id is not None:
        found = (
            await conn.execute(
                text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
                {"d": document_id, "w": workspace_id},
            )
        ).first()
        resolved = document_id if found is not None else None
    await conn.execute(
        text(
            "INSERT INTO design_agent_run (run_id, workspace_id, status, document_id, result_json)"
            " VALUES (:r, :w, 'running', :d, NULL)"
        ),
        {"r": run_id, "w": workspace_id, "d": resolved},
    )
    return await require_run(conn, workspace_id=workspace_id, run_id=run_id)


async def set_run_result(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    status: str,
    result: JsonObject | None,
) -> None:
    """Write the terminal status + result. Fail-closed: an unknown (or cross-workspace) run
    raises rather than silently updating nothing, which is what the SQLite UPDATE did."""
    outcome = await conn.execute(
        text(
            "UPDATE design_agent_run SET status = CAST(:s AS design_run_status),"
            " result_json = CAST(:result AS jsonb), updated_at = now()"
            " WHERE run_id = :r AND workspace_id = :w"
        ),
        {
            "s": status,
            "result": dump_json_opt(result),
            "r": run_id,
            "w": workspace_id,
        },
    )
    if outcome.rowcount == 0:
        raise DesignNotFoundError("agent_run", run_id)


async def complete_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    status: str,
    result: JsonObject | None,
    event_type: str,
    event_data: JsonObject | None = None,
) -> int:
    """Land a run's terminal result AND its terminal marker event in ONE transaction.

    Every caller that finishes a run does both writes back to back — the worker on success
    ('result'), the worker's catch-all on failure ('error'), and the restart sweep. Under SQLite
    those were two fast local commits, so the window in which a reader could see a terminal
    *status* with no terminal *event* was invisible; on Postgres, through the O5 bridge, each
    call is its own engine + round trip and the window is milliseconds wide — wide enough that
    a run-snapshot poller reliably caught the half-finished state (found by the async-turn test
    at D2.5A: status ``succeeded``, events ``[]``).

    Fusing them removes the interleaving rather than narrowing it: a reader sees the run either
    entirely running or entirely finished. Order inside the transaction matters too — the result
    is written BEFORE the marker, so the SSE stream, which reads the run row the moment it sees a
    terminal event, can never read a result that has not been committed yet.
    """
    await set_run_result(
        conn, workspace_id=workspace_id, run_id=run_id, status=status, result=result
    )
    return await append_run_event(
        conn,
        workspace_id=workspace_id,
        run_id=run_id,
        event_type=event_type,
        data=event_data,
    )


async def list_running_runs(conn: AsyncConnection, *, workspace_id: str) -> list[JsonObject]:
    """Runs still 'running' in this workspace, each with its document's ``doc_kind`` (NULL when
    the run has no document) — the ported LEFT JOIN, now a real join in one query."""
    rows = (
        await conn.execute(
            text(
                "SELECT r.run_id, r.document_id, d.doc_kind FROM design_agent_run r"
                " LEFT JOIN design_document d"
                "   ON d.id = r.document_id AND d.workspace_id = r.workspace_id"
                " WHERE r.workspace_id = :w AND r.status = 'running'"
                " ORDER BY r.created_at ASC, r.run_id ASC"
            ),
            {"w": workspace_id},
        )
    ).fetchall()
    return [
        {"run_id": row.run_id, "document_id": row.document_id, "doc_kind": row.doc_kind}
        for row in rows
    ]


async def list_running_runs_across_workspaces(conn: AsyncConnection) -> list[JsonObject]:
    """Every 'running' run in the DATABASE, with its owning ``workspace_id``.

    Deliberately **not** workspace-scoped — the one read in this module that is not, and the
    reason is structural rather than a relaxation of the tenancy rule: its only caller is the
    API's startup orphan sweep, and a process restart orphans the in-flight turns of *every*
    workspace the dead process was serving (turns run on daemon threads inside that process, so
    at startup every 'running' row is an orphan by construction). A workspace-scoped sweep would
    leave every other tenant's runs stuck 'running' forever, which is the exact live failure
    (2026-07-29) the sweep exists to prevent.

    The rows carry ``workspace_id`` precisely so the caller fails each run through a
    workspace-CORRECT store; nothing here writes, and no run payload is returned.
    (Dies at D5: a leased durable job needs no restart sweep.)
    """
    rows = (
        await conn.execute(
            text(
                "SELECT r.run_id, r.workspace_id, r.document_id, d.doc_kind"
                " FROM design_agent_run r"
                " LEFT JOIN design_document d"
                "   ON d.id = r.document_id AND d.workspace_id = r.workspace_id"
                " WHERE r.status = 'running'"
                " ORDER BY r.created_at ASC, r.run_id ASC"
            )
        )
    ).fetchall()
    return [
        {
            "run_id": row.run_id,
            "workspace_id": row.workspace_id,
            "document_id": row.document_id,
            "doc_kind": row.doc_kind,
        }
        for row in rows
    ]


# --- run events (the polled SSE log; dies at D7) -----------------------------------------------


async def append_run_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    event_type: str,
    data: JsonObject | None,
) -> int:
    """Append one event and bump the run's ``updated_at``; returns the allocated ``seq``.

    The seq comes from :func:`allocate_run_event_seq` under a ``FOR UPDATE`` lock on the parent
    run row, **in this same transaction** as the INSERT that consumes it (the O5 rule) — so
    concurrent appenders serialize instead of colliding on
    ``design_run_event_seq_unique (run_id, seq)``. The allocator is also the existence/tenancy
    gate: an unknown or cross-workspace run raises :class:`DesignNotFoundError` before anything
    is written.
    """
    seq = await allocate_run_event_seq(conn, run_id=run_id, workspace_id=workspace_id)
    await conn.execute(
        text(
            "INSERT INTO design_run_event (workspace_id, run_id, seq, event_type, data_json)"
            " VALUES (:w, :r, :seq, :t, CAST(:data AS jsonb))"
        ),
        {
            "w": workspace_id,
            "r": run_id,
            "seq": seq,
            "t": event_type,
            "data": dump_json(data or {}),
        },
    )
    await conn.execute(
        text(
            "UPDATE design_agent_run SET updated_at = now() WHERE run_id = :r AND workspace_id = :w"
        ),
        {"r": run_id, "w": workspace_id},
    )
    return seq


async def list_run_events(
    conn: AsyncConnection, *, workspace_id: str, run_id: str, after_seq: int = 0
) -> list[JsonObject]:
    """The SSE replay read: this run's events after ``after_seq``, oldest first.

    Fail-closed by construction — the workspace predicate means a cross-tenant ``run_id`` reads
    an empty list, the same answer an unknown run gives.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT * FROM design_run_event"
                " WHERE run_id = :r AND workspace_id = :w AND seq > :after"
                " ORDER BY seq ASC"
            ),
            {"r": run_id, "w": workspace_id, "after": after_seq},
        )
    ).fetchall()
    return [_run_event_from_row(row) for row in rows]
