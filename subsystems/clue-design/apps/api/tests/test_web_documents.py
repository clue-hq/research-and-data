from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
VALID_STYLES_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/styles/valid_insight_health.styles"
)


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


def test_approval_themes_only_documents_created_after_it(client: TestClient) -> None:
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": VALID_STYLES_PATH.read_text(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text

    before = create_web_document(client)
    before_scene = client.get(f"/documents/{before['id']}").json()["scene"]
    assert before_scene["theme"].get("brand_kit") is None

    approved = client.post(
        "/brand-kits/brand_kit_insight_health/approval",
        json={"approval_status": "approved"},
    )
    assert approved.status_code == 200, approved.text

    # Stamp-at-creation is not a render-time fallback: approval leaves the old row untouched.
    unchanged = client.get(f"/documents/{before['id']}").json()["scene"]
    assert unchanged["theme"].get("brand_kit") is None

    after = create_web_document(client)
    after_scene = client.get(f"/documents/{after['id']}").json()["scene"]
    assert after_scene["theme"]["brand_kit"] == {
        "id": "brand_kit_insight_health",
        "version": 4,
    }

    theme_response = client.get(f"/documents/{after['id']}/web/theme")
    assert theme_response.status_code == 200, theme_response.text
    theme = theme_response.json()["theme"]
    # These values distinguish the compiled client kit from the platform-default theme.
    assert theme["tokens"]["primary"].lower() != "#111827"
    assert "Source Sans 3" in theme["display_family"]


def _empty_page(page_id: str, route: str, name: str = "Pricing") -> dict:
    """The smallest legal WebPage: its root Container alone, no children."""
    root = f"root_{page_id}"
    return {
        "id": page_id,
        "name": name,
        "route": route,
        "root": root,
        "nodes": {root: {"id": root, "kind": "container", "classes": "", "children": []}},
    }


def test_add_page_operation_round_trips(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [{"kind": "add_page", "page": _empty_page("pricing", "/pricing")}],
            "base_version": document["current_version"],
            "intent": "add pricing page",
        },
    )
    assert response.status_code == 200, response.text
    # The route answers with the document HEADER only (id/current_version/doc_kind),
    # never the scene — so the page is proven by reading the document back.
    scene = client.get(f"/documents/{document['id']}").json()["scene"]
    routes = [page["route"] for page in scene["pages"]]
    assert routes == ["/", "/pricing"]


def test_add_page_with_a_bad_route_is_refused_whole(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [{"kind": "add_page", "page": _empty_page("x", "/Bad Route")}]},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    # The route flattens EVERY checked-apply rejection to one envelope code and
    # keeps the engine's own sentence as the message, so the engine's
    # `op.route_invalid` reaches the client as prose, not as a code. This
    # message is emitted by that branch alone (`ops.rs`, AddPage → route_is_valid),
    # so asserting it verbatim pins the engine's route refusal, not merely "a 422".
    assert detail["code"] == "web_operations.invalid"
    assert detail["message"] == "route `/Bad Route` is not a valid site route"
    # ...and the engine's own refusal code rides alongside the flattened
    # envelope code, so a client can branch on WHICH refusal this was.
    assert detail["engine_code"] == "op.route_invalid"

    # Refused WHOLE: the mutated document is never returned nor persisted.
    again = client.get(f"/documents/{document['id']}").json()
    assert len(again["scene"]["pages"]) == 1
    assert again["current_version"] == document["current_version"]


def test_render_targets_the_requested_page(client: TestClient) -> None:
    document = create_web_document(client)
    client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [{"kind": "add_page", "page": _empty_page("pricing", "/pricing")}]},
    )
    home = client.get(
        f"/documents/{document['id']}/web/render", params={"runtime_src": "/x.js"}
    )
    pricing = client.get(
        f"/documents/{document['id']}/web/render",
        params={"runtime_src": "/x.js", "page_id": "pricing"},
    )
    assert home.status_code == 200, home.text
    assert pricing.status_code == 200, pricing.text
    # Editor mode instruments every node with `data-node-id` (see
    # test_web_turns.py::test_web_render_editor_contains_node_ids), so the
    # pricing page's root node id is the proof that the render targeted it.
    assert 'data-node-id="root_pricing"' in pricing.json()["html"]
    assert 'data-node-id="root_pricing"' not in home.json()["html"]


def test_render_unknown_page_is_a_typed_404(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.get(
        f"/documents/{document['id']}/web/render",
        params={"runtime_src": "/x.js", "page_id": "nope"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "web_render.page_missing"
