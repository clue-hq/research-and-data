"""S3-compatible :class:`~clue_storage.protocol.StorageBackend` (B2.1).

One implementation covers AWS S3, Cloudflare R2, and MinIO — the *endpoint URL* is config
(REQ-07: "endpoint config covers R2/S3/MinIO"), so swapping object stores is a settings change,
never code. The ``aioboto3`` SDK is imported **lazily, only in this module** (the Rule-4
provider-SDK discipline: the SDK name never leaks past its seam; CI's fs-backed path never needs
it installed) and is guarded by a dedicated import-linter contract.

A fresh client context is opened per operation. Snapshot traffic is one blob per *paid* fetch —
low volume by construction — so per-call client setup is noise next to the network round-trip,
and it keeps this class free of connection lifecycle state (nothing to close, safe across event
loops in tests).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from clue_storage.protocol import ArtifactNotFound, StorageError


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
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key

    def _client(self) -> Any:
        """An ``aioboto3`` S3 client context manager (lazy import — the one sanctioned home of
        the SDK; a missing install fails loud with the fix, mirroring ``PypdfTextExtractor``)."""
        try:
            import aioboto3
        except ImportError as exc:  # pragma: no cover - CI installs the s3 extra
            raise StorageError(
                "aioboto3 is required for the S3 storage backend; install clue-storage[s3]"
            ) from exc
        session = aioboto3.Session()
        return session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
        )

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        async with self._client() as s3:
            try:
                await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=media_type)
            except Exception as exc:
                raise StorageError(f"could not store {key!r}: {exc}") from exc

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
            except Exception as exc:
                if _is_missing_key(exc):
                    raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
                raise StorageError(f"could not read {key!r}: {exc}") from exc
            async with response["Body"] as body:
                data: bytes = await body.read()
                return data

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            try:
                # S3 DeleteObject is idempotent (204 for a missing key) — matches the protocol's
                # safe-to-retry DSAR-erasure semantics with no extra existence check.
                await s3.delete_object(Bucket=self._bucket, Key=key)
            except Exception as exc:
                raise StorageError(f"could not delete {key!r}: {exc}") from exc

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except Exception as exc:
                if _is_missing_key(exc):
                    return False
                raise StorageError(f"could not stat {key!r}: {exc}") from exc
            return True

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        async with self._client() as s3:
            try:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=self._bucket):
                    for obj in page.get("Contents", ()):
                        modified: datetime = obj["LastModified"]
                        yield str(obj["Key"]), modified
            except Exception as exc:
                raise StorageError(f"could not list bucket {self._bucket!r}: {exc}") from exc

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)  # absent → typed not-found
            except Exception as exc:
                if _is_missing_key(exc):
                    raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
                raise StorageError(f"could not stat {key!r}: {exc}") from exc
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
