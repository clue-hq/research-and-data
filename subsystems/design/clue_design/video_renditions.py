"""A captured video's poster and smaller rendition, by the video's digest.

Table ``design_video_rendition`` (brand facts plan 2026-10-17, Task 4). The capture makes them with
ffmpeg and stores them as blobs; this table only names them, beside the immutable fragment payload.
Callers own the transaction.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection


async def get_many(
    conn: AsyncConnection, *, workspace_id: str, video_digests: list[str]
) -> dict[str, dict[str, str | None]]:
    """``{video digest: {"poster": digest or None, "rendition": digest or None}}``."""
    if not video_digests:
        return {}
    rows = await conn.execute(
        text(
            "SELECT video_digest, poster_digest, rendition_digest FROM design_video_rendition "
            "WHERE workspace_id = :w AND video_digest IN :digests"
        ).bindparams(bindparam("digests", expanding=True)),
        {"w": workspace_id, "digests": list(video_digests)},
    )
    return {
        row.video_digest: {"poster": row.poster_digest, "rendition": row.rendition_digest}
        for row in rows
    }


async def put(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    video_digest: str,
    poster_digest: str | None,
    rendition_digest: str | None,
) -> None:
    """Record what was made for one video; the first writer wins (same bytes, same files)."""
    await conn.execute(
        text(
            "INSERT INTO design_video_rendition "
            "(workspace_id, video_digest, poster_digest, rendition_digest) "
            "VALUES (:w, :v, :p, :r) ON CONFLICT (workspace_id, video_digest) DO NOTHING"
        ),
        {"w": workspace_id, "v": video_digest, "p": poster_digest, "r": rendition_digest},
    )
