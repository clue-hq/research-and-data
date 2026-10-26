"""F3 Phase 1, plan Task 6: worker areas are claimed by lock and wiped (spec WS-15, WS-16; AW-9,
AW-19)."""

from __future__ import annotations

import fcntl
import multiprocessing
import multiprocessing.synchronize
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from clue_agents import worker_area
from clue_agents.worker_area import (
    ChatScope,
    claim_worker_area,
    process_local_area,
    process_worker_area,
    remove_unused_local,
)
from tests.agents.workspace_helpers import hold_local_area


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    return root


def _hold_area(
    root: str,
    index: int,
    ready: multiprocessing.synchronize.Event,
    stop: multiprocessing.synchronize.Event,
) -> None:
    """A stand-in live worker: holds ``area-<index>``'s lock until told to stop."""

    workers = Path(root) / "workers"
    workers.mkdir(mode=0o700, exist_ok=True)
    (workers / f"area-{index}").mkdir(mode=0o700, exist_ok=True)
    (workers / f"area-{index}" / "busy.txt").write_text("in use")
    descriptor = os.open(workers / f"area-{index}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    ready.set()
    stop.wait(30)
    os.close(descriptor)


def _claim_name(
    root: str,
    names: multiprocessing.Queue,  # type: ignore[type-arg]
    stop: multiprocessing.synchronize.Event,
) -> None:
    area = claim_worker_area(Path(root))
    names.put(area.name)
    stop.wait(30)  # hold the lock until the parent has both names


@pytest.fixture
def held_area(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = _root(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready, stop = context.Event(), context.Event()
    holder = context.Process(target=_hold_area, args=(str(root), 0, ready, stop))
    holder.start()
    assert ready.wait(30)
    yield root
    stop.set()
    holder.join(30)


def test_claim_takes_first_free_area_and_wipes_it(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "workers" / "area-0").mkdir(parents=True, mode=0o700)
    (root / "workers" / "area-0" / "leftover.txt").write_text("from a dead worker")
    area = claim_worker_area(root)
    try:
        assert area.name == "area-0"
        assert area.path == root / "workers" / "area-0"
        assert list(area.path.iterdir()) == []
        assert oct(area.path.stat().st_mode & 0o777) == "0o700"
    finally:
        area.close()


def test_claim_skips_a_live_area_and_never_touches_it(held_area: Path) -> None:
    area = claim_worker_area(held_area)
    try:
        assert area.name == "area-1"
        assert (held_area / "workers" / "area-0" / "busy.txt").read_text() == "in use"
    finally:
        area.close()


def test_dead_area_is_wiped_at_claim(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = claim_worker_area(root)
    (first.path / "chats").mkdir(mode=0o700)
    second = claim_worker_area(root)
    second_path = second.path
    (second_path / "stale.txt").write_text("left by a worker that died")
    second.close()  # the second worker dies: its lock is free, its files remain
    third_root_claim = claim_worker_area(root)
    try:
        # area-0 is still held by `first`, so the new worker takes area-1 and wipes it; no other
        # unlocked area is left behind.
        assert third_root_claim.name == "area-1"
        assert not (second_path / "stale.txt").exists()
        assert (first.path / "chats").exists()
    finally:
        third_root_claim.close()
        first.close()


def test_other_unlocked_areas_are_removed_at_claim(tmp_path: Path) -> None:
    root = _root(tmp_path)
    for index in (0, 3):
        (root / "workers" / f"area-{index}").mkdir(parents=True, mode=0o700)
        (root / "workers" / f"area-{index}" / "x").write_text("dead")
    area = claim_worker_area(root)
    try:
        assert area.name == "area-0"
        assert not (root / "workers" / "area-3").exists()
    finally:
        area.close()


def test_two_processes_claim_different_areas(tmp_path: Path) -> None:
    root = _root(tmp_path)
    context = multiprocessing.get_context("spawn")
    queue: multiprocessing.Queue = context.Queue()  # type: ignore[type-arg]
    stop = context.Event()
    workers = [context.Process(target=_claim_name, args=(str(root), queue, stop)) for _ in range(2)]
    for worker in workers:
        worker.start()
    names = {queue.get(timeout=30), queue.get(timeout=30)}
    stop.set()
    for worker in workers:
        worker.join(30)
    assert names == {"area-0", "area-1"}


def test_all_areas_taken_raises(held_area: Path) -> None:
    with pytest.raises(RuntimeError):
        claim_worker_area(held_area, max_areas=1)


def test_in_use_counts_nested_uses(tmp_path: Path) -> None:
    area = claim_worker_area(_root(tmp_path))
    chat = ChatScope(workspace_id="ws-1", project_id="p-1", thread_id="t-1")
    try:
        area.mark_in_use(chat)
        area.mark_in_use(chat)
        area.mark_idle(chat)
        assert area.in_use() == frozenset({chat})
        area.mark_idle(chat)
        assert area.in_use() == frozenset()
    finally:
        area.close()


def test_process_worker_area_is_memoised(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = process_worker_area(root)
    try:
        assert process_worker_area(root) is first
    finally:
        first.close()


# --- the snapshots-off switch's shared ``local`` folder and its shared lock (Task 5 finding) ------
#
# Each "snapshots-off worker" below is a real child process holding a real shared flock on
# ``<root>/workers/local.lock`` through ``process_local_area``; the snapshots-on side runs the
# production ``remove_unused_local`` / ``claim_worker_area`` in this process, through its own open
# file description, so the kernel sees separate holders.

_EMERGENCY_FILE = Path("chats/ws-1/p-1/t-1/agent/scratch/emergency.md")


@contextmanager
def _off_worker(root: Path) -> Iterator[multiprocessing.process.BaseProcess]:
    """A live snapshots-off worker process for the duration of the block; it then exits."""

    context = multiprocessing.get_context("spawn")
    ready, stop = context.Event(), context.Event()
    holder = context.Process(target=hold_local_area, args=(str(root), ready, stop))
    holder.start()
    try:
        assert ready.wait(30), "the snapshots-off worker never got its shared lock"
        yield holder
    finally:
        stop.set()
        holder.join(30)
        assert not holder.is_alive()


def test_a_live_snapshots_off_worker_keeps_local_in_place(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with _off_worker(root):
        assert remove_unused_local(root) is False
        # A snapshots-on worker starting meanwhile (a rolling deploy) leaves it too.
        area = claim_worker_area(root)
        area.close()
        assert (root / "local" / _EMERGENCY_FILE).read_text() == "only copy"


def test_with_every_snapshots_off_worker_gone_a_starting_worker_removes_local(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    with _off_worker(root):
        pass
    assert (root / "local" / _EMERGENCY_FILE).exists()
    area = claim_worker_area(root)
    try:
        assert not (root / "local").exists()
        # The lock file stays, so every later process locks the very same file.
        assert (root / "workers" / "local.lock").is_file()
    finally:
        area.close()
    assert remove_unused_local(root) is False  # nothing left to remove


def test_snapshots_off_workers_share_local_at_once(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with _off_worker(root), _off_worker(root):
        # Both hold it together (an exclusive lock would never let the second one start).
        assert remove_unused_local(root) is False
    assert remove_unused_local(root) is True


def test_a_snapshots_off_worker_never_removes_local_itself(tmp_path: Path) -> None:
    """Mid-emergency the files exist only on this disk: a worker that restarts — even as the only
    one alive — must find them as the previous process left them."""

    root = _root(tmp_path)
    with _off_worker(root):
        pass
    area = process_local_area(root)
    try:
        assert (area.path / _EMERGENCY_FILE).read_text() == "only copy"
        with _off_worker(root):
            assert (area.path / _EMERGENCY_FILE).read_text() == "only copy"
    finally:
        area.close()


def test_a_snapshots_off_worker_waits_for_a_removal_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshots-on side holds ``workers/local.lock`` exclusively while it removes ``local``; a
    snapshots-off process starting then must wait and begin with the clean folder."""

    root = _root(tmp_path)
    with _off_worker(root):
        pass
    wiping, finish = threading.Event(), threading.Event()
    real_wipe = worker_area.wipe_path

    def paused_wipe(path: Path, *, remove_root: bool = False) -> None:
        wiping.set()
        assert finish.wait(30)
        real_wipe(path, remove_root=remove_root)

    monkeypatch.setattr(worker_area, "wipe_path", paused_wipe)
    removed: list[bool] = []
    remover = threading.Thread(target=lambda: removed.append(remove_unused_local(root)))
    remover.start()
    opened: list[object] = []
    opener = threading.Thread(target=lambda: opened.append(process_local_area(root)))
    try:
        assert wiping.wait(30)
        opener.start()
        opener.join(0.5)
        assert opener.is_alive(), "the snapshots-off worker did not wait for the removal"
        assert opened == []
    finally:
        finish.set()
        remover.join(30)
        if opener.ident is not None:
            opener.join(30)
    assert removed == [True]
    (area,) = opened
    try:
        assert isinstance(area, worker_area.WorkerArea)
        assert area.path == root / "local" and area.path.is_dir()
        assert list(area.path.iterdir()) == []
    finally:
        area.close()
