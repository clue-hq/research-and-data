"""storage_from_settings — the one place the CLUE_STORAGE_* knobs are read (PB-B2.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_config import Secrets, Settings
from clue_storage import FsStorage, S3Storage, StorageError, storage_from_settings


def _secrets(**kwargs: object) -> Secrets:
    return Secrets(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_default_backend_is_fs(tmp_path: object) -> None:
    settings = Settings(_env_file=None, storage_fs_root=str(tmp_path))
    assert settings.storage_backend == "fs"
    assert isinstance(storage_from_settings(settings, _secrets()), FsStorage)


def test_s3_requires_bucket_fails_loud() -> None:
    """A misconfigured s3 selection must never silently fall back to local disk."""
    settings = Settings(_env_file=None, storage_backend="s3")
    with pytest.raises(StorageError, match="CLUE_STORAGE_S3_BUCKET"):
        storage_from_settings(settings, _secrets())


def test_s3_selection_builds_s3_backend() -> None:
    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        storage_s3_bucket="snapshots",
        storage_s3_endpoint_url="http://localhost:9000",
        storage_s3_region="auto",
    )
    secrets = _secrets(storage_s3_access_key_id="ak", storage_s3_secret_access_key="sk")
    assert isinstance(storage_from_settings(settings, secrets), S3Storage)


def test_settings_reject_unknown_backend() -> None:
    with pytest.raises(ValidationError):  # Literal["fs", "s3"]
        Settings(_env_file=None, storage_backend="gcs")


def test_s3_pool_size_comes_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        storage_s3_bucket="b",
        storage_s3_max_pool_connections=7,
    )
    backend = storage_from_settings(settings, Secrets(_env_file=None))
    assert isinstance(backend, S3Storage)
    assert backend._max_pool_connections == 7
