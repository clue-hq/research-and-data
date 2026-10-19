"""Sync a design session's folder to content-addressed storage (design note §3.2, ruling: sync).

One design document is one design session, and a session's memory lives in a folder on whichever
worker ran its last turn. Fleet work is not sticky, so without this the next turn would open a
continued thread over an empty workspace — the agent would hold a conversation about files it
cannot read.

What travels: the agent-visible ``workspace/`` tree and the deepagents conversation-history file
for the session (``<trace_dir>/conversation_history/<session_id>.md``). What does not:
``turns/<run_id>/`` outputs (observability, not continuity), files over :data:`MAX_FILE_BYTES`,
and symlinks — a symlink names a path on a host the next worker does not have, so following it
would smuggle foreign bytes into the session and storing it verbatim would restore a dangling
pointer.

The manifest keys every file on its OWN sha256 rather than on whatever ``register`` returns: the
production store (``DesignBlobStore.register``) hands back a storage KEY (``{ws}/design/{sha}``)
while its reader (``read_blob``) takes a DIGEST, so a manifest built from the return value could
never be read back. ``register`` is called for custody; its answer is deliberately ignored.
"""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable, Iterator
from pathlib import Path

#: Per-file ceiling. A session's memory is briefs, notes and round previews; anything larger is a
#: turn's scratch output that the next turn does not need in order to continue the conversation.
MAX_FILE_BYTES = 25 * 1024 * 1024

#: The one manifest key prefix that does NOT live under the session folder — the conversation
#: history is written beside ``sessions/``, at the workspace root, by the deepagents middleware.
_HISTORY_KEY_PREFIX = "conversation_history/"


def _iter_workspace_files(session_dir: Path, exclude: frozenset[str] = frozenset()) -> Iterator[tuple[str, Path]]:
    """``(manifest key, path)`` for every file the session workspace may carry across turns.

    ``exclude`` names top-level entries of ``workspace/`` that are rebuilt for every turn (the site
    agent's research, catalog and page files) and so never belong in the session's memory.
    """
    workspace = session_dir / "workspace"
    if not workspace.is_dir():
        return
    for path in sorted(workspace.rglob("*")):
        # ``is_symlink`` is checked FIRST: ``is_file`` follows the link, so a symlink to a real
        # file would otherwise be read and stored as if it were session content.
        if path.is_symlink() or not path.is_file():
            continue
        if path.relative_to(workspace).parts[0] in exclude:
            continue
        if path.stat().st_size <= MAX_FILE_BYTES:
            yield path.relative_to(session_dir).as_posix(), path


def snapshot_session(
    session_dir: Path,
    *,
    register: Callable[[bytes, str, str], str],
    history_file: Path | None,
    exclude: frozenset[str] = frozenset(),
) -> dict:
    """Give this session's memory durable custody and describe it.

    ``register(data, media_type, source_key)`` is the blob store's custody call. Its return value
    is ignored (see the module docstring); the manifest carries the digest computed here.
    """
    files: dict[str, dict] = {}
    entries = list(_iter_workspace_files(session_dir, exclude))
    if history_file is not None and history_file.is_file() and not history_file.is_symlink():
        entries.append((_HISTORY_KEY_PREFIX + history_file.name, history_file))
    for key, path in entries:
        data = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        register(data, media_type, f"design-session/{key}")
        files[key] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "media_type": media_type,
        }
    return {"schema_version": 1, "files": files}


def restore_session(
    session_dir: Path,
    manifest: dict,
    *,
    read_blob: Callable[[str], tuple[str, bytes]],
    history_file: Path | None,
) -> int:
    """Rebuild a missing session folder from ``manifest``; return how many files were written.

    Every blob is verified against the digest the manifest names. A mismatch raises rather than
    writing: a session folder rebuilt from bytes that are not this session's is not memory, it is
    a quiet fabrication, and the honest alternative (a fresh empty workspace) is strictly better.
    """
    restored = 0
    for key, entry in (manifest.get("files") or {}).items():
        if key.startswith(_HISTORY_KEY_PREFIX):
            if history_file is None:
                continue
            target = history_file
        else:
            target = session_dir / key
            # A manifest is data from storage, so its keys are treated as untrusted: a key that
            # climbs out of the session folder is skipped rather than followed.
            if not _is_inside(target, session_dir):
                continue
        _, data = read_blob(entry["sha256"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"session blob digest mismatch for {key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored += 1
    return restored


def _is_inside(target: Path, session_dir: Path) -> bool:
    """Whether ``target`` stays within ``session_dir``, resolved against a folder that may not
    exist yet (restore runs precisely when it does not)."""
    root = session_dir.resolve()
    # ``Path.resolve`` on a non-existent path is non-strict in 3.6+, so this is safe pre-mkdir.
    return target.resolve().is_relative_to(root)


__all__ = ["MAX_FILE_BYTES", "restore_session", "snapshot_session"]
