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
from clue_storage import (
    FsStorage,
    StorageError,
    agent_workspace_key,
    artifact_key,
    is_agent_workspace_key,
    record_artifact,
    retain_artifact,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

WHEN = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    """The filesystem backend, counting puts and recording deletes; ``fail_gets`` makes every read
    fail like an outage."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.puts = 0
        self.fail_gets = False
        self.fail_next_puts = 0
        self.deletes: list[str] = []

    async def delete(self, key: str) -> None:
        self.deletes.append(key)
        await super().delete(key)

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


async def _reference_keys(ws: str, thread: str = "thr-1") -> set[str]:
    async with transaction() as conn:
        rows = await conn.execute(
            text(
                "SELECT storage_key FROM artifact_reference WHERE workspace_id = :ws "
                "AND reference_kind = :kind AND reference_id = :id"
            ),
            {"ws": ws, "kind": SNAPSHOT_REFERENCE_KIND, "id": thread},
        )
    return {row[0] for row in rows}


async def _erasure(key: str) -> tuple[bool, bool]:
    """``(erased, purged)`` of the artifact row for ``key`` — it must exist."""

    async with transaction() as conn:
        row = (
            await conn.execute(
                text("SELECT erased_at, purged_at FROM artifact WHERE storage_key = :k"),
                {"k": key},
            )
        ).first()
    assert row is not None, f"no artifact row for {key}"
    return row[0] is not None, row[1] is not None


async def _record_legacy(ws: str, storage: CountingStorage, data: bytes, thread: str) -> str:
    """A Phase 1 hold: bytes recorded and held under the bare ``{ws}/{sha}`` key."""

    sha = hashlib.sha256(data).hexdigest()
    key = artifact_key(ws, sha)
    async with transaction() as conn:
        await record_artifact(
            conn,
            storage_key=key,
            workspace_id=ws,
            content_sha256=sha,
            media_type="text/plain",
            size_bytes=len(data),
        )
        await retain_artifact(
            conn,
            workspace_id=ws,
            storage_key=key,
            reference_kind=SNAPSHOT_REFERENCE_KIND,
            reference_id=thread,
        )
    await FsStorage.put(storage, key, data, media_type="text/plain")
    return key


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
        expected_keys = {pointer.manifest_key, agent_workspace_key(ws, _sha(b"2"))}
        assert keys == expected_keys

    _scenario(body, tmp_path)


def test_tampered_blob_raises_corrupt(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        _, pointer = await _save(store, ws, {"scratch/a.md": b"good"}, expected=None)
        assert pointer is not None
        manifest = await store.read_manifest(workspace_id=ws, pointer=pointer)
        entry = manifest.entries[0]
        await FsStorage.put(
            storage, agent_workspace_key(ws, entry.sha256), b"evil", media_type="text/plain"
        )
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


# --- F3 Phase 2 (WS-30, ruling AW-26): own storage area, erase what no snapshot holds ------------


def test_files_are_stored_under_the_agent_workspace_area(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        _, pointer = await _save(
            store, ws, {"scratch/a.md": b"1", "outputs/b.md": b"2"}, expected=None
        )
        assert pointer is not None
        keys = await _reference_keys(ws)
        assert len(keys) == 3
        assert all(is_agent_workspace_key(key) for key in keys)
        assert pointer.manifest_key in keys
        assert keys >= {agent_workspace_key(ws, _sha(b"1")), agent_workspace_key(ws, _sha(b"2"))}
        for key in keys:
            assert await storage.exists(key)

    _scenario(body, tmp_path)


def test_a_phase_1_file_is_read_from_the_old_key_and_restored_under_the_new_one(
    tmp_path: Path,
) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        data = b"written before Phase 2"
        entry = _entry("scratch/a.md", data)
        old_key = await _record_legacy(ws, storage, data, "thr-1")

        assert await store.read_file(workspace_id=ws, entry=entry) == data

        await _save(store, ws, {"scratch/a.md": data}, expected=None)
        new_key = agent_workspace_key(ws, entry.sha256)
        assert await storage.exists(new_key)
        assert new_key in await _reference_keys(ws)
        # The Phase 1 key is only released: its bytes may belong to an upload (AW-26).
        assert await _erasure(old_key) == (False, False)
        assert await storage.exists(old_key)
        assert await store.read_file(workspace_id=ws, entry=entry) == data

    _scenario(body, tmp_path)


def test_a_new_version_erases_the_files_only_the_old_version_used(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        _, first = await _save(
            store, ws, {"scratch/a.md": b"A", "scratch/b.md": b"B"}, expected=None
        )
        assert first is not None
        kept = agent_workspace_key(ws, _sha(b"A"))
        dropped = agent_workspace_key(ws, _sha(b"B"))

        _, second = await _save(store, ws, {"scratch/a.md": b"A"}, expected=1)
        assert second is not None

        assert await _erasure(dropped) == (True, True)
        assert not await storage.exists(dropped)
        assert await _erasure(first.manifest_key) == (True, True)
        assert not await storage.exists(first.manifest_key)
        assert await _erasure(kept) == (False, False)
        assert await storage.exists(kept)
        assert await _erasure(second.manifest_key) == (False, False)

    _scenario(body, tmp_path)


def test_a_file_two_chats_hold_survives_one_chat_dropping_it(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        shared = b"both chats wrote this"
        key = agent_workspace_key(ws, _sha(shared))
        await _save(store, ws, {"scratch/s.md": shared}, expected=None, thread="thr-x")
        await _save(store, ws, {"scratch/s.md": shared}, expected=None, thread="thr-y")

        await _save(store, ws, {"scratch/other.md": b"other"}, expected=1, thread="thr-x")

        assert key not in await _reference_keys(ws, "thr-x")
        assert key in await _reference_keys(ws, "thr-y")
        assert await _erasure(key) == (False, False)
        assert await storage.exists(key)

    _scenario(body, tmp_path)


def test_forget_erases_every_file_no_other_chat_holds(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        mine, shared = b"only this chat", b"both chats wrote this"
        mine_key = agent_workspace_key(ws, _sha(mine))
        shared_key = agent_workspace_key(ws, _sha(shared))
        _, pointer = await _save(
            store,
            ws,
            {"scratch/m.md": mine, "scratch/s.md": shared},
            expected=None,
            thread="thr-x",
        )
        assert pointer is not None
        await _save(store, ws, {"scratch/s.md": shared}, expected=None, thread="thr-y")

        await store.forget(workspace_id=ws, thread_id="thr-x")

        assert await _reference_keys(ws, "thr-x") == set()
        assert await _erasure(mine_key) == (True, True)
        assert not await storage.exists(mine_key)
        assert await _erasure(pointer.manifest_key) == (True, True)
        assert await _erasure(shared_key) == (False, False)
        assert await storage.exists(shared_key)

    _scenario(body, tmp_path)


def test_a_chats_save_does_no_fleet_wide_work_on_other_owners_rows(tmp_path: Path) -> None:
    """Review I7: the purge a save runs is about this chat's keys and nothing else.

    ``purge_erased_artifacts`` opens with an unfiltered ``UPDATE artifact ... WHERE expires_at <=
    now()``, which the keyless fleet sweep wants and a per-key caller does not. Before Phase 2
    the function ran from the sweep and the DSAR paths; now a save calls it on almost every
    content-changing turn, so that statement had moved onto the turn's critical path — a
    sequential scan of ``artifact``, and the tombstoning of rows belonging to research quality
    artifacts and ARV2 media (both set ``expires_at``) inside somebody's chat.
    """

    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save(store, ws, {"scratch/a.md": b"first"}, expected=None)
        # Another owner's artifact, past its own expiry and not yet swept.
        someone_else = await _record_legacy(ws, storage, b"a media transcript", "other-owner")
        async with transaction() as conn:
            await conn.execute(
                text(
                    "UPDATE artifact SET expires_at = now() - interval '1 second' "
                    "WHERE storage_key = :k"
                ),
                {"k": someone_else},
            )

        # An ordinary turn: new content, so the previous manifest key is released and purged.
        status, _ = await _save(store, ws, {"scratch/a.md": b"second"}, expected=1)
        assert status == "saved"

        async with transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT privacy_erased, erasure_reason, erased_at, purged_at "
                        "FROM artifact WHERE storage_key = :k"
                    ),
                    {"k": someone_else},
                )
            ).first()
        assert row == (False, None, None, None)
        assert await storage.exists(someone_else)

    _scenario(body, tmp_path)


def test_erasure_never_touches_a_key_of_another_shape(tmp_path: Path) -> None:
    """AW-26: a released key outside the agent-workspace area is some other owner's bytes — an
    upload or a Gallery artifact — and neither a new version nor a forget may erase it."""

    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        data = b"an upload's bytes"
        legacy = await _record_legacy(ws, storage, data, "thr-1")

        await _save(store, ws, {"scratch/a.md": b"new"}, expected=None)
        assert legacy not in await _reference_keys(ws)
        assert await _erasure(legacy) == (False, False)
        assert await storage.exists(legacy)

        async with transaction() as conn:
            await retain_artifact(
                conn,
                workspace_id=ws,
                storage_key=legacy,
                reference_kind=SNAPSHOT_REFERENCE_KIND,
                reference_id="thr-1",
            )
        await store.forget(workspace_id=ws, thread_id="thr-1")
        assert await _erasure(legacy) == (False, False)
        assert await storage.exists(legacy)
        assert legacy not in storage.deletes

    _scenario(body, tmp_path)
