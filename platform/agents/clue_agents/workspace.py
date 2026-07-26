"""Production isolated workspace factory and POSIX-anchored deepagents backend.

All host access is rooted at already-open directory descriptors. Logical paths are normalized,
relative POSIX paths; every traversed directory and file is opened with ``O_NOFOLLOW``. Writes use
same-directory temporary files plus atomic link/replace, and a filesystem lock serializes quota
decisions across processes that share one execution workspace.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import fnmatch
import hashlib
import os
import stat
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, Literal
from uuid import uuid4

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from clue_agents.contracts import ArtifactRef, WorkspacePolicy, normalize_virtual_path
from clue_agents.ports import AgentArtifactSink, WorkspaceEntry
from clue_agents.workspace_policy import (
    PreparedWorkspaceRoot,
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceQuotaExceeded,
    WorkspaceSecurityError,
    validate_workspace_segment,
)
from clue_core import ExecutionId

__all__ = [
    "AgentWorkspaceFactory",
    "AgentWorkspaceLease",
    "AnchoredAgentWorkspaceBackend",
    "WorkspaceIdentity",
    "WorkspaceUsageSnapshot",
]

_DIRECTORY_MODE: Final = 0o700
_READ_ONLY_DIRECTORY_MODE: Final = 0o500
_FILE_MODE: Final = 0o600
_READ_ONLY_FILE_MODE: Final = 0o400
_DIR_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_LAYOUT: Final = (".deepagent", "inputs", "context", "work", "delegations", "outputs")
_MATERIALIZED_PREFIXES: Final = (".deepagent", "inputs", "context")
_MEDIA_TYPES: Final = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


def _is_under(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def _read_all(file_fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(file_fd, 64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(file_fd: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(file_fd, view[written:])
        if count <= 0:
            raise WorkspaceSecurityError("workspace write made no forward progress")
        written += count


def _validate_private_directory(directory_fd: int) -> None:
    metadata = os.fstat(directory_fd)
    if not stat.S_ISDIR(metadata.st_mode):
        raise WorkspaceSecurityError("workspace path component is not a directory")
    if metadata.st_mode & 0o077:
        raise WorkspaceSecurityError("workspace directory permissions are not private")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise WorkspaceSecurityError("workspace directory has an unexpected owner")


def _validate_regular_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise WorkspaceSecurityError("workspace entry is not a regular file")
    if metadata.st_nlink != 1:
        raise WorkspaceSecurityError("workspace files must not be hard-linked")
    if metadata.st_mode & 0o077:
        raise WorkspaceSecurityError("workspace file permissions are not private")
    if metadata.st_mode & 0o111:
        raise WorkspaceSecurityError("workspace files must not be executable")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise WorkspaceSecurityError("workspace file has an unexpected owner")


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    workspace_id: str
    project_id: str
    execution_id: ExecutionId
    workspace_root_id: str
    retention_class: str


@dataclass(frozen=True, slots=True)
class WorkspaceUsageSnapshot:
    file_count: int
    total_bytes: int
    output_file_count: int
    output_bytes: int
    max_file_count: int
    max_total_bytes: int


class AgentWorkspaceLease:
    """Trusted lifecycle handle. Only its backend/opaque identity reach later agent wiring."""

    def __init__(
        self,
        *,
        identity: WorkspaceIdentity,
        backend: AnchoredAgentWorkspaceBackend,
        workspace_segment: str,
        project_segment: str,
        execution_segment: str,
    ) -> None:
        self.identity = identity
        self.backend = backend
        self._workspace_segment = workspace_segment
        self._project_segment = project_segment
        self._execution_segment = execution_segment
        self._resources_frozen = False
        self._materialization_failed = False
        self._cleanup_authorized = False

    @property
    def resources_frozen(self) -> bool:
        return self._resources_frozen

    @property
    def materialization_failed(self) -> bool:
        return self._materialization_failed

    @property
    def cleanup_authorized(self) -> bool:
        return self._cleanup_authorized

    def mark_resources_frozen(self) -> None:
        if self._resources_frozen or self._materialization_failed:
            raise WorkspaceConflict("workspace resources cannot be frozen in the current state")
        self._resources_frozen = True

    def restore_resources_frozen(self) -> None:
        """Restore trusted lifecycle state after reopening an audited execution root."""

        if self._materialization_failed:
            raise WorkspaceConflict("failed materialization cannot be restored as frozen")
        self._resources_frozen = True

    def mark_materialization_failed(self) -> None:
        if self._resources_frozen:
            raise WorkspaceConflict("a frozen workspace cannot become materialization-failed")
        self._materialization_failed = True

    def authorize_cleanup(self, *, finalization_ref: ArtifactRef) -> None:
        if finalization_ref.workspace_id != self.identity.workspace_id:
            raise WorkspaceSecurityError("finalization artifact belongs to another workspace")
        if not self.backend.outputs_snapshotted:
            raise WorkspaceSecurityError("outputs must be durably snapshotted before cleanup")
        self._cleanup_authorized = True

    def usage_snapshot(self) -> WorkspaceUsageSnapshot:
        return self.backend.usage_snapshot()


class AnchoredAgentWorkspaceBackend(BackendProtocol):
    """File-only deepagents backend over one already-open execution root."""

    virtual_mode: Literal[True] = True

    def __init__(
        self,
        *,
        execution_fd: int,
        identity: WorkspaceIdentity,
        policy: WorkspacePolicy,
        artifact_sink: AgentArtifactSink,
    ) -> None:
        if policy.virtual_mode is not True:
            raise WorkspaceSecurityError("agent workspace requires virtual_mode=True")
        self._root_fd = execution_fd
        _validate_private_directory(self._root_fd)
        self._identity = identity
        self._policy = policy
        self._artifact_sink = artifact_sink
        self._thread_lock = threading.RLock()
        self._snapshot_lock = asyncio.Lock()
        self._closed = False
        self._outputs_snapshotted = False
        self._snapshot_refs: tuple[ArtifactRef, ...] = ()

    @property
    def workspace_root_id(self) -> str:
        return self._identity.workspace_root_id

    @property
    def outputs_snapshotted(self) -> bool:
        return self._outputs_snapshotted

    def close(self) -> None:
        with self._thread_lock:
            if not self._closed:
                os.close(self._root_fd)
                self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise WorkspaceSecurityError("workspace backend is closed")

    @contextmanager
    def _filesystem_lock(self, *, exclusive: bool) -> Iterator[None]:
        with self._thread_lock:
            self._ensure_open()
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(self._root_fd, operation)
            try:
                yield
            finally:
                fcntl.flock(self._root_fd, fcntl.LOCK_UN)

    @staticmethod
    def _framework_path(path: str, *, allow_root: bool = False) -> str:
        relative = path[1:] if path.startswith("/") else path
        if allow_root and relative in {"", "."}:
            return ""
        try:
            return normalize_virtual_path(relative)
        except ValueError as exc:
            raise WorkspaceSecurityError(str(exc)) from exc

    def _validate_path(self, path: str, *, write: bool, materialize: bool = False) -> str:
        try:
            logical = normalize_virtual_path(path)
        except ValueError as exc:
            raise WorkspaceSecurityError(str(exc)) from exc
        readable = self._policy.readable_prefixes
        if not _is_under(logical, readable):
            raise WorkspaceSecurityError("path is outside the readable workspace authority")
        if write:
            prefixes = _MATERIALIZED_PREFIXES if materialize else self._policy.writable_prefixes
            if not _is_under(logical, prefixes):
                raise WorkspaceSecurityError("path is outside the writable workspace authority")
            if not materialize and self._outputs_snapshotted and _is_under(logical, ("outputs",)):
                raise WorkspaceConflict("snapshotted outputs are immutable")
            suffix = PurePosixPath(logical).suffix.lower()
            if suffix not in self._policy.allowed_extensions:
                raise WorkspaceSecurityError("file type is not allowed in the agent workspace")
        return logical

    @contextmanager
    def _parent_fd(self, logical: str, *, create: bool) -> Iterator[tuple[int, str]]:
        parts = logical.split("/")
        current = os.dup(self._root_fd)
        try:
            _validate_private_directory(current)
            for component in parts[:-1]:
                try:
                    next_fd = os.open(component, _DIR_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise WorkspaceSecurityError(
                            "workspace parent directory does not exist"
                        ) from None
                    with suppress(FileExistsError):
                        os.mkdir(component, _DIRECTORY_MODE, dir_fd=current)
                    next_fd = os.open(component, _DIR_FLAGS, dir_fd=current)
                except OSError as exc:
                    raise WorkspaceSecurityError("workspace parent directory is unsafe") from exc
                os.close(current)
                current = next_fd
                _validate_private_directory(current)
            yield current, parts[-1]
        finally:
            os.close(current)

    def _open_file(self, logical: str) -> tuple[int, os.stat_result]:
        with self._parent_fd(logical, create=False) as (parent_fd, leaf):
            try:
                file_fd = os.open(leaf, _READ_FLAGS, dir_fd=parent_fd)
            except FileNotFoundError:
                raise WorkspaceSecurityError("workspace file does not exist") from None
            except OSError as exc:
                raise WorkspaceSecurityError("workspace file is unsafe") from exc
        metadata = os.fstat(file_fd)
        try:
            _validate_regular_file(metadata)
        except Exception:
            os.close(file_fd)
            raise
        return file_fd, metadata

    def _walk_files(self, *, prefix: str = "") -> list[tuple[str, int, int]]:
        start_fd = os.dup(self._root_fd)
        try:
            if prefix:
                for component in prefix.split("/"):
                    next_fd = os.open(component, _DIR_FLAGS, dir_fd=start_fd)
                    os.close(start_fd)
                    start_fd = next_fd
                    _validate_private_directory(start_fd)
            files: list[tuple[str, int, int]] = []

            def walk(directory_fd: int, relative: str) -> None:
                for name in sorted(os.listdir(directory_fd)):
                    if name.startswith(".clue-tmp-"):
                        raise WorkspaceSecurityError(
                            "workspace contains an incomplete atomic-write residue"
                        )
                    metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    logical = f"{relative}/{name}" if relative else name
                    if stat.S_ISDIR(metadata.st_mode):
                        child_fd = os.open(name, _DIR_FLAGS, dir_fd=directory_fd)
                        try:
                            _validate_private_directory(child_fd)
                            walk(child_fd, logical)
                        finally:
                            os.close(child_fd)
                    else:
                        _validate_regular_file(metadata)
                        files.append((logical, metadata.st_size, metadata.st_mode))

            walk(start_fd, prefix)
            return files
        except FileNotFoundError:
            return []
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("workspace tree contains an unsafe entry") from exc
        finally:
            os.close(start_fd)

    def _quota_before_write(
        self,
        *,
        byte_count: int,
        replacing_size: int = 0,
        adds_file: bool,
    ) -> None:
        if byte_count > self._policy.max_file_bytes:
            raise WorkspaceQuotaExceeded("file exceeds the per-file workspace quota")
        files = self._walk_files()
        self._validate_current_quota(files)
        file_count = len(files) + (1 if adds_file else 0)
        total_bytes = sum(size for _, size, _ in files) - replacing_size + byte_count
        if file_count > self._policy.max_file_count:
            raise WorkspaceQuotaExceeded("workspace file-count quota would be exceeded")
        if total_bytes > self._policy.max_total_bytes:
            raise WorkspaceQuotaExceeded("workspace total-byte quota would be exceeded")

    def _validate_current_quota(self, files: Sequence[tuple[str, int, int]]) -> None:
        if len(files) > self._policy.max_file_count:
            raise WorkspaceQuotaExceeded("workspace file-count quota is already exceeded")
        if any(size > self._policy.max_file_bytes for _, size, _ in files):
            raise WorkspaceQuotaExceeded("workspace contains a file over its per-file quota")
        if sum(size for _, size, _ in files) > self._policy.max_total_bytes:
            raise WorkspaceQuotaExceeded("workspace total-byte quota is already exceeded")

    @staticmethod
    def _write_temp(parent_fd: int, data: bytes) -> tuple[str, int]:
        temporary = f".clue-tmp-{uuid4().hex}"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        temp_fd = os.open(temporary, flags, _FILE_MODE, dir_fd=parent_fd)
        try:
            _write_all(temp_fd, data)
            os.fsync(temp_fd)
            return temporary, temp_fd
        except Exception:
            os.close(temp_fd)
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent_fd)
            raise

    def _create_file(self, logical: str, data: bytes, *, read_only: bool) -> WorkspaceEntry:
        with self._filesystem_lock(exclusive=True):
            self._quota_before_write(byte_count=len(data), adds_file=True)
            with self._parent_fd(logical, create=True) as (parent_fd, leaf):
                try:
                    os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise WorkspaceConflict("workspace file already exists")

                temporary = ""
                temp_fd = -1
                try:
                    temporary, temp_fd = self._write_temp(parent_fd, data)
                    if read_only:
                        os.fchmod(temp_fd, _READ_ONLY_FILE_MODE)
                    os.close(temp_fd)
                    temp_fd = -1
                    # linkat is an atomic no-replace install: a concurrent target wins loudly.
                    os.link(
                        temporary,
                        leaf,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    os.unlink(temporary, dir_fd=parent_fd)
                    temporary = ""
                    installed = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                    try:
                        _validate_regular_file(installed)
                    except Exception:
                        with suppress(FileNotFoundError):
                            os.unlink(leaf, dir_fd=parent_fd)
                        raise
                    os.fsync(parent_fd)
                except FileExistsError:
                    raise WorkspaceConflict("workspace file already exists") from None
                except WorkspaceError:
                    raise
                except OSError as exc:
                    raise WorkspaceSecurityError("atomic workspace write failed") from exc
                finally:
                    if temp_fd >= 0:
                        os.close(temp_fd)
                    if temporary:
                        with suppress(FileNotFoundError):
                            os.unlink(temporary, dir_fd=parent_fd)
        return self._entry(logical)

    def _replace_file_unlocked(self, logical: str, data: bytes, *, old_size: int) -> None:
        self._quota_before_write(
            byte_count=len(data),
            replacing_size=old_size,
            adds_file=False,
        )
        with self._parent_fd(logical, create=False) as (parent_fd, leaf):
            temporary = ""
            temp_fd = -1
            try:
                # Re-open immediately before replacement to reject a symlink, hard-link, or
                # special-file swap after the caller's first read.
                destination_fd = os.open(leaf, _READ_FLAGS, dir_fd=parent_fd)
                try:
                    current = os.fstat(destination_fd)
                    _validate_regular_file(current)
                    if current.st_size != old_size:
                        raise WorkspaceConflict("workspace file changed during edit")
                finally:
                    os.close(destination_fd)
                temporary, temp_fd = self._write_temp(parent_fd, data)
                os.close(temp_fd)
                temp_fd = -1
                os.replace(
                    temporary,
                    leaf,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                temporary = ""
                os.fsync(parent_fd)
            except WorkspaceError:
                raise
            except OSError as exc:
                raise WorkspaceSecurityError("atomic workspace edit failed") from exc
            finally:
                if temp_fd >= 0:
                    os.close(temp_fd)
                if temporary:
                    with suppress(FileNotFoundError):
                        os.unlink(temporary, dir_fd=parent_fd)

    def _entry(self, logical: str) -> WorkspaceEntry:
        file_fd, metadata = self._open_file(logical)
        try:
            digest = hashlib.sha256(_read_all(file_fd)).hexdigest()
        finally:
            os.close(file_fd)
        return WorkspaceEntry(
            path=logical,
            kind="file",
            byte_count=metadata.st_size,
            sha256=digest,
            read_only=not bool(metadata.st_mode & stat.S_IWUSR),
        )

    def read_text_sync(self, path: str) -> str:
        logical = self._validate_path(path, write=False)
        with self._filesystem_lock(exclusive=False):
            file_fd, metadata = self._open_file(logical)
            try:
                if metadata.st_size > self._policy.max_file_bytes:
                    raise WorkspaceQuotaExceeded("workspace file exceeds its read quota")
                data = _read_all(file_fd)
                if len(data) > self._policy.max_file_bytes:
                    raise WorkspaceQuotaExceeded("workspace file exceeds its read quota")
            finally:
                os.close(file_fd)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceSecurityError("workspace file is not valid UTF-8 text") from exc

    def write_text_sync(self, path: str, content: str) -> WorkspaceEntry:
        logical = self._validate_path(path, write=True)
        return self._create_file(logical, content.encode("utf-8"), read_only=False)

    def edit_text_sync(self, path: str, *, old: str, new: str) -> WorkspaceEntry:
        logical = self._validate_path(path, write=True)
        # Compare and replace under one process + filesystem lock, preventing lost updates.
        with self._filesystem_lock(exclusive=True):
            file_fd, metadata = self._open_file(logical)
            try:
                original = _read_all(file_fd).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceSecurityError("workspace file is not valid UTF-8 text") from exc
            finally:
                os.close(file_fd)
            count = original.count(old)
            if count == 0:
                raise WorkspaceConflict("edit source text was not found")
            if count != 1:
                raise WorkspaceConflict("edit source text is not unique")
            self._replace_file_unlocked(
                logical,
                original.replace(old, new, 1).encode("utf-8"),
                old_size=metadata.st_size,
            )
            return self._entry(logical)

    def materialize_bytes(self, path: str, data: bytes) -> WorkspaceEntry:
        """Trusted pre-model write into a read-only resource/context/input prefix."""

        logical = self._validate_path(path, write=True, materialize=True)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceSecurityError("materialized agent resources must be UTF-8 text") from exc
        return self._create_file(logical, data, read_only=True)

    def freeze_materialized_trees(self) -> None:
        with self._filesystem_lock(exclusive=True):
            for prefix in _MATERIALIZED_PREFIXES:
                self._freeze_tree(prefix)

    def _freeze_tree(self, prefix: str) -> None:
        current = os.dup(self._root_fd)
        try:
            for component in prefix.split("/"):
                next_fd = os.open(component, _DIR_FLAGS, dir_fd=current)
                os.close(current)
                current = next_fd

            def freeze(directory_fd: int) -> None:
                for name in os.listdir(directory_fd):
                    metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISDIR(metadata.st_mode):
                        child_fd = os.open(name, _DIR_FLAGS, dir_fd=directory_fd)
                        try:
                            freeze(child_fd)
                            os.fchmod(child_fd, _READ_ONLY_DIRECTORY_MODE)
                        finally:
                            os.close(child_fd)
                    else:
                        _validate_regular_file(metadata)
                        file_fd = os.open(name, _READ_FLAGS, dir_fd=directory_fd)
                        try:
                            os.fchmod(file_fd, _READ_ONLY_FILE_MODE)
                        finally:
                            os.close(file_fd)

            freeze(current)
            os.fchmod(current, _READ_ONLY_DIRECTORY_MODE)
        except OSError as exc:
            raise WorkspaceSecurityError("resource tree could not be frozen") from exc
        finally:
            os.close(current)

    def list_entries_sync(self, prefix: str = "") -> tuple[WorkspaceEntry, ...]:
        logical_prefix = ""
        if prefix:
            logical_prefix = self._validate_path(prefix.rstrip("/"), write=False)
        with self._filesystem_lock(exclusive=False):
            files = self._walk_files(prefix=logical_prefix)
            return tuple(self._entry(path) for path, _, _ in files)

    def stat_entry_sync(self, path: str) -> WorkspaceEntry:
        logical = self._validate_path(path, write=False)
        with self._filesystem_lock(exclusive=False):
            return self._entry(logical)

    async def list_entries(self, prefix: str = "") -> Sequence[WorkspaceEntry]:
        return await asyncio.to_thread(self.list_entries_sync, prefix)

    async def read_text(self, path: str) -> str:
        return await asyncio.to_thread(self.read_text_sync, path)

    async def stat_entry(self, path: str) -> WorkspaceEntry:
        return await asyncio.to_thread(self.stat_entry_sync, path)

    def usage_snapshot(self) -> WorkspaceUsageSnapshot:
        with self._filesystem_lock(exclusive=False):
            files = self._walk_files()
            self._validate_current_quota(files)
            output_sizes = tuple(
                size for path, size, _mode in files if _is_under(path, ("outputs",))
            )
            return WorkspaceUsageSnapshot(
                file_count=len(files),
                total_bytes=sum(size for _path, size, _mode in files),
                output_file_count=len(output_sizes),
                output_bytes=sum(output_sizes),
                max_file_count=self._policy.max_file_count,
                max_total_bytes=self._policy.max_total_bytes,
            )

    def materialized_trees_frozen(self) -> bool:
        """Return the all-or-none immutable state of the three trusted materialized trees."""

        with self._filesystem_lock(exclusive=False):
            modes: list[int] = []
            for name in _MATERIALIZED_PREFIXES:
                metadata = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise WorkspaceSecurityError("materialized workspace tree is not a directory")
                modes.append(stat.S_IMODE(metadata.st_mode))
            if all(mode == _READ_ONLY_DIRECTORY_MODE for mode in modes):
                return True
            if all(mode == _DIRECTORY_MODE for mode in modes):
                return False
            raise WorkspaceSecurityError(
                "materialized workspace trees have a partial immutable state"
            )

    def require_policy(self, policy: WorkspacePolicy) -> None:
        if policy != self._policy:
            raise WorkspaceConflict("reopened workspace policy differs from its original authority")

    async def write_text(self, path: str, content: str) -> WorkspaceEntry:
        return await asyncio.to_thread(self.write_text_sync, path, content)

    async def edit_text(self, path: str, *, old: str, new: str) -> WorkspaceEntry:
        return await asyncio.to_thread(self.edit_text_sync, path, old=old, new=new)

    async def snapshot_outputs(self) -> Sequence[ArtifactRef]:
        async with self._snapshot_lock:
            if self._outputs_snapshotted:
                return self._snapshot_refs
            with self._filesystem_lock(exclusive=True):
                self._validate_current_quota(self._walk_files())
                files = self._walk_files(prefix="outputs")
                payloads: list[tuple[str, bytes, str]] = []
                for logical, _, _ in files:
                    file_fd, _ = self._open_file(logical)
                    try:
                        data = _read_all(file_fd)
                    finally:
                        os.close(file_fd)
                    media_type = _MEDIA_TYPES.get(
                        PurePosixPath(logical).suffix.lower(),
                        "application/octet-stream",
                    )
                    payloads.append((logical, data, media_type))
                self._freeze_tree("outputs")

            refs: list[ArtifactRef] = []
            for logical, data, media_type in payloads:
                ref = await self._artifact_sink.persist(
                    workspace_id=self._identity.workspace_id,
                    logical_path=logical,
                    data=data,
                    media_type=media_type,
                )
                if ref.workspace_id != self._identity.workspace_id:
                    raise WorkspaceSecurityError(
                        "artifact sink returned a cross-workspace reference"
                    )
                if ref.sha256 != hashlib.sha256(data).hexdigest():
                    raise WorkspaceSecurityError(
                        "artifact sink returned a mismatched content digest"
                    )
                refs.append(ref)
            self._snapshot_refs = tuple(refs)
            self._outputs_snapshotted = True
            return self._snapshot_refs

    # --- deepagents BackendProtocol compatibility -----------------------------------------

    @staticmethod
    def _error(exc: Exception) -> str:
        if isinstance(exc, WorkspaceQuotaExceeded):
            return f"quota_exceeded: {exc}"
        if isinstance(exc, WorkspaceConflict):
            return f"conflict: {exc}"
        return f"permission_denied: {exc}"

    def ls(self, path: str) -> LsResult:
        try:
            logical = self._framework_path(path, allow_root=True)
            entries = self.list_entries_sync(logical)
            result: list[FileInfo] = [
                {"path": item.path, "is_dir": False, "size": item.byte_count} for item in entries
            ]
            return LsResult(entries=result)
        except WorkspaceError as exc:
            return LsResult(error=self._error(exc))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            logical = self._framework_path(file_path)
            content = self.read_text_sync(logical)
            lines = content.splitlines(keepends=True)
            return ReadResult(
                file_data={
                    "content": "".join(lines[offset : offset + limit]),
                    "encoding": "utf-8",
                }
            )
        except WorkspaceError as exc:
            return ReadResult(error=self._error(exc))

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            logical = self._framework_path(file_path)
            entry = self.write_text_sync(logical, content)
            return WriteResult(path=entry.path)
        except WorkspaceError as exc:
            return WriteResult(error=self._error(exc))

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if replace_all:
            return EditResult(error="permission_denied: replace_all is not available")
        try:
            logical = self._framework_path(file_path)
            entry = self.edit_text_sync(logical, old=old_string, new=new_string)
            return EditResult(path=entry.path, occurrences=1)
        except WorkspaceError as exc:
            return EditResult(error=self._error(exc))

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            logical = self._framework_path(path or "", allow_root=True)
            entries = self.list_entries_sync(logical)
            matches: list[FileInfo] = []
            for item in entries:
                relative = item.path.removeprefix(f"{logical}/") if logical else item.path
                if fnmatch.fnmatch(relative, pattern):
                    matches.append({"path": item.path, "is_dir": False, "size": item.byte_count})
            return GlobResult(matches=matches)
        except WorkspaceError as exc:
            return GlobResult(error=self._error(exc))

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        listed = self.glob(glob or "**", path)
        if listed.error:
            return GrepResult(error=listed.error)
        matches: list[GrepMatch] = []
        for entry in listed.matches or []:
            content = self.read_text_sync(entry["path"])
            for line_number, line in enumerate(content.splitlines(), start=1):
                if pattern in line:
                    matches.append({"path": entry["path"], "line": line_number, "text": line})
        return GrepResult(matches=matches)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for requested, data in files:
            try:
                logical = self._framework_path(requested)
                content = data.decode("utf-8")
                self.write_text_sync(logical, content)
                responses.append(FileUploadResponse(path=requested))
            except UnicodeDecodeError:
                responses.append(FileUploadResponse(path=requested, error="invalid_encoding"))
            except WorkspaceError as exc:
                responses.append(FileUploadResponse(path=requested, error=self._error(exc)))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for requested in paths:
            try:
                logical = self._framework_path(requested)
                content = self.read_text_sync(logical).encode("utf-8")
                responses.append(FileDownloadResponse(path=requested, content=content))
            except WorkspaceError as exc:
                responses.append(FileDownloadResponse(path=requested, error=self._error(exc)))
        return responses


class AgentWorkspaceFactory:
    """Create and remove one-shot execution workspaces below a prepared dedicated root."""

    def __init__(
        self,
        *,
        prepared_root: PreparedWorkspaceRoot,
        artifact_sink: AgentArtifactSink,
    ) -> None:
        self._root_fd = os.open(prepared_root.path, _DIR_FLAGS)
        _validate_private_directory(self._root_fd)
        self._artifact_sink = artifact_sink
        self._lock = threading.RLock()
        self._closed = False
        self._active: dict[tuple[str, str, str], AnchoredAgentWorkspaceBackend] = {}

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                for backend in tuple(self._active.values()):
                    backend.close()
                self._active.clear()
                os.close(self._root_fd)
                self._closed = True

    @contextmanager
    def _root_lock(self) -> Iterator[None]:
        with self._lock:
            if self._closed:
                raise WorkspaceSecurityError("workspace factory is closed")
            fcntl.flock(self._root_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(self._root_fd, fcntl.LOCK_UN)

    @staticmethod
    def _ensure_directory(parent_fd: int, segment: str) -> int:
        try:
            os.mkdir(segment, _DIRECTORY_MODE, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise WorkspaceSecurityError("workspace scope directory could not be created") from exc
        try:
            directory_fd = os.open(segment, _DIR_FLAGS, dir_fd=parent_fd)
            _validate_private_directory(directory_fd)
            if stat.S_IMODE(os.fstat(directory_fd).st_mode) != _DIRECTORY_MODE:
                os.close(directory_fd)
                raise WorkspaceSecurityError("active workspace scope directory must have mode 0700")
            return directory_fd
        except OSError as exc:
            raise WorkspaceSecurityError("workspace scope directory is unsafe") from exc

    @staticmethod
    def _audit_scope_directories(parent_fd: int) -> None:
        """Reject files, links, permissive directories, and special nodes between scope levels."""

        try:
            for name in os.listdir(parent_fd):
                metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise WorkspaceSecurityError(
                        "workspace scope contains an unexpected non-directory entry"
                    )
                child_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
                try:
                    _validate_private_directory(child_fd)
                    if stat.S_IMODE(os.fstat(child_fd).st_mode) != _DIRECTORY_MODE:
                        raise WorkspaceSecurityError(
                            "active workspace scope directory must have mode 0700"
                        )
                finally:
                    os.close(child_fd)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("workspace scope directory audit failed") from exc

    def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        execution_id: ExecutionId,
        policy: WorkspacePolicy,
    ) -> AgentWorkspaceLease:
        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        project_segment = validate_workspace_segment(project_id, label="project_id")
        execution_segment = validate_workspace_segment(str(execution_id), label="execution_id")
        root_id = (
            "awr_"
            + hashlib.sha256(
                f"{workspace_segment}\0{project_segment}\0{execution_segment}".encode()
            ).hexdigest()
        )
        identity = WorkspaceIdentity(
            workspace_id=workspace_id,
            project_id=project_id,
            execution_id=execution_id,
            workspace_root_id=root_id,
            retention_class=policy.retention_class,
        )

        with self._root_lock():
            workspace_fd = self._ensure_directory(self._root_fd, workspace_segment)
            try:
                self._audit_scope_directories(workspace_fd)
                project_fd = self._ensure_directory(workspace_fd, project_segment)
                try:
                    self._audit_scope_directories(project_fd)
                    try:
                        os.mkdir(execution_segment, _DIRECTORY_MODE, dir_fd=project_fd)
                    except FileExistsError:
                        raise WorkspaceConflict(
                            "execution workspace already exists and cannot be reused"
                        ) from None
                    execution_fd = os.open(execution_segment, _DIR_FLAGS, dir_fd=project_fd)
                    _validate_private_directory(execution_fd)
                    try:
                        for directory in _LAYOUT:
                            os.mkdir(directory, _DIRECTORY_MODE, dir_fd=execution_fd)
                        os.fsync(execution_fd)
                    except Exception:
                        os.close(execution_fd)
                        self._remove_tree(project_fd, execution_segment)
                        raise
                finally:
                    os.close(project_fd)
            finally:
                os.close(workspace_fd)

        backend = AnchoredAgentWorkspaceBackend(
            execution_fd=execution_fd,
            identity=identity,
            policy=policy,
            artifact_sink=self._artifact_sink,
        )
        with self._lock:
            self._active[(workspace_segment, project_segment, execution_segment)] = backend
        return AgentWorkspaceLease(
            identity=identity,
            backend=backend,
            workspace_segment=workspace_segment,
            project_segment=project_segment,
            execution_segment=execution_segment,
        )

    def acquire(
        self,
        *,
        workspace_id: str,
        project_id: str,
        execution_id: ExecutionId,
        policy: WorkspacePolicy,
    ) -> AgentWorkspaceLease:
        """Create or securely reopen the same execution root for durable crash recovery."""

        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        project_segment = validate_workspace_segment(project_id, label="project_id")
        execution_segment = validate_workspace_segment(str(execution_id), label="execution_id")
        key = (workspace_segment, project_segment, execution_segment)
        with self._lock:
            backend = self._active.get(key)
        if backend is None:
            try:
                return self.create(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    execution_id=execution_id,
                    policy=policy,
                )
            except WorkspaceConflict:
                backend = self._reopen_backend(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    execution_id=execution_id,
                    workspace_segment=workspace_segment,
                    project_segment=project_segment,
                    execution_segment=execution_segment,
                    policy=policy,
                )
                with self._lock:
                    self._active[key] = backend
        backend.require_policy(policy)
        lease = AgentWorkspaceLease(
            identity=WorkspaceIdentity(
                workspace_id=workspace_id,
                project_id=project_id,
                execution_id=execution_id,
                workspace_root_id=backend.workspace_root_id,
                retention_class=policy.retention_class,
            ),
            backend=backend,
            workspace_segment=workspace_segment,
            project_segment=project_segment,
            execution_segment=execution_segment,
        )
        if backend.materialized_trees_frozen():
            lease.restore_resources_frozen()
        return lease

    def _reopen_backend(
        self,
        *,
        workspace_id: str,
        project_id: str,
        execution_id: ExecutionId,
        workspace_segment: str,
        project_segment: str,
        execution_segment: str,
        policy: WorkspacePolicy,
    ) -> AnchoredAgentWorkspaceBackend:
        with self._root_lock():
            workspace_fd = os.open(workspace_segment, _DIR_FLAGS, dir_fd=self._root_fd)
            try:
                _validate_private_directory(workspace_fd)
                project_fd = os.open(project_segment, _DIR_FLAGS, dir_fd=workspace_fd)
                try:
                    _validate_private_directory(project_fd)
                    execution_fd = os.open(execution_segment, _DIR_FLAGS, dir_fd=project_fd)
                    _validate_private_directory(execution_fd)
                    entries = set(os.listdir(execution_fd))
                    if entries != set(_LAYOUT):
                        os.close(execution_fd)
                        raise WorkspaceSecurityError(
                            "reopened execution root has an unexpected top-level layout"
                        )
                    for entry in entries:
                        metadata = os.stat(entry, dir_fd=execution_fd, follow_symlinks=False)
                        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(
                            metadata.st_mode
                        ) not in {_DIRECTORY_MODE, _READ_ONLY_DIRECTORY_MODE}:
                            os.close(execution_fd)
                            raise WorkspaceSecurityError(
                                "reopened execution root contains an unsafe top-level entry"
                            )
                finally:
                    os.close(project_fd)
            finally:
                os.close(workspace_fd)
        identity = WorkspaceIdentity(
            workspace_id=workspace_id,
            project_id=project_id,
            execution_id=execution_id,
            workspace_root_id=(
                "awr_"
                + hashlib.sha256(
                    f"{workspace_segment}\0{project_segment}\0{execution_segment}".encode()
                ).hexdigest()
            ),
            retention_class=policy.retention_class,
        )
        return AnchoredAgentWorkspaceBackend(
            execution_fd=execution_fd,
            identity=identity,
            policy=policy,
            artifact_sink=self._artifact_sink,
        )

    @classmethod
    def _remove_tree(cls, parent_fd: int, name: str) -> None:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(metadata.st_mode):
            raise WorkspaceSecurityError("workspace cleanup found an unexpected entry")
        directory_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        try:
            # Resource/output trees are immutable during execution. Cleanup alone restores
            # owner-write permission so their children can be unlinked.
            os.fchmod(directory_fd, _DIRECTORY_MODE)
            for child in os.listdir(directory_fd):
                child_metadata = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISDIR(child_metadata.st_mode):
                    cls._remove_tree(directory_fd, child)
                elif stat.S_ISREG(child_metadata.st_mode):
                    os.unlink(child, dir_fd=directory_fd)
                else:
                    raise WorkspaceSecurityError("workspace cleanup found a link or special file")
        finally:
            os.close(directory_fd)
        os.rmdir(name, dir_fd=parent_fd)

    def _delete_execution(self, lease: AgentWorkspaceLease) -> None:
        lease.backend.close()
        with self._lock:
            self._active.pop(
                (lease._workspace_segment, lease._project_segment, lease._execution_segment),
                None,
            )
        with self._root_lock():
            workspace_fd = os.open(lease._workspace_segment, _DIR_FLAGS, dir_fd=self._root_fd)
            try:
                project_fd = os.open(
                    lease._project_segment,
                    _DIR_FLAGS,
                    dir_fd=workspace_fd,
                )
                try:
                    self._remove_tree(project_fd, lease._execution_segment)
                    try:
                        os.rmdir(lease._project_segment, dir_fd=workspace_fd)
                    except OSError as exc:
                        if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                            raise
                finally:
                    os.close(project_fd)
                try:
                    os.rmdir(lease._workspace_segment, dir_fd=self._root_fd)
                except OSError as exc:
                    if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                        raise
            finally:
                os.close(workspace_fd)

    def cleanup(self, lease: AgentWorkspaceLease) -> None:
        if not lease.cleanup_authorized:
            raise WorkspaceSecurityError("workspace cleanup requires durable finalization")
        self._delete_execution(lease)

    def discard_failed_materialization(self, lease: AgentWorkspaceLease) -> None:
        if not lease.materialization_failed or lease.resources_frozen:
            raise WorkspaceSecurityError(
                "only a pre-model materialization failure may be discarded without finalization"
            )
        self._delete_execution(lease)

    def erase_for_privacy(
        self,
        *,
        workspace_id: str,
        project_id: str,
        execution_id: ExecutionId,
    ) -> bool:
        """Privileged, idempotent DSAR deletion of an execution workspace.

        Unlike ordinary cleanup this does not require a finalization receipt: retaining
        materialized personal data after an erasure request would be the unsafe outcome. Any
        live backend held by this process is closed first so it cannot continue writing through
        an unlinked directory descriptor. Returns whether the execution directory existed.
        """

        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        project_segment = validate_workspace_segment(project_id, label="project_id")
        execution_segment = validate_workspace_segment(str(execution_id), label="execution_id")
        key = (workspace_segment, project_segment, execution_segment)
        with self._lock:
            active = self._active.pop(key, None)
            if active is not None:
                active.close()

        with self._root_lock():
            try:
                workspace_fd = os.open(workspace_segment, _DIR_FLAGS, dir_fd=self._root_fd)
            except FileNotFoundError:
                return False
            try:
                try:
                    project_fd = os.open(project_segment, _DIR_FLAGS, dir_fd=workspace_fd)
                except FileNotFoundError:
                    return False
                try:
                    try:
                        os.stat(execution_segment, dir_fd=project_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        return False
                    self._remove_tree(project_fd, execution_segment)
                    try:
                        os.rmdir(project_segment, dir_fd=workspace_fd)
                    except OSError as exc:
                        if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                            raise
                finally:
                    os.close(project_fd)
                try:
                    os.rmdir(workspace_segment, dir_fd=self._root_fd)
                except OSError as exc:
                    if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                        raise
            finally:
                os.close(workspace_fd)
        return True

    def purge_terminal(
        self,
        *,
        workspace_id: str,
        project_id: str,
        execution_id: ExecutionId,
    ) -> bool:
        """Remove a terminal execution root after the caller verifies durable retention policy."""

        return self.erase_for_privacy(
            workspace_id=workspace_id,
            project_id=project_id,
            execution_id=execution_id,
        )
