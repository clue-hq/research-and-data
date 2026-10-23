"""F3 Phase 2, plan Task 5: the daily expiry job (spec WS-24, WS-26; ruling AW-24).

Scenario tests through the real
:class:`~clue_api.agent_workspace_snapshots.DbWorkspaceSnapshotStore` and the real artifact tables:
the job publishes a file list with the due entries marked expired, and the store's own
release-and-erase machinery is what frees the bytes. Every test therefore asserts on storage, not
only on the file list.

Rows are committed (the store opens its own transactions), so every test uses its own workspace id
and removes what it wrote. A chat's age is pushed into the past with SQL rather than waited for.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text

from clue_agents.workspace_snapshot import (
    UNKNOWN_RECEIPT,
    Receipt,
    SnapshotEntry,
    SnapshotManifest,
    tier_for,
)
from clue_api.agent_turn_submission import thread_work_id
from clue_api.agent_workspace_retention import (
    RETENTION_SWEEP,
    AgentWorkspaceRetentionJob,
    run_retention_if_due,
)
from clue_api.agent_workspace_snapshots import DbWorkspaceSnapshotStore
from clue_db import db_lifespan, transaction
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_storage import FsStorage, agent_workspace_key
from tests._workspace import seed_project
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

WHEN = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
RAW_S = 172800.0
WORKING_S = 604800.0
THREAD = "thr-ret-1"
#: The receipt a tool's read carries before it expires; the job must keep it exactly.
READ_RECEIPT = Receipt(
    source="run_crm_action",
    operation_id="11111111-2222-3333-4444-555555555555",
    produced_at=WHEN,
    details={"action": "list_contacts", "record_count": 42},
    read_again="These bytes are gone. Call run_crm_action again.",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(path: str, data: bytes, *, receipt: Receipt | None = None) -> SnapshotEntry:
    return SnapshotEntry(
        path=path,
        sha256=_sha(data),
        size=len(data),
        media_type="text/plain",
        tier=tier_for(path),
        written_at=WHEN,
        receipt=receipt,
    )


class CountingStorage(FsStorage):
    """The filesystem backend, recording what was deleted."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.deletes: list[str] = []

    async def delete(self, key: str) -> None:
        self.deletes.append(key)
        await super().delete(key)


@asynccontextmanager
async def _workspace() -> AsyncIterator[str]:
    ws = f"ws-f3ret-{uuid.uuid4().hex[:10]}"
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
            # The seeded submission's ``onboarding_input`` cites an artifact and is append-only,
            # so that one row stays; everything the snapshots wrote goes.
            await conn.execute(
                text(
                    "DELETE FROM artifact WHERE workspace_id = :ws AND NOT EXISTS ("
                    "SELECT 1 FROM onboarding_input o WHERE o.artifact_key = artifact.storage_key)"
                ),
                {"ws": ws},
            )
            await conn.execute(
                text("DELETE FROM maintenance_run WHERE name = :name"), {"name": RETENTION_SWEEP}
            )
        # ``agent_turn_submission`` and its project/thread/user chain are append-only by trigger,
        # so the one test that seeds a submission leaves those rows behind under its own
        # throwaway workspace id.


def _scenario(body: Callable[[str, CountingStorage], Awaitable[None]], tmp_path: Path) -> None:
    async def run() -> None:
        async with db_lifespan(), _workspace() as ws:
            await body(ws, CountingStorage(tmp_path / "store"))

    run_async(run())


async def _save(
    store: DbWorkspaceSnapshotStore,
    ws: str,
    files: list[SnapshotEntry],
    bodies: dict[str, bytes],
    *,
    expected: int | None,
    thread: str = THREAD,
    project: str = "prj-ret",
) -> int:
    pairs = [(entry, bodies[entry.path]) for entry in files]
    await store.store_files(workspace_id=ws, files=pairs)
    status, pointer = await store.save(
        workspace_id=ws,
        project_id=project,
        thread_id=thread,
        expected_version=expected,
        manifest=SnapshotManifest(entries=tuple(files)),
        fence=None,
    )
    assert status == "saved" and pointer is not None
    return pointer.version


async def _save_bodies(
    store: DbWorkspaceSnapshotStore,
    ws: str,
    bodies: dict[str, bytes],
    *,
    receipts: dict[str, Receipt] | None = None,
    thread: str = THREAD,
) -> int:
    receipts = receipts or {}
    entries = [_entry(path, data, receipt=receipts.get(path)) for path, data in bodies.items()]
    return await _save(store, ws, entries, bodies, expected=None, thread=thread)


async def _age(ws: str, *, days: float, thread: str = THREAD) -> datetime:
    """Push the chat's last activity ``days`` into the past; return the stamped time."""

    when = datetime.now(UTC) - timedelta(days=days)
    async with transaction() as conn:
        await conn.execute(
            text(
                "UPDATE agent_workspace_snapshot SET last_activity_at = :t "
                "WHERE workspace_id = :ws AND thread_id = :th"
            ),
            {"t": when, "ws": ws, "th": thread},
        )
    return when


async def _last_activity(ws: str, thread: str = THREAD) -> datetime:
    async with transaction() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT last_activity_at FROM agent_workspace_snapshot "
                    "WHERE workspace_id = :ws AND thread_id = :th"
                ),
                {"ws": ws, "th": thread},
            )
        ).scalar_one()


def _job(store: DbWorkspaceSnapshotStore) -> AgentWorkspaceRetentionJob:
    return AgentWorkspaceRetentionJob(
        store=store, conn_factory=transaction, raw_s=RAW_S, working_s=WORKING_S
    )


async def _manifest(store: DbWorkspaceSnapshotStore, ws: str, thread: str = THREAD):  # type: ignore[no-untyped-def]
    pointer = await store.current(workspace_id=ws, thread_id=thread)
    assert pointer is not None
    return pointer, await store.read_manifest(workspace_id=ws, pointer=pointer)


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


async def _queue_agent_turn(ws: str, thread: str = THREAD) -> None:
    async with transaction() as conn:
        await conn.execute(
            text(
                "INSERT INTO fleet_task (task_id, kind, work_id, dedup_key, priority, "
                "payload_json) VALUES (:task, CAST('agent_turn' AS fleet_task_kind), :work, "
                ":dedup, 0, '{}'::jsonb)"
            ),
            {
                "task": uuid4(),
                "work": thread_work_id(workspace_id=ws, thread_id=thread),
                "dedup": f"retention-test:{uuid4()}",
            },
        )


def test_raw_inputs_expire_after_their_window_and_keep_their_receipt(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        bodies = {"reads/r.json": b"raw bytes", "scratch/a": b"rough", "outputs/o": b"finished"}
        await _save_bodies(store, ws, bodies, receipts={"reads/r.json": READ_RECEIPT})
        aged = await _age(ws, days=3)

        report = await _job(store).run_once()

        assert (report.chats_checked, report.chats_expired, report.files_expired) == (1, 1, 1)
        assert (report.skipped_busy, report.stale) == (0, 0)
        pointer, manifest = await _manifest(store, ws)
        assert pointer.version == 2
        by_path = manifest.by_path()
        expired = by_path["reads/r.json"]
        assert expired.expired_at is not None
        assert expired.receipt == READ_RECEIPT
        assert {entry.path for entry in manifest.live()} == {"scratch/a", "outputs/o"}
        # The whole point of the job: the raw bytes are gone from storage, not merely unlisted.
        gone = agent_workspace_key(ws, _sha(bodies["reads/r.json"]))
        assert await _erasure(gone) == (True, True)
        assert gone in storage.deletes
        assert await storage.exists(gone) is False
        # The two surviving files still read back.
        for path in ("scratch/a", "outputs/o"):
            assert await store.read_file(workspace_id=ws, entry=by_path[path]) == bodies[path]
        # The job's own save is not chat activity: the clock stays where the chat left it, so the
        # working files still go at 7 days rather than 7 days after this pass.
        assert await _last_activity(ws) == aged

    _scenario(body, tmp_path)


def test_working_files_expire_after_seven_days_outputs_never(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        bodies = {"reads/r.json": b"raw bytes", "scratch/a": b"rough", "outputs/o": b"finished"}
        await _save_bodies(store, ws, bodies)
        await _age(ws, days=8)

        report = await _job(store).run_once()

        assert (report.chats_expired, report.files_expired) == (1, 2)
        _, manifest = await _manifest(store, ws)
        assert {entry.path for entry in manifest.expired()} == {"reads/r.json", "scratch/a"}
        assert [entry.path for entry in manifest.live()] == ["outputs/o"]
        # An entry saved before receipts existed is expired with the unknown receipt, never blank.
        assert manifest.by_path()["scratch/a"].receipt == UNKNOWN_RECEIPT
        for path in ("reads/r.json", "scratch/a"):
            assert await _erasure(agent_workspace_key(ws, _sha(bodies[path]))) == (True, True)
        kept = manifest.by_path()["outputs/o"]
        assert await store.read_file(workspace_id=ws, entry=kept) == bodies["outputs/o"]

        # A second pass finds nothing left to do, and outputs/ still never expires.
        again = await _job(store).run_once()
        assert (again.chats_expired, again.files_expired) == (0, 0)

    _scenario(body, tmp_path)


def test_a_busy_chat_is_skipped(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        bodies = {"reads/r.json": b"raw bytes", "outputs/o": b"finished"}
        await _save_bodies(store, ws, bodies)
        await _age(ws, days=8)
        work_id = thread_work_id(workspace_id=ws, thread_id=THREAD)
        try:
            await _queue_agent_turn(ws)

            queued = await _job(store).run_once()

            assert (queued.chats_checked, queued.skipped_busy, queued.chats_expired) == (1, 1, 0)
            pointer, manifest = await _manifest(store, ws)
            assert pointer.version == 1 and manifest.expired() == ()

            # A live lease on the thread's work id is the other way a chat is busy.
            async with transaction() as conn:
                await conn.execute(
                    text("DELETE FROM fleet_task WHERE work_id = :w"), {"w": work_id}
                )
                lease = await acquire_work_lease(
                    conn, work_id=WorkId(work_id), worker_id="worker-ret", ttl=timedelta(hours=1)
                )
            assert lease is not None

            leased = await _job(store).run_once()

            assert (leased.skipped_busy, leased.chats_expired) == (1, 0)
            pointer, _ = await _manifest(store, ws)
            assert pointer.version == 1
        finally:
            async with transaction() as conn:
                await conn.execute(
                    text("DELETE FROM fleet_task WHERE work_id = :w"), {"w": work_id}
                )
                await conn.execute(
                    text("DELETE FROM work_lease WHERE work_id = :w"), {"w": work_id}
                )

    _scenario(body, tmp_path)


def test_a_recent_submission_counts_as_activity(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        thread = await _seed_submission(ws, requested_at=datetime.now(UTC) - timedelta(hours=1))
        await _save_bodies(store, ws, {"reads/r.json": b"raw bytes"}, thread=thread)
        await _age(ws, days=3, thread=thread)

        report = await _job(store).run_once()

        assert (report.chats_checked, report.chats_expired) == (0, 0)
        pointer, manifest = await _manifest(store, ws, thread)
        assert pointer.version == 1 and manifest.expired() == ()

    _scenario(body, tmp_path)


def test_one_runner_at_a_time_and_only_when_due(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save_bodies(store, ws, {"reads/r.json": b"raw bytes", "outputs/o": b"kept"})
        await _age(ws, days=3)
        job = _job(store)
        every = timedelta(days=1)

        async def attempt() -> object:
            async with transaction() as conn:
                return await run_retention_if_due(conn, job=job, every=every)

        # Two processes check at once: one holds the advisory lock, the other skips.
        both = await asyncio.gather(attempt(), attempt())
        assert sorted(result is None for result in both) == [False, True]

        async with transaction() as conn:
            last = (
                await conn.execute(
                    text("SELECT last_run_at FROM maintenance_run WHERE name = :n"),
                    {"n": RETENTION_SWEEP},
                )
            ).scalar_one()
        assert last is not None

        # Not due again until ``every`` has passed.
        assert await attempt() is None

    _scenario(body, tmp_path)


def test_reading_identical_bytes_again_works_after_expiry(tmp_path: Path) -> None:
    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        raw = b"the very same bytes"
        await _save_bodies(store, ws, {"reads/r.json": raw, "outputs/o": b"kept"})
        await _age(ws, days=3)
        assert (await _job(store).run_once()).files_expired == 1
        key = agent_workspace_key(ws, _sha(raw))
        assert await _erasure(key) == (True, True)

        # WS-26: the same bytes may be fetched and saved again. The erased row is resurrected and
        # the blob is put back, so the new entry reads.
        pointer, manifest = await _manifest(store, ws)
        entries = [*manifest.entries, _entry("reads/r2.json", raw)]
        await _save(
            store,
            ws,
            entries,
            {"reads/r.json": raw, "outputs/o": b"kept", "reads/r2.json": raw},
            expected=pointer.version,
        )

        assert await _erasure(key) == (False, False)
        _, after = await _manifest(store, ws)
        fresh = after.by_path()["reads/r2.json"]
        assert fresh.expired_at is None
        assert await store.read_file(workspace_id=ws, entry=fresh) == raw

    _scenario(body, tmp_path)


def test_one_unreadable_chat_does_not_abort_the_pass(tmp_path: Path) -> None:
    """Review I1: a chat whose manifest blob is gone is counted and stepped over, not fatal.

    It happened in anger during the Task 9 live check. Without isolation the raise leaves
    ``run_retention_if_due`` without its ``maintenance_run`` row, so the next pass starts on the
    same deterministic ordering and dies on the same chat — retention off fleet-wide, for good,
    with nothing but a warning to say so.
    """

    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        broken, healthy = "thr-ret-broken", "thr-ret-healthy"
        await _save_bodies(store, ws, {"reads/r.json": b"lost raw"}, thread=broken)
        await _save_bodies(store, ws, {"reads/r.json": b"good raw"}, thread=healthy)
        # The oldest chat is swept first, so the broken one is reached before the healthy one.
        await _age(ws, days=10, thread=broken)
        await _age(ws, days=9, thread=healthy)
        pointer = await store.current(workspace_id=ws, thread_id=broken)
        assert pointer is not None
        # This lane's R2 lost blobs the rows still name; the local equivalent is one delete.
        await storage.delete(pointer.manifest_key)

        report = await _job(store).run_once()

        assert (report.chats_checked, report.failed) == (2, 1)
        # The chat behind the broken one in the ordering is still swept.
        assert (report.chats_expired, report.files_expired) == (1, 1)
        _, manifest = await _manifest(store, ws, healthy)
        assert [entry.path for entry in manifest.expired()] == ["reads/r.json"]
        # And the broken chat is left exactly as it was, for a human to look at.
        after = await store.current(workspace_id=ws, thread_id=broken)
        assert after is not None and after.version == 1

    _scenario(body, tmp_path)


def test_the_scan_walks_every_cold_chat_one_bounded_page_at_a_time(tmp_path: Path) -> None:
    """Ledger T5-a: the candidate scan is paged, so no backlog is ever read whole.

    Paging may not cost the pass its reach: every cold chat is still swept in the one run, and
    the keyset resumes where the page ended rather than starting over.
    """

    async def body(ws: str, storage: CountingStorage) -> None:
        store = DbWorkspaceSnapshotStore(storage=storage)
        threads = ("thr-ret-p1", "thr-ret-p2", "thr-ret-p3")
        for index, thread in enumerate(threads):
            await _save_bodies(store, ws, {"reads/r.json": f"raw {index}".encode()}, thread=thread)
            await _age(ws, days=8 + index, thread=thread)

        report = await AgentWorkspaceRetentionJob(
            store=store, conn_factory=transaction, raw_s=RAW_S, working_s=WORKING_S, page_size=1
        ).run_once()

        assert (report.chats_checked, report.chats_expired) == (3, 3)
        for thread in threads:
            _, manifest = await _manifest(store, ws, thread)
            assert [entry.path for entry in manifest.expired()] == ["reads/r.json"]

    _scenario(body, tmp_path)


class _TouchesAfterSaving(DbWorkspaceSnapshotStore):
    """A turn that changed no files finishing just after the job's save.

    ``touch()`` is what such a turn calls: it moves ``last_activity_at`` and leaves the version
    alone, so a version guard cannot see it.
    """

    async def save(self, **kwargs):  # type: ignore[no-untyped-def,override]
        result = await super().save(**kwargs)
        await self.touch(workspace_id=kwargs["workspace_id"], thread_id=kwargs["thread_id"])
        return result


def test_a_turn_touching_the_chat_is_not_stamped_back_to_cold(tmp_path: Path) -> None:
    """Review I3: the job's save is not activity, and it must not erase somebody else's.

    A research run or a delegation has no submissions, so the snapshot row's own stamp is the
    only activity signal it has — and ``_BUSY`` cannot see either of them. Reverting the stamp
    there costs the thread a whole window.
    """

    async def body(ws: str, storage: CountingStorage) -> None:
        store = _TouchesAfterSaving(storage=storage)
        await _save_bodies(store, ws, {"reads/r.json": b"raw bytes", "outputs/o": b"finished"})
        aged = await _age(ws, days=3)

        report = await _job(store).run_once()

        assert report.files_expired == 1
        # The touch happened; the chat is warm, and the job's bookkeeping may not say otherwise.
        assert await _last_activity(ws) > aged

    _scenario(body, tmp_path)


class _TurnLandsFirst(DbWorkspaceSnapshotStore):
    """The store, with one turn completing the first time the job looks the chat up.

    The candidate scan has already read this chat as cold. By the time ``_expire`` reads it the
    turn has committed — a finished turn, so no queued task and no live lease: ``_busy`` cannot
    see it. Everything the job then decides must be decided on what the turn left behind.
    """

    def __init__(self, *, storage: CountingStorage, turn: Callable[[], Awaitable[None]]) -> None:
        super().__init__(storage=storage)
        self._turn = turn
        self.fired = False

    async def current(self, *, workspace_id: str, thread_id: str):  # type: ignore[no-untyped-def]
        if not self.fired:
            self.fired = True
            await self._turn()
        return await super().current(workspace_id=workspace_id, thread_id=thread_id)


def test_a_turn_that_lands_after_the_scan_keeps_its_brand_new_files(tmp_path: Path) -> None:
    """The one race that destroys a person's data: due-ness judged on a stale scan (review I2)."""

    async def body(ws: str, storage: CountingStorage) -> None:
        cold = {"reads/old.json": b"old raw", "outputs/o": b"finished"}
        fresh = b"the turn's brand-new notes"
        store = DbWorkspaceSnapshotStore(storage=storage)
        await _save_bodies(store, ws, cold)
        await _age(ws, days=8)

        async def turn() -> None:
            """A whole turn: new rough work saved, the chat's activity stamped now."""

            bodies = {**cold, "scratch/new.md": fresh, "reads/new.json": fresh}
            await _save(
                store,
                ws,
                [_entry(path, data) for path, data in bodies.items()],
                bodies,
                expected=1,
            )

        racing = _TurnLandsFirst(storage=storage, turn=turn)

        report = await _job(racing).run_once()

        assert racing.fired
        # The chat is active as of a second ago. Nothing of it may be expired on this pass.
        assert (report.chats_expired, report.files_expired) == (0, 0)
        pointer, manifest = await _manifest(store, ws)
        assert pointer.version == 2
        assert manifest.expired() == ()
        # And the bytes the turn just wrote are still there to be read.
        key = agent_workspace_key(ws, _sha(fresh))
        assert await storage.exists(key) is True
        assert key not in storage.deletes
        for path in ("scratch/new.md", "reads/new.json"):
            assert await store.read_file(workspace_id=ws, entry=manifest.by_path()[path]) == fresh

    _scenario(body, tmp_path)


async def _seed_submission(ws: str, *, requested_at: datetime) -> str:
    """The workspace/project/thread/user chain one ``agent_turn_submission`` needs, and its thread.

    Direct SQL rather than ``clue_api.agent_turn_submission.insert_submission``: this test only
    needs a submission row with a chosen ``requested_at`` for the activity read to find.
    """

    async with transaction() as conn:
        project = await seed_project(conn, ws, name="Workspace retention")
        sha = "d" * 64
        key = f"{ws}/{sha}"
        await conn.execute(
            text(
                "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 3)"
            ),
            {"key": key, "ws": ws, "sha": sha},
        )
        onboarding_input_id = uuid5(NAMESPACE_URL, f"agent-workspace-retention-onb:{ws}")
        await conn.execute(
            text(
                "INSERT INTO onboarding_input (id, workspace_id, brand_id, kind, artifact_key, "
                "content_sha256, actor) VALUES (:id, :ws, :brand, 'user_turn', :key, :sha, 'human')"
            ),
            {
                "id": onboarding_input_id,
                "ws": ws,
                "brand": project.brand_id,
                "key": key,
                "sha": sha,
            },
        )
        thread_id = f"thr_ret_{uuid4().hex[:10]}"
        await conn.execute(
            text(
                "INSERT INTO agent_thread (id, workspace_id, project_id) "
                "VALUES (:id, :ws, :project)"
            ),
            {"id": thread_id, "ws": ws, "project": project.project_id},
        )
        user_id = f"user_ret_{uuid4().hex[:8]}"
        membership_id = f"member_ret_{uuid4().hex[:8]}"
        await conn.execute(
            text("INSERT INTO platform_user (user_id) VALUES (:user)"), {"user": user_id}
        )
        await conn.execute(
            text(
                "INSERT INTO workspace_membership (membership_id, workspace_id, user_id, "
                "role_key, status, activated_at) "
                "VALUES (:membership, :ws, :user, 'owner', 'active', now())"
            ),
            {"membership": membership_id, "ws": ws, "user": user_id},
        )
        await conn.execute(
            text(
                "INSERT INTO agent_turn_submission (turn_id, workspace_id, project_id, thread_id, "
                "submitted_by_user_id, submitted_via_membership_id, onboarding_input_id, "
                "message_artifact_key, message_sha256, requested_at) "
                "VALUES (:turn, :ws, :project, :thread, :user, :membership, :onb, :key, :sha, :at)"
            ),
            {
                "turn": uuid4(),
                "ws": ws,
                "project": project.project_id,
                "thread": thread_id,
                "user": user_id,
                "membership": membership_id,
                "onb": onboarding_input_id,
                "key": key,
                "sha": sha,
                "at": requested_at,
            },
        )
    return thread_id
