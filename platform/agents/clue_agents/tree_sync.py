"""Bring one folder to an exact set of files, writing only what changed.

F3 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md, WS-36
and WS-37; ruling AW-1 as amended 2026-10-22). Nothing is emptied and rebuilt: a file whose bytes
already match is left alone, a new or changed file is written to a temporary name and renamed into
place, and a file the set no longer names is removed. The agent's instruction folders
(``.deepagent/ inputs/ context/``) and each chat's own ``brand/ project/ attachments/`` copies go
through this one function.

Every operation is anchored to directory descriptors opened with ``O_NOFOLLOW``, and the tree is
checked as it is walked: a link, a special file, a hard-linked file or a folder with group/other
bits is refused, never followed. One turn per chat is the caller's guarantee (Postgres enforces it),
so the folder is not shared with a concurrent writer.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Final

from clue_agents.workspace_policy import WorkspaceSecurityError

__all__ = [
    "TreeSyncReport",
    "check_segment",
    "is_temporary_name",
    "read_directory",
    "sync_directory",
]

_DIRECTORY_MODE: Final = 0o700
_FROZEN_DIRECTORY_MODE: Final = 0o500
_FILE_MODE: Final = 0o600
_FROZEN_FILE_MODE: Final = 0o400
_TEMP_PREFIX: Final = ".clue-tmp-"
_DIR_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_CREATE_FLAGS: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


@dataclass(frozen=True, slots=True)
class TreeSyncReport:
    """What one sync did: paths written and removed (sorted), and how many were already right."""

    written: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: int


def sync_directory(
    parent_fd: int, name: str, files: Mapping[str, bytes], *, frozen: bool
) -> TreeSyncReport:
    """Make ``<parent_fd>/<name>`` hold exactly ``files`` (relative path → bytes).

    ``frozen`` folders end read-only (folders 0500, files 0400) and are thawed first; others stay
    private and writable (0700 / 0600). The folder is created if missing.
    """

    check_segment(name)
    desired = {_check_relative(path): data for path, data in files.items()}
    _check_no_file_dir_clash(desired)
    root_fd = _open_or_create(parent_fd, name)
    try:
        _set_modes(root_fd, directory_mode=_DIRECTORY_MODE, file_mode=_FILE_MODE)
        existing = dict(_walk_files(root_fd, ""))
        removed = sorted(path for path in existing if path not in desired)
        for path in removed:
            _unlink(root_fd, path)
        written: list[str] = []
        unchanged = 0
        for path in sorted(desired):
            data = desired[path]
            if path in existing and _same_bytes(root_fd, path, data):
                unchanged += 1
                continue
            _write_file(root_fd, path, data)
            written.append(path)
        _prune_empty(root_fd)
        if frozen:
            _set_modes(root_fd, directory_mode=_FROZEN_DIRECTORY_MODE, file_mode=_FROZEN_FILE_MODE)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    return TreeSyncReport(written=tuple(written), removed=tuple(removed), unchanged=unchanged)


def read_directory(parent_fd: int, name: str) -> dict[str, bytes]:
    """Every file below ``<parent_fd>/<name>`` (relative path → bytes); ``{}`` when it is absent.

    The same checks as :func:`sync_directory`: a link, a special file or a non-private folder is
    refused, never followed.
    """

    check_segment(name)
    try:
        root_fd = _open_dir(parent_fd, name)
    except WorkspaceSecurityError:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return {}
        raise
    try:
        files: dict[str, bytes] = {}
        for path, _size in list(_walk_files(root_fd, "")):
            parent, leaf = _open_parent(root_fd, path, create=False)
            try:
                file_fd = os.open(leaf, _READ_FLAGS, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                _check_file(os.fstat(file_fd))
                chunks = []
                while chunk := os.read(file_fd, 64 * 1024):
                    chunks.append(chunk)
            finally:
                os.close(file_fd)
            files[path] = b"".join(chunks)
        return files
    finally:
        os.close(root_fd)


# --- validation ---------------------------------------------------------------------------------


def is_temporary_name(segment: str) -> bool:
    """A name this module reserves for a write in progress (``.clue-tmp-*``)."""

    return segment.startswith(_TEMP_PREFIX)


def check_segment(segment: str) -> str:
    """``segment`` if a sync may write a file or folder by this name, else refuse it.

    The one rule for a path segment on disk. The snapshot file list checks its paths with this
    same function, so a path is never saved that a restore would refuse to write (review A2-I3).
    """

    if (
        not segment
        or segment in (".", "..")
        or "/" in segment
        or "\x00" in segment
        or is_temporary_name(segment)
    ):
        raise WorkspaceSecurityError(f"invalid path segment {segment!r}")
    return segment


def _check_relative(path: str) -> str:
    if not path or path.startswith("/"):
        raise WorkspaceSecurityError(f"invalid relative path {path!r}")
    for segment in path.split("/"):
        check_segment(segment)
    return path


def _check_no_file_dir_clash(desired: Mapping[str, bytes]) -> None:
    directories = {path.rsplit("/", 1)[0] for path in desired if "/" in path}
    prefixes = {
        "/".join(d.split("/")[: i + 1]) for d in directories for i in range(d.count("/") + 1)
    }
    clash = prefixes.intersection(desired)
    if clash:
        raise WorkspaceSecurityError(f"a path is both a file and a folder: {sorted(clash)[0]!r}")


def _check_directory(directory_fd: int) -> None:
    metadata = os.fstat(directory_fd)
    if not stat.S_ISDIR(metadata.st_mode):
        raise WorkspaceSecurityError("synced path is not a directory")
    if metadata.st_mode & 0o077:
        raise WorkspaceSecurityError("synced directory permissions are not private")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise WorkspaceSecurityError("synced directory has an unexpected owner")


def _check_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise WorkspaceSecurityError("synced entry is not a regular file")
    if metadata.st_nlink != 1:
        raise WorkspaceSecurityError("synced files must not be hard-linked")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise WorkspaceSecurityError("synced file has an unexpected owner")


# --- descriptors --------------------------------------------------------------------------------


def _open_dir(parent_fd: int, segment: str) -> int:
    try:
        directory_fd = os.open(segment, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise WorkspaceSecurityError(f"cannot open folder {segment!r} safely") from exc
    try:
        _check_directory(directory_fd)
    except BaseException:
        os.close(directory_fd)
        raise
    return directory_fd


def _open_or_create(parent_fd: int, segment: str) -> int:
    with suppress(FileExistsError):
        os.mkdir(segment, _DIRECTORY_MODE, dir_fd=parent_fd)
    return _open_dir(parent_fd, segment)


def _open_parent(root_fd: int, path: str, *, create: bool) -> tuple[int, str]:
    """A descriptor for the folder holding ``path`` (the caller closes it) and the leaf name."""

    *folders, leaf = path.split("/")
    current = os.dup(root_fd)
    try:
        for segment in folders:
            following = _open_or_create(current, segment) if create else _open_dir(current, segment)
            os.close(current)
            current = following
    except BaseException:
        os.close(current)
        raise
    return current, leaf


def _walk_files(directory_fd: int, prefix: str) -> Iterator[tuple[str, int]]:
    """``(relative path, size)`` of every file below ``directory_fd``; refuses anything unsafe.

    A leftover temporary file from an interrupted write is removed on the way.
    """

    for entry in sorted(os.listdir(directory_fd)):
        metadata = os.stat(entry, dir_fd=directory_fd, follow_symlinks=False)
        relative = f"{prefix}{entry}"
        if entry.startswith(_TEMP_PREFIX) and stat.S_ISREG(metadata.st_mode):
            os.unlink(entry, dir_fd=directory_fd)
            continue
        if stat.S_ISDIR(metadata.st_mode):
            child = _open_dir(directory_fd, entry)
            try:
                yield from _walk_files(child, f"{relative}/")
            finally:
                os.close(child)
            continue
        _check_file(metadata)
        yield relative, metadata.st_size


def _set_modes(directory_fd: int, *, directory_mode: int, file_mode: int) -> None:
    os.fchmod(directory_fd, _DIRECTORY_MODE)
    for entry in os.listdir(directory_fd):
        metadata = os.stat(entry, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            os.chmod(entry, _DIRECTORY_MODE, dir_fd=directory_fd, follow_symlinks=False)
            child = _open_dir(directory_fd, entry)
            try:
                _set_modes(child, directory_mode=directory_mode, file_mode=file_mode)
            finally:
                os.close(child)
            continue
        _check_file(metadata)
        file_fd = os.open(entry, _READ_FLAGS, dir_fd=directory_fd)
        try:
            os.fchmod(file_fd, file_mode)
        finally:
            os.close(file_fd)
    os.fchmod(directory_fd, directory_mode)


def _same_bytes(root_fd: int, path: str, data: bytes) -> bool:
    parent_fd, leaf = _open_parent(root_fd, path, create=False)
    try:
        file_fd = os.open(leaf, _READ_FLAGS, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    try:
        metadata = os.fstat(file_fd)
        _check_file(metadata)
        if metadata.st_size != len(data):
            return False
        digest = hashlib.sha256()
        while chunk := os.read(file_fd, 64 * 1024):
            digest.update(chunk)
    finally:
        os.close(file_fd)
    return digest.digest() == hashlib.sha256(data).digest()


def _write_file(root_fd: int, path: str, data: bytes) -> None:
    parent_fd, leaf = _open_parent(root_fd, path, create=True)
    try:
        temporary = f"{_TEMP_PREFIX}{secrets.token_hex(8)}"
        file_fd = os.open(temporary, _CREATE_FLAGS, _FILE_MODE, dir_fd=parent_fd)
        try:
            view = memoryview(data)
            while view:
                count = os.write(file_fd, view)
                if count <= 0:
                    raise WorkspaceSecurityError("write made no forward progress")
                view = view[count:]
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _unlink(root_fd: int, path: str) -> None:
    parent_fd, leaf = _open_parent(root_fd, path, create=False)
    try:
        os.unlink(leaf, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _prune_empty(directory_fd: int) -> bool:
    """Remove empty folders below ``directory_fd``; True when it is itself empty afterwards."""

    empty = True
    for entry in os.listdir(directory_fd):
        metadata = os.stat(entry, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child = _open_dir(directory_fd, entry)
            try:
                child_empty = _prune_empty(child)
            finally:
                os.close(child)
            if child_empty:
                os.rmdir(entry, dir_fd=directory_fd)
                continue
        empty = False
    return empty
