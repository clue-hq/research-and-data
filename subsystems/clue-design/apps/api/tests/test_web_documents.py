from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def create_web_document(client: TestClient, **extra) -> dict:
    response = client.post(
        "/documents", json={"doc_kind": "web", "title": "My site", **extra}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "created"
    return payload["document"]


def test_create_web_document(client: TestClient) -> None:
    document = create_web_document(client)
    assert document["doc_kind"] == "web"
    assert document["title"] == "My site"
    assert document["artifact_type"] == "website"
    assert document["medium"] == "web"


def test_get_web_document_returns_webdoc_payload(client: TestClient) -> None:
    created = create_web_document(client)

    response = client.get(f"/documents/{created['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["doc_kind"] == "web"
    # A WebDoc reuses the "scene" storage key; the editor branches on doc_kind.
    web_doc = body["scene"]
    assert web_doc["schema_version"] == 1
    assert len(web_doc["pages"]) == 1
    assert web_doc["pages"][0]["route"] == "/"


def test_web_document_rejects_operations(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [{"kind": "update_document", "patch": {}}]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_web_document_rejects_preflight(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(f"/documents/{document['id']}/preflight", json={})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_web_document_rejects_export(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(f"/documents/{document['id']}/export", json={})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_scene_document_still_created_as_scene(client: TestClient) -> None:
    response = client.post(
        "/documents", json={"title": "Hospital Letter", "scene": minimal_scene()}
    )
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["doc_kind"] == "scene"


def test_bogus_doc_kind_rejected(client: TestClient) -> None:
    response = client.post("/documents", json={"doc_kind": "bogus", "title": "x"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_web_document_brand_kit_ref_stored_in_theme(client: TestClient) -> None:
    document = create_web_document(
        client, brand_kit_ref={"id": "platform_default", "version": 1}
    )

    response = client.get(f"/documents/{document['id']}")
    assert response.status_code == 200, response.text
    theme = response.json()["scene"]["theme"]
    # P0 stores the ref verbatim; no validation against the kits table.
    assert theme["brand_kit"] == {"id": "platform_default", "version": 1}
