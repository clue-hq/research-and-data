"""The agent-workspace proofs (ruling AW-16; spec §11 tests 1–10, 13, 14 and WS-18).

F3 Phase 1, plan Task 11: tests 1–4, 8, 10, 13, 14 and WS-18.
F3 Phase 2, plan Task 7: tests 5, 6 and 7 — a cold chat's raw inputs lose their bytes and the next
turn is told so, finished work survives every window, and an erasure leaves nothing anywhere.
F3 Phase 3, plan Task 4: test 9 — research reconciliation on one machine reads a source run
another machine saved, from its snapshot.
F3 Phase 3, plan Task 5 (WS-35): the snapshots switch turned off and back on loses no saved
version — and leaves the switched-off period's ``<root>/local`` copy on the machine.

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
import json
import os
import stat
import subprocess
import sys
import time
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
from clue_api.agent_workspace_snapshots import SNAPSHOT_REFERENCE_KIND, DbWorkspaceSnapshotStore
from clue_api.agent_workspace_wiring import LOCAL_DIR, build_agent_workspace_factory
from clue_api.quality_research_wiring import copy_source_run_files, write_reconciliation_files
from clue_api.sandbox.policy_sweep import snapshot as sweep_snapshot
from clue_api.sandbox.policy_sweep import sweep
from clue_api.sandbox.workspaces import sandbox_mounts_for_lease
from clue_config import Settings
from clue_core import ExecutionId
from clue_db import db_lifespan, transaction
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_storage import (
    FsStorage,
    agent_workspace_key,
    artifact_key,
    is_agent_workspace_key,
    record_artifact,
    retain_artifact,
)
from tests.agents.workspace_helpers import RecordingArtifactSink, policy, resource_snapshot
from tests.api.agent_workspace_retention_scope import ScopedRetentionJob
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
        """The real job, held to this world's workspace: a zero-second window here must not
        expire the files of other tests' chats in the shared test database (fix pass 2)."""

        return ScopedRetentionJob(
            workspaces={self.ws},
            store=self.store(),
            conn_factory=transaction,
            raw_s=raw_s,
            working_s=working_s,
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


def _bytes(machine: Machine, ws: str, path: str, thread: str = THREAD) -> bytes:
    return (machine.agent(ws, thread) / path).read_bytes()


def _has(machine: Machine, ws: str, path: str, thread: str = THREAD) -> bool:
    return (machine.agent(ws, thread) / path).exists()


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
                # And the one line that explains all of this to the agent, in the words the
                # founder approved on 2026-10-23 and no others (ledger T7-c).
                assert card["note"] == (
                    "Files are deleted by age: what a tool pulled down after 48 hours, your own "
                    "working files after 7 days. outputs/ is kept for the life of the chat."
                )
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


def test_9_research_reconciliation_reads_the_source_snapshot_across_roots(tmp_path: Path) -> None:
    """§11 test 9: a reconciling research turn on one machine copies the notes and raw reads of
    a source run another machine saved, byte for byte, and says which snapshot it read.

    Root B holds nothing of the source run before the copy, so every byte the reconciling turn
    gets must have come back from the source run's snapshot — not from a leftover local copy.
    """

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            source_thread = f"research-quality-{uuid.uuid4()}"
            reconciling_thread = f"research-quality-{uuid.uuid4()}"
            # Non-ASCII text and a raw read: byte identity is about more than plain ASCII.
            files = {
                "work/notes.md": "Renewal cycle ≈ 42 days — confirmed by two reads.\n".encode(),
                "reads/raw.json": b'{"deals": 28, "owner": "Zo\xc3\xab", "stages": ["won"]}',
            }

            a = world.machine()
            source = await _open(
                world, a, fence=await world.fence("worker-a"), thread=source_thread
            )
            try:
                _write(source, files)
                saved = await source.save_snapshot()
                assert (saved.status, saved.version) == ("saved", 1)
            finally:
                await a.factory.release_saved(source)

            b = world.machine()
            assert b.area.path != a.area.path
            # B is cold: nothing of the source run, under any path, is on its disk.
            assert not b.agent(world.ws, source_thread).exists()
            assert not any(source_thread in str(p) for p in b.area.path.rglob("*"))

            lease = await _open(world, b, thread=reconciling_thread)
            source_on_b = await _open(world, b, thread=source_thread)
            try:
                assert source_on_b.restore_report is not None
                assert source_on_b.restore_report.warm is False
                assert source_on_b.restore_report.downloaded == len(files)
                block = await copy_source_run_files(
                    lease=lease,
                    source_lease=source_on_b,
                    readable_prefixes=_policy().readable_prefixes,
                    source_thread_id=source_thread,
                )
            finally:
                await b.factory.release_saved(source_on_b)
            try:
                expected = {"thread_id": source_thread, "version": 1, "files_copied": 2}
                assert block == expected
                # The copies are in the reconciling turn's own folders on B, as A wrote them —
                # ``work/`` through the text write, ``reads/`` through the spill path.
                for path, data in files.items():
                    assert _bytes(b, world.ws, path, thread=reconciling_thread) == data, path
                assert (
                    await lease.backend.read_text("work/notes.md")
                    == files["work/notes.md"].decode()
                )

                await write_reconciliation_files(
                    lease=lease,
                    reconciliation={
                        "claims": [{"id": "c-1", "status": "stale"}],
                        "_editorial_system": "Reconcile the claims against the source notes.",
                    },
                    source_snapshot=block,
                )
                written = json.loads(
                    await lease.backend.read_text("work/reconciliation/input.json")
                )
                assert written["source_snapshot"] == expected
            finally:
                await b.factory.release_saved(lease)

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


#: The four other kinds of agent that open a workspace through the same layer, each with the
#: thread id its production wiring builds (WS-34). None of them files ``agent_turn_submission``
#: rows or leases the thread's work id, so the snapshot row's own ``last_activity_at`` is the only
#: activity the expiry job sees for them — which is why each is proved here and not only chats.
CALLER_SHAPES = {
    # platform/api/clue_api/account_research_turn_wiring.py
    "account-research": f"account-research-{uuid.uuid4()}",
    # platform/api/clue_api/specialist_wiring.py
    "delegation": f"delegation-{uuid.uuid4()}",
    # platform/api/clue_api/onboarding_synthesis_wiring.py — the extra segments are the point
    "onboarding-synthesis": f"onboarding-synthesis-{uuid.uuid4()}-persona-icp_key_1",
    # platform/api/clue_api/quality_research_wiring.py
    "research-quality": f"research-quality-{uuid.uuid4()}",
}


@pytest.mark.parametrize("thread", list(CALLER_SHAPES.values()), ids=list(CALLER_SHAPES))
def test_15_every_caller_shape_round_trips_and_expires(tmp_path: Path, thread: str) -> None:
    """WS-34: a research run, a delegation, onboarding synthesis and a quality run, end to end.

    Each restores, saves, continues on another machine, goes cold and loses its rough work's
    bytes exactly as a chat does — opened the way its wiring opens it: no fence, no submissions.
    """

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            receipts = StubReceipts()
            a, b = world.machine(receipts=receipts), world.machine(receipts=receipts)
            raw = f'{{"run": "{thread}"}}'.encode()
            rough = f"notes for {thread}".encode()
            finished = f"account,score\n{thread},10\n".encode()
            files = {"reads/r.json": raw, "scratch/a.md": rough, "outputs/o.csv": finished}

            lease = await _open(world, a, thread=thread)
            try:
                assert lease.restore_report is not None
                assert lease.snapshot_base is not None
                assert lease.snapshot_base.pointer is None  # a new run: nothing to restore
                _write(lease, files)
                report = await lease.save_snapshot()
                assert (report.status, report.version) == ("saved", 1)
            finally:
                await a.factory.release_saved(lease)
            # A's copy is only a cache: the sweep finds this folder id under its own key.
            swept = AgentWorkspaceCacheJob(area=a.area, idle_s=0, max_bytes=0).run_once()
            assert f"{world.ws}/{PROJECT}/{thread}" in swept.removed
            assert not a.factory.chat_host_path(world.chat(thread)).exists()

            # The run continues on another machine, which has never seen it.
            lease = await _open(world, b, thread=thread)
            try:
                assert lease.restore_report is not None
                assert lease.restore_report.warm is False
                assert lease.restore_report.downloaded == len(files)
                for path, data in files.items():
                    assert _bytes(b, world.ws, path, thread) == data, path
            finally:
                await b.factory.release_saved(lease)

            # Aged after its last restore (a restore is activity, WS-34a): past both windows.
            await world.age(days=8, thread=thread)

            job = await world.job(raw_s=RAW_S, working_s=WORKING_S).run_once()

            assert (job.chats_checked, job.chats_expired, job.files_expired) == (1, 1, 2)
            assert (job.skipped_busy, job.stale, job.failed) == (0, 0, 0)
            manifest = await world.manifest(thread)
            assert [entry.path for entry in manifest.live()] == ["outputs/o.csv"]
            assert sorted(entry.path for entry in manifest.expired()) == [
                "reads/r.json",
                "scratch/a.md",
            ]
            for entry in manifest.expired():
                assert entry.expired_at is not None
                assert entry.receipt is not None
                assert entry.receipt.read_again == receipts.read_again
            assert await world.gone_from_storage(world.key(raw))
            assert await world.gone_from_storage(world.key(rough))
            assert await world.stored(world.key(finished))

            # The run's next turn on B: the copies of the expired files go, the card says so.
            lease = await _open(world, b, thread=thread)
            try:
                assert lease.restore_report is not None
                assert (lease.restore_report.deleted, lease.restore_report.downloaded) == (2, 0)
                assert not _has(b, world.ws, "reads/r.json", thread)
                assert not _has(b, world.ws, "scratch/a.md", thread)
                assert _bytes(b, world.ws, "outputs/o.csv", thread) == finished
                card = _card(lease)
                assert _paths(card, "live") == ["outputs/o.csv"]
                assert sorted(_paths(card, "expired")) == ["reads/r.json", "scratch/a.md"]
                tiers = {str(item["path"]): item["tier"] for item in _section(card, "expired")}
                assert tiers == {"reads/r.json": "raw_input", "scratch/a.md": "working_file"}
            finally:
                await b.factory.release_saved(lease)

    run_async(scenario())


@pytest.mark.parametrize("thread", list(CALLER_SHAPES.values()), ids=list(CALLER_SHAPES))
def test_16_a_run_longer_than_its_window_keeps_its_files(tmp_path: Path, thread: str) -> None:
    """Review Focus 2: the expiry lands while a run is still open, and the run loses nothing.

    The run's save loses its compare-and-set to the job's expiry-only version, rebases onto it
    (AW-24), and keeps every file the run wrote; the expired entry stays expired and its bytes
    stay gone — the run's stale local copy of it must not upload them again.
    """

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            receipts = StubReceipts()
            a, b = world.machine(receipts=receipts), world.machine(receipts=receipts)
            raw = f'{{"run": "{thread}"}}'.encode()
            rough = f"notes for {thread}".encode()
            lease = await _open(world, a, thread=thread)
            try:
                _write(lease, {"reads/r.json": raw, "scratch/a.md": rough})
                assert (await lease.save_snapshot()).status == "saved"
            finally:
                await a.factory.release_saved(lease)

            # The run opens (the restore stamps its activity) and is still running when, 3 days
            # later, the job comes round: the raw window has passed, the working one has not.
            run = await _open(world, a, thread=thread)
            try:
                assert _bytes(a, world.ws, "reads/r.json", thread) == raw
                await world.age(days=3, thread=thread)

                job = await world.job(raw_s=RAW_S, working_s=WORKING_S).run_once()

                assert (job.chats_checked, job.chats_expired, job.files_expired) == (1, 1, 1)
                assert (job.skipped_busy, job.stale, job.failed) == (0, 0, 0)
                assert [e.path for e in (await world.manifest(thread)).expired()] == [
                    "reads/r.json"
                ]
                assert await world.gone_from_storage(world.key(raw))

                # The run writes its own work and saves, on the version it restored.
                new = {"outputs/new.csv": b"a,b\n1,2\n", "scratch/b.md": b"more notes"}
                _write(run, new)
                report = await run.save_snapshot()
                assert (report.status, report.version) == ("saved", 3)
            finally:
                await a.factory.release_saved(run)

            manifest = await world.manifest(thread)
            assert [entry.path for entry in manifest.live()] == [
                "outputs/new.csv",
                "scratch/a.md",
                "scratch/b.md",
            ]
            gone = manifest.by_path()["reads/r.json"]
            assert gone.expired_at is not None
            assert gone.receipt is not None and gone.receipt.read_again == receipts.read_again
            # The bytes did not come back with the run's save: the expiry stands in storage.
            assert await world.gone_from_storage(world.key(raw))
            assert await world.stored(world.key(rough))
            for data in new.values():
                assert await world.stored(world.key(data))
            # The rebase dropped the run's released copy, as a restore would have.
            assert not _has(a, world.ws, "reads/r.json", thread)

            # Another machine picks the run up: the run's files, and the expired one as a receipt.
            lease = await _open(world, b, thread=thread)
            try:
                assert lease.restore_report is not None
                assert lease.restore_report.downloaded == 3
                assert not _has(b, world.ws, "reads/r.json", thread)
                assert _bytes(b, world.ws, "scratch/a.md", thread) == rough
                for path, data in new.items():
                    assert _bytes(b, world.ws, path, thread) == data
                card = _card(lease)
                assert _paths(card, "expired") == ["reads/r.json"]
                assert _paths(card, "live") == ["outputs/new.csv", "scratch/a.md", "scratch/b.md"]
            finally:
                await b.factory.release_saved(lease)

    run_async(scenario())


_ = asyncio


# --- A chat saved before Phase 2 (fix pass 1, review C1) ------------------------------------------

PHASE_1_FILES = {
    "outputs/t.csv": b"deal,amount\nA,10\n",
    "reads/00000000-0000-0000-0000-000000000001.json": b'{"deals": 28}',
    "scratch/notes.md": b"cycle ~42 days",
}


async def _plant_phase_1_chat(world: World, files: dict[str, bytes]) -> dict[str, str]:
    """A chat exactly as Phase 1 left it, and return the bare key of each file's bytes.

    A schema-1 file list (every non-raw file called a work product, no receipts, no expiries),
    every byte — the list's own included — recorded, held and stored ONLY under the bare
    ``{ws}/{sha}`` key, and a version record whose manifest key has that old shape too. Nothing in
    the chat's own area: that is what a Phase 1 chat looks like the moment Phase 2 deploys.
    """

    written = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    document = {
        "schema_version": 1,
        "entries": [
            {
                "path": path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "media_type": "text/plain",
                "tier": "raw_input" if path.startswith("reads/") else "work_product",
                "written_at": written.isoformat(),
            }
            for path, data in sorted(files.items())
        ],
    }
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    manifest_sha = hashlib.sha256(body).hexdigest()
    blobs = {hashlib.sha256(data).hexdigest(): data for data in files.values()}
    blobs[manifest_sha] = body
    async with transaction() as conn:
        for sha, data in blobs.items():
            key = artifact_key(world.ws, sha)
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=world.ws,
                content_sha256=sha,
                media_type="text/plain",
                size_bytes=len(data),
            )
            await retain_artifact(
                conn,
                workspace_id=world.ws,
                storage_key=key,
                reference_kind=SNAPSHOT_REFERENCE_KIND,
                reference_id=THREAD,
            )
        await conn.execute(
            text(
                "INSERT INTO agent_workspace_snapshot (workspace_id, thread_id, project_id, "
                "version, manifest_artifact_key, manifest_sha256) "
                "VALUES (:ws, :th, :prj, 1, :key, :sha)"
            ),
            {
                "ws": world.ws,
                "th": THREAD,
                "prj": PROJECT,
                "key": artifact_key(world.ws, manifest_sha),
                "sha": manifest_sha,
            },
        )
    for sha, data in blobs.items():
        await FsStorage.put(
            world.storage, artifact_key(world.ws, sha), data, media_type="text/plain"
        )
    keys = {
        path: artifact_key(world.ws, hashlib.sha256(data).hexdigest())
        for path, data in files.items()
    }
    keys["<manifest>"] = artifact_key(world.ws, manifest_sha)
    return keys


async def _held(world: World, thread: str = THREAD) -> set[str]:
    async with transaction() as conn:
        rows = await conn.execute(
            text(
                "SELECT storage_key FROM artifact_reference WHERE workspace_id = :ws "
                "AND reference_kind = :kind AND reference_id = :th"
            ),
            {"ws": world.ws, "kind": SNAPSHOT_REFERENCE_KIND, "th": thread},
        )
    return {str(row[0]) for row in rows}


def test_17_a_phase_1_chat_moves_to_its_own_area_on_its_next_save(tmp_path: Path) -> None:
    """Review C1: a turn on a chat Phase 1 saved changes one file and leaves the others alone.

    The snapshotter uploads only what changed, so the unchanged files' bytes existed only under
    the old bare key and the save — which holds every live file in the chat's own area — had
    nothing to hold: ``ArtifactIntegrityError``, the turn failed, and its outputs were never saved,
    on every later turn too. The save must carry the unchanged files into the new area from the
    bytes the turn already has on disk, release the old keys and erase none of them (AW-26).
    """

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            old = await _plant_phase_1_chat(world, PHASE_1_FILES)
            a, c = world.machine(), world.machine()

            lease = await _open(world, a, fence=await world.fence("worker-a"))
            try:
                for path, data in PHASE_1_FILES.items():
                    assert _bytes(a, world.ws, path) == data, path
                _write(lease, {"scratch/notes.md": b"cycle ~40 days, revised"})
                report = await lease.save_snapshot()
                assert (report.status, report.version) == ("saved", 2)
            finally:
                await a.factory.release_saved(lease)

            expected = {**PHASE_1_FILES, "scratch/notes.md": b"cycle ~40 days, revised"}
            manifest = await world.manifest()
            assert {entry.path for entry in manifest.live()} == set(expected)
            # Every live file of the new version is held, and stored, in the chat's own area.
            held = await _held(world)
            assert all(is_agent_workspace_key(key) for key in held), held
            for data in expected.values():
                assert world.key(data) in held
                assert await world.stored(world.key(data))
            # The old keys are only released — their bytes may be an upload's (AW-26).
            for key in old.values():
                assert key not in held
                assert await world.erasure(key) == (False, False)
                assert await world.storage.exists(key)
            assert not any(key in world.storage.deletes for key in old.values())

            # A third machine needs nothing from the old area: take its bytes away and restore.
            for key in old.values():
                await FsStorage.delete(world.storage, key)
            lease = await _open(world, c, fence=await world.fence("worker-c"))
            try:
                assert lease.restore_report is not None and lease.restore_report.warm is False
                for path, data in expected.items():
                    assert _bytes(c, world.ws, path) == data, path
            finally:
                await c.factory.release_saved(lease)

    run_async(scenario())


def test_18_the_expiry_job_moves_a_cold_phase_1_chat_to_its_own_area(tmp_path: Path) -> None:
    """Review C1, the job's side: its save of a cold Phase 1 chat holds the files it keeps in the
    chat's own area too, and it has no local copy to upload them from — so before the fix the
    chat failed every pass and never expired. It must carry them over from the old keys."""

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            old = await _plant_phase_1_chat(world, PHASE_1_FILES)
            raw_path = "reads/00000000-0000-0000-0000-000000000001.json"
            await world.age(days=3)

            await world.job(raw_s=RAW_S, working_s=WORKING_S).run_once()

            manifest = await world.manifest()
            assert [entry.path for entry in manifest.expired()] == [raw_path]
            assert {entry.path for entry in manifest.live()} == {
                "outputs/t.csv",
                "scratch/notes.md",
            }
            held = await _held(world)
            assert all(is_agent_workspace_key(key) for key in held), held
            for path in ("outputs/t.csv", "scratch/notes.md"):
                assert await world.stored(world.key(PHASE_1_FILES[path]))
                assert world.key(PHASE_1_FILES[path]) in held
            for key in old.values():
                assert key not in held
                assert await world.erasure(key) == (False, False)
                assert await world.storage.exists(key)

            for key in old.values():
                await FsStorage.delete(world.storage, key)
            b = world.machine()
            lease = await _open(world, b, fence=await world.fence("worker-b"))
            try:
                assert not _has(b, world.ws, raw_path)
                for path in ("outputs/t.csv", "scratch/notes.md"):
                    assert _bytes(b, world.ws, path) == PHASE_1_FILES[path]
            finally:
                await b.factory.release_saved(lease)

    run_async(scenario())


# --- F3 Phase 3, plan Task 5: the emergency switch (WS-35) --------------------------------------


def _built_machine(world: World, root: Path, *, snapshots: bool) -> Machine:
    """A machine composed by the production builder, with the switch set on its own settings.

    The real ``build_agent_workspace_factory``, not a hand-built imitation: with snapshots on it
    claims ``<root>/workers/area-<n>`` and has a snapshotter; with them off it opens the shared,
    unlocked ``<root>/local`` and has none. The ``.env`` is never touched.
    """

    source, home = world.root.parent / "source", world.root.parent / "home"
    for folder in (source, home):
        folder.mkdir(mode=0o700, exist_ok=True)
    factory = build_agent_workspace_factory(
        storage=world.storage,
        settings=Settings(
            _env_file=None,
            agent_workspace_root=str(root),
            agent_workspace_snapshots_enabled=snapshots,
        ),
        source_root=source,
        home_root=home,
    )
    assert factory.area is not None
    machine = Machine(area=factory.area, factory=factory)
    world.machines.append(machine)
    return machine


def _stop(machine: Machine) -> None:
    """The process ends (the operator restarts it to flip the switch): its lock goes, its files
    stay on disk for the next claimer of the area to wipe."""

    machine.factory.close()
    machine.area.close()


def _blobs(world: World) -> set[str]:
    """Every object in the storage standing in for R2, by its path."""

    base = world.root.parent / "r2"
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


async def _artifact_rows(world: World) -> int:
    async with transaction() as conn:
        return int(
            (
                await conn.execute(
                    text("SELECT count(*) FROM artifact WHERE workspace_id = :ws"),
                    {"ws": world.ws},
                )
            ).scalar_one()
        )


def test_17_the_emergency_flag_turns_snapshots_off_and_back_on(tmp_path: Path) -> None:
    """WS-35: ``CLUE_AGENT_WORKSPACE_SNAPSHOTS_ENABLED`` can be turned off and back on without
    losing a saved version and without wedging.

    With the switch off a chat's folder lives in ``<root>/local``, not in a worker area, and
    nothing restores from or saves to R2 — so a turn run while it is off starts WITHOUT the files
    the chat saved while it was on, and what it writes is never saved. Turned back on, every
    machine restores the last saved version, untouched.

    It also pins what happens to ``<root>/local`` afterwards (AW-1, D-2 say a machine keeps no
    residue): once the switch is back on NOTHING removes it — not the area claim, not the cache
    sweep, not the legacy-layout script — and if the switch is turned off again, the chat's turn
    reopens that old copy rather than the newer saved version.
    """

    from clue_api.fleet_main import _workspace_cache_job

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            root_a, root_b = world.root, tmp_path / "workspaces-b"
            v1 = {
                "scratch/notes.md": b"cycle ~42 days",
                "outputs/report.csv": b"deal,amount\nA,10\n",
                "work/plan.md": "Renewal ≈ 42 days\n".encode(),
            }
            off_files = {
                "scratch/notes.md": b"written while snapshots were off",
                "outputs/off.csv": b"deal,amount\nB,20\n",
            }

            # 1. Snapshots ON, root A: the chat saves version 1.
            on_a = _built_machine(world, root_a, snapshots=True)
            assert on_a.factory.root_path == root_a / "workers" / on_a.area.name
            assert await _turn(world, on_a, v1, worker="worker-on") == "saved"
            v1_pointer = await world.store().current(workspace_id=world.ws, thread_id=THREAD)
            assert v1_pointer is not None and v1_pointer.version == 1
            v1_manifest = await world.manifest()
            assert {entry.path for entry in v1_manifest.live()} == set(v1)
            v1_blobs, v1_rows = _blobs(world), await _artifact_rows(world)
            assert v1_blobs and v1_rows > 0
            dead_copy = on_a.agent(world.ws)
            _stop(on_a)
            # The stopped process's copy is still on disk in its (now free) area.
            assert (dead_copy / "scratch/notes.md").read_bytes() == v1["scratch/notes.md"]

            # 2. Same root, snapshots OFF: the emergency path.
            off = _built_machine(world, root_a, snapshots=False)
            assert off.area.name == LOCAL_DIR
            assert off.area.path == off.factory.root_path == root_a / LOCAL_DIR
            lease = await _open(world, off, fence=await world.fence("worker-off"))
            try:
                agent = off.agent(world.ws)
                assert agent == (
                    root_a / LOCAL_DIR / "chats" / world.ws / PROJECT / THREAD / "agent"
                )
                # Nothing restores: the turn starts without version 1's files, which sit in R2
                # and in the dead area's folder but are read from neither.
                assert lease.restore_report is None
                assert lease.snapshot_base is None
                for path in v1:
                    assert not _has(off, world.ws, path), path
                # It reads and writes locally like any turn.
                _write(lease, off_files)
                for path, data in off_files.items():
                    assert _bytes(off, world.ws, path) == data
                # Its "save" saves nothing, and says so.
                report = await lease.save_snapshot()
                assert (report.status, report.version, report.uploaded, report.bytes) == (
                    "unchanged",
                    None,
                    0,
                    0,
                )
            finally:
                await off.factory.release_saved(lease)
            # Nothing reached R2 or the database: the version record is still version 1.
            pointer = await world.store().current(workspace_id=world.ws, thread_id=THREAD)
            assert pointer == v1_pointer
            assert await world.manifest() == v1_manifest
            assert _blobs(world) == v1_blobs
            assert world.storage.deletes == []
            assert await _artifact_rows(world) == v1_rows
            # The local folder is the only copy of what the off turn wrote, and it stays.
            for path, data in off_files.items():
                assert _bytes(off, world.ws, path) == data
            _stop(off)

            # 3. Snapshots ON again, on a DIFFERENT root: a cold restore of version 1.
            on_b = _built_machine(world, root_b, snapshots=True)
            assert on_b.factory.root_path == root_b / "workers" / on_b.area.name
            lease = await _open(world, on_b, fence=await world.fence("worker-b"))
            try:
                assert lease.restore_report is not None
                assert lease.restore_report.warm is False
                assert lease.restore_report.downloaded == len(v1)
                for path, data in v1.items():
                    assert _bytes(on_b, world.ws, path) == data, path
                # The off turn's writes were never saved, so they are simply not here.
                assert not _has(on_b, world.ws, "outputs/off.csv")
                assert lease.snapshot_base is not None
                assert lease.snapshot_base.pointer == v1_pointer
                # And the chat carries on: the next save is version 2.
                _write(lease, {"scratch/notes.md": b"v2, saved on root B"})
                saved = await lease.save_snapshot()
                assert (saved.status, saved.version) == ("saved", 2)
            finally:
                await on_b.factory.release_saved(lease)

            # 4. The residue. Snapshots back ON at root A: a new process claims an area (wiping
            # the dead one), and runs the fleet's own cache sweep long past every idle window.
            local_chat = root_a / LOCAL_DIR / "chats" / world.ws / PROJECT / THREAD
            on_a2 = _built_machine(world, root_a, snapshots=True)
            assert not dead_copy.exists()
            swept = _workspace_cache_job(
                Settings(
                    _env_file=None,
                    agent_workspace_root=str(root_a),
                    agent_workspace_snapshots_enabled=True,
                ),
                on_a2.area,
            ).run_once(now=time.time() + 10 * 365 * 86400)
            assert swept.removed == ()
            # The legacy-layout script, run to remove everything it can, keeps ``local`` too.
            subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[2]
                        / "scripts"
                        / "remove_legacy_agent_workspaces.py"
                    ),
                    "--root",
                    str(root_a),
                    "--older-than-hours",
                    "0",
                    "--apply",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            # FINDING (pinned, not fixed): the off period's copy is left on the machine.
            for path, data in off_files.items():
                assert (local_chat / "agent" / path).read_bytes() == data, path
            # While snapshots are on it is never read: a turn at root A gets version 2 from R2.
            lease = await _open(world, on_a2, fence=await world.fence("worker-a2"))
            try:
                assert lease.restore_report is not None and lease.restore_report.warm is False
                assert _bytes(on_a2, world.ws, "scratch/notes.md") == b"v2, saved on root B"
                assert not _has(on_a2, world.ws, "outputs/off.csv")
            finally:
                await on_a2.factory.release_saved(lease)
            _stop(on_a2)

            # 5. Switched OFF again at root A: the chat reopens the old off-period copy — older
            # than version 2 and never saved — rather than starting empty.
            off_again = _built_machine(world, root_a, snapshots=False)
            lease = await _open(world, off_again, fence=await world.fence("worker-off-2"))
            try:
                assert lease.restore_report is None
                for path, data in off_files.items():
                    assert _bytes(off_again, world.ws, path) == data, path
                assert not _has(off_again, world.ws, "outputs/report.csv")
            finally:
                await off_again.factory.release_saved(lease)
            # And reopening it saved nothing: the record is still version 2.
            final = await world.store().current(workspace_id=world.ws, thread_id=THREAD)
            assert final is not None and final.version == 2

    run_async(scenario())


# --- A stored path with a reserved name (founder ruling 2026-10-24, review A2-I3) ----------------


async def _plant_reserved_name_chat(world: World, thread: str, files: dict[str, bytes]) -> None:
    """A chat as a save made before fix pass 1 left it, when a list could name a ``.clue-tmp-*``
    folder: a schema-2 list naming ``files`` as given, every byte — the list's own included —
    recorded, held and stored in the chat's own area under its hash, and a version record naming
    that list. Planted by hand because today's save refuses to write such a list at all."""

    written = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    document = {
        "schema_version": 2,
        "entries": [
            {
                "path": path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "media_type": "text/markdown",
                "tier": "work_product",
                "written_at": written.isoformat(),
            }
            for path, data in sorted(files.items())
        ],
    }
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    manifest_sha = hashlib.sha256(body).hexdigest()
    blobs = {hashlib.sha256(data).hexdigest(): data for data in files.values()}
    blobs[manifest_sha] = body
    async with transaction() as conn:
        for sha, data in blobs.items():
            key = agent_workspace_key(world.ws, sha)
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=world.ws,
                content_sha256=sha,
                media_type="text/markdown",
                size_bytes=len(data),
            )
            await retain_artifact(
                conn,
                workspace_id=world.ws,
                storage_key=key,
                reference_kind=SNAPSHOT_REFERENCE_KIND,
                reference_id=thread,
            )
        await conn.execute(
            text(
                "INSERT INTO agent_workspace_snapshot (workspace_id, thread_id, project_id, "
                "version, manifest_artifact_key, manifest_sha256) "
                "VALUES (:ws, :th, :prj, 1, :key, :sha)"
            ),
            {
                "ws": world.ws,
                "th": thread,
                "prj": PROJECT,
                "key": agent_workspace_key(world.ws, manifest_sha),
                "sha": manifest_sha,
            },
        )
    for sha, data in blobs.items():
        await FsStorage.put(
            world.storage, agent_workspace_key(world.ws, sha), data, media_type="text/markdown"
        )


def test_19_a_reserved_name_under_outputs_is_renamed_and_its_bytes_are_never_erased(
    tmp_path: Path,
) -> None:
    """Founder ruling 2026-10-24. A version saved before fix pass 1 lists the agent's finished
    work at ``outputs/.clue-tmp-a/r.md`` — a path no disk writes. Fix pass 1 dropped that entry on
    restore, so the next save no longer listed the file's hash, released it and erased its bytes
    from R2: work under ``outputs/``, which is never deleted. Now the entry is renamed to
    ``outputs/clue-tmp-a/r.md``: the restore writes the same stored bytes there, the next save
    lists that path by the same hash, and the bytes stay stored and held."""

    thread = f"thread-reserved-{uuid.uuid4().hex[:8]}"
    report = b"# Account plan\nThe agent's finished work.\n"
    kept = b"finished, and always at a legal path"
    planted = {"outputs/.clue-tmp-a/r.md": report, "outputs/ok.md": kept}

    async def scenario() -> None:
        async with _world(tmp_path) as world:
            await _plant_reserved_name_chat(world, thread, planted)
            a, b = world.machine(), world.machine()

            lease = await _open(world, a, fence=await world.fence("worker-a"), thread=thread)
            try:
                assert lease.restore_report is not None and lease.restore_report.warm is False
                assert _bytes(a, world.ws, "outputs/clue-tmp-a/r.md", thread) == report
                assert _bytes(a, world.ws, "outputs/ok.md", thread) == kept
                assert not _has(a, world.ws, "outputs/.clue-tmp-a", thread)
                # The turn changes something, so the save writes a new version (an unchanged
                # turn writes nothing and releases nothing).
                _write(lease, {"scratch/next.md": b"the chat goes on"})
                saved = await lease.save_snapshot()
                assert (saved.status, saved.version) == ("saved", 2)
            finally:
                await a.factory.release_saved(lease)

            entries = (await world.manifest(thread)).by_path()
            assert sorted(entries) == [
                "outputs/clue-tmp-a/r.md",
                "outputs/ok.md",
                "scratch/next.md",
            ]
            renamed = entries["outputs/clue-tmp-a/r.md"]
            assert renamed.sha256 == hashlib.sha256(report).hexdigest()
            assert renamed.tier == "work_product" and renamed.expired_at is None
            assert renamed.written_at == datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
            # The bytes were never released: still held by the chat, still stored, never erased.
            key = world.key(report)
            assert key in await _held(world, thread)
            assert await world.stored(key)
            assert key not in world.storage.deletes

            # A second machine, with nothing local, gets the file back from R2 alone.
            lease = await _open(world, b, fence=await world.fence("worker-b"), thread=thread)
            try:
                assert lease.restore_report is not None and lease.restore_report.warm is False
                assert _bytes(b, world.ws, "outputs/clue-tmp-a/r.md", thread) == report
            finally:
                await b.factory.release_saved(lease)

    run_async(scenario())
