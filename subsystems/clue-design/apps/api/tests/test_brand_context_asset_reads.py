"""The brand-context page's asset reads: one batch for records, revalidated (not re-downloaded) bytes.

Production 2026-10-03: the page read every kit asset's record one request at a time (27 per
load) and every image's full bytes with no cache header (899 downloads in 30 minutes), queueing
design-api to a 30 s median per image. Asset bytes can change under the same id (re-registering
an asset replaces its record), so bytes are revalidated by their content digest rather than
cached as immutable.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clue_design.storage import SOURCE_KEY_ASSET
from clue_storage import FsStorage
from conftest import make_blob_store, make_client

from lumen_api import main as api_main
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _png(color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, "PNG")
    return buffer.getvalue()


def _stored(client: TestClient, data: bytes) -> dict:
    make_blob_store(client.app).register(
        data, media_type="image/png", source_key=SOURCE_KEY_ASSET
    )
    digest = hashlib.sha256(data).hexdigest()
    return {
        "provider": "local-store",
        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
        "url": None,
    }, digest


def _asset(client: TestClient, asset_id: str, color: str, *, thumbnail: bool = False) -> str:
    location, digest = _stored(client, _png(color))
    media = {
        "mime_type": "image/png",
        "filename": f"{asset_id}.png",
        "byte_length": 1,
        "digest": {"algorithm": "sha256", "value": digest},
        "location": location,
    }
    if thumbnail:
        thumb_location, _ = _stored(client, _png("white"))
        media["thumbnail"] = {"mime_type": "image/png", "location": thumb_location}
    HybridRepository().create_asset_record(
        {
            "id": asset_id,
            "label": asset_id,
            "kind": "raster_image",
            "status": "ready",
            "source": {"kind": "uploaded"},
            "media": media,
            "raster": {"pixel_width": 4, "pixel_height": 4},
            "vector": None,
            "font": None,
            "logo": None,
            "license": None,
            "provenance": {"created_by": "user", "created_at": "2026-10-04T00:00:00Z"},
            "tags": [],
        }
    )
    return digest


def test_batch_records_return_each_visible_asset_in_one_request(client: TestClient) -> None:
    _asset(client, "asset_batch_a", "red")
    _asset(client, "asset_batch_b", "blue")
    response = client.get("/assets/records", params={"asset_ids": "asset_batch_a,asset_batch_b,nope"})
    assert response.status_code == 200, response.text
    records = response.json()["assets"]
    assert set(records) == {"asset_batch_a", "asset_batch_b"}
    single = client.get("/assets/asset_batch_a").json()
    # The same envelope the single-asset route serves, so the page parses both identically.
    assert records["asset_batch_a"] == single


def test_bytes_carry_a_digest_etag_and_a_short_private_cache(client: TestClient) -> None:
    digest = _asset(client, "asset_etag", "green")
    response = client.get("/assets/asset_etag/bytes")
    assert response.status_code == 200
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["cache-control"] == "private, max-age=300"


def test_a_matching_revalidation_is_a_304_without_reading_storage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = _asset(client, "asset_revalidate", "purple")

    def unreachable(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("a matching If-None-Match must not read the bytes")

    monkeypatch.setattr(api_main, "read_asset_bytes", unreachable)
    response = client.get("/assets/asset_revalidate/bytes", headers={"If-None-Match": f'"{digest}"'})
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == f'"{digest}"'


def test_a_stale_revalidation_gets_the_new_bytes(client: TestClient) -> None:
    _asset(client, "asset_stale", "orange")
    response = client.get("/assets/asset_stale/bytes", headers={"If-None-Match": '"old-digest"'})
    assert response.status_code == 200
    assert response.content == _png("orange")


def test_thumbnails_revalidate_by_their_own_digest(client: TestClient) -> None:
    _asset(client, "asset_thumb", "black", thumbnail=True)
    first = client.get("/assets/asset_thumb/thumbnail")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, max-age=300"
    again = client.get(
        "/assets/asset_thumb/thumbnail", headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
