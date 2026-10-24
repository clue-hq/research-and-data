"""F3 Phase 1, plan Task 8: restore and save a chat's agent folders (spec WS-6–WS-11, WS-18, WS-22;
AW-13, AW-14, AW-18). Phase 2, Task 3 adds expired entries and save-time receipts (AW-2, AW-22,
AW-24)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from clue_agents.ports import ReceiptSource, WorkspaceSnapshotStore
from clue_agents.worker_area import ChatScope
from clue_agents.workspace import AgentWorkspaceFactory, AgentWorkspaceLease
from clue_agents.workspace_policy import PreparedWorkspaceRoot, WorkspaceRootPolicy
from clue_agents.workspace_snapshot import (
    UNKNOWN_RECEIPT,
    LeaseFence,
    Receipt,
    SaveStatus,
    SnapshotCorrupt,
    SnapshotEntry,
    SnapshotManifest,
    SnapshotPointer,
    WorkspaceRestoreUnavailable,
    WorkspaceSaveUnavailable,
    encode_manifest,
)
from clue_agents.workspace_snapshotter import WorkspaceSnapshotter
from clue_core import ExecutionId
from tests.agents.workspace_helpers import RecordingArtifactSink, policy

WS, PROJECT, THREAD = "ws-1", "project-1", "thread-1"
EXECUTIONS = [ExecutionId(UUID(f"00000000-0000-0000-0000-0000000008{n:02d}")) for n in range(10)]


@dataclass
class FakeStore(WorkspaceSnapshotStore):
    """An in-memory snapshot store with the real store's compare-and-set rules."""

    blobs: dict[str, bytes] = field(default_factory=dict)
    pointer: SnapshotPointer | None = None
    reads: int = 0
    uploads: int = 0
    touches: int = 0
    fail_reads_after: int | None = None
    fail_uploads: int = 0
    fenced: bool = False

    async def current(self, *, workspace_id: str, thread_id: str) -> SnapshotPointer | None:
        return self.pointer

    async def read_manifest(
        self, *, workspace_id: str, pointer: SnapshotPointer
    ) -> SnapshotManifest:
        from clue_agents.workspace_snapshot import decode_manifest

        return decode_manifest(self._read(pointer.manifest_sha256))

    async def read_file(self, *, workspace_id: str, entry: SnapshotEntry) -> bytes:
        data = self._read(entry.sha256)
        if hashlib.sha256(data).hexdigest() != entry.sha256:
            raise SnapshotCorrupt("hash mismatch")
        return data

    def _read(self, sha: str) -> bytes:
        self.reads += 1
        if self.fail_reads_after is not None and self.reads > self.fail_reads_after:
            raise WorkspaceRestoreUnavailable("storage down")
        return self.blobs[sha]

    async def store_files(
        self, *, workspace_id: str, files: Sequence[tuple[SnapshotEntry, bytes]]
    ) -> int:
        if self.fail_uploads:
            self.fail_uploads -= 1
            raise WorkspaceSaveUnavailable("storage down")
        count = 0
        for entry, data in files:
            if entry.sha256 not in self.blobs:
                self.blobs[entry.sha256] = data
                count += 1
        self.uploads += count
        return count

    async def save(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        expected_version: int | None,
        manifest: SnapshotManifest,
        fence: LeaseFence | None,
        # Only the expiry job passes False, and it drives the real store; this fake has no
        # activity stamp to leave alone.
        activity: bool = True,
    ) -> tuple[SaveStatus, SnapshotPointer | None]:
        if self.fenced:
            return "fenced", None
        current = None if self.pointer is None else self.pointer.version
        if current != expected_version:
            return "stale", None
        body = encode_manifest(manifest)
        sha = hashlib.sha256(body).hexdigest()
        self.blobs[sha] = body
        self.pointer = SnapshotPointer(
            version=(current or 0) + 1, manifest_sha256=sha, manifest_key=f"{workspace_id}/{sha}"
        )
        return "saved", self.pointer

    async def touch(self, *, workspace_id: str, thread_id: str) -> None:
        self.touches += 1

    async def forget(self, *, workspace_id: str, thread_id: str) -> None:
        self.pointer = None


@dataclass
class Machine:
    """One worker: its own root, its own factory, sharing the store with other machines."""

    root: Path
    factory: AgentWorkspaceFactory
    turns: int = 0

    def chat_dir(self) -> Path:
        return self.root / "chats" / WS / PROJECT / THREAD

    def agent(self) -> Path:
        return self.chat_dir() / "agent"


@dataclass
class FakeReceipts(ReceiptSource):
    """A receipt source that answers for every path and remembers what it was asked."""

    asked: list[str] = field(default_factory=list)

    async def receipt_for(self, *, workspace_id: str, thread_id: str, path: str) -> Receipt:
        self.asked.append(path)
        return Receipt(
            source="run_crm_action",
            operation_id="op-1",
            produced_at=datetime(2026, 10, 22, 11, tzinfo=UTC),
            details={"tool": "hubspot", "records": 120},
            read_again=f"run_crm_action(...) wrote {path}",
        )


def _expire(store: FakeStore, *paths: str) -> SnapshotManifest:
    """Publish a new version with ``paths`` expired and their bytes gone, as Task 5's job will."""

    assert store.pointer is not None
    manifest = asyncio.run(store.read_manifest(workspace_id=WS, pointer=store.pointer))
    expired_at = datetime(2026, 10, 22, 12, tzinfo=UTC)
    receipt = Receipt(
        source="run_crm_action",
        operation_id="op-9",
        produced_at=datetime(2026, 10, 20, tzinfo=UTC),
        details={},
        read_again="run_crm_action(action='deals.list')",
    )
    entries = []
    for item in manifest.entries:
        if item.path in paths:
            store.blobs.pop(item.sha256, None)  # the expiry deleted the bytes
            entries.append(replace(item, expired_at=expired_at, receipt=receipt))
        else:
            entries.append(item)
    updated = SnapshotManifest(entries=tuple(entries))
    body = encode_manifest(updated)
    sha = hashlib.sha256(body).hexdigest()
    store.blobs[sha] = body
    store.pointer = SnapshotPointer(
        version=store.pointer.version + 1, manifest_sha256=sha, manifest_key=f"{WS}/{sha}"
    )
    return updated


def _current(store: FakeStore) -> dict[str, SnapshotEntry]:
    assert store.pointer is not None
    return asyncio.run(store.read_manifest(workspace_id=WS, pointer=store.pointer)).by_path()


def _machine(
    tmp_path: Path,
    name: str,
    store: FakeStore,
    legacy: Path | None = None,
    receipts: ReceiptSource | None = None,
) -> Machine:
    base = tmp_path / name
    base.mkdir()
    (base / "source").mkdir(mode=0o700)
    (base / "home").mkdir(mode=0o700)
    prepared = WorkspaceRootPolicy(
        configured_root=base / "root", source_root=base / "source", home_root=base / "home"
    ).prepare()
    factory = AgentWorkspaceFactory(
        prepared_root=PreparedWorkspaceRoot(path=prepared.path),
        artifact_sink=RecordingArtifactSink(),
        snapshotter=WorkspaceSnapshotter(
            store=store,
            concurrency=4,
            legacy_root=legacy,
            retry_delays=(0, 0, 0),
            receipts=receipts,
        ),
    )
    return Machine(root=prepared.path, factory=factory)


def _open(machine: Machine) -> AgentWorkspaceLease:
    machine.turns += 1
    return asyncio.run(
        machine.factory.acquire_restored(
            workspace_id=WS,
            project_id=PROJECT,
            thread_id=THREAD,
            execution_id=EXECUTIONS[machine.turns],
            policy=policy(max_total_bytes=1_000_000, max_file_bytes=500_000, max_file_count=100),
        )
    )


def _write(lease: AgentWorkspaceLease, path: str, data: bytes) -> None:
    """Write a file straight into the agent folder, as a sandbox run would."""

    host = lease.factory.thread_host_path(WS, PROJECT, THREAD) / path
    host.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    host.write_bytes(data)
    host.chmod(0o600)


def _turn(machine: Machine, files: dict[str, bytes], *, delete: Sequence[str] = ()) -> str:
    lease = _open(machine)
    try:
        for path, data in files.items():
            _write(lease, path, data)
        for path in delete:
            (machine.agent() / path).unlink()
        return asyncio.run(lease.save_snapshot()).status
    finally:
        asyncio.run(machine.factory.release_saved(lease))


def _note(machine: Machine) -> dict[str, object] | None:
    path = machine.chat_dir() / "snapshot-note.json"
    return json.loads(path.read_text()) if path.exists() else None


def test_new_chat_starts_empty_and_first_save_is_version_1(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    lease = _open(machine)
    try:
        assert list((machine.agent() / "scratch").iterdir()) == []
        _write(lease, "scratch/notes.md", b"note")
        report = asyncio.run(lease.save_snapshot())
        assert (report.status, report.version, report.uploaded) == ("saved", 1, 1)
    finally:
        asyncio.run(machine.factory.release_saved(lease))
    assert _note(machine)["version"] == 1  # type: ignore[index]


def test_warm_restore_downloads_nothing(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/notes.md": b"note", "outputs/t.csv": b"a,b"})
    store.reads = 0
    lease = _open(machine)
    try:
        assert lease.restore_report is not None and lease.restore_report.warm is True
        assert store.reads == 0
    finally:
        asyncio.run(machine.factory.release_saved(lease))


def test_another_machine_restores_exactly_the_saved_files(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    files = {
        "scratch/notes.md": b"note",
        "outputs/t.csv": b"a,b",
        "reads/op-1.json": b"{}",
        "work/deals_clean.csv": b"x",
    }
    _turn(a, files)
    lease = _open(b)
    try:
        for path, data in files.items():
            assert (b.agent() / path).read_bytes() == data
        assert lease.restore_report is not None and lease.restore_report.downloaded == 4
    finally:
        asyncio.run(b.factory.release_saved(lease))


def test_stale_copy_downloads_only_changed_files(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"scratch/1.md": b"1", "scratch/2.md": b"2", "scratch/3.md": b"3"})
    _turn(b, {"scratch/2.md": b"two"})
    lease = _open(a)
    try:
        assert lease.restore_report is not None and lease.restore_report.downloaded == 1
        assert (a.agent() / "scratch/2.md").read_bytes() == b"two"
    finally:
        asyncio.run(a.factory.release_saved(lease))


def test_restore_deletes_files_not_in_the_manifest(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"scratch/keep.md": b"k", "scratch/gone.md": b"g"})
    _turn(b, {}, delete=["scratch/gone.md"])
    lease = _open(a)
    try:
        assert not (a.agent() / "scratch/gone.md").exists()
        assert (a.agent() / "scratch/keep.md").read_bytes() == b"k"
        assert lease.restore_report is not None and lease.restore_report.deleted == 1
    finally:
        asyncio.run(a.factory.release_saved(lease))


def test_restore_refuses_escaping_path(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    evil = (
        b'{"entries":[{"media_type":"text/plain","path":"scratch/../../../evil","sha256":"'
        + hashlib.sha256(b"x").hexdigest().encode()
        + b'","size":1,"tier":"work_product","written_at":"2026-10-22T09:30:00+00:00"}],'
        b'"schema_version":1}'
    )
    sha = hashlib.sha256(evil).hexdigest()
    store.blobs[sha] = evil
    store.blobs[hashlib.sha256(b"x").hexdigest()] = b"x"
    store.pointer = SnapshotPointer(version=1, manifest_sha256=sha, manifest_key=f"{WS}/{sha}")
    with pytest.raises(SnapshotCorrupt):
        _open(machine)
    assert not (tmp_path / "a" / "evil").exists()
    assert _note(machine) is None


def test_round_trip_keeps_empty_and_binary_files(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"outputs/empty.txt": b"", "outputs/book.xlsx": b"PK\x03\x04\x00\xff"})
    lease = _open(b)
    try:
        assert (b.agent() / "outputs/empty.txt").read_bytes() == b""
        assert (b.agent() / "outputs/book.xlsx").read_bytes() == b"PK\x03\x04\x00\xff"
    finally:
        asyncio.run(b.factory.release_saved(lease))


def test_failed_restore_leaves_no_note_and_releases_the_lease(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"scratch/1.md": b"1", "scratch/2.md": b"2"})
    store.reads, store.fail_reads_after = 0, 2  # the file list and one file, then storage fails
    with pytest.raises(WorkspaceRestoreUnavailable):
        _open(b)
    assert _note(b) is None
    store.fail_reads_after = None
    lease = _open(b)  # the thread was released, so the next turn can open it and restore
    try:
        assert (b.agent() / "scratch/2.md").read_bytes() == b"2"
    finally:
        asyncio.run(b.factory.release_saved(lease))


def test_restore_never_touches_recipe_folders_or_libraries(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"scratch/n.md": b"n"})
    lease = _open(b)
    asyncio.run(b.factory.release_saved(lease))
    (b.agent() / "inputs" / "kept.txt").write_text("recipe")
    (b.agent() / "inputs" / "kept.txt").chmod(0o600)
    _turn(a, {"scratch/n.md": b"n2"})
    lease = _open(b)
    try:
        assert (b.agent() / "inputs" / "kept.txt").read_text() == "recipe"
    finally:
        asyncio.run(b.factory.release_saved(lease))


def test_unchanged_save_only_touches(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/n.md": b"n"})
    assert _turn(machine, {}) == "unchanged"
    assert store.pointer is not None and store.pointer.version == 1
    assert store.touches == 1


def test_stale_save_removes_note(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/n.md": b"n"})
    lease = _open(machine)
    try:
        _write(lease, "scratch/n.md", b"zombie")
        store.pointer = SnapshotPointer(
            version=9, manifest_sha256=store.pointer.manifest_sha256, manifest_key="k"
        )  # type: ignore[union-attr]
        assert asyncio.run(lease.save_snapshot()).status == "stale"
        assert _note(machine) is None
    finally:
        asyncio.run(machine.factory.release_saved(lease))


def test_fenced_save_removes_note(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/n.md": b"n"})
    store.fenced = True
    assert _turn(machine, {"scratch/n.md": b"late"}) == "fenced"
    assert _note(machine) is None


def test_save_storage_down_marks_unsaved_and_raises(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/n.md": b"n"})
    store.fail_uploads = 4  # the first attempt and all three retries (AW-18)
    lease = _open(machine)
    try:
        _write(lease, "scratch/n.md", b"changed")
        with pytest.raises(WorkspaceSaveUnavailable):
            asyncio.run(lease.save_snapshot())
        note = _note(machine)
        assert note is not None and note["unsaved"] is True and note["version"] == 1
    finally:
        machine.factory.release(lease)


def test_unsaved_copy_is_kept_and_saved_next_turn(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/n.md": b"n"})
    store.fail_uploads = 4  # the first attempt and all three retries (AW-18)
    lease = _open(machine)
    _write(lease, "scratch/n.md", b"changed")
    with pytest.raises(WorkspaceSaveUnavailable):
        asyncio.run(lease.save_snapshot())
    machine.factory.release(lease)
    store.reads = 0
    lease = _open(machine)
    try:
        assert lease.restore_report is not None and lease.restore_report.warm is True
        assert (machine.agent() / "scratch/n.md").read_bytes() == b"changed"
        assert asyncio.run(lease.save_snapshot()).status == "saved"
        assert store.pointer is not None and store.pointer.version == 2
    finally:
        asyncio.run(machine.factory.release_saved(lease))


def test_retries_ride_out_a_short_outage(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    store.fail_uploads = 2
    assert _turn(machine, {"scratch/n.md": b"n"}) == "saved"


def test_legacy_folder_is_imported_then_removed_after_save(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    old = legacy / WS / "projects" / PROJECT / "threads" / THREAD
    (old / "scratch").mkdir(parents=True)
    (old / "scratch" / "old-notes.md").write_bytes(b"from before F3")
    (old / "outputs").mkdir()
    (old / "outputs" / "t.csv").write_bytes(b"1,2")
    store = FakeStore()
    machine = _machine(tmp_path, "a", store, legacy=legacy)
    lease = _open(machine)
    try:
        assert lease.restore_report is not None and lease.restore_report.imported_legacy is True
        assert (machine.agent() / "scratch/old-notes.md").read_bytes() == b"from before F3"
        assert asyncio.run(lease.save_snapshot()).status == "saved"
    finally:
        asyncio.run(machine.factory.release_saved(lease))
    assert not old.exists()


def test_written_at_carries_forward_for_unchanged_files(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/a.md": b"a"})
    first = asyncio.run(store.read_manifest(workspace_id=WS, pointer=store.pointer)).by_path()  # type: ignore[arg-type]
    _turn(machine, {"scratch/b.md": b"b"})
    second = asyncio.run(store.read_manifest(workspace_id=WS, pointer=store.pointer)).by_path()  # type: ignore[arg-type]
    assert second["scratch/a.md"].written_at == first["scratch/a.md"].written_at
    assert second["scratch/b.md"].written_at >= first["scratch/a.md"].written_at


def test_an_erased_chat_never_reuses_its_cached_copy(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"scratch/personal.md": b"erase me"})
    store.pointer = None  # the version record was deleted by a privacy erasure
    lease = _open(machine)
    try:
        assert not (machine.agent() / "scratch/personal.md").exists()
    finally:
        asyncio.run(machine.factory.release_saved(lease))


def test_without_a_snapshotter_nothing_changes(tmp_path: Path) -> None:
    from tests.agents.workspace_helpers import make_factory

    _root, factory, _sink = make_factory(tmp_path)
    lease = asyncio.run(
        factory.acquire_restored(
            workspace_id=WS,
            project_id=PROJECT,
            thread_id=THREAD,
            execution_id=EXECUTIONS[0],
            policy=policy(),
        )
    )
    try:
        assert lease.restore_report is None
        assert asyncio.run(lease.save_snapshot()).status == "unchanged"
    finally:
        asyncio.run(factory.release_saved(lease))
        factory.close()


def test_the_fence_reaches_the_store(tmp_path: Path) -> None:
    seen: list[LeaseFence | None] = []

    class Recording(FakeStore):
        async def save(self, **kwargs):  # type: ignore[no-untyped-def,override]
            seen.append(kwargs["fence"])
            return await super().save(**kwargs)

    store = Recording()
    machine = _machine(tmp_path, "a", store)
    fence = LeaseFence(work_id=UUID(int=7), worker_id="w-1", generation=3)
    lease = asyncio.run(
        machine.factory.acquire_restored(
            workspace_id=WS,
            project_id=PROJECT,
            thread_id=THREAD,
            execution_id=EXECUTIONS[1],
            policy=policy(),
            fence=fence,
        )
    )
    try:
        _write(lease, "scratch/n.md", b"n")
        asyncio.run(lease.save_snapshot())
        assert seen == [fence]
    finally:
        asyncio.run(machine.factory.release_saved(lease))


def test_release_saved_saves_unsaved_writes_best_effort(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    lease = _open(machine)
    _write(lease, "scratch/n.md", b"n")
    asyncio.run(machine.factory.release_saved(lease))
    assert store.pointer is not None and store.pointer.version == 1
    store.fail_uploads = 5
    lease = _open(machine)
    _write(lease, "scratch/n.md", b"m")
    asyncio.run(machine.factory.release_saved(lease))  # never raises
    assert store.pointer.version == 1


def test_restore_never_downloads_an_expired_entry_and_removes_its_local_file(
    tmp_path: Path,
) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"reads/r.json": b"{}"})
    asyncio.run(b.factory.release_saved(_open(b)))  # b's copy now holds reads/r.json
    _turn(a, {"reads/r.json": b"{}", "scratch/a.md": b"a"})
    _expire(store, "reads/r.json")
    lease = _open(b)
    try:
        assert not (b.agent() / "reads/r.json").exists()
        assert (b.agent() / "scratch/a.md").read_bytes() == b"a"
        assert lease.restore_report is not None and lease.restore_report.downloaded == 1
        base = lease.snapshot_base
        assert base is not None and base.manifest is not None
        gone = base.manifest.by_path()["reads/r.json"]
        assert gone.expired_at is not None and gone.receipt is not None
    finally:
        asyncio.run(b.factory.release_saved(lease))


def test_save_carries_expired_entries_forward_and_revives_a_rewritten_path(
    tmp_path: Path,
) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"reads/r.json": b"{}", "scratch/keep.md": b"k"})
    first = _current(store)["reads/r.json"]
    _expire(store, "reads/r.json")

    assert _turn(machine, {"scratch/other.md": b"o"}) == "saved"
    carried = _current(store)["reads/r.json"]
    assert carried.expired_at is not None and carried.receipt is not None
    assert carried.written_at == first.written_at

    before_save = datetime.now(UTC)
    assert first.written_at < before_save
    assert _turn(machine, {"reads/r.json": b"{}"}) == "saved"  # the same bytes, written again
    revived = _current(store)["reads/r.json"]
    assert revived.expired_at is None
    assert revived.written_at >= before_save
    assert store.blobs[revived.sha256] == b"{}"  # the bytes the expiry deleted were put back


def test_save_attaches_a_receipt_to_each_new_raw_input(tmp_path: Path) -> None:
    store, receipts = FakeStore(), FakeReceipts()
    machine = _machine(tmp_path, "a", store, receipts=receipts)
    _turn(
        machine,
        {"reads/op-1.json": b"{}", "scratch/a.md": b"a", "outputs/t.csv": b"a,b"},
    )
    saved = _current(store)
    assert saved["reads/op-1.json"].receipt == asyncio.run(
        receipts.receipt_for(workspace_id=WS, thread_id=THREAD, path="reads/op-1.json")
    )
    assert saved["scratch/a.md"].receipt is not None  # a working file expires too (AW-22)
    assert saved["outputs/t.csv"].receipt is None  # work products never expire (AW-2)
    assert sorted(set(receipts.asked)) == ["reads/op-1.json", "scratch/a.md"]

    _turn(machine, {"scratch/b.md": b"b"})  # an unchanged entry keeps the receipt it had
    assert _current(store)["reads/op-1.json"].receipt == saved["reads/op-1.json"].receipt


def test_without_a_receipt_source_a_new_file_still_gets_one(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"reads/op-1.json": b"{}", "outputs/t.csv": b"a,b"})
    saved = _current(store)
    assert saved["reads/op-1.json"].receipt == UNKNOWN_RECEIPT
    assert saved["outputs/t.csv"].receipt is None


def test_a_save_rebases_over_an_expiry_only_move(tmp_path: Path) -> None:
    """The expiry job moved the version mid-turn; the turn's own files must not be lost (AW-24)."""

    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"reads/r.json": b"{}", "scratch/a.md": b"a"})
    lease = _open(machine)
    try:
        _expire(store, "reads/r.json")  # the job publishes version 2 under the running turn
        _write(lease, "scratch/b.md", b"b")
        report = asyncio.run(lease.save_snapshot())
        assert (report.status, report.version) == ("saved", 3)
    finally:
        asyncio.run(machine.factory.release_saved(lease))
    saved = _current(store)
    assert sorted(saved) == ["reads/r.json", "scratch/a.md", "scratch/b.md"]
    assert saved["reads/r.json"].expired_at is not None  # the expiry is not undone
    assert saved["scratch/b.md"].expired_at is None
    assert not (machine.agent() / "reads/r.json").exists()  # its bytes went with the expiry
    assert _note(machine)["version"] == 3  # type: ignore[index]


def test_a_rebased_save_keeps_a_file_the_turn_rewrote_after_its_expiry(tmp_path: Path) -> None:
    store = FakeStore()
    machine = _machine(tmp_path, "a", store)
    _turn(machine, {"reads/r.json": b"{}"})
    lease = _open(machine)
    try:
        _expire(store, "reads/r.json")
        _write(lease, "reads/r.json", b'{"again":true}')
        assert asyncio.run(lease.save_snapshot()).status == "saved"
    finally:
        asyncio.run(machine.factory.release_saved(lease))
    revived = _current(store)["reads/r.json"]
    assert revived.expired_at is None
    assert store.blobs[revived.sha256] == b'{"again":true}'


def test_a_save_still_refuses_a_real_conflict(tmp_path: Path) -> None:
    store = FakeStore()
    a, b = _machine(tmp_path, "a", store), _machine(tmp_path, "b", store)
    _turn(a, {"scratch/a.md": b"a"})
    lease = _open(a)
    try:
        _turn(b, {"scratch/a.md": b"changed"})  # another machine, not the expiry job
        _write(lease, "scratch/c.md", b"c")
        assert asyncio.run(lease.save_snapshot()).status == "stale"
        assert _note(a) is None
    finally:
        asyncio.run(a.factory.release_saved(lease))
    assert sorted(_current(store)) == ["scratch/a.md"]


@dataclass
class _WatchfulReceipts(ReceiptSource):
    """A receipt source that answers slowly, out of order, and records how many were in flight.

    The slowest answer goes to the path that is asked for first, so an implementation that
    paired answers with paths by the order they came back would put every receipt on the wrong
    entry.
    """

    order: Sequence[str] = ()
    inflight: int = 0
    peak: int = 0

    async def receipt_for(self, *, workspace_id: str, thread_id: str, path: str) -> Receipt:
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            rank = self.order.index(path) if path in self.order else 0
            await asyncio.sleep(0.01 * (len(self.order) - rank))
        finally:
            self.inflight -= 1
        return Receipt(source="run_crm_action", details={"path": path}, read_again=f"redo {path}")


class _SequentialSnapshotter(WorkspaceSnapshotter):
    """The snapshotter as it was: one receipt looked up at a time, in path order."""

    async def _receipts_for(self, chat, paths):  # type: ignore[no-untyped-def,override]
        return {path: await self._receipt_for(chat, path) for path in paths}


_NEW_FILES = {f"reads/op-{index}.json": f"body {index}".encode() for index in range(6)} | {
    "outputs/t.csv": b"a,b"
}


def _snapshotter(cls: type[WorkspaceSnapshotter], receipts: ReceiptSource):
    return cls(store=FakeStore(), concurrency=4, retry_delays=(0,), receipts=receipts)


def test_a_saves_receipt_lookups_overlap_instead_of_queueing(tmp_path: Path) -> None:
    """Two of the five receipt rules go to the database, and a turn writes many files at once.

    Walked one at a time those round trips are all on the save path, in series. They do not
    depend on each other, so they are gathered — under the same bound a restore's downloads
    use, so a save cannot open more at once than a restore already does.
    """

    del tmp_path
    receipts = _WatchfulReceipts(order=sorted(_NEW_FILES))
    chat = ChatScope(workspace_id=WS, project_id=PROJECT, thread_id=THREAD)

    manifest = asyncio.run(
        _snapshotter(WorkspaceSnapshotter, receipts)._manifest_for(
            _NEW_FILES, previous=None, chat=chat
        )
    )

    assert receipts.peak > 1
    assert receipts.peak <= 4  # …and never more than the transfer bound allows
    assert len(manifest.entries) == len(_NEW_FILES)


def test_gathering_the_receipts_changes_nothing_about_the_file_list(tmp_path: Path) -> None:
    """Byte-identical to looking them up one at a time: same order, same receipt on each entry."""

    del tmp_path
    chat = ChatScope(workspace_id=WS, project_id=PROJECT, thread_id=THREAD)
    order = sorted(_NEW_FILES)
    # One file is unchanged since the previous version, so its carried receipt is exercised too.
    previous = asyncio.run(
        _snapshotter(_SequentialSnapshotter, _WatchfulReceipts(order=order))._manifest_for(
            {"reads/op-0.json": _NEW_FILES["reads/op-0.json"]}, previous=None, chat=chat
        )
    )

    gathered = asyncio.run(
        _snapshotter(WorkspaceSnapshotter, _WatchfulReceipts(order=order))._manifest_for(
            _NEW_FILES, previous=previous, chat=chat
        )
    )
    one_at_a_time = asyncio.run(
        _snapshotter(_SequentialSnapshotter, _WatchfulReceipts(order=order))._manifest_for(
            _NEW_FILES, previous=previous, chat=chat
        )
    )

    carried = gathered.by_path()["reads/op-0.json"]
    assert carried.receipt == previous.by_path()["reads/op-0.json"].receipt
    assert [entry.path for entry in gathered.entries] == order
    assert {entry.path: entry.receipt for entry in gathered.entries} == {
        entry.path: entry.receipt for entry in one_at_a_time.entries
    }
    # ``written_at`` is the one field a second run cannot reproduce, so it is normalised away.
    stamp = datetime(2026, 10, 23, tzinfo=UTC)
    assert encode_manifest(
        SnapshotManifest(entries=tuple(replace(e, written_at=stamp) for e in gathered.entries))
    ) == encode_manifest(
        SnapshotManifest(entries=tuple(replace(e, written_at=stamp) for e in one_at_a_time.entries))
    )
