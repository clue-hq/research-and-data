"""Human structured edits preserve pinned effective type and exact undo."""

from copy import deepcopy
from uuid import uuid4

import pytest
from lumen_api.main import create_app
from py_lumen_config import settings

from conftest import make_client


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False)
    return make_client(create_app(tmp_path / "engine-cache"))


def authored_document(client, *, publish_kit=True):
    core = client.app.state.core
    kit = core.platform_default_brand_kit()
    kit["id"], kit["version"] = "pinned_text_repair", 7
    if publish_kit:
        for version in (7, 8):
            published = deepcopy(kit)
            published["version"] = version
            response = client.post("/brand-kits", json={"brand_kit": published, "source": "manual"})
            assert response.status_code == 200, response.text
    scene = core.compile_dsl_into_scene(
        core.new_scene(f"doc_{uuid4().hex[:12]}", "Pinned typography edit", medium="ad"),
        "page square size(1080,1080,px)\n"
        '  support text "A bounded repair" s(800,hug) font("Raw Fallback",11,300,left) '
        "style($type.body) lh(1.35) ls(0.9)\n"
        '  other text "Leave this authored node alone" s(800,hug) style($type.body)',
    )["scene"]
    scene = core.apply_operations(
        scene, [{"kind": "set_brand_kit_ref", "brand_kit_id": kit["id"], "version": kit["version"]}]
    )["scene"]
    response = client.post("/documents", json={"title": "Pinned typography edit", "scene": scene})
    assert response.status_code == 200, response.text
    return response.json()["document"]["id"], scene, kit


def typography(core, scene, kit):
    response = core.preflight_scene(scene, kit)
    assert not response["preflight"]["has_errors"]
    text = response["scene"]["nodes"]["support"]["kind"]
    return {
        field: text[field]
        for field in (
            "font_family",
            "font_size",
            "font_weight",
            "line_height",
            "letter_spacing",
        )
    }


def edit_request(patch):
    return {
        "edit": {
            "kind": "modify",
            "target": {"kind": "node", "id": "support"},
            "patch": {"kind": "node", "value": patch},
        },
        "actor": {"kind": "human"},
        "source": "editor",
    }


FILL = {
    "fills": {
        "kind": "set",
        "value": [
            {
                "id": "human_fill",
                "paint": {"kind": "solid", "color": {"kind": "hex", "value": "#123456"}},
            }
        ],
    }
}


@pytest.mark.parametrize("patch", [FILL, {"text": {"font_size": {"kind": "set", "value": 33.5}}}])
def test_http_edit_preserves_pinned_effective_type_and_undo(client, patch):
    document_id, authored, kit = authored_document(client)
    expected = typography(client.app.state.core, authored, kit)
    assert authored["nodes"]["support"]["kind"]["line_height"] != expected["line_height"]
    if "text" in patch:
        expected["font_size"] = 33.5
    response = client.post(f"/documents/{document_id}/edits", json=edit_request(patch))
    assert response.status_code == 200, response.text
    saved = client.get(f"/documents/{document_id}").json()["scene"]
    assert typography(client.app.state.core, saved, kit) == expected
    assert saved["nodes"]["other"] == authored["nodes"]["other"]
    undo = client.post(f"/documents/{document_id}/undo", json={})
    assert undo.status_code == 200, undo.text
    assert client.get(f"/documents/{document_id}").json()["scene"] == authored


def test_http_edit_refuses_unavailable_pinned_authority_without_history(client):
    document_id, authored, _ = authored_document(client, publish_kit=False)
    response = client.post(f"/documents/{document_id}/edits", json=edit_request(FILL))
    assert response.status_code == 404, response.text
    assert client.get(f"/documents/{document_id}").json()["scene"] == authored
    assert client.get(f"/documents/{document_id}/operations").json() == []
