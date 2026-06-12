from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from lumen_api.main import agent_response_from_trace, create_app


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


def test_export_preview_route_returns_compact_svg_artifact(client: TestClient) -> None:
    scene = minimal_scene()
    scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1080,
        "unit": "px",
        "preset": "custom",
        "orientation": "landscape",
    }

    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "svg",
            "page_ids": ["page_a4"],
            "profile": {
                "name": "custom_square_svg",
                "format": "svg",
                "pdf_intent": "preview",
                "raster": None,
                "include_bleed": False,
                "embed_fonts": False,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "ok"
    artifact = payload["export"]["artifacts"][0]
    assert artifact["format"] == "svg"
    assert artifact["filename"] == "page_a4.custom_square_svg.svg"
    assert artifact["sidecar_filename"] == "page_a4.custom_square_svg.sidecar.json"
    assert artifact["mime_type"] == "image/svg+xml"
    assert artifact["byte_length"] > 20
    assert artifact["data_url"].startswith("data:image/svg+xml;base64,")
    assert "viewBox=\"0 0 1080 1080\"" in artifact["text"]
    assert artifact["dimensions"] == {
        "width": 1080.0,
        "height": 1080.0,
        "unit": "scene",
        "source": "svg_view_box",
    }
    assert '"profile_name": "custom_square_svg"' in artifact["sidecar_json"]
    assert artifact["sidecar_summary"]["profile_name"] == "custom_square_svg"
    assert artifact["sidecar_summary"]["page_ids"] == ["page_a4"]
    assert artifact["sidecar_summary"]["node_count"] == 1
    assert artifact["sidecar_summary"]["slot_keys"] == ["contact.full_name"]


def test_agent_turn_preview_route_returns_editor_safe_proposal(client: TestClient) -> None:
    captured = {}

    def fake_agent_runner(payload, root):
        captured["payload"] = payload
        captured["root"] = root
        return {
            "schema_version": 1,
            "status": "proposed",
            "summary": "Agent proposed a document title update.",
            "run_id": "run_test_agent",
            "trace_dir": ".lumen-runs/run_test_agent",
            "preview_paths": [".lumen-runs/run_test_agent/page_a4.svg"],
            "dsl_blocks": ["# document title repair"],
            "operations": [title_operation("Agent Title")],
            "diagnostics": [],
            "artifacts": [
                {
                    "format": "svg",
                    "page_id": "page_a4",
                    "filename": "page_a4.svg",
                    "path": ".lumen-runs/run_test_agent/page_a4.svg",
                    "data_url": None,
                    "mime_type": "image/svg+xml",
                }
            ],
        }

    client.app.state.agent_turn_runner = fake_agent_runner

    response = client.post(
        "/agent/turn-preview",
        json={
            "prompt": "Repair the headline",
            "scene": minimal_scene(),
            "document_id": "doc_agent_route",
            "active_page_id": "page_a4",
            "selected_node_id": "node_contact_name",
            "diagnostics": [],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "proposed"
    assert payload["run_id"] == "run_test_agent"
    assert payload["dsl_blocks"] == ["# document title repair"]
    assert payload["operations"][0]["kind"] == "update_document"
    assert payload["artifacts"][0]["format"] == "svg"
    assert captured["payload"].prompt == "Repair the headline"
    assert captured["payload"].active_page_id == "page_a4"
    assert captured["payload"].selected_node_id == "node_contact_name"
    assert captured["root"] == REPO_ROOT


def test_agent_turn_preview_allows_editor_cors_preflight(client: TestClient) -> None:
    response = client.options(
        "/agent/turn-preview",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_structured_request_logging_adds_request_id_header(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="lumen_api.api")

    response = client.get(
        "/documents/missing_document",
        headers={"x-request-id": "req_test_observability"},
    )

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req_test_observability"
    completed = [
        record
        for record in caplog.records
        if getattr(record, "lumen_event", None) == "http_request_completed"
    ]
    assert completed
    fields = getattr(completed[-1], "lumen_fields")
    assert fields["request_id"] == "req_test_observability"
    assert fields["method"] == "GET"
    assert fields["route"] == "/documents/{document_id}"
    assert fields["status_code"] == 404
    assert fields["duration_ms"] >= 0


def test_core_helper_logging_records_runtime_summary(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="lumen_api.core")

    response = client.post(
        "/export-preview",
        headers={"x-request-id": "req_helper_observability"},
        json={
            "scene": minimal_scene(),
            "format": "svg",
            "page_ids": ["page_a4"],
        },
    )

    assert response.status_code == 200, response.text
    events = {
        getattr(record, "lumen_event", None): getattr(record, "lumen_fields")
        for record in caplog.records
    }
    assert events["core_helper_started"]["request_id"] == "req_helper_observability"
    assert events["core_helper_started"]["action"] == "export_preview"
    assert events["core_helper_started"]["page_id_count"] == 1
    assert events["core_helper_completed"]["ok"] is True
    assert events["core_helper_completed"]["action"] == "export_preview"
    assert events["core_helper_completed"]["diagnostic_count"] >= 0


def test_agent_trace_response_returns_unapproved_draft_scene(tmp_path: Path) -> None:
    trace_dir = tmp_path / "run_agent_draft"
    iteration_dir = trace_dir / "iterations" / "001"
    iteration_dir.mkdir(parents=True)
    (iteration_dir / "dsl.lumen").write_text(
        "page page_square size(1080,1080,px)", encoding="utf-8"
    )
    (iteration_dir / "compile.json").write_text(
        json.dumps(
            {
                "compile": {
                    "status": "ok",
                    "diagnostics": [],
                },
                "operations": [title_operation("Unapproved Draft")],
            }
        ),
        encoding="utf-8",
    )
    draft_scene = minimal_scene()
    draft_scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1080,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }

    payload = agent_response_from_trace(
        {
            "status": "failed",
            "summary": "Maximum repair iterations reached.",
            "run_id": "run_agent_draft",
            "stop_reason": "max_iterations_reached",
            "preview_paths": [],
        },
        trace_dir,
        draft_scene,
    )

    assert payload["status"] == "failed"
    assert payload["operations"] == []
    assert payload["draft_scene"]["pages"]["page_a4"]["size"]["width"] == 1080
    assert payload["stop_reason"] == "max_iterations_reached"
    assert payload["dsl_blocks"] == ["page page_square size(1080,1080,px)"]


def test_export_preview_route_returns_failed_payload_for_missing_page(
    client: TestClient,
) -> None:
    scene = minimal_scene()

    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "svg",
            "page_ids": ["missing_page"],
            "profile": {
                "name": "missing_page_svg",
                "format": "svg",
                "pdf_intent": "preview",
                "raster": None,
                "include_bleed": False,
                "embed_fonts": False,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "failed"
    assert payload["export"]["artifacts"] == []
    diagnostic_codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
    assert "LUME0101" in diagnostic_codes
    assert all(
        diagnostic["severity"] == "error"
        for diagnostic in payload["diagnostics"]
        if diagnostic["code"] == "LUME0101"
    )


def test_document_export_route_uses_saved_profile_and_persists_preflight(
    client: TestClient,
) -> None:
    scene = preflightable_scene()
    scene["meta"]["medium"] = "ad"
    scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1080,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }
    scene["export_profiles"] = [
        {
            "name": "client_square_svg",
            "format": "svg",
            "pdf_intent": "preview",
            "raster": None,
            "include_bleed": False,
            "embed_fonts": False,
        }
    ]
    document = create_document(client, scene)

    response = client.post(
        f"/documents/{document['id']}/export",
        json={"profile_name": "client_square_svg", "page_ids": ["page_a4"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "ok"
    assert payload["document"]["id"] == document["id"]
    assert payload["profile"]["name"] == "client_square_svg"
    assert payload["brand_kit"]["source"] == "platform_default"
    assert payload["brand_kit"]["mode"]["values"]["medium"] == "digital"
    assert payload["operation_application"]["preflight_operations"] > 0
    assert all(
        diagnostic["severity"] != "error"
        for diagnostic in payload["diagnostics"]["current"]
    )

    artifact = payload["export"]["artifacts"][0]
    assert artifact["format"] == "svg"
    assert artifact["filename"] == "page_a4.client_square_svg.svg"
    assert artifact["sidecar_filename"] == "page_a4.client_square_svg.sidecar.json"
    assert artifact["mime_type"] == "image/svg+xml"
    assert "viewBox=\"0 0 1080 1080\"" in artifact["text"]
    assert artifact["dimensions"] == {
        "width": 1080.0,
        "height": 1080.0,
        "unit": "scene",
        "source": "svg_view_box",
    }
    assert artifact["sidecar_summary"]["profile_name"] == "client_square_svg"
    assert artifact["sidecar_summary"]["page_ids"] == ["page_a4"]

    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["current_version"] == payload["document"]["current_version"]
    assert loaded["effective_brand_kit_source"] == "platform_default"
    assert loaded["scene"]["pages"]["page_a4"]["size"] == {
        "width": 1080.0,
        "height": 1080.0,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }

    diagnostics = client.get(
        f"/documents/{document['id']}/diagnostics?kind=export"
    ).json()
    assert diagnostics["schema_version"] == 1
    assert diagnostics["kind"] == "export"


def test_document_export_route_fails_closed_before_export_on_preflight_errors(
    client: TestClient,
) -> None:
    document = create_document(
        client, tokenized_surface_scene("doc_export_requires_brand")
    )

    response = client.post(
        f"/documents/{document['id']}/export",
        json={
            "format": "svg",
            "page_ids": ["page_a4"],
            "strict_no_fallback": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "failed"
    assert payload["brand_kit"]["source"] == "none"
    assert payload["preflight"]["has_errors"] is True
    assert payload["export"]["artifacts"] == []
    assert any(
        diagnostic["severity"] == "error"
        for diagnostic in payload["diagnostics"]["current"]
    )

    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["current_version"] == document["current_version"]

    diagnostics = client.get(
        f"/documents/{document['id']}/diagnostics?kind=export"
    ).json()
    assert diagnostics["schema_version"] == 1
    assert diagnostics["kind"] == "export"
    assert diagnostics["views"]["latest"]


def test_document_export_route_rejects_unknown_saved_profile(
    client: TestClient,
) -> None:
    document = create_document(client, preflightable_scene())

    response = client.post(
        f"/documents/{document['id']}/export",
        json={"profile_name": "missing_profile"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "export_profile.not_found"


def test_preflight_preview_route_returns_preflighted_custom_scene(
    client: TestClient,
) -> None:
    scene = preflightable_scene()
    scene["meta"]["medium"] = "ad"
    scene["pages"]["page_a4"]["size"] = {
        "width": 1200,
        "height": 628,
        "unit": "px",
        "preset": "custom",
        "orientation": "landscape",
    }

    response = client.post(
        "/preflight-preview",
        json={
            "scene": scene,
            "mode": {
                "values": {
                    "theme": "light",
                    "density": "comfortable",
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["status"] == "applied"
    assert payload["brand_kit"]["source"] == "platform_default"
    assert payload["brand_kit"]["mode"]["values"]["medium"] == "digital"
    assert payload["document"]["counts"]["pages"] == 1
    assert payload["operation_application"]["preflight_operations"] > 0
    assert all(
        diagnostic["severity"] != "error"
        for diagnostic in payload["diagnostics"]["current"]
    )
    assert payload["scene"]["pages"]["page_a4"]["size"] == {
        "width": 1200.0,
        "height": 628.0,
        "unit": "px",
        "preset": "custom",
        "orientation": "landscape",
    }
    assert (
        payload["scene"]["nodes"]["node_contact_name"]["computed"]["layout_bounds"][
            "width"
        ]
        > 0
    )


def test_export_preview_route_reports_print_pdf_bleed_dimensions(
    client: TestClient,
) -> None:
    scene = minimal_scene()
    scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1080,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }
    scene["pages"]["page_a4"]["bleed"] = {
        "x": -18,
        "y": -18,
        "width": 1116,
        "height": 1116,
    }
    scene["pages"]["page_a4"]["safe_area"] = {
        "x": 72,
        "y": 72,
        "width": 936,
        "height": 936,
    }

    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "pdf",
            "page_ids": ["page_a4"],
            "profile": {
                "name": "print_pdf_with_bleed",
                "format": "pdf",
                "pdf_intent": "print",
                "raster": None,
                "include_bleed": True,
                "embed_fonts": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    artifact = payload["export"]["artifacts"][0]
    assert artifact["format"] == "pdf"
    assert artifact["filename"] == "page_a4.print_pdf_with_bleed.pdf"
    assert artifact["sidecar_filename"] == "page_a4.print_pdf_with_bleed.sidecar.json"
    assert artifact["mime_type"] == "application/pdf"
    assert artifact["dimensions"] == {
        "width": 1116.0,
        "height": 1116.0,
        "unit": "pt",
        "source": "pdf_media_box",
    }
    diagnostic_codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
    assert "LUME0401" in diagnostic_codes
    assert "LUME0402" in diagnostic_codes
    assert "LUME0411" not in diagnostic_codes
    assert "LUME0412" not in diagnostic_codes


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


def test_apply_structured_edit_persists_canonical_operations(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/edits",
        json={
            "edit": {
                "kind": "modify",
                "target": {"kind": "node", "id": "node_contact_name"},
                "patch": {
                    "kind": "node",
                    "value": {
                        "text": {
                            "content": {
                                "kind": "set",
                                "value": "Targeted API repair headline",
                            },
                            "font_size": {"kind": "set", "value": 16.0},
                        }
                    },
                },
            },
            "actor": {"kind": "agent", "id": "agent_repair"},
            "source": "agent",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["edit"]["kind"] == "modify"
    assert payload["operation_application"]["applied_operations"] == 1
    assert payload["operations"] == [{"sequence": 1, "kind": "update_node"}]

    loaded = client.get(f"/documents/{document['id']}").json()
    assert (
        loaded["scene"]["nodes"]["node_contact_name"]["kind"]["content"]
        == "Targeted API repair headline"
    )
    assert loaded["scene"]["nodes"]["node_contact_name"]["kind"]["font_size"] == 16.0

    history = client.get(f"/documents/{document['id']}/operations").json()
    assert history[0]["source"] == "agent"
    assert history[0]["operation"]["kind"] == "update_node"
    assert (
        history[0]["operation"]["patch"]["kind"]["value"]["content"]
        == "Targeted API repair headline"
    )


def test_apply_structured_edit_rejects_missing_target_without_history(
    client: TestClient,
) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/edits",
        json={
            "edit": {
                "kind": "delete",
                "target": {"kind": "node", "id": "missing_node"},
            }
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "edit.target_not_found"
    assert detail["diagnostics"][0]["code"] == "edit.target_not_found"
    assert client.get(f"/documents/{document['id']}/operations").json() == []


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


def test_structured_edit_envelope_persists_intent_inverses_and_readback(
    client: TestClient,
) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/edits",
        json={
            "edit": {
                "kind": "modify",
                "target": {"kind": "node", "id": "node_contact_name"},
                "patch": {
                    "kind": "node",
                    "value": {
                        "text": {
                            "content": {"kind": "set", "value": "Enveloped repair"}
                        }
                    },
                },
            },
            "actor": {"kind": "agent", "id": "agent_repair"},
            "source": "agent",
            "checkpoint": "headline fix",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    envelope_summary = payload["envelope"]
    assert envelope_summary["intent"] == "modify_node"
    assert envelope_summary["checkpoint_label"] == "headline fix"
    assert envelope_summary["invertible"] is True
    assert envelope_summary["base_revision"] == 0
    assert envelope_summary["touched_targets"] == [
        {"kind": "node", "id": "node_contact_name"}
    ]

    history = client.get(f"/documents/{document['id']}/history").json()
    assert history["document_id"] == document["id"]
    envelope = history["envelopes"][0]
    assert envelope["batch_id"] == envelope_summary["batch_id"]
    assert envelope["envelope_version"] == 1
    assert envelope["actor"] == {"kind": "agent", "id": "agent_repair"}
    assert envelope["source"] == "agent"
    assert envelope["operations"][0]["kind"] == "update_node"
    inverse = envelope["inverse_operations"]
    assert inverse is not None and len(inverse) == 1
    assert inverse[0]["kind"] == "update_node"

    operation_rows = client.get(f"/documents/{document['id']}/operations").json()
    assert operation_rows[0]["batch_id"] == envelope["batch_id"]


def test_apply_operations_envelope_carries_inverse_and_intent(
    client: TestClient,
) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [title_operation("Enveloped Title")],
            "intent": "rename_document",
            "checkpoint": "rename",
        },
    )
    assert response.status_code == 200, response.text
    envelope_summary = response.json()["envelope"]
    assert envelope_summary["intent"] == "rename_document"
    assert envelope_summary["invertible"] is True

    history = client.get(f"/documents/{document['id']}/history").json()
    envelope = history["envelopes"][0]
    assert envelope["checkpoint_label"] == "rename"
    inverse = envelope["inverse_operations"]
    assert inverse[0]["kind"] == "update_document"
    assert inverse[0]["patch"]["title"]["value"] == "Hospital Letter"


def test_base_version_mismatch_rejects_edit_before_mutation(
    client: TestClient,
) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [title_operation("Should not apply")],
            "base_version": 7,
        },
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "edits.base_version_mismatch"
    assert detail["current_version"] == 0

    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["title"] == "Hospital Letter"
    assert client.get(f"/documents/{document['id']}/history").json()["envelopes"] == []


def test_backfill_wraps_pre_envelope_operation_rows(tmp_path: Path) -> None:
    import sqlite3

    database_path = tmp_path / "api.sqlite3"
    app = create_app(database_path)
    client = TestClient(app)
    document = create_document(client)
    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Legacy Title")]},
    )

    connection = sqlite3.connect(database_path)
    connection.execute("UPDATE operation_log SET batch_id = NULL")
    connection.execute("DELETE FROM edit_envelopes")
    connection.commit()
    connection.close()

    restarted = TestClient(create_app(database_path))
    history = restarted.get(f"/documents/{document['id']}/history").json()
    envelope = history["envelopes"][0]
    assert envelope["envelope_version"] == 0
    assert envelope["batch_id"].startswith("backfill_")
    assert envelope["intent"] is None
    assert envelope["inverse_operations"] is None
    assert envelope["operations"][0]["kind"] == "update_document"


def test_strict_scope_violation_rejects_edit_fail_closed(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/edits",
        json={
            "edit": {
                "kind": "modify",
                "target": {"kind": "node", "id": "node_contact_name"},
                "patch": {
                    "kind": "node",
                    "value": {
                        "text": {"content": {"kind": "set", "value": "Out of scope"}}
                    },
                },
            },
            "scope": {"mode": "strict", "allowed": [{"kind": "document"}]},
            "actor": {"kind": "agent", "id": "agent_repair"},
            "source": "agent",
        },
    )
    assert response.status_code >= 400, response.text
    assert "edit.scope_violation" in response.text

    loaded = client.get(f"/documents/{document['id']}").json()
    assert loaded["current_version"] == 0
    assert client.get(f"/documents/{document['id']}/history").json()["envelopes"] == []


def test_strict_scope_in_scope_edit_applies(client: TestClient) -> None:
    document = create_document(client)
    response = client.post(
        f"/documents/{document['id']}/edits",
        json={
            "edit": {
                "kind": "modify",
                "target": {"kind": "node", "id": "node_contact_name"},
                "patch": {
                    "kind": "node",
                    "value": {
                        "text": {"content": {"kind": "set", "value": "In scope"}}
                    },
                },
            },
            "scope": {
                "mode": "strict",
                "allowed": [{"kind": "node", "id": "node_contact_name"}],
            },
            "actor": {"kind": "agent", "id": "agent_repair"},
            "source": "agent",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["envelope"]["invertible"] is True


def test_undo_redo_round_trip_appends_history(client: TestClient) -> None:
    document = create_document(client)
    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Version B")], "intent": "rename"},
    )

    undo = client.post(f"/documents/{document['id']}/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["reverted_intent"] == "rename"
    assert client.get(f"/documents/{document['id']}").json()["title"] == "Hospital Letter"

    redo = client.post(f"/documents/{document['id']}/redo")
    assert redo.status_code == 200, redo.text
    assert client.get(f"/documents/{document['id']}").json()["title"] == "Version B"

    # History is append-only: edit, undo, redo are three envelopes.
    envelopes = client.get(f"/documents/{document['id']}/history").json()["envelopes"]
    assert len(envelopes) == 3
    assert envelopes[0]["intent"] == "redo:rename"
    assert envelopes[0]["reapplies_batch_id"] == envelopes[2]["batch_id"]
    assert envelopes[1]["intent"] == "undo:rename"
    assert envelopes[1]["reverts_batch_id"] == envelopes[2]["batch_id"]

    # Undo after redo still works (linear cursor over the appended log).
    assert client.post(f"/documents/{document['id']}/undo").status_code == 200
    assert client.get(f"/documents/{document['id']}").json()["title"] == "Hospital Letter"


def test_new_edit_clears_redo_stack(client: TestClient) -> None:
    document = create_document(client)
    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("First")]},
    )
    client.post(f"/documents/{document['id']}/undo")
    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Second")]},
    )

    redo = client.post(f"/documents/{document['id']}/redo")
    assert redo.status_code == 409
    assert redo.json()["detail"]["code"] == "history.nothing_to_redo"

    empty = client.post(f"/documents/{document['id']}/undo")
    assert empty.status_code == 200
    second_undo = client.post(f"/documents/{document['id']}/undo")
    assert second_undo.status_code == 409
    assert second_undo.json()["detail"]["code"] == "history.nothing_to_undo"


def test_revert_to_checkpoint_composes_undos(client: TestClient) -> None:
    document = create_document(client)
    client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [title_operation("Anchored")],
            "checkpoint": "good state",
        },
    )
    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Drift 1")]},
    )
    client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Drift 2")]},
    )

    checkpoints = client.get(f"/documents/{document['id']}/checkpoints").json()
    assert [c["label"] for c in checkpoints["checkpoints"]] == ["good state"]

    revert = client.post(
        f"/documents/{document['id']}/revert", params={"checkpoint": "good state"}
    )
    assert revert.status_code == 200, revert.text
    assert len(revert.json()["reverted_batch_ids"]) == 2
    assert client.get(f"/documents/{document['id']}").json()["title"] == "Anchored"

    missing = client.post(
        f"/documents/{document['id']}/revert", params={"checkpoint": "nope"}
    )
    assert missing.status_code == 404


LOGO_PNG_PATH = REPO_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"


def upload_logo(client: TestClient, **form) -> "object":
    data = {"label": "Acme logo", "kind": "logo", "uploaded_by": "designer"}
    data.update(form)
    return client.post(
        "/assets",
        files={"file": ("acme-logo.png", LOGO_PNG_PATH.read_bytes(), "image/png")},
        data=data,
    )


def store_files(tmp_path: Path) -> list[Path]:
    store_root = tmp_path / "asset-store"
    if not store_root.exists():
        return []
    return [path for path in store_root.rglob("*") if path.is_file()]


def test_asset_upload_stores_content_addressed_bytes(
    client: TestClient, tmp_path: Path
) -> None:
    response = upload_logo(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    record = payload["asset"]

    assert record["kind"] == "logo"
    assert record["status"] == "ready"
    assert record["media"]["mime_type"] == "image/png"
    digest = record["media"]["digest"]
    assert digest["algorithm"] == "sha256"
    opaque_ref = record["media"]["location"]["opaque_ref"]
    assert opaque_ref == f"sha256/{digest['value'][:2]}/{digest['value']}"
    assert record["media"]["location"]["provider"] == "local-store"
    assert payload["deduplicated"] is False

    store_path = tmp_path / "asset-store" / opaque_ref
    assert store_path.is_file()
    assert store_path.read_bytes() == LOGO_PNG_PATH.read_bytes()

    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200
    assert served.content == LOGO_PNG_PATH.read_bytes()
    assert served.headers["content-type"].startswith("image/png")

    loaded = client.get(f"/assets/{record['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["asset"]["id"] == record["id"]


def test_duplicate_asset_upload_dedups_bytes(
    client: TestClient, tmp_path: Path
) -> None:
    first = upload_logo(client)
    assert first.status_code == 200, first.text
    second = upload_logo(client)
    assert second.status_code == 200, second.text

    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True
    assert (
        first.json()["asset"]["media"]["digest"]
        == second.json()["asset"]["media"]["digest"]
    )
    # Two records, one stored byte object.
    assert first.json()["asset"]["id"] != second.json()["asset"]["id"]
    # Two stored objects per logical asset (bytes + derived thumbnail);
    # the duplicate upload adds none.
    files_after_both = store_files(tmp_path)
    assert len(files_after_both) == 2


def test_asset_upload_rejects_mime_mismatch(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(
        "/assets",
        files={"file": ("logo.jpg", LOGO_PNG_PATH.read_bytes(), "image/jpeg")},
        data={"label": "Mislabeled"},
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "ingest.mime_mismatch"
    assert any(
        diagnostic["code"] == "LUMA0600" for diagnostic in detail["diagnostics"]
    )
    assert store_files(tmp_path) == []


def test_asset_upload_enforces_size_limit(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LUMEN_ASSET_MAX_BYTES", "16")
    response = upload_logo(client)
    assert response.status_code == 413, response.text
    assert store_files(tmp_path) == []


def test_upload_resolve_export_round_trip(client: TestClient) -> None:
    uploaded = upload_logo(client)
    assert uploaded.status_code == 200, uploaded.text
    record = uploaded.json()["asset"]

    document = create_document(client)
    operations = asset_operations()
    # The uploaded fixture is a square logo; align the slot policy with the
    # probed aspect ratio so placement validation passes.
    operations[1]["slot"]["image_policy"]["aspect_ratio"] = 1.0
    operations[2] = {"kind": "upsert_asset", "asset": record}
    operations[3]["asset_id"] = record["id"]
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": operations,
            "actor": {"kind": "user", "id": "designer"},
            "source": "editor",
        },
    )
    assert applied.status_code == 200, applied.text

    scene = client.get(f"/documents/{document['id']}").json()["scene"]
    exported = client.post(
        "/export-preview",
        json={"scene": scene, "format": "svg", "page_ids": ["page_a4"]},
    )
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    artifact = payload["export"]["artifacts"][0]
    assert artifact["format"] == "svg"
    assert "data:image/png;base64," in (artifact.get("text") or "")
    for diagnostic in payload["diagnostics"]:
        assert diagnostic["code"] not in {"LUME0202", "LUME0210", "LUME0211"}, (
            payload["diagnostics"]
        )


HOSTILE_SVG = (
    '<?xml version="1.0"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60" viewBox="0 0 120 60">\n'
    "  <script>alert('owned')</script>\n"
    '  <rect width="120" height="60" fill="#0F766E" onload="alert(1)"/>\n'
    '  <a href="javascript:alert(2)"><text x="10" y="30">x</text></a>\n'
    '</svg>\n'
)


def test_svg_upload_is_sanitized_before_storage(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(
        "/assets",
        files={"file": ("mark.svg", HOSTILE_SVG.encode(), "image/svg+xml")},
        data={"label": "Brand mark", "kind": "vector"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    record = payload["asset"]

    assert record["kind"] == "vector"
    assert record["media"]["mime_type"] == "image/svg+xml"
    assert record["vector"]["width"] == 120.0
    assert record["vector"]["view_box"] == [0.0, 0.0, 120.0, 60.0]
    assert any(
        diagnostic["code"] == "LUMA0603" for diagnostic in payload["diagnostics"]
    )

    served = client.get(f"/assets/{record['id']}/bytes")
    stored_svg = served.content.decode()
    assert "<script" not in stored_svg
    assert "onload" not in stored_svg
    assert "javascript:" not in stored_svg
    assert "<rect" in stored_svg

    # Vector thumbnails are the sanitized SVG itself.
    thumbnail = client.get(f"/assets/{record['id']}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.content == served.content


def test_raster_upload_probes_metadata_and_serves_thumbnail(
    client: TestClient,
) -> None:
    response = upload_logo(client)
    assert response.status_code == 200, response.text
    record = response.json()["asset"]

    raster = record["raster"]
    assert raster["pixel_width"] == 8
    assert raster["pixel_height"] == 8
    assert raster["has_alpha"] is True
    assert abs(raster["dpi_x"] - 300.0) < 0.5

    thumbnail_meta = record["media"]["thumbnail"]
    assert thumbnail_meta["mime_type"] == "image/png"

    thumbnail = client.get(f"/assets/{record['id']}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/png")
    assert thumbnail.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_qr_route_is_deterministic_and_persists_record(
    client: TestClient,
) -> None:
    body = {
        "data": "https://lumen.example/a/acme-health",
        "label": "Acme landing QR",
        "print_media": True,
        "target_width_mm": 24.0,
    }
    first = client.post("/assets/generate/qr", json=body)
    assert first.status_code == 200, first.text
    payload = first.json()
    record = payload["asset"]

    assert record["kind"] == "vector"
    assert record["source"] == {
        "kind": "generated",
        "request_id": record["id"],
        "model": "qr-v1",
    }
    assert record["provenance"]["source_label"] == "generated:qr"
    assert record["license"]["allow_export"] is True
    assert payload["qr"]["ec_level"] == "h"
    assert payload["qr"]["quiet_zone_modules"] == 4
    assert payload["deduplicated"] is False
    assert payload["diagnostics"] == []

    # Determinism: same data -> same digest, second generation dedups.
    second = client.post("/assets/generate/qr", json=body).json()
    assert second["deduplicated"] is True
    assert (
        second["asset"]["media"]["digest"] == record["media"]["digest"]
    )

    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/svg+xml")
    svg = served.content.decode()
    assert "<svg" in svg and "viewBox" in svg

    loaded = client.get(f"/assets/{record['id']}")
    assert loaded.status_code == 200


def test_generate_qr_route_surfaces_diagnostics_and_rejections(
    client: TestClient,
) -> None:
    small = client.post(
        "/assets/generate/qr",
        json={
            "data": "https://lumen.example/a/acme-health",
            "print_media": True,
            "target_width_mm": 12.0,
        },
    )
    assert small.status_code == 200, small.text
    assert any(
        diagnostic["code"] == "LUMA0700" for diagnostic in small.json()["diagnostics"]
    )

    empty = client.post("/assets/generate/qr", json={"data": "   "})
    assert empty.status_code == 400
    detail = empty.json()["detail"]
    assert detail["code"] == "qr.empty_data"
    assert any(
        diagnostic["code"] == "LUMA0702" for diagnostic in detail["diagnostics"]
    )


def test_generate_asset_route_runs_registry_providers(client: TestClient) -> None:
    # Public provider-registry surface (Phase G slice G5): qr-v1 through
    # the generation trait produces a persisted vector record.
    qr = client.post(
        "/assets/generate",
        json={
            "provider": "qr-v1",
            "prompt": "https://go.example.com/acme/dr-sharma",
            "output_kind": "vector",
            "label": "Landing QR",
        },
    )
    assert qr.status_code == 200, qr.text
    payload = qr.json()
    record = payload["asset"]
    assert record["kind"] == "vector"
    assert record["provenance"]["source_label"] == "generated:qr-v1"
    assert payload["provider"]["id"] == "qr-v1"
    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200
    assert b"<svg" in served.content

    # Deterministic stub image provider persists a raster record.
    image = client.post(
        "/assets/generate",
        json={
            "provider": "stub-image-v0",
            "prompt": "calm clinical hero image",
            "width": 64,
            "height": 32,
        },
    )
    assert image.status_code == 200, image.text
    image_record = image.json()["asset"]
    assert image_record["kind"] == "raster_image"
    assert image_record["raster"]["pixel_width"] == 64
    assert image_record["raster"]["pixel_height"] == 32

    # Unknown providers are typed rejections, never 500s.
    unknown = client.post(
        "/assets/generate",
        json={"provider": "imaginary-v9", "prompt": "anything"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "provider.unknown"


def test_mailer_carries_scannable_qr_through_export(client: TestClient) -> None:
    # Gate for slice E4: a mailer-style document carries a generated QR
    # that survives placement and export with real bytes.
    generated = client.post(
        "/assets/generate/qr",
        json={
            "data": "https://lumen.example/a/acme-health",
            "label": "Acme landing QR",
            "print_media": True,
            "target_width_mm": 24.0,
        },
    ).json()
    record = generated["asset"]

    document = create_document(client)
    operations = asset_operations()
    # QR codes are square; align the slot policy and drop the DPI
    # requirement (vector assets carry no raster DPI).
    operations[1]["slot"]["image_policy"]["aspect_ratio"] = 1.0
    operations[1]["slot"]["image_policy"]["min_dpi"] = None
    operations[2] = {"kind": "upsert_asset", "asset": record}
    operations[3]["asset_id"] = record["id"]
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": operations,
            "actor": {"kind": "agent", "id": "agent_design"},
            "source": "agent",
        },
    )
    assert applied.status_code == 200, applied.text

    scene = client.get(f"/documents/{document['id']}").json()["scene"]
    exported = client.post(
        "/export-preview",
        json={"scene": scene, "format": "svg", "page_ids": ["page_a4"]},
    )
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    svg_text = payload["export"]["artifacts"][0].get("text") or ""
    assert "data:image/svg+xml;base64," in svg_text
    for diagnostic in payload["diagnostics"]:
        assert diagnostic["code"] not in {"LUME0202", "LUME0210", "LUME0211"}


def test_asset_library_list_search_and_filter(client: TestClient) -> None:
    uploaded = upload_logo(client).json()["asset"]
    generated = client.post(
        "/assets/generate/qr",
        json={"data": "https://lumen.example/a/acme-health", "label": "Acme QR"},
    ).json()["asset"]

    listed = client.get("/assets").json()
    listed_ids = {asset["id"] for asset in listed["assets"]}
    assert {uploaded["id"], generated["id"]} <= listed_ids

    vectors = client.get("/assets", params={"kind": "vector"}).json()
    assert {asset["id"] for asset in vectors["assets"]} == {generated["id"]}

    by_label = client.get("/assets", params={"q": "acme logo"}).json()
    assert {asset["id"] for asset in by_label["assets"]} == {uploaded["id"]}

    by_tag = client.get("/assets", params={"q": "qr"}).json()
    assert generated["id"] in {asset["id"] for asset in by_tag["assets"]}

    nothing = client.get("/assets", params={"q": "no-such-asset"}).json()
    assert nothing["assets"] == []


def test_archived_assets_are_excluded_by_default(client: TestClient) -> None:
    record = upload_logo(client).json()["asset"]

    archived = client.post(f"/assets/{record['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["asset"]["status"] == "archived"

    default_list = client.get("/assets").json()
    assert record["id"] not in {asset["id"] for asset in default_list["assets"]}

    with_archived = client.get("/assets", params={"include_archived": True}).json()
    assert record["id"] in {asset["id"] for asset in with_archived["assets"]}

    restored = client.post(f"/assets/{record['id']}/restore")
    assert restored.json()["asset"]["status"] == "ready"
    assert record["id"] in {
        asset["id"] for asset in client.get("/assets").json()["assets"]
    }


def test_hard_delete_refuses_while_documents_reference_the_asset(
    client: TestClient,
) -> None:
    record = upload_logo(client).json()["asset"]
    document = create_document(client)
    operations = asset_operations()
    operations[1]["slot"]["image_policy"]["aspect_ratio"] = 1.0
    operations[2] = {"kind": "upsert_asset", "asset": record}
    operations[3]["asset_id"] = record["id"]
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": operations,
            "actor": {"kind": "user", "id": "designer"},
            "source": "editor",
        },
    )
    assert applied.status_code == 200, applied.text

    refused = client.delete(f"/assets/{record['id']}")
    assert refused.status_code == 409
    assert "referenced" in refused.json()["detail"]

    # The record and bytes survive the refusal.
    assert client.get(f"/assets/{record['id']}").status_code == 200
    assert client.get(f"/assets/{record['id']}/bytes").status_code == 200


def test_hard_delete_byte_lifecycle_respects_digest_references(
    client: TestClient, tmp_path: Path
) -> None:
    first = upload_logo(client).json()["asset"]
    second = upload_logo(client).json()["asset"]
    assert first["media"]["digest"] == second["media"]["digest"]
    assert len(store_files(tmp_path)) == 2  # shared bytes + shared thumbnail

    # Deleting one record keeps the bytes: the digest is still referenced.
    deleted = client.delete(f"/assets/{first['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["removed_digests"] == []
    assert len(store_files(tmp_path)) == 2
    assert client.get(f"/assets/{first['id']}").status_code == 404
    assert client.get(f"/assets/{second['id']}/bytes").status_code == 200

    # Deleting the last record garbage-collects bytes and thumbnail.
    deleted = client.delete(f"/assets/{second['id']}")
    assert deleted.status_code == 200, deleted.text
    assert len(deleted.json()["removed_digests"]) == 2
    assert store_files(tmp_path) == []


def test_licensing_rejection_blocks_print_export_end_to_end(
    client: TestClient,
) -> None:
    # Conformance for slice E9 (Decision 5): licensing recorded at ingest
    # is enforced at export with a precise diagnostic.
    uploaded = client.post(
        "/assets",
        files={"file": ("editorial.png", LOGO_PNG_PATH.read_bytes(), "image/png")},
        data={
            "label": "Editorial photo",
            "license_json": json.dumps(
                {
                    "name": "editorial_only",
                    "allow_export": False,
                    "allow_modification": False,
                    "allow_embedding": False,
                    "allow_subsetting": False,
                    "source_url": None,
                    "restrictions": ["no commercial export"],
                }
            ),
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    record = uploaded.json()["asset"]
    assert record["license"]["allow_export"] is False

    # Place into a node directly: slot placement already rejects
    # non-exportable assets at operation time (LUMA0400); the node path
    # exercises export-time enforcement.
    document = create_document(client)
    operations = [
        {
            "kind": "insert_node",
            "parent": {"kind": "page", "id": "page_a4"},
            "index": 1,
            "node": asset_placeholder_node(),
        },
        {"kind": "upsert_asset", "asset": record},
        {
            "kind": "place_asset_in_node",
            "node_id": "node_hero_image",
            "asset_id": record["id"],
            "placement": {"fit": "cover", "alt_text": "Editorial photo"},
        },
    ]
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": operations,
            "actor": {"kind": "user", "id": "designer"},
            "source": "editor",
        },
    )
    assert applied.status_code == 200, applied.text
    scene = client.get(f"/documents/{document['id']}").json()["scene"]

    # Critic-style preview still renders, carrying the LUME0212 warning.
    preview = client.post(
        "/export-preview",
        json={"scene": scene, "format": "svg", "page_ids": ["page_a4"]},
    )
    assert preview.status_code == 200, preview.text
    preview_payload = preview.json()
    warning = next(
        diagnostic
        for diagnostic in preview_payload["diagnostics"]
        if diagnostic["code"] == "LUME0212"
    )
    assert warning["severity"] == "warning"

    # A print-intent export is rejected, naming the asset and license.
    rejected = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "svg",
            "page_ids": ["page_a4"],
            "profile": {
                "name": "print_letter",
                "format": "svg",
                "pdf_intent": "print",
                "raster": None,
                "include_bleed": False,
                "embed_fonts": True,
            },
        },
    )
    assert rejected.status_code == 200, rejected.text
    rejected_payload = rejected.json()
    assert rejected_payload["status"] == "failed"
    rejection = next(
        diagnostic
        for diagnostic in rejected_payload["diagnostics"]
        if diagnostic["code"] == "LUME0212"
    )
    assert rejection["severity"] == "error"
    assert record["id"] in rejection["message"]
    assert "editorial_only" in rejection["message"]


# ---------------------------------------------------------------------------
# Phase G personalization runtime (slice G8)
# ---------------------------------------------------------------------------

MAILER_REVISION_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/conformance/phase_g_mailer_revision.json"
)
BINDING_FIXTURES_DIR = REPO_ROOT / "crates/lumen-core/fixtures/binding"


def mailer_revision_scene_draft(document_id: str) -> dict:
    scene = json.loads(MAILER_REVISION_PATH.read_text())
    scene["meta"]["id"] = document_id
    scene["meta"]["status"] = {"kind": "draft"}
    return scene


def binding_fixture_payload(name: str) -> dict:
    return json.loads((BINDING_FIXTURES_DIR / f"{name}.json").read_text())


def upload_logo_asset(client: TestClient, label: str = "Acme logo") -> dict:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    # The mailer's logo slot policy demands transparency and 300 DPI.
    # 305 DPI absorbs PNG pHYs quantization (300 DPI stores as 299.9994
    # px/m-rounded, which the strict min_dpi check rejects).
    Image.new("RGBA", (600, 200), (200, 30, 60, 255)).save(
        buffer, format="PNG", dpi=(305, 305)
    )
    buffer.seek(0)
    response = client.post(
        "/assets",
        files={"file": ("logo.png", buffer, "image/png")},
        data={"label": label, "kind": "logo"},
    )
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def finalize_mailer_revision(client: TestClient) -> str:
    document_id = "doc_g8_mailer"
    scene = mailer_revision_scene_draft(document_id)
    created = client.post(
        "/documents", json={"document_id": document_id, "scene": scene}
    )
    assert created.status_code == 200, created.text
    finalized = client.post(
        f"/documents/{document_id}/finalize",
        json={"template_revision_id": "tmpl_mailer_v1"},
    )
    assert finalized.status_code == 200, finalized.text
    return "tmpl_mailer_v1"


def stored_binding(client: TestClient, name: str, logo_asset_id: str) -> str:
    binding = binding_fixture_payload(name)
    binding["values"]["account.logo"]["asset_id"] = logo_asset_id
    response = client.post("/binding-sets", json={"binding_set": binding})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "valid"
    return binding["binding_set_id"]


def test_binding_set_crud_validates_on_write(client: TestClient) -> None:
    revision_id = finalize_mailer_revision(client)
    logo = upload_logo_asset(client)

    binding_set_id = stored_binding(client, "nominal", logo["id"])
    loaded = client.get(f"/binding-sets/{binding_set_id}")
    assert loaded.status_code == 200
    assert loaded.json()["template_revision_id"] == revision_id

    listed = client.get("/binding-sets", params={"template_revision_id": revision_id})
    assert [b["binding_set_id"] for b in listed.json()["binding_sets"]] == [
        binding_set_id
    ]

    # Invalid binding sets are rejected on write with precise codes.
    invalid = binding_fixture_payload("nominal")
    invalid["binding_set_id"] = "bind_invalid"
    invalid["values"].pop("contact.full_name")
    rejected = client.post("/binding-sets", json={"binding_set": invalid})
    assert rejected.status_code == 422, rejected.text
    detail = rejected.json()["detail"]
    assert detail["code"] == "binding_set.invalid"
    assert any(d["code"] == "LUMG0012" for d in detail["diagnostics"])
    assert client.get("/binding-sets/bind_invalid").status_code == 404

    deleted = client.delete(f"/binding-sets/{binding_set_id}")
    assert deleted.status_code == 200
    assert client.get(f"/binding-sets/{binding_set_id}").status_code == 404


def test_instance_derivation_route_persists_derived_artifacts(
    client: TestClient,
) -> None:
    revision_id = finalize_mailer_revision(client)
    logo = upload_logo_asset(client)
    binding_set_id = stored_binding(client, "nominal", logo["id"])

    response = client.post(
        f"/template-revisions/{revision_id}/instances",
        json={"binding_set_id": binding_set_id, "export_formats": ["svg"]},
    )
    assert response.status_code == 200, response.text
    instance = response.json()
    assert instance["status"] == "derived"
    assert instance["fit_status"] == "fits"
    assert instance["instance_id"] == "inst_tmpl_mailer_v1_bind_acme_dr_sharma"
    assert instance["derived_scene"]["nodes"]["node_headline"]["kind"]["content"] == (
        "Dr. Priya Sharma"
    )
    assert len(instance["artifacts"]) == 1
    assert instance["artifacts"][0]["format"] == "svg"
    assert instance["audit"], "audit trail persists"

    # The generated QR became a first-class asset record.
    qr_asset_id = "asset_gen_bind_acme_dr_sharma_qr_landing"
    qr_bytes = client.get(f"/assets/{qr_asset_id}/bytes")
    assert qr_bytes.status_code == 200, qr_bytes.text
    assert b"<svg" in qr_bytes.content

    # Readback (with and without the derived scene cache).
    loaded = client.get(f"/instances/{instance['instance_id']}")
    assert loaded.status_code == 200
    slim = client.get(
        f"/instances/{instance['instance_id']}", params={"include_scene": False}
    )
    assert "derived_scene" not in slim.json()

    # Re-deriving upserts the same instance row (derived artifacts, not
    # documents): identical id, identical derived scene.
    again = client.post(
        f"/template-revisions/{revision_id}/instances",
        json={"binding_set_id": binding_set_id, "export_formats": ["svg"]},
    ).json()
    assert again["instance_id"] == instance["instance_id"]
    assert again["derived_scene"] == instance["derived_scene"]
    assert again["artifacts"][0]["digest_value"] == (
        instance["artifacts"][0]["digest_value"]
    )

    listed = client.get(f"/template-revisions/{revision_id}/instances").json()
    assert len(listed["instances"]) == 1


def test_instance_batch_processes_chunks_with_resumable_cursor(
    client: TestClient,
) -> None:
    revision_id = finalize_mailer_revision(client)
    logo = upload_logo_asset(client)
    ids = [
        stored_binding(client, "nominal", logo["id"]),
        stored_binding(client, "missing_optional", logo["id"]),
        stored_binding(client, "worst_case", logo["id"]),
    ]

    response = client.post(
        f"/template-revisions/{revision_id}/batches",
        json={"binding_set_ids": ids, "export_formats": ["svg"], "chunk_size": 2},
    )
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["status"] == "completed"
    assert batch["cursor"] == 3
    assert batch["counts"]["total"] == 3
    # worst_case's headline cannot fit even at min font => failed.
    assert batch["counts"]["derived"] == 2
    assert batch["counts"]["failed"] == 1
    assert batch["counts"]["fit"]["overflow"] == 1
    assert len(batch["manifest"]) == 3

    by_binding = {entry["binding_set_id"]: entry for entry in batch["manifest"]}
    assert by_binding["bind_meridian_dr_whitmore"]["status"] == "failed"
    assert by_binding["bind_meridian_dr_whitmore"]["artifacts"] == []
    assert by_binding["bind_acme_dr_sharma"]["artifacts"], "derived instances export"

    failed_instance = client.get(
        f"/instances/{by_binding['bind_meridian_dr_whitmore']['instance_id']}"
    ).json()
    assert any(
        d["code"] == "LUMG0321" for d in failed_instance["diagnostics"]
    ), "the overflow is surfaced, never silent"

    # Resume seam: simulate an interrupted batch (cursor persisted after
    # chunk one, manifest truncated to the committed work).
    import sqlite3 as _sqlite3

    connection = _sqlite3.connect(str(client.app.state.database_path))
    connection.execute(
        """
        UPDATE instance_batches
        SET cursor = 1, status = 'running',
            manifest_json = ?, counts_json = ?
        WHERE batch_id = ?
        """,
        (
            json.dumps([batch["manifest"][0]]),
            json.dumps(
                {
                    "total": 3,
                    "derived": 1,
                    "failed": 0,
                    "fit": {"fits": 1, "fits_with_policy": 0, "overflow": 0},
                }
            ),
            batch["batch_id"],
        ),
    )
    connection.commit()
    connection.close()

    resumed = client.post(f"/batches/{batch['batch_id']}/resume")
    assert resumed.status_code == 200, resumed.text
    resumed_batch = resumed.json()
    assert resumed_batch["status"] == "completed"
    assert resumed_batch["cursor"] == 3
    assert len(resumed_batch["manifest"]) == 3
    assert resumed_batch["counts"]["derived"] == 2

    # Idempotence across the resume: re-derived instances carry the same
    # artifact digests as the first run (only the store's deduplicated
    # flag flips, because the bytes already exist).
    def artifact_identity(artifacts: list) -> list:
        return [
            {k: v for k, v in artifact.items() if k != "deduplicated"}
            for artifact in artifacts
        ]

    original = {
        entry["binding_set_id"]: artifact_identity(entry["artifacts"])
        for entry in batch["manifest"]
    }
    for entry in resumed_batch["manifest"]:
        assert artifact_identity(entry["artifacts"]) == (
            original[entry["binding_set_id"]]
        )
    # The re-processed entry (after the simulated crash point) re-stored
    # its bytes and hit the content-addressed store.
    reprocessed = next(
        entry
        for entry in resumed_batch["manifest"]
        if entry["binding_set_id"] == "bind_northcare_ms_okafor"
    )
    for artifact in reprocessed["artifacts"]:
        assert artifact["deduplicated"] is True, (
            "resume must hit the content-addressed store"
        )

    loaded = client.get(f"/batches/{batch['batch_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["status"] == "completed"


def test_batch_rejects_unknown_or_mismatched_binding_sets(
    client: TestClient,
) -> None:
    revision_id = finalize_mailer_revision(client)
    missing = client.post(
        f"/template-revisions/{revision_id}/batches",
        json={"binding_set_ids": ["bind_ghost"]},
    )
    assert missing.status_code == 404

    empty = client.post(
        f"/template-revisions/{revision_id}/batches",
        json={"binding_set_ids": []},
    )
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "batch.empty"
