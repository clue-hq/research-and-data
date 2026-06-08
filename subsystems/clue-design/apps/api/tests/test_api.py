from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "api.sqlite3")
    return TestClient(app)


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def preflightable_scene() -> dict:
    scene = minimal_scene()
    slot = scene["slots"]["slot_contact_name"]
    slot["formatting"]["max_length"] = None
    slot["validation"]["samples"] = []
    slot["validation"]["max_length"] = None
    return scene


def create_document(client: TestClient, scene: Optional[dict] = None) -> dict:
    response = client.post(
        "/documents",
        json={"title": "Hospital Letter", "scene": scene or minimal_scene()},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "created"
    assert "scene" not in payload["document"]
    return payload["document"]


def title_operation(title: str) -> dict:
    return {
        "kind": "update_document",
        "patch": {
            "title": {"kind": "set", "value": title},
            "artifact_type": {"kind": "unchanged"},
            "medium": {"kind": "unchanged"},
            "brand_kit": {"kind": "unchanged"},
        },
    }


def invalid_insert_operation() -> dict:
    return {
        "kind": "insert_node",
        "parent": {"kind": "page", "id": "missing_page"},
        "index": 0,
        "node": {
            "id": "node_orphan",
            "name": None,
            "kind": {"kind": "rect"},
            "transform": {
                "x": 0.0,
                "y": 0.0,
                "rotation": 0.0,
                "skew_x": 0.0,
                "skew_y": 0.0,
                "flip_x": False,
                "flip_y": False,
            },
            "size": {
                "width": {"kind": "fixed", "value": 10.0},
                "height": {"kind": "fixed", "value": 10.0},
            },
            "children": [],
            "fills": [],
            "strokes": [],
            "corner": {
                "top_left": 0.0,
                "top_right": 0.0,
                "bottom_right": 0.0,
                "bottom_left": 0.0,
            },
            "opacity": 1.0,
            "clip": False,
            "layout": None,
            "computed": None,
            "locked": False,
        },
    }


def test_create_and_load_document_preserves_canonical_scene(client: TestClient) -> None:
    scene = minimal_scene()
    document = create_document(client, scene)

    response = client.get(f"/documents/{document['id']}")
    assert response.status_code == 200
    loaded = response.json()

    assert loaded["scene"] == scene
    assert loaded["current_version"] == 0
    assert loaded["status"] == "draft"
    assert document["counts"]["nodes"] == 1


def test_apply_operations_updates_scene_and_ordered_history(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [title_operation("Updated Letter")],
            "actor": {"kind": "agent", "id": "agent_design"},
            "source": "agent",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["document"]["title"] == "Updated Letter"
    assert payload["operation_application"]["applied_operations"] == 1
    assert "scene" not in payload["document"]

    history = client.get(f"/documents/{document['id']}/operations").json()
    assert [entry["sequence"] for entry in history] == [1]
    assert history[0]["source"] == "agent"
    assert history[0]["operation"]["patch"]["title"]["value"] == "Updated Letter"


def test_invalid_operation_batch_does_not_update_scene_or_history(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [invalid_insert_operation()]},
    )
    assert response.status_code == 422

    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["scene"]["meta"]["title"] == "Hospital Letter"
    assert client.get(f"/documents/{document['id']}/operations").json() == []


def test_snapshot_stores_immutable_scene_at_version(client: TestClient) -> None:
    document = create_document(client)
    snapshot_payload = client.post(
        f"/documents/{document['id']}/snapshots",
        json={"snapshot_id": "snap_before_edit", "reason": "before edit"},
    ).json()
    snapshot = snapshot_payload["snapshot"]
    assert snapshot_payload["schema_version"] == 1
    assert "scene" not in snapshot

    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("After Snapshot")]},
    )
    loaded_snapshot = client.get(
        f"/documents/{document['id']}/snapshots/{snapshot['snapshot_id']}"
    ).json()

    assert loaded_snapshot["scene"]["meta"]["title"] == "Hospital Letter"
    assert loaded_snapshot["version"] == 0


def test_finalize_creates_immutable_template_revision(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/finalize",
        json={"template_revision_id": "tmpl_hospital_letter"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    revision = payload["template_revision"]
    assert payload["schema_version"] == 1
    assert payload["document"]["status"] == "finalized"
    assert "scene" not in revision

    edited_scene = copy.deepcopy(client.get(f"/documents/{document['id']}").json()["scene"])
    edited_scene["meta"]["title"] = "Edited After Finalize"
    replace = client.put(f"/documents/{document['id']}/scene", json={"scene": edited_scene})
    assert replace.status_code == 409, replace.text
    assert replace.json()["detail"]["code"] == "document.finalized"

    current = client.get(f"/documents/{document['id']}").json()
    assert current["scene"]["meta"]["title"] == "Hospital Letter"

    loaded_revision = client.get("/template-revisions/tmpl_hospital_letter").json()
    assert loaded_revision["scene"]["meta"]["status"]["kind"] == "finalized"
    assert loaded_revision["scene"]["meta"]["title"] == "Hospital Letter"


def test_scene_replace_cannot_smuggle_finalized_status(client: TestClient) -> None:
    document = create_document(client)
    finalized_scene = copy.deepcopy(client.get(f"/documents/{document['id']}").json()["scene"])
    finalized_scene["meta"]["status"] = {
        "kind": "finalized",
        "template_revision_id": "tmpl_smuggled",
    }

    response = client.put(
        f"/documents/{document['id']}/scene", json={"scene": finalized_scene}
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "scene.finalized_status_forbidden"
    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["status"] == "draft"


def test_create_document_rejects_finalized_scene_import(client: TestClient) -> None:
    scene = minimal_scene()
    scene["meta"]["status"] = {
        "kind": "finalized",
        "template_revision_id": "tmpl_imported",
    }

    response = client.post(
        "/documents",
        json={"title": "Imported Finalized Scene", "scene": scene},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "scene.finalized_status_forbidden"


def test_failed_finalization_persists_diagnostics(client: TestClient) -> None:
    scene = minimal_scene()
    scene["slots"]["slot_contact_name"]["placeholder"] = None
    document = create_document(client, scene)

    response = client.post(
        f"/documents/{document['id']}/finalize",
        json={"template_revision_id": "tmpl_invalid"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["views"]["latest"]
    diagnostics = client.get(
        f"/documents/{document['id']}/diagnostics?kind=finalize"
    ).json()
    assert diagnostics["kind"] == "finalize"
    assert diagnostics["schema_version"] == 1
    assert diagnostics["views"]["latest"]
    assert any(
        diagnostic["code"] == "LUMV0501"
        for diagnostic in diagnostics["diagnostics"]
    )


def test_asset_metadata_round_trip_stores_references_only(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        "/asset-metadata",
        json={
            "asset_id": "asset_logo",
            "document_id": document["id"],
            "kind": "logo",
            "filename": "logo.svg",
            "source_uri": "s3://example/logo.svg",
            "mime_type": "image/svg+xml",
            "width": 400,
            "height": 120,
            "provenance": {"source": "uploaded"},
            "licensing": {"usage": "client_owned"},
        },
    )
    assert response.status_code == 200, response.text

    loaded = client.get("/asset-metadata/asset_logo").json()
    assert loaded["source_uri"] == "s3://example/logo.svg"
    assert loaded["provenance"] == {"source": "uploaded"}


def test_agent_read_surfaces_return_slots_geometry_and_summary(client: TestClient) -> None:
    document = create_document(client, preflightable_scene())
    preflight = client.post(f"/documents/{document['id']}/preflight", json={})
    assert preflight.status_code == 200, preflight.text
    preflight_payload = preflight.json()
    assert preflight_payload["schema_version"] == 1
    assert preflight_payload["brand_kit"]["source"] == "platform_default"
    assert "scene" not in preflight_payload
    assert preflight_payload["operation_application"]["preflight_operations"] > 0

    summary = client.get(f"/documents/{document['id']}/summary").json()
    slots = client.get(f"/documents/{document['id']}/slots").json()
    geometry = client.get(f"/documents/{document['id']}/geometry").json()
    diagnostics = client.get(f"/documents/{document['id']}/diagnostics").json()

    assert summary["document"]["id"] == document["id"]
    assert slots[0]["key"] == "contact.full_name"
    assert "node_contact_name" in geometry["geometry"]
    assert diagnostics["kind"] == "preflight"


def test_delete_operation_persists_slot_binding_cleanup(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [{"kind": "remove_node", "node_id": "node_contact_name"}]},
    )
    assert response.status_code == 200, response.text

    slots = client.get(f"/documents/{document['id']}/slots").json()
    assert slots[0]["bound_nodes"] == []


def test_missing_resource_routes_return_404_envelopes(client: TestClient) -> None:
    paths = [
        "/documents/missing/operations",
        "/documents/missing/snapshots",
        "/documents/missing/diagnostics",
        "/template-revisions/missing",
        "/asset-metadata/missing",
    ]

    for path in paths:
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["detail"]["code"].endswith(".not_found")


def test_mutation_responses_are_compact_dto_envelopes(client: TestClient) -> None:
    document = create_document(client)

    response = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [title_operation("DTO Update")],
            "snapshot_reason": "dto checkpoint",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "applied"
    assert payload["operations"] == [{"sequence": 1, "kind": "update_document"}]
    assert payload["diagnostics"]["audit"] == []
    assert payload["snapshot"]["snapshot_id"].startswith("snap_")
    assert "scene" not in payload["document"]
    assert "scene" not in payload["snapshot"]
