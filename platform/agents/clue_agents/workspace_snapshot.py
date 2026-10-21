"""The snapshot of a chat's agent folders: what is saved, in which tier, and the file list's format.

F3 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md, WS-2,
WS-4, WS-5; rulings AW-2, AW-14). A chat's ``scratch/ reads/ work/ outputs/`` are saved as one
versioned snapshot: a canonical JSON file list naming every file by its content hash, plus the
files themselves, both in the artifact store. The version record in Postgres says which file list
is current. Nothing here touches the disk, the database or storage; those live in the snapshot
store and the snapshotter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, get_args
from uuid import UUID

__all__ = [
    "MANIFEST_MEDIA_TYPE",
    "MANIFEST_SCHEMA_VERSION",
    "RAW_INPUT_PREFIXES",
    "SAVED_FOLDERS",
    "LeaseFence",
    "SaveStatus",
    "SnapshotCorrupt",
    "SnapshotEntry",
    "SnapshotManifest",
    "SnapshotPointer",
    "SnapshotTier",
    "WorkspaceRestoreUnavailable",
    "WorkspaceSaveUnavailable",
    "decode_manifest",
    "encode_manifest",
    "tier_for",
    "validate_snapshot_path",
]

SnapshotTier = Literal["work_product", "raw_input"]
SaveStatus = Literal["saved", "unchanged", "stale", "fenced"]

#: The agent folders a snapshot holds, every file in them (AW-14: nothing is emptied between turns).
SAVED_FOLDERS: Final = ("scratch", "reads", "work", "outputs")
#: Raw inputs (AW-2): bulky, re-fetchable; Phase 2 expires their bytes and keeps a receipt.
RAW_INPUT_PREFIXES: Final = ("reads/", "work/conversation_history/", "work/large_tool_results/")
MANIFEST_MEDIA_TYPE: Final = "application/vnd.clue.agent-workspace-manifest+json"
MANIFEST_SCHEMA_VERSION: Final = 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SnapshotCorrupt(RuntimeError):
    """A file list or a stored file is not what it claims to be. Never restored."""


class WorkspaceRestoreUnavailable(RuntimeError):
    """Storage could not be reached to bring a stale local copy up to date (the turn is retried)."""


class WorkspaceSaveUnavailable(RuntimeError):
    """Storage could not be reached to save the agent's files after retries (AW-18)."""


def validate_snapshot_path(path: str) -> str:
    """``path`` if it names a file inside one of the saved folders, else :class:`SnapshotCorrupt`.

    The path is the one recorded in a file list, so it is checked as untrusted input: a restore
    writes it to disk. Relative, ``/``-separated, no empty, ``.`` or ``..`` segment, first segment
    one of :data:`SAVED_FOLDERS`, and at least one segment below it.
    """

    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise SnapshotCorrupt(f"snapshot path is not a relative path: {path!r}")
    segments = path.split("/")
    if len(segments) < 2 or segments[0] not in SAVED_FOLDERS:
        raise SnapshotCorrupt(f"snapshot path is outside the saved folders: {path!r}")
    if any(segment in ("", ".", "..") or "\x00" in segment for segment in segments):
        raise SnapshotCorrupt(f"snapshot path has an invalid segment: {path!r}")
    return path


def tier_for(path: str) -> SnapshotTier:
    """The retention tier of a saved path (AW-2, AW-14)."""

    return "raw_input" if path.startswith(RAW_INPUT_PREFIXES) else "work_product"


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """One saved file: where it goes, its bytes by hash, and when this content first appeared."""

    path: str
    sha256: str
    size: int
    media_type: str
    tier: SnapshotTier
    written_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Every file of one snapshot version."""

    entries: tuple[SnapshotEntry, ...]
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def by_path(self) -> Mapping[str, SnapshotEntry]:
        return {entry.path: entry for entry in self.entries}

    def same_files(self, other: SnapshotManifest) -> bool:
        """The same paths with the same bytes; times and media types do not count."""

        return {(e.path, e.sha256) for e in self.entries} == {
            (e.path, e.sha256) for e in other.entries
        }


@dataclass(frozen=True, slots=True)
class SnapshotPointer:
    """A chat's current snapshot, as its version record names it."""

    version: int
    manifest_sha256: str
    manifest_key: str


@dataclass(frozen=True, slots=True)
class LeaseFence:
    """The fleet lease a save must still hold (WS-8, AW-10)."""

    work_id: UUID
    worker_id: str
    generation: int


def encode_manifest(manifest: SnapshotManifest) -> bytes:
    """Canonical bytes: entries sorted by path, keys sorted, no whitespace, UTC ISO-8601 times."""

    document = {
        "schema_version": manifest.schema_version,
        "entries": [
            {
                "path": entry.path,
                "sha256": entry.sha256,
                "size": entry.size,
                "media_type": entry.media_type,
                "tier": entry.tier,
                "written_at": entry.written_at.isoformat(),
            }
            for entry in sorted(manifest.entries, key=lambda item: item.path)
        ],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_manifest(data: bytes) -> SnapshotManifest:
    """The file list in ``data``, every field checked, or :class:`SnapshotCorrupt`."""

    try:
        document = json.loads(data)
        if document["schema_version"] != MANIFEST_SCHEMA_VERSION:
            raise SnapshotCorrupt(f"unknown file list schema {document['schema_version']!r}")
        entries = []
        seen: set[str] = set()
        for raw in document["entries"]:
            path = validate_snapshot_path(raw["path"])
            sha = raw["sha256"]
            size = raw["size"]
            tier = raw["tier"]
            if not isinstance(sha, str) or not _SHA256.match(sha):
                raise SnapshotCorrupt(f"file list entry {path!r} has a bad hash")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise SnapshotCorrupt(f"file list entry {path!r} has a bad size")
            if tier not in get_args(SnapshotTier):
                raise SnapshotCorrupt(f"file list entry {path!r} has a bad tier")
            if path in seen:
                raise SnapshotCorrupt(f"file list names {path!r} twice")
            seen.add(path)
            entries.append(
                SnapshotEntry(
                    path=path,
                    sha256=sha,
                    size=size,
                    media_type=str(raw["media_type"]),
                    tier=tier,
                    written_at=datetime.fromisoformat(raw["written_at"]),
                )
            )
    except SnapshotCorrupt:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise SnapshotCorrupt("file list is not readable") from exc
    return SnapshotManifest(entries=tuple(sorted(entries, key=lambda item: item.path)))
