"""Each worker process's own area of the workspace disk, claimed by lock (AW-9, AW-19).

F3 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md, WS-15,
WS-16). Workers have no stable names, so an area is claimed rather than named: a starting process
takes the first ``<root>/workers/area-<n>`` whose ``area-<n>.lock`` it can lock exclusively, holds
that lock for as long as it runs, and wipes the area before using it. The kernel releases the lock
when the process dies, so a free lock proves no live process owns that area; a starting worker
therefore also removes every other area whose lock it can take. Nothing in an area belongs to
anyone else, so no cleanup ever has to work out who is using a folder.

Locks are only reliable on a local filesystem; the workspace root must not sit on a network drive.
Every factory in one process shares one area (:func:`process_worker_area`), and the area counts
which chats this process is using right now so the idle cleanup skips them.

The snapshots-off emergency switch is the one exception: with nothing saved to R2, every worker on
a machine shares ONE folder, ``<root>/local``, so a chat finds its files whichever worker runs its
next turn. Its lock file is ``<root>/workers/local.lock``, beside the area locks — not beside
``local`` itself, because the root's audit (:class:`~clue_agents.WorkspaceRootPolicy`) refuses any
file at the top level of the root. It is locked the other way round from an area's: each
snapshots-off process holds a SHARED lock on it for as long as it runs
(:func:`process_local_area`), and a snapshots-on worker removes ``local`` only when it can take
the lock EXCLUSIVELY — proof that no snapshots-off process is alive, so the emergency is over
(:func:`remove_unused_local`). It tries when it claims its area and again on every cache sweep.
Nothing on the snapshots-off side ever removes ``local``: there its files exist only on that disk.
The lock file itself is never deleted, so every process always locks the same file.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "LOCAL_DIR",
    "ChatScope",
    "WorkerArea",
    "claim_worker_area",
    "process_local_area",
    "process_area_name",
    "process_worker_area",
    "remove_unused_local",
    "wipe_path",
]

WORKERS_DIR: Final = "workers"
#: The snapshots-off switch's shared folder below the root (WS-21); its lock is in ``workers/``.
LOCAL_DIR: Final = "local"
_LOCAL_LOCK: Final = f"{LOCAL_DIR}.lock"
_AREA_PREFIX: Final = "area-"
_CLAIM_LOCK: Final = ".claim.lock"
_DIRECTORY_MODE: Final = 0o700
_LOCK_FLAGS: Final = (
    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)


@dataclass(frozen=True, slots=True)
class ChatScope:
    """One chat's identity on disk: the three segments its folder is named by."""

    workspace_id: str
    project_id: str
    thread_id: str


class WorkerArea:
    """A claimed area: its path, the lock that proves it is ours, and the chats in use in it."""

    def __init__(self, *, name: str, path: Path, lock_fd: int | None) -> None:
        # ``lock_fd`` is the area's lock: exclusive for a claimed ``area-<n>``, SHARED for the
        # ``local`` folder of the snapshots-off switch, which every snapshots-off process holds at
        # once. Either way :meth:`close` (or the process ending) gives it up.
        self.name = name
        self.path = path
        self._lock_fd: int | None = lock_fd
        self._guard = threading.Lock()
        self._uses: Counter[ChatScope] = Counter()

    def mark_in_use(self, chat: ChatScope) -> None:
        with self._guard:
            self._uses[chat] += 1

    def mark_idle(self, chat: ChatScope) -> None:
        with self._guard:
            if self._uses[chat] <= 1:
                self._uses.pop(chat, None)
            else:
                self._uses[chat] -= 1

    def in_use(self) -> frozenset[ChatScope]:
        with self._guard:
            return frozenset(self._uses)

    def remove_if_idle(self, chat: ChatScope, remove: Callable[[], None]) -> bool:
        """Run ``remove`` for ``chat`` unless this process is using it; True when it ran.

        The check and the removal are one step under the area's guard, and a factory marks a chat
        in use under the same guard before it opens the chat's folder, so the cache sweep can
        never delete a folder a turn of this worker is opening or using.
        """

        with self._guard:
            if self._uses.get(chat, 0) > 0:
                return False
            remove()
            return True

    def close(self) -> None:
        """Give the area up (the process is ending). Its files stay for the next claimer to wipe."""

        with self._guard:
            descriptor, self._lock_fd = self._lock_fd, None
        if descriptor is not None:
            os.close(descriptor)
        with _PROCESS_LOCK:
            for key, area in tuple(_PROCESS_AREAS.items()):
                if area is self:
                    del _PROCESS_AREAS[key]


def claim_worker_area(root: Path, *, max_areas: int = 64) -> WorkerArea:
    """Claim, wipe and return the first free area under ``root``; remove every other dead area.

    Raises :class:`RuntimeError` when ``max_areas`` areas are all held by live processes.
    """

    workers = root / WORKERS_DIR
    _ensure_private_directory(workers)
    # Claims run one at a time on this host: without it, one worker's cleanup could take a new
    # area's lock between its creator opening the lock file and locking it.
    claim_fd = os.open(workers / _CLAIM_LOCK, _LOCK_FLAGS, 0o600)
    try:
        fcntl.flock(claim_fd, fcntl.LOCK_EX)
        # A snapshots-on worker is starting: if the emergency folder is left from a snapshots-off
        # period and no snapshots-off process is alive any more, it goes now. If one still is
        # (a rolling deploy), the cache sweep tries again until it is gone.
        remove_unused_local(root)
        return _claim_locked(workers, max_areas=max_areas)
    finally:
        os.close(claim_fd)


def _claim_locked(workers: Path, *, max_areas: int) -> WorkerArea:
    claimed: WorkerArea | None = None
    for index in range(max_areas):
        name = f"{_AREA_PREFIX}{index}"
        descriptor = _try_lock(workers / f"{name}.lock")
        if descriptor is None:
            continue
        path = workers / name
        wipe_path(path)
        _ensure_private_directory(path)
        claimed = WorkerArea(name=name, path=path, lock_fd=descriptor)
        break
    if claimed is None:
        raise RuntimeError(f"all {max_areas} worker areas under {workers} are held by live workers")
    _remove_dead_areas(workers, keep=claimed.name)
    return claimed


def process_worker_area(root: Path) -> WorkerArea:
    """This process's one area under ``root``, claimed on first use and shared by every factory."""

    key = root.resolve()
    with _PROCESS_LOCK:
        area = _PROCESS_AREAS.get(key)
        if area is None:
            area = claim_worker_area(root)
            _PROCESS_AREAS[key] = area
        return area


_PROCESS_LOCK = threading.Lock()
_PROCESS_AREAS: dict[Path, WorkerArea] = {}


def process_area_name() -> str | None:
    """The name of the area this process has claimed, or ``None`` outside a fleet worker.

    A sandbox container carries it as a label, so the next process of this area can kill one a
    dead run left behind (AW-19) — whichever agent started it.
    """

    with _PROCESS_LOCK:
        names = {area.name for area in _PROCESS_AREAS.values()}
    return next(iter(names)) if len(names) == 1 else None


def process_local_area(root: Path) -> WorkerArea:
    """This process's hold on the shared ``<root>/local`` of the snapshots-off switch.

    Opened once per process and shared by every factory, like :func:`process_worker_area`, so the
    in-use tracking is one per process and a factory built per job opens no new lock. Opening it
    takes a SHARED lock on ``<root>/workers/local.lock`` and keeps it until
    :meth:`WorkerArea.close` or the process ends. The lock is taken blocking: a snapshots-on
    worker removing a leftover ``local`` holds it exclusively, and this process waits and then
    starts with the clean folder.
    Nothing here ever deletes from ``local`` — in an emergency its files exist only on this disk,
    so a worker restarting mid-emergency must find them as they were.
    """

    local = root / LOCAL_DIR
    key = local.resolve()
    with _PROCESS_LOCK:
        area = _PROCESS_AREAS.get(key)
        if area is None:
            workers = root / WORKERS_DIR
            _ensure_private_directory(workers)
            descriptor = os.open(workers / _LOCAL_LOCK, _LOCK_FLAGS, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
                _ensure_private_directory(local)
            except BaseException:
                os.close(descriptor)
                raise
            area = WorkerArea(name=LOCAL_DIR, path=local, lock_fd=descriptor)
            _PROCESS_AREAS[key] = area
        return area


def remove_unused_local(root: Path) -> bool:
    """Remove ``<root>/local`` if no snapshots-off process holds it; True when it was removed.

    Only a snapshots-on worker calls this. It tries the lock exclusively without waiting: success
    proves no snapshots-off process is alive (each holds a shared lock for its whole life), so the
    folder is a leftover and goes, under the lock; a snapshots-off process starting meanwhile waits
    for it and then finds no folder. If any snapshots-off process is alive the folder is left
    alone. The lock file is never deleted: a process waiting on a deleted file's lock would lock a
    file nobody else can see.
    """

    local = root / LOCAL_DIR
    if not local.exists() and not local.is_symlink():
        return False
    # ``workers/`` exists: either a snapshots-off process made it with the lock file, or this
    # caller is a snapshots-on worker that has claimed (or is claiming) an area in it.
    workers = root / WORKERS_DIR
    _ensure_private_directory(workers)
    descriptor = _try_lock(workers / _LOCAL_LOCK)
    if descriptor is None:
        return False
    try:
        wipe_path(local, remove_root=True)
    finally:
        os.close(descriptor)
    return True


def _try_lock(path: Path) -> int | None:
    descriptor = os.open(path, _LOCK_FLAGS, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _remove_dead_areas(workers: Path, *, keep: str) -> None:
    """Delete every other area (and its lock file) whose lock no live process holds."""

    for entry in sorted(workers.iterdir()):
        name = entry.name.removesuffix(".lock")
        if not name.startswith(_AREA_PREFIX) or name == keep:
            continue
        lock_path = workers / f"{name}.lock"
        descriptor = _try_lock(lock_path)
        if descriptor is None:
            continue
        try:
            wipe_path(workers / name, remove_root=True)
            lock_path.unlink(missing_ok=True)
        finally:
            os.close(descriptor)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{path} is not a directory")
    if stat.S_IMODE(metadata.st_mode) != _DIRECTORY_MODE:
        path.chmod(_DIRECTORY_MODE)


def wipe_path(path: Path, *, remove_root: bool = False) -> None:
    """Remove everything below ``path`` (frozen read-only trees included), never following links."""

    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return

    def make_writable(function: object, target: str, excinfo: object) -> None:
        del function, excinfo
        parent = os.path.dirname(target)
        os.chmod(parent, _DIRECTORY_MODE)
        if os.path.isdir(target) and not os.path.islink(target):
            os.chmod(target, _DIRECTORY_MODE)
            shutil.rmtree(target, onexc=make_writable)
        else:
            os.unlink(target)

    for directory, _, _ in os.walk(path):
        os.chmod(directory, _DIRECTORY_MODE)
    if remove_root:
        shutil.rmtree(path, onexc=make_writable)
        return
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, onexc=make_writable)
        else:
            child.unlink()
