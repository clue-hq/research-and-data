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
import json
import os
import re
import stat
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
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
from clue_agents.versioned_root import (
    VersionedRootWriter,
    VersionedWriteOutcome,
    VersionedWriteRefused,
)
from clue_agents.workspace_policy import (
    PreparedWorkspaceRoot,
    WorkspaceConfigurationError,
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceQuotaExceeded,
    WorkspaceSecurityError,
    validate_workspace_segment,
)
from clue_core import ExecutionId

__all__ = [
    "ATTACHMENTS_DIR",
    "LIBRARY_DIR",
    "PROJECTS_DIR",
    "THREADS_DIR",
    "AgentWorkspaceFactory",
    "AgentWorkspaceLease",
    "AnchoredAgentWorkspaceBackend",
    "MountMode",
    "MountRequest",
    "WorkspaceIdentity",
    "WorkspaceMount",
    "WorkspaceUsageSnapshot",
]

#: The three scope folders below the prepared root. A workspace holds its shared ``library``
#: beside ``projects``; a project holds its own ``library`` beside ``threads``; one thread
#: directory is one persistent agent workspace.
LIBRARY_DIR: Final = "library"
PROJECTS_DIR: Final = "projects"
THREADS_DIR: Final = "threads"
#: The project's uploaded files, beside its ``library``: every attachment a human sent in a
#: project chat, byte for byte, read-only to the agent.
ATTACHMENTS_DIR: Final = "attachments"

#: The manifest name every library generation carries — written by
#: :class:`~clue_agents.library_tree.LibraryTree`, read back here. The literal is repeated rather
#: than imported because that module imports this one; the name is frozen on disk either way.
_LIBRARY_INDEX_NAME: Final = "index.json"
#: A mount whose generation names no versions: every write under it is a first write.
_NO_VERSIONS: Final[Mapping[str, int]] = MappingProxyType({})

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
_LAYOUT: Final = (".deepagent", "inputs", "context", "scratch", "reads", "work", "outputs")
# A mount claims one reserved first path segment. It is deliberately narrower than a
# workspace segment: lowercase, no dot, no separator, so it can never collide with a
# layout folder, a temporary-write residue, or a relative path component.
_MOUNT_SEGMENT: Final = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_MATERIALIZED_PREFIXES: Final = (".deepagent", "inputs", "context")
#: The one folder a spilled read may land in. ``reads/`` is readable by the model and writable by
#: nobody but the runtime, which is exactly the shape an oversized tool result needs.
_SPILL_PREFIXES: Final = ("reads",)
#: A spill file is named for its operation and nothing else: one flat, lowercase, dot-free and
#: separator-free segment (a UUID is the shape in production), so the caller's id can never become
#: a path, a traversal, a second extension, or a hidden file.
_SPILL_SEGMENT: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
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


def _mounted_versions(directory_fd: int, *, mount_name: str) -> Mapping[str, int]:
    """The ``path → version`` map a mounted library generation records about itself.

    Read straight off the tree's own ``index.json`` — the manifest the generation was installed
    with — so the versions the backend sends to the writer are the versions of the very bytes the
    model is reading, and not a second opinion fetched from somewhere else that could already
    have moved. A file with a null version is a compiled one that nobody versions; it is left out
    of the map, which is exactly the "I read no version" the writer expects for it.

    The index is parsed as plain JSON on purpose: its typed shape
    (``ProjectLibraryIndexCard``) belongs to the API package, which this one may not import, and
    the two fields read here are the whole contract. ``files[].path`` is already relative to the
    tree — the card's ``workspace_path`` is the one that carries the mount's name — so the strip
    below is a no-op on today's manifests and only keeps the key mount-relative if a future
    manifest ever writes the served path there.
    """

    try:
        file_fd = os.open(_LIBRARY_INDEX_NAME, _READ_FLAGS, dir_fd=directory_fd)
    except FileNotFoundError:
        return _NO_VERSIONS
    except OSError as exc:
        raise WorkspaceSecurityError("mounted library index is a link or is unreadable") from exc
    try:
        raw = _read_all(file_fd)
    finally:
        os.close(file_fd)
    try:
        document = json.loads(raw.decode("utf-8"))
        entries = document["files"]
        versions = {
            str(entry["path"]).removeprefix(f"{mount_name}/"): int(entry["version"])
            for entry in entries
            if entry.get("version") is not None
        }
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise WorkspaceConfigurationError("mounted library index is not a readable manifest") from (
            exc
        )
    return MappingProxyType(versions)


#: ``read_only`` serves somebody else's bytes; ``read_write`` is an ordinary writable tree under
#: the thread's quota; ``versioned`` reads like the first and writes like neither — every write
#: goes to the mount's :class:`~clue_agents.versioned_root.VersionedRootWriter` and comes back as
#: a document version, and the tree the model reads is re-opened from whatever that produced.
MountMode = Literal["read_only", "read_write", "versioned"]


@dataclass(frozen=True, slots=True)
class WorkspaceMount:
    """One extra anchored root served under a reserved first path segment.

    ``directory_fd`` is an already-open, audited private directory descriptor. The backend owns
    it once the mount is accepted: :meth:`AnchoredAgentWorkspaceBackend.close` closes it.

    The last three fields belong to a ``versioned`` mount and are absent from every other kind.
    ``writer`` takes the writes; ``versions`` is the ``path → version`` map read off the mounted
    generation's own manifest, which is what makes a write an *optimistic* one — the backend can
    tell the writer which version the model was looking at; ``reopen`` returns a fresh descriptor
    on the refreshed tree, so the mount is a frozen dataclass that gets *replaced*, never mutated.
    """

    name: str
    directory_fd: int
    mode: MountMode
    writer: VersionedRootWriter | None = None
    versions: Mapping[str, int] = _NO_VERSIONS
    reopen: Callable[[], int] | None = None


@dataclass(frozen=True, slots=True)
class MountRequest:
    """What the caller wants mounted; the factory turns it into open descriptors.

    A request names durable directories that live *beside* the thread root — never inside it —
    so a mount is a read of already-materialized bytes, never a copy into the agent's workspace.
    """

    #: ``(brand_id, knowledge_version)`` → ``<ws>/library/brand/<brand>/<version>``, read-only.
    brand: tuple[str, str] | None = None
    #: ``<ws>/projects/<project>/<project_library_name>`` → the ``project`` mount, read-only.
    project_library: bool = False
    #: Which tree below ``<ws>/projects/<project>/`` the ``project`` mount serves. The project's
    #: shared library for every caller but one: a turn whose pinned generation is no longer the
    #: installed one materializes that generation as its own tree beside the library and names it
    #: here, so the mount is the one place the choice is made and the model's paths never move.
    #: It is a single directory name, never a path — the factory validates it as one segment.
    project_library_name: str = LIBRARY_DIR
    #: When set (and ``project_library`` is on), the ``project`` mount is opened ``versioned``:
    #: the model's ``write_file``/``edit_file`` under ``project/`` become document versions taken
    #: by this writer. Left ``None`` the mount stays read-only, which is the state every caller
    #: that has no documents to offer should be in — a mount is writable only on purpose.
    project_writer: VersionedRootWriter | None = None
    #: ``<ws>/projects/<project>/attachments`` → the ``attachments`` mount, read-only, when the
    #: directory exists (spec 2026-09-19 §3.2). The fleet's sync creates it before the acquire,
    #: so a project nobody has uploaded to simply mounts nothing — asking for it is never an
    #: error, because "no attachments yet" is the ordinary state of a new project.
    attachments: bool = False


_NO_MOUNTS: Final = MountRequest()


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    workspace_id: str
    project_id: str
    thread_id: str
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
    """Trusted lifecycle handle. Only its backend/opaque identity reach later agent wiring.

    One lease is one turn's hold on a persistent thread workspace. Ending the turn
    :meth:`release` s the hold; the thread directory and its ``scratch``/``reads`` folders
    outlive every lease taken over them.
    """

    def __init__(
        self,
        *,
        identity: WorkspaceIdentity,
        backend: AnchoredAgentWorkspaceBackend,
        workspace_segment: str,
        project_segment: str,
        thread_segment: str,
        factory: AgentWorkspaceFactory,
    ) -> None:
        self.identity = identity
        self.backend = backend
        self._workspace_segment = workspace_segment
        self._project_segment = project_segment
        self._thread_segment = thread_segment
        self._factory = factory
        self._resources_frozen = False
        self._materialized = False
        self._materialization_failed = False
        self._cleanup_authorized = False

    @property
    def workspace_segment(self) -> str:
        """The validated directory segment this lease's workspace lives under."""

        return self._workspace_segment

    @property
    def project_segment(self) -> str:
        """The validated directory segment this lease's project lives under."""

        return self._project_segment

    @property
    def thread_segment(self) -> str:
        """The validated directory segment this lease's thread workspace lives under."""

        return self._thread_segment

    @property
    def resources_frozen(self) -> bool:
        """Whether the trusted trees on disk are frozen — last turn's or this turn's."""

        return self._resources_frozen

    @property
    def materialized(self) -> bool:
        """Whether *this* turn wrote and verified its own pinned bytes into the thread."""

        return self._materialized

    @property
    def materialization_failed(self) -> bool:
        return self._materialization_failed

    @property
    def cleanup_authorized(self) -> bool:
        return self._cleanup_authorized

    def mark_resources_frozen(self) -> None:
        """Record that the materialized trees are frozen again after this turn's write."""

        if self._materialization_failed:
            raise WorkspaceConflict("workspace resources cannot be frozen in the current state")
        self._resources_frozen = True

    def restore_resources_frozen(self) -> None:
        """Restore trusted lifecycle state after reopening an audited thread root."""

        if self._materialization_failed:
            raise WorkspaceConflict("failed materialization cannot be restored as frozen")
        self._resources_frozen = True

    def mark_materialized(self) -> None:
        """Record that this turn's pinned resources, inputs and context are verified on disk."""

        if self._materialization_failed:
            raise WorkspaceConflict("a failed materialization cannot become materialized")
        if not self._resources_frozen:
            raise WorkspaceConflict("materialized resources must be frozen before the model runs")
        self._materialized = True

    def mark_materialization_failed(self) -> None:
        if self._materialized:
            raise WorkspaceConflict("a materialized workspace cannot become materialization-failed")
        # The reset unfroze the trusted trees and the write never finished, so nothing on
        # disk is this turn's pinned truth any more.
        self._resources_frozen = False
        self._materialization_failed = True

    def release(self) -> None:
        """End this turn's hold on the thread. Nothing on disk is removed."""

        self._factory.release(self)

    def authorize_cleanup(self, *, finalization_ref: ArtifactRef) -> None:
        """Record that outputs are durably snapshotted under a same-workspace finalization.

        Since the thread workspace persists, this no longer gates a deletion; it stays the
        turn's honest statement that nothing unsaved is being dropped when the lease ends.
        """

        if finalization_ref.workspace_id != self.identity.workspace_id:
            raise WorkspaceSecurityError("finalization artifact belongs to another workspace")
        if not self.backend.outputs_snapshotted:
            raise WorkspaceSecurityError("outputs must be durably snapshotted before cleanup")
        self._cleanup_authorized = True

    def usage_snapshot(self) -> WorkspaceUsageSnapshot:
        return self.backend.usage_snapshot()


class AnchoredAgentWorkspaceBackend(BackendProtocol):
    """File-only deepagents backend over one already-open thread root."""

    virtual_mode: Literal[True] = True

    def __init__(
        self,
        *,
        execution_fd: int,
        identity: WorkspaceIdentity,
        policy: WorkspacePolicy,
        artifact_sink: AgentArtifactSink,
        mounts: Sequence[WorkspaceMount] = (),
    ) -> None:
        if policy.virtual_mode is not True:
            raise WorkspaceSecurityError("agent workspace requires virtual_mode=True")
        self._root_fd = execution_fd
        _validate_private_directory(self._root_fd)
        by_name: dict[str, WorkspaceMount] = {}
        for mount in mounts:
            if not _MOUNT_SEGMENT.fullmatch(mount.name) or mount.name in _LAYOUT:
                raise WorkspaceConfigurationError("mount name is reserved or malformed")
            if mount.name in by_name:
                raise WorkspaceConfigurationError("duplicate mount name")
            versioned = mount.mode == "versioned"
            if versioned != (mount.writer is not None) or versioned != (mount.reopen is not None):
                # Both halves or neither: a versioned mount with no writer would silently fall
                # through to a filesystem write on somebody else's tree, and a writer on a
                # read-only mount would be a promise nothing keeps.
                raise WorkspaceConfigurationError(
                    "a versioned mount carries its writer and reopen, and nothing else does"
                )
            _validate_private_directory(mount.directory_fd)
            by_name[mount.name] = mount
        self._mounts: dict[str, WorkspaceMount] = by_name
        self._identity = identity
        self._policy = policy
        self._artifact_sink = artifact_sink
        self._thread_lock = threading.RLock()
        self._snapshot_lock = asyncio.Lock()
        self._closed = False
        self._outputs_snapshotted = False
        self._snapshot_refs: tuple[ArtifactRef, ...] = ()
        self._written_documents: list[VersionedWriteOutcome] = []

    @property
    def workspace_root_id(self) -> str:
        return self._identity.workspace_root_id

    @property
    def policy(self) -> WorkspacePolicy:
        """The profile's workspace contract this backend enforces, read-only."""

        return self._policy

    @property
    def written_documents(self) -> tuple[VersionedWriteOutcome, ...]:
        """Every document version this turn's writes created, in the order they were taken.

        A file write into a versioned mount is a durable, human-visible event, so the turn needs
        to be able to say what it did — which document, at which version — without re-reading the
        store and guessing which rows were its own.
        """

        return tuple(self._written_documents)

    @property
    def outputs_snapshotted(self) -> bool:
        return self._outputs_snapshotted

    def close(self) -> None:
        with self._thread_lock:
            if self._closed:
                return
            # Flip first: a re-entrant or racing close must never double-close a descriptor
            # number that the kernel may already have handed back out.
            self._closed = True
            for directory_fd in dict.fromkeys(
                [self._root_fd, *(mount.directory_fd for mount in self._mounts.values())]
            ):
                with suppress(OSError):
                    os.close(directory_fd)

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

    def _mount_for(self, logical: str) -> WorkspaceMount | None:
        return self._mounts.get(logical.partition("/")[0])

    def _resolve(
        self,
        logical: str,
        *,
        allow_mount_root: bool = False,
    ) -> tuple[int, str, WorkspaceMount | None]:
        """Return (root fd, path relative to that root, the mount or None for the thread root)."""

        head, _, rest = logical.partition("/")
        mount = self._mounts.get(head)
        if mount is None:
            return self._root_fd, logical, None
        if not rest:
            if allow_mount_root:
                return mount.directory_fd, "", mount
            raise WorkspaceSecurityError("a mount root is a directory, not a file")
        return mount.directory_fd, rest, mount

    def _validate_path(
        self,
        path: str,
        *,
        write: bool,
        trusted: Sequence[str] | None = None,
    ) -> str:
        """Turn a caller's path into a logical one the policy actually permits.

        ``trusted`` names the prefixes a *platform* write may use in place of the policy's
        ``writable_prefixes``.  It is how the runtime puts bytes somewhere the model may read but
        never write — materialized resources before the turn, a spilled read during it — without
        widening by one byte the authority the model itself holds.  Everything else still binds:
        the folder must be readable, the extension allowed, and no mount may take such a write.
        """

        try:
            logical = normalize_virtual_path(path)
        except ValueError as exc:
            raise WorkspaceSecurityError(str(exc)) from exc
        readable = self._policy.readable_prefixes
        if not _is_under(logical, readable):
            raise WorkspaceSecurityError("path is outside the readable workspace authority")
        if write:
            mount = self._mount_for(logical)
            if mount is not None:
                if trusted is not None:
                    raise WorkspaceSecurityError("a mount cannot hold a trusted platform write")
                if mount.mode == "read_only":
                    raise WorkspaceSecurityError("path is inside a read-only mount")
                # A versioned mount is writable, but by its writer, never by this process; the
                # prefix still has to be one the policy grants, so the authority check below
                # stays in force for it exactly as for a read_write mount.
            prefixes = self._policy.writable_prefixes if trusted is None else trusted
            if not _is_under(logical, prefixes):
                raise WorkspaceSecurityError("path is outside the writable workspace authority")
            if trusted is None and self._outputs_snapshotted and _is_under(logical, ("outputs",)):
                raise WorkspaceConflict("snapshotted outputs are immutable")
            suffix = PurePosixPath(logical).suffix.lower()
            if suffix not in self._policy.allowed_extensions:
                raise WorkspaceSecurityError("file type is not allowed in the agent workspace")
        return logical

    @contextmanager
    def _parent_fd(self, logical: str, *, create: bool) -> Iterator[tuple[int, str]]:
        root_fd, relative, _mount = self._resolve(logical)
        parts = relative.split("/")
        current = os.dup(root_fd)
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
        root_fd, relative, mount = (
            self._resolve(prefix, allow_mount_root=True) if prefix else (self._root_fd, "", None)
        )
        start_fd = os.dup(root_fd)
        try:
            if relative:
                components = relative.split("/")
                for index, component in enumerate(components):
                    if index == len(components) - 1:
                        leaf = os.stat(component, dir_fd=start_fd, follow_symlinks=False)
                        if not stat.S_ISDIR(leaf.st_mode):
                            # The prefix names one file (a grep or glob scoped to a file): list
                            # just it, under the same checks a walk applies to every file.
                            _validate_regular_file(leaf)
                            named = relative if mount is None else f"{mount.name}/{relative}"
                            return [(named, leaf.st_size, leaf.st_mode)]
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

            walk(start_fd, relative)
            if mount is None:
                return files
            # A mount's paths are model-visible only under its reserved virtual segment.
            return [(f"{mount.name}/{path}", size, mode) for path, size, mode in files]
        except FileNotFoundError:
            return []
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("workspace tree contains an unsafe entry") from exc
        finally:
            os.close(start_fd)

    def _quota_files(self) -> list[tuple[str, int, int]]:
        """Every file the one policy quota governs: the thread root plus writable mounts.

        A read-only mount is readable but never charged — nothing this workspace does can
        change its size, so counting it would spend the agent's budget on someone else's bytes.
        A versioned mount is spared for the same reason: its bytes are the document store's,
        and its writes are governed by the writer's own rules, not by this workspace's quota.
        """

        files = self._walk_files()
        for mount in self._mounts.values():
            if mount.mode == "read_write":
                files.extend(self._walk_files(prefix=mount.name))
        return files

    def _quota_before_write(
        self,
        *,
        byte_count: int,
        replacing_size: int = 0,
        adds_file: bool,
    ) -> None:
        if byte_count > self._policy.max_file_bytes:
            raise WorkspaceQuotaExceeded("file exceeds the per-file workspace quota")
        files = self._quota_files()
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
        mount = self._mount_for(logical)
        if mount is not None and mount.mode == "versioned":
            with self._filesystem_lock(exclusive=True):
                return self._versioned_write(logical, mount, content)
        return self._create_file(logical, content.encode("utf-8"), read_only=False)

    def edit_text_sync(self, path: str, *, old: str, new: str) -> WorkspaceEntry:
        logical = self._validate_path(path, write=True)
        mount = self._mount_for(logical)
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
            edited = original.replace(old, new, 1)
            if mount is not None and mount.mode == "versioned":
                # An edit of a document is a whole new version of it: the same single-occurrence
                # rule decides *what* the new text is, and the writer decides whether it lands.
                # The read and the write stay under one lock for the same reason the thread
                # root's edit does: two concurrent edits must not each win half of the result.
                return self._versioned_write(logical, mount, edited)
            self._replace_file_unlocked(
                logical,
                edited.encode("utf-8"),
                old_size=metadata.st_size,
            )
            return self._entry(logical)

    def _versioned_write(
        self,
        logical: str,
        mount: WorkspaceMount,
        content: str,
    ) -> WorkspaceEntry:
        """Hand one write to the mount's writer, then re-read the tree it produced.

        Caller holds the exclusive filesystem lock. Three things happen in order and none of them
        is optional: the writer takes the write against the version the model read (a disagreement
        is a refusal, surfaced to the model as a conflict it can act on); the refreshed
        ``path → version`` map replaces the mount's, so the *next* write in this turn carries the
        version this one just created; and the mount's descriptor is swapped for one on the new
        generation, so the very next read shows what was written rather than the tree the turn
        opened with. The old descriptor is closed here, under the exclusive lock, which is the one
        moment no reader can be inside the tree.

        A failure after the write has landed is reported as a conflict, not a success: the bytes
        are durable but the view is stale, and the honest thing to tell the model is that it must
        read again.
        """

        writer, reopen = mount.writer, mount.reopen
        if writer is None or reopen is None:
            raise WorkspaceConfigurationError("a versioned mount has no writer")
        relative = logical[len(mount.name) + 1 :]
        try:
            outcome = writer.write(
                path=relative,
                content=content,
                expected_version=mount.versions.get(relative),
            )
        except VersionedWriteRefused as exc:
            raise WorkspaceConflict(f"{exc.code}: {exc.message}") from exc
        self._written_documents.append(outcome)
        try:
            versions = writer.refresh()
            directory_fd = reopen()
        except Exception as exc:
            raise WorkspaceConflict(
                f"{outcome.path} was written at version {outcome.version} "
                f"but the refreshed library could not be opened: {exc}"
            ) from exc
        # The filesystem lock already holds the re-entrant thread lock; taking it again states
        # that the mount table is only ever mutated under it.
        with self._thread_lock:
            current = self._mounts[mount.name]
            self._mounts[mount.name] = dataclass_replace(
                current,
                directory_fd=directory_fd,
                versions=MappingProxyType(dict(versions)),
            )
            with suppress(OSError):
                os.close(current.directory_fd)
        return self._entry(logical)

    def write_spill(self, operation_id: str, data: bytes) -> str:
        """Park one oversized governed result in ``reads/`` and return the path to read it at.

        This is the escape hatch for a result that will not fit in its receipt.  It is a trusted
        write — ``reads/`` is in the model's readable prefixes and in nobody's writable ones — so
        it goes around ``writable_prefixes`` the way a materialized resource does, and around
        nothing else: the quota still counts these bytes, the install is still the atomic
        create-then-link, and a mount still cannot be the target.

        Re-running the same operation (a replay, a resumed turn) rewrites its own file rather than
        colliding with it.  The path it returns is the one the model passes to ``read_file``.
        """

        if not _SPILL_SEGMENT.fullmatch(operation_id):
            raise WorkspaceSecurityError("a spill is named by a single safe operation segment")
        logical = self._validate_path(
            f"{_SPILL_PREFIXES[0]}/{operation_id}.json",
            write=True,
            trusted=_SPILL_PREFIXES,
        )
        try:
            return self._create_file(logical, data, read_only=False).path
        except WorkspaceConflict:
            # The same operation spilled before. Its bytes are this operation's bytes either way,
            # so the honest answer is to replace them, not to fail a read that has already run.
            with self._filesystem_lock(exclusive=True):
                file_fd, metadata = self._open_file(logical)
                os.close(file_fd)
                self._replace_file_unlocked(logical, data, old_size=metadata.st_size)
            return logical

    def materialize_bytes(self, path: str, data: bytes) -> WorkspaceEntry:
        """Trusted pre-model write into a read-only resource/context/input prefix."""

        logical = self._validate_path(path, write=True, trusted=_MATERIALIZED_PREFIXES)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceSecurityError("materialized agent resources must be UTF-8 text") from exc
        return self._create_file(logical, data, read_only=True)

    def freeze_materialized_trees(self) -> None:
        with self._filesystem_lock(exclusive=True):
            for prefix in _MATERIALIZED_PREFIXES:
                self._freeze_tree(prefix)

    def reset_materialized_trees(self) -> None:
        """Empty the three trusted trees so this turn can write its own pinned bytes.

        The thread directory persists across turns, so last turn's resources, inputs and
        context are still frozen on disk. Resetting restores owner-write and removes every
        file and subdirectory below the three prefixes, leaving the folders themselves in
        place and writable. ``scratch``/``reads``/``work``/``outputs`` are never touched.
        """

        with self._filesystem_lock(exclusive=True):
            for prefix in _MATERIALIZED_PREFIXES:
                self._reset_tree(prefix)

    def _reset_tree(self, name: str) -> None:
        """Unfreeze and empty one top-level folder, keeping the folder itself at 0700."""

        try:
            metadata = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
        except FileNotFoundError:
            os.mkdir(name, _DIRECTORY_MODE, dir_fd=self._root_fd)
            return
        except OSError as exc:
            raise WorkspaceSecurityError("workspace tree could not be reset") from exc
        if not stat.S_ISDIR(metadata.st_mode):
            raise WorkspaceSecurityError("workspace tree is not a directory")
        try:
            # O_NOFOLLOW | O_DIRECTORY refuses a swapped symlink; the frozen 0500 mode is
            # restored top-down so the children below it can be unlinked.
            directory_fd = os.open(name, _DIR_FLAGS, dir_fd=self._root_fd)
            try:
                os.fchmod(directory_fd, _DIRECTORY_MODE)
                _validate_private_directory(directory_fd)
                self._empty_directory(directory_fd)
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("workspace tree could not be reset") from exc

    @classmethod
    def _empty_directory(cls, directory_fd: int) -> None:
        """Remove every entry below one already-writable directory, refusing odd entries."""

        for child in os.listdir(directory_fd):
            child_metadata = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(child_metadata.st_mode):
                child_fd = os.open(child, _DIR_FLAGS, dir_fd=directory_fd)
                try:
                    os.fchmod(child_fd, _DIRECTORY_MODE)
                    cls._empty_directory(child_fd)
                finally:
                    os.close(child_fd)
                os.rmdir(child, dir_fd=directory_fd)
            elif stat.S_ISREG(child_metadata.st_mode):
                os.unlink(child, dir_fd=directory_fd)
            else:
                raise WorkspaceSecurityError("workspace reset found a link or special file")

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
            if not logical_prefix:
                # Every mount is readable, so the root listing spans them all.
                for mount in self._mounts.values():
                    files.extend(self._walk_files(prefix=mount.name))
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
            files = self._quota_files()
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

    async def snapshot_outputs(self, *, empty_after: bool = False) -> Sequence[ArtifactRef]:
        """Persist ``outputs/`` durably, optionally emptying it for the thread's next turn.

        With ``empty_after``, the folder itself survives — writable and empty — while the
        snapshot refs stay this turn's durable answer for the single-flight replay.
        """

        async with self._snapshot_lock:
            if self._outputs_snapshotted:
                return self._snapshot_refs
            with self._filesystem_lock(exclusive=True):
                self._validate_current_quota(self._quota_files())
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
            if empty_after:
                # Only after every byte is durable: the folder is emptied, never removed,
                # and nothing outside outputs/ is touched.
                with self._filesystem_lock(exclusive=True):
                    self._reset_tree("outputs")
            return self._snapshot_refs

    # --- deepagents BackendProtocol compatibility -----------------------------------------

    @staticmethod
    def _error(exc: Exception) -> str:
        if isinstance(exc, WorkspaceQuotaExceeded):
            return f"quota_exceeded: {exc}"
        if isinstance(exc, WorkspaceConflict):
            return f"conflict: {exc}"
        return f"permission_denied: {exc}"

    def _mount_directory_entries(self) -> list[FileInfo]:
        return [{"path": name, "is_dir": True, "size": 0} for name in sorted(self._mounts)]

    def ls(self, path: str) -> LsResult:
        try:
            logical = self._framework_path(path, allow_root=True)
            entries = self.list_entries_sync(logical)
            result: list[FileInfo] = [
                {"path": item.path, "is_dir": False, "size": item.byte_count} for item in entries
            ]
            if not logical:
                result = [*self._mount_directory_entries(), *result]
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
            if not logical:
                matches.extend(
                    entry
                    for entry in self._mount_directory_entries()
                    if fnmatch.fnmatch(entry["path"], pattern)
                )
            for item in entries:
                if logical and item.path == logical:
                    # ``path`` named one file: match the pattern against its own name.
                    relative = logical.rsplit("/", 1)[-1]
                else:
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
            if entry.get("is_dir"):
                # A mount root matches a bare glob but has no bytes to search.
                continue
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


@dataclass(frozen=True, slots=True)
class _ActiveThread:
    """The single live lease a thread may have, and what it was opened with."""

    backend: AnchoredAgentWorkspaceBackend
    execution_id: ExecutionId
    mounts: MountRequest


def _workspace_root_id(
    workspace_segment: str,
    project_segment: str,
    thread_segment: str,
) -> str:
    """The opaque, model-safe root id. It names the thread, so it is stable across turns."""

    digest = hashlib.sha256(
        f"{workspace_segment}\0{project_segment}\0{thread_segment}".encode()
    ).hexdigest()
    return f"awr_{digest}"


class AgentWorkspaceFactory:
    """Open, hold and remove one persistent workspace per chat thread below a prepared root.

    The layout is ``<root>/<workspace>/projects/<project>/threads/<thread>/``. A thread
    directory is created once and reopened by every later turn of that thread, so the agent's
    ``scratch/`` and ``reads/`` folders survive between turns. At most one lease is live per
    thread at a time, matching the one-turn-per-thread queue.
    """

    def __init__(
        self,
        *,
        prepared_root: PreparedWorkspaceRoot,
        artifact_sink: AgentArtifactSink,
    ) -> None:
        self._root_fd = os.open(prepared_root.path, _DIR_FLAGS)
        _validate_private_directory(self._root_fd)
        self._root_path = prepared_root.path
        self._artifact_sink = artifact_sink
        self._lock = threading.RLock()
        self._closed = False
        # One live lease per thread: the key is ``(workspace, project, thread)``.
        self._active: dict[tuple[str, str, str], _ActiveThread] = {}

    @property
    def root_path(self) -> Path:
        """The prepared root on the host. Never shown to a model; used to bind-mount a sandbox."""

        return self._root_path

    def project_host_path(self, workspace_id: str, project_id: str) -> Path:
        """``<root>/<ws>/projects/<project>`` on the host, from validated segments only.

        The descriptor-walking accessors above are the way *this* process reaches the tree. A
        container runtime cannot be handed a descriptor, so it gets the path — built from the
        same validated segments, so it names the same directory and can name no other.
        """

        return (
            self._root_path
            / validate_workspace_segment(workspace_id, label="workspace_id")
            / PROJECTS_DIR
            / validate_workspace_segment(project_id, label="project_id")
        )

    def thread_host_path(self, workspace_id: str, project_id: str, thread_id: str) -> Path:
        """``<root>/<ws>/projects/<project>/threads/<thread>`` on the host."""

        return (
            self.project_host_path(workspace_id, project_id)
            / THREADS_DIR
            / validate_workspace_segment(thread_id, label="thread_id")
        )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                for active in tuple(self._active.values()):
                    active.backend.close()
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
                    # A scope level legitimately holds a frozen (0500) library tree beside its
                    # 0700 working subdirectories — exactly the allowance `_audit_thread_root`
                    # already makes for a frozen top-level entry. Every other mode is refused.
                    if stat.S_IMODE(os.fstat(child_fd).st_mode) not in {
                        _DIRECTORY_MODE,
                        _READ_ONLY_DIRECTORY_MODE,
                    }:
                        raise WorkspaceSecurityError(
                            "workspace scope directory must have mode 0700 or 0500"
                        )
                finally:
                    os.close(child_fd)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("workspace scope directory audit failed") from exc

    @classmethod
    def ensure_child_directory(cls, parent_fd: int, segment: str) -> int:
        """Ensure one private 0700 child below an already-anchored parent descriptor.

        The single seam a library materializer uses to nest one level (``brand/``, then
        ``brand/<brand>/``) before writing a :class:`~clue_agents.library_tree.LibraryTree`
        under it. Only the child itself is audited — its children are the frozen 0500
        generations the materializer installs. The caller owns and closes the descriptor.
        """

        return cls._ensure_directory(
            parent_fd, validate_workspace_segment(segment, label="directory segment")
        )

    def library_parent_fd(self, workspace_id: str) -> int:
        """Ensure ``<ws>/library`` and return its descriptor. The caller owns and closes it.

        This is where the workspace-wide libraries (today: ``brand/<brand>/<version>``) are
        materialized, beside — never inside — any thread workspace.
        """

        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        with self._root_lock():
            workspace_fd = self._ensure_directory(self._root_fd, workspace_segment)
            try:
                self._audit_scope_directories(workspace_fd)
                library_fd = self._ensure_directory(workspace_fd, LIBRARY_DIR)
            finally:
                os.close(workspace_fd)
            try:
                self._audit_scope_directories(library_fd)
            except BaseException:
                os.close(library_fd)
                raise
            return library_fd

    def project_parent_fd(self, workspace_id: str, project_id: str) -> int:
        """Ensure ``<ws>/projects/<project>`` and return its descriptor.

        The project's own ``library`` tree is written directly below it, beside ``threads``.
        The caller owns and closes the descriptor.
        """

        chain = (
            validate_workspace_segment(workspace_id, label="workspace_id"),
            PROJECTS_DIR,
            validate_workspace_segment(project_id, label="project_id"),
        )
        with self._root_lock():
            parent_fd = self._root_fd
            opened: list[int] = []
            try:
                for segment in chain:
                    child_fd = self._ensure_directory(parent_fd, segment)
                    opened.append(child_fd)
                    self._audit_scope_directories(child_fd)
                    parent_fd = child_fd
                return opened.pop()
            finally:
                for descriptor in opened:
                    os.close(descriptor)

    def remove_project_tree(self, workspace_id: str, project_id: str, name: str) -> None:
        """Remove one named tree below ``<ws>/projects/<project>/``. Idempotent.

        The counterpart of a turn materializing its pinned generation beside the project's
        library: what one turn writes there, that turn removes, so no per-turn state outlives the
        turn. ``name`` is validated as a single segment and the project's own ``library`` is
        refused outright — that tree belongs to every thread of the project and is nobody's turn
        to delete, and an idempotent "remove whatever you were given" would make deleting it one
        typo away.

        ``LibraryTree`` keeps a superseded generation as ``<name>.old-<pid>`` and a crashed build
        as ``<name>.next-<pid>``, reclaiming both at the *next* replace of that name — which for a
        per-turn tree never comes. So this removes the tree and its own residue together;
        otherwise a turn killed between materializing and this call would leave a directory behind
        forever.
        """

        segment = validate_workspace_segment(name, label="project tree name")
        if segment == LIBRARY_DIR:
            raise WorkspaceConfigurationError("the project library is not a per-turn tree")
        # The descriptor is taken first and the lock second, never nested: ``_root_lock`` is an
        # ``flock`` on one shared descriptor, so an inner release would drop the outer holder's
        # lock too.
        parent_fd = self.project_parent_fd(workspace_id, project_id)
        try:
            with self._root_lock():
                for entry in os.listdir(parent_fd):
                    if entry == segment or entry.startswith(f"{segment}."):
                        self._remove_tree(parent_fd, entry)
        finally:
            os.close(parent_fd)

    def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        execution_id: ExecutionId,
        policy: WorkspacePolicy,
        mounts: MountRequest = _NO_MOUNTS,
        artifact_sink: AgentArtifactSink | None = None,
    ) -> AgentWorkspaceLease:
        """Open the thread's persistent workspace, creating whatever part of it is absent.

        The thread directory outlives every turn, so an existing one is reopened (and audited),
        never refused. What is refused is a second live lease over the same thread.
        """

        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        project_segment = validate_workspace_segment(project_id, label="project_id")
        thread_segment = validate_workspace_segment(thread_id, label="thread_id")
        validate_workspace_segment(str(execution_id), label="execution_id")
        key = (workspace_segment, project_segment, thread_segment)
        identity = WorkspaceIdentity(
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            execution_id=execution_id,
            workspace_root_id=_workspace_root_id(
                workspace_segment,
                project_segment,
                thread_segment,
            ),
            retention_class=policy.retention_class,
        )
        with self._lock:
            if key in self._active:
                raise WorkspaceConflict("this thread already has a live workspace lease")

        with self._root_lock():
            thread_fd = self._open_thread_root(
                workspace_segment=workspace_segment,
                project_segment=project_segment,
                thread_segment=thread_segment,
            )
            try:
                mount_table = self._open_mounts(
                    request=mounts,
                    workspace_segment=workspace_segment,
                    project_segment=project_segment,
                )
            except BaseException:
                os.close(thread_fd)
                raise

        try:
            backend = AnchoredAgentWorkspaceBackend(
                execution_fd=thread_fd,
                identity=identity,
                policy=policy,
                artifact_sink=artifact_sink or self._artifact_sink,
                mounts=mount_table,
            )
        except BaseException:
            for descriptor in (thread_fd, *(mount.directory_fd for mount in mount_table)):
                with suppress(OSError):
                    os.close(descriptor)
            raise

        with self._lock:
            if key in self._active:
                backend.close()
                raise WorkspaceConflict("this thread already has a live workspace lease")
            self._active[key] = _ActiveThread(
                backend=backend,
                execution_id=execution_id,
                mounts=mounts,
            )
        return self._lease(
            identity=identity,
            backend=backend,
            workspace_segment=workspace_segment,
            project_segment=project_segment,
            thread_segment=thread_segment,
        )

    def acquire(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        execution_id: ExecutionId,
        policy: WorkspacePolicy,
        mounts: MountRequest = _NO_MOUNTS,
        artifact_sink: AgentArtifactSink | None = None,
    ) -> AgentWorkspaceLease:
        """Take this turn's lease over the thread workspace.

        The thread directory is created if absent and securely reopened if present. The live
        lease is keyed by thread: re-acquiring for the *same* execution returns a lease over the
        same backend (in-process crash resume), while a *different* execution while one is live
        is a conflict, matching the one-turn-per-thread queue.
        """

        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        project_segment = validate_workspace_segment(project_id, label="project_id")
        thread_segment = validate_workspace_segment(thread_id, label="thread_id")
        key = (workspace_segment, project_segment, thread_segment)
        with self._lock:
            active = self._active.get(key)
        if active is None:
            return self.create(
                workspace_id=workspace_id,
                project_id=project_id,
                thread_id=thread_id,
                execution_id=execution_id,
                policy=policy,
                mounts=mounts,
                artifact_sink=artifact_sink,
            )
        if active.execution_id != execution_id:
            raise WorkspaceConflict("another execution holds this thread's live workspace lease")
        if active.mounts != mounts:
            raise WorkspaceConflict("the live workspace lease was opened with other mounts")
        backend = active.backend
        if artifact_sink is not None and backend._artifact_sink is not artifact_sink:
            raise WorkspaceConflict("the live workspace lease uses another artifact authority")
        backend.require_policy(policy)
        return self._lease(
            identity=WorkspaceIdentity(
                workspace_id=workspace_id,
                project_id=project_id,
                thread_id=thread_id,
                execution_id=execution_id,
                workspace_root_id=backend.workspace_root_id,
                retention_class=policy.retention_class,
            ),
            backend=backend,
            workspace_segment=workspace_segment,
            project_segment=project_segment,
            thread_segment=thread_segment,
        )

    def _lease(
        self,
        *,
        identity: WorkspaceIdentity,
        backend: AnchoredAgentWorkspaceBackend,
        workspace_segment: str,
        project_segment: str,
        thread_segment: str,
    ) -> AgentWorkspaceLease:
        """Hand out one turn's lease, with its frozen state read from the durable trees."""

        lease = AgentWorkspaceLease(
            identity=identity,
            backend=backend,
            workspace_segment=workspace_segment,
            project_segment=project_segment,
            thread_segment=thread_segment,
            factory=self,
        )
        try:
            frozen = backend.materialized_trees_frozen()
        except WorkspaceSecurityError:
            # A crash between the three freezes leaves a partial tree: not this turn's truth,
            # so the lease stays unfrozen and the materializer's rebuild repairs it.
            frozen = False
        if frozen:
            lease.restore_resources_frozen()
        return lease

    def _open_thread_root(
        self,
        *,
        workspace_segment: str,
        project_segment: str,
        thread_segment: str,
    ) -> int:
        """Ensure ``<ws>/projects/<project>/threads/<thread>`` and return its descriptor.

        Caller holds the root lock and owns the returned descriptor.
        """

        chain = (workspace_segment, PROJECTS_DIR, project_segment, THREADS_DIR)
        parent_fd = self._root_fd
        opened: list[int] = []
        try:
            for segment in chain:
                child_fd = self._ensure_directory(parent_fd, segment)
                opened.append(child_fd)
                self._audit_scope_directories(child_fd)
                parent_fd = child_fd
            thread_fd = self._ensure_directory(parent_fd, thread_segment)
            try:
                existing = set(os.listdir(thread_fd))
                for directory in _LAYOUT:
                    if directory not in existing:
                        os.mkdir(directory, _DIRECTORY_MODE, dir_fd=thread_fd)
                self._audit_thread_root(thread_fd)
                os.fsync(thread_fd)
            except BaseException:
                os.close(thread_fd)
                raise
            return thread_fd
        finally:
            for descriptor in opened:
                os.close(descriptor)

    @staticmethod
    def _audit_thread_root(thread_fd: int) -> None:
        """Reject any top-level entry a thread workspace is not allowed to hold."""

        entries = set(os.listdir(thread_fd))
        if entries != set(_LAYOUT):
            raise WorkspaceSecurityError("thread root has an unexpected top-level layout")
        for entry in entries:
            metadata = os.stat(entry, dir_fd=thread_fd, follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) not in {
                _DIRECTORY_MODE,
                _READ_ONLY_DIRECTORY_MODE,
            }:
                raise WorkspaceSecurityError("thread root contains an unsafe top-level entry")

    def _open_mounts(
        self,
        *,
        request: MountRequest,
        workspace_segment: str,
        project_segment: str,
    ) -> tuple[WorkspaceMount, ...]:
        """Open the requested durable libraries read-only. Caller holds the root lock."""

        opened: list[WorkspaceMount] = []
        try:
            if request.brand is not None:
                brand_id, knowledge_version = request.brand
                directory_fd = self._open_library(
                    (
                        workspace_segment,
                        LIBRARY_DIR,
                        "brand",
                        validate_workspace_segment(brand_id, label="brand_id"),
                        validate_workspace_segment(knowledge_version, label="brand_version"),
                    ),
                    name="brand",
                )
                opened.append(
                    WorkspaceMount(name="brand", directory_fd=directory_fd, mode="read_only")
                )
            if request.project_library:
                directory_fd = self._open_library(
                    (
                        workspace_segment,
                        PROJECTS_DIR,
                        project_segment,
                        validate_workspace_segment(
                            request.project_library_name, label="project_library_name"
                        ),
                    ),
                    name="project",
                )
                if request.project_writer is None:
                    opened.append(
                        WorkspaceMount(name="project", directory_fd=directory_fd, mode="read_only")
                    )
                else:
                    opened.append(
                        WorkspaceMount(
                            name="project",
                            directory_fd=directory_fd,
                            mode="versioned",
                            writer=request.project_writer,
                            versions=_mounted_versions(directory_fd, mount_name="project"),
                            reopen=self._project_library_reopen(workspace_segment, project_segment),
                        )
                    )
            if request.attachments:
                # Unlike a library, an absent attachments directory is not a misconfiguration:
                # it is a project with no uploads. The mount is then simply not there, and the
                # model's own ``ls`` says so.
                try:
                    directory_fd = self._open_library(
                        (workspace_segment, PROJECTS_DIR, project_segment, ATTACHMENTS_DIR),
                        name="attachments",
                    )
                except WorkspaceConfigurationError:
                    pass
                else:
                    opened.append(
                        WorkspaceMount(
                            name="attachments",
                            directory_fd=directory_fd,
                            mode="read_only",
                        )
                    )
        except BaseException:
            for mount in opened:
                with suppress(OSError):
                    os.close(mount.directory_fd)
            raise
        return tuple(opened)

    def _project_library_reopen(
        self,
        workspace_segment: str,
        project_segment: str,
    ) -> Callable[[], int]:
        """Build the callable a versioned ``project`` mount re-reads its tree through.

        It always opens the project's *shared* ``library``, whatever tree the mount was opened on.
        A turn pinned to a superseded generation reads that generation — but the moment it writes,
        the write lands in the live library, and what it must then see is the library, not the
        frozen snapshot it started from. The one honest view after a write is the current one.

        :class:`~clue_agents.library_tree.LibraryTree` is imported here rather than at module
        scope because it imports this module: the dependency runs one way, and this is the single
        place the backend needs to reach back the other.
        """

        def reopen() -> int:
            from clue_agents.library_tree import LibraryTree

            parent_fd = self.project_parent_fd(workspace_segment, project_segment)
            try:
                return LibraryTree(parent_fd=parent_fd, name=LIBRARY_DIR).open_fd()
            finally:
                os.close(parent_fd)

        return reopen

    def _open_library(self, segments: Sequence[str], *, name: str) -> int:
        """Walk one anchored, symlink-free chain below the root and keep only its leaf open."""

        parent_fd = self._root_fd
        opened: list[int] = []
        try:
            for segment in segments:
                try:
                    child_fd = os.open(segment, _DIR_FLAGS, dir_fd=parent_fd)
                except FileNotFoundError:
                    raise WorkspaceConfigurationError(
                        f"{name} library is not materialized"
                    ) from None
                except OSError as exc:
                    raise WorkspaceSecurityError("workspace library directory is unsafe") from exc
                opened.append(child_fd)
                _validate_private_directory(child_fd)
                parent_fd = child_fd
            return opened.pop()
        finally:
            for descriptor in opened:
                os.close(descriptor)

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

    @staticmethod
    def _rmdir_if_empty(name: str, parent_fd: int) -> bool:
        try:
            os.rmdir(name, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                raise
            return False
        return True

    def _delete_thread(
        self,
        workspace_segment: str,
        project_segment: str,
        thread_segment: str,
    ) -> bool:
        """Remove one thread directory and every scope level it leaves empty behind it."""

        chain = (workspace_segment, PROJECTS_DIR, project_segment, THREADS_DIR)
        with self._root_lock():
            parent_fd = self._root_fd
            parents = [self._root_fd]
            opened: list[int] = []
            try:
                for segment in chain:
                    try:
                        child_fd = os.open(segment, _DIR_FLAGS, dir_fd=parent_fd)
                    except FileNotFoundError:
                        return False
                    opened.append(child_fd)
                    parents.append(child_fd)
                    parent_fd = child_fd
                try:
                    os.stat(thread_segment, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return False
                self._remove_tree(parent_fd, thread_segment)
                for segment, level_fd in zip(
                    reversed(chain),
                    reversed(parents[:-1]),
                    strict=True,
                ):
                    if not self._rmdir_if_empty(segment, level_fd):
                        break
            finally:
                for descriptor in opened:
                    os.close(descriptor)
        return True

    def release(self, lease: AgentWorkspaceLease) -> None:
        """Drop this turn's lease and close its backend. Nothing on disk is removed."""

        key = (lease._workspace_segment, lease._project_segment, lease._thread_segment)
        with self._lock:
            active = self._active.get(key)
            if active is not None and active.backend is lease.backend:
                del self._active[key]
        lease.backend.close()

    def cleanup(self, lease: AgentWorkspaceLease) -> None:
        """End the turn's hold on the thread. Kept under its old name for the runtime wiring."""

        self.release(lease)

    def discard_failed_materialization(self, lease: AgentWorkspaceLease) -> None:
        """Release a lease whose materialization failed before the model ever ran.

        The thread workspace itself survives: the next turn's materialization resets and
        rewrites the trusted trees from its own pinned snapshot.
        """

        if not lease.materialization_failed or lease.resources_frozen:
            raise WorkspaceSecurityError(
                "only a pre-model materialization failure may be discarded without finalization"
            )
        self.release(lease)

    def purge_thread(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
    ) -> bool:
        """Remove one thread's persistent workspace. Idempotent; returns whether it existed.

        Any live backend this process holds for the thread is closed first so it cannot keep
        writing through an unlinked directory descriptor.
        """

        workspace_segment = validate_workspace_segment(workspace_id, label="workspace_id")
        project_segment = validate_workspace_segment(project_id, label="project_id")
        thread_segment = validate_workspace_segment(thread_id, label="thread_id")
        with self._lock:
            active = self._active.pop(
                (workspace_segment, project_segment, thread_segment),
                None,
            )
        if active is not None:
            active.backend.close()
        return self._delete_thread(workspace_segment, project_segment, thread_segment)

    def erase_for_privacy(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
    ) -> bool:
        """Privileged, idempotent DSAR deletion of a thread workspace.

        Unlike ordinary release this removes the bytes: retaining materialized personal data
        after an erasure request would be the unsafe outcome. Returns whether it existed.
        """

        return self.purge_thread(
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
        )

    def purge_terminal(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
    ) -> bool:
        """Remove a thread workspace after the caller verifies durable retention policy."""

        return self.purge_thread(
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
        )
