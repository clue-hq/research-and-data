"""The worker-area cache sweep: a chat's folder stays on a worker only while it is useful.

F3 Phase 1 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md,
WS-16, WS-17; rulings AW-9, AW-11, AW-17, AW-19). Every chat folder in this worker's own area is a
copy of the chat's snapshot, so deleting one never loses anything. The sweep deletes a chat's
whole folder when it has not been used for the idle window (30 minutes by default), and, while the
area is over its size cap (10 GiB by default), the least recently used idle folders first. It
skips the chats this worker is running a turn for right now — which the worker knows itself, so no
other worker and no database is consulted — and it never looks inside any other area.

A snapshots-on sweep also removes the snapshots-off switch's leftover ``<root>/local`` once no
snapshots-off process holds its lock (:func:`~clue_agents.worker_area.remove_unused_local`). The
area claim tries that at start-up too, but during a rolling deploy a snapshots-off worker may still
be alive then, so the sweep is what makes the folder go within one interval of the last one ending.

The local version note is deleted before the files, so a turn that starts during the deletion
restores instead of trusting a half-deleted folder; the area's guard makes the check and the
deletion one step against this worker's own turns.
"""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from clue_agents.worker_area import ChatScope, WorkerArea, remove_unused_local, wipe_path
from clue_obs import get_logger

__all__ = ["AgentWorkspaceCacheJob", "CacheSweepResult"]

log = get_logger("clue_api.agent_workspace_cache")

_CHATS_DIR: Final = "chats"
_LAST_USED: Final = "last-used"
_NOTE: Final = "snapshot-note.json"


@dataclass(frozen=True, slots=True)
class CacheSweepResult:
    """The chat folders one sweep removed (``ws/project/thread``) and the bytes it freed."""

    removed: tuple[str, ...]
    bytes_freed: int


@dataclass(frozen=True, slots=True)
class _Chat:
    scope: ChatScope
    path: Path
    last_used: float
    size: int

    @property
    def key(self) -> str:
        return f"{self.scope.workspace_id}/{self.scope.project_id}/{self.scope.thread_id}"


class AgentWorkspaceCacheJob:
    """Delete idle chat folders from this worker's own area (WS-16)."""

    def __init__(
        self,
        *,
        area: WorkerArea,
        idle_s: float,
        max_bytes: int,
        leftover_local_root: Path | None = None,
    ) -> None:
        # ``leftover_local_root`` is the workspace root of a snapshots-ON worker, whose sweep also
        # removes ``<root>/local`` once the emergency is over. Never set it with snapshots off.
        self._area = area
        self._idle_s = idle_s
        self._max_bytes = max_bytes
        self._leftover_local_root = leftover_local_root

    @property
    def idle_s(self) -> float:
        return self._idle_s

    def run_once(self, *, now: float | None = None) -> CacheSweepResult:
        clock = time.time() if now is None else now
        if self._leftover_local_root is not None and remove_unused_local(self._leftover_local_root):
            log.info("agent_workspace.leftover_local_removed", area=self._area.name)
        chats = _list_chats(self._area.path / _CHATS_DIR)
        removed: list[_Chat] = []
        for chat in sorted(chats, key=lambda item: item.last_used):
            if clock - chat.last_used >= self._idle_s and self._remove(chat):
                removed.append(chat)
        remaining = [chat for chat in chats if chat not in removed]
        total = sum(chat.size for chat in remaining)
        for chat in sorted(remaining, key=lambda item: item.last_used):
            if total <= self._max_bytes:
                break
            if self._remove(chat):
                removed.append(chat)
                total -= chat.size
        result = CacheSweepResult(
            removed=tuple(chat.key for chat in removed),
            bytes_freed=sum(chat.size for chat in removed),
        )
        if removed:
            log.info(
                "agent_workspace.cache_swept",
                area=self._area.name,
                removed=len(result.removed),
                bytes_freed=result.bytes_freed,
            )
        return result

    def _remove(self, chat: _Chat) -> bool:
        """Delete one chat's folder unless this worker is using it; True when it was deleted."""

        def delete() -> None:
            (chat.path / _NOTE).unlink(missing_ok=True)
            wipe_path(chat.path, remove_root=True)
            _prune_empty(chat.path.parent, stop=self._area.path / _CHATS_DIR)

        return self._area.remove_if_idle(chat.scope, delete)


def _list_chats(chats_root: Path) -> list[_Chat]:
    if not chats_root.is_dir() or chats_root.is_symlink():
        return []
    found: list[_Chat] = []
    for workspace in _directories(chats_root):
        for project in _directories(workspace):
            for thread in _directories(project):
                stamp = thread / _LAST_USED
                try:
                    last_used = stamp.lstat().st_mtime
                except FileNotFoundError:
                    last_used = thread.lstat().st_mtime
                found.append(
                    _Chat(
                        scope=ChatScope(workspace.name, project.name, thread.name),
                        path=thread,
                        last_used=last_used,
                        size=_size(thread),
                    )
                )
    return found


def _directories(parent: Path) -> list[Path]:
    return sorted(child for child in parent.iterdir() if child.is_dir() and not child.is_symlink())


def _size(folder: Path) -> int:
    total = 0
    for directory, _, files in os.walk(folder):
        for name in files:
            metadata = os.lstat(os.path.join(directory, name))
            if stat.S_ISREG(metadata.st_mode):
                total += metadata.st_size
    return total


def _prune_empty(folder: Path, *, stop: Path) -> None:
    while folder != stop and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent
