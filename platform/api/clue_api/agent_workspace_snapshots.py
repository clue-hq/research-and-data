"""The snapshot store: a chat's agent-folder snapshots in Postgres and the artifact store.

F3 Phase 1 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md,
WS-1–WS-3, WS-8, WS-10; rulings AW-1, AW-10, AW-13). Every file of a snapshot is stored once under
its content address in the chat's workspace; one file list names them; one row in
``agent_workspace_snapshot`` names the current file list. A save moves that row with a
compare-and-set on the version the turn restored, in the same transaction as the fleet-lease check,
so a worker that lost the chat's lease, or a turn that raced another, never overwrites a newer
version. Files are always stored before the row moves, so a row never names missing bytes.

The snapshot's files are held through ``artifact_reference`` rows of kind
:data:`SNAPSHOT_REFERENCE_KIND`, which always name exactly the current version; Phase 2 erases what
nothing references any more.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.ports import WorkspaceSnapshotStore
from clue_agents.workspace_snapshot import (
    MANIFEST_MEDIA_TYPE,
    LeaseFence,
    SaveStatus,
    SnapshotCorrupt,
    SnapshotEntry,
    SnapshotManifest,
    SnapshotPointer,
    WorkspaceRestoreUnavailable,
    WorkspaceSaveUnavailable,
    decode_manifest,
    encode_manifest,
)
from clue_db import ConnFactory, transaction
from clue_fleet.lease import LeaseGeneration, WorkId, hold_work_lease
from clue_storage import (
    ArtifactNotFound,
    ArtifactRecord,
    StorageBackend,
    StorageError,
    artifact_key,
    get_artifact,
    record_artifact,
    release_artifacts,
    retain_artifact,
)

__all__ = ["SNAPSHOT_REFERENCE_KIND", "DbWorkspaceSnapshotStore"]

#: The ``artifact_reference`` kind a snapshot holds its files under; the id is the thread id.
SNAPSHOT_REFERENCE_KIND = "agent_workspace_snapshot"

_CURRENT = text(
    "SELECT version, manifest_sha256, manifest_artifact_key FROM agent_workspace_snapshot "
    "WHERE workspace_id = :ws AND thread_id = :thread"
)
_INSERT_FIRST = text(
    "INSERT INTO agent_workspace_snapshot (workspace_id, thread_id, project_id, version, "
    "manifest_artifact_key, manifest_sha256) VALUES (:ws, :thread, :project, 1, :key, :sha) "
    "ON CONFLICT (workspace_id, thread_id) DO NOTHING RETURNING version"
)
_ADVANCE = text(
    "UPDATE agent_workspace_snapshot SET version = version + 1, manifest_artifact_key = :key, "
    "manifest_sha256 = :sha, last_activity_at = now(), updated_at = now() "
    "WHERE workspace_id = :ws AND thread_id = :thread AND version = :expected RETURNING version"
)
_TOUCH = text(
    "UPDATE agent_workspace_snapshot SET last_activity_at = now() "
    "WHERE workspace_id = :ws AND thread_id = :thread"
)
_FORGET = text(
    "DELETE FROM agent_workspace_snapshot WHERE workspace_id = :ws AND thread_id = :thread"
)


class DbWorkspaceSnapshotStore(WorkspaceSnapshotStore):
    """:class:`~clue_agents.ports.WorkspaceSnapshotStore` over Postgres and a storage backend."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        concurrency: int = 16,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory
        self._concurrency = max(1, concurrency)

    async def current(self, *, workspace_id: str, thread_id: str) -> SnapshotPointer | None:
        async with self._conn_factory() as conn:
            row = (await conn.execute(_CURRENT, {"ws": workspace_id, "thread": thread_id})).first()
        if row is None:
            return None
        return SnapshotPointer(
            version=int(row[0]), manifest_sha256=str(row[1]), manifest_key=str(row[2])
        )

    async def read_manifest(
        self, *, workspace_id: str, pointer: SnapshotPointer
    ) -> SnapshotManifest:
        data = await self._read_verified(
            workspace_id=workspace_id,
            key=pointer.manifest_key,
            sha256=pointer.manifest_sha256,
            size=None,
        )
        return decode_manifest(data)

    async def read_file(self, *, workspace_id: str, entry: SnapshotEntry) -> bytes:
        return await self._read_verified(
            workspace_id=workspace_id,
            key=artifact_key(workspace_id, entry.sha256),
            sha256=entry.sha256,
            size=entry.size,
        )

    async def store_files(
        self, *, workspace_id: str, files: Sequence[tuple[SnapshotEntry, bytes]]
    ) -> int:
        """Store each file not already live under its content address; return how many were put.

        The ``artifact`` row is recorded before the put (``record_artifact``'s rule: the row is the
        lock that serialises writers against an erasure). Identical bytes in two entries are put
        once.
        """

        unique: dict[str, tuple[str, bytes]] = {}
        for entry, data in files:
            if hashlib.sha256(data).hexdigest() != entry.sha256 or len(data) != entry.size:
                raise SnapshotCorrupt(f"bytes for {entry.path!r} do not match their entry")
            unique.setdefault(entry.sha256, (entry.media_type, data))
        gate = asyncio.Semaphore(self._concurrency)

        async def one(sha256: str, media_type: str, data: bytes) -> bool:
            async with gate:
                return await self._store_one(
                    workspace_id=workspace_id, sha256=sha256, media_type=media_type, data=data
                )

        results = await asyncio.gather(
            *(one(sha, media_type, data) for sha, (media_type, data) in unique.items())
        )
        return sum(results)

    async def save(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        expected_version: int | None,
        manifest: SnapshotManifest,
        fence: LeaseFence | None,
    ) -> tuple[SaveStatus, SnapshotPointer | None]:
        body = encode_manifest(manifest)
        manifest_sha = hashlib.sha256(body).hexdigest()
        manifest_key = artifact_key(workspace_id, manifest_sha)
        await self._store_one(
            workspace_id=workspace_id,
            sha256=manifest_sha,
            media_type=MANIFEST_MEDIA_TYPE,
            data=body,
        )
        async with self._conn_factory() as conn:
            if fence is not None and not await hold_work_lease(
                conn,
                work_id=WorkId(fence.work_id),
                worker_id=fence.worker_id,
                generation=LeaseGeneration(fence.generation),
            ):
                return "fenced", None
            params = {
                "ws": workspace_id,
                "thread": thread_id,
                "project": project_id,
                "key": manifest_key,
                "sha": manifest_sha,
                "expected": expected_version,
            }
            statement = _INSERT_FIRST if expected_version is None else _ADVANCE
            row = (await conn.execute(statement, params)).first()
            if row is None:
                return "stale", None
            await self._hold_current(
                conn,
                workspace_id=workspace_id,
                thread_id=thread_id,
                keys=(
                    manifest_key,
                    *(artifact_key(workspace_id, e.sha256) for e in manifest.entries),
                ),
            )
        return "saved", SnapshotPointer(
            version=int(row[0]), manifest_sha256=manifest_sha, manifest_key=manifest_key
        )

    async def touch(self, *, workspace_id: str, thread_id: str) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(_TOUCH, {"ws": workspace_id, "thread": thread_id})

    async def forget(self, *, workspace_id: str, thread_id: str) -> None:
        """Delete the chat's version record and its holds; Phase 2 erases the bytes (WS-31)."""

        async with self._conn_factory() as conn:
            await conn.execute(_FORGET, {"ws": workspace_id, "thread": thread_id})
            await release_artifacts(
                conn,
                workspace_id=workspace_id,
                reference_kind=SNAPSHOT_REFERENCE_KIND,
                reference_id=thread_id,
            )

    # --- internals ------------------------------------------------------------------------------

    async def _store_one(
        self, *, workspace_id: str, sha256: str, media_type: str, data: bytes
    ) -> bool:
        key = artifact_key(workspace_id, sha256)
        async with self._conn_factory() as conn:
            existing = await get_artifact(conn, key)
            live = (
                _is_live(existing)
                and existing is not None
                and existing.workspace_id == workspace_id
            )
            if not live:
                await record_artifact(
                    conn,
                    storage_key=key,
                    workspace_id=workspace_id,
                    content_sha256=sha256,
                    media_type=media_type,
                    size_bytes=len(data),
                )
        try:
            # The row is committed before the upload, so a live row alone does not prove the bytes
            # are stored: an upload that failed (or a writer that died) leaves exactly that. Check
            # storage before skipping, or the version record could name bytes nobody has.
            if live and await self._storage.exists(key):
                return False
            await self._storage.put(key, data, media_type=media_type)
        except StorageError as exc:
            raise WorkspaceSaveUnavailable(f"could not store {key}") from exc
        return True

    async def _hold_current(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        thread_id: str,
        keys: Sequence[str],
    ) -> None:
        await release_artifacts(
            conn,
            workspace_id=workspace_id,
            reference_kind=SNAPSHOT_REFERENCE_KIND,
            reference_id=thread_id,
        )
        for key in dict.fromkeys(keys):
            await retain_artifact(
                conn,
                workspace_id=workspace_id,
                storage_key=key,
                reference_kind=SNAPSHOT_REFERENCE_KIND,
                reference_id=thread_id,
            )

    async def _read_verified(
        self, *, workspace_id: str, key: str, sha256: str, size: int | None
    ) -> bytes:
        async with self._conn_factory() as conn:
            record = await get_artifact(conn, key)
        if record is None or not _is_live(record) or record.workspace_id != workspace_id:
            raise SnapshotCorrupt(f"snapshot file {key} is not a live artifact of this workspace")
        try:
            data = await self._storage.get(key)
        except ArtifactNotFound as exc:
            raise SnapshotCorrupt(f"snapshot file {key} is missing from storage") from exc
        except StorageError as exc:
            raise WorkspaceRestoreUnavailable(f"could not read {key}") from exc
        if hashlib.sha256(data).hexdigest() != sha256 or (size is not None and len(data) != size):
            raise SnapshotCorrupt(f"snapshot file {key} does not match its hash")
        return data


def _is_live(record: ArtifactRecord | None) -> bool:
    """The row names bytes that may be read and held: not erased, purged or expired."""

    if record is None:
        return False
    return (
        record.erased_at is None
        and record.purged_at is None
        and not record.privacy_erased
        and (record.expires_at is None or record.expires_at > datetime.now(UTC))
    )
