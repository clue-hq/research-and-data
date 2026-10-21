"""F3 Phase 1, plan Task 3: the snapshot store over Postgres and the artifact store (spec WS-1–WS-3,
WS-8, WS-10; ruling AW-10).

Rows are committed (the store opens its own transactions, and the concurrency cases need two), so
every test uses its own workspace id and removes what it wrote."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from clue_agents.workspace_snapshot import (
    LeaseFence,
    SnapshotCorrupt,
    SnapshotEntry,
    SnapshotManifest,
    WorkspaceRestoreUnavailable,
    WorkspaceSaveUnavailable,
    tier_for,
)
from clue_api.agent_workspace_snapshots import (
    SNAPSHOT_REFERENCE_KIND,
    DbWorkspaceSnapshotStore,
)
from clue_db import db_lifespan, transaction
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_storage import FsStorage, StorageError
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

WHEN = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


def _entry(path: str, data: bytes) -> SnapshotEntry:
    return SnapshotEntry(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        media_type="text/plain",
        tier=tier_for(path),
        written_at=WHEN,
    )


class CountingStorage(FsStorage):
    """The filesystem backend, counting puts; ``fail_gets`` makes every read fail like an outage."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.puts = 0
        self.fail_gets = False
        self.fail_next_puts = 0

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.puts += 1
        if self.fail_next_puts:
            self.fail_next_puts -= 1
            raise StorageError("storage is unreachable")
        await super().put(key, data, media_type=media_type)

    async def get(self, key: str) -> bytes:
        if self.fail_gets:
            raise StorageError("storage is unreachable")
        return await super().get(key)


@asynccontextmanager
async def _workspace() -> AsyncIterator[str]:
    ws = f"ws-f3-{uuid.uuid4().hex[:10]}"
    try:
        yield ws
    finally:
        async with transaction() as conn:
            await conn.execute(
                text("DELETE FROM agent_workspace_snapshot WHERE workspace_id = :ws"), {"ws": ws}
            )
            await conn.execute(
                text("DELETE FROM artifact_reference WHERE workspace_id = :ws"), {"ws": ws}
            )
            await conn.execute(text("DELETE FROM artifact WHERE workspace_id = :ws"), {"ws": ws})


def _scenario(body: Callable[[str, CountingStorage], Awaitable[None]], tmp_path: Path) -> None:
    async def run() -> None:
        async with db_lifespan(), _workspace() as ws:
            await body(ws, CountingStorage(tmp_path / "store"))

    run_async(run())


async def _save(
    store: DbWorkspaceSnapshotStore,
    ws: str,
    files: dict[str, bytes],
    *,
    expected: int | None,
    fence: LeaseFence | None = None,
    thread: str = "thr-1",
):  # type: ignore[no-untyped-def]
    entries = [(_entry(path, data), data) for path, data in files.items()]
    await store.store_files(workspace_id=ws, files=entries)
    manifest = SnapshotManifest(entries=tuple(entry for entry, _ in entries))
    return await store.save(
        workspace_id=ws,
        project_id="prj-1",
        thread_id=thread,
        expected_version=expected,
        manifest=manifest,
        fence=fence,
    )


def test_first_save_creates_version_1_and_reads_back(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        status, pointer = await _save(store, ws, {"scratch/a.md": b"note"}, expected=None)
        assert status == "saved" and pointer is not None and pointer.version == 1
        current = await store.current(workspace_id=ws, thread_id="thr-1")
        assert current == pointer
        manifest = await store.read_manifest(workspace_id=ws, pointer=current)
        assert [entry.path for entry in manifest.entries] == ["scratch/a.md"]
        assert await store.read_file(workspace_id=ws, entry=manifest.entries[0]) == b"note"

    _scenario(body, tmp_path)


def test_second_save_with_expected_version_moves_to_2(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save(store, ws, {"scratch/a.md": b"1"}, expected=None)
        status, pointer = await _save(store, ws, {"scratch/a.md": b"2"}, expected=1)
        assert status == "saved" and pointer is not None and pointer.version == 2

    _scenario(body, tmp_path)


def test_stale_expected_version_is_refused(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save(store, ws, {"scratch/a.md": b"1"}, expected=None)
        await _save(store, ws, {"scratch/a.md": b"2"}, expected=1)
        status, pointer = await _save(store, ws, {"scratch/a.md": b"3"}, expected=1)
        assert (status, pointer) == ("stale", None)
        current = await store.current(workspace_id=ws, thread_id="thr-1")
        assert current is not None and current.version == 2

    _scenario(body, tmp_path)


def test_concurrent_first_saves_one_wins(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        results = await asyncio.gather(
            _save(store, ws, {"scratch/a.md": b"A"}, expected=None),
            _save(store, ws, {"scratch/a.md": b"B"}, expected=None),
        )
        assert sorted(status for status, _ in results) == ["saved", "stale"]

    _scenario(body, tmp_path)


def test_save_with_lost_lease_is_fenced(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        work_id = uuid.uuid4()
        try:
            async with transaction() as conn:
                first = await acquire_work_lease(
                    conn, work_id=WorkId(work_id), worker_id="worker-a", ttl=timedelta(seconds=0)
                )
            assert first is not None
            async with transaction() as conn:
                second = await acquire_work_lease(
                    conn, work_id=WorkId(work_id), worker_id="worker-b"
                )
            assert second is not None and second.generation == first.generation + 1
            stale_fence = LeaseFence(
                work_id=work_id, worker_id="worker-a", generation=int(first.generation)
            )
            status, _ = await _save(
                store, ws, {"scratch/a.md": b"z"}, expected=None, fence=stale_fence
            )
            assert status == "fenced"
            assert await store.current(workspace_id=ws, thread_id="thr-1") is None
            live_fence = LeaseFence(
                work_id=work_id, worker_id="worker-b", generation=int(second.generation)
            )
            status, _ = await _save(
                store, ws, {"scratch/a.md": b"z"}, expected=None, fence=live_fence
            )
            assert status == "saved"
        finally:
            async with transaction() as conn:
                await conn.execute(
                    text("DELETE FROM work_lease WHERE work_id = :w"), {"w": work_id}
                )

    _scenario(body, tmp_path)


def test_identical_bytes_are_uploaded_once(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        data = b"same bytes"
        first = await store.store_files(
            workspace_id=ws, files=[(_entry("scratch/a.md", data), data)]
        )
        before = storage.puts
        second = await store.store_files(
            workspace_id=ws, files=[(_entry("outputs/b.md", data), data)]
        )
        assert (first, second) == (1, 0)
        assert storage.puts == before

    _scenario(body, tmp_path)


def test_store_files_refuses_bytes_that_do_not_match_the_entry(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        with pytest.raises(SnapshotCorrupt):
            await store.store_files(
                workspace_id=ws, files=[(_entry("scratch/a.md", b"one"), b"two")]
            )

    _scenario(body, tmp_path)


def test_references_name_only_the_current_version(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save(store, ws, {"scratch/a.md": b"1", "scratch/b.md": b"b"}, expected=None)
        _, pointer = await _save(store, ws, {"scratch/a.md": b"2"}, expected=1)
        assert pointer is not None
        async with transaction() as conn:
            rows = await conn.execute(
                text(
                    "SELECT storage_key FROM artifact_reference WHERE workspace_id = :ws "
                    "AND reference_kind = :kind AND reference_id = 'thr-1'"
                ),
                {"ws": ws, "kind": SNAPSHOT_REFERENCE_KIND},
            )
            keys = {row[0] for row in rows}
        expected_keys = {pointer.manifest_key, f"{ws}/{hashlib.sha256(b'2').hexdigest()}"}
        assert keys == expected_keys

    _scenario(body, tmp_path)


def test_tampered_blob_raises_corrupt(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        _, pointer = await _save(store, ws, {"scratch/a.md": b"good"}, expected=None)
        assert pointer is not None
        manifest = await store.read_manifest(workspace_id=ws, pointer=pointer)
        entry = manifest.entries[0]
        await FsStorage.put(storage, f"{ws}/{entry.sha256}", b"evil", media_type="text/plain")
        with pytest.raises(SnapshotCorrupt):
            await store.read_file(workspace_id=ws, entry=entry)

    _scenario(body, tmp_path)


def test_storage_down_raises_restore_unavailable(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        _, pointer = await _save(store, ws, {"scratch/a.md": b"good"}, expected=None)
        assert pointer is not None
        storage.fail_gets = True
        with pytest.raises(WorkspaceRestoreUnavailable):
            await store.read_manifest(workspace_id=ws, pointer=pointer)

    _scenario(body, tmp_path)


def test_touch_moves_last_activity_only(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save(store, ws, {"scratch/a.md": b"1"}, expected=None)
        async with transaction() as conn:
            await conn.execute(
                text(
                    "UPDATE agent_workspace_snapshot "
                    "SET last_activity_at = now() - interval '1 day' "
                    "WHERE workspace_id = :ws"
                ),
                {"ws": ws},
            )
        await store.touch(workspace_id=ws, thread_id="thr-1")
        async with transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT version, last_activity_at > now() - interval '1 minute' "
                        "FROM agent_workspace_snapshot WHERE workspace_id = :ws"
                    ),
                    {"ws": ws},
                )
            ).one()
        assert tuple(row) == (1, True)

    _scenario(body, tmp_path)


def test_forget_deletes_the_record(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save(store, ws, {"scratch/a.md": b"1"}, expected=None)
        await store.forget(workspace_id=ws, thread_id="thr-1")
        assert await store.current(workspace_id=ws, thread_id="thr-1") is None

    _scenario(body, tmp_path)


def test_privacy_erase_forgets_the_version_record(tmp_path: Path) -> None:
    """WS-27 (Phase 1 part) through the factory: the record and this worker's folder both go, so
    a cached copy on any other worker can never match a record again."""

    from uuid import UUID

    from clue_agents.worker_area import ChatScope
    from clue_agents.workspace import AgentWorkspaceFactory
    from clue_agents.workspace_policy import PreparedWorkspaceRoot, WorkspaceRootPolicy
    from clue_agents.workspace_snapshotter import WorkspaceSnapshotter
    from clue_core import ExecutionId
    from tests.agents.workspace_helpers import RecordingArtifactSink, policy

    async def body(ws: str, storage: CountingStorage) -> None:
        for name in ("source", "home"):
            (tmp_path / name).mkdir(mode=0o700)
        prepared = WorkspaceRootPolicy(
            configured_root=tmp_path / "root",
            source_root=tmp_path / "source",
            home_root=tmp_path / "home",
        ).prepare()
        store = DbWorkspaceSnapshotStore(storage=storage)
        factory = AgentWorkspaceFactory(
            prepared_root=PreparedWorkspaceRoot(path=prepared.path),
            artifact_sink=RecordingArtifactSink(),
            snapshotter=WorkspaceSnapshotter(store=store, concurrency=4),
        )
        chat = ChatScope(workspace_id=ws, project_id="prj-1", thread_id="thr-1")
        try:
            lease = await factory.acquire_restored(
                workspace_id=ws,
                project_id="prj-1",
                thread_id="thr-1",
                execution_id=ExecutionId(UUID("00000000-0000-0000-0000-000000000901")),
                policy=policy(max_total_bytes=100_000, max_file_bytes=10_000, max_file_count=20),
            )
            lease.backend.write_text_sync("scratch/personal.md", "erase me")
            assert (await lease.save_snapshot()).status == "saved"
            await factory.release_saved(lease)
            assert await store.current(workspace_id=ws, thread_id="thr-1") is not None

            assert await factory.forget_chat(chat) is True
            assert await store.current(workspace_id=ws, thread_id="thr-1") is None
            assert not factory.chat_host_path(chat).exists()
            # Idempotent: a second erasure finds nothing and does not fail.
            assert await factory.forget_chat(chat) is False
        finally:
            factory.close()

    _scenario(body, tmp_path)


def test_a_retry_after_a_failed_upload_stores_the_bytes(tmp_path: Path) -> None:
    """Review C1: the artifact row is committed before the upload, so a failed upload leaves a
    live row naming bytes storage never got. The retry must upload them, not trust the row."""

    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        data = b"cycle ~42 days"
        entry = _entry("scratch/a.md", data)
        storage.fail_next_puts = 1
        with pytest.raises(WorkspaceSaveUnavailable):
            await store.store_files(workspace_id=ws, files=[(entry, data)])
        await store.store_files(workspace_id=ws, files=[(entry, data)])
        status, pointer = await store.save(
            workspace_id=ws,
            project_id="prj-1",
            thread_id="thr-1",
            expected_version=None,
            manifest=SnapshotManifest(entries=(entry,)),
            fence=None,
        )
        assert status == "saved" and pointer is not None
        assert await store.read_file(workspace_id=ws, entry=entry) == data

    _scenario(body, tmp_path)
