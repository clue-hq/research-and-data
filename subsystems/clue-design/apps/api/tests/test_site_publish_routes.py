"""Publishing a Puck site (Wave 2 Lane A, Task 21)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clue_design.publishes import SITE_DELIVERY_CSP_META
from conftest import make_blob_store, make_client, published, published_html, published_manifest, published_page
from lumen_api.main import create_app
from site_kit_support import (
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    garner_site_without_clones,
    hold_site_images,
    install_site_inputs,
    section_module,
    store_site,
    QUOTE_JS,
)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def stored(client: TestClient, site: dict) -> dict:
    site, brand = hold_site_images(site, garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site


def test_publish_serve_state_republish_and_unpublish(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site_without_clones("site_pub"))
    response = client.post("/documents/site_pub/site/publish", json={"slug": "acme-site"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == "acme-site" and body["url"] == f"{body['public_origin']}/acme-site"
    assert body["routes"] == ["/", "/analysis"] and set(body["page_urls"]) == {"/", "/analysis"}
    html = published_html(workspace_id, "acme-site")
    assert f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">' in html
    assert "<script" not in html.lower()
    assert published_manifest(workspace_id, "acme-site")["delivery"] == "site"
    assert published_page(workspace_id, "acme-site", "/analysis") is not None
    state = client.get("/documents/site_pub/site/publish").json()
    assert state["published"] is True and state["slug"] == "acme-site"
    again = client.post("/documents/site_pub/site/publish", json={"slug": "acme-site"})
    assert again.status_code == 200 and again.json()["previous_available"] is True
    assert client.delete("/web/publishes/acme-site").json()["status"] == "unpublished"


def test_a_missing_agent_section_module_refuses_and_publishes_nothing(client: TestClient, workspace_id: str) -> None:
    site = garner_site_without_clones("site_pub_missing")
    site["agent_sections"] = {"Quote": section_module("Quote", QUOTE_JS).digest}
    stored(client, site)  # install_site_inputs with no modules: the loader returns none
    response = client.post("/documents/site_pub_missing/site/publish", json={"slug": "missing-site"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "site_publish.section_module_missing"
    assert published(workspace_id, "missing-site") is None


def test_a_clone_the_registry_does_not_hold_refuses(client: TestClient, workspace_id: str) -> None:
    stored(client, garner_site("site_pub_clone"))
    response = client.post("/documents/site_pub_clone/site/publish", json={"slug": "clone-site"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "site_publish.clone_unresolved"
    assert published(workspace_id, "clone-site") is None


def test_each_publish_route_refuses_the_other_kind(client: TestClient) -> None:
    stored(client, garner_site_without_clones("site_pub_kind"))
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"}).json()["document"]
    to_site = client.post(f"/documents/{web['id']}/site/publish", json={})
    assert to_site.status_code == 409 and to_site.json()["detail"]["code"] == "document.kind_unsupported"
    to_web = client.post("/documents/site_pub_kind/web/publish", json={})
    assert to_web.status_code == 409 and to_web.json()["detail"]["code"] == "document.kind_unsupported"
