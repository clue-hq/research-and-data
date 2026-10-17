"""A running site turn's working copy, and the prune that ends it (site-turn durability, Task 3).

One row per running site turn in ``design_site_turn_workspace``, overwritten in place: the text of
the turn's editable files and its in-memory turn state, stamped with the LangGraph checkpoint id
they match. A takeover after a worker dies lays the files over a folder rebuilt from the stored
site and resumes the conversation from that checkpoint
(docs/superpowers/plans/2026-10-16-site-turn-durability.md §2.1).

* :func:`get_site_turn_workspace` — the takeover's read.
* :func:`put_site_turn_workspace` — the attempt's write, fenced: it lands only while the run is
  ``running`` under the writer's lease generation (when the writer names one), so a fenced-out
  attempt can never overwrite its takeover's copy.
* :func:`restamp_site_turn_workspace` — after a round that changed no file: the same fence, an
  ``UPDATE`` of the existing row only, moving its checkpoint and turn state on without the files.
* :func:`prune_site_turn_state` — deletes the copy once the run is terminal. Called from every
  terminal write in :mod:`clue_design.runs`, in the same transaction, and idempotent.
* :func:`prune_expired_site_turn_checkpoints` — deletes a finished site turn's conversation
  checkpoints once the retention has passed (96 h, founder 2026-10-17; they are kept so a finished
  turn can be traced). Only a ``site_turn`` run whose thread is its own run id: a scene or web
  turn's thread is its document's session and is never pruned here.

Callers own the transaction; nothing here commits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.enums import DesignRunKind, DesignRunStatus

#: LangGraph's checkpoint tables (platform migration ``4a94970221e9``), children first.
_CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
_TERMINAL = (DesignRunStatus.SUCCEEDED.value, DesignRunStatus.FAILED.value)


async def get_site_turn_workspace(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> JsonObject | None:
    """The run's working copy, or ``None`` when it has none."""
    row = (
        await conn.execute(
            text(
                "SELECT run_id, checkpoint_id, files, turn_state, files_sha256, attempt_generation,"
                "       updated_at"
                " FROM design_site_turn_workspace WHERE run_id = :r AND workspace_id = :w"
            ),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        return None
    return {
        "run_id": row.run_id,
        "checkpoint_id": row.checkpoint_id,
        "files": load_json(row.files),
        "turn_state": load_json(row.turn_state),
        "files_sha256": row.files_sha256,
        "attempt_generation": row.attempt_generation,
        "updated_at": iso(row.updated_at),
    }


async def put_site_turn_workspace(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    checkpoint_id: str,
    files: JsonObject,
    turn_state: JsonObject,
    files_sha256: str,
    attempt_generation: int | None,
) -> bool:
    """Write (or overwrite) the run's working copy. ``False`` = refused: the run is not
    ``running``, or (with ``attempt_generation``) it is held under another generation."""
    fence = "" if attempt_generation is None else " AND lease_generation = :gen"
    params: dict[str, Any] = {
        "r": run_id,
        "w": workspace_id,
        "c": checkpoint_id,
        "files": dump_json(files),
        "state": dump_json(turn_state),
        "sha": files_sha256,
        "gen": attempt_generation,
    }
    row = (
        await conn.execute(
            text(
                "INSERT INTO design_site_turn_workspace"
                "  (run_id, workspace_id, checkpoint_id, files, turn_state, files_sha256,"
                "   attempt_generation, updated_at)"
                " SELECT :r, :w, :c, CAST(:files AS jsonb), CAST(:state AS jsonb), :sha,"
                "        CAST(:gen AS bigint), now()"
                " FROM design_agent_run"
                " WHERE run_id = :r AND workspace_id = :w AND status = 'running'"
                + fence
                + " FOR SHARE"
                " ON CONFLICT (run_id) DO UPDATE SET"
                "   checkpoint_id = EXCLUDED.checkpoint_id, files = EXCLUDED.files,"
                "   turn_state = EXCLUDED.turn_state, files_sha256 = EXCLUDED.files_sha256,"
                "   attempt_generation = EXCLUDED.attempt_generation, updated_at = now()"
                " RETURNING run_id"
            ),
            params,
        )
    ).first()
    return row is not None


async def restamp_site_turn_workspace(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    checkpoint_id: str,
    turn_state: JsonObject,
    attempt_generation: int | None,
) -> bool:
    """Move the run's existing working copy on to ``checkpoint_id`` and ``turn_state``, keeping its
    files (a round that only read). Never inserts. ``False`` = refused: there is no copy, the run
    is not ``running``, or (with ``attempt_generation``) it is held under another generation."""
    fence = "" if attempt_generation is None else " AND run.lease_generation = :gen"
    row = (
        await conn.execute(
            text(
                "UPDATE design_site_turn_workspace AS copy SET"
                "   checkpoint_id = :c, turn_state = CAST(:state AS jsonb),"
                "   attempt_generation = CAST(:gen AS bigint), updated_at = now()"
                " WHERE copy.run_id = :r AND copy.workspace_id = :w"
                "   AND EXISTS (SELECT 1 FROM design_agent_run AS run"
                "               WHERE run.run_id = :r AND run.workspace_id = :w"
                "                 AND run.status = 'running'" + fence + " FOR SHARE)"
                " RETURNING copy.run_id"
            ),
            {
                "r": run_id,
                "w": workspace_id,
                "c": checkpoint_id,
                "state": dump_json(turn_state),
                "gen": attempt_generation,
            },
        )
    ).first()
    return row is not None


async def prune_site_turn_state(conn: AsyncConnection, *, run_id: str) -> bool:
    """Delete a terminal site turn's working copy. Idempotent.

    Does nothing (returns ``False``) unless the run is terminal. The run's conversation
    checkpoints are kept, so a finished turn can be traced from its own messages, and deleted
    once the retention has passed (:func:`prune_expired_site_turn_checkpoints`; founder
    2026-10-17: 96 hours)."""
    run = (
        await conn.execute(
            text("SELECT status FROM design_agent_run WHERE run_id = :r"),
            {"r": run_id},
        )
    ).first()
    if run is None or run.status not in _TERMINAL:
        return False
    await conn.execute(
        text("DELETE FROM design_site_turn_workspace WHERE run_id = :r"), {"r": run_id}
    )
    return True


async def prune_expired_site_turn_checkpoints(
    conn: AsyncConnection, *, retain_s: float, limit: int = 200
) -> int:
    """Delete the conversation checkpoints of site turns that finished more than ``retain_s`` ago;
    returns how many runs' conversations were deleted.

    Only a ``site_turn`` run whose checkpoint thread is its own run id (a scene or web turn's
    thread is its document's session and is never deleted here), and only a terminal one: its
    ``updated_at`` is the terminal write and nothing bumps it afterwards. Bounded by ``limit``
    per pass, oldest first. Run by the design reaper's pass."""
    rows = (
        await conn.execute(
            text(
                "SELECT r.run_id FROM design_agent_run AS r"
                " WHERE r.kind = CAST(:kind AS design_run_kind)"
                "   AND r.status = ANY(CAST(:terminal AS design_run_status[]))"
                "   AND r.checkpoint_thread_id = r.run_id"
                "   AND r.updated_at < now() - make_interval(secs => :age_s)"
                "   AND EXISTS (SELECT 1 FROM checkpoints AS c WHERE c.thread_id = r.run_id)"
                " ORDER BY r.updated_at ASC LIMIT :limit"
            ),
            {
                "kind": DesignRunKind.SITE_TURN.value,
                "terminal": list(_TERMINAL),
                "age_s": retain_s,
                "limit": limit,
            },
        )
    ).fetchall()
    threads = [row.run_id for row in rows]
    if not threads:
        return 0
    for table in _CHECKPOINT_TABLES:
        await conn.execute(
            text(f"DELETE FROM {table} WHERE thread_id = ANY(:threads)"), {"threads": threads}
        )
    return len(threads)


__all__ = [
    "get_site_turn_workspace",
    "prune_expired_site_turn_checkpoints",
    "prune_site_turn_state",
    "put_site_turn_workspace",
    "restamp_site_turn_workspace",
]
