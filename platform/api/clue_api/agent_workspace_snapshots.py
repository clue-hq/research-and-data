"""The snapshot store: a chat's agent-folder snapshots in Postgres and the artifact store.

F3 Phase 1 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md,
WS-1–WS-3, WS-8, WS-10; rulings AW-1, AW-10, AW-13). Every file of a snapshot is stored once under
its content address in the chat's workspace; one file list names them; one row in
``agent_workspace_snapshot`` names the current file list. A save moves that row with a
compare-and-set on the version the turn restored, in the same transaction as the fleet-lease check,
so a worker that lost the chat's lease, or a turn that raced another, never overwrites a newer
version. Files are always stored before the row moves, so a row never names missing bytes.

The snapshot's files are held through ``artifact_reference`` rows of kind
:data:`SNAPSHOT_REFERENCE_KIND`, which always name exactly the current version.

F3 Phase 2 (WS-30, ruling AW-26) gives those files their own storage area — ``agent_workspace_key``
writes ``{workspace}/agent-workspace/{sha}`` — and makes a save or a forget erase the keys it
released that no other snapshot still holds. The area is what makes that safe: a released key of
any other shape is some other owner's bytes (an upload, a Gallery artifact, an evidence snapshot)
that merely deduped onto the same content address, so erasure is guarded by
:func:`~clue_storage.is_agent_workspace_key` and never touches one. Phase 1 bytes still live under
the bare ``{workspace}/{sha}`` key, so a read falls back to it and a re-save simply re-stores the
bytes in the new area and releases the old key without erasing it.
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
    agent_workspace_key,
    artifact_key,
    erase_if_unreferenced,
    get_artifact,
    is_agent_workspace_key,
    purge_erased_artifacts,
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
#: The same advance for a save that is **not** the chat being used — today only the expiry job's
#: (``activity=False``). It leaves ``last_activity_at`` exactly as it found it, which is the only
#: way to leave it: a save that stamps ``now()`` and a bookkeeping statement that puts the old
#: value back cannot tell a concurrent ``touch()`` — a turn that finished having changed no files,
#: and the only activity signal a research run or a delegation has — from its own stamp, and would
#: revert it (review I3).
_ADVANCE_QUIET = text(
    "UPDATE agent_workspace_snapshot SET version = version + 1, manifest_artifact_key = :key, "
    "manifest_sha256 = :sha, updated_at = now() "
    "WHERE workspace_id = :ws AND thread_id = :thread AND version = :expected RETURNING version"
)
_TOUCH = text(
    "UPDATE agent_workspace_snapshot SET last_activity_at = now() "
    "WHERE workspace_id = :ws AND thread_id = :thread"
)
_FORGET = text(
    "DELETE FROM agent_workspace_snapshot WHERE workspace_id = :ws AND thread_id = :thread"
)
_HELD = text(
    "SELECT storage_key FROM artifact_reference WHERE workspace_id = :ws "
    "AND reference_kind = :kind AND reference_id = :thread"
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
            keys=(pointer.manifest_key,),
            sha256=pointer.manifest_sha256,
            size=None,
        )
        return decode_manifest(data)

    async def read_file(self, *, workspace_id: str, entry: SnapshotEntry) -> bytes:
        return await self._read_verified(
            workspace_id=workspace_id,
            keys=(
                agent_workspace_key(workspace_id, entry.sha256),
                artifact_key(workspace_id, entry.sha256),
            ),
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
        activity: bool = True,
    ) -> tuple[SaveStatus, SnapshotPointer | None]:
        body = encode_manifest(manifest)
        manifest_sha = hashlib.sha256(body).hexdigest()
        manifest_key = agent_workspace_key(workspace_id, manifest_sha)
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
            if expected_version is None:
                statement = _INSERT_FIRST
            else:
                statement = _ADVANCE if activity else _ADVANCE_QUIET
            row = (await conn.execute(statement, params)).first()
            if row is None:
                return "stale", None
            # ``live()``, never ``entries``: an expired entry's bytes are already gone, and holding
            # its key would keep that key out of ``before - after`` forever — the retention job
            # would mark files expired and free nothing (WS-26).
            keys = dict.fromkeys(
                (
                    manifest_key,
                    *(agent_workspace_key(workspace_id, e.sha256) for e in manifest.live()),
                )
            )
            before = await self._held_keys(conn, workspace_id=workspace_id, thread_id=thread_id)
            await self._hold_current(
                conn, workspace_id=workspace_id, thread_id=thread_id, keys=tuple(keys)
            )
            marked = await self._erase_released(conn, before=before, after=set(keys))
        await self._purge(marked)
        return "saved", SnapshotPointer(
            version=int(row[0]), manifest_sha256=manifest_sha, manifest_key=manifest_key
        )

    async def touch(self, *, workspace_id: str, thread_id: str) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(_TOUCH, {"ws": workspace_id, "thread": thread_id})

    async def forget(self, *, workspace_id: str, thread_id: str) -> None:
        """Delete the chat's version record and its holds, and erase the files of its own area
        that no other snapshot still holds (WS-31)."""

        async with self._conn_factory() as conn:
            await conn.execute(_FORGET, {"ws": workspace_id, "thread": thread_id})
            before = await self._held_keys(conn, workspace_id=workspace_id, thread_id=thread_id)
            await release_artifacts(
                conn,
                workspace_id=workspace_id,
                reference_kind=SNAPSHOT_REFERENCE_KIND,
                reference_id=thread_id,
            )
            marked = await self._erase_released(conn, before=before, after=set())
        await self._purge(marked)

    # --- internals ------------------------------------------------------------------------------

    async def _store_one(
        self, *, workspace_id: str, sha256: str, media_type: str, data: bytes
    ) -> bool:
        key = agent_workspace_key(workspace_id, sha256)
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

    async def _held_keys(
        self, conn: AsyncConnection, *, workspace_id: str, thread_id: str
    ) -> set[str]:
        """The storage keys this chat's snapshot holds right now."""

        rows = await conn.execute(
            _HELD, {"ws": workspace_id, "kind": SNAPSHOT_REFERENCE_KIND, "thread": thread_id}
        )
        return {str(row[0]) for row in rows}

    async def _erase_released(
        self, conn: AsyncConnection, *, before: set[str], after: set[str]
    ) -> tuple[str, ...]:
        """Phase 1 of erasure for every key this chat has let go of: stamp ``erased_at`` on the
        ones nothing else holds, and return them for the post-commit purge.

        Only keys in the chat's own storage area are candidates (ruling AW-26). A released key of
        another shape is a Phase 1 snapshot's, and those bytes may equally be an upload's or a
        Gallery artifact's — releasing the hold is the whole of what this chat may do to them.
        """

        marked: list[str] = []
        for key in sorted(before - after):
            if not is_agent_workspace_key(key):
                continue
            if await erase_if_unreferenced(conn, key):
                marked.append(key)
        return tuple(marked)

    async def _purge(self, keys: tuple[str, ...]) -> None:
        """Phase 2 of erasure: delete the blobs, in a fresh transaction after the one that
        stamped ``erased_at`` committed (``clue_storage.artifacts`` module docstring — storage is
        never mutated inside the transaction whose rollback would have to undo it).

        ``sweep_expired=False``: this runs on nearly every content-changing turn, and the pass's
        opening table-wide expiry tombstone is the fleet sweep's work, not a chat's (review I7).
        Those rows are the orphan sweep's to converge on, as they were before Phase 2.
        """

        if not keys:
            return
        async with self._conn_factory() as conn:
            await purge_erased_artifacts(conn, self._storage, keys=keys, sweep_expired=False)

    async def _read_verified(
        self, *, workspace_id: str, keys: Sequence[str], sha256: str, size: int | None
    ) -> bytes:
        """Read the first of ``keys`` whose artifact row is live, and verify what comes back.

        A file is tried in its own area first and under its Phase 1 key second, so a chat whose
        snapshot predates the area still restores. A key whose row is live but whose bytes are
        missing or wrong is :class:`SnapshotCorrupt`, never a reason to try the next candidate —
        a live row is the claim that these are the bytes.
        """

        async with self._conn_factory() as conn:
            for candidate in keys:
                record = await get_artifact(conn, candidate)
                if record is not None and _is_live(record) and record.workspace_id == workspace_id:
                    key = candidate
                    break
            else:
                raise SnapshotCorrupt(
                    f"snapshot file {keys[0]} is not a live artifact of this workspace"
                )
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
