"""Re-apply the profile's workspace policy to everything a sandboxed script left behind.

The container writes into the thread's ``scratch/``, ``work/`` and ``outputs/`` directories with
an ordinary kernel, not through :class:`~clue_agents.workspace.AgentWorkspace`. Nothing in the
sandbox enforces the file types, the per-file ceiling or the quota the model's own ``write_file``
answers to, so a script can leave a 2 GB ``.so``, a symlink out of the tree, or ten thousand
files. This module is the enforcement that runs the moment the container exits: the workspace the
next tool call sees is one ``write_file`` could have produced, plus the extra *output* formats the
sandbox exists to create (:data:`SANDBOX_OUTPUT_EXTENSIONS` — a script's job is to write the CSV
or the chart the file tools cannot).

Four things are removed, each reported with its reason so the tool can tell the model exactly
what happened to its files:

``not_a_regular_file``
    A symlink, fifo, socket or device. The real workspace backend's own walk *raises* on one of
    these, so leaving one in place breaks every later listing and quota check for this thread.
``extension_not_allowed``
    A suffix outside ``policy.allowed_extensions + SANDBOX_OUTPUT_EXTENSIONS`` (case-insensitive;
    a file with no suffix has no allowed extension).
``file_too_large``
    Over ``policy.max_file_bytes``.
``quota_exceeded``
    The tree is over ``policy.max_total_bytes`` or ``policy.max_file_count``; the newest-written
    files go first, and only files this run wrote or changed are ever candidates.

Two more things the container leaves behind that ``write_file`` never would, and the backend's
own walk refuses (``_validate_regular_file``): a file that is not *private*, and a hard link. A
script normally creates private files and directories: the runner uses the worker's UID/GID and
``umask 077``. Only modes explicitly changed by a script or copied from another file need repair
here (``0600`` / ``0700``); ordinary outputs need no ``chmod``. A file whose mode cannot be
normalised is removed as ``not_private``, and a hard-linked file as ``hard_linked``.

One reason beyond the four is unavoidable: ``atomic_write_residue``. The workspace backend treats
a ``.clue-tmp-*`` name as an interrupted atomic write and refuses to walk a tree containing one,
so a script that writes that name — deliberately or by copying the convention — would brick the
thread's workspace for every later turn. It is removed on the same grounds as the rest.

Directories are walked, never removed — except one with a ``.clue-tmp-*`` name, which goes with
everything in it for the same reason as the file — because ``write_file`` creates parent
directories, so a nested tree is legitimate workspace state. Symlinks are unlinked and never
traversed, so a link pointing out of the workspace cannot make the sweep delete anything outside
it.

Quotas here are read over the read-write directories as a set. That is narrower than the
workspace's own quota (which also charges the thread's other folders), and deliberately so: this
sweep's contract is that the tree the sandbox could touch is within policy when it is done, not
that it re-derives the backend's accounting.

Nothing here talks to Docker, the tool layer or the database, and every call blocks — the caller
(the ``run_python@1`` tool) is responsible for keeping it off the event loop, exactly as it does
for the run itself.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from clue_agents.contracts import WorkspacePolicy
from clue_agents.sandbox.workspaces import SandboxMounts

__all__ = [
    "SANDBOX_OUTPUT_EXTENSIONS",
    "SweepResult",
    "snapshot",
    "sweep",
]

#: The formats a script may produce that the model's own file tools may not. These are the point
#: of the sandbox — "make me a spreadsheet", "plot this" — and they are all inert data: no
#: executable, archive or source extension is on the list.
SANDBOX_OUTPUT_EXTENSIONS: Final = (".csv", ".xlsx", ".docx", ".pptx", ".pdf", ".png")

#: What the workspace backend demands of everything under the thread (``_validate_regular_file``
#: / ``_validate_private_directory``): private to the owner, never executable.
_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

#: :meth:`clue_agents.workspace.AgentWorkspace._walk_files` raises on any name with this prefix,
#: reading it as an interrupted atomic write. A sandbox-written one would poison the tree.
_ATOMIC_WRITE_PREFIX: Final = ".clue-tmp-"


@dataclass(frozen=True, slots=True)
class SweepResult:
    """What the run left in the workspace, and what the policy took back out."""

    #: ``(workspace-relative path, size)`` for every surviving file this run wrote or changed,
    #: sorted by path. Files the run did not touch are not an output of the run.
    kept: tuple[tuple[str, int], ...]
    #: ``(workspace-relative path, reason)`` for every entry removed, sorted by path.
    removed: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    path: str
    host: Path
    size: int
    mtime: float
    changed: bool


def snapshot(mounts: SandboxMounts) -> dict[str, tuple[int, float]]:
    """The before-picture: every regular file under the read-write dirs → ``(size, mtime)``.

    Taken immediately before the container starts. Comparing against it after is what tells the
    sweep which files are the *run's* — the only ones it reports as written, and the only ones it
    is willing to delete for quota.
    """

    return {
        path: (metadata.st_size, metadata.st_mtime)
        for path, _host, metadata in _walk(mounts)
        if stat.S_ISREG(metadata.st_mode)
    }


def sweep(mounts: SandboxMounts, *, before: Mapping[str, tuple[int, float]]) -> SweepResult:
    """Re-apply the policy to the read-write dirs and report what was kept and removed."""

    policy = mounts.policy
    allowed = {extension.lower() for extension in policy.allowed_extensions}
    allowed.update(SANDBOX_OUTPUT_EXTENSIONS)

    removed: list[tuple[str, str]] = _remove_residue_folders(mounts)
    survivors: list[_Entry] = []
    for path, host, metadata in _walk(mounts):
        reason = _disallowed_reason(
            path, metadata, allowed=allowed, max_bytes=policy.max_file_bytes
        )
        if reason is not None:
            os.unlink(host)
            removed.append((path, reason))
            continue
        if metadata.st_nlink != 1:
            os.unlink(host)
            removed.append((path, "hard_linked"))
            continue
        try:
            if stat.S_IMODE(metadata.st_mode) != _FILE_MODE:
                os.chmod(host, _FILE_MODE, follow_symlinks=False)
        except (OSError, NotImplementedError):
            # A mode this worker cannot set (a foreign owner on a Linux host) is a file the
            # backend's walk would refuse; the only honest state is its absence.
            os.unlink(host)
            removed.append((path, "not_private"))
            continue
        survivors.append(
            _Entry(
                path=path,
                host=host,
                size=metadata.st_size,
                mtime=metadata.st_mtime,
                changed=before.get(path) != (metadata.st_size, metadata.st_mtime),
            )
        )

    survivors, over_quota = _trim_to_quota(survivors, policy=policy)
    removed.extend(over_quota)
    return SweepResult(
        kept=tuple(sorted((entry.path, entry.size) for entry in survivors if entry.changed)),
        removed=tuple(sorted(removed)),
    )


def _disallowed_reason(
    path: str, metadata: os.stat_result, *, allowed: set[str], max_bytes: int
) -> str | None:
    """Why this entry cannot stay, or ``None`` when it is a file the policy would have allowed."""

    if not stat.S_ISREG(metadata.st_mode):
        return "not_a_regular_file"
    name = PurePosixPath(path).name
    if name.startswith(_ATOMIC_WRITE_PREFIX):
        return "atomic_write_residue"
    if PurePosixPath(path).suffix.lower() not in allowed:
        return "extension_not_allowed"
    if metadata.st_size > max_bytes:
        return "file_too_large"
    return None


def _trim_to_quota(
    survivors: list[_Entry], *, policy: WorkspacePolicy
) -> tuple[list[_Entry], list[tuple[str, str]]]:
    """Delete newest-written files until the tree fits, and stop when only the past is left.

    A workspace that was already over quota before the run stays over it: those bytes are not
    this run's doing, deleting them would destroy state the model wrote in an earlier turn, and
    the workspace's own quota check will refuse the next ``write_file`` anyway. So the candidates
    are exactly the files this run wrote or changed, newest first.

    Returns the files that survived and the ``(path, reason)`` pairs for the ones that did not.
    """

    total = sum(entry.size for entry in survivors)
    count = len(survivors)
    if total <= policy.max_total_bytes and count <= policy.max_file_count:
        return survivors, []

    # Newest first; the path breaks ties so two files written in the same clock tick still have
    # one deterministic order.
    removed: list[tuple[str, str]] = []
    doomed: set[str] = set()
    for entry in sorted(
        (entry for entry in survivors if entry.changed),
        key=lambda entry: (entry.mtime, entry.path),
        reverse=True,
    ):
        if total <= policy.max_total_bytes and count <= policy.max_file_count:
            break
        os.unlink(entry.host)
        removed.append((entry.path, "quota_exceeded"))
        doomed.add(entry.path)
        total -= entry.size
        count -= 1
    return [entry for entry in survivors if entry.path not in doomed], removed


def _remove_residue_folders(mounts: SandboxMounts) -> list[tuple[str, str]]:
    """Delete every folder with a ``.clue-tmp-*`` name, and everything in it, before the walk.

    The backend's walk refuses that name on a folder exactly as on a file, and a saved snapshot
    would carry the folder to every machine (review A2-I3) — so the file-name check alone is not
    enough. Each entry inside is reported as ``atomic_write_residue``. A link inside is unlinked
    and never followed, so nothing outside the workspace can be reached.
    """

    removed: list[tuple[str, str]] = []
    for name in sorted(mounts.read_write):
        stack = [(mounts.read_write[name], name)]
        while stack:
            host, prefix = stack.pop()
            try:
                with os.scandir(host) as entries:
                    children = list(entries)
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                continue
            for child in children:
                path = f"{prefix}/{child.name}"
                if not child.is_dir(follow_symlinks=False):
                    continue
                if child.name.startswith(_ATOMIC_WRITE_PREFIX):
                    removed.extend(_remove_tree(Path(child.path), path))
                else:
                    stack.append((Path(child.path), path))
    return removed


def _remove_tree(host: Path, prefix: str) -> list[tuple[str, str]]:
    """Remove a real folder bottom-up without following any link; report each non-folder."""

    removed: list[tuple[str, str]] = []
    with os.scandir(host) as entries:
        children = list(entries)
    for child in children:
        path = f"{prefix}/{child.name}"
        if child.is_dir(follow_symlinks=False):
            removed.extend(_remove_tree(Path(child.path), path))
        else:
            os.unlink(child.path)
            removed.append((path, "atomic_write_residue"))
    os.rmdir(host)
    return removed


def _walk(mounts: SandboxMounts) -> Iterator[tuple[str, Path, os.stat_result]]:
    """Every non-directory entry under the read-write dirs, as ``(path, host path, lstat)``.

    Real directories are descended into; a symlink is yielded as an entry in its own right and
    never followed, so neither the walk nor anything it hands to :func:`os.unlink` can leave the
    workspace. A directory that does not exist yields nothing: the layout folder may simply never
    have been created.
    """

    for name in sorted(mounts.read_write):
        stack = [(mounts.read_write[name], name)]
        while stack:
            host, prefix = stack.pop()
            try:
                with os.scandir(host) as entries:
                    children = list(entries)
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                continue
            for child in children:
                path = f"{prefix}/{child.name}"
                try:
                    metadata = os.lstat(child.path)
                except OSError:
                    # Gone between the scan and the stat: nothing left to judge or delete.
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    # Normally already private; repair explicit chmod/copy operations only.
                    if stat.S_IMODE(metadata.st_mode) != _DIR_MODE:
                        with suppress(OSError):
                            os.chmod(child.path, _DIR_MODE, follow_symlinks=False)
                    stack.append((Path(child.path), path))
                else:
                    yield path, Path(child.path), metadata
