"""Document-thumbnail cache index (design gallery cards).

One row per ``(workspace, document, version)``: which blob-store digest holds the rendered PNG a
gallery card shows. The bytes themselves live where every other design blob lives — platform
storage under ``{workspace_id}/design/{sha256}`` (:mod:`clue_design.storage`) — so this table
holds no image data, only the pointer that saves a re-render.

**A pure cache, so no FK anywhere.** Not to the ``artifact`` row: a digest whose blob a DSAR
purge or a backend move took away is repaired by regenerating the thumbnail at read time, and a
constraint would turn that self-healing miss into a write failure. Not to ``design_document``
either: a cache must never be the thing that blocks a document delete. Rows for superseded
versions are simply kept — blobs are content-addressed, so a duplicate render costs nothing, and
pruning is future work rather than something a read path should be doing.

Reads answer ``None`` for a miss rather than raising: "this card has no cached PNG yet" is the
normal first read, not a failure. Both functions are keyed on ``workspace_id`` first, so one
tenant's cached thumbnail is neither readable nor overwritable from another workspace.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject


def _thumbnail_from_row(row: Any) -> JsonObject:
    return {"sha256": row.sha256, "media_type": row.media_type}


async def get_document_thumbnail(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, version: int
) -> JsonObject | None:
    """The cached thumbnail for one document version, or ``None`` when nothing is cached."""
    result = await conn.execute(
        text(
            "SELECT sha256, media_type FROM design_document_thumbnail"
            " WHERE workspace_id = :w AND document_id = :d AND version = :v"
        ),
        {"w": workspace_id, "d": document_id, "v": version},
    )
    row = result.one_or_none()
    return None if row is None else _thumbnail_from_row(row)


async def get_latest_document_thumbnail(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> JsonObject | None:
    """The newest cached thumbnail of a document, with its ``version``, or ``None``.

    The stand-in a gallery card shows while its current version renders in the background.
    """
    result = await conn.execute(
        text(
            "SELECT sha256, media_type, version FROM design_document_thumbnail"
            " WHERE workspace_id = :w AND document_id = :d"
            " ORDER BY version DESC LIMIT 1"
        ),
        {"w": workspace_id, "d": document_id},
    )
    row = result.one_or_none()
    return None if row is None else {**_thumbnail_from_row(row), "version": row.version}


async def record_document_thumbnail(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    version: int,
    sha256: str,
    media_type: str,
) -> JsonObject:
    """Claim the ``(document, version)`` thumbnail slot — an idempotent upsert, and the last
    render wins.

    ``DO UPDATE`` rather than ``DO NOTHING`` because a second record is a *newer* answer, not a
    duplicate one: two renders of the same version race only when the first one's blob went
    missing and a read triggered a repair, and the repaired digest is the one the card must
    show. Returns the row as stored, so a caller never has to read back what it just wrote.
    """
    result = await conn.execute(
        text(
            """
            INSERT INTO design_document_thumbnail
                (workspace_id, document_id, version, sha256, media_type)
            VALUES (:w, :d, :v, :sha256, :media_type)
            ON CONFLICT (workspace_id, document_id, version) DO UPDATE SET
              sha256 = excluded.sha256,
              media_type = excluded.media_type
            RETURNING sha256, media_type
            """
        ),
        {
            "w": workspace_id,
            "d": document_id,
            "v": version,
            "sha256": sha256,
            "media_type": media_type,
        },
    )
    return _thumbnail_from_row(result.one())
