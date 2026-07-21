"""The snapshot seam: **sync capture, async flush** (PB-B2.3).

The modality-adapter chain (``run_chain``: fetch → adapt → extract → materialize) is synchronous
and connection-less, but durable storage and the ``artifact`` row are async I/O. This module
bridges the two the same way ``adapters/cache.py`` does for caching — a small, caller-owned,
in-memory object handed *into* the sync chain:

* :meth:`SnapshotSink.capture` runs inside the sync chain, at the exact moment the fetched bytes
  exist. It computes the deterministic content-addressed key (pure sha256 work — no I/O) and
  buffers the bytes; the returned key is stamped onto every claim extracted from that fetch.
* :func:`flush_snapshots` runs in the async caller (``run_pipeline`` before persisting; the
  waterfall before its insert loop), doing the real work: ``storage.put`` + the ``artifact`` row
  — **before** the claims are inserted, so the ``claim.artifact_key`` FK always lands on an
  existing row. Content-addressing makes the whole flush idempotent: re-flushing (or two sinks
  capturing the same page) converges on one blob + one row.

The sink is per-run and workspace-scoped at construction: keys are ``{workspace|public}/{sha}``,
so tenant snapshots never dedup across workspaces (PB-B2 ruling 2).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import RawArtifact
from clue_storage.artifacts import record_artifact
from clue_storage.protocol import StorageBackend, artifact_key, content_address


class PendingSnapshot(BaseModel):
    """One captured-but-not-yet-flushed snapshot (bytes + the artifact-row metadata)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage_key: str
    content: bytes
    content_sha256: str
    media_type: str
    source_key: str | None = None
    source_url: str | None = None


class SnapshotSink:
    """Caller-owned, in-memory capture buffer for one run's evidence snapshots."""

    def __init__(self, *, workspace_id: str | None = None) -> None:
        self._workspace_id = workspace_id
        self._pending: dict[str, PendingSnapshot] = {}

    @property
    def workspace_id(self) -> str | None:
        return self._workspace_id

    @property
    def pending(self) -> tuple[PendingSnapshot, ...]:
        """The captures awaiting :func:`flush_snapshots` (content-addressed, so already deduped)."""
        return tuple(self._pending.values())

    def clear(self) -> None:
        """Drop every pending capture (flush calls this after durably storing them all)."""
        self._pending.clear()

    def capture(self, raw: RawArtifact, *, source_key: str | None = None) -> str:
        """Buffer one fetched artifact and return its deterministic ``storage_key`` (pure/sync —
        safe inside the adapter chain). Capturing identical bytes again is a no-op returning the
        same key; the first capture's source link wins (same rule as the artifact-row upsert)."""
        sha = content_address(raw.content)
        key = artifact_key(self._workspace_id, sha)
        if key not in self._pending:
            self._pending[key] = PendingSnapshot(
                storage_key=key,
                content=raw.content,
                content_sha256=sha,
                media_type=raw.media_type,
                source_key=source_key,
                source_url=raw.ref,
            )
        return key


async def flush_snapshots(
    conn: AsyncConnection, storage: StorageBackend, sink: SnapshotSink
) -> int:
    """Durably store every pending capture (blob + ``artifact`` row) and drain the sink.

    Call **before** inserting the claims that carry the sink's keys (the FK ordering). Returns
    the number of snapshots flushed. Idempotent end to end: ``put`` at a content-addressed key
    is a no-op overwrite and the row insert is ``ON CONFLICT DO NOTHING``.
    """
    flushed = 0
    for pending in sink.pending:
        await storage.put(pending.storage_key, pending.content, media_type=pending.media_type)
        await record_artifact(
            conn,
            storage_key=pending.storage_key,
            workspace_id=sink.workspace_id,
            content_sha256=pending.content_sha256,
            media_type=pending.media_type,
            size_bytes=len(pending.content),
            source_key=pending.source_key,
            source_url=pending.source_url,
        )
        flushed += 1
    sink.clear()
    return flushed
