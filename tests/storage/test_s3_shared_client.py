"""S3Storage reuses one client per (event loop, configuration) — no SDK, no MinIO needed.

Research slowness fix (2026-10-03): every storage call used to build a client and a fresh TLS
connection to R2 (~200 ms each from the worker VM).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from clue_storage import ArtifactNotFound, StorageError, close_shared_s3_clients
from clue_storage.s3 import S3Storage


class ConnectionClosedError(Exception):  # noqa: N818 — named like botocore's on purpose
    """Named like botocore's, which is how S3Storage recognises a connection-level failure."""


class _AccessDeniedError(Exception):
    def __init__(self) -> None:
        super().__init__("denied")
        self.response = {
            "Error": {"Code": "AccessDenied"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }


class _MissingError(Exception):
    def __init__(self) -> None:
        super().__init__("missing")
        self.response = {
            "Error": {"Code": "NoSuchKey"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> _Body:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._data


class _Client:
    def __init__(self, store: dict[str, bytes], failures: list[BaseException]) -> None:
        self._store = store
        self._failures = failures

    def _maybe_fail(self) -> None:
        if self._failures:
            raise self._failures.pop(0)

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:  # noqa: N803
        self._maybe_fail()
        self._store[Key] = Body

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self._maybe_fail()
        if Key not in self._store:
            raise _MissingError()
        return {"Body": _Body(self._store[Key])}


class _Context:
    def __init__(self, client: _Client) -> None:
        self.client = client
        self.closed = False

    async def __aenter__(self) -> _Client:
        return self.client

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True


@pytest.fixture
def contexts(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"made": [], "store": {}, "failures": []}

    def factory(self: S3Storage) -> _Context:
        context = _Context(_Client(state["store"], state["failures"]))
        state["made"].append(context)
        return context

    monkeypatch.setattr(S3Storage, "_new_client_context", factory)
    return state


def _storage(endpoint: str = "https://r2.example") -> S3Storage:
    return S3Storage("bucket", endpoint_url=endpoint, access_key_id="k", secret_access_key="s")


def test_many_calls_and_instances_share_one_client(contexts: dict[str, Any]) -> None:
    async def scenario() -> None:
        first, second = _storage(), _storage()
        await first.put("a", b"1", media_type="text/plain")
        await second.put("b", b"2", media_type="text/plain")
        assert await first.get("b") == b"2"
        assert await second.get("a") == b"1"
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert len(contexts["made"]) == 1
    assert contexts["made"][0].closed


def test_a_different_configuration_gets_its_own_client(contexts: dict[str, Any]) -> None:
    async def scenario() -> None:
        await _storage().put("a", b"1", media_type="text/plain")
        await _storage("https://other.example").put("b", b"2", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert len(contexts["made"]) == 2


def test_each_event_loop_gets_its_own_client(contexts: dict[str, Any]) -> None:
    async def one_call() -> None:
        await _storage().put("a", b"1", media_type="text/plain")

    asyncio.run(one_call())
    asyncio.run(one_call())
    assert len(contexts["made"]) == 2


def test_a_connection_error_rebuilds_the_client_once_and_retries(contexts: dict[str, Any]) -> None:
    contexts["failures"].append(ConnectionClosedError("reset by peer"))

    async def scenario() -> None:
        await _storage().put("a", b"1", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert contexts["store"] == {"a": b"1"}
    assert len(contexts["made"]) == 2
    assert contexts["made"][0].closed


def test_a_second_connection_error_surfaces_as_storage_error(contexts: dict[str, Any]) -> None:
    contexts["failures"].extend([ConnectionClosedError("1"), ConnectionClosedError("2")])

    async def scenario() -> None:
        with pytest.raises(StorageError):
            await _storage().put("a", b"1", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())


def test_an_access_error_is_not_retried(contexts: dict[str, Any]) -> None:
    contexts["failures"].append(_AccessDeniedError())

    async def scenario() -> None:
        with pytest.raises(StorageError):
            await _storage().put("a", b"1", media_type="text/plain")
        await close_shared_s3_clients()

    asyncio.run(scenario())
    assert len(contexts["made"]) == 1


def test_a_missing_key_is_still_a_typed_not_found(contexts: dict[str, Any]) -> None:
    async def scenario() -> None:
        with pytest.raises(ArtifactNotFound):
            await _storage().get("nope")
        await close_shared_s3_clients()

    asyncio.run(scenario())
