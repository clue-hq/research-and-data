"""S3-compatible :class:`~clue_storage.protocol.StorageBackend` (B2.1).

One implementation covers AWS S3, Cloudflare R2, and MinIO — the *endpoint URL* is config
(REQ-07: "endpoint config covers R2/S3/MinIO"), so swapping object stores is a settings change,
never code. The ``aioboto3`` SDK is imported **lazily, only in this module** (the Rule-4
provider-SDK discipline: the SDK name never leaks past its seam; CI's fs-backed path never needs
it installed) and is guarded by a dedicated import-linter contract.

**One shared client per event loop and configuration** (research slowness fix, 2026-10-03). The
original design opened a fresh client per operation on the theory that snapshot traffic was low;
in production research saves hundreds of blobs per job, and every call paid client construction
plus a new TLS handshake to R2 (~200 ms measured from the worker VM, against 3 ms for the
database). Now every ``S3Storage`` with the same configuration, on the same event loop, reuses one
long-lived client and its keep-alive connection pool (``max_pool_connections``) — many call sites
build a fresh ``S3Storage`` per call, so the client cannot live on the instance. Clients are kept
per event loop because an aiohttp session must not cross loops (tests run many loops); a loop's
entry disappears with the loop. :func:`close_shared_s3_clients` closes the current loop's clients
at process shutdown. A connection-level failure discards the client and retries the operation
once on a fresh one; anything else surfaces as before.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from clue_storage.protocol import ArtifactNotFound, StorageError

__all__ = ["DEFAULT_MAX_POOL_CONNECTIONS", "S3Storage", "close_shared_s3_clients"]

DEFAULT_MAX_POOL_CONNECTIONS = 50

# botocore / aiohttp exception class names that mean "the connection broke", matched by name so
# this module never imports those packages at module level.
_CONNECTION_ERROR_NAMES = frozenset(
    {
        "EndpointConnectionError",
        "ConnectionClosedError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "HTTPClientError",
        "ClientConnectorError",
        "ClientOSError",
        "ServerDisconnectedError",
        "ConnectionResetError",
        "BrokenPipeError",
    }
)


@dataclass
class _LoopClients:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # configuration key -> (client context manager, entered client)
    clients: dict[tuple[object, ...], tuple[Any, Any]] = field(default_factory=dict)


_BY_LOOP: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopClients] = (
    weakref.WeakKeyDictionary()
)


def _loop_clients() -> _LoopClients:
    loop = asyncio.get_running_loop()
    held = _BY_LOOP.get(loop)
    if held is None:
        held = _LoopClients()
        _BY_LOOP[loop] = held
    return held


async def close_shared_s3_clients() -> None:
    """Close the current event loop's shared S3 clients (call once, at process shutdown)."""
    held = _BY_LOOP.pop(asyncio.get_running_loop(), None)
    if held is None:
        return
    for context, _client in held.clients.values():
        with contextlib.suppress(Exception):
            await context.__aexit__(None, None, None)


def _is_connection_error(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    for _ in range(5):  # the exception, then a few causes/contexts
        if seen is None:
            return False
        if type(seen).__name__ in _CONNECTION_ERROR_NAMES:
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _s3_sdk() -> tuple[Any, Any]:
    """``(aioboto3, AioConfig)``, imported here and nowhere else; a missing install fails loud
    with the fix."""
    try:
        import aioboto3
        from aiobotocore.config import AioConfig
    except ImportError as exc:
        raise StorageError(
            "aioboto3 is required for the S3 storage backend; install clue-storage[s3]"
        ) from exc
    return aioboto3, AioConfig


def require_s3_sdk() -> None:
    """Refuse at start-up, not at the first read, when the S3 SDK is not installed (live
    2026-10-19: the page origin's image lacked it, and every published asset answered 404)."""
    _s3_sdk()


class S3Storage:
    """Store blobs in an S3-compatible bucket (AWS S3 / R2 / MinIO — endpoint is config)."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        max_pool_connections: int = DEFAULT_MAX_POOL_CONNECTIONS,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._max_pool_connections = max_pool_connections

    def _config_key(self) -> tuple[object, ...]:
        return (
            self._endpoint_url,
            self._region,
            self._access_key_id,
            self._secret_access_key,
            self._max_pool_connections,
        )

    def _new_client_context(self) -> Any:
        """A fresh ``aioboto3`` client context manager (lazy import — the one sanctioned home of
        the SDK; a missing install fails loud with the fix). The test seam."""
        aioboto3, AioConfig = _s3_sdk()
        return aioboto3.Session().client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            config=AioConfig(max_pool_connections=self._max_pool_connections),
        )

    async def _client(self) -> Any:
        held = _loop_clients()
        key = self._config_key()
        cached = held.clients.get(key)
        if cached is None:
            async with held.lock:
                cached = held.clients.get(key)
                if cached is None:
                    context = self._new_client_context()
                    cached = (context, await context.__aenter__())
                    held.clients[key] = cached
        return cached[1]

    async def _discard(self, client: Any) -> None:
        held = _loop_clients()
        key = self._config_key()
        cached = held.clients.get(key)
        if cached is not None and cached[1] is client:
            del held.clients[key]
            with contextlib.suppress(Exception):
                await cached[0].__aexit__(None, None, None)

    async def _call[T](self, operation: Callable[[Any], Awaitable[T]]) -> T:
        client = await self._client()
        try:
            return await operation(client)
        except Exception as exc:
            if not _is_connection_error(exc):
                raise
            await self._discard(client)
        return await operation(await self._client())

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        try:
            await self._call(
                lambda s3: s3.put_object(
                    Bucket=self._bucket, Key=key, Body=data, ContentType=media_type
                )
            )
        except Exception as exc:
            raise StorageError(f"could not store {key!r}: {exc}") from exc

    async def get(self, key: str) -> bytes:
        async def read(s3: Any) -> bytes:
            response = await s3.get_object(Bucket=self._bucket, Key=key)
            async with response["Body"] as body:
                data: bytes = await body.read()
                return data

        try:
            return await self._call(read)
        except Exception as exc:
            if _is_missing_key(exc):
                raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
            raise StorageError(f"could not read {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            # S3 DeleteObject is idempotent (204 for a missing key) — matches the protocol's
            # safe-to-retry DSAR-erasure semantics with no extra existence check.
            await self._call(lambda s3: s3.delete_object(Bucket=self._bucket, Key=key))
        except Exception as exc:
            raise StorageError(f"could not delete {key!r}: {exc}") from exc

    async def exists(self, key: str) -> bool:
        try:
            await self._call(lambda s3: s3.head_object(Bucket=self._bucket, Key=key))
        except Exception as exc:
            if _is_missing_key(exc):
                return False
            raise StorageError(f"could not stat {key!r}: {exc}") from exc
        return True

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        s3 = await self._client()
        try:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket):
                for obj in page.get("Contents", ()):
                    modified: datetime = obj["LastModified"]
                    yield str(obj["Key"]), modified
        except Exception as exc:
            raise StorageError(f"could not list bucket {self._bucket!r}: {exc}") from exc

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        try:
            await self._call(lambda s3: s3.head_object(Bucket=self._bucket, Key=key))
        except Exception as exc:
            if _is_missing_key(exc):
                raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
            raise StorageError(f"could not stat {key!r}: {exc}") from exc
        s3 = await self._client()
        url: str = await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def _is_missing_key(exc: Exception) -> bool:
    """Whether a botocore ClientError means "key/object absent" (404 / NoSuchKey), duck-typed so
    this module never imports botocore's exception types at module level."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error", {})
    code = str(error.get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
