"""deploy/check_r2.py: the R2 bucket and token check, run before anything depends on R2.

The check logic runs here against an in-memory stand-in for ``S3Storage`` (same five methods
the app uses); the live run against R2 is the founder's, with real tokens.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clue_storage import ArtifactNotFound, StorageError

_PATH = Path(__file__).resolve().parents[2] / "deploy" / "check_r2.py"
_spec = importlib.util.spec_from_file_location("check_r2", _PATH)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


class MemoryStore:
    """What the app needs from a bucket, with knobs for each way R2 could be wrong."""

    def __init__(self, *, corrupt: bool = False, unlisted: bool = False, denied: bool = False):
        self.blobs: dict[str, bytes] = {}
        self.corrupt, self.unlisted, self.denied = corrupt, unlisted, denied

    def _gate(self) -> None:
        if self.denied:
            raise StorageError("AccessDenied")

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self._gate()
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        self._gate()
        if key not in self.blobs:
            raise ArtifactNotFound(key)
        return self.blobs[key][::-1] if self.corrupt else self.blobs[key]

    async def exists(self, key: str) -> bool:
        self._gate()
        return key in self.blobs

    async def delete(self, key: str) -> None:
        self._gate()
        self.blobs.pop(key, None)

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        self._gate()
        for key in [] if self.unlisted else list(self.blobs):
            yield key, datetime.now(UTC)

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://{key}"


def _fetch_from(store: MemoryStore):
    return lambda url: store.blobs[url.removeprefix("memory://")]


def test_a_working_bucket_passes_every_step_and_leaves_nothing_behind() -> None:
    store = MemoryStore()
    steps = asyncio.run(check.exercise_bucket(store, fetch=_fetch_from(store)))
    assert steps == ["put", "exists", "get", "list", "presigned fetch", "delete", "gone"]
    assert store.blobs == {}


@pytest.mark.parametrize(
    ("store", "step"),
    [
        (MemoryStore(corrupt=True), "get"),
        (MemoryStore(unlisted=True), "list"),
        (MemoryStore(denied=True), "put"),
    ],
)
def test_a_broken_bucket_fails_at_the_step_that_broke(store: MemoryStore, step: str) -> None:
    with pytest.raises(check.CheckFailed, match=f"^{step}:"):
        asyncio.run(check.exercise_bucket(store, fetch=_fetch_from(store)))
    assert store.blobs == {}, "the probe is removed even when a later step fails"


def test_a_presigned_link_that_serves_other_bytes_fails() -> None:
    store = MemoryStore()
    with pytest.raises(check.CheckFailed, match="^presigned fetch:"):
        asyncio.run(check.exercise_bucket(store, fetch=lambda url: b"something else"))


def test_a_token_refused_on_the_other_bucket_passes() -> None:
    asyncio.run(check.expect_refused(MemoryStore(denied=True), "app token on clue-backups"))


def test_a_token_allowed_on_the_other_bucket_fails_and_its_probe_is_removed() -> None:
    store = MemoryStore()
    with pytest.raises(check.CheckFailed, match="app token on clue-backups: was ALLOWED"):
        asyncio.run(check.expect_refused(store, "app token on clue-backups"))
    assert store.blobs == {}


def test_the_env_file_reads_like_backup_env_and_the_app_settings(tmp_path: Path) -> None:
    path = tmp_path / "r2.env"
    path.write_text(
        "# comment\nCLUE_STORAGE_S3_BUCKET=clue-prod\nR2_BUCKET='clue-backups'\n"
        'AWS_ACCESS_KEY_ID="b"\n',
        encoding="utf-8",
    )
    assert check.parse(path.read_text(encoding="utf-8")) == {
        "CLUE_STORAGE_S3_BUCKET": "clue-prod",
        "R2_BUCKET": "clue-backups",
        "AWS_ACCESS_KEY_ID": "b",
    }


def test_missing_settings_are_named_before_any_request(tmp_path: Path) -> None:
    path = tmp_path / "r2.env"
    path.write_text("CLUE_STORAGE_S3_BUCKET=clue-prod\n", encoding="utf-8")
    missing = check.missing(check.parse(path.read_text(encoding="utf-8")))
    assert "CLUE_STORAGE_S3_ENDPOINT_URL" in missing and "AWS_SECRET_ACCESS_KEY" in missing
    assert "CLUE_STORAGE_S3_BUCKET" not in missing
