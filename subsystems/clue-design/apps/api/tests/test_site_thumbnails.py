"""Gallery thumbnails for Puck sites (Wave 2 Lane A, Task 18)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import make_blob_store, make_client
from lumen_api import site_publish
from lumen_api.main import create_app
from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, install_site_inputs, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def stored(client: TestClient, document_id: str) -> None:
    site, brand = hold_site_images(garner_site(document_id), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)


def test_a_site_thumbnail_is_captured_once_then_served_from_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    stored(client, "site_thumb")
    first = client.get("/documents/site_thumb/thumbnail?v=0")
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(first.content)).size == (724, 543)

    def must_not_run(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("a cached thumbnail must not be captured again")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", must_not_run)
    assert client.get("/documents/site_thumb/thumbnail?v=0").content == first.content


def test_a_site_thumbnail_without_its_brand_is_a_typed_502(client: TestClient) -> None:
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    stored(client, "site_thumb_nobrand")
    client.app.state.site_brand_loader = brand_loader_not_composed
    response = client.get("/documents/site_thumb_nobrand/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "thumbnail.render_failed"


def test_a_failed_site_render_is_labelled_render_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api.site_render import RENDER_TIMEOUT, SiteRenderError

    stored(client, "site_thumb_slow")

    def slow(*_args: object, **_kwargs: object) -> bytes:
        raise SiteRenderError(RENDER_TIMEOUT, "the site did not render within 20s")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", slow)
    response = client.get("/documents/site_thumb_slow/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "thumbnail.render_failed", "message": "the site did not render within 20s"}
