"""The ``artifact`` table DAL (PB-B2.2) — snapshot rows + the DSAR refcount read.

Plain async functions over ``AsyncConnection`` in the repo's raw-SQL style (the ``clue_spine``
pattern: one implementation will ever exist, so no repository/service layer). The table's UNIQUE
``storage_key`` makes :func:`record_artifact` the dedup — identical bytes in one workspace land
on one row, however many times a fetch (or a re-flush of the same sink) records them.

``live_claim_count`` is the PB-B2 ruling-2 refcount: how many *live* (non-superseded) claims
still cite a snapshot as evidence. DSAR erasure deletes the physical blob only when it reaches
zero; the row itself is never deleted — :func:`mark_erased` stamps ``erased_at`` and the metadata
(key/hash/size — no personal content) survives as the audit trail.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime


class ArtifactRecord(BaseModel):
    """An ``artifact`` row — the DB identity of one stored evidence snapshot (REQ-07)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    storage_key: str
    workspace_id: str | None = None
    content_sha256: str
    media_type: str
    size_bytes: int
    source_key: str | None = None
    source_url: str | None = None
    created_at: UtcDatetime
    erased_at: UtcDatetime | None = None


_COLUMNS = (
    "artifact_id, storage_key, workspace_id, content_sha256, media_type, size_bytes, "
    "source_key, source_url, created_at, erased_at"
)


async def record_artifact(
    conn: AsyncConnection,
    *,
    storage_key: str,
    workspace_id: str | None,
    content_sha256: str,
    media_type: str,
    size_bytes: int,
    source_key: str | None = None,
    source_url: str | None = None,
) -> ArtifactRecord:
    """Upsert one snapshot row and return the canonical record.

    ``ON CONFLICT (storage_key) DO NOTHING``: the key is content-addressed, so a conflict means
    the identical bytes are already recorded — the existing row (with its original timestamps
    and source link) wins, and re-flushing a snapshot sink is a true no-op.
    """
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes, source_key, source_url) "
            "VALUES (:storage_key, :workspace_id, :content_sha256, :media_type, :size_bytes, "
            ":source_key, :source_url) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {
            "storage_key": storage_key,
            "workspace_id": workspace_id,
            "content_sha256": content_sha256,
            "media_type": media_type,
            "size_bytes": size_bytes,
            "source_key": source_key,
            "source_url": source_url,
        },
    )
    record = await get_artifact(conn, storage_key)
    if record is None:  # pragma: no cover - unreachable inside one transaction
        raise RuntimeError(f"artifact {storage_key!r} vanished during record")
    return record


async def get_artifact(conn: AsyncConnection, storage_key: str) -> ArtifactRecord | None:
    result = await conn.execute(
        text(f"SELECT {_COLUMNS} FROM artifact WHERE storage_key = :storage_key"),
        {"storage_key": storage_key},
    )
    row = result.mappings().first()
    if row is None:
        return None
    data = dict(row)
    data["artifact_id"] = str(data["artifact_id"])
    return ArtifactRecord(**data)


async def live_claim_count(conn: AsyncConnection, storage_key: str) -> int:
    """How many live (non-superseded) claims still cite this snapshot — the DSAR refcount.

    Deliberately counts *all* non-superseded claims regardless of verification status (the
    fail-safe direction: an unverified-but-live claim keeps its evidence). Erasure tombstones
    supersede the claim row, so an erased person's claims drop out of this count.
    """
    result = await conn.execute(
        text(
            "SELECT count(*) FROM claim WHERE artifact_key = :storage_key AND superseded_by IS NULL"
        ),
        {"storage_key": storage_key},
    )
    return int(result.scalar_one())


async def mark_erased(conn: AsyncConnection, storage_key: str) -> None:
    """Stamp ``erased_at`` (idempotent — the first erasure's timestamp is the audit fact)."""
    await conn.execute(
        text(
            "UPDATE artifact SET erased_at = now() "
            "WHERE storage_key = :storage_key AND erased_at IS NULL"
        ),
        {"storage_key": storage_key},
    )
