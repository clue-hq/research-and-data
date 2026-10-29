"""Web pages and Puck sites have no download (founder ruling 2026-10-13).

"We are providing hosting in our platform only": there is no ZIP and no PDF of a web document or
a site, in the API or anywhere else. Publishing is the only way a page leaves the platform.

Each scenario drives the real composed app (``create_app`` over the Postgres test database, the
test's blob storage, the real core helper, Tailwind compile, site-kit bundles and Chromium) on one
stored document: the four old export URLs answer FastAPI's own 404, and the same document still
publishes and still gets its gallery thumbnail, so the removal took the exports and nothing next
to them.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import fetch_thumbnail, make_blob_store, make_client, published_html
from lumen_api.main import create_app
from site_kit_support import (
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site_without_clones,
    hold_site_images,
    install_site_inputs,
    store_site,
)
from test_web_export import seed_document

#: Every download route a web document or a site used to have.
OLD_EXPORT_PATHS = ("web/export", "web/export.pdf", "site/export", "site/export.pdf")

#: The home page heading of the stored site (``garner_site_without_clones``).
SITE_HOME_HEADING = "7.4% lower medical spend in year one. No plan changes."


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def assert_no_export_route(client: TestClient, document_id: str) -> None:
    for path in OLD_EXPORT_PATHS:
        response = client.get(f"/documents/{document_id}/{path}")
        # FastAPI's own answer for a route that does not exist: no tombstone route, no typed
        # refusal, nothing that could be mistaken for an export that is temporarily unavailable.
        assert response.status_code == 404, f"{path}: {response.status_code} {response.text[:200]}"
        assert response.json() == {"detail": "Not Found"}, path
        assert "attachment" not in response.headers.get("content-disposition", "")


def assert_thumbnail(client: TestClient, document_id: str) -> None:
    response = fetch_thumbnail(client, f"/documents/{document_id}/thumbnail")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(response.content)).format == "PNG"


def test_a_web_page_has_no_download_and_still_publishes_and_gets_its_thumbnail(
    client: TestClient, workspace_id: str
) -> None:
    document_id = seed_document(client)["id"]

    assert_no_export_route(client, document_id)

    published = client.post(
        f"/documents/{document_id}/web/publish", json={"slug": "no-download-web"}
    )
    assert published.status_code == 200, published.text
    assert "Ship faster with Acme" in published_html(workspace_id, "no-download-web")

    assert_thumbnail(client, document_id)


def test_a_site_has_no_download_and_still_publishes_and_gets_its_thumbnail(
    client: TestClient, workspace_id: str
) -> None:
    site, brand = hold_site_images(
        garner_site_without_clones("site_no_download"), garner_brand(), make_blob_store(client.app)
    )
    store_site(site)
    install_site_inputs(client.app, brand)

    assert_no_export_route(client, "site_no_download")

    published = client.post(
        "/documents/site_no_download/site/publish", json={"slug": "no-download-site"}
    )
    assert published.status_code == 200, published.text
    assert SITE_HOME_HEADING in published_html(workspace_id, "no-download-site")

    assert_thumbnail(client, "site_no_download")
