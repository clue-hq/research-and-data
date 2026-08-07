"""Snapshot + template-revision DAL (Part II slice D2.2).

Snapshots are explicit full-scene copies (never compaction); template revisions are the frozen
scenes the personalization plane (D1d/D2.4) derives against. Ported verbatim from the SQLite
layer, workspace-scoped and fail-closed per the D2 error taxonomy.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json, load_json_opt
from clue_design.documents import get_document
from clue_design.errors import DesignNotFoundError


def _snapshot_from_row(row: Any) -> JsonObject:
    return {
        "snapshot_id": row.snapshot_id,
        "document_id": row.document_id,
        "version": row.version,
        "scene": load_json(row.scene_json),
        "reason": row.reason,
        "created_at": iso(row.created_at),
    }


def _template_revision_from_row(row: Any) -> JsonObject:
    return {
        "template_revision_id": row.template_revision_id,
        "document_id": row.document_id,
        "source_snapshot_id": row.source_snapshot_id,
        "version": row.version,
        "scene": load_json(row.scene_json),
        "export_profiles": load_json(row.export_profiles_json),
        "slot_summary": load_json(row.slot_summary_json),
        "brand_ref": load_json_opt(row.brand_ref_json),
        "created_at": iso(row.created_at),
    }


async def create_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    snapshot_id: str,
    reason: str,
) -> JsonObject:
    document = await get_document(conn, workspace_id=workspace_id, document_id=document_id)
    await conn.execute(
        text(
            """
            INSERT INTO design_snapshot
              (snapshot_id, workspace_id, document_id, version, scene_json, reason)
            VALUES (:s, :w, :d, :version, CAST(:scene AS jsonb), :reason)
            """
        ),
        {
            "s": snapshot_id,
            "w": workspace_id,
            "d": document_id,
            "version": document["current_version"],
            "scene": dump_json(document["scene"]),
            "reason": reason,
        },
    )
    return await get_snapshot(
        conn, workspace_id=workspace_id, document_id=document_id, snapshot_id=snapshot_id
    )


async def list_snapshots(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> list[JsonObject]:
    await get_document(conn, workspace_id=workspace_id, document_id=document_id)
    rows = await conn.execute(
        text(
            "SELECT * FROM design_snapshot"
            " WHERE document_id = :d AND workspace_id = :w ORDER BY created_at ASC"
        ),
        {"d": document_id, "w": workspace_id},
    )
    return [_snapshot_from_row(row) for row in rows]


async def get_snapshot(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, snapshot_id: str
) -> JsonObject:
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_snapshot"
                " WHERE document_id = :d AND workspace_id = :w AND snapshot_id = :s"
            ),
            {"d": document_id, "w": workspace_id, "s": snapshot_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("snapshot", snapshot_id)
    return _snapshot_from_row(row)


async def create_template_revision(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    template_revision_id: str,
    source_snapshot_id: str | None,
    scene: JsonObject,
    slot_summary: list[JsonObject],
) -> JsonObject:
    document = await get_document(conn, workspace_id=workspace_id, document_id=document_id)
    await conn.execute(
        text(
            """
            INSERT INTO design_template_revision (
              template_revision_id, workspace_id, document_id, source_snapshot_id,
              version, scene_json, export_profiles_json, slot_summary_json, brand_ref_json
            )
            VALUES (:r, :w, :d, :snap, :version, CAST(:scene AS jsonb),
                    CAST(:profiles AS jsonb), CAST(:slots AS jsonb), CAST(:brand AS jsonb))
            """
        ),
        {
            "r": template_revision_id,
            "w": workspace_id,
            "d": document_id,
            "snap": source_snapshot_id,
            "version": document["current_version"] + 1,
            "scene": dump_json(scene),
            "profiles": dump_json(scene.get("export_profiles", [])),
            "slots": dump_json(slot_summary),
            "brand": dump_json_opt(scene.get("meta", {}).get("brand_kit")),
        },
    )
    return await get_template_revision(
        conn, workspace_id=workspace_id, template_revision_id=template_revision_id
    )


async def get_template_revision(
    conn: AsyncConnection, *, workspace_id: str, template_revision_id: str
) -> JsonObject:
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_template_revision"
                " WHERE template_revision_id = :r AND workspace_id = :w"
            ),
            {"r": template_revision_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("template_revision", template_revision_id)
    return _template_revision_from_row(row)
