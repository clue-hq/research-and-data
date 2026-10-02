"""The images a past turn was sent with, read back for the conversation layer.

Ruling 2 (spec 2026-09-18): a picture the user already attached stays visible for the rest of the
thread, so a later turn can still be asked about it. History loaders call :func:`turn_image_refs`
once for a whole page of turns and hand each message its own attachments; the conversation layer
then decides how many of them the thread can afford.

Only images come back. Everything else a turn carried (a text file, a pdf) already became a
project document the agent opens deliberately with a tool, so re-sending its bytes every turn
would buy nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef


async def turn_image_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_ids: Sequence[UUID],
) -> dict[UUID, tuple[ArtifactRef, ...]]:
    """Map each turn id to the image attachments that turn was submitted with, in ordinal order.

    Turns with no image attachments are simply absent from the result. An erased, purged or
    tombstoned artifact is left out on exactly the terms the history-body hydrator uses
    (``chat/message_bodies.py``), because the durable store refuses to read one: naming an image
    nobody can read would raise ``ArtifactNotFound`` on every later turn of that thread.
    """

    if not turn_ids:
        return {}
    result = await conn.execute(
        text(
            "SELECT r.turn_id, r.artifact_key, r.artifact_sha256, a.media_type, a.size_bytes "
            "FROM agent_artifact_ref r "
            "JOIN artifact a ON a.storage_key = r.artifact_key "
            "WHERE r.workspace_id = :workspace AND r.owner_kind = 'turn' "
            "AND r.ref_role = 'attachment' AND r.turn_id = ANY(:turn_ids) "
            "AND a.media_type LIKE 'image/%' "
            "AND a.erased_at IS NULL AND a.purged_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM agent_artifact_tombstone t "
            "                WHERE t.workspace_id = a.workspace_id "
            "                  AND t.artifact_key = a.storage_key) "
            "ORDER BY r.turn_id, r.ordinal"
        ),
        {"workspace": workspace_id, "turn_ids": list(turn_ids)},
    )
    images: dict[UUID, list[ArtifactRef]] = {}
    for row in result.mappings():
        images.setdefault(row["turn_id"], []).append(
            ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=row["artifact_key"],
                sha256=row["artifact_sha256"],
                media_type=row["media_type"],
                byte_count=int(row["size_bytes"]),
            )
        )
    return {turn_id: tuple(refs) for turn_id, refs in images.items()}
