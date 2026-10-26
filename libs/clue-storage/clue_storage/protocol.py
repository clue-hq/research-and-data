"""The ``StorageBackend`` protocol + content addressing (Phase B2 / harness REQ-07).

Durable artifact storage so evidence stops rotting: the raw bytes a scrape fetches are stored at
the moment they exist, under a **content-addressed** key, and every claim extracted from them
carries that key — so an ``evidence_span`` resolves *offline* from the snapshot forever, even
after the live ``source_url`` dies.

Two deliberate design points (PB-B2 founder rulings):

* **Keys are workspace-scoped** — ``{workspace_id or "public"}/{sha256}``. Identical bytes dedup
  *within* a workspace, never across tenants (a shared blob across workspaces would make DSAR
  erasure a cross-tenant concern).
* **The protocol is async** (the codebase's I/O is async end-to-end); the *capture* of bytes in
  the sync adapter chain is a separate, in-memory concern (:mod:`clue_storage.snapshot`).

The concrete backend (fs vs S3-compatible) is selected by settings alone
(:func:`clue_storage.factory.storage_from_settings`); no caller learns which one it holds —
exactly the ``ArtifactCache`` docstring's promise ("no caller learns where artifacts live"),
made durable.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

# The scope segment used when a snapshot backs public-footprint (workspace-less) claims.
PUBLIC_SCOPE = "public"


class StorageError(RuntimeError):
    """Base error for the storage backend (a typed failure callers can catch)."""


class ArtifactNotFound(StorageError):
    """``get``/``presign`` was called for a key the backend does not hold."""


def content_address(data: bytes) -> str:
    """The sha256 hexdigest of ``data`` — the content-addressed identity of a snapshot.

    Hashing the *bytes* (not the request) is what makes re-storing identical content a no-op
    (REQ-07: "re-uploading identical bytes creates no duplicate artifact"). The request-keyed
    sibling — ``adapters/cache.py::content_key`` — has a different job (per-run fetch dedup) and
    deliberately stays separate.
    """
    return hashlib.sha256(data).hexdigest()


def artifact_key(workspace_id: str | None, sha256: str) -> str:
    """The storage key for a snapshot: ``{workspace_id or "public"}/{sha256}``.

    Deterministic from ``(scope, bytes)`` alone — computable synchronously inside the adapter
    chain before any DB or network write, which is what lets claims be stamped with their
    artifact ref with no id-remap step (PB-B2 §B2.2).
    """
    return f"{workspace_id or PUBLIC_SCOPE}/{sha256}"


# The scope-relative segment that marks a blob as one chat's agent-workspace file.
AGENT_WORKSPACE_SEGMENT = "agent-workspace"


def agent_workspace_key(workspace_id: str | None, sha256: str) -> str:
    """The storage key for an agent-workspace snapshot file:
    ``{workspace_id or "public"}/agent-workspace/{sha256}``.

    F3 Phase 2 gives a chat's own files their own area for the same reason design bytes got one
    (``{workspace}/design/{sha}``, ruling R-D4-2): **the areas decide what a cleanup can reach.**
    Retention expires a chat's files by age, and if they shared the bare ``{workspace}/{sha}``
    namespace with evidence snapshots, uploads and Gallery artifacts, identical bytes would
    dedup onto one key and expiring the chat's copy would delete somebody else's blob. Separate
    areas make that unrepresentable rather than a refcount to get right.
    """
    return f"{workspace_id or PUBLIC_SCOPE}/{AGENT_WORKSPACE_SEGMENT}/{sha256}"


def is_agent_workspace_key(storage_key: str) -> bool:
    """Whether ``storage_key`` names a blob in the agent-workspace area.

    The retention sweep asks this before it deletes anything: a key outside the area is some
    other owner's (evidence, design, uploads) and is never the sweep's to touch. So the match is
    the exact three-segment shape :func:`agent_workspace_key` writes, not a substring — a key
    that merely *contains* the word somewhere is not in the area and must not be deleted.
    """
    parts = storage_key.split("/")
    return len(parts) == 3 and parts[1] == AGENT_WORKSPACE_SEGMENT


@runtime_checkable
class StorageBackend(Protocol):
    """Durable blob storage over content-addressed keys (REQ-07).

    Implementations: :class:`clue_storage.fs.FsStorage` and :class:`clue_storage.s3.S3Storage`
    (endpoint config covers AWS S3 / R2 / MinIO). All operations are idempotent where retry
    matters: ``put`` of identical bytes at the same key is a no-op overwrite; ``delete`` of a
    missing key is a no-op (DSAR erasure must be safe to retry).
    """

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        """Store ``data`` under ``key``. Content-addressed keys make this idempotent — the same
        key always names the same bytes, so an overwrite can never lose information."""
        ...

    async def get(self, key: str) -> bytes:
        """Return the bytes under ``key``; raises :class:`ArtifactNotFound` if absent."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the blob under ``key`` (idempotent; a missing key is a no-op)."""
        ...

    async def exists(self, key: str) -> bool:
        """Whether a blob is stored under ``key``."""
        ...

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        """A URL/URI a client can fetch ``key`` from without credentials, valid ``expires_in``
        seconds (frontend serving, treaty §2.8 — nothing consumes this yet in Phase B)."""
        ...

    def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        """Iterate every stored ``(key, last_modified)`` — the reconciliation read
        (:func:`clue_storage.artifacts.sweep_orphan_blobs`): a blob older than the sweep's
        grace window with no ``artifact`` row is a rolled-back upload's orphan. ``last_modified``
        is timezone-aware UTC."""
        ...
