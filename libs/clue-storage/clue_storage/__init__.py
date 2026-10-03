"""clue-storage — durable, content-addressed artifact storage (Phase B2 / harness REQ-07)."""

from clue_storage.artifacts import (
    ArtifactIntegrityError,
    ArtifactRecord,
    PurgeResult,
    erase_if_unreferenced,
    get_artifact,
    live_claim_count,
    live_reference_count,
    mark_erased,
    purge_erased_artifacts,
    read_verified_artifact,
    record_artifact,
    release_artifacts,
    retain_artifact,
    sweep_orphan_blobs,
)
from clue_storage.context import bind_snapshots, current_snapshot_sink, current_storage
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
from clue_storage.s3 import S3Storage, close_shared_s3_clients
from clue_storage.snapshot import PendingSnapshot, SnapshotSink, flush_snapshots

__all__ = [
    "PUBLIC_SCOPE",
    "ArtifactNotFound",
    "ArtifactIntegrityError",
    "ArtifactRecord",
    "FsStorage",
    "PendingSnapshot",
    "PurgeResult",
    "S3Storage",
    "close_shared_s3_clients",
    "SnapshotSink",
    "StorageBackend",
    "StorageError",
    "artifact_key",
    "bind_snapshots",
    "content_address",
    "current_snapshot_sink",
    "current_storage",
    "erase_if_unreferenced",
    "flush_snapshots",
    "get_artifact",
    "live_claim_count",
    "live_reference_count",
    "mark_erased",
    "purge_erased_artifacts",
    "record_artifact",
    "release_artifacts",
    "retain_artifact",
    "read_verified_artifact",
    "storage_from_settings",
    "sweep_orphan_blobs",
]
