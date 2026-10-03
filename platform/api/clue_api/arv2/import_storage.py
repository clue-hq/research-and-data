"""Storage for one dossier import: prefetched reads, deferred concurrent uploads.

Research slowness fix (2026-10-03, spec part 3b). A dossier import runs inside its caller's
transaction and, finding by finding, read the research-context manifest, each cited source, and
uploaded proposal and disposition receipts — one R2 round trip at a time (~2.5 s per finding in
production). This wrapper lets the import fetch everything it will read up front, concurrently,
and send its uploads together just before it returns. It only changes where bytes come from and
when they leave: every artifact row check in ``read_verified_artifact`` still runs inside the
transaction, rows are still recorded before ``put`` is called, and a failed upload still raises
before the caller commits.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable
from datetime import datetime

from clue_storage import ArtifactNotFound, StorageBackend

__all__ = ["IMPORT_STORAGE_CONCURRENCY", "ImportStorage"]

IMPORT_STORAGE_CONCURRENCY = 8


class ImportStorage:
    def __init__(
        self, inner: StorageBackend, *, concurrency: int = IMPORT_STORAGE_CONCURRENCY
    ) -> None:
        self._inner = inner
        self._limit = asyncio.Semaphore(concurrency)
        self._bytes: dict[str, bytes] = {}
        self._pending: dict[str, tuple[bytes, str]] = {}

    async def prefetch(self, keys: Iterable[str]) -> None:
        async def one(key: str) -> None:
            # A missing key is left for the verified read inside the transaction to refuse.
            async with self._limit:
                with contextlib.suppress(ArtifactNotFound):
                    self._bytes[key] = await self._inner.get(key)

        wanted = sorted({key for key in keys if key and key not in self._bytes})
        await asyncio.gather(*(one(key) for key in wanted))

    async def get(self, key: str) -> bytes:
        held = self._bytes.get(key)
        return held if held is not None else await self._inner.get(key)

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self._bytes[key] = data
        self._pending[key] = (data, media_type)

    async def flush(self) -> None:
        pending, self._pending = self._pending, {}

        async def one(key: str, data: bytes, media_type: str) -> None:
            async with self._limit:
                await self._inner.put(key, data, media_type=media_type)

        await asyncio.gather(*(one(k, d, m) for k, (d, m) in pending.items()))

    async def exists(self, key: str) -> bool:
        return key in self._pending or await self._inner.exists(key)

    async def delete(self, key: str) -> None:
        self._bytes.pop(key, None)
        self._pending.pop(key, None)
        await self._inner.delete(key)

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        if key in self._pending:
            await self.flush()
        return await self._inner.presign(key, expires_in=expires_in)

    def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return self._inner.list_blobs()
