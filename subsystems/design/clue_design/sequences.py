"""Per-parent sequence allocation for the design history tables (Part II slice D2.1).

The merged design subsystem assigned ``operation_log.sequence`` / ``edit_envelopes.seq``
with ``SELECT COALESCE(MAX(..),0)+1`` — race-free only under SQLite's
single-writer assumption. The D1 contract (PD §4) replaces that with allocation under a
``SELECT … FOR UPDATE`` row lock on the parent (``design_document`` / ``design_agent_run``):
concurrent allocators serialize on the parent row, so each transaction sees the true MAX and
sequences stay gapless and per-parent monotonic — the property the undo substrate relies on.

(A third allocator, ``allocate_run_event_seq``, died at D7 with ``design_run_event``: the design
run's stream ids are now the platform ``run_event`` table's own global ``seq``, which the database
assigns — nothing to allocate, and nothing to lock the run row for.)

Contract (O5 atomicity rule, binding): **the allocation and the insert that uses it must live
in ONE transaction on ONE connection** — the returned number is only safe while the parent
row lock is held. Never allocate in one ``asyncio.run`` bridge call and insert in another.

The allocators are fail-closed on tenancy: the parent is located by ``(id, workspace_id)``,
so a cross-workspace (or absent) parent raises :class:`DesignNotFoundError` — same refusal
either way, existence never leaks (the D2 error taxonomy's rule).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design.errors import DesignNotFoundError

__all__ = [
    "allocate_envelope_seq",
    "allocate_operation_sequence",
]


async def _allocate(
    conn: AsyncConnection,
    *,
    parent_table: str,
    parent_pk: str,
    parent_kind: str,
    parent_id: str,
    workspace_id: str,
    child_table: str,
    child_fk: str,
    seq_column: str,
) -> int:
    """Lock the parent row, then hand out ``MAX(seq)+1`` over the child table.

    Table/column names are supplied by the three public wrappers below (never caller input),
    so the f-string SQL is closed over a fixed vocabulary; values travel as bound parameters.
    """
    locked = await conn.execute(
        text(
            f"SELECT 1 FROM {parent_table} "  # noqa: S608 - identifiers are module-fixed
            f"WHERE {parent_pk} = :parent_id AND workspace_id = :workspace_id FOR UPDATE"
        ),
        {"parent_id": parent_id, "workspace_id": workspace_id},
    )
    if locked.first() is None:
        raise DesignNotFoundError(parent_kind, parent_id)
    row = await conn.execute(
        text(
            f"SELECT COALESCE(MAX({seq_column}), 0) + 1 FROM {child_table} "  # noqa: S608
            f"WHERE {child_fk} = :parent_id AND workspace_id = :workspace_id"
        ),
        {"parent_id": parent_id, "workspace_id": workspace_id},
    )
    return int(row.scalar_one())


async def allocate_envelope_seq(
    conn: AsyncConnection, *, document_id: str, workspace_id: str
) -> int:
    """Next ``design_edit_envelope.seq`` for a document, under the document row lock."""
    return await _allocate(
        conn,
        parent_table="design_document",
        parent_pk="id",
        parent_kind="design_document",
        parent_id=document_id,
        workspace_id=workspace_id,
        child_table="design_edit_envelope",
        child_fk="document_id",
        seq_column="seq",
    )


async def allocate_operation_sequence(
    conn: AsyncConnection, *, document_id: str, workspace_id: str
) -> int:
    """Next ``design_operation_log.sequence`` for a document, under the document row lock."""
    return await _allocate(
        conn,
        parent_table="design_document",
        parent_pk="id",
        parent_kind="design_document",
        parent_id=document_id,
        workspace_id=workspace_id,
        child_table="design_operation_log",
        child_fk="document_id",
        seq_column="sequence",
    )
