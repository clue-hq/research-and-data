"""The StorageBackend contract suite (PB-B2.1) — every test runs under fs AND S3-on-MinIO.

The ``backend`` fixture parametrization is the exit gate: a behavior difference between the two
implementations fails here, and the only thing that varies between legs is the ``Settings``
object (the fs ↔ S3 swap is config alone).
"""

from __future__ import annotations

import pytest

from clue_storage import (
    ArtifactNotFound,
    FsStorage,
    StorageError,
    artifact_key,
    content_address,
)
from clue_storage.protocol import StorageBackend
from tests.storage.conftest import run_async


def test_put_get_round_trip_byte_identical(backend: StorageBackend, unique_key: str) -> None:
    data = b"<html>\x00\xff binary-safe evidence bytes</html>"
    run_async(backend.put(unique_key, data, media_type="text/html"))
    assert run_async(backend.get(unique_key)) == data


def test_exists_reflects_lifecycle(backend: StorageBackend, unique_key: str) -> None:
    assert run_async(backend.exists(unique_key)) is False
    run_async(backend.put(unique_key, b"x", media_type="text/plain"))
    assert run_async(backend.exists(unique_key)) is True
    run_async(backend.delete(unique_key))
    assert run_async(backend.exists(unique_key)) is False


def test_put_identical_bytes_is_idempotent(backend: StorageBackend, unique_key: str) -> None:
    """Re-storing the same content at its content-addressed key is a no-op overwrite."""
    data = b"same bytes"
    run_async(backend.put(unique_key, data, media_type="text/plain"))
    run_async(backend.put(unique_key, data, media_type="text/plain"))
    assert run_async(backend.get(unique_key)) == data


def test_get_missing_raises_typed_not_found(backend: StorageBackend, unique_key: str) -> None:
    with pytest.raises(ArtifactNotFound):
        run_async(backend.get(unique_key))


def test_delete_missing_is_a_noop(backend: StorageBackend, unique_key: str) -> None:
    """DSAR erasure must be safe to retry — deleting an absent key never raises."""
    run_async(backend.delete(unique_key))
    run_async(backend.delete(unique_key))


def test_presign_returns_a_reference(backend: StorageBackend, unique_key: str) -> None:
    run_async(backend.put(unique_key, b"payload", media_type="text/plain"))
    ref = run_async(backend.presign(unique_key, expires_in=60))
    assert isinstance(ref, str) and unique_key.rsplit("/", 1)[-1] in ref


def test_presign_missing_raises(backend: StorageBackend, unique_key: str) -> None:
    with pytest.raises(ArtifactNotFound):
        run_async(backend.presign(unique_key))


def test_list_blobs_surfaces_stored_keys_with_utc_mtime(
    backend: StorageBackend, unique_key: str
) -> None:
    """The reconciliation read (orphan-blob sweep): a stored key appears with a tz-aware UTC
    last-modified; a deleted key disappears."""

    async def listing() -> dict[str, object]:
        return {key: modified async for key, modified in backend.list_blobs()}

    run_async(backend.put(unique_key, b"listed", media_type="text/plain"))
    entries = run_async(listing())
    assert unique_key in entries
    modified = entries[unique_key]
    assert getattr(modified, "tzinfo", None) is not None  # tz-aware
    run_async(backend.delete(unique_key))
    assert unique_key not in run_async(listing())


# --- content addressing (pure) ------------------------------------------------


def test_content_address_is_sha256_of_bytes() -> None:
    assert content_address(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert content_address(b"a") != content_address(b"b")


def test_artifact_key_is_workspace_scoped() -> None:
    sha = content_address(b"same bytes")
    assert artifact_key("ws_1", sha) == f"ws_1/{sha}"
    assert artifact_key("ws_2", sha) != artifact_key("ws_1", sha)  # never cross-tenant dedup
    assert artifact_key(None, sha) == f"public/{sha}"


# --- fs-specific hardening ----------------------------------------------------


def test_fs_rejects_traversal_keys(tmp_path: object) -> None:
    fs = FsStorage(str(tmp_path))
    for bad in ("../escape", "/abs/path", "a/../../b"):
        with pytest.raises(StorageError):
            run_async(fs.put(bad, b"x", media_type="text/plain"))


def test_fs_put_creates_nested_scope_dirs(tmp_path: object) -> None:
    fs = FsStorage(str(tmp_path))
    key = artifact_key("ws_nested", content_address(b"data"))
    run_async(fs.put(key, b"data", media_type="text/plain"))
    assert run_async(fs.get(key)) == b"data"
    assert run_async(fs.presign(key)).startswith("file://")
