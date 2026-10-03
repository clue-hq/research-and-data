"""ImportStorage: prefetched reads, deferred concurrent uploads, failures surface."""

from __future__ import annotations

import asyncio
import time

import pytest

from clue_api.arv2.import_storage import ImportStorage
from clue_storage import ArtifactNotFound, StorageError


class _Slow:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {"a": b"A", "b": b"B", "c": b"C"}
        self.gets: list[str] = []
        self.puts: list[str] = []
        self.fail_put = False

    async def get(self, key: str) -> bytes:
        self.gets.append(key)
        await asyncio.sleep(0.2)
        if key not in self.data:
            raise ArtifactNotFound(key)
        return self.data[key]

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        await asyncio.sleep(0.2)
        if self.fail_put:
            raise StorageError("upload failed")
        self.puts.append(key)
        self.data[key] = data

    async def exists(self, key: str) -> bool:
        return key in self.data


def test_prefetch_runs_concurrently_and_serves_reads_from_memory() -> None:
    async def scenario() -> None:
        inner = _Slow()
        staged = ImportStorage(inner, concurrency=8)  # type: ignore[arg-type]
        started = time.monotonic()
        await staged.prefetch(["a", "b", "c", "a"])
        assert time.monotonic() - started < 0.45
        assert await staged.get("b") == b"B"
        assert sorted(inner.gets) == ["a", "b", "c"]

    asyncio.run(scenario())


def test_a_missing_key_at_prefetch_is_left_for_the_real_read_to_refuse() -> None:
    async def scenario() -> None:
        staged = ImportStorage(_Slow(), concurrency=8)  # type: ignore[arg-type]
        await staged.prefetch(["nope"])
        with pytest.raises(ArtifactNotFound):
            await staged.get("nope")

    asyncio.run(scenario())


def test_uploads_are_deferred_then_sent_concurrently_and_readable_before_flush() -> None:
    async def scenario() -> None:
        inner = _Slow()
        staged = ImportStorage(inner, concurrency=8)  # type: ignore[arg-type]
        for key in ("p1", "p2", "p3"):
            await staged.put(key, key.encode(), media_type="application/json")
        assert inner.puts == []
        assert await staged.get("p2") == b"p2"
        started = time.monotonic()
        await staged.flush()
        assert time.monotonic() - started < 0.45
        assert sorted(inner.puts) == ["p1", "p2", "p3"]

    asyncio.run(scenario())


def test_a_failed_upload_raises_from_flush() -> None:
    async def scenario() -> None:
        inner = _Slow()
        inner.fail_put = True
        staged = ImportStorage(inner, concurrency=8)  # type: ignore[arg-type]
        await staged.put("p1", b"x", media_type="application/json")
        with pytest.raises(StorageError):
            await staged.flush()

    asyncio.run(scenario())
