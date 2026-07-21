"""clue-storage — durable, content-addressed artifact storage (Phase B2 / harness REQ-07)."""

from clue_storage.factory import storage_from_settings
from clue_storage.fs import FsStorage
from clue_storage.protocol import (
    PUBLIC_SCOPE,
    ArtifactNotFound,
    StorageBackend,
    StorageError,
    artifact_key,
    content_address,
)
from clue_storage.s3 import S3Storage

__all__ = [
    "PUBLIC_SCOPE",
    "ArtifactNotFound",
    "FsStorage",
    "S3Storage",
    "StorageBackend",
    "StorageError",
    "artifact_key",
    "content_address",
    "storage_from_settings",
]
