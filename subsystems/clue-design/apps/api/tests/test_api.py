from __future__ import annotations

import base64
import copy
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client, unique_run_id

from lumen_api import image_provider
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.main import agent_response_from_trace, create_app
from py_lumen_config import settings
from py_lumen_obs import bind_request_id, get_logger, unbind_context
from py_lumen_obs.testing import capture_events


def _spend_test_stamp():
    from clue_spend import LedgerStamp

    return LedgerStamp(workspace_id="ws_image_tests")


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
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def _workspace_blobs() -> DesignBlobStore:
    """This test's byte store on the process-configured backend.

    D5 Round C made ``blobs`` REQUIRED on the by-value turn resolvers (they used to default to
    ``api_blob_store()``, i.e. the dev workspace, which meant an unthreaded caller silently read
    another tenant's library). This is exactly what that default resolved to under the autouse
    isolation fixture, so the tests below still exercise the same rows — they just have to say
    which tenant they mean now.
    """
    from lumen_api.main import api_blob_store

    return api_blob_store(os.environ["LUMEN_DEV_WORKSPACE_ID"])


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


def test_build_info_reports_engine_handshake(client: TestClient) -> None:
    """Track E W5: the editor compares this payload against the WASM
    module's version() and downgrades to server-only mode on mismatch."""
    response = client.get("/build-info")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 1
    build_info = payload["build_info"]
    assert build_info["schema_version"] == 1
    assert isinstance(build_info["engine_commit"], str)
    assert build_info["engine_commit"]

    # Cached per process: a second call returns the identical payload.
    second = client.get("/build-info")
    assert second.status_code == 200
    assert second.json() == payload


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
            # Legacy senders may still include the dropped back-compat key;
            # it must be IGNORED (pydantic extra), never a 422.
            "selected_node_id": "node_legacy_ignored",
            "target_node_ids": ["node_contact_name"],
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
    assert captured["payload"].target_node_ids == ["node_contact_name"]
    assert not hasattr(captured["payload"], "selected_node_id")
    assert captured["root"] == REPO_ROOT


def test_resolve_agent_turn_brand_kit_passes_document_kit_by_value(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K0 kit application: a turn whose scene references an attached Brand Kit
    resolves the full kit JSON from the library (passed by value into the
    runtime config); resolution failures degrade to (None, None) so the turn
    itself can never fail on kit lookup."""
    from lumen_api.main import api_blob_store, resolve_agent_turn_brand_kit
    from lumen_api.models import AgentTurnPreviewRequest

    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")

    scene = preflightable_scene()
    scene["meta"]["brand_kit"] = {"id": "brand_kit_insight_health", "version": 4}
    kit, source, manifest, brand_fonts = resolve_agent_turn_brand_kit(
        AgentTurnPreviewRequest(prompt="Restyle the letter", scene=scene),
        _workspace_blobs(),
    )
    assert source == "document"
    assert kit is not None
    assert kit["id"] == "brand_kit_insight_health"
    assert kit["version"] == 4
    # K2: a styles-compiled kit has no logo/image assets → empty manifest,
    # not an error. K3: its font faces carry no asset_ids → no font spec
    # (bundled fallback), not an error.
    assert manifest == {}
    assert brand_fonts is None

    # No scene ref → no kit (platform-default behavior unchanged).
    assert resolve_agent_turn_brand_kit(
        AgentTurnPreviewRequest(prompt="x", scene=preflightable_scene()),
        _workspace_blobs(),
    ) == (None, None, None, None)

    # Unknown kit id → graceful Nones, never an exception.
    ghost = preflightable_scene()
    ghost["meta"]["brand_kit"] = {"id": "brand_kit_ghost", "version": 1}
    assert resolve_agent_turn_brand_kit(
        AgentTurnPreviewRequest(prompt="x", scene=ghost),
        _workspace_blobs(),
    ) == (None, None, None, None)

    # K2: a kit WITH a logo asset yields a manifest carrying the library
    # record verbatim plus the human usage guidance.
    uploaded = upload_logo(client, label="Insight reversed lockup")
    assert uploaded.status_code == 200, uploaded.text
    logo_asset_id = uploaded.json()["asset"]["id"]
    described = client.put(
        f"/assets/{logo_asset_id}/description",
        json={"usage": "Use on dark or brand-colored fields."},
    )
    assert described.status_code == 200, described.text

    kit_with_logo = json.loads(
        json.dumps(client.get("/brand-kits/brand_kit_insight_health").json()["brand_kit_json"])
    )
    kit_with_logo["id"] = "brand_kit_insight_with_logo"
    kit_with_logo["assets"]["logos"] = {
        "primary": {
            "variants": [
                {
                    "name": "reversed",
                    "asset_id": logo_asset_id,
                    "color_mode": "reversed",
                    "width": 8.0,
                    "height": 8.0,
                }
            ],
            "usage": "primary",
            "min_size": 8.0,
            "clearspace": None,
            "allowed_backgrounds": ["surface.brand"],
            "license": None,
            "provenance": {"source": "manual", "confidence": 1.0},
        }
    }
    created = client.post(
        "/brand-kits", json={"brand_kit": kit_with_logo, "source": "manual"}
    )
    assert created.status_code == 200, created.text

    logo_scene = preflightable_scene()
    logo_scene["meta"]["brand_kit"] = {
        "id": "brand_kit_insight_with_logo",
        "version": kit_with_logo["version"],
    }
    kit, source, manifest, _ = resolve_agent_turn_brand_kit(
        AgentTurnPreviewRequest(prompt="Add our logo", scene=logo_scene),
        _workspace_blobs(),
    )
    assert kit is not None and source == "document"
    entry = manifest[logo_asset_id]
    assert entry["record"]["id"] == logo_asset_id
    assert entry["record"]["media"]["digest"]["algorithm"] == "sha256"
    assert entry["usage"] == "Use on dark or brand-colored fields."


def test_zero_face_brand_font_uses_inter_and_reports_the_server_fallback(
    client: TestClient,
) -> None:
    """A pinned kit may name a family without carrying licensed face bytes.

    That is an explicit, deterministic degradation — not permission to fetch
    an arbitrary system/web font. The server's Skia path must use bundled
    Inter and report LUMS0100, matching the browser's renderer diagnostic.
    """
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_zero_face_fallback",
            "version": 4,
            "name": "Zero-face fallback",
        },
    )
    assert compiled.status_code == 200, compiled.text

    scene = preflightable_scene()
    scene["meta"]["brand_kit"] = {
        "id": "brand_kit_zero_face_fallback",
        "version": 4,
    }
    scene["nodes"]["node_contact_name"]["kind"]["font_family"] = "Source Sans 3"

    exported = client.post(
        "/export-preview",
        json={"scene": scene, "format": "png", "page_ids": ["page_a4"]},
    )
    assert exported.status_code == 200, exported.text
    current = exported.json().get("diagnostics") or []
    fallback = next(
        (diagnostic for diagnostic in current if diagnostic.get("code") == "LUMS0100"),
        None,
    )
    assert fallback is not None, current
    assert "Source Sans 3" in fallback["message"]
    assert "Inter" in fallback["message"]


def test_brand_kit_font_faces_ride_preflight_as_store_digests(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K3 server font fidelity: a kit whose font faces reference stored font
    assets yields a {store_root, digests} spec (via the agent-turn resolver),
    and a real-engine /preflight-preview against that kit stays clean — the
    helper loads the face bytes from the store instead of erroring."""
    from lumen_api.main import api_blob_store, resolve_agent_turn_brand_kit
    from lumen_api.models import AgentTurnPreviewRequest

    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text

    font_path = Path(__file__).resolve().parents[3] / "fonts" / "Inter-Regular.ttf"
    uploaded = client.post(
        "/assets",
        files={"file": ("Inter-Regular.ttf", font_path.read_bytes(), "font/ttf")},
        data={"label": "Inter Regular", "kind": "font"},
    )
    assert uploaded.status_code == 200, uploaded.text
    font_asset = uploaded.json()["asset"]
    font_digest = font_asset["media"]["digest"]["value"]

    kit_with_font = json.loads(
        json.dumps(
            client.get("/brand-kits/brand_kit_insight_health").json()["brand_kit_json"]
        )
    )
    kit_with_font["id"] = "brand_kit_insight_with_font"
    kit_with_font["assets"]["fonts"]["brand"]["faces"][0]["asset_id"] = font_asset["id"]
    created = client.post(
        "/brand-kits", json={"brand_kit": kit_with_font, "source": "manual"}
    )
    assert created.status_code == 200, created.text

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    scene = preflightable_scene()
    scene["meta"]["brand_kit"] = {
        "id": "brand_kit_insight_with_font",
        "version": kit_with_font["version"],
    }
    kit, source, _, brand_fonts = resolve_agent_turn_brand_kit(
        AgentTurnPreviewRequest(prompt="Set our type", scene=scene),
        _workspace_blobs(),
    )
    assert kit is not None and source == "document"
    assert brand_fonts is not None
    # Spec faces now ride with their per-face weight/style (P2.5 enrichment);
    # this kit face records 400/normal.
    assert brand_fonts["faces"] == [
        {"digest": font_digest, "family": "Source Sans 3", "weight": 400, "style": "normal"}
    ]
    assert (Path(brand_fonts["store_root"]) / "sha256").exists()

    # Real engine round trip: the spec flows through /preflight-preview and
    # the helper reads the face bytes from the store — clean result, no
    # LUMS0101 (unloadable face) diagnostics.
    previewed = client.post(
        "/preflight-preview",
        json={"scene": scene, "brand_kit_id": "brand_kit_insight_with_font"},
    )
    assert previewed.status_code == 200, previewed.text
    codes = [
        d.get("code")
        for d in (previewed.json().get("diagnostics") or {}).get("current", [])
    ]
    assert "LUMS0101" not in codes


REFERENCE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
    b'<rect width="120" height="80" fill="#3366CC"/></svg>'
)


def upload_reference_svg(client: TestClient):
    # NOTE: the engine AssetKind enum has no "reference" variant, so the upload
    # omits `kind` (the engine auto-classifies SVG → vector); reference-ness is
    # carried by tags, exactly as the editor sends it.
    return client.post(
        "/assets",
        files={"file": ("wash.svg", REFERENCE_SVG, "image/svg+xml")},
        data={"label": "Soft wash", "tags": "reference,chat-attachment"},
    )


def test_reference_manifest_matches_config_contract_shape(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC (D2): a raster reference resolves to the exact config.py
    reference_assets contract — record verbatim, the asset's OWN sha256 as
    preview_digest, mime/dims/dominant_colors/order — and dedupes ids
    preserving first-occurrence order."""
    from lumen_api.main import api_blob_store, resolve_agent_turn_references
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    uploaded = upload_logo(client)
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()["asset"]
    asset_id = asset["id"]
    own_digest = asset["media"]["digest"]["value"]

    # Duplicate id + empty id: deduped, order preserved, still one entry.
    manifest = resolve_agent_turn_references(
        AgentTurnPreviewRequest(
            prompt="Match this",
            scene=minimal_scene(),
            reference_asset_ids=[asset_id, "", asset_id],
        ),
        _workspace_blobs(),
    )
    assert set(manifest.keys()) == {asset_id}
    entry = manifest[asset_id]
    assert set(entry.keys()) == {
        "record",
        "preview_digest",
        "mime_type",
        "width",
        "height",
        "dominant_colors",
        "title",
        "description",
        "order",
    }
    assert entry["record"]["id"] == asset_id
    assert entry["preview_digest"] == own_digest  # raster: its own digest
    assert entry["mime_type"] == "image/png"
    assert entry["order"] == 0
    assert isinstance(entry["dominant_colors"], list)
    assert isinstance(entry["width"], int) and isinstance(entry["height"], int)


def test_reference_manifest_no_ids_is_none(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No reference ids → None: the turn is byte-identical to today (and no DB
    connection is opened)."""
    from lumen_api.main import api_blob_store, resolve_agent_turn_references
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    assert (
        resolve_agent_turn_references(
            AgentTurnPreviewRequest(prompt="x", scene=minimal_scene()),
            _workspace_blobs(),
        )
        is None
    )


def test_reference_manifest_svg_materializes_raster_preview(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC (D2): an SVG reference is engine-rasterized at resolve time — its
    preview_digest is a PNG that exists in the shared store, NOT the SVG's own
    digest, and mime_type reports the raster."""
    from fastapi import HTTPException  # noqa: F401  (kept for parity w/ 422 tests)
    from lumen_api.main import api_blob_store, resolve_agent_turn_references
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    uploaded = upload_reference_svg(client)
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()["asset"]
    asset_id = asset["id"]
    svg_digest = asset["media"]["digest"]["value"]

    manifest = resolve_agent_turn_references(
        AgentTurnPreviewRequest(
            prompt="Match this",
            scene=minimal_scene(),
            reference_asset_ids=[asset_id],
        ),
        _workspace_blobs(),
    )
    entry = manifest[asset_id]
    preview_digest = entry["preview_digest"]
    assert preview_digest != svg_digest
    assert entry["mime_type"] == "image/png"
    # D4: the rasterized preview gets DURABLE custody (it is a real derived artifact) and is
    # mirrored into the engine cache, which is where the runtime's `view("reference:<n>")`
    # reads it from. Both halves are the contract; the durable one is the load-bearing half.
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    blobs = make_blob_store(client.app)
    assert blobs.exists(preview_digest), "rasterized SVG preview must be durably stored"
    cache_blob = (
        tmp_path / "engine-cache" / workspace_id / "sha256" / preview_digest[:2] / preview_digest
    )
    assert cache_blob.is_file(), "and mirrored into the engine cache the runtime reads"


def test_reference_manifest_unknown_id_is_422(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC (D2): a missing id is EXPLICIT user intent gone wrong — a hard 422
    naming the id, never a silent skip like the kit manifest."""
    from fastapi import HTTPException
    from lumen_api.main import api_blob_store, resolve_agent_turn_references
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    # Touch the store so the db/store exist for this run.
    upload_logo(client)
    with pytest.raises(HTTPException) as excinfo:
        resolve_agent_turn_references(
            AgentTurnPreviewRequest(
                prompt="x",
                scene=minimal_scene(),
                reference_asset_ids=["asset_ghost"],
            ),
            _workspace_blobs(),
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "reference.asset_not_found"
    assert "asset_ghost" in excinfo.value.detail["message"]


def test_reference_manifest_too_many_is_422(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC (D1): >4 references → 422 reference.too_many (cap enforced API-side)."""
    from fastapi import HTTPException
    from lumen_api.main import api_blob_store, resolve_agent_turn_references
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    with pytest.raises(HTTPException) as excinfo:
        resolve_agent_turn_references(
            AgentTurnPreviewRequest(
                prompt="x",
                scene=minimal_scene(),
                reference_asset_ids=[f"asset_{i}" for i in range(5)],
            ),
            _workspace_blobs(),
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "reference.too_many"


def test_async_agent_turns_route_422s_on_bad_reference_before_creating_a_run(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC adversarial-gate ship-blocker 1: on the LIVE editor path
    (POST /agent/turns) a bad attachment must surface as a REAL 422 from the
    route handler — validated BEFORE the run row exists — never be swallowed
    by the worker's catch-all into a generic agent_runtime.failed run."""
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    response = client.post(
        "/agent/turns",
        json={
            "prompt": "x",
            "scene": minimal_scene(),
            "reference_asset_ids": ["asset_ghost"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "reference.asset_not_found"
    # No run row was created: the runs listing endpoint knows nothing new.
    # (A swallowed 422 would have produced a run with a failed result.)


def test_agent_turn_forwards_references_into_config(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC (D2): run_agent_turn_preview resolves the ids and threads the manifest
    into config.reference_assets BY VALUE (mirrors the kit/target-node
    forwarding), pinning the store root so the runtime resolves preview bytes."""
    import lumen_agent.harness as harness_mod
    import lumen_agent.llm as llm_mod

    from lumen_api.main import repo_root, run_agent_turn_preview
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    asset_id = upload_logo(client).json()["asset"]["id"]

    captured: dict = {}

    class _Stop(Exception):
        pass

    def fake_run(prompt, config, **kwargs):
        captured["config"] = config
        raise _Stop()

    monkeypatch.setattr(harness_mod, "run_deepagent_turn", fake_run)
    monkeypatch.setattr(
        llm_mod, "assert_model_supports_image_input", lambda *a, **k: None
    )

    run_agent_turn_preview(
        AgentTurnPreviewRequest(
            prompt="Match these references",
            scene=minimal_scene(),
            reference_asset_ids=[asset_id],
        ),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )
    config = captured["config"]
    assert config.reference_assets is not None
    assert asset_id in config.reference_assets
    assert config.reference_assets[asset_id]["order"] == 0
    # D4: the runtime is pinned to the turn workspace's ENGINE MATERIALIZATION CACHE — the
    # same tree the API's own engine calls use, which is what keeps seeded imagery resolvable.
    assert config.asset_store_root == (
        tmp_path / "engine-cache" / os.environ["LUMEN_DEV_WORKSPACE_ID"]
    )


def test_agent_turn_without_references_leaves_config_unset(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RC: a no-reference turn never sets config.reference_assets (byte-identical
    to pre-RC behavior)."""
    import lumen_agent.harness as harness_mod
    import lumen_agent.llm as llm_mod

    from lumen_api.main import repo_root, run_agent_turn_preview
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")

    captured: dict = {}

    class _Stop(Exception):
        pass

    def fake_run(prompt, config, **kwargs):
        captured["config"] = config
        raise _Stop()

    monkeypatch.setattr(harness_mod, "run_deepagent_turn", fake_run)
    monkeypatch.setattr(
        llm_mod, "assert_model_supports_image_input", lambda *a, **k: None
    )

    run_agent_turn_preview(
        AgentTurnPreviewRequest(prompt="Design a poster", scene=minimal_scene()),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )
    assert captured["config"].reference_assets is None


# --- W1.1: the workspace asset library reaches the SCENE turn ---------------


def _stub_scene_turn_runtime(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture the config a scene turn hands the runtime, without running one."""
    import lumen_agent.harness as harness_mod
    import lumen_agent.llm as llm_mod

    captured: dict = {}

    class _Stop(Exception):
        pass

    def fake_run(prompt, config, **kwargs):
        captured["config"] = config
        raise _Stop()

    monkeypatch.setattr(harness_mod, "run_deepagent_turn", fake_run)
    monkeypatch.setattr(
        llm_mod, "assert_model_supports_image_input", lambda *a, **k: None
    )
    return captured


def test_agent_turn_forwards_the_workspace_asset_library_into_config(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W1.1 (Brand Ad Assets v1 §5, item 1) — RED before the fix.

    `workspace_asset_library_manifest` had one call site, the WEBSITE turn, so a
    scene turn's config carried only `brand_kit_assets` + `reference_assets`. A
    library asset that was neither could not be viewed and could not be placed
    (Apollo POC 2026-08-26, `.context/ref-ads-pilot-apollo-report.md` §6.1). The
    manifest must now ride the scene run BY VALUE — and its bytes must be
    materialized into the turn's engine cache, or a placed asset renders empty.
    """
    from lumen_api.asset_custody import cache_blob_path, record_digests
    from lumen_api.main import repo_root, run_agent_turn_preview
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    asset_id = upload_logo(client).json()["asset"]["id"]
    cache_dir = tmp_path / "engine-cache" / os.environ["LUMEN_DEV_WORKSPACE_ID"]
    record = HybridRepository().require_asset_record(asset_id)["asset"]
    for digest, _mime in record_digests(record):
        cache_blob_path(cache_dir, digest).unlink(missing_ok=True)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        AgentTurnPreviewRequest(prompt="Design an ad", scene=minimal_scene()),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )
    config = captured["config"]
    assert config.asset_library is not None
    assert asset_id in config.asset_library
    entry = config.asset_library[asset_id]
    assert entry["record"]["id"] == asset_id
    assert entry["record"]["status"] == "ready"

    # Inventory is metadata-only. Bytes arrive on explicit inspection or placement.
    cache_dir = tmp_path / "engine-cache" / os.environ["LUMEN_DEV_WORKSPACE_ID"]
    digests = [digest for digest, _mime in record_digests(entry["record"])]
    assert digests
    assert all(not cache_blob_path(cache_dir, digest).is_file() for digest in digests)
    config.asset_materializer(asset_id)
    assert all(cache_blob_path(cache_dir, digest).is_file() for digest in digests)


def test_agent_turn_forwards_the_workspace_image_vectors_into_config(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hybrid asset search (2026-10-05): the scene turn's config carries the workspace's CLIP
    vectors BY VALUE next to the library, read for the turn's own workspace — and an empty map
    (visual search off or unavailable) still lets the turn run."""
    from lumen_api import asset_embeddings
    from lumen_api.main import repo_root, run_agent_turn_preview
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    asset_id = upload_logo(client).json()["asset"]["id"]
    asked = []

    def fake_load(workspace_id, asset_ids=None):
        asked.append(workspace_id)
        return {asset_id: [0.0] * 511 + [1.0]}

    monkeypatch.setattr(asset_embeddings, "load_workspace_embeddings", fake_load)
    captured = _stub_scene_turn_runtime(monkeypatch)
    workspace = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    run_agent_turn_preview(AgentTurnPreviewRequest(prompt="Design an ad", scene=minimal_scene()),
                           repo_root(), workspace_id=workspace)
    assert asked == [workspace]
    assert list(captured["config"].asset_embeddings) == [asset_id]

    monkeypatch.setattr(asset_embeddings, "load_workspace_embeddings", lambda *a, **k: {})
    captured = _stub_scene_turn_runtime(monkeypatch)
    run_agent_turn_preview(AgentTurnPreviewRequest(prompt="Design an ad", scene=minimal_scene()),
                           repo_root(), workspace_id=workspace)
    assert captured["config"].asset_embeddings == {}


def test_agent_turn_asset_library_keeps_older_assets_without_a_recent_cap(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full metadata coverage replaces the old recent-only materialization cap."""
    from lumen_api import main as main_mod
    from lumen_api.main import repo_root, run_agent_turn_preview
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    older = upload_logo(client, label="Older mark").json()["asset"]["id"]
    newer = upload_logo(client, label="Newer mark").json()["asset"]["id"]
    assert older != newer
    monkeypatch.setattr(main_mod, "SCENE_TURN_ASSET_LIBRARY_MAX", 1)
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        AgentTurnPreviewRequest(prompt="Design an ad", scene=minimal_scene()),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )
    library = captured["config"].asset_library
    assert set(library) == {older, newer}, library


def test_scene_turn_asset_library_drops_unplaceable_kinds(
    client: TestClient, tmp_path: Path
) -> None:
    """A font is not placeable in a scene. Shipping one would spend read-through on
    bytes no image node can bind and would waste a slot in a hard-capped manifest."""
    from lumen_api.main import api_engine_cache_root, scene_turn_asset_library_manifest

    repo = HybridRepository()
    font = json.loads(
        (REPO_ROOT / "crates/lumen-core/fixtures/assets/font_asset.json").read_text()
    )
    repo.create_asset_record(font)
    raster = generated_raster_asset()
    repo.create_asset_record(raster)

    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    manifest = scene_turn_asset_library_manifest(
        repo, _workspace_blobs(), str(api_engine_cache_root(workspace_id))
    )
    assert raster["id"] in manifest
    assert font["id"] not in manifest


def test_agent_turn_without_library_assets_leaves_config_unset(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-op guarantee: a workspace with an empty library runs exactly as it did
    before W1.1 — `config.asset_library` stays None, not an empty dict."""
    from lumen_api.main import repo_root, run_agent_turn_preview
    from lumen_api.models import AgentTurnPreviewRequest

    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    captured = _stub_scene_turn_runtime(monkeypatch)

    run_agent_turn_preview(
        AgentTurnPreviewRequest(prompt="Design a poster", scene=minimal_scene()),
        repo_root(),
        workspace_id=os.environ["LUMEN_DEV_WORKSPACE_ID"],
    )
    assert captured["config"].asset_library is None


def test_set_brand_kit_logo_publishes_new_version_with_human_choice(
    client: TestClient,
) -> None:
    """Human logo curation: POST /brand-kits/{id}/logo promotes a library
    asset into the chosen slot as a NEW kit version — manual provenance,
    approval state preserved, scraper's guess kept in history."""
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text
    approved = client.post(
        "/brand-kits/brand_kit_insight_health/approval",
        json={"approval_status": "approved"},
    )
    assert approved.status_code == 200, approved.text

    uploaded = upload_logo(client, label="The real lockup")
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["asset"]["id"]

    chosen = client.post(
        "/brand-kits/brand_kit_insight_health/logo",
        json={"asset_id": asset_id, "slot": "primary"},
    )
    assert chosen.status_code == 200, chosen.text
    kit = chosen.json()["brand_kit"]
    assert kit["version"] == 5

    detail = client.get("/brand-kits/brand_kit_insight_health").json()
    kit_json = detail["brand_kit_json"]
    assert kit_json["version"] == 5
    # approval survives the curation version bump
    assert kit_json["approval_status"] == "approved"
    primary = kit_json["assets"]["logos"]["primary"]
    assert [v["asset_id"] for v in primary["variants"]] == [asset_id]
    assert primary["provenance"]["confidence"] == 1.0
    assert primary["provenance"]["source"].startswith("manual :: human-selected")
    # history keeps the prior version
    assert client.get("/brand-kits/brand_kit_insight_health?version=4").status_code in (200, 404)

    # unknown asset → 404, kit untouched
    missing = client.post(
        "/brand-kits/brand_kit_insight_health/logo",
        json={"asset_id": "asset_ghost", "slot": "primary"},
    )
    assert missing.status_code == 404


def test_describe_assets_backfill_republishes_kit_with_metadata(
    client: TestClient,
) -> None:
    """Imagery slice 1 backfill: POST /brand-kits/{id}/describe-assets stamps
    cached asset descriptions onto the kit's entries and publishes a NEW
    version — descriptions are frozen into the kit JSON at publish, so
    healing the library alone never reaches the agent's brand card. With no
    describer configured (tests), the cache is the only source: cache-first
    behavior is exactly what's under test."""
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text

    uploaded = upload_logo(client, label="The real lockup")
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["asset"]["id"]
    chosen = client.post(
        "/brand-kits/brand_kit_insight_health/logo",
        json={"asset_id": asset_id, "slot": "primary"},
    )
    assert chosen.status_code == 200, chosen.text  # kit v5, real asset in slot

    # A human-authored library row is the cache the backfill stamps from.
    described = client.put(
        f"/assets/{asset_id}/description",
        json={
            "title": "Insight lockup",
            "description": "Teal squares beside INSIGHT HEALTH text.",
            "usage": "Use the reversed variant on dark surfaces.",
            "tags": ["logo"],
        },
    )
    assert described.status_code == 200, described.text

    backfilled = client.post(
        "/brand-kits/brand_kit_insight_health/describe-assets"
    )
    assert backfilled.status_code == 200, backfilled.text
    payload = backfilled.json()
    assert payload["published"] is True
    assert payload["counts"]["cached"] >= 1

    detail = client.get("/brand-kits/brand_kit_insight_health").json()
    kit_json = detail["brand_kit_json"]
    assert kit_json["version"] == 6
    primary = kit_json["assets"]["logos"]["primary"]
    assert primary["title"] == "Insight lockup"
    assert primary["description"] == "Teal squares beside INSIGHT HEALTH text."
    # usage guidance is its OWN field — never folded into description.
    assert primary["usage_note"] == "Use the reversed variant on dark surfaces."

    # Idempotence: nothing new to stamp → no no-op version published.
    again = client.post("/brand-kits/brand_kit_insight_health/describe-assets")
    assert again.status_code == 200, again.text
    assert again.json()["published"] is False
    assert (
        client.get("/brand-kits/brand_kit_insight_health").json()["brand_kit_json"][
            "version"
        ]
        == 6
    )


def test_logo_curation_keeps_the_kit_sections_the_engine_does_not_know(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave 2 A9 (Task X5): the logo route publishes the engine's validated kit, which dropped the
    brief, the grammar audit and the measured components; they are carried across now."""
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={"source": valid_styles_source(), "brand_kit_id": "brand_kit_insight_health", "version": 4, "name": "Insight Health"},
    )
    assert compiled.status_code == 200, compiled.text
    sections = {
        "brief": {"schema_version": 1, "characterization": {"words": ["calm", "clinical"], "support": "s", "confidence": "low"}},
        "grammar_audit": {"schema_version": 1},
        "measured_components": {"schema_version": 1, "source": "website:https://example.test/", "styles": [],
                                "motion": {"animations": [], "reveals": [], "scripted": []}},
    }
    original = HybridRepository.require_brand_kit

    def stored_with_sections(self, brand_kit_id, version=None):
        record = original(self, brand_kit_id, version)
        return {**record, "brand_kit": {**record["brand_kit"], **sections}} if version is None else record

    monkeypatch.setattr(HybridRepository, "require_brand_kit", stored_with_sections)
    uploaded = upload_logo(client, label="The real lockup")
    chosen = client.post(
        "/brand-kits/brand_kit_insight_health/logo",
        json={"asset_id": uploaded.json()["asset"]["id"], "slot": "primary"},
    )
    assert chosen.status_code == 200, chosen.text
    monkeypatch.setattr(HybridRepository, "require_brand_kit", original)
    kit_json = client.get("/brand-kits/brand_kit_insight_health").json()["brand_kit_json"]
    for key, value in sections.items():
        assert kit_json[key] == value, key


def test_ops_attached_brand_kit_preflights_via_scene_ref_and_heals_the_row(
    client: TestClient,
) -> None:
    """K0.5: the editor's Brandkit chip attaches via an update_document patch
    (scene.meta.brand_kit only — the document row's brand_kit_json stays
    null). choose_effective_brand must fall back to the scene ref so
    preflight/export resolve the attached kit instead of the platform default
    (which hard-errors LUMB0101 against the scene ref), and a successful
    preflight persists the kit onto the row (source scene_ref)."""
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text

    document = create_document(client, preflightable_scene())

    attach_via_ops = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [
                {
                    "kind": "update_document",
                    "patch": {
                        "title": {"kind": "unchanged"},
                        "artifact_type": {"kind": "unchanged"},
                        "medium": {"kind": "unchanged"},
                        "brand_kit": {
                            "kind": "set",
                            "value": {"id": "brand_kit_insight_health", "version": 4},
                        },
                    },
                }
            ],
            "actor": {"kind": "human"},
            "source": "editor",
        },
    )
    assert attach_via_ops.status_code == 200, attach_via_ops.text

    preflight = client.post(f"/documents/{document['id']}/preflight", json={})
    assert preflight.status_code == 200, preflight.text
    payload = preflight.json()
    assert payload["brand_kit"]["source"] == "scene_ref"
    assert payload["brand_kit"]["id"] == "brand_kit_insight_health"
    diagnostic_views = payload.get("diagnostics", {})
    codes = {
        diag.get("code")
        for view in diagnostic_views.values()
        for diag in view
        if isinstance(diag, dict)
    }
    assert "LUMB0101" not in codes

    # The row heals: subsequent resolution takes the fast "document" branch.
    detail = client.get(f"/documents/{document['id']}").json()
    assert detail["effective_brand_kit_id"] == "brand_kit_insight_health"
    assert detail["effective_brand_kit_source"] == "scene_ref"


def test_preflight_preview_freeze_layout_bakes_resolved_scene(
    client: TestClient,
) -> None:
    """K1.6(b): freeze_layout=true returns a `bake` block whose scene is
    token-RESOLVED, server-relaid-out, and container-frozen — with raw
    resolution + freeze operations (and freeze inverses) for the editor's
    accept envelope. The frozen text child keeps its hug height (K1 rider)."""
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": "brand_kit_insight_health",
            "version": 4,
            "name": "Insight Health",
        },
    )
    assert compiled.status_code == 200, compiled.text

    # Author the production shape through the real compiler: a Stack (al)
    # container whose text children carry style TOKENS + skeleton literals
    # (Inter 16) — exactly what agent proposal ops replay into the editor.
    core = client.app.state.core
    compiled_scene = core.compile_dsl_into_scene(
        core.new_scene("doc_bake", "Bake preview"),
        "\n".join(
            [
                "page page_bake size(1080,1080,px)",
                "  hero al p(96,96) s(888,hug)",
                '    headline text "Your health, now online." s(888,hug) style($type.headline)',
                '    subtitle text "Short supporting line." s(820,hug) style($type.body)',
            ]
        ),
        None,
    )["scene"]
    compiled_scene["meta"]["brand_kit"] = {
        "id": "brand_kit_insight_health",
        "version": 4,
    }
    assert compiled_scene["nodes"]["headline"]["kind"]["font_size"] == 16.0

    response = client.post(
        "/preflight-preview",
        json={"scene": compiled_scene, "freeze_layout": True},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["brand_kit"]["source"] == "scene_ref"

    bake = payload["bake"]
    baked_scene = bake["scene"]
    # Resolution happened before the bake: the headline's literals are the
    # kit's real typography, not the skeleton.
    headline = baked_scene["nodes"]["headline"]
    assert headline["kind"]["font_family"] == "Source Sans 3"
    assert headline["kind"]["font_size"] != 16.0
    # The container froze (Stack -> Free) with real ops + inverses; the text
    # child keeps its hug height through the bake (K1 rider).
    assert baked_scene["nodes"]["hero"]["layout"]["layout_mode"] == "free"
    assert len(bake["freeze_operations"]) > 0
    assert len(bake["freeze_inverse_operations"]) > 0
    assert len(bake["resolution_operations"]) > 0
    assert headline["size"]["height"] == {"kind": "hug"}
    # No scene-ref mismatch anywhere in the pipeline.
    codes = {
        diag.get("code")
        for view in payload.get("diagnostics", {}).values()
        for diag in view
        if isinstance(diag, dict)
    }
    assert "LUMB0101" not in codes


def test_editor_target_node_ids_prefers_plural_and_dedupes() -> None:
    from lumen_api.main import editor_target_node_ids
    from lumen_api.models import AgentTurnPreviewRequest

    scene = {"meta": {}, "pages": {}, "nodes": {}}
    both = AgentTurnPreviewRequest(
        prompt="x",
        scene=scene,
        target_node_ids=["node_a", "node_a", "node_b"],
    )
    # Order preserved, deduped.
    assert editor_target_node_ids(both) == ["node_a", "node_b"]

    neither = AgentTurnPreviewRequest(prompt="x", scene=scene)
    assert editor_target_node_ids(neither) == []


def test_editor_prompt_scopes_to_targets_with_compensating_contract() -> None:
    from lumen_api.main import editor_agent_prompt
    from lumen_api.models import AgentTurnPreviewRequest

    payload = AgentTurnPreviewRequest(
        prompt="Make the headline bigger",
        scene=minimal_scene(),
        target_node_ids=["node_contact_name"],
    )
    prompt = editor_agent_prompt(payload)
    # The chipped target is named in the context and the instruction scopes to
    # it (untouched nodes byte-identical) with the §1.6 compensating contract.
    assert '"target_node_ids"' in prompt
    assert "node_contact_name" in prompt
    assert "byte-identical" in prompt
    assert "re-fit and verify" in prompt
    assert "what you preserved" in prompt


def test_editor_prompt_without_targets_uses_soft_targeting() -> None:
    from lumen_api.main import editor_agent_prompt
    from lumen_api.models import AgentTurnPreviewRequest

    prompt = editor_agent_prompt(
        AgentTurnPreviewRequest(prompt="Fix overflow", scene=minimal_scene())
    )
    # No chips: no hard byte-identical scoping, but the compensating contract
    # still applies to every turn.
    assert "byte-identical" not in prompt
    assert "Prefer targeted repairs" in prompt
    assert "what you preserved" in prompt


def test_agent_instructions_round_trip_and_prompt_injection(client: TestClient) -> None:
    from lumen_api.main import editor_agent_prompt
    from lumen_api.models import AgentTurnPreviewRequest

    document = create_document(client)
    document_id = document["id"]

    # Set → returned by GET (survives reload); blank → cleared.
    response = client.put(
        f"/documents/{document_id}/agent-instructions",
        json={"instructions": "Always use the serif brand voice."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["agent_instructions"] == "Always use the serif brand voice."
    assert (
        client.get(f"/documents/{document_id}").json()["agent_instructions"]
        == "Always use the serif brand voice."
    )
    cleared = client.put(
        f"/documents/{document_id}/agent-instructions", json={"instructions": "   "}
    )
    assert cleared.json()["agent_instructions"] is None

    # The editor sends the instructions with each turn; they land in the
    # context as standing instructions that never override the request.
    prompt = editor_agent_prompt(
        AgentTurnPreviewRequest(
            prompt="Make a poster",
            scene=minimal_scene(),
            agent_instructions="Always use the serif brand voice.",
        )
    )
    assert "standing_instructions" in prompt
    assert "Always use the serif brand voice." in prompt
    assert "current request wins" in prompt
    # Absent instructions → no standing block at all.
    bare = editor_agent_prompt(
        AgentTurnPreviewRequest(prompt="Make a poster", scene=minimal_scene())
    )
    assert "standing_instructions" not in bare


def test_layout_managed_editing_round_trip(client: TestClient) -> None:
    document = create_document(client)
    document_id = document["id"]

    # Default off: handoff-absolute freezing stays the shipped behavior.
    assert client.get(f"/documents/{document_id}").json()["layout_managed_editing"] is False

    enabled = client.put(
        f"/documents/{document_id}/layout-managed-editing", json={"enabled": True}
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["layout_managed_editing"] is True
    assert client.get(f"/documents/{document_id}").json()["layout_managed_editing"] is True

    # Disabling re-enables freezing at the next seam and survives reloads.
    disabled = client.put(
        f"/documents/{document_id}/layout-managed-editing", json={"enabled": False}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["layout_managed_editing"] is False
    assert client.get(f"/documents/{document_id}").json()["layout_managed_editing"] is False


def _fake_async_runner(status: str = "proposed"):
    def runner(payload, root):
        return {
            "schema_version": 1,
            "status": status,
            "summary": "Agent proposed a document title update.",
            "run_id": "run_internal_trace",
            "trace_dir": ".lumen-runs/run_internal_trace",
            "preview_paths": [],
            "dsl_blocks": ["# doc title"],
            "operations": [title_operation("Async Title")],
            "diagnostics": [],
            "artifacts": [],
        }

    return runner


def _wait_for_run_terminal(client: TestClient, run_id: str) -> dict:
    # D5 Round B: a run is now born `queued` and only becomes `running` once a fleet worker
    # claims it, so "not running" is no longer the same thing as "terminal". Wait for a genuinely
    # terminal status instead of the absence of one non-terminal status.
    import time as _time

    for _ in range(400):
        snapshot = client.get(f"/agent/runs/{run_id}").json()
        if snapshot["status"] in ("succeeded", "failed"):
            return snapshot
        _time.sleep(0.02)
    raise AssertionError(f"run {run_id} never reached a terminal status")


def test_agent_turns_async_persists_result_and_terminal_event(
    client: TestClient,
) -> None:
    client.app.state.agent_turn_runner = _fake_async_runner("proposed")

    start = client.post(
        "/agent/turns",
        json={
            "prompt": "Repair the headline",
            "scene": minimal_scene(),
            "document_id": "doc_async_route",
            "active_page_id": "page_a4",
            "diagnostics": [],
        },
    )
    assert start.status_code == 200, start.text
    started = start.json()
    # D5 Round B: the route OFFERS the turn to the fleet and returns; `queued` is the honest
    # status of a run no worker has claimed yet. The editor reads only `run_id` from this body.
    assert started["status"] == "queued"
    run_id = started["run_id"]
    assert run_id.startswith("run_")

    snapshot = _wait_for_run_terminal(client, run_id)
    assert snapshot["status"] == "succeeded"
    assert snapshot["result"]["operations"][0]["kind"] == "update_document"
    # The worker appends exactly one terminal marker event.
    assert [event["type"] for event in snapshot["events"]] == ["result"]


def test_agent_turns_async_marks_failed_status(client: TestClient) -> None:
    client.app.state.agent_turn_runner = _fake_async_runner("failed")
    start = client.post(
        "/agent/turns",
        json={"prompt": "x", "scene": minimal_scene(), "diagnostics": []},
    )
    run_id = start.json()["run_id"]
    snapshot = _wait_for_run_terminal(client, run_id)
    assert snapshot["status"] == "failed"


def test_agent_run_snapshot_404_for_unknown_run(client: TestClient) -> None:
    assert client.get("/agent/runs/run_missing").status_code == 404


def test_a_restart_leaves_an_unclaimed_run_recoverable(tmp_path: Path) -> None:
    # D5 Round B replaces the startup orphan sweep with lease recovery, and this test replaces
    # `test_startup_sweep_fails_runs_orphaned_by_a_restart` with the INVERSE contract.
    #
    # The sweep existed because turns ran on daemon threads inside the API process: a restart
    # killed them silently, so every leftover `running` row was an orphan by construction and
    # failing it at boot was the only way the editor's stream could settle. Turns are leased
    # fleet work now. A run that a dead worker was driving is NOT lost — its lease expires and a
    # takeover worker re-claims it through the D5 CAS — so a boot-time sweep would destroy
    # recoverable work. It is gone, and the assertion is that a restart changes nothing.
    cache_root = tmp_path / "engine-cache"
    first = make_client(create_app(cache_root))

    queued_run = unique_run_id("queued")
    finished_run = unique_run_id("finished")

    repo = HybridRepository()
    repo.create_run(queued_run, None)
    repo.create_run(finished_run, None)
    repo.complete_run(
        finished_run, "succeeded", {"status": "applied"}, "result", {"status": "applied"}
    )
    del first

    # "Restart": a new app over the same database. Nothing is swept.
    restarted = make_client(create_app(cache_root))

    queued = restarted.get(f"/agent/runs/{queued_run}").json()
    assert queued["status"] == "queued"
    assert queued["result"] is None
    assert queued["events"] == []

    finished = restarted.get(f"/agent/runs/{finished_run}").json()
    assert finished["status"] == "succeeded"
    assert finished["result"] == {"status": "applied"}


def _open_stream(client: TestClient, run_id: str, **kwargs) -> str:
    """Open the run's SSE stream the way a client must since D7: mint a token, then present it.

    The mint is header-authenticated (the ``client`` fixture sends ``X-Workspace-Id``); the GET
    carries no workspace at all. That handshake IS the auth change, so every stream test goes
    through it rather than reaching past it."""
    token = client.post(f"/agent/runs/{run_id}/stream-token").json()["stream_token"]
    return client.get(f"/agent/runs/{run_id}/events?stream_token={token}", **kwargs).text


def test_agent_run_events_stream_replays_then_done(client: TestClient) -> None:
    # Drive the store directly to assert SSE framing deterministically (no
    # dependence on background-thread timing): a progress event replays, then
    # the terminal event closes the stream with the run's result.

    run_id = unique_run_id("sse")
    repo = HybridRepository()
    repo.create_run(run_id, None)
    seq = repo.emit_run_event(run_id, "dsl_block_produced", {"iteration": 1})
    repo.complete_run(
        run_id,
        "succeeded",
        {"status": "proposed", "summary": "done"},
        "result",
        {"status": "proposed"},
    )

    body = _open_stream(client, run_id)
    assert "event: progress" in body
    assert "dsl_block_produced" in body
    assert "event: done" in body
    assert '"summary":"done"' in body or '"summary": "done"' in body
    # Last-Event-ID replay: subscribing after the progress event's seq skips it. The seq is the
    # platform outbox's global sequence now, so the cursor comes from the write, not from "1".
    resumed = _open_stream(client, run_id, headers={"Last-Event-ID": str(seq)})
    assert "event: progress" not in resumed
    assert "event: done" in resumed
    # A fresh connect with no cursor replays the whole run from the beginning.
    assert "event: progress" in _open_stream(client, run_id)


def test_the_stream_token_is_single_use_and_carries_the_workspace(client: TestClient) -> None:
    """R-D7-B4: one token, one connect, and no ``?workspace_id=`` anywhere.

    The four refusals — replayed token, unknown token, malformed token, and a token minted for a
    DIFFERENT run — are one indistinguishable 401, so the refusal cannot be used to probe which
    runs exist.
    """
    run_id = unique_run_id("tok")
    other_run = unique_run_id("tok2")
    repo = HybridRepository()
    repo.create_run(run_id, None)
    repo.create_run(other_run, None)
    repo.complete_run(run_id, "succeeded", {"status": "proposed"}, "result", {})

    token = client.post(f"/agent/runs/{run_id}/stream-token").json()["stream_token"]
    first = client.get(f"/agent/runs/{run_id}/events?stream_token={token}")
    assert first.status_code == 200 and "event: done" in first.text
    # Replaying the same token is refused: consumption stamps used_at atomically.
    assert client.get(f"/agent/runs/{run_id}/events?stream_token={token}").status_code == 401
    assert (
        client.get(f"/agent/runs/{run_id}/events?stream_token={uuid4()}").status_code == 401
    )
    assert client.get(f"/agent/runs/{run_id}/events?stream_token=not-a-uuid").status_code == 401
    # A token minted for another run does not open this one.
    foreign = client.post(f"/agent/runs/{other_run}/stream-token").json()["stream_token"]
    assert client.get(f"/agent/runs/{run_id}/events?stream_token={foreign}").status_code == 401
    # And the stream refuses to be opened without a token at all.
    assert client.get(f"/agent/runs/{run_id}/events").status_code == 422


def test_the_done_frame_is_built_from_the_terminal_event_not_the_run_row(
    client: TestClient,
) -> None:
    """R-D7-B2, proved by removal: blank the run row's stored result and the stream still serves it.

    The pre-D7 stream read ``run["result"]`` the moment it saw a terminal marker — a second read,
    in a second transaction, of a row the marker only *implied* was ready. D7 puts the whole result
    envelope inside the terminal event, so the serve layer never looks at the run row again. If
    that were still a lie, this test would stream ``null``.
    """
    import asyncio

    from clue_db import create_engine
    from sqlalchemy import text

    run_id = unique_run_id("selfcontained")
    repo = HybridRepository()
    repo.create_run(run_id, None)
    repo.complete_run(
        run_id, "succeeded", {"status": "proposed", "summary": "from the event"}, "result", {}
    )

    async def blank_the_row() -> None:
        engine = create_engine()
        try:
            async with engine.connect() as conn, conn.begin():
                await conn.execute(
                    text("UPDATE design_agent_run SET result_json = NULL WHERE run_id = :r"),
                    {"r": run_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(blank_the_row())

    body = _open_stream(client, run_id)
    assert "event: done" in body
    assert "from the event" in body


def test_minting_a_token_for_an_unknown_run_is_a_404(client: TestClient) -> None:
    assert client.post("/agent/runs/run_never_created/stream-token").status_code == 404


def test_run_event_enriched_with_operations_round_trips_and_streams(
    client: TestClient,
) -> None:
    # Live-design-streaming S0 (D1/D2): the sink stores whatever dict it is
    # handed untouched, so an authoring event enriched with its applied
    # `operations` list round-trips through the durable row AND rides the SSE
    # progress frame the editor consumes. D7 swapped the row's table; the
    # payload envelope (`{event_type, data}`) is unwrapped on the way out, so
    # this contract is byte-identical.

    run_id = unique_run_id("ops")
    repo = HybridRepository()
    repo.create_run(run_id, None)
    enriched = {
        "actor": "dsl-author",
        "iteration": 1,
        "input_summary": "page Hero",
        "output_summary": "2 operations; 0 DSL diagnostics",
        "diagnostic_count": 0,
        "operations": [
            {"kind": "add_page", "page_id": "page_hero"},
            {"kind": "insert_node", "node_id": "headline", "parent_id": "page_hero"},
        ],
    }
    repo.emit_run_event(run_id, "dsl_compiled", enriched)

    # (e-i) the durable row round-trips the enriched dict verbatim.
    rows = repo.list_run_events(run_id)
    assert rows[-1]["data"] == enriched
    repo.complete_run(
        run_id, "succeeded", {"status": "proposed"}, "result", {"status": "proposed"}
    )

    # (e-ii) the SSE progress frame carries the operations to the client.
    body = _open_stream(client, run_id)
    assert "event: progress" in body
    assert "dsl_compiled" in body
    assert "add_page" in body and "page_hero" in body
    assert "insert_node" in body


def test_run_events_sse_cadence_constants_pinned() -> None:
    # D2: poll fast (250ms) so authoring batches land promptly; keepalive slow
    # (~1s) so a quiet run does not spam a comment every poll. D7 moved these
    # next to the loop they pace (``run_stream``) and made the override of the
    # platform's 1.0s default explicit; the values are unchanged, because the
    # editor's reveal pacing depends on them.
    from lumen_api import main as api_main
    from lumen_api import run_stream

    assert run_stream.POLL_INTERVAL_SECONDS == 0.25
    assert run_stream.KEEPALIVE_INTERVAL_SECONDS == 1.0
    # The polled stream's machinery left main.py with them: one seam, one home.
    assert not hasattr(api_main, "sse_frame")
    assert not hasattr(api_main, "_RUN_EVENTS_SSE_POLL_INTERVAL_SECONDS")


def write_iteration_compile(trace_dir, index: int, operations: list) -> None:
    iteration_dir = trace_dir / "iterations" / f"{index:03d}"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    (iteration_dir / "dsl.lumen").write_text(f"# block {index}", encoding="utf-8")
    (iteration_dir / "compile.json").write_text(
        json.dumps(
            {
                "compile": {"status": "ok", "diagnostics": []},
                "operations": operations,
            }
        ),
        encoding="utf-8",
    )


def test_agent_response_prefers_operations_ledger_over_compile_scrape(tmp_path) -> None:
    """K2 accept-seam: the ledger is the proposal-op source of truth — it
    carries asset-tool mutations the compile scrape can never see, honors the
    keep-best iteration window, and the scrape remains only as the fallback
    for pre-ledger traces."""
    from lumen_api.main import agent_response_from_trace

    write_iteration_compile(
        tmp_path, 1, [{"kind": "update_node", "node_id": "stale_scrape_op"}]
    )
    ledger = {
        "entries": [
            {"iteration": 1, "source": "compile_dsl_block",
             "operation": {"kind": "insert_node", "node": {"id": "mark"}}},
            {"iteration": 1, "source": "use_brand_asset",
             "operation": {"kind": "upsert_asset", "asset": {"id": "asset_logo"}}},
            {"iteration": 2, "source": "compile_dsl_block",
             "operation": {"kind": "update_node", "node_id": "beyond_window"}},
        ]
    }
    (tmp_path / "operations_ledger.json").write_text(json.dumps(ledger))
    result = {
        "status": "accepted",
        "stop_reason": "accepted",
        "run_id": "run_ledger",
        "summary": "ok",
        "preview_paths": [],
        "ops_valid_through_iteration": 1,
    }

    response = agent_response_from_trace(result, tmp_path)

    assert response["operations"] == [
        {"kind": "insert_node", "node": {"id": "mark"}},
        {"kind": "upsert_asset", "asset": {"id": "asset_logo"}},
    ]


def test_agent_response_edit_applied_maps_to_proposed_with_advisory_diagnostics(
    tmp_path,
) -> None:
    # Phase 0b: an edit-scoped acceptance proposes its ops; the whole-design
    # critique rides along as ADVISORY warning diagnostics, never errors.
    from lumen_api.main import agent_response_from_trace

    write_iteration_compile(
        tmp_path, 1, [{"kind": "update_node", "node_id": "headline"}]
    )
    result = {
        "status": "edit_applied",
        "stop_reason": "edit_scoped_acceptance",
        "run_id": "run_edit_scoped",
        "summary": "Requested edit applied and verified.",
        "draft_verification": {
            "scene_stamp": "current-scene",
            "preflight": {"status": "current", "scene_stamp": "current-scene", "iteration": 1,
                          "has_blocking_errors": False, "diagnostics": []},
            "preview": {"status": "current", "scene_stamp": "current-scene", "iteration": 1},
            "review": {"status": "current", "scene_stamp": "current-scene", "iteration": 1},
        },
        "preview_paths": [],
        "ops_valid_through_iteration": 1,
        "critique": {
            "accepted": False,
            "summary": "pre-existing issues",
            "issues": [
                {
                    "severity": "blocker",
                    "category": "imagery",
                    "message": "hero image is a placeholder gradient",
                    "suggested_repair": "regenerate the hero",
                    "target": {"page_id": "hero_poster", "node_id": "hero"},
                }
            ],
        },
    }

    response = agent_response_from_trace(result, tmp_path)

    assert response["status"] == "proposed"
    assert response["acceptance_scope"] == "edit"
    assert response["operations"] == [{"kind": "update_node", "node_id": "headline"}]
    advisory = [
        diag
        for diag in response["diagnostics"]
        if diag["code"] == "agent_runtime.visual_critique_advisory"
    ]
    assert len(advisory) == 1
    assert advisory[0]["severity"] == "warning"  # advisory even for critique blockers
    assert advisory[0]["subject"] == {"kind": "node", "id": "hero"}
    assert advisory[0]["hint"] == "regenerate the hero"


def test_agent_response_clarification_requested_round_trips(tmp_path) -> None:
    # Brief clarification (honest turn outcome #3): the harness's
    # clarification_requested envelope maps to an editor response that carries
    # the questions and proposes NO operations — the turn asked, it did not
    # author. Mirrors how run_deepagent_turn returns final.json verbatim.
    from lumen_api.main import agent_response_from_trace

    # An operations ledger from an earlier design is irrelevant to a
    # clarification turn — the branch fires before any op scrape.
    write_iteration_compile(
        tmp_path, 1, [{"kind": "update_node", "node_id": "headline"}]
    )
    result = {
        "run_id": "run_clarify",
        "status": "clarification_requested",
        "stop_reason": "clarification_requested",
        "outcome": "clarification_requested",
        "summary": "Before I design this, a couple of quick decisions...",
        "clarification": {
            "questions": [
                {
                    "id": "format",
                    "question": "What surface is this for?",
                    "why_it_matters": "It fixes the canvas size.",
                    "options": ["Instagram square", "LinkedIn landscape"],
                    "default": "an Instagram square (1080x1080)",
                    "allow_freeform": True,
                }
            ]
        },
    }

    response = agent_response_from_trace(result, tmp_path)

    assert response["status"] == "clarification_requested"
    assert response["stop_reason"] == "clarification_requested"
    assert response["run_id"] == "run_clarify"
    # The questions ride through intact.
    questions = response["clarification"]["questions"]
    assert len(questions) == 1
    assert questions[0]["id"] == "format"
    assert questions[0]["default"] == "an Instagram square (1080x1080)"
    # Nothing to apply — asking is not authoring.
    assert response["operations"] == []
    assert response["artifacts"] == []
    assert response["draft_scene"] is None


def test_agent_turn_preview_request_accepts_previous_turn_outcome() -> None:
    # The one-round-per-turn signal the editor echoes back rides on the request
    # model (None by default; set to "clarification_requested" on the reply turn).
    from lumen_api.models import AgentTurnPreviewRequest

    default = AgentTurnPreviewRequest(prompt="x", scene={})
    assert default.previous_turn_outcome is None
    echoed = AgentTurnPreviewRequest(
        prompt="Instagram square, lead with the benefit",
        scene={},
        previous_turn_outcome="clarification_requested",
    )
    assert echoed.previous_turn_outcome == "clarification_requested"


def test_agent_response_completed_with_warnings_maps_to_proposed(tmp_path) -> None:
    # Agent-quality: a run that exhausts its repair budget holding a
    # preflight-clean best draft can finalize as `completed_with_warnings`. That
    # draft must reach the editor as a reviewable PROPOSAL (Accept/Reject),
    # not "failed" — with the unresolved critique as advisory warnings. The
    # critique arrives wrapped in the loop's last feedback envelope.
    from lumen_api.main import agent_response_from_trace

    write_iteration_compile(
        tmp_path, 1, [{"kind": "update_node", "node_id": "cta_text"}]
    )
    result = {
        "status": "completed_with_warnings",
        "stop_reason": "max_iterations_reached",
        "run_id": "run_best_draft",
        "summary": "Repair budget reached. Returned the best preflight-clean draft.",
        "draft_verification": {
            "scene_stamp": "current-scene",
            "preflight": {"status": "current", "scene_stamp": "current-scene", "iteration": 1,
                          "has_blocking_errors": False, "diagnostics": []},
            "preview": {"status": "current", "scene_stamp": "current-scene", "iteration": 1},
            "review": {"status": "current", "scene_stamp": "current-scene", "iteration": 1},
        },
        "preview_paths": [],
        "ops_valid_through_iteration": 1,
        "critique": {
            "kind": "visual",
            "feedback": {
                "accepted": False,
                "summary": "composition still off-center",
                "issues": [
                    {
                        "severity": "major",
                        "category": "visual_balance",
                        "message": "composition sits low on the canvas",
                        "suggested_repair": "re-center the main group",
                        "target": {"node_id": "artboard"},
                    }
                ],
            },
        },
    }

    response = agent_response_from_trace(result, tmp_path)

    assert response["status"] == "proposed"
    assert response["acceptance_scope"] is None
    assert response["operations"] == [{"kind": "update_node", "node_id": "cta_text"}]
    advisory = [
        diag
        for diag in response["diagnostics"]
        if diag["code"] == "agent_runtime.visual_critique_advisory"
    ]
    assert len(advisory) == 1
    assert advisory[0]["severity"] == "warning"
    assert advisory[0]["subject"] == {"kind": "node", "id": "artboard"}

    # A best draft whose last feedback was compile/preflight-shaped (no
    # critique issues) still proposes — just without advisories.
    result_no_visual = dict(result, critique={"kind": "compile", "feedback": {}})
    response2 = agent_response_from_trace(result_no_visual, tmp_path)
    assert response2["status"] == "proposed"
    assert [
        d
        for d in response2["diagnostics"]
        if d["code"] == "agent_runtime.visual_critique_advisory"
    ] == []

    # Without any applied operations there is nothing to propose: still failed.
    result_no_ops = dict(result, ops_valid_through_iteration=0)
    response3 = agent_response_from_trace(result_no_ops, tmp_path)
    assert response3["status"] == "failed"


def test_agent_response_ops_window_excludes_iterations_after_best(tmp_path) -> None:
    # Phase 0b: when the loop returns an EARLIER iteration's scene as the best
    # draft, ops from later iterations are not part of it and must not replay.
    from lumen_api.main import agent_response_from_trace

    write_iteration_compile(tmp_path, 1, [{"kind": "update_node", "node_id": "headline"}])
    write_iteration_compile(tmp_path, 2, [{"kind": "update_node", "node_id": "kicker"}])
    result = {
        "status": "edit_applied",
        "stop_reason": "max_iterations_reached",
        "run_id": "run_window",
        "summary": "Budget reached; best draft returned.",
        "preview_paths": [],
        "ops_valid_through_iteration": 1,
        "critique": {},
    }

    response = agent_response_from_trace(result, tmp_path)

    assert response["status"] == "proposed"
    assert response["operations"] == [{"kind": "update_node", "node_id": "headline"}]
    # Later blocks still appear as informational DSL history.
    assert len(response["dsl_blocks"]) == 2


def test_agent_seed_scene_accepts_scene_shape_and_rejects_junk() -> None:
    # Phase 0a: only a structurally plausible scene document seeds the agent's
    # working scene; anything else falls back to a fresh scene (None).
    from lumen_api.main import agent_seed_scene
    from lumen_api.models import AgentTurnPreviewRequest

    seeded = AgentTurnPreviewRequest(prompt="edit", scene=minimal_scene())
    assert agent_seed_scene(seeded) == seeded.scene

    junk = AgentTurnPreviewRequest(prompt="edit", scene={"foo": "bar"})
    assert agent_seed_scene(junk) is None

    empty = AgentTurnPreviewRequest(prompt="edit", scene={})
    assert agent_seed_scene(empty) is None

    # An empty DOCUMENT (valid scene, zero pages/nodes) runs unseeded: nothing
    # to preserve, and continuation mode would fight a blank scaffold.
    empty_doc = AgentTurnPreviewRequest(
        prompt="design something",
        scene={
            "schema_version": 1,
            "meta": {"id": "doc_untitled", "title": "Untitled design"},
            "pages": {},
            "nodes": {},
            "slots": {},
            "assets": {},
            "export_profiles": [],
        },
    )
    assert agent_seed_scene(empty_doc) is None


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


def test_structured_request_logging_adds_request_id_header(client: TestClient) -> None:
    # request_id is bound ONCE into the obs contextvar by the middleware; the
    # merge_contextvars processor then stamps it on http_request_completed —
    # proving the contextvar (not a per-call kwarg) supplies it.
    with capture_events(mode="info") as cap:
        response = client.get(
            "/documents/missing_document",
            headers={"x-request-id": "req_test_observability"},
        )

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req_test_observability"
    completed = cap.first("http_request_completed")
    assert completed is not None
    assert completed["request_id"] == "req_test_observability"
    assert completed["method"] == "GET"
    assert completed["route"] == "/documents/{document_id}"
    assert completed["status_code"] == 404
    assert completed["duration_ms"] >= 0


def test_http_request_completed_event_shape_is_preserved(client: TestClient) -> None:
    # The canonical event name + field set must survive the migration onto the
    # shared obs pipeline unchanged.
    with capture_events(mode="info") as cap:
        client.get("/documents/missing_document", headers={"x-request-id": "req_shape"})

    completed = cap.first("http_request_completed")
    assert completed is not None
    assert completed["event"] == "http_request_completed"
    assert completed["level"] == "info"
    for key in (
        "request_id",
        "method",
        "path",
        "route",
        "status_code",
        "duration_ms",
        "client_host",
    ):
        assert key in completed, f"missing preserved field: {key}"


def test_request_id_from_contextvar_stamps_events() -> None:
    # Bind directly (no request) and confirm any obs logger's event carries it.
    with capture_events(mode="info") as cap:
        bind_request_id("req_ctx_direct")
        try:
            get_logger("lumen_api.api").info("probe_event", widget="x")
        finally:
            unbind_context("request_id")

    probe = cap.first("probe_event")
    assert probe is not None
    assert probe["request_id"] == "req_ctx_direct"
    assert probe["widget"] == "x"


def test_startup_configures_logging_once(tmp_path: Path) -> None:
    root = logging.getLogger()

    create_app(tmp_path / "once_a")
    owned = [h for h in root.handlers if getattr(h, "_lumen_obs_handler", False)]
    assert len(owned) == 1

    # A second app build must NOT stack another root handler — configure is
    # idempotent (it removes its own owned handlers first).
    create_app(tmp_path / "once_b")
    owned_again = [h for h in root.handlers if getattr(h, "_lumen_obs_handler", False)]
    assert len(owned_again) == 1


def test_core_helper_logging_records_runtime_summary(client: TestClient) -> None:
    with capture_events(mode="info") as cap:
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
    started = cap.first("core_helper_started")
    completed = cap.first("core_helper_completed")
    assert started is not None and completed is not None
    # request_id flows into the core-helper path via the same contextvar.
    assert started["request_id"] == "req_helper_observability"
    assert started["action"] == "export_preview"
    assert started["page_id_count"] == 1
    assert completed["ok"] is True
    assert completed["action"] == "export_preview"
    assert completed["diagnostic_count"] >= 0


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


def advisory_only_scene(document_id: str) -> dict:
    """A scene whose ONLY error-severity diagnostic is the LUMV0820 policy
    lint: an image-like slot carrying no image policy.

    This is the exact shape that bricked the 2026-08-24 baseline run — a scene
    that rendered previews perfectly for 43 minutes and then had every export
    refused on a lint.
    """
    scene = preflightable_scene()
    scene["meta"]["id"] = document_id
    template = scene["slots"]["slot_contact_name"]
    scene["slots"]["slot_account_logo"] = {
        **json.loads(json.dumps(template)),
        "id": "slot_account_logo",
        "key": "account.logo",
        "label": "Account logo",
        "content_type": "logo",
        # The defect under test. Left unbound so the scene trips LUMV0820 and
        # nothing else — an image-like slot bound to a TEXT node would also
        # raise LUMA0300, which is a genuine blocker and would muddy the case.
        "image_policy": None,
        "bound_nodes": [],
        "required": False,
        "placeholder": None,
        "binding_hints": [],
    }
    return scene


def test_document_export_route_exports_with_warnings_on_advisory_diagnostics(
    client: TestClient,
) -> None:
    """P0.3: an advisory-only scene EXPORTS, and the advisories ride the
    response for the editor's export menu (ruling R5)."""
    document = create_document(client, advisory_only_scene("doc_export_advisory"))

    response = client.post(
        f"/documents/{document['id']}/export",
        json={"format": "svg", "page_ids": ["page_a4"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    # The scene really does carry an error-severity diagnostic...
    assert payload["preflight"]["has_errors"] is True
    assert any(
        diagnostic["code"] == "LUMV0820"
        for diagnostic in payload["diagnostics"]["current"]
    )

    # ...and the export succeeded anyway, with real bytes.
    assert payload["status"] == "ok"
    artifacts = payload["export"]["artifacts"]
    assert artifacts, "an advisory-only scene must still produce artifacts"
    assert artifacts[0]["format"] == "svg"

    # The advisory is surfaced, not swallowed.
    warnings = payload["warnings"]
    assert [warning["code"] for warning in warnings] == ["LUMV0820"]
    assert warnings[0]["severity"] == "advisory"
    assert warnings[0]["engine_severity"] == "error"
    assert "image policy" in warnings[0]["message"]
    assert payload["preflight"]["advisory_warnings"] == 1


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
    # P0.3: the severity split must not have turned a real blocker advisory.
    # An unresolved token paint is render-impossible, so it still refuses, and
    # nothing about it is reported as a mere warning.
    assert payload["warnings"] == []
    assert payload["preflight"]["advisory_warnings"] == 0

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
    # Print W2: the server PDF path renders vector by default through the
    # Skia PDF backend (declared by LUME0427; LUMEN_PDF_RENDERER=flattened
    # selects the W0 raster baseline, LUME0426). The early vector writer's
    # fidelity warnings no longer apply.
    assert "LUME0427" in diagnostic_codes
    assert "LUME0401" not in diagnostic_codes
    assert "LUME0402" not in diagnostic_codes
    assert "LUME0411" not in diagnostic_codes
    assert "LUME0412" not in diagnostic_codes

    # Print W6: the print-ready report must SURVIVE the API compaction —
    # compact_export_result once rebuilt the payload without it and the
    # editor's report block silently never rendered (browser-verify find).
    report = payload["export"]["print_ready"]
    assert report["ruleset"] == "print-ready-v1"
    assert report["status"] in {"pass", "warn", "fail"}
    assert any(rule["id"] == "edge_art_reaches_bleed" for rule in report["rules"])


def test_export_preview_route_honors_include_marks(client: TestClient) -> None:
    """Print W2r: include_marks must survive profile normalization — the
    MediaBox grows by the 14pt mark margin per side around the bleed."""
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

    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "pdf",
            "page_ids": ["page_a4"],
            "profile": {
                "name": "print_pdf_marks",
                "format": "pdf",
                "pdf_intent": "print",
                "raster": None,
                "include_bleed": True,
                "embed_fonts": True,
                "include_marks": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    artifact = payload["export"]["artifacts"][0]
    assert artifact["dimensions"] == {
        "width": 1144.0,
        "height": 1144.0,
        "unit": "pt",
        "source": "pdf_media_box",
    }


def test_export_preview_marks_on_bleedless_page_keep_exact_trim_geometry(
    client: TestClient,
) -> None:
    """The 2026-07-15 phantom-margin bug, pinned end-to-end: a print export
    with bleed+marks flags against a page WITHOUT a bleed rect must produce
    plain trim-size geometry — previously the box finalizer grew the
    MediaBox by the 14pt mark margin while the renderer painted a trim-size
    canvas, shipping a TrimBox that cut into the art."""
    scene = minimal_scene()
    scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1350,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }
    assert scene["pages"]["page_a4"].get("bleed") is None

    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "pdf",
            "page_ids": ["page_a4"],
            "profile": {
                "name": "print_pdf_marks_no_bleed",
                "format": "pdf",
                "pdf_intent": "print",
                "raster": None,
                "include_bleed": True,
                "embed_fonts": True,
                "include_marks": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload["diagnostics"]
    artifact = payload["export"]["artifacts"][0]
    # Exactly the trim size — no phantom 14pt margin.
    assert artifact["dimensions"] == {
        "width": 1080.0,
        "height": 1350.0,
        "unit": "pt",
        "source": "pdf_media_box",
    }
    # The gap stays loud: the missing-bleed warning rides the export.
    codes = {item["code"] for item in payload["export"]["diagnostics"]}
    assert "LUME0412" in codes


def test_normalize_export_profile_keeps_optional_print_controls() -> None:
    """Print W5: the profile whitelist rebuild must pass imposition/proof/
    color through — dropping them here silently downgraded saved document
    profiles (same defect class as the include_marks browser-verify find)."""
    from lumen_api.main import normalize_export_profile

    normalized = normalize_export_profile(
        {
            "name": "offset_press_pdf",
            "format": "pdf",
            "pdf_intent": "print",
            "include_bleed": True,
            "embed_fonts": True,
            "include_marks": True,
            "imposition": "booklet",
            "proof": True,
            "color": "cmyk",
        }
    )
    assert normalized["imposition"] == "booklet"
    assert normalized["proof"] is True
    assert normalized["color"] == "cmyk"

    plain = normalize_export_profile({"name": "digital_pdf", "format": "pdf"})
    assert "imposition" not in plain
    assert "proof" not in plain
    assert "color" not in plain


def cmyk_print_profile() -> JsonObject:
    return {
        "name": "print_pdf_cmyk",
        "format": "pdf",
        "pdf_intent": "print",
        "raster": None,
        "include_bleed": False,
        "embed_fonts": True,
        "include_marks": False,
        "color": "cmyk",
    }


@pytest.mark.skipif(shutil.which("gs") is None, reason="ghostscript not installed")
def test_export_preview_route_converts_print_pdf_to_cmyk(client: TestClient) -> None:
    """Print W5 stage B: color:"cmyk" on a print-intent profile converts the
    PDF through Ghostscript — the export declares the conversion (LUME0432)
    and the OutputIntent names the press profile, not sRGB."""
    scene = minimal_scene()
    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "pdf",
            "page_ids": ["page_a4"],
            "profile": cmyk_print_profile(),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload["diagnostics"]
    codes = {item["code"] for item in payload["export"]["diagnostics"]}
    assert "LUME0432" in codes
    assert payload["export"]["print_ready"] is not None

    artifact = payload["export"]["artifacts"][0]
    header, encoded = artifact["data_url"].split(",", 1)
    assert header == "data:application/pdf;base64"
    pdf_bytes = base64.b64decode(encoded)
    assert b"GTS_PDFX" in pdf_bytes
    assert b"sRGB IEC61966-2.1" not in pdf_bytes, "CMYK export must not claim an sRGB intent"


@pytest.mark.skipif(shutil.which("gs") is None, reason="ghostscript not installed")
def test_document_export_via_saved_cmyk_profile(client: TestClient) -> None:
    """The saved-profile blind spot: every other CMYK test uses an ad-hoc
    inline profile — the exact gap that let the normalize whitelist silently
    drop imposition/proof for weeks. This drives CMYK through a profile
    SAVED in the document (name-resolved), end to end."""
    scene = preflightable_scene()
    scene["export_profiles"] = [cmyk_print_profile()]
    document = create_document(client, scene)

    response = client.post(
        f"/documents/{document['id']}/export",
        json={"profile_name": "print_pdf_cmyk", "page_ids": ["page_a4"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload["diagnostics"]
    # The saved profile survived normalization with its color intact.
    assert payload["profile"]["color"] == "cmyk"

    artifact = payload["export"]["artifacts"][0]
    header, encoded = artifact["data_url"].split(",", 1)
    assert header == "data:application/pdf;base64"
    pdf_bytes = base64.b64decode(encoded)
    assert b"GTS_PDFX" in pdf_bytes
    assert b"sRGB IEC61966-2.1" not in pdf_bytes, (
        "CMYK export must not claim an sRGB intent"
    )


def test_export_preview_route_rejects_cmyk_on_digital_pdf(client: TestClient) -> None:
    """CMYK conversion is print-only: an electronic-distribution (preview
    intent) PDF requesting it fails loudly, never silently converts."""
    scene = minimal_scene()
    profile = cmyk_print_profile()
    profile["pdf_intent"] = "preview"
    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "pdf",
            "page_ids": ["page_a4"],
            "profile": profile,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    codes = {item["code"] for item in payload["diagnostics"]}
    assert "export.cmyk_requires_print_intent" in codes


def png_scale_profile(scale: float) -> JsonObject:
    return {
        "name": f"png_{scale}x",
        "format": "png",
        "pdf_intent": None,
        "raster": {"scale": scale, "dpi": 96},
        "include_bleed": False,
        "embed_fonts": False,
    }


def test_export_preview_route_scales_png_with_raster_scale(client: TestClient) -> None:
    """raster.scale must survive profile normalization end-to-end: the PNG's
    own IHDR dimensions scale by the profile multiplier (px pages get the
    figma-style 1x/2x/... semantics)."""
    scene = minimal_scene()
    scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1080,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }

    for scale, expected in ((1.0, 1080), (2.0, 2160)):
        response = client.post(
            "/export-preview",
            json={
                "scene": scene,
                "format": "png",
                "page_ids": ["page_a4"],
                "profile": png_scale_profile(scale),
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "ok", payload["diagnostics"]
        artifact = payload["export"]["artifacts"][0]
        assert artifact["dimensions"] == {
            "width": expected,
            "height": expected,
            "unit": "px",
            "source": "png_ihdr",
        }


def test_export_preview_route_fails_raster_over_budget(client: TestClient) -> None:
    """The engine raster budget (150 MP) fails loudly through the API: a
    runaway scale x dpi profile must never OOM the helper silently."""
    scene = minimal_scene()
    scene["pages"]["page_a4"]["size"] = {
        "width": 1080,
        "height": 1080,
        "unit": "px",
        "preset": "custom",
        "orientation": "portrait",
    }

    response = client.post(
        "/export-preview",
        json={
            "scene": scene,
            "format": "png",
            "page_ids": ["page_a4"],
            "profile": png_scale_profile(40.0),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
    assert "export.raster_budget_exceeded" in codes, codes


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


def test_asset_metadata_endpoint_is_gone(client: TestClient) -> None:
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
    assert response.status_code == 410, response.text
    assert response.json()["detail"]["code"] == "asset_metadata.gone"


def test_asset_scene_operations_persist_history_snapshot_and_template(
    client: TestClient,
) -> None:
    # O3: the legacy asset_metadata surface is retired (410) — PD contract
    # docs/specs/PD-part2-design-substrate.md §6; scene assets ride the scene itself.
    document = create_document(client)

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
    assert [diagnostic["code"] for diagnostic in payload["diagnostics"]["audit"]] == [
        "LUMV0805"
    ]
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


# D2.5B DELETED `test_backfill_wraps_pre_envelope_operation_rows` (skipped since D1): it drove
# `backfill_edit_envelopes` by hand-editing the SQLite `operation_log` / `edit_envelopes`
# tables. The function, the migrations, and those tables are all deleted.


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
    """This test's DURABLE design blobs (D4) — the ``{workspace}/design/{sha256}`` namespace.

    The API-local `asset-store/` tree is gone: bytes live in platform storage, which the
    conftest fixture roots at `tmp_path/default-storage` for every non-injecting app. Counting
    the physical blobs there is the same property these assertions always asserted — how many
    byte objects one logical asset costs, and whether the GC actually destroyed them.

    D6 Round C narrowed the glob to the ``design/`` segment. The same backend now also holds the
    governed toolbelt's canonical PARAMETER SNAPSHOTS (`{workspace}/{sha256}`, source_key
    `tool_parameters`), which are journal evidence, not asset bytes — counting them made a
    second upload look like it had cost two extra byte objects. The narrowing restores exactly
    the property the docstring describes; it does not weaken it."""
    store_root = tmp_path / "default-storage"
    if not store_root.exists():
        return []
    return [
        path
        for path in store_root.rglob("*")
        if path.is_file() and path.parent.name == "design"
    ]


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
    # D4/R-D4-4: the persisted record points at PLATFORM STORAGE — the workspace-scoped design
    # key, never a local path. That re-pointing is what survives a wiped engine cache.
    opaque_ref = record["media"]["location"]["opaque_ref"]
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    assert opaque_ref == f"{workspace_id}/design/{digest['value']}"
    assert record["media"]["location"]["provider"] == "clue-storage"
    assert payload["deduplicated"] is False

    assert make_blob_store(client.app).read(digest["value"]) == LOGO_PNG_PATH.read_bytes()

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
    monkeypatch.setattr(settings, "lumen_asset_max_bytes", 16)
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

    # W1.2: a vector's thumbnail is a REAL raster rendered from the sanitized
    # SVG, not the SVG bytes again. The old self-referential thumbnail was
    # decodable by nothing — every logo was invisible to `view`, the describe
    # stage, and the vision APIs, and the viewer failed on it outright.
    thumbnail = client.get(f"/assets/{record['id']}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/png")
    assert thumbnail.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert thumbnail.content != served.content
    thumb_block = record["media"]["thumbnail"]
    assert thumb_block["mime_type"] == "image/png"
    # 120x60 fits the 256 box, so the short side is lifted to the 512 floor.
    assert (thumb_block["pixel_width"], thumb_block["pixel_height"]) == (1024, 512)


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


class _SpendPostTransport:
    """Adapts a ``httpx.post``-shaped stub onto ``clue_spend``'s transport seam.

    Lane 3 slice 5 moved the image model's HTTP call behind the provider caller, so patching
    ``httpx.post`` no longer intercepts it. Rather than rewrite twenty stubs, this calls each one
    with the arguments it was written against — ``(url, json=…, headers=…, timeout=…)`` — and turns
    its response object back into an ``HttpResponse``.

    The metering key the seam adds (``usage: {"include": True}``) is stripped BEFORE the stub sees
    the body, and recorded on ``self.metering`` instead, so every "the request body is exactly
    this" assertion below keeps pinning what the IMAGE PROVIDER built. That the seam adds the key
    is pinned in its own suite (``test_spend_scope``), where it belongs.
    """

    def __init__(self, post) -> None:
        self._post = post
        self.metering: list = []

    def send(self, request):
        from clue_spend import HttpResponse

        body = json.loads(request.body) if request.body else None
        if isinstance(body, dict) and "usage" in body:
            self.metering.append(body.pop("usage"))
        response = self._post(
            request.url,
            json=body,
            headers=dict(request.headers),
            timeout=request.timeout_s,
        )
        status = int(response.status_code)
        content = getattr(response, "content", None)
        if content is not None:
            raw = content
        elif status >= 400 and getattr(response, "text", None):
            raw = response.text.encode("utf-8")
        else:
            raw = json.dumps(response.json()).encode("utf-8")
        return HttpResponse(
            status=status, headers=dict(getattr(response, "headers", {}) or {}), body=raw
        )


def _patch_image_post(monkeypatch: pytest.MonkeyPatch, post) -> _SpendPostTransport:
    """Point the process-wide UNSCOPED spend caller at ``post`` for the duration of one test.

    These tests call ``image_provider.generate``/``edit`` directly, outside any request or job, so
    there is no scope open — which is exactly what the unscoped fallback is for. ``monkeypatch``
    owns the restore; the warn flag is pre-set so a test's caplog is not polluted by the seam's
    one-time "no scope open" warning.
    """
    from lumen_api import spend

    transport = _SpendPostTransport(post)
    monkeypatch.setattr(
        spend, "_UNSCOPED", spend._new_scope(_spend_test_stamp(), transport), raising=False
    )
    monkeypatch.setattr(spend, "_UNSCOPED_WARNED", True, raising=False)
    return transport


def _tiny_png(width: int = 8, height: int = 8, rgba=(64, 120, 200, 255)) -> bytes:
    """A minimal but valid RGBA PNG the Rust asset probe can decode."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = (b"\x00" + bytes(rgba) * width) * height  # filter byte 0 + pixels per row
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_generate_asset_image_model_persists_generated_raster(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Slice 0 / Step 1: the Python T2I provider path. A mocked model returns real
    # PNG bytes that are persisted through the SAME ingest pipeline as uploads,
    # stamped with a `generated` source — no live API key required.
    png = _tiny_png(8, 8)

    def fake_generate(**kwargs) -> image_provider.ImageGenerationResult:
        assert kwargs["prompt"], "prompt must thread through to the provider"
        # brand_notes flow through for conditioning
        assert kwargs.get("brand_notes") == ["warm palette", "trustworthy"]
        return image_provider.ImageGenerationResult(
            image_bytes=png,
            mime_type="image/png",
            model="mock-image-model",
            provenance={
                "created_by": "agent",
                "created_at": "2026-06-19T00:00:00Z",
                "source_label": "image generation",
                "confidence": None,
                "notes": ["model=mock-image-model"],
            },
            license={
                "name": "generated_commercial_use",
                "allow_export": True,
                "allow_modification": True,
                "allow_embedding": True,
                "allow_subsetting": False,
                "source_url": None,
                "restrictions": [],
            },
        )

    monkeypatch.setattr(image_provider, "generate", fake_generate)

    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "a calm, sunlit clinic waiting room, editorial photography",
            "width": 8,
            "height": 8,
            "brand_notes": ["warm palette", "trustworthy"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    record = body["asset"]
    assert record["kind"] == "raster_image"
    assert record["source"]["kind"] == "generated"
    assert record["source"]["model"] == "mock-image-model"
    assert record["raster"]["pixel_width"] == 8
    assert record["raster"]["pixel_height"] == 8
    assert record["license"]["allow_export"] is True
    assert body["provider"]["id"] == "image-gen-v1"

    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200
    assert served.content == png


def test_generate_asset_image_model_not_configured_returns_clean_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no model configured and no mock, the provider raises a typed error
    # that surfaces as a clean 503 (never a 500).
    monkeypatch.setattr(settings, "image_model_base_url", "")
    monkeypatch.setattr(settings, "image_model_api_key", "")
    response = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": "anything"},
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "image_model.not_configured"


def test_image_provider_openrouter_chat_completion_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Raw-HTTP OpenRouter adapter: POST {base}/chat/completions with an image
    # modality; decode the data: URL from choices[0].message.images[0].
    import base64

    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    # Pin the TRANSPORT, not just the credentials: .env.example ships
    # IMAGE_MODEL_API_STYLE=images uncommented, so a dev who follows the
    # documented copy-.env.example-to-.env workflow flips the ambient default
    # and every chat-shape assertion below would otherwise go red on a machine
    # that is configured exactly as the docs say to configure it.
    monkeypatch.setattr(settings, "image_model_api_style", "chat")

    png = _tiny_png(8, 8)
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"choices": [{"message": {"images": [{"image_url": {"url": data_url}}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _FakeResponse()

    _patch_image_post(monkeypatch, fake_post)

    result = image_provider.generate(
        prompt="a calm clinic waiting room",
        aspect_ratio="16:9",
        brand_notes=["warm palette"],
    )
    assert result.image_bytes == png
    assert result.mime_type == "image/png"
    assert result.model == "test/image-model"
    # request shape: chat-completions + image modality, brand/aspect threaded in
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == "test/image-model"
    assert captured["json"]["modalities"] == ["image", "text"]
    content = captured["json"]["messages"][0]["content"]
    assert "16:9" in content and "warm palette" in content
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_image_provider_surfaces_no_image_response(monkeypatch: pytest.MonkeyPatch) -> None:
    # A text-only chat response (model refused / no image) -> typed error.
    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    # Pin the TRANSPORT, not just the credentials: .env.example ships
    # IMAGE_MODEL_API_STYLE=images uncommented, so a dev who follows the
    # documented copy-.env.example-to-.env workflow flips the ambient default
    # and every chat-shape assertion below would otherwise go red on a machine
    # that is configured exactly as the docs say to configure it.
    monkeypatch.setattr(settings, "image_model_api_style", "chat")

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "I can't make that image."}}]}

    _patch_image_post(monkeypatch, lambda *a, **k: _FakeResponse())

    with pytest.raises(image_provider.ImageGenerationError) as excinfo:
        image_provider.generate(prompt="anything")
    assert excinfo.value.code == "image_model.no_image"


def test_image_generation_cache_dedups_identical_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Slice 0 / Step 6: an identical repeat request re-uses the cached asset instead
    # of re-paying the (paid, non-deterministic) model. The byte-digest store dedup
    # only fires AFTER the call — too late; this cache fires BEFORE the provider.
    png = _tiny_png(8, 8)
    calls = {"n": 0}

    def fake_generate(**kwargs) -> image_provider.ImageGenerationResult:
        calls["n"] += 1
        return image_provider.ImageGenerationResult(
            image_bytes=png,
            mime_type="image/png",
            model="mock-image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr(image_provider, "generate", fake_generate)
    body = {
        "provider": "image-gen-v1",
        "prompt": "a calm sunlit clinic reception, editorial photography",
        "width": 1024,
        "height": 768,
        "brand_notes": ["deep navy", "premium"],
    }

    first = client.post("/assets/generate", json=body)
    assert first.status_code == 200, first.text
    first_id = first.json()["asset"]["id"]
    assert calls["n"] == 1
    assert first.json()["deduplicated"] is False

    # Identical request → cache hit: the model is NOT called again, same asset id.
    second = client.post("/assets/generate", json=body)
    assert second.status_code == 200, second.text
    assert calls["n"] == 1, "the cached request must not re-call the model"
    assert second.json()["deduplicated"] is True
    assert second.json()["asset"]["id"] == first_id

    # A different prompt is a cache miss → the model runs again.
    third = client.post("/assets/generate", json={**body, "prompt": "a wholly different scene"})
    assert third.status_code == 200, third.text
    assert calls["n"] == 2


# --- W1.4 / W1.7 (brand-ad-assets v1): model id + generation robustness -----


def _image_model_env(monkeypatch: pytest.MonkeyPatch, model_id: str = "test/image-model") -> None:
    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", model_id)


class _StubResponse:
    """Minimal httpx-response stand-in for the OpenRouter adapter."""

    headers = {"content-type": "application/json"}

    def __init__(self, payload: dict, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> dict:
        return self._payload


def _image_response(png: bytes) -> _StubResponse:
    import base64

    url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return _StubResponse({"choices": [{"message": {"images": [{"image_url": {"url": url}}]}}]})


_TEXT_ONLY_RESPONSE = {"choices": [{"message": {"content": "I can't make that image."}}]}


def test_w14_blank_or_sentinel_model_id_resolves_to_the_verified_working_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.4: `.env` shipped `openai/gpt-image-2`, which OpenRouter serves ONLY on
    its dedicated Image API — on the chat-completions image modality this
    provider uses it 404s. The in-code default must be a model that actually
    works on THIS path, and the config layer's `"default"` sentinel (what a blank
    IMAGE_MODEL_ID normalizes to) is not one — it 404s just the same.

    RED before the fix: `configured_model_id()` returned the literal `"default"`."""
    assert image_provider.DEFAULT_IMAGE_MODEL_ID == "openai/gpt-5.4-image-2"

    monkeypatch.setattr(settings, "image_model_id", "default")
    assert image_provider.configured_model_id() == "openai/gpt-5.4-image-2"

    monkeypatch.setattr(settings, "image_model_id", "   ")
    assert image_provider.configured_model_id() == "openai/gpt-5.4-image-2"

    # An explicitly configured id is always honored — no silent override.
    monkeypatch.setattr(settings, "image_model_id", "google/gemini-2.5-flash-image")
    assert image_provider.configured_model_id() == "google/gemini-2.5-flash-image"

    # The known Image-API-only ids are named so the 404 can be explained.
    assert "openai/gpt-image-2" in image_provider._IMAGE_API_ONLY_MODEL_IDS


@pytest.mark.parametrize("model_id", ["openai/gpt-image-2", "openai/gpt-image-2.5-flare"])
def test_w14_model_not_found_404_logs_the_config_fix_not_just_the_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, model_id: str
) -> None:
    """W1.4: a wrong IMAGE_MODEL_ID surfaces as a generic 'no endpoints found'
    404 that reads like a provider outage (it cost the Apollo POC a restart to
    diagnose). The first failing call must name the actual remedy in the log.

    The typed error still propagates unchanged — this adds a diagnostic, not a
    behavior change."""
    _image_model_env(monkeypatch, model_id)
    body = (
        '{"error":{"message":"No endpoints found that support the requested '
        'output modalities: image, text"}}'
    )
    _patch_image_post(
        monkeypatch, lambda *a, **k: _StubResponse({}, status_code=404, text=body)
    )

    with (
        caplog.at_level(logging.ERROR, logger="lumen_api.image_provider"),
        pytest.raises(image_provider.ImageGenerationError) as excinfo,
    ):
        image_provider.generate(prompt="a holographic yellow wash")

    assert excinfo.value.code == "image_model.http_error"
    logged = caplog.text
    assert model_id in logged
    assert "IMAGE-API" in logged.upper()
    assert "IMAGE_MODEL_API_STYLE=images" in logged
    assert "Set IMAGE_MODEL_ID=" not in logged  # preserve the selected model


def test_w17a_text_only_response_is_retried_exactly_once_then_fails_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.7(a): the model is non-deterministic about honoring the image modality
    — 1 of 4 Apollo POC calls came back text-only (`image_model.no_image`) and
    the POC's manual re-request succeeded. One automatic retry, then typed failure.

    RED before the fix: `_invoke_with_retries` re-raised EVERY ImageGenerationError
    immediately, so calls == 1 and a one-in-four flake was a hard failure."""
    _image_model_env(monkeypatch)
    png = _tiny_png(8, 8)

    # Case 1: text-only, then an image -> the retry rescues the call.
    calls = {"n": 0}

    def flaky_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _StubResponse(_TEXT_ONLY_RESPONSE)
        return _image_response(png)

    _patch_image_post(monkeypatch, flaky_post)
    result = image_provider.generate(prompt="a holographic yellow wash")
    assert result.image_bytes == png
    assert calls["n"] == 2, "a text-only answer must be retried exactly once"

    # Case 2: text-only every time -> exactly ONE retry, then the typed error.
    # The retry budget must not be unbounded, and must not silently become a
    # success: a genuinely refusing prompt fails loudly after 2 attempts.
    always = {"n": 0}

    def always_text(*args, **kwargs):
        always["n"] += 1
        return _StubResponse(_TEXT_ONLY_RESPONSE)

    _patch_image_post(monkeypatch, always_text)
    with pytest.raises(image_provider.ImageGenerationError) as excinfo:
        image_provider.generate(prompt="something it will refuse")
    assert excinfo.value.code == "image_model.no_image"
    assert always["n"] == 1 + image_provider.NO_IMAGE_RETRIES == 2


def test_w17a_other_typed_errors_are_still_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.7(a) boundary: only `no_image` gets the extra attempt. Retrying a 404 or
    an undecodable response just re-buys the same answer at the same price."""
    _image_model_env(monkeypatch)
    calls = {"n": 0}

    def http_error(*args, **kwargs):
        calls["n"] += 1
        return _StubResponse({}, status_code=404, text="nope")

    _patch_image_post(monkeypatch, http_error)
    with pytest.raises(image_provider.ImageGenerationError):
        image_provider.generate(prompt="anything")
    assert calls["n"] == 1


def test_w17b_aspect_ratio_rides_the_request_structurally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.7(b): the POC asked 16:9 and got 1024x1024 because the ratio never left
    the prose. OpenRouter's chat-completions body takes a documented
    `image_config` object; the requested ratio must ride it.

    RED before the fix: the body had no `image_config` key at all."""
    _image_model_env(monkeypatch)
    png = _tiny_png(8, 8)
    captured: dict = {}

    def capture_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json)
        return _image_response(png)

    _patch_image_post(monkeypatch, capture_post)
    image_provider.generate(prompt="a holographic yellow wash", aspect_ratio="16:9")
    assert captured["json"]["image_config"] == {"aspect_ratio": "16:9"}
    # Belt and braces: providers clamp to their own subset, so the prompt hint stays.
    assert "16:9" in captured["json"]["messages"][0]["content"]

    # No ask -> no key at all, so a plain generation's body is unchanged.
    captured.clear()
    image_provider.generate(prompt="a holographic yellow wash")
    assert "image_config" not in captured["json"]


def test_w17b_requested_ratios_snap_to_openrouters_allowlist() -> None:
    """W1.7(b): callers speak in frame geometry ('3x2', '1.78', a raw node
    ratio); OpenRouter takes a normalized ratio and providers reject values off
    their supported subset. Every ask must land on a documented value."""
    snap = image_provider.api_aspect_ratio
    assert snap("16:9") == "16:9"
    assert snap("16x9") == "16:9"
    assert snap("1.78") == "16:9"
    assert snap("1:1") == "1:1"
    assert snap("4:5") == "4:5"
    assert snap("1080:1350") == "4:5"  # a real LinkedIn ad frame
    assert snap(None) is None
    assert snap("not-a-ratio") is None
    assert snap("0:0") is None
    for value in ("16:9", "3:2", "9:16", "21:9", "2.35", "0.1", "12"):
        assert snap(value) in image_provider._SUPPORTED_ASPECT_RATIOS


def test_w17b_result_reports_actual_dimensions_not_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.7(b): the Apollo POC's manifest reported the generated asset as
    1024x1024 while every surface still said '16:9' — the caller was misled by
    its own request. The result must carry the MEASURED geometry and admit when
    the ratio was not honored.

    RED before the fix: ImageGenerationResult had no width/height at all."""
    _image_model_env(monkeypatch)

    # The exact POC shape: 16:9 asked, a square delivered.
    _patch_image_post(monkeypatch, lambda *a, **k: _image_response(_tiny_png(1024, 8)))
    ignored = image_provider.generate(prompt="a wash", aspect_ratio="16:9")
    assert (ignored.width, ignored.height) == (1024, 8)
    assert ignored.requested_aspect_ratio == "16:9"
    assert ignored.aspect_ratio_honored is False
    notes = " ".join(ignored.provenance["notes"])
    assert "did not honor requested aspect_ratio 16:9" in notes
    assert "output 1024x8" in notes

    # An honored ratio reports honored, and adds no complaint to provenance.
    _patch_image_post(monkeypatch, lambda *a, **k: _image_response(_tiny_png(32, 18)))
    honored = image_provider.generate(prompt="a wash", aspect_ratio="16:9")
    assert (honored.width, honored.height) == (32, 18)
    assert honored.aspect_ratio_honored is True
    assert not any("did not honor" in note for note in honored.provenance["notes"])

    # No ask -> the question is unanswerable, not False.
    _patch_image_post(monkeypatch, lambda *a, **k: _image_response(_tiny_png(8, 8)))
    assert image_provider.generate(prompt="a wash").aspect_ratio_honored is None


def test_w17b_sniff_dimensions_reads_real_headers_and_never_raises() -> None:
    """W1.7(b): header-only, dependency-free, and honest about not knowing."""
    assert image_provider.sniff_dimensions(_tiny_png(21, 9)) == (21, 9)
    assert image_provider.sniff_dimensions(b"GIF89a" + b"\x40\x00\x20\x00") == (64, 32)
    # Unreadable input is "unknown", never an exception.
    for junk in (b"", b"not an image", b"\x89PNG\r\n\x1a\n", b"\xff\xd8truncated"):
        assert image_provider.sniff_dimensions(junk) == (None, None)


def test_resolve_dimensions_translates_aspect_ratio_and_size_tier() -> None:
    # Step 7 (G0.2): aspect_ratio + image_size → concrete dimensions; explicit dims win.
    resolve = image_provider.resolve_dimensions
    assert resolve(1080, 1350, "16:9", "2k") == (1080, 1350)  # explicit w+h win
    assert resolve(None, None, "16:9", None) == (1024, 576)  # default 1k long edge
    assert resolve(None, None, "16:9", "2k") == (2048, 1152)
    assert resolve(None, None, "4:5", "1k") == (819, 1024)  # portrait
    assert resolve(None, None, "3x2", None) == (1024, 683)  # 'WxH' form
    assert resolve(None, None, None, "4k") == (4096, 4096)  # no aspect → square at tier
    assert resolve(None, None, "1:1", "unknown") == (1024, 1024)  # unknown tier → 1k


def test_generate_asset_image_model_forwards_aspect_size_and_references(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 7 + RC2 D-RC2.5: the route threads aspect_ratio / image_size to the
    # provider AND resolves reference_asset_ids FOR REAL — the once-inert field now
    # lands the reference PIXELS on the provider's reference_images channel (bytes
    # read from the store), while the ids stay passed through too.
    ref_rgba = (12, 200, 90, 255)
    ref = _upload_source_raster(client, rgba=ref_rgba, label="style-ref")
    ref_png = _tiny_png(8, 8, rgba=ref_rgba)
    captured: dict = {}

    def fake_generate(**kwargs) -> image_provider.ImageGenerationResult:
        captured.update(kwargs)
        return image_provider.ImageGenerationResult(
            image_bytes=_tiny_png(8, 8),
            mime_type="image/png",
            model="mock-image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr(image_provider, "generate", fake_generate)
    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "a hero photograph",
            "aspect_ratio": "16:9",
            "image_size": "2k",
            "reference_asset_ids": [ref["id"]],
        },
    )
    assert response.status_code == 200, response.text
    assert captured["aspect_ratio"] == "16:9"
    assert captured["image_size"] == "2k"
    assert captured["reference_asset_ids"] == [ref["id"]]
    # The real resolution: the reference's stored pixels ride the bytes channel.
    assert captured["reference_images"] == [(ref_png, "image/png")]


def _upload_source_raster(
    client: TestClient, rgba=(64, 120, 200, 255), label: str = "source"
) -> dict:
    """Upload a valid PNG as a source asset with content-addressed stored bytes.

    Distinct `rgba` -> distinct pixels -> distinct digest, which is what an
    edit's source-keyed cache must discriminate on.
    """
    png = _tiny_png(8, 8, rgba=rgba)
    response = client.post(
        "/assets",
        files={"file": (f"{label}.png", png, "image/png")},
        data={"label": label, "kind": "raster_image", "uploaded_by": "designer"},
    )
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def test_generate_asset_image_edit_loads_source_bytes_and_stamps_edited_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 3b: an edit with source_asset_id routes to image_provider.edit with the
    # SOURCE BYTES loaded from the store, and the persisted record's source chains
    # provenance to the parent as kind "edited".
    source = _upload_source_raster(client)
    source_png = _tiny_png(8, 8, rgba=(64, 120, 200, 255))
    edited_png = _tiny_png(8, 8, rgba=(10, 20, 30, 255))
    captured: dict = {}

    def fake_edit(**kwargs) -> image_provider.ImageGenerationResult:
        captured.update(kwargs)
        return image_provider.ImageGenerationResult(
            image_bytes=edited_png,
            mime_type="image/png",
            model="mock-image-model",
            provenance={"created_by": "agent", "source_label": "image edit", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr(image_provider, "edit", fake_edit)
    # generate must NOT be called on the edit path
    def fail_generate(**kwargs):  # pragma: no cover - guard
        raise AssertionError("edit path must not call generate")

    monkeypatch.setattr(image_provider, "generate", fail_generate)

    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "make the sky pink",
            "source_asset_id": source["id"],
        },
    )
    assert response.status_code == 200, response.text
    record = response.json()["asset"]
    # source bytes were loaded from the store and handed to edit()
    assert captured["prompt"] == "make the sky pink"
    assert captured["source_images"] == [(source_png, "image/png")]
    # provenance chains to the parent
    assert record["source"]["kind"] == "edited"
    assert record["source"]["source_asset_id"] == source["id"]
    assert record["source"]["model"] == "mock-image-model"
    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200
    assert served.content == edited_png


def test_image_edit_cache_keys_on_source_digest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The edit cache must discriminate on source pixels: the SAME instruction on
    # a DIFFERENT source is a miss; a repeat of the same (source, prompt) is a hit.
    source_a = _upload_source_raster(client, rgba=(64, 120, 200, 255), label="a")
    source_b = _upload_source_raster(client, rgba=(200, 30, 30, 255), label="b")
    calls = {"n": 0}

    def fake_edit(**kwargs) -> image_provider.ImageGenerationResult:
        calls["n"] += 1
        return image_provider.ImageGenerationResult(
            image_bytes=_tiny_png(8, 8, rgba=(1, 2, 3, 255)),
            mime_type="image/png",
            model="mock-image-model",
            provenance={"created_by": "agent", "source_label": "image edit", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr(image_provider, "edit", fake_edit)
    prompt = "remove the background"

    first = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": prompt, "source_asset_id": source_a["id"]},
    )
    assert first.status_code == 200, first.text
    assert calls["n"] == 1
    assert first.json()["deduplicated"] is False

    # Different source, identical prompt -> MISS (must not return A's result).
    second = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": prompt, "source_asset_id": source_b["id"]},
    )
    assert second.status_code == 200, second.text
    assert calls["n"] == 2, "a different source with the same prompt must not hit the cache"

    # Repeat of the first (source, prompt) -> HIT (model not re-called).
    repeat = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": prompt, "source_asset_id": source_a["id"]},
    )
    assert repeat.status_code == 200, repeat.text
    assert calls["n"] == 2, "an identical (source, prompt) edit must hit the cache"
    assert repeat.json()["deduplicated"] is True
    assert repeat.json()["asset"]["id"] == first.json()["asset"]["id"]


def test_image_edit_source_bytes_missing_returns_409(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A source record whose bytes are absent from the store -> clean 409, not a 500.
    def fail_edit(**kwargs):  # pragma: no cover - guard
        raise AssertionError("edit must not run when source bytes are missing")

    monkeypatch.setattr(image_provider, "edit", fail_edit)

    source = _upload_source_raster(client, rgba=(5, 6, 7, 255), label="gone")
    # Remove the content-addressed blob backing the record, leaving the record.
    for blob in store_files(tmp_path):
        blob.unlink()

    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "edit me",
            "source_asset_id": source["id"],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "asset.source_bytes_missing"


def test_image_provider_edit_rejects_empty_prompt_and_missing_source() -> None:
    # Typed guardrails on the edit provider entrypoint.
    with pytest.raises(image_provider.ImageGenerationError) as empty:
        image_provider.edit(prompt="   ", source_images=[(b"x", "image/png")])
    assert empty.value.code == "image_model.empty_prompt"

    with pytest.raises(image_provider.ImageGenerationError) as missing:
        image_provider.edit(prompt="make it pop", source_images=[])
    assert missing.value.code == "image_model.missing_source"


def test_image_provider_edit_builds_multimodal_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # _invoke_model turns source_images into OpenAI-style multimodal content:
    # image_url part(s) first, the text instruction last.
    import base64

    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    # Pin the TRANSPORT, not just the credentials: .env.example ships
    # IMAGE_MODEL_API_STYLE=images uncommented, so a dev who follows the
    # documented copy-.env.example-to-.env workflow flips the ambient default
    # and every chat-shape assertion below would otherwise go red on a machine
    # that is configured exactly as the docs say to configure it.
    monkeypatch.setattr(settings, "image_model_api_style", "chat")

    src_png = _tiny_png(8, 8)
    out_png = _tiny_png(8, 8, rgba=(9, 9, 9, 255))
    out_url = "data:image/png;base64," + base64.b64encode(out_png).decode("ascii")
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"choices": [{"message": {"images": [{"image_url": {"url": out_url}}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _FakeResponse()

    _patch_image_post(monkeypatch, fake_post)

    result = image_provider.edit(
        prompt="remove the background completely",
        source_images=[(src_png, "image/png")],
        transparent_background=True,
    )
    assert result.image_bytes == out_png

    content = captured["json"]["messages"][0]["content"]
    assert isinstance(content, list)
    # image part first, text part last
    assert content[0]["type"] == "image_url"
    expected_data_url = "data:image/png;base64," + base64.b64encode(src_png).decode("ascii")
    assert content[0]["image_url"]["url"] == expected_data_url
    assert content[-1]["type"] == "text"
    assert "remove the background completely" in content[-1]["text"]
    assert "transparent background" in content[-1]["text"]


def test_image_provider_generate_builds_reference_conditioned_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RC2 D-RC2.2: reference_images turn a GENERATION into OpenAI-style multimodal
    # content — reference image part(s) FIRST, the instruction LAST, prefixed with
    # the fixed STYLE-REFERENCE framing (make a NEW image, don't edit these).
    import base64

    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    # Pin the TRANSPORT, not just the credentials: .env.example ships
    # IMAGE_MODEL_API_STYLE=images uncommented, so a dev who follows the
    # documented copy-.env.example-to-.env workflow flips the ambient default
    # and every chat-shape assertion below would otherwise go red on a machine
    # that is configured exactly as the docs say to configure it.
    monkeypatch.setattr(settings, "image_model_api_style", "chat")

    ref_a = _tiny_png(8, 8, rgba=(200, 40, 40, 255))
    ref_b = _tiny_png(8, 8, rgba=(40, 40, 200, 255))
    out_png = _tiny_png(8, 8, rgba=(9, 9, 9, 255))
    out_url = "data:image/png;base64," + base64.b64encode(out_png).decode("ascii")
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"choices": [{"message": {"images": [{"image_url": {"url": out_url}}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _FakeResponse()

    _patch_image_post(monkeypatch, fake_post)

    result = image_provider.generate(
        prompt="a focused surgeon in an operating theatre",
        brand_notes=["calm clinical confidence"],
        aspect_ratio="16:9",
        reference_images=[(ref_a, "image/png"), (ref_b, "image/png")],
    )
    assert result.image_bytes == out_png

    content = captured["json"]["messages"][0]["content"]
    assert isinstance(content, list)
    # References first, in order; instruction last.
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(ref_a).decode("ascii")
    )
    assert content[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(ref_b).decode("ascii")
    )
    assert content[-1]["type"] == "text"
    text = content[-1]["text"]
    assert image_provider.STYLE_REFERENCE_FRAMING in text
    assert "STYLE REFERENCES only" in text
    # The composed prompt (subject + brand notes) and the aspect hint still ride the
    # instruction, AFTER the framing.
    assert "a focused surgeon" in text
    assert "calm clinical confidence" in text
    assert "aspect ratio 16:9" in text
    assert text.index(image_provider.STYLE_REFERENCE_FRAMING) < text.index("a focused surgeon")


def test_image_provider_generate_without_references_is_bare_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No-references path stays BYTE-IDENTICAL: bare-string content (no multimodal
    # list), exactly the request a plain text-to-image call has always made.
    import base64

    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    # Pin the TRANSPORT, not just the credentials: .env.example ships
    # IMAGE_MODEL_API_STYLE=images uncommented, so a dev who follows the
    # documented copy-.env.example-to-.env workflow flips the ambient default
    # and every chat-shape assertion below would otherwise go red on a machine
    # that is configured exactly as the docs say to configure it.
    monkeypatch.setattr(settings, "image_model_api_style", "chat")

    out_png = _tiny_png(8, 8, rgba=(1, 2, 3, 255))
    out_url = "data:image/png;base64," + base64.b64encode(out_png).decode("ascii")
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"choices": [{"message": {"images": [{"image_url": {"url": out_url}}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(json=json)
        return _FakeResponse()

    _patch_image_post(monkeypatch, fake_post)

    image_provider.generate(prompt="a quiet mountain lake at dawn", aspect_ratio="16:9")
    content = captured["json"]["messages"][0]["content"]
    assert content == "a quiet mountain lake at dawn\n\n(Render with aspect ratio 16:9.)"


# --- IMG-API: the gpt-image-2 (OpenRouter Images API) transport --------------
#
# `openai/gpt-image-2` does NOT speak the chat-completions image modality; it
# takes an OpenAI-Images-style body at POST {base_url}/images with a top-level
# `prompt` and a base64 `data[*].b64_json` response (founder-supplied OpenRouter
# reference, 2026-08-23). `IMAGE_MODEL_API_STYLE=images` selects that transport;
# the default `chat` path stays byte-identical for the Gemini-class models.


def _images_api_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "openai/gpt-image-2")
    monkeypatch.setattr(settings, "image_model_api_style", "images")


def _capture_images_api_post(
    monkeypatch: pytest.MonkeyPatch, out_png: bytes
) -> dict:
    """Patch httpx.post with a stub that captures the request and answers in the
    documented Images-API shape (`data[*].b64_json`)."""
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {
                "data": [{"b64_json": base64.b64encode(out_png).decode("ascii")}]
            }

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return _FakeResponse()

    _patch_image_post(monkeypatch, fake_post)
    return captured


@pytest.mark.parametrize("model_id", ["openai/gpt-image-2", "openai/gpt-image-2.5-flare"])
def test_image_provider_images_api_generation_body(
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
) -> None:
    # The founder's generation sample, minus `stream` (we are synchronous):
    # top-level prompt + structured aspect_ratio + quality + background. No
    # messages, no modalities. FOUNDER RULE 2026-08-23: `background` is ALWAYS
    # "auto" — the enum is auto|opaque, so it has no "transparent" member at all
    # and a transparent request can only be a prose hint, best-effort (see
    # test_image_provider_images_api_transparency_is_prose_only). "auto" is what
    # both founder sample bodies carry; do not "tidy up" the default away.
    _images_api_settings(monkeypatch)
    monkeypatch.setattr(settings, "image_model_id", model_id)
    out_png = _tiny_png(8, 8, rgba=(3, 3, 3, 255))
    captured = _capture_images_api_post(monkeypatch, out_png)

    result = image_provider.generate(
        prompt="a calm clinic waiting room",
        brand_notes=["warm palette"],
        aspect_ratio="16:9",
        image_size="2k",
    )
    assert result.image_bytes == out_png
    assert result.mime_type == "image/png"
    assert result.model == model_id

    assert captured["url"] == "https://openrouter.ai/api/v1/images"
    assert captured["json"] == {
        "model": model_id,
        "prompt": "a calm clinic waiting room\n\nBrand/style direction: warm palette",
        "aspect_ratio": "16:9",
        "quality": "high",
        "background": "auto",
    }
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_image_provider_images_api_omits_chat_only_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Explicit negative pins: the chat vocabulary and streaming never appear.
    _images_api_settings(monkeypatch)
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))
    image_provider.generate(prompt="a hero band", aspect_ratio="16:9")
    body = captured["json"]
    for absent in ("messages", "modalities", "stream", "n", "size", "output_compression"):
        assert absent not in body, absent
    # The prose aspect hint belongs to the chat path only — here it is structural.
    assert "(Render with" not in body["prompt"]


def test_image_provider_images_api_snaps_aspect_ratio_to_the_supported_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `aspect_ratio` is a CLOSED enum (1:1, 3:2, 2:3, 4:3, 3:4, 16:9, 9:16, 21:9,
    # auto). An unsupported caller ratio snaps to the NEAREST supported value
    # rather than being sent verbatim (which would be a 400 → grey stub).
    _images_api_settings(monkeypatch)
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))

    image_provider.generate(prompt="a wide banner", aspect_ratio="5:2")
    assert captured["json"]["aspect_ratio"] == "21:9"

    image_provider.generate(prompt="a portrait", aspect_ratio="4:5")
    assert captured["json"]["aspect_ratio"] == "3:4"

    # Exact members survive untouched, including the alternate `16x9` spelling.
    image_provider.generate(prompt="a hero", aspect_ratio="16x9")
    assert captured["json"]["aspect_ratio"] == "16:9"


def test_image_provider_images_api_derives_aspect_ratio_from_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With only width/height the ratio is derived the way resolve_dimensions
    # reasons, then snapped.
    _images_api_settings(monkeypatch)
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))
    image_provider.generate(prompt="a hero band", width=1024, height=768)
    assert captured["json"]["aspect_ratio"] == "4:3"


def test_image_provider_images_api_transparency_is_prose_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `background` accepts only auto|opaque, so a transparent request CANNOT be
    # expressed structurally. FOUNDER RULE 2026-08-23: `background` is ALWAYS
    # "auto" (as in the founder's own sample bodies) — a transparent request
    # still sends "auto" and asks for transparency in PROSE, best-effort. Never
    # a fake "transparent" enum value (that is a 400 → grey stub), and never a
    # silent claim that the request was honored: this model cannot guarantee an
    # alpha channel and the caller gets whatever it renders.
    _images_api_settings(monkeypatch)
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))
    image_provider.generate(prompt="a cut-out product shot", transparent_background=True)
    body = captured["json"]
    assert body["background"] == "auto"
    assert "transparent background" in body["prompt"]


def test_image_provider_images_api_always_sends_background_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The founder's sample bodies carry `"background":"auto"` on BOTH the plain
    # and the reference-conditioned call, and the rule is explicit: always auto.
    # Pinned separately from the full-body test so a future "omit the default"
    # tidy-up has to argue with the founder rule rather than slip through.
    _images_api_settings(monkeypatch)
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))

    image_provider.generate(prompt="a hero band", aspect_ratio="16:9")
    assert captured["json"]["background"] == "auto"

    image_provider.generate(
        prompt="a hero band",
        aspect_ratio="3:2",
        reference_images=[(_tiny_png(8, 8), "image/png")],
    )
    assert captured["json"]["background"] == "auto"

    image_provider.edit(
        prompt="make the sky pink", source_images=[(_tiny_png(8, 8), "image/png")]
    )
    assert captured["json"]["background"] == "auto"


def test_image_provider_images_api_square_default_is_sent_structurally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A generation with no framing at all still resolves to a 1024x1024 frame
    # (resolve_dimensions' documented default), and the body says so: 1:1, not
    # an omitted field. The rest of the stack already places into that square,
    # so letting the endpoint's own `auto` pick something else would hand
    # cover-fit placement a crop it did not ask for.
    _images_api_settings(monkeypatch)
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))
    image_provider.generate(prompt="a plain illustration")
    assert captured["json"]["aspect_ratio"] == "1:1"


@pytest.mark.parametrize("model_id", ["openai/gpt-image-2", "openai/gpt-image-2.5-flare"])
def test_image_provider_images_api_input_references_match_the_founder_sample(
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
) -> None:
    # Reference-conditioned generation: `input_references` typed dicts in caller
    # order. The founder's sample used https URLs; we send base64 data: URLs.
    # This verifies transport serialization, not live provider support or quality.
    _images_api_settings(monkeypatch)
    monkeypatch.setattr(settings, "image_model_id", model_id)
    ref_a = _tiny_png(8, 8, rgba=(200, 40, 40, 255))
    ref_b = _tiny_png(8, 8, rgba=(40, 40, 200, 255))
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))

    image_provider.generate(
        prompt="a focused surgeon in an operating theatre",
        aspect_ratio="3:2",
        reference_images=[(ref_a, "image/png"), (ref_b, "image/png")],
    )
    body = captured["json"]
    assert body["model"] == model_id
    assert body["input_references"] == [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(ref_a).decode("ascii")
            },
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(ref_b).decode("ascii")
            },
        },
    ]
    # gpt-image-2 composites reference SUBJECTS by design, so the style-anchor
    # framing is load-bearing here — and it rides the prompt, not a body field.
    assert body["prompt"].startswith(image_provider.STYLE_REFERENCE_FRAMING)
    assert "a focused surgeon" in body["prompt"]
    assert body["aspect_ratio"] == "3:2"


def test_image_provider_images_api_edit_sends_source_as_input_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An edit's source image rides the same `input_references` channel, WITHOUT
    # the style-anchor framing (an edit really does mean "use this image").
    _images_api_settings(monkeypatch)
    src = _tiny_png(8, 8, rgba=(7, 7, 7, 255))
    captured = _capture_images_api_post(monkeypatch, _tiny_png(8, 8))

    image_provider.edit(prompt="make the sky pink", source_images=[(src, "image/png")])
    body = captured["json"]
    assert body["input_references"] == [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(src).decode("ascii")
            },
        }
    ]
    assert image_provider.STYLE_REFERENCE_FRAMING not in body["prompt"]
    # No dimensions on an edit → no aspect ratio asserted.
    assert "aspect_ratio" not in body


def test_image_provider_images_api_refuses_more_references_than_the_endpoint_takes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `input_references` is documented 0-16. Our upstream cap is far lower, so
    # this can only fire on a caller bug — it must fail loudly, not silently
    # truncate the anchors the user attached.
    _images_api_settings(monkeypatch)
    _capture_images_api_post(monkeypatch, _tiny_png(8, 8))
    too_many = [(_tiny_png(8, 8), "image/png")] * (
        image_provider.IMAGES_API_MAX_INPUT_REFERENCES + 1
    )
    with pytest.raises(image_provider.ImageGenerationError) as excinfo:
        image_provider.generate(prompt="a hero", reference_images=too_many)
    assert excinfo.value.code == "image_model.too_many_references"


def test_image_provider_images_api_decodes_b64_then_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Documented shape first: data[*].b64_json. A `data:` URL in data[0].url
    # reuses the existing decoder; a plain https URL is fetched (the minimal
    # slice of the W4.1 fetch the images path needs to function).
    _images_api_settings(monkeypatch)
    png = _tiny_png(8, 8, rgba=(5, 6, 7, 255))
    payloads: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return payloads["body"]

    _patch_image_post(monkeypatch, lambda *a, **k: _FakeResponse())

    payloads["body"] = {"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}
    assert image_provider.generate(prompt="x").image_bytes == png

    payloads["body"] = {
        "data": [
            {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}
        ]
    }
    assert image_provider.generate(prompt="x").image_bytes == png

    fetched: dict = {}

    class _FakeGetResponse:
        status_code = 200
        headers = {"content-type": "image/png"}
        content = png

    def fake_get(url, timeout=None, **kwargs):
        fetched.update(url=url, timeout=timeout)
        return _FakeGetResponse()

    monkeypatch.setattr("httpx.get", fake_get)
    payloads["body"] = {"data": [{"url": "https://cdn.example/out-0.png"}]}
    result = image_provider.generate(prompt="x")
    assert result.image_bytes == png
    assert result.mime_type == "image/png"
    assert fetched["url"] == "https://cdn.example/out-0.png"
    assert fetched["timeout"] == settings.image_model_timeout_s


def test_image_provider_images_api_url_fetch_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A by-reference result is typically a SIGNED CDN URL, and those redirect.
    # httpx defaults follow_redirects=False, which hands back a 302 whose body is
    # empty — zero bytes that would sail through as a "successful" generation and
    # land an empty image in the document. The fetch must follow the redirect.
    _images_api_settings(monkeypatch)
    png = _tiny_png(8, 8, rgba=(4, 5, 6, 255))

    class _FakePostResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"data": [{"url": "https://cdn.example/signed/out-0.png"}]}

    fetched: dict = {}

    class _FakeGetResponse:
        status_code = 200
        headers = {"content-type": "image/png"}
        content = png

    def fake_get(url, timeout=None, **kwargs):
        fetched.update(url=url, timeout=timeout, **kwargs)
        return _FakeGetResponse()

    _patch_image_post(monkeypatch, lambda *a, **k: _FakePostResponse())
    monkeypatch.setattr("httpx.get", fake_get)

    result = image_provider.generate(prompt="a signed-url result")
    assert result.image_bytes == png
    assert fetched["follow_redirects"] is True


def test_image_provider_images_api_url_fetch_rejects_a_non_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An expired signed URL, an error page, or a login interstitial answers 200
    # with text/html. Those bytes are not an image, and ingesting them would put
    # a corrupt asset in the document under a "generated" provenance stamp —
    # worse than failing, because it looks like it worked. Fail typed instead.
    _images_api_settings(monkeypatch)

    class _FakePostResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"data": [{"url": "https://cdn.example/expired"}]}

    class _FakeGetResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html><body>Access denied</body></html>"

    _patch_image_post(monkeypatch, lambda *a, **k: _FakePostResponse())
    monkeypatch.setattr("httpx.get", lambda *a, **k: _FakeGetResponse())

    with pytest.raises(image_provider.ImageGenerationError) as excinfo:
        image_provider.generate(prompt="an expired signed url")
    assert excinfo.value.code == "image_model.bad_response"


def test_image_provider_images_api_garbage_response_is_bad_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _images_api_settings(monkeypatch)

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"error": {"message": "model unavailable"}}

    _patch_image_post(monkeypatch, lambda *a, **k: _FakeResponse())
    with pytest.raises(image_provider.ImageGenerationError) as excinfo:
        image_provider.generate(prompt="anything")
    assert excinfo.value.code == "image_model.bad_response"


def test_image_provider_chat_style_request_bodies_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: with the default `chat` style the request bodies are exactly
    # what they were before the images transport existed — the Gemini-class
    # models still ride this path and must not shift by one byte.
    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    monkeypatch.setattr(settings, "image_model_api_style", "chat")

    out_png = _tiny_png(8, 8, rgba=(9, 9, 9, 255))
    out_url = "data:image/png;base64," + base64.b64encode(out_png).decode("ascii")
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"choices": [{"message": {"images": [{"image_url": {"url": out_url}}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _FakeResponse()

    _patch_image_post(monkeypatch, fake_post)

    # (1) plain generation — bare-string content, prose hints, image modality.
    image_provider.generate(
        prompt="a calm clinic waiting room",
        brand_notes=["warm palette"],
        aspect_ratio="16:9",
        image_size="2k",
        transparent_background=True,
    )
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["json"] == {
        "model": "test/image-model",
        "messages": [
            {
                "role": "user",
                "content": (
                    "a calm clinic waiting room\n\nBrand/style direction: warm palette"
                    "\n\n(Render with aspect ratio 16:9, 2k resolution, "
                    "transparent background.)"
                ),
            }
        ],
        "modalities": ["image", "text"],
        # W1.7(b) (merged after this test was written on the v2 lane): a
        # REQUESTED ratio rides the chat body structurally; a no-ratio body
        # stays byte-identical (pinned by the W1.7 tests).
        "image_config": {"aspect_ratio": "16:9"},
    }

    # (2) reference-conditioned generation — multimodal parts, framing first.
    ref = _tiny_png(8, 8, rgba=(200, 40, 40, 255))
    image_provider.generate(
        prompt="a focused surgeon",
        aspect_ratio="3:2",
        reference_images=[(ref, "image/png")],
    )
    assert captured["json"] == {
        "model": "test/image-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(ref).decode("ascii")
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            image_provider.STYLE_REFERENCE_FRAMING
                            + "\n\na focused surgeon\n\n(Render with aspect ratio 3:2.)"
                        ),
                    },
                ],
            }
        ],
        "modalities": ["image", "text"],
        # W1.7(b): the requested ratio rides structurally here too.
        "image_config": {"aspect_ratio": "3:2"},
    }


def test_image_model_api_style_rejects_a_typo(monkeypatch: pytest.MonkeyPatch) -> None:
    # A typo'd transport must fail at startup, not silently send the wrong body
    # shape to a paid endpoint for the rest of the deployment's life.
    from py_lumen_config.config import Settings

    monkeypatch.setenv("IMAGE_MODEL_API_STYLE", "imagess")
    with pytest.raises(Exception) as excinfo:
        Settings()
    assert "IMAGE_MODEL_API_STYLE" in str(excinfo.value)

    monkeypatch.setenv("IMAGE_MODEL_API_STYLE", "images")
    assert Settings().image_model_api_style == "images"
    monkeypatch.setenv("IMAGE_MODEL_API_STYLE", "")
    assert Settings().image_model_api_style == "chat"


def test_generation_key_reference_digests() -> None:
    # RC2 D-RC2.3: reference_digests participate only when truthy (existing keys
    # byte-identical). Reference order is part of the composition contract.
    from lumen_api import image_cache

    base = image_cache.generation_key(prompt="a hero", model="m")
    # No digests / empty list -> identical to the pre-RC2 key (byte-compatible).
    assert image_cache.generation_key(prompt="a hero", model="m", reference_digests=None) == base
    assert image_cache.generation_key(prompt="a hero", model="m", reference_digests=[]) == base
    # Truthy digests change the key, including when their order changes.
    with_refs = image_cache.generation_key(prompt="a hero", model="m", reference_digests=["b", "a"])
    assert with_refs != base
    assert with_refs != image_cache.generation_key(
        prompt="a hero", model="m", reference_digests=["a", "b"]
    )
    # Different reference pixels -> different key.
    assert with_refs != image_cache.generation_key(
        prompt="a hero", model="m", reference_digests=["a", "c"]
    )


def test_generate_asset_route_422s_on_unknown_reference(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RC2 D-RC2.5: the route resolves references for real, so an unknown id fails
    # with the RC manifest's hard 422 (the field is no longer inert) — the model is
    # never called.
    def fail_generate(**kwargs):  # pragma: no cover - guard
        raise AssertionError("generate must not run when a reference id is bad")

    monkeypatch.setattr(image_provider, "generate", fail_generate)
    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "a hero photograph",
            "reference_asset_ids": ["asset_ghost"],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "reference.asset_not_found"


def test_generate_asset_reference_cache_keys_on_pixel_digests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RC2 D-RC2.3 at the route: the same (prompt, reference) is a cache HIT; the SAME
    # prompt with a DIFFERENT reference is a MISS (digests are in the key).
    ref_a = _upload_source_raster(client, rgba=(200, 40, 40, 255), label="ref-a")
    ref_b = _upload_source_raster(client, rgba=(40, 40, 200, 255), label="ref-b")
    calls = {"n": 0}

    def fake_generate(**kwargs) -> image_provider.ImageGenerationResult:
        calls["n"] += 1
        return image_provider.ImageGenerationResult(
            image_bytes=_tiny_png(8, 8, rgba=(7, 7, 7, 255)),
            mime_type="image/png",
            model="mock-image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr(image_provider, "generate", fake_generate)
    prompt = "a calm hero field"

    first = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": prompt, "reference_asset_ids": [ref_a["id"]]},
    )
    assert first.status_code == 200, first.text
    assert calls["n"] == 1
    assert first.json()["deduplicated"] is False

    # Different reference pixels, identical prompt -> MISS.
    second = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": prompt, "reference_asset_ids": [ref_b["id"]]},
    )
    assert second.status_code == 200, second.text
    assert calls["n"] == 2, "a different reference with the same prompt must not hit the cache"

    # Repeat of the first (prompt, reference) -> HIT (model not re-called).
    repeat = client.post(
        "/assets/generate",
        json={"provider": "image-gen-v1", "prompt": prompt, "reference_asset_ids": [ref_a["id"]]},
    )
    assert repeat.status_code == 200, repeat.text
    assert calls["n"] == 2, "an identical (prompt, reference) generation must hit the cache"
    assert repeat.json()["deduplicated"] is True
    assert repeat.json()["asset"]["id"] == first.json()["asset"]["id"]


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
    # chunk one, manifest truncated to the committed work). Batches live on
    # Postgres since D2.4, so this rewinds through the store surface rather
    # than the old direct SQLite UPDATE.
    from lumen_api.design_store import HybridRepository as _HybridRepository

    store = _HybridRepository()
    store.update_batch_progress(
        batch["batch_id"],
        1,
        "running",
        {
            "total": 3,
            "derived": 1,
            "failed": 0,
            "fit": {"fits": 1, "fits_with_policy": 0, "overflow": 0},
        },
        [batch["manifest"][0]],
        store.require_batch(batch["batch_id"])["diagnostics"],
    )

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


PRINT_RUN_PROFILE = {
    "name": "print_run",
    "format": "pdf",
    "pdf_intent": "print",
    "raster": None,
    "include_bleed": True,
    "include_marks": True,
    "embed_fonts": True,
}


def finalize_mailer_revision_with_saved_profile(client: TestClient) -> str:
    """Mailer revision whose scene carries a saved print profile — the
    'set up once, reuse forever' shape bulk runs resolve by name."""
    document_id = "doc_g8_mailer"
    scene = mailer_revision_scene_draft(document_id)
    scene["export_profiles"] = [dict(PRINT_RUN_PROFILE)]
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


def test_instance_derivation_with_saved_print_profile(client: TestClient) -> None:
    # A saved document profile drives the bulk artifact through the same
    # print pipeline as an interactive download: bleed, marks, print boxes,
    # embedded fonts, and the print-ready report.
    revision_id = finalize_mailer_revision_with_saved_profile(client)
    logo = upload_logo_asset(client)
    binding_set_id = stored_binding(client, "nominal", logo["id"])

    response = client.post(
        f"/template-revisions/{revision_id}/instances",
        json={
            "binding_set_id": binding_set_id,
            "export_profile_name": "print_run",
        },
    )
    assert response.status_code == 200, response.text
    instance = response.json()
    assert instance["status"] == "derived"
    pdfs = [a for a in instance["artifacts"] if a["format"] == "pdf"]
    assert len(pdfs) == 1, instance["artifacts"]
    pdf = pdfs[0]
    assert pdf["profile_name"] == "print_run"
    assert pdf.get("error") is None, pdf
    assert pdf["print_ready"]["status"] != "fail"

    # D4: the derive artifact is written into this workspace's engine cache (and registered
    # durably at the same moment — see the cache-wipe rehydration test).
    cache_dir = Path(client.app.state.engine_cache_root) / os.environ["LUMEN_DEV_WORKSPACE_ID"]
    pdf_bytes = (cache_dir / pdf["relative_path"]).read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"/TrimBox" in pdf_bytes, "print finalize expected"
    assert b"FontFile2" in pdf_bytes, "embedded subset fonts expected"


def test_instance_derivation_rejects_bad_profile_requests(
    client: TestClient,
) -> None:
    revision_id = finalize_mailer_revision_with_saved_profile(client)
    logo = upload_logo_asset(client)
    binding_set_id = stored_binding(client, "nominal", logo["id"])

    both = client.post(
        f"/template-revisions/{revision_id}/instances",
        json={
            "binding_set_id": binding_set_id,
            "export_profile": dict(PRINT_RUN_PROFILE),
            "export_profile_name": "print_run",
        },
    )
    assert both.status_code == 422
    assert both.json()["detail"]["code"] == "export_profile.ambiguous_source"

    unknown = client.post(
        f"/template-revisions/{revision_id}/instances",
        json={"binding_set_id": binding_set_id, "export_profile_name": "ghost"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "export_profile.not_found"

    formatless = client.post(
        f"/template-revisions/{revision_id}/instances",
        json={
            "binding_set_id": binding_set_id,
            "export_profile": {"name": "mystery", "include_bleed": True},
        },
    )
    assert formatless.status_code == 422
    assert formatless.json()["detail"]["code"] == "export_profile.format_required"


def test_batch_with_print_profile_persists_profile_and_error_codes(
    client: TestClient,
) -> None:
    revision_id = finalize_mailer_revision(client)
    logo = upload_logo_asset(client)
    ids = [
        stored_binding(client, "nominal", logo["id"]),
        stored_binding(client, "worst_case", logo["id"]),
    ]

    response = client.post(
        f"/template-revisions/{revision_id}/batches",
        json={
            "binding_set_ids": ids,
            "export_formats": [],
            "export_profile": dict(PRINT_RUN_PROFILE),
            "chunk_size": 2,
        },
    )
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["status"] == "completed"
    assert batch["export_profile"]["name"] == "print_run"

    by_binding = {entry["binding_set_id"]: entry for entry in batch["manifest"]}
    derived = by_binding["bind_acme_dr_sharma"]
    assert derived["status"] == "derived"
    assert derived["error_codes"] == []
    pdf = next(a for a in derived["artifacts"] if a["format"] == "pdf")
    assert pdf["profile_name"] == "print_run"
    assert pdf["print_ready"]["status"] != "fail"

    # The failed derivation names its why directly in the manifest.
    failed = by_binding["bind_meridian_dr_whitmore"]
    assert failed["status"] == "failed"
    assert failed["error_codes"], "failed instances must surface error codes"

    # The profile survives persistence (resume reads it from the row).
    loaded = client.get(f"/batches/{batch['batch_id']}").json()
    assert loaded["export_profile"]["name"] == "print_run"


def test_batch_with_bleed_profile_fails_fast_on_bleedless_template(
    client: TestClient,
) -> None:
    # Fail-fast at copy zero: a bleed-requesting profile against a template
    # with no bleed geometry would print-not-ready EVERY instance.
    document_id = "doc_g8_mailer"
    scene = mailer_revision_scene_draft(document_id)
    scene["pages"]["page_mailer"]["bleed"] = None
    created = client.post(
        "/documents", json={"document_id": document_id, "scene": scene}
    )
    assert created.status_code == 200, created.text
    assert (
        client.post(
            f"/documents/{document_id}/finalize",
            json={"template_revision_id": "tmpl_mailer_v1"},
        ).status_code
        == 200
    )
    logo = upload_logo_asset(client)
    binding_set_id = stored_binding(client, "nominal", logo["id"])

    response = client.post(
        "/template-revisions/tmpl_mailer_v1/batches",
        json={
            "binding_set_ids": [binding_set_id],
            "export_profile": dict(PRINT_RUN_PROFILE),
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "batch.template_not_print_ready"


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


def test_instance_preview_renders_worst_case_read_only(client: TestClient) -> None:
    # The preview endpoint is stateless: a draft scene is treated as a
    # finalized snapshot, derived, and rendered; nothing persists.
    scene = mailer_revision_scene_draft("doc_preview")
    binding = binding_fixture_payload("worst_case")
    binding["values"]["account.logo"]["asset_id"] = "asset_placeholder_logo"

    response = client.post(
        "/instances/preview",
        json={"scene": scene, "binding_set": binding, "format": "svg"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    # Worst-case headline cannot fit even at min font: the preview is
    # honest about it.
    assert payload["status"] == "failed"
    assert payload["fit_report"]["status"] == "overflow"
    headline = next(
        entry
        for entry in payload["fit_report"]["slots"]
        if entry["slot_key"] == "contact.full_name"
    )
    assert headline["verdict"]["kind"] == "overflow"
    # Failed instances skip export; no artifact is returned.
    assert payload["artifact"] is None

    # A nominal preview renders the artifact inline.
    nominal = binding_fixture_payload("nominal")
    nominal["values"]["account.logo"]["asset_id"] = "asset_placeholder_logo"
    response = client.post(
        "/instances/preview",
        json={"scene": scene, "binding_set": nominal, "format": "svg"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fit_report"]["status"] == "fits"
    assert payload["artifact"]["format"] == "svg"
    assert "Dr. Priya Sharma" in payload["artifact"]["content"]
