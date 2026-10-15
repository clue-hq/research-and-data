"""Brand-context document bytes: fetched together, cached by content, checked on every read.

The Brand-context page lists every brand document with its title and product links, which means
opening each document. Fetching them from object storage one after another made the Stripe
workspace's page take 8.7 s for 37 documents (2026-10-15). Two changes, and no check skipped:

* **Fetched together.** One page's documents are downloaded concurrently (16 at a time); only the
  downloads overlap — the database checks then run in turn on the caller's connection.
* **Cached by content.** A document version's bytes live under a content address and never change,
  so a cached copy cannot be stale. The cache is keyed by workspace, storage key and digest, and
  is bounded.

Every read, cache hit or not, still runs :func:`clue_storage.verify_artifact_bytes`: the artifact
row exists in this workspace, is not erased, expired or purged, and matches the bytes' digest and
size. An erased document is therefore refused even when its bytes are cached.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_storage import ArtifactIntegrityError, StorageBackend, StorageError, verify_artifact_bytes

__all__ = [
    "KnowledgeRef",
    "clear_knowledge_byte_cache",
    "read_knowledge_bytes",
    "read_one_knowledge_bytes",
]

#: How many document downloads run at once for one page.
FETCH_CONCURRENCY = 16
#: How many documents the process keeps, and the largest one it keeps.
CACHE_ENTRIES = 2048
CACHE_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

#: ``(storage_key, digest)`` of one stored document version.
KnowledgeRef = tuple[str, str]

_cache: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()


def clear_knowledge_byte_cache() -> None:
    _cache.clear()


def _cached(workspace_id: str, ref: KnowledgeRef) -> bytes | None:
    key = (workspace_id, *ref)
    data = _cache.get(key)
    if data is not None:
        _cache.move_to_end(key)
    return data


def _remember(workspace_id: str, ref: KnowledgeRef, data: bytes) -> None:
    if len(data) > CACHE_MAX_DOCUMENT_BYTES:
        return
    _cache[(workspace_id, *ref)] = data
    _cache.move_to_end((workspace_id, *ref))
    while len(_cache) > CACHE_ENTRIES:
        _cache.popitem(last=False)


async def read_knowledge_bytes(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    refs: Sequence[KnowledgeRef],
) -> dict[KnowledgeRef, bytes | Exception]:
    """Each document's verified bytes, or the error that refused it — never raises for one.

    ``refs`` pairs a storage key with the digest its document row records; a stored artifact whose
    digest differs from the row's is refused like any other integrity failure.
    """
    wanted = list(dict.fromkeys(refs))
    fetched: dict[KnowledgeRef, bytes | Exception] = {}
    missing = [ref for ref in wanted if _cached(workspace_id, ref) is None]
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def fetch(ref: KnowledgeRef) -> None:
        async with gate:
            try:
                fetched[ref] = await storage.get(ref[0])
            except StorageError as exc:
                fetched[ref] = ArtifactIntegrityError(f"artifact blob is missing: {exc}")
            except Exception as exc:  # noqa: BLE001 — one unreadable blob never fails the page
                fetched[ref] = exc

    await asyncio.gather(*(fetch(ref) for ref in missing))

    out: dict[KnowledgeRef, bytes | Exception] = {}
    for ref in wanted:
        cached = _cached(workspace_id, ref)
        data = cached if cached is not None else fetched.get(ref)
        if isinstance(data, Exception) or data is None:
            out[ref] = data or ArtifactIntegrityError("artifact blob is missing")
            continue
        try:
            record = await verify_artifact_bytes(
                conn, storage_key=ref[0], workspace_id=workspace_id, data=data
            )
            if record.content_sha256 != ref[1]:
                raise ArtifactIntegrityError("document digest does not match its artifact")
        except Exception as exc:  # noqa: BLE001 — refused bytes are reported, not raised
            out[ref] = exc
            continue
        _remember(workspace_id, ref, data)
        out[ref] = data
    return out


async def read_one_knowledge_bytes(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, ref: KnowledgeRef
) -> bytes:
    """One document's verified bytes; raises the refusal like ``read_verified_artifact`` does."""
    result = (await read_knowledge_bytes(conn, storage, workspace_id=workspace_id, refs=[ref]))[ref]
    if isinstance(result, Exception):
        raise result
    return result
