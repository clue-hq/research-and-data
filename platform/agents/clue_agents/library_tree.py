"""Atomically replaceable, read-only library trees under an anchored parent directory.

A library tree is a directory of already-verified bytes that agents *read* and never write:
the brand kit at ``<ws>/library/brand/<brand>/<version>/`` and the project library at
``<ws>/projects/<project>/library/``. It is built beside its final name, frozen (0500
directories, 0400 files), and moved into place with ``rename``, so a reader either sees the
whole previous generation or the whole new one — never a half-written tree.

Every host access here is rooted at the caller's already-open parent descriptor and every
component is opened with ``O_NOFOLLOW``, so nothing outside that parent can be reached or
followed. The primitives are deliberately the ones :mod:`clue_agents.workspace` already uses
(``_write_temp`` + ``link`` installs, ``_validate_private_directory``, ``_remove_tree``); they
are imported rather than re-implemented so the two writers can never drift apart.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Final

from clue_agents.contracts import normalize_virtual_path
from clue_agents.workspace import (
    _DIR_FLAGS,
    _DIRECTORY_MODE,
    _READ_FLAGS,
    _READ_ONLY_DIRECTORY_MODE,
    _READ_ONLY_FILE_MODE,
    AgentWorkspaceFactory,
    AnchoredAgentWorkspaceBackend,
    _read_all,
    _validate_private_directory,
)
from clue_agents.workspace_policy import (
    WorkspaceConfigurationError,
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceSecurityError,
    validate_workspace_segment,
)

__all__ = ["LibraryFile", "LibraryTree"]

#: A library holds only text an agent can read and quote. Anything else is refused at the door.
_ALLOWED_SUFFIXES: Final = (".md", ".json", ".txt", ".yaml")
#: Every tree carries its own manifest, and the manifest carries the digest of the tree.
_INDEX_NAME: Final = "index.json"
_DIGEST_KEY: Final = "library_sha256"

_write_temp: Final = AnchoredAgentWorkspaceBackend._write_temp
_remove_tree: Final = AgentWorkspaceFactory._remove_tree


@dataclass(frozen=True, slots=True)
class LibraryFile:
    """One file of a library generation.

    ``path`` is virtual and relative to the library root (``normalize_virtual_path``-clean);
    ``content`` is UTF-8 text bytes.
    """

    path: str
    content: bytes


def _validated_path(value: str) -> str:
    """Return one safe, relative library path, or refuse it loudly."""

    try:
        path = normalize_virtual_path(value)
    except (TypeError, ValueError) as exc:
        raise WorkspaceSecurityError("library file path is unsafe") from exc
    try:
        for segment in path.split("/"):
            validate_workspace_segment(segment, label="library path segment")
    except WorkspaceConfigurationError as exc:
        raise WorkspaceSecurityError("library file path segment is unsafe") from exc
    if not path.endswith(_ALLOWED_SUFFIXES):
        raise WorkspaceSecurityError("library files must be .md, .json, .txt or .yaml")
    return path


def _validated_files(files: Sequence[LibraryFile], digest: str) -> tuple[tuple[str, bytes], ...]:
    """Validate the whole generation before a single byte is written."""

    validated: dict[str, bytes] = {}
    for file in files:
        path = _validated_path(file.path)
        content = file.content
        if not isinstance(content, bytes | bytearray):
            raise WorkspaceSecurityError("library file content must be bytes")
        try:
            bytes(content).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceSecurityError("library file content must be UTF-8 text") from exc
        if path in validated:
            raise WorkspaceConflict("library generation contains a duplicate path")
        validated[path] = bytes(content)

    if not isinstance(digest, str) or not digest:
        raise WorkspaceConflict("library digest must be a non-empty string")
    index = validated.get(_INDEX_NAME)
    if index is None:
        raise WorkspaceConflict(f"library generation must include {_INDEX_NAME}")
    if _decode_index(index).get(_DIGEST_KEY) != digest:
        raise WorkspaceConflict("library index does not record the declared digest")
    return tuple(validated.items())


def _decode_index(data: bytes) -> dict[str, object]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorkspaceConflict("library index is not readable JSON") from exc
    if not isinstance(document, dict):
        raise WorkspaceConflict("library index is not a JSON object")
    return document


def _install_file(parent_fd: int, leaf: str, content: bytes) -> None:
    """Write one 0400 file by same-directory temporary plus atomic no-replace ``link``."""

    temporary, temp_fd = _write_temp(parent_fd, content)
    closed = False
    try:
        os.fchmod(temp_fd, _READ_ONLY_FILE_MODE)
        os.close(temp_fd)
        closed = True
        os.link(
            temporary,
            leaf,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
    finally:
        if not closed:
            with suppress(OSError):
                os.close(temp_fd)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_fd)


def _depth(relative: str) -> int:
    return 0 if not relative else relative.count("/") + 1


class LibraryTree:
    """One persistent read-only tree under an anchored parent directory, replaced atomically.

    ``replace`` builds the next generation in ``<name>.next-<pid>``, renames the live tree to
    ``<name>.old-<pid>`` and renames the new one into place. The superseded generation is
    *kept* until the following ``replace``, which removes every ``<name>.next-*`` and
    ``<name>.old-*`` leftover before it starts — one mechanism that reclaims both a crashed
    build and last generation's tree. The bound that buys: a turn holding a descriptor on the
    tree from one replace ago keeps reading its own consistent bytes; a tree two replaces old
    is gone.

    One writer at a time per tree. Residue reclamation is by name prefix, so two concurrent
    ``replace`` calls on the same tree would each discard the other's in-flight build; the
    caller serializes them (materialization is owned by one turn, under the factory's root
    lock). Readers need no lock at all — they hold descriptors, never names.

    The instance never owns ``parent_fd`` — the caller opens it and closes it.
    """

    __slots__ = ("_name", "_parent_fd")

    def __init__(self, *, parent_fd: int, name: str) -> None:
        try:
            self._name = validate_workspace_segment(name, label="library tree name")
        except WorkspaceConfigurationError as exc:
            raise WorkspaceSecurityError("library tree name is unsafe") from exc
        self._parent_fd = parent_fd

    @property
    def name(self) -> str:
        return self._name

    def current_digest(self) -> str | None:
        """The ``library_sha256`` recorded in ``<name>/index.json``, or None when absent."""

        document = self.read_index()
        if document is None:
            return None
        recorded = document.get(_DIGEST_KEY)
        if recorded is None:
            return None
        if not isinstance(recorded, str):
            raise WorkspaceConflict("library index digest is not a string")
        return recorded

    def read_index(self) -> dict[str, object] | None:
        """The installed ``<name>/index.json`` as a JSON object, or None when there is none.

        The whole manifest, for a caller that wants what the tree says about itself rather than
        only its digest — a library whose digest still matches is described entirely by the card
        it already carries, so nothing has to be recompiled to answer "what is in there".

        Audited exactly as :meth:`open_fd` audits the tree: the directory is private, the index is
        opened ``O_NOFOLLOW`` and must be a regular file. A tree that is absent, or that carries
        no index yet, is None; anything unsafe or unreadable is refused loudly.
        """

        try:
            tree_fd = os.open(self._name, _DIR_FLAGS, dir_fd=self._parent_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkspaceSecurityError("library tree is not a safe directory") from exc
        try:
            _validate_private_directory(tree_fd)
            try:
                file_fd = os.open(_INDEX_NAME, _READ_FLAGS, dir_fd=tree_fd)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise WorkspaceSecurityError("library index is a link or is unreadable") from exc
            try:
                if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                    raise WorkspaceSecurityError("library index is not a regular file")
                data = _read_all(file_fd)
            finally:
                os.close(file_fd)
        finally:
            os.close(tree_fd)

        return _decode_index(data)

    def replace(self, files: Sequence[LibraryFile], *, digest: str) -> None:
        """Install one whole generation, atomically, as a frozen read-only tree.

        Every path and byte is validated first, so a refused generation leaves the live tree
        exactly as it was. ``files`` must include ``index.json`` and ``digest`` must equal the
        ``library_sha256`` recorded inside it.
        """

        entries = _validated_files(files, digest)
        self._discard_residue()
        next_name = f"{self._name}.next-{os.getpid()}"
        try:
            os.mkdir(next_name, _DIRECTORY_MODE, dir_fd=self._parent_fd)
        except OSError as exc:
            raise WorkspaceSecurityError("library build directory could not be created") from exc
        try:
            self._build(next_name, entries)
            self._swap(next_name)
        except BaseException:
            # A failed build never becomes a served tree; the live generation is untouched.
            with suppress(OSError, WorkspaceError):
                _remove_tree(self._parent_fd, next_name)
            raise

    def open_fd(self) -> int:
        """An ``O_DIRECTORY|O_NOFOLLOW`` descriptor on the current tree, audited private.

        A tree that is writable, group/other-readable, or holds a link at its top level is
        refused rather than served. The caller owns the returned descriptor.
        """

        try:
            tree_fd = os.open(self._name, _DIR_FLAGS, dir_fd=self._parent_fd)
        except FileNotFoundError:
            raise WorkspaceConflict("library tree is not materialized") from None
        except OSError as exc:
            raise WorkspaceSecurityError("library tree is not a safe directory") from exc
        try:
            _validate_private_directory(tree_fd)
            if stat.S_IMODE(os.fstat(tree_fd).st_mode) != _READ_ONLY_DIRECTORY_MODE:
                raise WorkspaceSecurityError("a served library tree must be read-only")
            for entry in os.listdir(tree_fd):
                metadata = os.stat(entry, dir_fd=tree_fd, follow_symlinks=False)
                if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                    raise WorkspaceSecurityError("library tree holds a link or special file")
        except BaseException:
            os.close(tree_fd)
            raise
        return tree_fd

    # --- internals -------------------------------------------------------------------------

    def _discard_residue(self) -> None:
        """Refuse a hijacked tree name and reclaim the previous generation and crash residue."""

        try:
            metadata = os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise WorkspaceSecurityError("library tree is not a safe directory") from exc
        else:
            if not stat.S_ISDIR(metadata.st_mode):
                raise WorkspaceSecurityError("library tree name is taken by a non-directory")

        prefixes = (f"{self._name}.next-", f"{self._name}.old-")
        try:
            residue = [entry for entry in os.listdir(self._parent_fd) if entry.startswith(prefixes)]
            for entry in residue:
                leftover = os.stat(entry, dir_fd=self._parent_fd, follow_symlinks=False)
                if stat.S_ISDIR(leftover.st_mode):
                    _remove_tree(self._parent_fd, entry)
                else:
                    os.unlink(entry, dir_fd=self._parent_fd)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("library residue could not be reclaimed") from exc

    def _build(self, next_name: str, entries: Sequence[tuple[str, bytes]]) -> None:
        """Write and freeze the whole generation below ``next_name``."""

        try:
            root_fd = os.open(next_name, _DIR_FLAGS, dir_fd=self._parent_fd)
        except OSError as exc:
            raise WorkspaceSecurityError("library build directory is unsafe") from exc
        directories: dict[str, int] = {"": root_fd}
        try:
            for path, content in entries:
                head, _, leaf = path.rpartition("/")
                _install_file(self._directory_fd(directories, head), leaf, content)
            # Bottom-up: a directory is frozen only once nothing more will be created in it.
            for relative in sorted(directories, key=_depth, reverse=True):
                directory_fd = directories[relative]
                os.fsync(directory_fd)
                os.fchmod(directory_fd, _READ_ONLY_DIRECTORY_MODE)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceSecurityError("library generation could not be written") from exc
        finally:
            for directory_fd in directories.values():
                with suppress(OSError):
                    os.close(directory_fd)

    def _directory_fd(self, directories: dict[str, int], relative: str) -> int:
        """Create and cache one directory of the build, anchored at its own parent."""

        cached = directories.get(relative)
        if cached is not None:
            return cached
        head, _, leaf = relative.rpartition("/")
        parent_fd = self._directory_fd(directories, head)
        os.mkdir(leaf, _DIRECTORY_MODE, dir_fd=parent_fd)
        child_fd = os.open(leaf, _DIR_FLAGS, dir_fd=parent_fd)
        try:
            _validate_private_directory(child_fd)
        except BaseException:
            os.close(child_fd)
            raise
        directories[relative] = child_fd
        return child_fd

    def _swap(self, next_name: str) -> None:
        """Move the built generation into place, keeping the superseded one for its readers."""

        try:
            live = True
            try:
                os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                live = False
            if live:
                os.rename(
                    self._name,
                    f"{self._name}.old-{os.getpid()}",
                    src_dir_fd=self._parent_fd,
                    dst_dir_fd=self._parent_fd,
                )
            os.rename(
                next_name,
                self._name,
                src_dir_fd=self._parent_fd,
                dst_dir_fd=self._parent_fd,
            )
            os.fsync(self._parent_fd)
        except OSError as exc:
            raise WorkspaceSecurityError("library generation could not be installed") from exc
