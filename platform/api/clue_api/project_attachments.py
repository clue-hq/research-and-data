"""The project's uploaded files in each chat's own folder (spec 2026-09-19 §3.2; F3 WS-37).

Every file a human attached in a project chat — text, image or document, nothing converted —
belongs to the *project*, not to the turn that carried it. Each chat holds its own copy in
``<chat>/attachments`` (beside its ``agent/`` root, never shared with another chat; ruling AW-9),
read-only mounted by every turn of that chat.

This module is the sync: the durable attachment rows are the truth, the directory is a cache of
them, and one call reconciles the second to the first. It runs on the **worker** that owns the
workspace root — the HTTP process that accepted the upload has no such root, and a file written
where the agent cannot reach it is not an attachment.

Three properties the implementation exists to keep:

* **Idempotent.** A file whose bytes on disk already hash to the entry's ``sha256`` is left
  untouched, so the ordinary turn of an unchanged project does no I/O beyond one listing.
* **Convergent.** A name the entries no longer carry — an erased or purged artifact, most of all —
  is removed. What the model can read is what the workspace still holds.
* **Anchored.** Every write goes through the factory's chat-folder descriptor and ``O_NOFOLLOW``,
  never through a host path string, exactly as the library sync does.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    ATTACHMENTS_DIR,
    AgentArtifactReader,
    AgentWorkspaceFactory,
    ArtifactRef,
    WorkspaceSecurityError,
)
from clue_agents.worker_area import ChatScope

__all__ = [
    "ProjectAttachmentEntry",
    "project_attachment_entries",
    "sync_project_attachments",
]

# The same anchored, link-refusing flags the workspace itself opens with. They are spelled here
# rather than imported from ``clue_agents.workspace``'s private names because this package is not
# that one; ``getattr`` keeps the module importable on a platform lacking a flag.
_DIR_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_WRITE_FLAGS: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_TRUNC
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_MODE: Final = 0o600
_CHUNK: Final = 1 << 20


@dataclass(frozen=True)
class ProjectAttachmentEntry:
    """One file this project holds: the name the human gave it and the bytes behind it."""

    filename: str
    ref: ArtifactRef
    attached_at: datetime


# ``DISTINCT ON (a.filename)`` with the newest submission first: re-attaching a name replaces the
# file rather than accumulating ``brief (1).md``. The order key is the *submission's*
# ``requested_at`` — the acceptance clock ``insert_submission`` maintains — and not the
# attachment row's ``created_at``, which defaults to ``now()`` (transaction-start time) and
# therefore ties for two submissions accepted inside one transaction. ``ordinal DESC`` is the last
# tiebreak, so one message attaching the same name twice still resolves to exactly one file.
_ENTRIES_SQL: Final = text(
    "SELECT DISTINCT ON (a.filename) a.filename, a.artifact_key, a.sha256, a.media_type, "
    " a.byte_count, s.requested_at "
    "FROM agent_turn_submission_attachment a "
    "JOIN agent_turn_submission s "
    " ON s.turn_id = a.turn_id AND s.workspace_id = a.workspace_id "
    "JOIN artifact art ON art.storage_key = a.artifact_key "
    "WHERE s.workspace_id = :ws AND s.project_id = :project "
    " AND art.erased_at IS NULL AND art.purged_at IS NULL "
    "ORDER BY a.filename, s.requested_at DESC, a.ordinal DESC"
)


async def project_attachment_entries(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[ProjectAttachmentEntry, ...]:
    """Every live file this project holds, one row per filename, newest upload of a name winning.

    An erased or purged artifact is simply absent: the DSAR path tombstones the artifact row, and
    this read is the join that makes the file disappear from the agent's view on the next turn
    without anybody having to remember the directory exists.
    """

    result = await conn.execute(_ENTRIES_SQL, {"ws": workspace_id, "project": project_id})
    return tuple(
        ProjectAttachmentEntry(
            filename=row["filename"],
            ref=ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=row["artifact_key"],
                sha256=row["sha256"],
                media_type=row["media_type"],
                byte_count=int(row["byte_count"]),
            ),
            attached_at=row["requested_at"],
        )
        for row in result.mappings()
    )


async def sync_project_attachments(
    workspaces: AgentWorkspaceFactory,
    artifacts: AgentArtifactReader,
    conn: AsyncConnection,
    *,
    chat: ChatScope,
) -> int:
    """Reconcile ``<chat>/attachments`` with this project's attachment rows. Returns writes.

    Only what moved is paid for: the directory is listed and hashed, the entries whose bytes are
    absent or different are fetched, and everything else is left exactly as it stands. A project
    with no attachments and no directory is a no-op — the directory is *not* created, because an
    absent one is how :class:`~clue_agents.MountRequest` says "this project has no uploads" and an
    empty mount would tell the model something else.

    The filesystem work runs in a worker thread: the turn's event loop is never held while a
    directory is listed, hashed or written.
    """

    entries = await project_attachment_entries(
        conn, workspace_id=chat.workspace_id, project_id=chat.project_id
    )
    installed = await asyncio.to_thread(_installed_digests, workspaces, chat=chat)
    if not entries and installed is None:
        return 0
    known: Mapping[str, str] = installed or {}
    stale = tuple(entry for entry in entries if known.get(entry.filename) != entry.ref.sha256)
    # Removed first, then rewritten: a name no live entry carries, plus anything down there this
    # module cannot have written (a directory, a device node, an unreadable file — all carry the
    # empty digest). Dropping the second kind is what keeps a stray entry from turning into a
    # write that can never succeed, and so a turn that can never start.
    obsolete = tuple(
        sorted(
            (set(known) - {entry.filename for entry in entries})
            | {name for name, digest in known.items() if not digest}
        )
    )
    if not stale and not obsolete:
        return 0
    bodies: list[tuple[str, bytes]] = []
    for entry in stale:
        bodies.append((entry.filename, await artifacts.read(entry.ref)))
    await asyncio.to_thread(
        _install,
        workspaces,
        chat=chat,
        bodies=tuple(bodies),
        obsolete=obsolete,
    )
    return len(bodies)


def _validated_name(filename: str) -> str:
    """One path segment, or nothing.

    Upload already reduced the human's filename to a single segment
    (:func:`~clue_api.chat.uploads.sanitize_filename`) and the ``chat_upload`` CHECK refuses a
    ``/``. This refuses it a second time, at the only place the name becomes a real directory
    entry, because a name that reached the write is a name that reached the filesystem. Only the
    *written* names are checked: a name being removed came from ``os.listdir`` and is therefore
    already one segment, and refusing one would strand it here forever.
    """

    if not filename or "/" in filename or "\x00" in filename:
        raise WorkspaceSecurityError("an attachment filename must be one path segment")
    if filename in {".", ".."}:
        raise WorkspaceSecurityError("an attachment filename must not be a dot path component")
    return filename


def _installed_digests(
    workspaces: AgentWorkspaceFactory,
    *,
    chat: ChatScope,
) -> dict[str, str] | None:
    """``{filename: sha256}`` for what is on disk, or None when there is no directory at all.

    Anything below the directory that is not a regular file is reported under a digest nothing can
    match, so the next step removes it: this directory holds uploads and nothing else.
    """

    parent_fd = workspaces.chat_dir_fd(chat)
    try:
        try:
            directory_fd = os.open(ATTACHMENTS_DIR, _DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkspaceSecurityError("the project attachments directory is unsafe") from exc
        try:
            digests: dict[str, str] = {}
            for name in os.listdir(directory_fd):
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    digests[name] = ""
                    continue
                digests[name] = _digest(directory_fd, name)
            return digests
        finally:
            os.close(directory_fd)
    finally:
        os.close(parent_fd)


def _digest(directory_fd: int, name: str) -> str:
    """The sha256 of one file below an anchored descriptor, or ``""`` when it cannot be read."""

    try:
        file_fd = os.open(name, _READ_FLAGS, dir_fd=directory_fd)
    except OSError:
        return ""
    try:
        digest = hashlib.sha256()
        while chunk := os.read(file_fd, _CHUNK):
            digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""
    finally:
        os.close(file_fd)


def _install(
    workspaces: AgentWorkspaceFactory,
    *,
    chat: ChatScope,
    bodies: Sequence[tuple[str, bytes]],
    obsolete: Sequence[str],
) -> None:
    """Write the moved files and drop the ones no live entry names. Both anchored, both by name."""

    parent_fd = workspaces.chat_dir_fd(chat)
    try:
        directory_fd = workspaces.ensure_child_directory(parent_fd, ATTACHMENTS_DIR)
    finally:
        os.close(parent_fd)
    try:
        for name in obsolete:
            _remove(directory_fd, name)
        for filename, data in bodies:
            _write(directory_fd, _validated_name(filename), data)
    finally:
        os.close(directory_fd)


def _remove(directory_fd: int, name: str) -> None:
    """Drop one entry, whatever kind it is. Idempotent, and never fatal to the turn."""

    try:
        os.unlink(name, dir_fd=directory_fd)
    except OSError:
        with suppress(OSError):
            os.rmdir(name, dir_fd=directory_fd)


def _write(directory_fd: int, name: str, data: bytes) -> None:
    try:
        file_fd = os.open(name, _WRITE_FLAGS, _FILE_MODE, dir_fd=directory_fd)
    except OSError as exc:
        raise WorkspaceSecurityError("a project attachment could not be written") from exc
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(file_fd, view) :]
    except OSError as exc:
        raise WorkspaceSecurityError("a project attachment could not be written") from exc
    finally:
        os.close(file_fd)
