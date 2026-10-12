"""Exporting a Puck site as a ZIP and as a PDF (Wave 2 Lane A, Task 22)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client
from lumen_api.main import create_app
from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand, garner_site_without_clones, hold_site_images, install_site_inputs, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def site(client: TestClient) -> dict:
    site, brand = hold_site_images(garner_site_without_clones("site_export"), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site


def test_the_zip_holds_every_page_its_bytes_and_folder_links(client: TestClient, site: dict) -> None:
    response = client.get("/documents/site_export/site/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert {"index.html", "analysis/index.html", "manifest.json"} <= names
    held = site["pages"]["/analysis"]["content"][0]["props"]["image"].removeprefix("/asset-store/")
    assert f"assets/{held}.png" in names
    analysis = archive.read("analysis/index.html").decode()
    assert f"../assets/{held}.png" in analysis and f"/asset-store/{held}" not in analysis
    home = archive.read("index.html").decode()
    assert 'href="/analysis/"' in home and "<script" not in home.lower()
    assert "img-src 'self' data: file:" in home
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["delivery"] == "site" and [page["route"] for page in manifest["pages"]] == ["/", "/analysis"]


def test_the_pdf_prints_every_page(client: TestClient, site: dict) -> None:
    response = client.get("/documents/site_export/site/export.pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    with pymupdf.open(stream=response.content, filetype="pdf") as document:
        assert document.page_count >= 2


def test_a_web_document_is_not_exported_as_a_site(client: TestClient, site: dict) -> None:
    web = client.post("/documents", json={"doc_kind": "web", "title": "W"}).json()["document"]
    assert client.get(f"/documents/{web['id']}/site/export").json()["detail"]["code"] == "document.kind_unsupported"
