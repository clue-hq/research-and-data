"""Storage test harness (PB-B2): one contract suite, two backends, selected by settings alone.

The ``backend`` fixture is parametrized over ``fs`` and ``s3`` and builds each via
:func:`clue_storage.storage_from_settings` from an explicit :class:`~clue_config.Settings` —
so the suite *is* the fs ↔ S3 swap exit gate: the same tests run green under both with nothing
but the settings object differing.

The S3 leg runs against MinIO (real S3 API — REQ-07's "endpoint config covers R2/S3/MinIO");
it skips gracefully when ``CLUE_TEST_MINIO_ENDPOINT`` is unset or unreachable, mirroring the
reachable-DB gate (M0.3), so the default ``make check`` stays green without MinIO.
"""

from __future__ import annotations

import os
import uuid

import pytest

from clue_config import Secrets, Settings
from clue_storage import StorageBackend, storage_from_settings

# Re-exported for the storage test modules (DRY: the M0.3 sync→async driver).
from tests.db.conftest import run_async as run_async

MINIO_ENDPOINT_ENV = "CLUE_TEST_MINIO_ENDPOINT"
MINIO_ACCESS_KEY_ENV = "CLUE_TEST_MINIO_ACCESS_KEY"
MINIO_SECRET_KEY_ENV = "CLUE_TEST_MINIO_SECRET_KEY"
_TEST_BUCKET = "clue-test-artifacts"


def _minio_pair() -> tuple[Settings, Secrets] | None:
    """The (settings, secrets) selecting the MinIO-backed S3 leg, or ``None`` when unset."""
    endpoint = os.environ.get(MINIO_ENDPOINT_ENV)
    if not endpoint:
        return None
    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        storage_s3_bucket=_TEST_BUCKET,
        storage_s3_endpoint_url=endpoint,
        storage_s3_region="us-east-1",
    )
    secrets = Secrets(
        _env_file=None,
        storage_s3_access_key_id=os.environ.get(MINIO_ACCESS_KEY_ENV, "clueminio"),
        storage_s3_secret_access_key=os.environ.get(MINIO_SECRET_KEY_ENV, "clueminio123"),
    )
    return settings, secrets


async def _ensure_bucket(settings: Settings, secrets: Secrets) -> bool:
    """Create the test bucket if needed; ``False`` when MinIO is unreachable (→ skip)."""
    import aioboto3  # test-harness only; product code reaches the SDK via clue_storage.s3

    access = secrets.storage_s3_access_key_id
    secret = secrets.storage_s3_secret_access_key
    session = aioboto3.Session()
    try:
        async with session.client(
            "s3",
            endpoint_url=settings.storage_s3_endpoint_url,
            region_name=settings.storage_s3_region,
            aws_access_key_id=access.get_secret_value() if access else None,
            aws_secret_access_key=secret.get_secret_value() if secret else None,
        ) as s3:
            try:
                await s3.head_bucket(Bucket=settings.storage_s3_bucket)
            except Exception:
                await s3.create_bucket(Bucket=settings.storage_s3_bucket)
        return True
    except Exception:
        return False


@pytest.fixture(params=["fs", "s3"])
def backend(request: pytest.FixtureRequest, tmp_path: object) -> StorageBackend:
    """The configured backend under test — built from settings alone (the swap gate)."""
    if request.param == "fs":
        settings = Settings(_env_file=None, storage_backend="fs", storage_fs_root=str(tmp_path))
        return storage_from_settings(settings, Secrets(_env_file=None))
    pair = _minio_pair()
    if pair is None:
        pytest.skip(f"{MINIO_ENDPOINT_ENV} unset; start MinIO to exercise the S3 leg")
    settings, secrets = pair
    if not run_async(_ensure_bucket(settings, secrets)):
        pytest.skip(f"MinIO at {settings.storage_s3_endpoint_url} unreachable")
    return storage_from_settings(settings, secrets)


@pytest.fixture
def unique_key() -> str:
    """A fresh workspace-scoped key per test, so the shared MinIO bucket never cross-talks."""
    return f"ws_{uuid.uuid4().hex}/{uuid.uuid4().hex}"
