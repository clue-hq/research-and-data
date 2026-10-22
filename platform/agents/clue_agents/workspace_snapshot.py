"""The snapshot of a chat's agent folders: what is saved, in which tier, and the file list's format.

F3 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md, WS-2,
WS-4, WS-5; rulings AW-2, AW-14). A chat's ``scratch/ reads/ work/ outputs/`` are saved as one
versioned snapshot: a canonical JSON file list naming every file by its content hash, plus the
files themselves, both in the artifact store. The version record in Postgres says which file list
is current. Nothing here touches the disk, the database or storage; those live in the snapshot
store and the snapshotter.

Phase 2 (rulings AW-2, AW-22, AW-24) expires a chat's rough work while keeping a receipt saying
what was there and how to get it again. Every saved path falls in one of three tiers:

``raw_input``
    What a tool fetched: ``reads/``, ``work/conversation_history/``, ``work/large_tool_results/``.
    Bulky and re-fetchable; the bytes go 48 hours after the chat's last activity.
``working_file``
    The agent's own rough work: ``scratch/`` and the rest of ``work/``. The bytes go after 7 days.
``work_product``
    ``outputs/`` and nothing else. It never expires (AW-2).

An expired entry stays in the file list with an ``expired_at`` and its :class:`Receipt`, and has
no bytes anywhere. Nothing may try to read one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, get_args
from uuid import UUID

from pydantic import JsonValue

__all__ = [
    "MANIFEST_MEDIA_TYPE",
    "MANIFEST_SCHEMA_VERSION",
    "RAW_INPUT_PREFIXES",
    "SAVED_FOLDERS",
    "WORK_PRODUCT_PREFIXES",
    "LeaseFence",
    "Receipt",
    "SaveStatus",
    "SnapshotCorrupt",
    "SnapshotEntry",
    "SnapshotManifest",
    "SnapshotPointer",
    "SnapshotTier",
    "UNKNOWN_RECEIPT",
    "WorkspaceRestoreUnavailable",
    "WorkspaceSaveUnavailable",
    "decode_manifest",
    "encode_manifest",
    "tier_for",
    "validate_snapshot_path",
]

SnapshotTier = Literal["work_product", "working_file", "raw_input"]
SaveStatus = Literal["saved", "unchanged", "stale", "fenced"]

#: The agent folders a snapshot holds, every file in them (AW-14: nothing is emptied between turns).
SAVED_FOLDERS: Final = ("scratch", "reads", "work", "outputs")
#: Raw inputs (AW-2): bulky, re-fetchable; Phase 2 expires their bytes and keeps a receipt.
RAW_INPUT_PREFIXES: Final = ("reads/", "work/conversation_history/", "work/large_tool_results/")
#: Finished work the agent keeps (AW-2). This tier never expires, so it is never widened.
WORK_PRODUCT_PREFIXES: Final = ("outputs/",)
MANIFEST_MEDIA_TYPE: Final = "application/vnd.clue.agent-workspace-manifest+json"
#: 2 adds the ``working_file`` tier, per-entry receipts and ``expired_at``. 1 still decodes.
MANIFEST_SCHEMA_VERSION: Final = 2
_READABLE_SCHEMA_VERSIONS: Final = (1, 2)

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
    """The retention tier of a saved path (AW-2, AW-22).

    The path decides, always: a file list never gets to say its own tier. That is what lets a
    Phase 1 list — which called every non-raw file a work product — gain the ``working_file``
    tier with no migration.
    """

    if path.startswith(RAW_INPUT_PREFIXES):
        return "raw_input"
    if path.startswith(WORK_PRODUCT_PREFIXES):
        return "work_product"
    return "working_file"


@dataclass(frozen=True, slots=True)
class Receipt:
    """What a file held and how to get it again, kept after its bytes expire (AW-22, AW-24).

    ``source`` names what produced the file (a tool name, or ``"unknown"`` when nothing told us),
    ``read_again`` is the plain sentence the agent is shown so it can fetch the same thing, and
    ``details`` is whatever small JSON that source wants to remember about the call.
    """

    source: str
    operation_id: str | None = None
    produced_at: datetime | None = None
    details: Mapping[str, JsonValue] = field(default_factory=dict)
    read_again: str = ""


#: What a new expiring entry carries when nothing could say where it came from. Never ``None``:
#: a file is not dropped for want of a receipt.
UNKNOWN_RECEIPT: Final = Receipt(
    source="unknown", operation_id=None, produced_at=None, details={}, read_again=""
)


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """One saved file: where it goes, its bytes by hash, and when this content first appeared.

    An entry with an ``expired_at`` has no bytes anywhere: its ``sha256`` names content nobody
    holds any more, and only its ``receipt`` says what it was.
    """

    path: str
    sha256: str
    size: int
    media_type: str
    tier: SnapshotTier
    written_at: datetime
    receipt: Receipt | None = None
    expired_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Every file of one snapshot version."""

    entries: tuple[SnapshotEntry, ...]
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def by_path(self) -> Mapping[str, SnapshotEntry]:
        return {entry.path: entry for entry in self.entries}

    def live(self) -> tuple[SnapshotEntry, ...]:
        """The entries whose bytes are still stored — the only ones anything may read."""

        return tuple(entry for entry in self.entries if entry.expired_at is None)

    def expired(self) -> tuple[SnapshotEntry, ...]:
        """The entries kept only as a receipt: their bytes are gone (AW-22)."""

        return tuple(entry for entry in self.entries if entry.expired_at is not None)

    def same_files(self, other: SnapshotManifest) -> bool:
        """The same live paths with the same bytes, and the same paths expired.

        Times, media types and receipts do not count — but an expiry does, or a save would
        call it unchanged and the expiry would never be persisted.
        """

        def shape(manifest: SnapshotManifest) -> tuple[set[tuple[str, str]], set[str]]:
            return (
                {(e.path, e.sha256) for e in manifest.live()},
                {e.path for e in manifest.expired()},
            )

        return shape(self) == shape(other)


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


def _encode_receipt(receipt: Receipt) -> dict[str, object]:
    return {
        "source": receipt.source,
        "operation_id": receipt.operation_id,
        "produced_at": None if receipt.produced_at is None else receipt.produced_at.isoformat(),
        "details": dict(receipt.details),
        "read_again": receipt.read_again,
    }


def _encode_entry(entry: SnapshotEntry) -> dict[str, object]:
    document: dict[str, object] = {
        "path": entry.path,
        "sha256": entry.sha256,
        "size": entry.size,
        "media_type": entry.media_type,
        "tier": entry.tier,
        "written_at": entry.written_at.isoformat(),
    }
    # Omitted rather than written as null, so a file list with neither is byte-identical to the
    # Phase 1 shape and an unchanged chat's manifest hash does not move.
    if entry.receipt is not None:
        document["receipt"] = _encode_receipt(entry.receipt)
    if entry.expired_at is not None:
        document["expired_at"] = entry.expired_at.isoformat()
    return document


def encode_manifest(manifest: SnapshotManifest) -> bytes:
    """Canonical bytes: entries sorted by path, keys sorted, no whitespace, UTC ISO-8601 times."""

    document = {
        "schema_version": manifest.schema_version,
        "entries": [
            _encode_entry(entry) for entry in sorted(manifest.entries, key=lambda item: item.path)
        ],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode_receipt(path: str, raw: object) -> Receipt:
    if not isinstance(raw, dict):
        raise SnapshotCorrupt(f"file list entry {path!r} has a bad receipt")
    source = raw["source"]
    operation_id = raw["operation_id"]
    produced_at = raw["produced_at"]
    details = raw["details"]
    read_again = raw["read_again"]
    if not isinstance(source, str) or not isinstance(read_again, str):
        raise SnapshotCorrupt(f"file list entry {path!r} has a bad receipt")
    if operation_id is not None and not isinstance(operation_id, str):
        raise SnapshotCorrupt(f"file list entry {path!r} has a bad receipt")
    if not isinstance(details, dict) or any(not isinstance(key, str) for key in details):
        raise SnapshotCorrupt(f"file list entry {path!r} has a bad receipt")
    return Receipt(
        source=source,
        operation_id=operation_id,
        produced_at=None if produced_at is None else datetime.fromisoformat(produced_at),
        details=details,
        read_again=read_again,
    )


def decode_manifest(data: bytes) -> SnapshotManifest:
    """The file list in ``data``, every field checked, or :class:`SnapshotCorrupt`.

    Schema 1 still decodes (a Phase 1 snapshot must keep restoring): its entries carry no receipt
    and are not expired, and their tier is re-derived from the path by :func:`tier_for`, which is
    how they gain the ``working_file`` tier without a migration.
    """

    try:
        document = json.loads(data)
        if document["schema_version"] not in _READABLE_SCHEMA_VERSIONS:
            raise SnapshotCorrupt(f"unknown file list schema {document['schema_version']!r}")
        entries = []
        seen: set[str] = set()
        for raw in document["entries"]:
            path = validate_snapshot_path(raw["path"])
            sha = raw["sha256"]
            size = raw["size"]
            tier = raw["tier"]
            expired_at = raw.get("expired_at")
            receipt = raw.get("receipt")
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
                    # The stored tier is read only to check the list is well formed; the path is
                    # what decides, so an old list's "work_product" on scratch/ does not stick.
                    tier=tier_for(path),
                    written_at=datetime.fromisoformat(raw["written_at"]),
                    receipt=None if receipt is None else _decode_receipt(path, receipt),
                    expired_at=None if expired_at is None else datetime.fromisoformat(expired_at),
                )
            )
    except SnapshotCorrupt:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise SnapshotCorrupt("file list is not readable") from exc
    return SnapshotManifest(entries=tuple(sorted(entries, key=lambda item: item.path)))
