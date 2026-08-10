"""Document-diagnostics DAL (Part II slice D2.2) — append-only, latest-per-kind reads."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError


def _diagnostics_from_row(row: Any) -> JsonObject:
    return {
        "document_id": row.document_id,
        "kind": row.kind,
        "diagnostics": load_json(row.diagnostics_json),
        "created_at": iso(row.created_at),
    }


async def store_diagnostics(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    kind: str,
    diagnostics: list[JsonObject],
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO design_document_diagnostic
              (workspace_id, document_id, kind, diagnostics_json)
            VALUES (:w, :d, :kind, CAST(:diag AS jsonb))
            """
        ),
        {"w": workspace_id, "d": document_id, "kind": kind, "diag": dump_json(diagnostics)},
    )


async def latest_diagnostics(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    kind: str | None = None,
) -> JsonObject | None:
    exists = await conn.execute(
        text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
        {"d": document_id, "w": workspace_id},
    )
    if exists.first() is None:
        raise DesignNotFoundError("document", document_id)
    query = "SELECT * FROM design_document_diagnostic WHERE document_id = :d AND workspace_id = :w"
    params: dict[str, object] = {"d": document_id, "w": workspace_id}
    if kind is not None:
        query += " AND kind = :kind"
        params["kind"] = kind
    query += " ORDER BY id DESC LIMIT 1"
    row = (await conn.execute(text(query), params)).first()
    return None if row is None else _diagnostics_from_row(row)
