"""The agent-workspace proofs (ruling AW-16; spec §11 tests 1–8, 10, 13, 14 and WS-18).

F3 Phase 1, plan Task 11: tests 1–4, 8, 10, 13, 14 and WS-18.
F3 Phase 2, plan Task 7: tests 5, 6 and 7 — a cold chat's raw inputs lose their bytes and the next
turn is told so, finished work survives every window, and an erasure leaves nothing anywhere.

Each scenario runs the real pieces end to end: one database (the lane's throwaway test database),
one filesystem storage standing in for R2, and two or three worker areas claimed from one
temporary root — each area with its own factory and snapshotter, which is what two machines are.
Rows are committed (the store opens its own transactions), so every scenario uses its own
workspace id and removes what it wrote.

The Phase 2 scenarios assert on storage as well as on the file list: an entry marked expired that
still has its bytes in R2 has expired nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue
from sqlalchemy import text

from clue_agents.ports import ReceiptSource
from clue_agents.resources import AgentResourceMaterializer
from clue_agents.worker_area import ChatScope, WorkerArea, claim_worker_area
from clue_agents.workspace import AgentWorkspaceFactory, AgentWorkspaceLease
from clue_agents.workspace_policy import PreparedWorkspaceRoot
from clue_agents.workspace_snapshot import LeaseFence, Receipt, SnapshotManifest
from clue_agents.workspace_snapshotter import WorkspaceSnapshotter
from clue_api.agent_workspace_cache import AgentWorkspaceCacheJob
from clue_api.agent_workspace_files_card import build_workspace_files_card
from clue_api.agent_workspace_retention import AgentWorkspaceRetentionJob
from clue_api.agent_workspace_snapshots import DbWorkspaceSnapshotStore
from clue_api.sandbox.policy_sweep import snapshot as sweep_snapshot
from clue_api.sandbox.policy_sweep import sweep
from clue_api.sandbox.workspaces import sandbox_mounts_for_lease
from clue_core import ExecutionId
from clue_db import db_lifespan, transaction
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_storage import FsStorage, agent_workspace_key
from tests.agents.workspace_helpers import RecordingArtifactSink, policy, resource_snapshot
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

PROJECT, THREAD = "project-1", "thread-1"
#: The production windows (``.env.example``): a raw input's bytes go after 48 hours, a working
#: file's after 7 days, a work product's never.
RAW_S = 172800.0
WORKING_S = 604800.0


class CountingStorage(FsStorage):
    """The filesystem backend, recording which blobs it was asked to delete."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.deletes: list[str] = []

    async def delete(self, key: str) -> None:
        self.deletes.append(key)
        await super().delete(key)


@dataclass
class StubReceipts(ReceiptSource):
    """A tool that says what it wrote, so an expired file still tells the agent how to get it.

    Stands in for :class:`~clue_api.agent_workspace_receipts.DbReceiptSource`, whose own joins are
    proven in ``tests/api/test_agent_workspace_receipts_db.py``. What these scenarios need from it
    is only that whatever it answers survives the save, the expiry and the card.
    """

    read_again: str = "These bytes are gone. Call run_crm_action again."

    async def receipt_for(self, *, workspace_id: str, thread_id: str, path: str) -> Receipt:
        return Receipt(
            source="run_crm_action",
            operation_id="11111111-2222-3333-4444-555555555555",
            produced_at=datetime(2026, 10, 22, 9, 30, tzinfo=UTC),
            details={"action": "list_contacts", "path": path},
            read_again=self.read_again,
        )


def _policy():  # type: ignore[no-untyped-def]
    return policy(max_total_bytes=2_000_000, max_file_bytes=1_000_000, max_file_count=200)


@dataclass
class Machine:
    area: WorkerArea
    factory: AgentWorkspaceFactory

    def agent(self, ws: str, thread: str = THREAD) -> Path:
        return self.factory.thread_host_path(ws, PROJECT, thread)


@dataclass
class World:
    ws: str
    root: Path
    storage: CountingStorage
    machines: list[Machine]
    work_id: uuid.UUID

    def machine(self, *, receipts: ReceiptSource | None = None) -> Machine:
        area = claim_worker_area(self.root)
        machine = Machine(
            area=area,
            factory=AgentWorkspaceFactory(
                prepared_root=PreparedWorkspaceRoot(path=area.path),
                artifact_sink=RecordingArtifactSink(),
                area=area,
                snapshotter=WorkspaceSnapshotter(
                    store=DbWorkspaceSnapshotStore(storage=self.storage),
                    concurrency=8,
                    retry_delays=(0, 0, 0),
                    receipts=receipts,
                ),
            ),
        )
        self.machines.append(machine)
        return machine

    def store(self) -> DbWorkspaceSnapshotStore:
        """A reader of the chat's snapshots, over the same storage the machines save through."""

        return DbWorkspaceSnapshotStore(storage=self.storage)

    def chat(self, thread: str = THREAD) -> ChatScope:
        return ChatScope(self.ws, PROJECT, thread)

    def key(self, data: bytes) -> str:
        """Where this chat's snapshot stores these bytes (its own area, ruling AW-26)."""

        return agent_workspace_key(self.ws, hashlib.sha256(data).hexdigest())

    def job(self, *, raw_s: float, working_s: float) -> AgentWorkspaceRetentionJob:
        return AgentWorkspaceRetentionJob(
            store=self.store(), conn_factory=transaction, raw_s=raw_s, working_s=working_s
        )

    async def manifest(self, thread: str = THREAD) -> SnapshotManifest:
        store = self.store()
        pointer = await store.current(workspace_id=self.ws, thread_id=thread)
        assert pointer is not None
        return await store.read_manifest(workspace_id=self.ws, pointer=pointer)

    async def age(self, *, days: float, thread: str = THREAD) -> None:
        """Push the chat's last activity ``days`` into the past, rather than waiting for it."""

        async with transaction() as conn:
            await conn.execute(
                text(
                    "UPDATE agent_workspace_snapshot SET last_activity_at = :t "
                    "WHERE workspace_id = :ws AND thread_id = :th"
                ),
                {"t": datetime.now(UTC) - timedelta(days=days), "ws": self.ws, "th": thread},
            )

    async def erasure(self, key: str) -> tuple[bool, bool]:
        """``(erased, purged)`` of the artifact row for ``key`` — the row itself must exist."""

        async with transaction() as conn:
            row = (
                await conn.execute(
                    text("SELECT erased_at, purged_at FROM artifact WHERE storage_key = :k"),
                    {"k": key},
                )
            ).first()
        assert row is not None, f"no artifact row for {key}"
        return row[0] is not None, row[1] is not None

    async def gone_from_storage(self, key: str) -> bool:
        """The bytes are erased, purged, deleted through the backend, and no longer readable."""

        return (
            await self.erasure(key) == (True, True)
            and key in self.storage.deletes
            and await self.storage.exists(key) is False
        )

    async def stored(self, key: str) -> bool:
        return await self.erasure(key) == (False, False) and await self.storage.exists(key)

    async def fence(self, worker: str) -> LeaseFence:
        """Take the thread's fleet lease the way a worker claiming the turn does."""

        async with transaction() as conn:
            await conn.execute(
                text("UPDATE work_lease SET expires_at = now() WHERE work_id = :w"),
                {"w": self.work_id},
            )
            lease = await acquire_work_lease(
                conn, work_id=WorkId(self.work_id), worker_id=worker, ttl=timedelta(minutes=5)
            )
        assert lease is not None
        return LeaseFence(work_id=self.work_id, worker_id=worker, generation=int(lease.generation))


@asynccontextmanager
async def _world(tmp_path: Path) -> AsyncIterator[World]:
    ws = f"ws-f3s-{uuid.uuid4().hex[:10]}"
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    world = World(
        ws=ws,
        root=root,
        storage=CountingStorage(tmp_path / "r2"),
        machines=[],
        work_id=uuid.uuid4(),
    )
    async with db_lifespan():
        try:
            yield world
        finally:
            for machine in world.machines:
                machine.factory.close()
                machine.area.close()
            async with transaction() as conn:
                for table in ("agent_workspace_snapshot", "artifact_reference", "artifact"):
                    await conn.execute(
                        text(f"DELETE FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                        {"ws": ws},
                    )
                await conn.execute(
                    text("DELETE FROM work_lease WHERE work_id = :w"), {"w": world.work_id}
                )


_EXECUTIONS = iter(range(1, 10_000))


async def _open(
    world: World, machine: Machine, *, fence: LeaseFence | None = None, thread: str = THREAD
) -> AgentWorkspaceLease:
    return await machine.factory.acquire_restored(
        workspace_id=world.ws,
        project_id=PROJECT,
        thread_id=thread,
        execution_id=ExecutionId(uuid.UUID(int=next(_EXECUTIONS))),
        policy=_policy(),
        fence=fence,
    )


def _write(lease: AgentWorkspaceLease, files: dict[str, bytes]) -> None:
    agent = lease.factory.thread_host_path(
        lease.workspace_segment, lease.project_segment, lease.thread_segment
    )
    for path, data in files.items():
        target = agent / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o600)


async def _turn(
    world: World,
    machine: Machine,
    files: dict[str, bytes],
    *,
    worker: str = "worker-a",
    delete: Sequence[str] = (),
) -> str:
    lease = await _open(world, machine, fence=await world.fence(worker))
    try:
        _write(lease, files)
        for path in delete:
            (machine.agent(world.ws) / path).unlink()
        return (await lease.save_snapshot()).status
    finally:
        await machine.factory.release_saved(lease)


def _bytes(machine: Machine, ws: str, path: str) -> bytes:
    return (machine.agent(ws) / path).read_bytes()


def _has(machine: Machine, ws: str, path: str) -> bool:
    return (machine.agent(ws) / path).exists()


def _card(lease: AgentWorkspaceLease) -> dict[str, JsonValue]:
    """The turn-start card this turn's agent is handed, built exactly as the fleet builds it."""

    base = lease.snapshot_base
    return build_workspace_files_card(
        None if base is None else base.manifest, now=datetime.now(UTC)
    )


def _section(card: dict[str, JsonValue], section: str) -> list[dict[str, JsonValue]]:
    """One list of the card — ``live`` or ``expired`` — as the agent is shown it."""

    entries = card[section]
    assert isinstance(entries, list)
    listed: list[dict[str, JsonValue]] = []
    for entry in entries:
        assert isinstance(entry, dict)
        listed.append(entry)
    return listed


def _paths(card: dict[str, JsonValue], section: str) -> list[str]:
    return [str(entry["path"]) for entry in _section(card, section)]


def test_1_two_machines_one_chat(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            files = {
                "scratch/notes.md": b"cycle ~42 days",
                "outputs/t.csv": b"deal,amount\nA,10\n",
                "reads/00000000-0000-0000-0000-000000000001.json": b'{"deals": 28}',
            }
            assert await _turn(world, a, files) == "saved"
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                for path, data in files.items():
                    assert _bytes(b, world.ws, path) == data
                _write(lease, {"scratch/notes.md": b"revised on B"})
                assert (await lease.save_snapshot()).status == "saved"
            finally:
                await b.factory.release_saved(lease)
            lease = await _open(world, a, fence=await world.fence("worker-a"))
            try:
                assert lease.restore_report is not None
                assert lease.restore_report.warm is False
                assert lease.restore_report.downloaded == 1
                assert _bytes(a, world.ws, "scratch/notes.md") == b"revised on B"
            finally:
                await a.factory.release_saved(lease)

    run_async(scenario())


def test_2_warm_second_turn_downloads_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a = world.machine()
            await _turn(world, a, {"scratch/n.md": b"n"})
            lease = await _open(world, a, fence=await world.fence("worker-a"))
            try:
                assert lease.restore_report is not None
                assert lease.restore_report.warm is True
                assert lease.restore_report.downloaded == 0
            finally:
                await a.factory.release_saved(lease)

    run_async(scenario())


def test_3_kill_before_save_and_after_save(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            await _turn(world, a, {"scratch/n.md": b"v1"})
            # Killed before its save: nothing of that attempt is in the snapshot.
            lease = await _open(world, a, fence=await world.fence("worker-a"))
            _write(lease, {"scratch/n.md": b"lost"})
            a.factory.release(lease)
            retry = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                assert _bytes(b, world.ws, "scratch/n.md") == b"v1"
            finally:
                b.factory.release(retry)
            # Killed after its save, before the turn committed: the retry sees the saved version.
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            _write(lease, {"scratch/n.md": b"v2"})
            assert (await lease.save_snapshot()).status == "saved"
            b.factory.release(lease)
            retry = await _open(world, a, fence=await world.fence("worker-a"))
            try:
                assert _bytes(a, world.ws, "scratch/n.md") == b"v2"
                _write(retry, {"scratch/m.md": b"retried"})
                report = await retry.save_snapshot()
                assert (report.status, report.version) == ("saved", 3)
            finally:
                await a.factory.release_saved(retry)

    run_async(scenario())


def test_4_a_zombie_save_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            await _turn(world, a, {"scratch/n.md": b"v1"})
            zombie = await _open(world, a, fence=await world.fence("worker-a"))
            # The fleet hands the turn to worker B (a takeover moves the lease generation on).
            await _turn(world, b, {"scratch/n.md": b"b wins"}, worker="worker-b")
            _write(zombie, {"scratch/n.md": b"late zombie write"})
            assert (await zombie.save_snapshot()).status == "fenced"
            a.factory.release(zombie)
            check = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                assert _bytes(b, world.ws, "scratch/n.md") == b"b wins"
            finally:
                await b.factory.release_saved(check)
            # A stale version is refused even while the lease is still held: B saves a newer
            # version without touching the lease (no fence), so A's save fails on the version.
            stale = await _open(world, a, fence=await world.fence("worker-a"))
            newer = await _open(world, b)
            try:
                _write(newer, {"scratch/n.md": b"newer"})
                assert (await newer.save_snapshot()).status == "saved"
            finally:
                await b.factory.release_saved(newer)
            _write(stale, {"scratch/n.md": b"stale"})
            assert (await stale.save_snapshot()).status == "stale"
            a.factory.release(stale)

    run_async(scenario())


def test_5_raw_expiry_removes_bytes_keeps_receipt_and_the_next_turn_sees_it(
    tmp_path: Path,
) -> None:
    """§11 test 5: a cold chat's raw input loses its bytes, and the next turn is told exactly."""

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            receipts = StubReceipts()
            a, b = world.machine(receipts=receipts), world.machine(receipts=receipts)
            raw = b'{"deals": 28}'
            rough = b"cycle ~42 days"
            assert await _turn(world, a, {"reads/r.json": raw, "scratch/a.md": rough}) == "saved"
            await world.age(days=3)

            report = await world.job(raw_s=RAW_S, working_s=WORKING_S).run_once()

            assert (report.chats_checked, report.chats_expired, report.files_expired) == (1, 1, 1)
            assert (report.skipped_busy, report.stale) == (0, 0)
            manifest = await world.manifest()
            expired = manifest.by_path()["reads/r.json"]
            assert expired.expired_at is not None
            assert expired.receipt is not None
            assert expired.receipt.read_again == receipts.read_again
            assert [entry.path for entry in manifest.live()] == ["scratch/a.md"]
            # The point of the job: the raw bytes are gone from storage, not merely unlisted.
            assert await world.gone_from_storage(world.key(raw))
            # The agent's own rough work is still within its 7 days and is untouched.
            assert await world.stored(world.key(rough))

            # The chat's next turn, on another machine.
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                assert not _has(b, world.ws, "reads/r.json")
                assert _bytes(b, world.ws, "scratch/a.md") == rough
                card = _card(lease)
                assert _paths(card, "live") == ["scratch/a.md"]
                assert _paths(card, "expired") == ["reads/r.json"]
                gone_entry = _section(card, "expired")[0]
                assert gone_entry["tier"] == "raw_input"
                assert gone_entry["receipt"] == {
                    "source": "run_crm_action",
                    "operation_id": "11111111-2222-3333-4444-555555555555",
                    "produced_at": "2026-10-22T09:30:00+00:00",
                    "details": {"action": "list_contacts", "path": "reads/r.json"},
                    "read_again": receipts.read_again,
                }
                # WS-26: the agent reads the same thing again and saves it. The erased row is
                # resurrected and the blob put back — an erasure must never poison a key.
                _write(lease, {"reads/r2.json": raw})
                assert (await lease.save_snapshot()).status == "saved"
            finally:
                await b.factory.release_saved(lease)
            assert await world.stored(world.key(raw))

            # The machine that still had the expired copy on disk loses it on its next restore.
            assert _has(a, world.ws, "reads/r.json")
            lease = await _open(world, a, fence=await world.fence("worker-a"))
            try:
                assert lease.restore_report is not None
                assert (lease.restore_report.deleted, lease.restore_report.downloaded) == (1, 1)
                assert not _has(a, world.ws, "reads/r.json")
                assert _bytes(a, world.ws, "reads/r2.json") == raw
                assert _paths(_card(lease), "expired") == ["reads/r.json"]
            finally:
                await a.factory.release_saved(lease)

    run_async(scenario())


def test_6_work_products_survive_the_expiry_job(tmp_path: Path) -> None:
    """§11 test 6: ``outputs/`` outlives a cache wipe and every window (AW-2)."""

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            finished = b"deal,amount\nA,10\n"
            rough = b"my own notes"
            raw = b'{"deals": 28}'
            files = {"outputs/o.csv": finished, "scratch/a.md": rough, "reads/r.json": raw}
            assert await _turn(world, a, files) == "saved"
            # The worker's copy is only a cache (AW-23): its whole folder goes.
            AgentWorkspaceCacheJob(area=a.area, idle_s=0, max_bytes=0).run_once()
            assert not a.factory.chat_host_path(world.chat()).exists()

            report = await world.job(raw_s=0.0, working_s=WORKING_S).run_once()

            assert (report.chats_expired, report.files_expired) == (1, 1)
            manifest = await world.manifest()
            assert [entry.path for entry in manifest.live()] == ["outputs/o.csv", "scratch/a.md"]
            assert [entry.path for entry in manifest.expired()] == ["reads/r.json"]
            assert await world.stored(world.key(finished))
            assert await world.stored(world.key(rough))

            # A turn on another machine gets both of them back from the snapshot.
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                assert _bytes(b, world.ws, "outputs/o.csv") == finished
                assert _bytes(b, world.ws, "scratch/a.md") == rough
                assert not _has(b, world.ws, "reads/r.json")
                assert _paths(_card(lease), "live") == ["outputs/o.csv", "scratch/a.md"]
            finally:
                await b.factory.release_saved(lease)

            # AW-2: no window expires finished work — not even one that has passed for
            # everything else, on a chat nobody has touched for over a year.
            await world.age(days=400)

            second = await world.job(raw_s=0.0, working_s=0.0).run_once()

            assert (second.chats_expired, second.files_expired) == (1, 1)
            manifest = await world.manifest()
            assert [entry.path for entry in manifest.live()] == ["outputs/o.csv"]
            assert {entry.path for entry in manifest.expired()} == {"reads/r.json", "scratch/a.md"}
            kept = manifest.by_path()["outputs/o.csv"]
            assert kept.expired_at is None and kept.tier == "work_product"
            assert await world.store().read_file(workspace_id=world.ws, entry=kept) == finished
            assert await world.gone_from_storage(world.key(rough))

    run_async(scenario())


def test_7_erasing_a_chat_leaves_nothing_in_storage_and_no_root_reuses_its_copy(
    tmp_path: Path,
) -> None:
    """§11 test 7: a privacy erasure (WS-27, WS-31) takes the record, the bytes and every copy."""

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            files = {
                "outputs/o.csv": b"deal,amount\nA,10\n",
                "scratch/a.md": b"cycle ~42 days",
                "reads/r.json": b'{"deals": 28}',
            }
            assert await _turn(world, a, files) == "saved"
            # The chat's next turn runs on B, so two machines hold a copy of it.
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                for path, data in files.items():
                    assert _bytes(b, world.ws, path) == data
            finally:
                b.factory.release(lease)
            store = world.store()
            pointer = await store.current(workspace_id=world.ws, thread_id=THREAD)
            assert pointer is not None
            keys = {pointer.manifest_key, *(world.key(data) for data in files.values())}

            assert await a.factory.forget_chat(world.chat()) is True

            assert await store.current(workspace_id=world.ws, thread_id=THREAD) is None
            for key in sorted(keys):
                assert await world.gone_from_storage(key), key
            assert not a.factory.chat_host_path(world.chat()).exists()

            # B's copy survives the erasure on disk — until B opens the chat again, which finds
            # no record and empties the folder rather than letting a byte of it be used (WS-16).
            assert _bytes(b, world.ws, "outputs/o.csv") == files["outputs/o.csv"]
            lease = await _open(world, b)
            try:
                assert lease.restore_report is not None
                assert lease.restore_report.deleted == len(files)
                assert lease.snapshot_base is not None
                assert lease.snapshot_base.manifest is None
                for path in files:
                    assert not _has(b, world.ws, path)
                card = _card(lease)
                assert (card["live"], card["expired"], card["omitted"]) == ([], [], {})
            finally:
                b.factory.release(lease)

            swept = AgentWorkspaceCacheJob(area=b.area, idle_s=0, max_bytes=0).run_once()

            assert f"{world.ws}/{PROJECT}/{THREAD}" in swept.removed
            assert not b.factory.chat_host_path(world.chat()).exists()

    run_async(scenario())


def test_8_cleanup_stays_in_its_own_area(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            await _turn(world, a, {"scratch/n.md": b"a"})
            running = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                # A's sweep with no idle window at all, and a third worker starting up: neither
                # touches B's area while B runs a turn.
                AgentWorkspaceCacheJob(area=a.area, idle_s=0, max_bytes=0).run_once()
                world.machine()
                assert (b.agent(world.ws) / "scratch" / "n.md").read_bytes() == b"a"
                assert not (a.area.path / "chats").exists() or not any(
                    (a.area.path / "chats").iterdir()
                )
                # B's own sweep skips the chat B is running.
                AgentWorkspaceCacheJob(area=b.area, idle_s=0, max_bytes=0).run_once()
                assert b.agent(world.ws).is_dir()
            finally:
                await b.factory.release_saved(running)

    run_async(scenario())


def test_10_sandbox_after_restore(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            await _turn(world, a, {"scratch/n.md": b"n", "outputs/t.csv": b"1,2"})
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                agent = b.agent(world.ws)
                for path in ("scratch/n.md", "outputs/t.csv"):
                    metadata = (agent / path).stat()
                    assert stat.S_IMODE(metadata.st_mode) == 0o600
                    assert metadata.st_uid == os.getuid()
                for folder in ("scratch", "outputs"):
                    assert stat.S_IMODE((agent / folder).stat().st_mode) == 0o700
                mounts = sandbox_mounts_for_lease(
                    lease, b.factory, brand=None, project_library=False, attachments=False
                )
                assert all(path.is_dir() for path in mounts.read_write.values())
                before = sweep_snapshot(mounts)
                assert sweep(mounts, before=before).removed == ()
            finally:
                await b.factory.release_saved(lease)

    run_async(scenario())


def test_13_recipe_folders_update_in_place(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a = world.machine()
            snapshot, seeds = resource_snapshot()
            lease = await _open(world, a)
            AgentResourceMaterializer().materialize(
                lease=lease, snapshot=snapshot, seed_files=seeds
            )
            skill = a.agent(world.ws) / ".deepagent/skills/project-planning/1.0.0/SKILL.md"
            before = skill.stat().st_ino
            await a.factory.release_saved(lease)
            lease = await _open(world, a)
            try:
                AgentResourceMaterializer().materialize(
                    lease=lease, snapshot=snapshot, seed_files=seeds
                )
                assert skill.stat().st_ino == before
            finally:
                await a.factory.release_saved(lease)

    run_async(scenario())


def test_14_two_chats_never_share_a_folder(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a = world.machine()
            first = await _open(world, a, thread="thread-a")
            second = await _open(world, a, thread="thread-b")
            try:
                _write(first, {"scratch/a.md": b"only in chat a"})
                assert not (a.agent(world.ws, "thread-b") / "scratch" / "a.md").exists()
                await a.factory.release_saved(first)
                assert a.factory.remove_chat(ChatScope(world.ws, PROJECT, "thread-a")) is True
                _write(second, {"scratch/b.md": b"still here"})
                assert (await second.save_snapshot()).status == "saved"
            finally:
                await a.factory.release_saved(second)
            assert not a.factory.chat_host_path(ChatScope(world.ws, PROJECT, "thread-a")).exists()

    run_async(scenario())


def test_ws18_resume_on_a_newer_profile(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            a, b = world.machine(), world.machine()
            old, seeds = resource_snapshot()
            lease = await _open(world, a, fence=await world.fence("worker-a"))
            AgentResourceMaterializer().materialize(lease=lease, snapshot=old, seed_files=seeds)
            _write(lease, {"scratch/plan.md": b"my plan"})
            assert (await lease.save_snapshot()).status == "saved"
            await a.factory.release_saved(lease)
            # The chat continues elsewhere under whatever profile is current there: the restore
            # brings the agent's own files and never pins a profile, a skill or a recipe folder.
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                assert _bytes(b, world.ws, "scratch/plan.md") == b"my plan"
                assert not (b.agent(world.ws) / ".deepagent" / "manifest.json").exists()
                AgentResourceMaterializer().materialize(lease=lease, snapshot=old, seed_files=seeds)
                assert (b.agent(world.ws) / ".deepagent" / "manifest.json").exists()
                assert _bytes(b, world.ws, "scratch/plan.md") == b"my plan"
            finally:
                await b.factory.release_saved(lease)

    run_async(scenario())


_ = asyncio
