"""Agent-written Puck sections (Lane B, Contract 4): one immutable row per compiled module.

A section is per WORKSPACE (founder ruling 2026-10-11): a section compiled for one site may be
placed on any site of the same workspace. The row is keyed by the sha256 of the compiled module,
so a repeat compile of the same code records nothing new. Bytes live in DesignBlobStore
(``SOURCE_KEY_SITE_SECTION``) and are never served by the public asset read.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json

__all__ = ["get_site_sections", "list_latest_site_sections", "record_site_section"]

_COLUMNS = (
    "workspace_id, digest, name, source_sha256, module_sha256, css_sha256, "
    "props_schema_json, created_at, created_by_run_id"
)


def _row(row: Any) -> JsonObject:
    return {
        "workspace_id": row.workspace_id,
        "digest": row.digest,
        "name": row.name,
        "source_sha256": row.source_sha256,
        "module_sha256": row.module_sha256,
        "css_sha256": row.css_sha256,
        "props_schema": load_json(row.props_schema_json),
        "created_at": iso(row.created_at),
        "created_by_run_id": row.created_by_run_id,
    }


async def record_site_section(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    digest: str,
    name: str,
    source_sha256: str,
    css_sha256: str,
    props_schema: JsonObject,
    created_by_run_id: str | None,
) -> JsonObject:
    """Record one compiled section, or return the row already holding this digest."""

    await conn.execute(
        text(
            "INSERT INTO design_site_section (workspace_id, digest, name, source_sha256, "
            "module_sha256, css_sha256, props_schema_json, created_by_run_id) "
            "VALUES (:w, :d, :n, :s, :d, :c, CAST(:p AS jsonb), :r) "
            "ON CONFLICT (workspace_id, digest) DO NOTHING"
        ),
        {
            "w": workspace_id,
            "d": digest,
            "n": name,
            "s": source_sha256,
            "c": css_sha256,
            "p": dump_json(props_schema),
            "r": created_by_run_id,
        },
    )
    rows = await get_site_sections(conn, workspace_id=workspace_id, digests=[digest])
    return rows[0]


async def get_site_sections(
    conn: AsyncConnection, *, workspace_id: str, digests: Sequence[str]
) -> list[JsonObject]:
    """This workspace's rows for ``digests``, in the order asked; a missing digest is left out."""

    wanted = list(dict.fromkeys(digests))
    if not wanted:
        return []
    rows = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM design_site_section "
            "WHERE workspace_id = :w AND digest = ANY(:d)"
        ),
        {"w": workspace_id, "d": wanted},
    )
    by_digest = {row.digest: _row(row) for row in rows}
    return [by_digest[digest] for digest in wanted if digest in by_digest]


async def list_latest_site_sections(
    conn: AsyncConnection, *, workspace_id: str
) -> list[JsonObject]:
    """The newest section of each name in this workspace, sorted by name."""

    rows = await conn.execute(
        text(
            f"SELECT DISTINCT ON (name) {_COLUMNS} FROM design_site_section "
            "WHERE workspace_id = :w ORDER BY name, created_at DESC, digest"
        ),
        {"w": workspace_id},
    )
    return [_row(row) for row in rows]
