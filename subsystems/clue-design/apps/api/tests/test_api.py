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
GENERATED_RASTER_ASSET_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/assets/generated_raster_asset.json"
)
VALID_STYLES_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/styles/valid_insight_health.styles"
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "api.sqlite3")
    return TestClient(app)


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def generated_raster_asset() -> dict:
    return json.loads(GENERATED_RASTER_ASSET_PATH.read_text())


def valid_styles_source() -> str:
    return VALID_STYLES_PATH.read_text()


def preflightable_scene() -> dict:
    scene = minimal_scene()
    slot = scene["slots"]["slot_contact_name"]
    slot["formatting"]["max_length"] = None
    slot["validation"]["samples"] = []
    slot["validation"]["max_length"] = None
    return scene


def tokenized_surface_scene(document_id: str) -> dict:
    scene = preflightable_scene()
    scene["meta"]["id"] = document_id
    scene["nodes"]["node_contact_name"]["fills"] = [
        {
            "id": "paint_contact_name_brand",
            "paint": {"kind": "token", "token": "surface.brand"},
        }
    ]
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


def asset_placeholder_node() -> dict:
    return {
        "id": "node_hero_image",
        "name": "Hero image",
        "kind": {"kind": "rect"},
        "transform": {
            "x": 24.0,
            "y": 76.0,
            "rotation": 0.0,
            "skew_x": 0.0,
            "skew_y": 0.0,
            "flip_x": False,
            "flip_y": False,
        },
        "size": {
            "width": {"kind": "fixed", "value": 120.0},
            "height": {"kind": "fixed", "value": 67.5},
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
    }


def image_slot() -> dict:
    return {
        "id": "slot_campaign_hero_image",
        "key": "campaign.hero_image",
        "label": "Hero image",
        "content_type": "image",
        "scope": {"kind": "document"},
        "bound_nodes": ["node_hero_image"],
        "required": False,
        "placeholder": "Generated clinic hero",
        "overflow": {"kind": "error"},
        "formatting": {
            "max_length": None,
            "allowed_pattern": None,
            "preserve_case": True,
        },
        "cardinality": {
            "min_items": 1,
            "max_items": 1,
        },
        "conditional": None,
        "repeater": None,
        "validation": {
            "samples": [],
            "worst_case": None,
            "max_length": None,
        },
        "image_policy": {
            "fit": "cover",
            "focal_point": {"x": 0.5, "y": 0.42},
            "min_dpi": 72,
            "preserve_transparency": False,
            "aspect_ratio": 1.7777777777777777,
        },
        "editability": "template_and_instance",
        "binding_hints": [],
    }


def asset_operations() -> list[dict]:
    return [
        {
            "kind": "insert_node",
            "parent": {"kind": "page", "id": "page_a4"},
            "index": 1,
            "node": asset_placeholder_node(),
        },
        {
            "kind": "upsert_slot",
            "slot": image_slot(),
        },
        {
            "kind": "upsert_asset",
            "asset": generated_raster_asset(),
        },
        {
            "kind": "place_asset_in_slot",
            "slot_id": "slot_campaign_hero_image",
            "asset_id": "asset_generated_hero",
            "placement": {
                "fit": "cover",
                "focal_point": {"x": 0.5, "y": 0.42},
                "preserve_transparency": False,
                "alt_text": "Generated clinic hero",
            },
        },
    ]


def brand_seed(version: int = 2) -> dict:
    return {
        "id": "brand_kit_api_seeded_insight",
        "version": version,
        "name": "Seeded Insight Health",
        "primary_color": "#075E68",
        "description": "Healthcare automation brand kit generated from seed inputs.",
        "secondary_color": "#0F766E",
        "accent_color": "#22C55E",
        "neutral_color": "#111827",
        "preferred_fonts": ["Source Sans 3", "Arial"],
        "logo_refs": [
            {
                "logo_id": "primary",
                "asset_id": "asset_logo_primary",
                "usage": "primary",
                "color_mode": "full_color",
                "variant": "default",
                "width": 160.0,
                "height": 48.0,
            }
        ],
        "tone_words": ["clinical", "calm", "expert"],
        "website_url": "https://example.test",
        "style_guide_asset_ids": [],
        "sources": [],
        "default_mode": {
            "values": {
                "theme": "light",
                "density": "comfortable",
                "accessibility": "standard",
                "medium": "digital",
            }
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


def test_styles_brand_kit_persists_validates_and_lists_versions(
    client: TestClient,
) -> None:
    response = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "created"
    assert payload["brand_kit"]["id"] == "brand_kit_insight_health"
    assert payload["brand_kit"]["product_ready"] is True
    assert "brand_kit_json" in payload

    duplicate = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "brand_kit.version_exists"

    latest = client.get("/brand-kits/brand_kit_insight_health").json()
    assert latest["brand_kit"]["version"] == 4
    assert latest["brand_kit_json"]["approval_status"] == "generated_unreviewed"

    listed = client.get("/brand-kits").json()
    assert [brand_kit["id"] for brand_kit in listed] == ["brand_kit_insight_health"]

    validation = client.post(
        "/brand-kits/validate",
        json={"brand_kit_id": "brand_kit_insight_health", "product_ready": True},
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["status"] == "ok"


def test_generated_brand_kit_attaches_to_document_and_reports_governance(
    client: TestClient,
) -> None:
    generated = client.post(
        "/brand-kits/generate",
        json={"seed": brand_seed()},
    )
    assert generated.status_code == 200, generated.text
    generated_payload = generated.json()
    assert generated_payload["brand_kit"]["id"] == "brand_kit_api_seeded_insight"
    assert generated_payload["brand_kit"]["product_ready"] is True

    document = create_document(client, preflightable_scene())
    attached = client.post(
        f"/documents/{document['id']}/brand-kit",
        json={
            "brand_kit_id": "brand_kit_api_seeded_insight",
            "version": 2,
            "mode": {
                "values": {
                    "theme": "dark",
                    "density": "comfortable",
                    "accessibility": "standard",
                    "medium": "digital",
                }
            },
            "snapshot_reason": "attach generated brand kit",
        },
    )
    assert attached.status_code == 200, attached.text
    attach_payload = attached.json()
    assert attach_payload["operation_application"]["applied_operations"] == 1
    assert attach_payload["snapshot"]["snapshot_id"].startswith("snap_")

    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["scene"]["meta"]["brand_kit"] == {
        "id": "brand_kit_api_seeded_insight",
        "version": 2,
    }
    assert loaded["effective_brand_kit_source"] == "brand_kit_library"
    assert loaded["effective_brand_kit_id"] == "brand_kit_api_seeded_insight"
    assert loaded["effective_brand_mode"] == {
        "values": {
            "accessibility": "standard",
            "density": "comfortable",
            "medium": "digital",
            "theme": "dark",
        }
    }
    assert loaded["scene"]["meta"]["medium"] == "digital"

    preflight = client.post(f"/documents/{document['id']}/preflight", json={})
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["brand_kit"]["source"] == "document"
    assert preflight.json()["brand_kit"]["mode"] == loaded["effective_brand_mode"]

    governance = client.post(
        f"/documents/{document['id']}/brand-governance",
        json={"brand_kit_id": "brand_kit_api_seeded_insight", "version": 2},
    )
    assert governance.status_code == 200, governance.text
    assert governance.json()["schema_version"] == 1
    assert governance.json()["brand_kit"]["id"] == "brand_kit_api_seeded_insight"

    diagnostics = client.get(
        f"/documents/{document['id']}/diagnostics?kind=brand_governance"
    ).json()
    assert diagnostics["kind"] == "brand_governance"


def test_preflight_uses_persisted_brand_mode_for_token_resolution(
    client: TestClient,
) -> None:
    generated = client.post(
        "/brand-kits/generate",
        json={"seed": brand_seed()},
    )
    assert generated.status_code == 200, generated.text

    light_document = create_document(
        client, tokenized_surface_scene("doc_brand_mode_light")
    )
    dark_document = create_document(client, tokenized_surface_scene("doc_brand_mode_dark"))

    for document, theme in [(light_document, "light"), (dark_document, "dark")]:
        attach = client.post(
            f"/documents/{document['id']}/brand-kit",
            json={
                "brand_kit_id": "brand_kit_api_seeded_insight",
                "version": 2,
                "mode": {
                    "values": {
                        "theme": theme,
                        "density": "comfortable",
                        "accessibility": "standard",
                        "medium": "digital",
                    }
                },
            },
        )
        assert attach.status_code == 200, attach.text
        preflight = client.post(f"/documents/{document['id']}/preflight", json={})
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["brand_kit"]["mode"]["values"]["theme"] == theme

    light = client.get(f"/documents/{light_document['id']}").json()
    dark = client.get(f"/documents/{dark_document['id']}").json()

    assert light["effective_brand_mode"]["values"]["theme"] == "light"
    assert dark["effective_brand_mode"]["values"]["theme"] == "dark"

    light_fill = light["scene"]["nodes"]["node_contact_name"]["fills"][0]["paint"]
    dark_fill = dark["scene"]["nodes"]["node_contact_name"]["fills"][0]["paint"]

    assert light_fill["kind"] == "solid"
    assert dark_fill["kind"] == "solid"
    assert light_fill["color"]["kind"] == "hex"
    assert dark_fill["color"]["kind"] == "hex"
    assert light_fill["color"]["value"] != dark_fill["color"]["value"]


def test_brand_kit_compatibility_report_persists_between_stored_versions(
    client: TestClient,
) -> None:
    version_four = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert version_four.status_code == 200, version_four.text

    version_five_source = valid_styles_source().replace("version(4)", "version(5)")
    version_five = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": version_five_source,
            "brand_kit_id": "brand_kit_insight_health",
            "version": 5,
            "name": "Insight Health",
        },
    )
    assert version_five.status_code == 200, version_five.text

    response = client.post(
        "/brand-kits/compatibility",
        json={
            "from_ref": {"brand_kit_id": "brand_kit_insight_health", "version": 4},
            "to_ref": {"brand_kit_id": "brand_kit_insight_health", "version": 5},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["report"]["from"] == {
        "id": "brand_kit_insight_health",
        "version": 4,
    }
    assert payload["report"]["to"] == {
        "id": "brand_kit_insight_health",
        "version": 5,
    }
    assert payload["stored_report"]["report_id"].startswith("brand_report_")

    stored = client.get(
        f"/brand-compatibility-reports/{payload['stored_report']['report_id']}"
    ).json()
    assert stored["from_ref"] == {"id": "brand_kit_insight_health", "version": 4}
    assert stored["to_ref"] == {"id": "brand_kit_insight_health", "version": 5}


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


def test_asset_scene_operations_persist_history_snapshot_and_template(
    client: TestClient,
) -> None:
    document = create_document(client)

    metadata = client.post(
        "/asset-metadata",
        json={
            "asset_id": "asset_generated_hero",
            "document_id": document["id"],
            "kind": "raster_image",
            "filename": "generated-clinic-hero.png",
            "source_uri": "s3://example/generated-clinic-hero.png",
            "mime_type": "image/png",
            "width": 1600,
            "height": 900,
            "provenance": {"source": "agent_generated"},
            "licensing": {"usage": "generated_commercial_use"},
        },
    )
    assert metadata.status_code == 200, metadata.text

    response = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": asset_operations(),
            "actor": {"kind": "agent", "id": "agent_design"},
            "source": "agent",
            "snapshot_reason": "after asset placement",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["operation_application"]["applied_operations"] == 4
    assert payload["document"]["counts"]["assets"] == 1
    assert [operation["kind"] for operation in payload["operations"]] == [
        "insert_node",
        "upsert_slot",
        "upsert_asset",
        "place_asset_in_slot",
    ]

    loaded = client.get(f"/documents/{document['id']}").json()
    scene = loaded["scene"]
    assert scene["assets"]["asset_generated_hero"]["kind"] == "raster_image"
    assert scene["nodes"]["node_hero_image"]["kind"] == {
        "kind": "image",
        "asset_id": "asset_generated_hero",
        "alt": "Generated clinic hero",
    }
    assert scene["nodes"]["node_hero_image"]["asset_placement"]["fit"] == "cover"

    history = client.get(f"/documents/{document['id']}/operations").json()
    assert [entry["operation"]["kind"] for entry in history] == [
        "insert_node",
        "upsert_slot",
        "upsert_asset",
        "place_asset_in_slot",
    ]

    snapshot_id = payload["snapshot"]["snapshot_id"]
    snapshot = client.get(
        f"/documents/{document['id']}/snapshots/{snapshot_id}"
    ).json()
    assert "asset_generated_hero" in snapshot["scene"]["assets"]

    finalized = client.post(
        f"/documents/{document['id']}/finalize",
        json={"template_revision_id": "tmpl_asset_scene"},
    )
    assert finalized.status_code == 200, finalized.text
    revision = client.get("/template-revisions/tmpl_asset_scene").json()
    assert "asset_generated_hero" in revision["scene"]["assets"]
    assert (
        revision["scene"]["nodes"]["node_hero_image"]["kind"]["asset_id"]
        == "asset_generated_hero"
    )

    metadata_loaded = client.get("/asset-metadata/asset_generated_hero").json()
    assert metadata_loaded["source_uri"] == "s3://example/generated-clinic-hero.png"


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
        "/brand-kits/missing",
        "/brand-compatibility-reports/missing",
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
