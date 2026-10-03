"""Settings-driven backend selection — the fs ↔ S3 swap is config alone (B2.1 exit gate).

``storage_from_settings`` is the **only** reader of the ``CLUE_STORAGE_*`` knobs; every consumer
takes an injected :class:`~clue_storage.protocol.StorageBackend` and never learns which impl it
holds. Credentials come from :class:`clue_config.Secrets` (SecretStr), never from the non-secret
``Settings`` — the same split the gateway/db seams use.
"""

from __future__ import annotations

from clue_config import Secrets, Settings
from clue_storage.fs import FsStorage
from clue_storage.protocol import StorageBackend, StorageError
from clue_storage.s3 import S3Storage


def storage_from_settings(
    settings: Settings | None = None, secrets: Secrets | None = None
) -> StorageBackend:
    """Build the configured backend: ``CLUE_STORAGE_BACKEND=fs`` (default) or ``s3``.

    ``s3`` requires ``CLUE_STORAGE_S3_BUCKET`` (fails loud, never a silent fs fallback — a
    misconfigured store must not quietly write snapshots to a local disk that gets wiped).
    """
    settings = settings if settings is not None else Settings()
    if settings.storage_backend == "fs":
        return FsStorage(settings.storage_fs_root)
    if settings.storage_s3_bucket is None:
        raise StorageError(
            "CLUE_STORAGE_BACKEND=s3 requires CLUE_STORAGE_S3_BUCKET; refusing to fall back to fs"
        )
    secrets = secrets if secrets is not None else Secrets()
    access_key = secrets.storage_s3_access_key_id
    secret_key = secrets.storage_s3_secret_access_key
    return S3Storage(
        settings.storage_s3_bucket,
        endpoint_url=settings.storage_s3_endpoint_url,
        region=settings.storage_s3_region,
        access_key_id=access_key.get_secret_value() if access_key else None,
        secret_access_key=secret_key.get_secret_value() if secret_key else None,
        max_pool_connections=settings.storage_s3_max_pool_connections,
    )
