"""F3 Phase 1, plan Task 11: the Phase 1 proofs (ruling AW-16; spec §11 tests 1–4, 8, 10, 13, 14
and WS-18).

Each scenario runs the real pieces end to end: one database (the lane's throwaway test database),
one filesystem storage standing in for R2, and two or three worker areas claimed from one
temporary root — each area with its own factory and snapshotter, which is what two machines are.
Rows are committed (the store opens its own transactions), so every scenario uses its own
workspace id and removes what it wrote.
"""

from __future__ import annotations

import asyncio
import os
import stat
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from clue_agents.resources import AgentResourceMaterializer
from clue_agents.worker_area import ChatScope, WorkerArea, claim_worker_area
from clue_agents.workspace import AgentWorkspaceFactory, AgentWorkspaceLease
from clue_agents.workspace_policy import PreparedWorkspaceRoot
from clue_agents.workspace_snapshot import LeaseFence
from clue_agents.workspace_snapshotter import WorkspaceSnapshotter
from clue_api.agent_workspace_cache import AgentWorkspaceCacheJob
from clue_api.agent_workspace_snapshots import DbWorkspaceSnapshotStore
from clue_api.sandbox.policy_sweep import snapshot as sweep_snapshot
from clue_api.sandbox.policy_sweep import sweep
from clue_api.sandbox.workspaces import sandbox_mounts_for_lease
from clue_core import ExecutionId
from clue_db import db_lifespan, transaction
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_storage import FsStorage
from tests.agents.workspace_helpers import RecordingArtifactSink, policy, resource_snapshot
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

PROJECT, THREAD = "project-1", "thread-1"


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
    storage: FsStorage
    machines: list[Machine]
    work_id: uuid.UUID

    def machine(self) -> Machine:
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
                ),
            ),
        )
        self.machines.append(machine)
        return machine

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
        storage=FsStorage(tmp_path / "r2"),
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
