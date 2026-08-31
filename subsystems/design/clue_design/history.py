"""Edit-envelope + operation-log DAL (Part II slice D2.2) — the append-only history port.

History is a preserved principle (founder 2026-08-07): envelopes and operations are appended,
never updated or truncated; undo/redo writes new forward envelopes. Sequences come from the
D2.1 parent-row-lock allocators, so concurrent writers serialize on the document row instead
of racing the old ``MAX+1`` read (callers hold one transaction across allocate+insert — the
O5 rule).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json, load_json_opt
from clue_design.errors import DesignNotFoundError
from clue_design.sequences import allocate_envelope_seq, allocate_operation_sequence


def new_batch_id() -> str:
    return f"batch_{uuid4().hex[:12]}"


def _envelope_from_row(row: Any) -> JsonObject:
    return {
        "batch_id": row.batch_id,
        "document_id": row.document_id,
        "seq": row.seq,
        "envelope_version": row.envelope_version,
        "base_revision": row.base_revision,
        "actor": {"kind": row.actor_kind, "id": row.actor_id},
        "source": row.source,
        "intent": row.intent,
        "checkpoint_label": row.checkpoint_label,
        "touched_targets": load_json(row.touched_targets_json),
        "operations": load_json(row.operations_json),
        "inverse_operations": load_json_opt(row.inverse_operations_json),
        "lineage": load_json_opt(row.lineage_json),
        "reverts_batch_id": row.reverts_batch_id,
        "reapplies_batch_id": row.reapplies_batch_id,
        "created_at": iso(row.created_at),
    }


def _operation_from_row(row: Any) -> JsonObject:
    return {
        "document_id": row.document_id,
        "sequence": row.sequence,
        "operation": load_json(row.operation_json),
        "actor": {"kind": row.actor_kind, "id": row.actor_id},
        "source": row.source,
        "diagnostics": load_json(row.diagnostics_json),
        "batch_id": row.batch_id,
        "created_at": iso(row.created_at),
    }


async def append_envelope(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    envelope: JsonObject,
    source: str,
    actor_kind: str,
    actor_id: str | None,
) -> str:
    batch_id = str(envelope.get("batch_id") or new_batch_id())
    seq = await allocate_envelope_seq(conn, document_id=document_id, workspace_id=workspace_id)
    await conn.execute(
        text(
            """
            INSERT INTO design_edit_envelope (
              batch_id, workspace_id, document_id, seq, envelope_version, base_revision,
              actor_kind, actor_id, source, intent, checkpoint_label,
              touched_targets_json, operations_json, inverse_operations_json,
              lineage_json, reverts_batch_id, reapplies_batch_id
            )
            VALUES (:batch, :w, :d, :seq, 1, :base, :actor_kind, :actor_id,
                    CAST(:source AS design_op_source), :intent, :label,
                    CAST(:touched AS jsonb), CAST(:ops AS jsonb), CAST(:inverse AS jsonb),
                    CAST(:lineage AS jsonb), :reverts, :reapplies)
            """
        ),
        {
            "batch": batch_id,
            "w": workspace_id,
            "d": document_id,
            "seq": seq,
            "base": envelope.get("base_revision"),
            "actor_kind": actor_kind,
            "actor_id": actor_id,
            "source": source,
            "intent": envelope.get("intent"),
            "label": envelope.get("checkpoint_label"),
            "touched": dump_json(envelope.get("touched_targets") or []),
            "ops": dump_json(envelope.get("operations") or []),
            "inverse": dump_json_opt(envelope.get("inverse_operations")),
            "lineage": dump_json_opt(envelope.get("lineage")),
            "reverts": envelope.get("reverts_batch_id"),
            "reapplies": envelope.get("reapplies_batch_id"),
        },
    )
    return batch_id


async def append_operations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    operations: list[JsonObject],
    source: str,
    actor_kind: str,
    actor_id: str | None,
    diagnostics: list[JsonObject],
    batch_id: str | None = None,
) -> None:
    if not operations:
        return
    next_sequence = await allocate_operation_sequence(
        conn, document_id=document_id, workspace_id=workspace_id
    )
    rows = [
        {
            "d": document_id,
            "w": workspace_id,
            "seq": next_sequence + offset,
            "op": dump_json(operation),
            "actor_kind": actor_kind,
            "actor_id": actor_id,
            "source": source,
            "diag": dump_json(diagnostics),
            "batch": batch_id,
        }
        for offset, operation in enumerate(operations)
    ]
    await conn.execute(
        text(
            """
            INSERT INTO design_operation_log (
              document_id, workspace_id, sequence, operation_json, actor_kind, actor_id,
              source, diagnostics_json, batch_id
            )
            VALUES (:d, :w, :seq, CAST(:op AS jsonb), :actor_kind, :actor_id,
                    CAST(:source AS design_op_source), CAST(:diag AS jsonb), :batch)
            """
        ),
        rows,
    )


async def _require_document_row(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> None:
    row = await conn.execute(
        text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
        {"d": document_id, "w": workspace_id},
    )
    if row.first() is None:
        raise DesignNotFoundError("document", document_id)


async def list_envelopes(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
) -> list[JsonObject]:
    await _require_document_row(conn, workspace_id=workspace_id, document_id=document_id)
    order = "DESC" if newest_first else "ASC"
    query = (
        "SELECT * FROM design_edit_envelope WHERE document_id = :d AND workspace_id = :w"
        f" ORDER BY seq {order}"
    )
    params: dict[str, object] = {"d": document_id, "w": workspace_id}
    if limit is not None:
        query += " LIMIT :limit OFFSET :offset"
        params.update({"limit": limit, "offset": offset})
    rows = await conn.execute(text(query), params)
    return [_envelope_from_row(row) for row in rows]


async def get_envelope(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, batch_id: str
) -> JsonObject:
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_edit_envelope"
                " WHERE document_id = :d AND workspace_id = :w AND batch_id = :b"
            ),
            {"d": document_id, "w": workspace_id, "b": batch_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("edit_envelope", batch_id)
    return _envelope_from_row(row)


async def list_operations(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> list[JsonObject]:
    await _require_document_row(conn, workspace_id=workspace_id, document_id=document_id)
    rows = await conn.execute(
        text(
            "SELECT * FROM design_operation_log"
            " WHERE document_id = :d AND workspace_id = :w ORDER BY sequence ASC"
        ),
        {"d": document_id, "w": workspace_id},
    )
    return [_operation_from_row(row) for row in rows]
