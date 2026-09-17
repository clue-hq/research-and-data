"""Read-only render selection must match normal export, without persisting a rebind."""

import copy
from types import SimpleNamespace

from lumen_api import main
from lumen_api.database import NotFoundError


def kit(version=1):
    return {"id": "kit", "version": version, "modes": {"defaults": {"theme": "light"}}}


def document():
    return {
        "id": "doc",
        "current_version": 3,
        "scene": {"meta": {"id": "doc", "medium": "ad", "brand_kit": {"id": "kit", "version": 1}}},
        "effective_brand_mode": {"values": {"theme": "dark"}},
        "effective_brand_kit": {"id": "historical", "version": 42},
    }


def test_read_context_uses_attached_kit_and_current_export_mode_without_mutation():
    doc = document()
    doc["brand_kit"] = kit()
    before = copy.deepcopy(doc)
    ctx = main.document_render_context(None, None, doc)
    assert ctx["brand_kit"] == doc["brand_kit"]
    assert ctx["source"] == "document"
    assert ctx["mode"] == {"values": {"theme": "dark", "medium": "digital"}}
    assert ctx["scene_brand_ref"] == {"id": "kit", "version": 1}
    assert ctx["diagnostics"] == []
    assert doc == before
    doc["effective_brand_mode"] = {"values": {"theme": "light"}}
    assert main.document_render_context(None, None, doc)["context_key"] != ctx["context_key"]


def test_attached_mismatch_is_visible_and_never_silently_rebound():
    doc = document()
    doc["brand_kit"] = kit(2)
    ctx = main.document_render_context(None, None, doc)
    assert ctx["brand_kit"]["version"] == 2
    assert ctx["scene_brand_ref"]["version"] == 1
    assert ctx["diagnostics"][0]["code"] == "LUMB0101"


def test_missing_exact_pin_retains_export_fallback_provenance_but_is_invalid():
    def missing(*args):
        raise NotFoundError("brand_kit", "kit@1")

    core = SimpleNamespace(platform_default_brand_kit=lambda: {"id": "default", "version": 1})
    repo = SimpleNamespace(require_brand_kit=missing)
    ctx = main.document_render_context(core, repo, document())
    assert ctx["source"] == "platform_default"
    assert ctx["diagnostics"][0]["code"] == "LUMB0101"


def test_unpinned_default_is_explicit_and_json_changes_change_identity():
    doc = document()
    doc["scene"]["meta"]["brand_kit"] = None
    selected = kit()
    core = SimpleNamespace(platform_default_brand_kit=lambda: selected)
    first = main.document_render_context(core, None, doc)
    assert first["source"] == "platform_default"
    assert first["diagnostics"] == []
    selected["name"] = "changed inline JSON at same pin"
    assert main.document_render_context(core, None, doc)["context_key"] != first["context_key"]


def test_scene_read_route_projects_context_without_rewriting_scene_or_history(
    tmp_path, monkeypatch
):
    doc = document()
    doc.update(brand_kit=kit(), undo_stack=[{"batch_id": "original"}], redo_stack=[])
    original = copy.deepcopy(doc)
    monkeypatch.setattr(main, "require_document", lambda repo, document_id: doc)
    app = main.create_app(tmp_path / "engine-cache")
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/documents/{document_id}"
        and "GET" in getattr(route, "methods", [])
    )
    response = route.endpoint("doc", repo=None)
    assert response["render_context"]["brand_kit"] == kit()
    assert "brand_kit" not in response
    assert response["scene"] == original["scene"]
    assert response["undo_stack"] == original["undo_stack"]
    assert doc == original
    doc["doc_kind"] = "web"
    doc["scene"] = {"pages": {}}
    response = route.endpoint("doc", repo=SimpleNamespace(list_web_fragments=lambda: []))
    assert "render_context" not in response
