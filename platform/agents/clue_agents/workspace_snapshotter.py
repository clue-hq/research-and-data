"""Restore a chat's agent folders at turn start and save them at turn end.

F3 Phase 1 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md,
WS-6–WS-11, WS-20, WS-22; rulings AW-1, AW-13, AW-14, AW-18). The agent's own folders
(``scratch/ reads/ work/ outputs/``) are a cache of the chat's snapshot. A small local version
note beside the agent folder (``<chat>/snapshot-note.json``, outside what the agent can see) says
which version this machine's copy holds and carries that version's file list, so a turn on the
machine that holds the current copy makes one database read and no storage call.

Restore brings a stale copy up to date without wiping it: files whose hash already matches stay,
missing or different ones are downloaded, files the version no longer lists are deleted. It also
stamps the chat's activity, because starting a turn is activity: that is what keeps Phase 2's
expiry off a chat whose turn is still running, for every caller (WS-34a). Save
stores only new bytes, then moves the version record with a compare-and-set under the turn's fleet
lease. A save that loses the race removes the note, so the next turn restores the winner — unless
it lost to Phase 2's expiry job alone (AW-24), which it re-aims at the version that job published
and retries once, so a turn never loses its own work to an expiry. A save
that cannot reach storage after its retries marks the copy *unsaved* and raises: the copy is kept
and the chat's next turn on this machine saves it (AW-18).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import mimetypes
import os
import secrets
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from clue_agents.tree_sync import read_directory, sync_directory
from clue_agents.worker_area import ChatScope, wipe_path
from clue_agents.workspace_policy import WorkspaceSecurityError
from clue_agents.workspace_snapshot import (
    SAVED_FOLDERS,
    UNKNOWN_RECEIPT,
    Receipt,
    SaveStatus,
    SnapshotCorrupt,
    SnapshotEntry,
    SnapshotManifest,
    SnapshotPointer,
    WorkspaceSaveUnavailable,
    decode_manifest,
    encode_manifest,
    tier_for,
    validate_snapshot_path,
)
from clue_obs import get_logger

if TYPE_CHECKING:
    from clue_agents.ports import ReceiptSource, WorkspaceSnapshotStore
    from clue_agents.workspace import AgentWorkspaceLease

__all__ = ["RestoreReport", "SaveReport", "WorkspaceSnapshotter"]

log = get_logger("clue_agents.workspace_snapshotter")

NOTE_FILE: Final = "snapshot-note.json"
_AGENT_DIR: Final = "agent"
_FILE_MODE: Final = 0o600
_DIR_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_DEFAULT_RETRY_DELAYS: Final = (0.5, 1.0, 2.0)


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """What one restore did (WS-20)."""

    warm: bool
    downloaded: int
    deleted: int
    bytes: int
    duration_ms: int
    imported_legacy: bool


@dataclass(frozen=True, slots=True)
class SaveReport:
    """What one save did (WS-20)."""

    status: SaveStatus
    uploaded: int
    bytes: int
    version: int | None
    duration_ms: int


@dataclass(frozen=True, slots=True)
class _Note:
    version: int
    manifest_sha256: str
    unsaved: bool
    manifest: SnapshotManifest


@dataclass(slots=True)
class SnapshotBase:
    """What a turn restored: the version a save must move from, and that version's file list."""

    pointer: SnapshotPointer | None
    manifest: SnapshotManifest | None
    legacy_folder: Path | None = None


class WorkspaceSnapshotter:
    """Restore and save one chat's agent folders against a :class:`WorkspaceSnapshotStore`."""

    def __init__(
        self,
        *,
        store: WorkspaceSnapshotStore,
        concurrency: int,
        legacy_root: Path | None = None,
        retry_delays: Sequence[float] = _DEFAULT_RETRY_DELAYS,
        sleep: Callable[[float], Any] = asyncio.sleep,
        receipts: ReceiptSource | None = None,
    ) -> None:
        self._store = store
        self._concurrency = max(1, concurrency)
        self._legacy_root = legacy_root
        self._retry_delays = tuple(retry_delays)
        self._sleep = sleep
        self._receipts = receipts

    # --- restore ------------------------------------------------------------------------------

    async def restore(self, lease: AgentWorkspaceLease) -> RestoreReport:
        """Bring this machine's copy of the chat's agent folders to the chat's current version."""

        started = time.monotonic()
        chat = lease.chat
        pointer = await self._store.current(
            workspace_id=chat.workspace_id, thread_id=chat.thread_id
        )
        note = await asyncio.to_thread(_read_note, lease)
        try:
            if pointer is None:
                report = await self._restore_without_record(lease, note=note, started=started)
            elif note is not None and (note.version, note.manifest_sha256) == (
                pointer.version,
                pointer.manifest_sha256,
            ):
                lease.snapshot_base = SnapshotBase(pointer=pointer, manifest=note.manifest)
                report = RestoreReport(
                    warm=True,
                    downloaded=0,
                    deleted=0,
                    bytes=0,
                    duration_ms=_elapsed(started),
                    imported_legacy=False,
                )
            else:
                report = await self._restore_version(lease, pointer=pointer, started=started)
        except BaseException:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(_remove_note, lease)
            raise
        if pointer is not None:
            await self._mark_active(chat)
        log.info(
            "agent_workspace.restore",
            workspace_id=chat.workspace_id,
            thread_id=chat.thread_id,
            version=None if pointer is None else pointer.version,
            warm=report.warm,
            downloaded=report.downloaded,
            deleted=report.deleted,
            bytes=report.bytes,
            duration_ms=report.duration_ms,
            imported_legacy=report.imported_legacy,
        )
        return report

    async def _mark_active(self, chat: ChatScope) -> None:
        """Stamp the chat's snapshot row: a turn has started, so it is not cold (WS-34a).

        The expiry job (Phase 2) skips a chat it can see is busy, but it recognises only *chat*
        turns — an ``agent_turn`` task or a lease on the thread's work id. A research run, a
        delegated specialist and onboarding synthesis take their lease on their execution id,
        which that query cannot match and cannot derive from a thread id, and they file no
        submissions either, so the snapshot row's own ``last_activity_at`` is the only signal
        they have. Restoring is the one hook every one of them goes through, so starting a turn
        is what marks the chat active — and a run is then never a candidate while it runs.

        There is nothing to stamp when the chat has no version record yet, so the caller only
        asks on a restore that had a pointer. A stamp is bookkeeping and the restore is the
        turn's doorway: a ``touch`` that fails is logged and the turn goes on, exactly as the
        factory's last-used stamp does.
        """

        try:
            await self._store.touch(workspace_id=chat.workspace_id, thread_id=chat.thread_id)
        except Exception as exc:  # noqa: BLE001 — best effort by design
            log.warning(
                "agent_workspace.restore_touch_failed",
                workspace_id=chat.workspace_id,
                thread_id=chat.thread_id,
                error=type(exc).__name__,
            )

    async def _restore_without_record(
        self, lease: AgentWorkspaceLease, *, note: _Note | None, started: float
    ) -> RestoreReport:
        """No version record: a new chat, an old chat from before F3, or an erased one."""

        if note is not None:
            # The record this copy was a copy of is gone (a privacy erasure, a deleted chat):
            # nothing in it may be used again (WS-27, WS-16).
            deleted = await asyncio.to_thread(_replace_agent_folders, lease, {})
            await asyncio.to_thread(_remove_note, lease)
            lease.snapshot_base = SnapshotBase(pointer=None, manifest=None)
            return RestoreReport(
                warm=False,
                downloaded=0,
                deleted=deleted,
                bytes=0,
                duration_ms=_elapsed(started),
                imported_legacy=False,
            )
        legacy = self._legacy_folder(lease.chat)
        if legacy is not None:
            files = await asyncio.to_thread(_read_legacy_folder, legacy)
            current = await asyncio.to_thread(_read_agent_folders, lease)
            await asyncio.to_thread(_replace_agent_folders, lease, {**files, **current})
            lease.snapshot_base = SnapshotBase(pointer=None, manifest=None, legacy_folder=legacy)
            return RestoreReport(
                warm=False,
                downloaded=0,
                deleted=0,
                bytes=sum(len(data) for data in files.values()),
                duration_ms=_elapsed(started),
                imported_legacy=True,
            )
        lease.snapshot_base = SnapshotBase(pointer=None, manifest=None)
        return RestoreReport(
            warm=True,
            downloaded=0,
            deleted=0,
            bytes=0,
            duration_ms=_elapsed(started),
            imported_legacy=False,
        )

    async def _restore_version(
        self, lease: AgentWorkspaceLease, *, pointer: SnapshotPointer, started: float
    ) -> RestoreReport:
        await asyncio.to_thread(_remove_note, lease)
        chat = lease.chat
        manifest = await self._store.read_manifest(workspace_id=chat.workspace_id, pointer=pointer)
        for entry in manifest.entries:
            validate_snapshot_path(entry.path)
        local = await asyncio.to_thread(_read_agent_folders, lease)
        # Only the live entries have bytes. An expired one is kept in the file list for its
        # receipt (AW-22), so it must never be downloaded, and a local copy left over from
        # before the expiry is deleted along with the files the version no longer lists.
        wanted = {entry.path: entry for entry in manifest.live()}
        missing = [
            entry
            for path, entry in wanted.items()
            if path not in local or hashlib.sha256(local[path]).hexdigest() != entry.sha256
        ]
        gate = asyncio.Semaphore(self._concurrency)

        async def fetch(entry: SnapshotEntry) -> tuple[str, bytes]:
            async with gate:
                data = await self._store.read_file(workspace_id=chat.workspace_id, entry=entry)
            if hashlib.sha256(data).hexdigest() != entry.sha256 or len(data) != entry.size:
                raise SnapshotCorrupt(f"{entry.path} does not match its file list entry")
            return entry.path, data

        downloaded = dict(await asyncio.gather(*(fetch(entry) for entry in missing)))
        desired = {path: downloaded.get(path, local.get(path, b"")) for path in wanted}
        deleted = sum(1 for path in local if path not in wanted)
        await asyncio.to_thread(_replace_agent_folders, lease, desired)
        await asyncio.to_thread(
            _write_note,
            lease,
            _Note(
                version=pointer.version,
                manifest_sha256=pointer.manifest_sha256,
                unsaved=False,
                manifest=manifest,
            ),
        )
        lease.snapshot_base = SnapshotBase(pointer=pointer, manifest=manifest)
        return RestoreReport(
            warm=False,
            downloaded=len(downloaded),
            deleted=deleted,
            bytes=sum(len(data) for data in downloaded.values()),
            duration_ms=_elapsed(started),
            imported_legacy=False,
        )

    def _legacy_folder(self, chat: ChatScope) -> Path | None:
        if self._legacy_root is None:
            return None
        folder = (
            self._legacy_root
            / chat.workspace_id
            / "projects"
            / chat.project_id
            / "threads"
            / chat.thread_id
        )
        return folder if folder.is_dir() and not folder.is_symlink() else None

    async def forget(self, chat: ChatScope) -> None:
        """Delete the chat's version record (a privacy erasure, WS-27)."""

        await self._store.forget(workspace_id=chat.workspace_id, thread_id=chat.thread_id)

    # --- save ---------------------------------------------------------------------------------

    async def save(self, lease: AgentWorkspaceLease) -> SaveReport:
        """Save the chat's agent folders as a new version, or record that nothing changed."""

        started = time.monotonic()
        chat = lease.chat
        base = lease.snapshot_base or SnapshotBase(pointer=None, manifest=None)
        local: Mapping[str, bytes] = await asyncio.to_thread(_read_agent_folders, lease)
        manifest = await self._manifest_for(local, previous=base.manifest, chat=chat)
        if base.manifest is not None and manifest.same_files(base.manifest):
            await self._store.touch(workspace_id=chat.workspace_id, thread_id=chat.thread_id)
            return self._report(
                lease, "unchanged", uploaded=0, size=0, version=_version(base), started=started
            )
        if base.manifest is None and not manifest.entries and base.pointer is None:
            return self._report(
                lease, "unchanged", uploaded=0, size=0, version=None, started=started
            )
        new_files = await self._files_to_upload(chat, manifest, base=base, local=local)
        try:
            uploaded, status, pointer = await self._save_with_retries(
                lease, base=base, manifest=manifest, new_files=new_files
            )
            if status == "stale":
                rebased = await self._rebase_over_expiry(lease, base=base, local=local)
                if rebased is not None:
                    base, local, manifest = rebased
                    new_files = await self._files_to_upload(chat, manifest, base=base, local=local)
                    again, status, pointer = await self._save_with_retries(
                        lease, base=base, manifest=manifest, new_files=new_files
                    )
                    uploaded += again
        except WorkspaceSaveUnavailable:
            if base.pointer is not None and base.manifest is not None:
                await asyncio.to_thread(
                    _write_note,
                    lease,
                    _Note(
                        version=base.pointer.version,
                        manifest_sha256=base.pointer.manifest_sha256,
                        unsaved=True,
                        manifest=base.manifest,
                    ),
                )
            log.warning(
                "agent_workspace.save_unavailable",
                workspace_id=chat.workspace_id,
                thread_id=chat.thread_id,
                base_version=_version(base),
            )
            raise
        if status == "saved" and pointer is not None:
            await asyncio.to_thread(
                _write_note,
                lease,
                _Note(
                    version=pointer.version,
                    manifest_sha256=pointer.manifest_sha256,
                    unsaved=False,
                    manifest=manifest,
                ),
            )
            if base.legacy_folder is not None:
                await asyncio.to_thread(wipe_path, base.legacy_folder, remove_root=True)
            lease.snapshot_base = SnapshotBase(pointer=pointer, manifest=manifest)
        else:
            await asyncio.to_thread(_remove_note, lease)
            log.warning(
                "agent_workspace.save_refused",
                workspace_id=chat.workspace_id,
                thread_id=chat.thread_id,
                status=status,
                base_version=_version(base),
            )
        return self._report(
            lease,
            status,
            uploaded=uploaded,
            size=sum(len(data) for _, data in new_files),
            version=None if pointer is None else pointer.version,
            started=started,
        )

    async def _manifest_for(
        self,
        local: Mapping[str, bytes],
        *,
        previous: SnapshotManifest | None,
        chat: ChatScope,
    ) -> SnapshotManifest:
        """The file list for what is on disk now, carrying the previous version's expiries.

        An entry whose bytes are unchanged keeps the ``written_at`` and the receipt it already
        had. An expired entry (AW-22) is carried forward as it is — unless a local file now sits
        at its path, in which case the agent wrote it again and a fresh live entry replaces it.
        A new raw input or working file is given a receipt, so that when its bytes expire the
        agent is still told what was there and how to get it again. Those lookups are gathered
        rather than walked, because a turn that writes many new files would otherwise pay their
        round trips one after another on the save path.
        """

        earlier = previous.by_path() if previous is not None else {}
        now = datetime.now(UTC)
        shas = {path: hashlib.sha256(data).hexdigest() for path, data in local.items()}

        def carried(path: str) -> SnapshotEntry | None:
            """The previous version's entry when this file is untouched, else ``None``."""

            before = earlier.get(path)
            if before is not None and before.expired_at is None and before.sha256 == shas[path]:
                return before
            return None

        receipts = await self._receipts_for(
            chat, tuple(path for path in sorted(local) if carried(path) is None)
        )
        entries = []
        for path, data in sorted(local.items()):
            before = carried(path)
            entries.append(
                SnapshotEntry(
                    path=path,
                    sha256=shas[path],
                    size=len(data),
                    media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                    tier=tier_for(path),
                    written_at=before.written_at if before is not None else now,
                    receipt=before.receipt if before is not None else receipts[path],
                )
            )
        entries.extend(
            entry
            for entry in earlier.values()
            if entry.expired_at is not None and entry.path not in local
        )
        return SnapshotManifest(entries=tuple(sorted(entries, key=lambda item: item.path)))

    async def _rebase_over_expiry(
        self,
        lease: AgentWorkspaceLease,
        *,
        base: SnapshotBase,
        local: Mapping[str, bytes],
    ) -> tuple[SnapshotBase, Mapping[str, bytes], SnapshotManifest] | None:
        """Re-aim a save that lost only to the expiry job, or ``None`` for a real conflict.

        The expiry job (AW-24) moves a chat's version while a turn is still running, and without
        this the turn's own work would be thrown away for a race it did not lose to anyone. The
        move is an expiry *only* when every live entry the published version still has is the
        base's, byte for byte, and every path it no longer has live is one it now carries as an
        expired receipt. Anything else — another machine saved, a file changed — is a genuine
        conflict and stays ``stale``.

        The copies the expiry released go from the disk too, exactly as a restore would have
        dropped them; one the turn itself rewrote stays, and revives its path.
        """

        chat = lease.chat
        if base.pointer is None or base.manifest is None:
            return None
        current = await self._store.current(
            workspace_id=chat.workspace_id, thread_id=chat.thread_id
        )
        if current is None or current.version == base.pointer.version:
            return None
        published = await self._store.read_manifest(workspace_id=chat.workspace_id, pointer=current)
        base_live = {entry.path: entry.sha256 for entry in base.manifest.live()}
        published_live = {entry.path: entry.sha256 for entry in published.live()}
        expired = {entry.path for entry in published.expired()}
        gone = base_live.keys() - published_live.keys()
        if not gone:
            return None  # a move that expired nothing the base held is somebody else's save
        if any(base_live.get(path) != sha for path, sha in published_live.items()):
            return None
        if any(path not in expired for path in gone):
            return None
        released = {
            path
            for path in expired
            if path in local and hashlib.sha256(local[path]).hexdigest() == base_live.get(path)
        }
        if released:
            local = {path: data for path, data in local.items() if path not in released}
            await asyncio.to_thread(_replace_agent_folders, lease, local)
        log.info(
            "agent_workspace.save_rebased",
            workspace_id=chat.workspace_id,
            thread_id=chat.thread_id,
            base_version=base.pointer.version,
            onto_version=current.version,
            released=len(released),
        )
        rebased = SnapshotBase(
            pointer=current, manifest=published, legacy_folder=base.legacy_folder
        )
        manifest = await self._manifest_for(local, previous=published, chat=chat)
        return rebased, local, manifest

    async def _files_to_upload(
        self,
        chat: ChatScope,
        manifest: SnapshotManifest,
        *,
        base: SnapshotBase,
        local: Mapping[str, bytes],
    ) -> list[tuple[SnapshotEntry, bytes]]:
        """What this save must store: the new bytes, plus any this chat still holds only where
        the store no longer keeps a chat's files.

        Skipping a file the base already holds is what keeps a save cheap — but a base saved
        before the store moved a chat's files to their own area (F3 Phase 2, WS-30) holds bytes
        the save cannot hold, and skipping those failed every later save of the chat (review
        C1). The turn has every live file on disk, so it stores those again from there, and the
        chat moves to the new area on this save. The common case — everything already there —
        costs one query for the whole set; nothing is asked when nothing was skipped.
        """

        new_files = _new_files(manifest, base=base, local=local)
        uploading = {entry.sha256 for entry, _ in new_files}
        skipped = {entry.sha256 for entry in manifest.live()} - uploading
        if not skipped:
            return new_files
        missing = await self._store.unmoved_files(
            workspace_id=chat.workspace_id, thread_id=chat.thread_id, sha256s=skipped
        )
        return [
            *new_files,
            *((entry, local[entry.path]) for entry in manifest.live() if entry.sha256 in missing),
        ]

    async def _receipts_for(
        self, chat: ChatScope, paths: Sequence[str]
    ) -> dict[str, Receipt | None]:
        """Every new file's receipt, looked up concurrently under the transfer bound.

        Two of the five rules a receipt is read by go to the database, so a turn that wrote many
        new files pays that many round trips before its save can even start. The lookups are
        independent of one another, so they are gathered. The bound is ``concurrency`` — the
        same ``agent_workspace_transfer_concurrency`` a restore's downloads run under — so a
        save never opens more at once than a restore already does.

        Which receipt lands on which entry does not depend on the order they come back in: the
        answers are keyed by path and the file list is sorted by path either way.
        """

        if not paths:
            return {}
        gate = asyncio.Semaphore(self._concurrency)

        async def one(path: str) -> tuple[str, Receipt | None]:
            async with gate:
                return path, await self._receipt_for(chat, path)

        return dict(await asyncio.gather(*(one(path) for path in paths)))

    async def _receipt_for(self, chat: ChatScope, path: str) -> Receipt | None:
        """What this new file was, for after its bytes expire; ``None`` for a work product."""

        if tier_for(path) == "work_product":
            return None  # outputs/ never expires (AW-2), so there is nothing to tell the agent
        if self._receipts is None:
            return UNKNOWN_RECEIPT
        return await self._receipts.receipt_for(
            workspace_id=chat.workspace_id, thread_id=chat.thread_id, path=path
        )

    async def _save_with_retries(
        self,
        lease: AgentWorkspaceLease,
        *,
        base: SnapshotBase,
        manifest: SnapshotManifest,
        new_files: Sequence[tuple[SnapshotEntry, bytes]],
    ) -> tuple[int, SaveStatus, SnapshotPointer | None]:
        chat = lease.chat
        attempts = (*self._retry_delays, None)
        for delay in attempts:
            try:
                uploaded = await self._store.store_files(
                    workspace_id=chat.workspace_id, files=new_files
                )
                status, pointer = await self._store.save(
                    workspace_id=chat.workspace_id,
                    project_id=chat.project_id,
                    thread_id=chat.thread_id,
                    expected_version=_version(base),
                    manifest=manifest,
                    fence=lease.fence,
                )
                return uploaded, status, pointer
            except WorkspaceSaveUnavailable:
                if delay is None:
                    raise
                await self._sleep(delay)
        raise WorkspaceSaveUnavailable("unreachable")  # pragma: no cover

    def _report(
        self,
        lease: AgentWorkspaceLease,
        status: SaveStatus,
        *,
        uploaded: int,
        size: int,
        version: int | None,
        started: float,
    ) -> SaveReport:
        report = SaveReport(
            status=status,
            uploaded=uploaded,
            bytes=size,
            version=version,
            duration_ms=_elapsed(started),
        )
        log.info(
            "agent_workspace.save",
            workspace_id=lease.chat.workspace_id,
            thread_id=lease.chat.thread_id,
            status=report.status,
            uploaded=report.uploaded,
            bytes=report.bytes,
            version=report.version,
            duration_ms=report.duration_ms,
        )
        return report


# --- helpers ----------------------------------------------------------------------------------


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _version(base: SnapshotBase) -> int | None:
    return None if base.pointer is None else base.pointer.version


def _new_files(
    manifest: SnapshotManifest, *, base: SnapshotBase, local: Mapping[str, bytes]
) -> list[tuple[SnapshotEntry, bytes]]:
    """The bytes this save must upload: only the ones the base version still HOLDS may be skipped.

    An expired entry's content address names bytes the expiry deleted, so a file revived with the
    same bytes is uploaded again.
    """

    known = {entry.sha256 for entry in (base.manifest.live() if base.manifest else ())}
    return [(entry, local[entry.path]) for entry in manifest.live() if entry.sha256 not in known]


def _open_agent(lease: AgentWorkspaceLease) -> tuple[int, int]:
    """``(chat folder fd, agent folder fd)``; the caller closes both."""

    chat_fd = lease.factory.chat_dir_fd(lease.chat)
    try:
        agent_fd = os.open(_AGENT_DIR, _DIR_FLAGS, dir_fd=chat_fd)
    except BaseException:
        os.close(chat_fd)
        raise
    return chat_fd, agent_fd


def _read_agent_folders(lease: AgentWorkspaceLease) -> dict[str, bytes]:
    chat_fd, agent_fd = _open_agent(lease)
    try:
        files: dict[str, bytes] = {}
        for folder in SAVED_FOLDERS:
            for relative, data in read_directory(agent_fd, folder).items():
                files[f"{folder}/{relative}"] = data
        return files
    finally:
        os.close(agent_fd)
        os.close(chat_fd)


def _replace_agent_folders(lease: AgentWorkspaceLease, files: Mapping[str, bytes]) -> int:
    """Make the saved folders hold exactly ``files``; return how many local files were deleted."""

    by_folder: dict[str, dict[str, bytes]] = {folder: {} for folder in SAVED_FOLDERS}
    for path, data in files.items():
        folder, _, relative = validate_snapshot_path(path).partition("/")
        by_folder[folder][relative] = data
    chat_fd, agent_fd = _open_agent(lease)
    try:
        deleted = 0
        for folder, folder_files in by_folder.items():
            deleted += len(sync_directory(agent_fd, folder, folder_files, frozen=False).removed)
        return deleted
    finally:
        os.close(agent_fd)
        os.close(chat_fd)


def _read_legacy_folder(folder: Path) -> dict[str, bytes]:
    """The four agent folders of a chat's folder from before F3 (WS-22); links are skipped."""

    files: dict[str, bytes] = {}
    for name in SAVED_FOLDERS:
        base = folder / name
        if not base.is_dir() or base.is_symlink():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(folder).as_posix()
            if path.is_symlink() or not path.is_file() or ".clue-tmp-" in path.name:
                continue
            if any(part.is_symlink() for part in path.parents if folder in part.parents):
                continue
            try:
                validate_snapshot_path(relative)
            except SnapshotCorrupt:
                continue
            files[relative] = path.read_bytes()
    return files


def _read_note(lease: AgentWorkspaceLease) -> _Note | None:
    chat_fd = lease.factory.chat_dir_fd(lease.chat)
    try:
        try:
            file_fd = os.open(NOTE_FILE, _READ_FLAGS, dir_fd=chat_fd)
        except FileNotFoundError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise WorkspaceSecurityError("the snapshot note is not a regular file")
            chunks = []
            while chunk := os.read(file_fd, 64 * 1024):
                chunks.append(chunk)
        finally:
            os.close(file_fd)
    finally:
        os.close(chat_fd)
    try:
        document = json.loads(b"".join(chunks))
        return _Note(
            version=int(document["version"]),
            manifest_sha256=str(document["manifest_sha256"]),
            unsaved=bool(document["unsaved"]),
            manifest=decode_manifest(json.dumps(document["manifest"]).encode()),
        )
    except (ValueError, KeyError, TypeError, SnapshotCorrupt):
        # An unreadable note is no note: the next restore reconciles from the record.
        return None


def _write_note(lease: AgentWorkspaceLease, note: _Note) -> None:
    body = json.dumps(
        {
            "version": note.version,
            "manifest_sha256": note.manifest_sha256,
            "unsaved": note.unsaved,
            "manifest": json.loads(encode_manifest(note.manifest)),
        },
        sort_keys=True,
    ).encode()
    chat_fd = lease.factory.chat_dir_fd(lease.chat)
    try:
        temporary = f".clue-tmp-{secrets.token_hex(8)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(temporary, flags, _FILE_MODE, dir_fd=chat_fd)
        try:
            os.write(file_fd, body)
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        os.replace(temporary, NOTE_FILE, src_dir_fd=chat_fd, dst_dir_fd=chat_fd)
    finally:
        os.close(chat_fd)


def _remove_note(lease: AgentWorkspaceLease) -> None:
    chat_fd = lease.factory.chat_dir_fd(lease.chat)
    try:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(NOTE_FILE, dir_fd=chat_fd)
    finally:
        os.close(chat_fd)
