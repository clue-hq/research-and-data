"""The one-time backfill that brings already-stored AVIF/ICO assets onto the PNG invariant
(`lumen_api/image_containers.py`). Dry-run by default, idempotent, reversible by provenance.

The scenario is the one found live on 2026-10-18: Garner's reversed logo, harvested as AVIF,
sat in the library as `application/octet-stream` with no thumbnail, so the agent could not
view it and cropped a wordmark out of an old ad instead.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from io import BytesIO
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clue_design.storage import SOURCE_KEY_ASSET, design_location
from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from py_lumen_config import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "convert_stored_web_images.py"
RELEASE_HELPER = REPO_ROOT / "target" / "release" / "lumen-api-helper"

pytestmark = pytest.mark.skipif(
    not RELEASE_HELPER.exists(), reason="needs the release lumen-api-helper"
)


def load_script():
    spec = importlib.util.spec_from_file_location("convert_stored_web_images", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # see test_decode_stored_web_fonts.load_script
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def release_helper(monkeypatch) -> None:
    monkeypatch.setattr(settings, "lumen_core_helper", str(RELEASE_HELPER))


@pytest.fixture()
def storage(tmp_path: Path):
    from clue_storage import FsStorage

    return FsStorage(tmp_path / "design-storage")


@pytest.fixture()
def client(tmp_path: Path, storage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=storage))


@pytest.fixture()
def conn():
    dsn = (
        os.environ["CLUE_DATABASE_URL"]
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    with psycopg.connect(dsn) as connection:
        yield connection


def reversed_logo_avif() -> bytes:
    image = Image.new("RGBA", (90, 30), (0, 0, 0, 0))
    for x in range(5, 85):
        for y in range(8, 22):
            image.putpixel((x, y), (255, 255, 255, 255))
    out = BytesIO()
    image.save(out, format="AVIF", quality=95)
    return out.getvalue()


def seed_unreadable_image(client: TestClient, asset_id: str, data: bytes, filename: str) -> str:
    """An AVIF asset exactly as ingestion stored it before 2026-10-18."""
    key = make_blob_store(client.app).register(
        data, media_type="application/octet-stream", source_key=SOURCE_KEY_ASSET
    )
    digest = hashlib.sha256(data).hexdigest()
    HybridRepository().create_asset_record(
        {
            "id": asset_id,
            "label": filename,
            "kind": "other",
            "status": "ready",
            "source": {"kind": "website", "url": f"https://example.test/{filename}"},
            "media": {
                "mime_type": "application/octet-stream",
                "digest": {"algorithm": "sha256", "value": digest},
                "filename": filename,
                "byte_length": len(data),
                "location": design_location(key),
            },
            "provenance": {"created_by": "lumen_ingestion", "notes": []},
            "tags": ["brand-ingestion"],
        }
    )
    return digest


def test_dry_run_changes_nothing(client: TestClient, conn, storage) -> None:
    digest = seed_unreadable_image(
        client, "asset_img_dry", reversed_logo_avif(), "garner-logo.avif"
    )
    summary = load_script().convert_stored_web_images(
        conn, storage, workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"], apply=False
    )
    assert summary.converted == 1 and summary.missing == 0 and summary.failed == 0
    stored = HybridRepository().require_asset_record("asset_img_dry")["asset"]
    assert stored["media"]["digest"]["value"] == digest
    assert stored["media"]["mime_type"] == "application/octet-stream"


def test_apply_converts_keeps_the_id_and_is_idempotent(client: TestClient, conn, storage) -> None:
    avif = reversed_logo_avif()
    old_digest = seed_unreadable_image(client, "asset_img_apply", avif, "garner-logo.avif")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    script = load_script()

    first = script.convert_stored_web_images(conn, storage, workspace_id=workspace_id, apply=True)
    assert first.converted == 1 and first.failed == 0 and first.missing == 0

    stored = HybridRepository().require_asset_record("asset_img_apply")["asset"]
    media = stored["media"]
    new_digest = media["digest"]["value"]
    assert stored["id"] == "asset_img_apply"
    assert new_digest != old_digest
    assert media["mime_type"] == "image/png"
    assert media["filename"] == "garner-logo.png"
    assert media.get("thumbnail"), "the converted asset gets a thumbnail, so view can show it"
    assert stored["kind"] == "raster_image"
    assert stored["label"] == "garner-logo.avif"
    assert stored["source"]["url"] == "https://example.test/garner-logo.avif"
    assert stored["tags"] == ["brand-ingestion"]
    notes = stored["provenance"]["notes"]
    assert any("converted at ingestion: avif -> png" in note for note in notes)
    assert any(f"backfill previous digest sha256:{old_digest}" in note for note in notes)

    row = conn.execute(
        "SELECT kind, mime_type, digest_value, filename FROM design_asset"
        " WHERE asset_id = %s AND workspace_id = %s",
        ("asset_img_apply", workspace_id),
    ).fetchone()
    assert row == ("raster_image", "image/png", new_digest, "garner-logo.png")

    blobs = make_blob_store(client.app)
    assert blobs.has_readable_bytes(new_digest)
    thumb_digest = media["thumbnail"]["location"]["opaque_ref"].rsplit("/", 1)[-1]
    assert blobs.has_readable_bytes(thumb_digest)
    served = client.get("/assets/asset_img_apply/bytes")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert Image.open(BytesIO(served.content)).size == (90, 30)
    # The original blob is kept, so the change can be undone from the provenance note.
    assert blobs.read(old_digest) == avif

    second = script.convert_stored_web_images(conn, storage, workspace_id=workspace_id, apply=True)
    assert second.converted == 0 and second.failed == 0


def test_bytes_that_are_not_avif_or_ico_are_skipped(client: TestClient, conn, storage) -> None:
    seed_unreadable_image(client, "asset_img_other", b"not an image at all" * 8, "mystery.bin")
    summary = load_script().convert_stored_web_images(
        conn, storage, workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"], apply=True
    )
    assert summary.converted == 0 and summary.skipped == 1 and summary.failed == 0
    stored = HybridRepository().require_asset_record("asset_img_other")["asset"]
    assert stored["media"]["mime_type"] == "application/octet-stream"


def test_missing_blob_is_reported_not_fatal(client: TestClient, conn, storage) -> None:
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    HybridRepository().create_asset_record(
        {
            "id": "asset_img_missing",
            "label": "gone.avif",
            "kind": "other",
            "status": "ready",
            "source": {"kind": "website", "url": "https://example.test/gone.avif"},
            "media": {
                "mime_type": "application/octet-stream",
                "digest": {"algorithm": "sha256", "value": "ab" * 32},
                "filename": "gone.avif",
                "byte_length": 10,
                "location": design_location(f"{workspace_id}/design/{'ab' * 32}"),
            },
            "provenance": {"created_by": "lumen_ingestion", "notes": []},
            "tags": [],
        }
    )
    summary = load_script().convert_stored_web_images(
        conn, storage, workspace_id=workspace_id, apply=True
    )
    assert summary.missing == 1 and summary.converted == 0
