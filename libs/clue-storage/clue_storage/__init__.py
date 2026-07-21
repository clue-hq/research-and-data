"""clue-storage — durable, content-addressed artifact storage (Phase B2 / harness REQ-07)."""

from clue_storage.artifacts import (
    ArtifactRecord,
    get_artifact,
    live_claim_count,
    mark_erased,
    record_artifact,
)
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
from clue_storage.snapshot import PendingSnapshot, SnapshotSink, flush_snapshots

__all__ = [
    "PUBLIC_SCOPE",
    "ArtifactNotFound",
    "ArtifactRecord",
    "FsStorage",
    "PendingSnapshot",
    "S3Storage",
    "SnapshotSink",
    "StorageBackend",
    "StorageError",
    "artifact_key",
    "content_address",
    "flush_snapshots",
    "get_artifact",
    "live_claim_count",
    "mark_erased",
    "record_artifact",
    "storage_from_settings",
]
