"""The snapshot seam: **sync capture, async flush** (PB-B2.3).

The modality-adapter chain (``run_chain``: fetch → adapt → extract → materialize) is synchronous
and connection-less, but durable storage and the ``artifact`` row are async I/O. This module
bridges the two the same way ``adapters/cache.py`` does for caching — a small, caller-owned,
in-memory object handed *into* the sync chain:

* :meth:`SnapshotSink.capture` runs inside the sync chain, at the exact moment the fetched bytes
  exist. It computes the deterministic content-addressed key (pure sha256 work — no I/O) and
  buffers the bytes; the returned key is stamped onto every claim extracted from that fetch.
* :func:`flush_snapshots` runs in the async caller (``run_pipeline`` before persisting; the
  waterfall before its insert loop), doing the real work: the ``artifact`` row **then** the
  ``storage.put`` — row first, because the row's lock is what serializes writers against a
  concurrent DSAR erasure (see :mod:`clue_storage.artifacts`) — and both **before** the claims
  are inserted, so the ``claim.artifact_key`` FK always lands on an existing row.
  Content-addressing makes the whole flush idempotent: re-flushing (or two sinks capturing the
  same page) converges on one blob + one row.

**Rollback survival:** a flush deliberately does *not* drain the sink — captures stay pending
for the sink's whole lifetime (re-flushes are cheap: an idempotent row upsert + an
exists-skipped put). If the surrounding transaction rolls back, the artifact rows vanish with
it but the bytes are still in the sink, so a retried flush + insert re-converges instead of
leaving claims whose FK targets were rolled away. The sink is therefore **scoped to one run**:
create it with the run, let every transaction of the run flush it, and drop it (or call
:meth:`SnapshotSink.clear`) only after the run's final commit. A blob put by a transaction that
rolled back and was never retried is collected by
:func:`clue_storage.artifacts.sweep_orphan_blobs`.

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
        """Drop every pending capture. Call only after the run's **final commit** — a flush
        never drains the sink itself, precisely so a rolled-back transaction's captures are
        still here for the retry (see the module docstring)."""
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
    """Durably store every pending capture (``artifact`` row, then blob). Returns the number of
    captures processed. The sink is **not** drained (rollback survival — module docstring).

    Call **before** inserting the claims that carry the sink's keys (the FK ordering). Row
    before blob: ``record_artifact``'s upsert takes the artifact row lock — serializing this
    writer against a concurrent erasure's refcount decision and *resurrecting* an erased row —
    and only then is the blob (re-)put, skipped when it already exists (the common re-flush /
    dedup case; safe under the row lock we now hold, since a purge deletes only while holding
    that same lock). Idempotent end to end.
    """
    flushed = 0
    for pending in sink.pending:
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
        if not await storage.exists(pending.storage_key):
            await storage.put(pending.storage_key, pending.content, media_type=pending.media_type)
        flushed += 1
    return flushed
