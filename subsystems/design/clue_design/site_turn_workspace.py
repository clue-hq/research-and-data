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
* :func:`prune_site_turn_state` — deletes the copy and the run's conversation checkpoints once the
  run is terminal. Called from every terminal write in :mod:`clue_design.runs`, in the same
  transaction, and idempotent. Checkpoints are touched only for a ``site_turn`` run whose thread is
  its own run id: a scene or web turn's thread is its document's session and is never pruned here.

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


async def prune_site_turn_state(conn: AsyncConnection, *, run_id: str) -> bool:
    """Delete a terminal site turn's working copy and conversation checkpoints. Idempotent.

    Does nothing (returns ``False``) unless the run is terminal; checkpoints are deleted only for
    a ``site_turn`` run whose checkpoint thread is its own run id."""
    run = (
        await conn.execute(
            text(
                "SELECT kind, status, checkpoint_thread_id FROM design_agent_run WHERE run_id = :r"
            ),
            {"r": run_id},
        )
    ).first()
    if run is None or run.status not in _TERMINAL:
        return False
    await conn.execute(
        text("DELETE FROM design_site_turn_workspace WHERE run_id = :r"), {"r": run_id}
    )
    if run.kind == DesignRunKind.SITE_TURN.value and run.checkpoint_thread_id == run_id:
        for table in _CHECKPOINT_TABLES:
            await conn.execute(text(f"DELETE FROM {table} WHERE thread_id = :r"), {"r": run_id})
    return True


__all__ = ["get_site_turn_workspace", "prune_site_turn_state", "put_site_turn_workspace"]
