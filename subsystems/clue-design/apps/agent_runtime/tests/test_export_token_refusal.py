"""Export refuses unresolved token PAINTS (A1a ordering follow-up).

Token resolution happens canonically in `preflight_design` — its ordered side
effects (retokenize on the authored scene, the `authored_scene.json` snapshot
the fidelity eval reads, governance) must not be skipped. So export does NOT
auto-resolve; it REFUSES (mirroring the view("preview") staleness contract) when
the working scene still carries token paints, which would otherwise render the
engine's magenta LUME0213 sentinel (crates/lumen-skia raster, commit 925bdec).
"""

from __future__ import annotations

import json
from dataclasses import replace

from lumen_agent.tools.substrate import (
    LumenDesignTools,
    _paint_token_refs,
    _unresolved_paint_refs,
)

from agent_fixtures import FakeCoreClient, runtime_config


# --- scene builders ---------------------------------------------------------


def _token_scene() -> dict:
    return {
        "meta": {"id": "doc", "title": "t"},
        "pages": {
            "p1": {
                "id": "p1",
                "children": ["headline", "rule"],
                "size": {"width": 1080.0, "height": 1080.0},
                "background": [
                    {"id": "bg", "paint": {"kind": "token", "token": "surface.brand"}}
                ],
            }
        },
        "nodes": {
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Hi"},
                "children": [],
                "fills": [
                    {"id": "f1", "paint": {"kind": "token", "token": "text.primary"}}
                ],
                "strokes": [],
            },
            "rule": {
                "id": "rule",
                "kind": {"kind": "rect"},
                "children": [],
                "fills": [],
                "strokes": [
                    {
                        "id": "s1",
                        "paint": {"kind": "token", "token": "accent.primary"},
                        "width": 2.0,
                    }
                ],
            },
        },
        "slots": {},
        "assets": {},
    }


def _literal_scene() -> dict:
    return {
        "meta": {"id": "doc", "title": "t"},
        "pages": {
            "p1": {
                "id": "p1",
                "children": ["headline"],
                "size": {"width": 1080.0, "height": 1080.0},
                "background": [
                    {
                        "id": "bg",
                        "paint": {
                            "kind": "solid",
                            "color": {"kind": "hex", "value": "#fffaf2"},
                        },
                    }
                ],
            }
        },
        "nodes": {
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Hi"},
                "children": [],
                "fills": [
                    {
                        "id": "f1",
                        "paint": {
                            "kind": "solid",
                            "color": {"kind": "hex", "value": "#193235"},
                        },
                    }
                ],
                "strokes": [],
            }
        },
        "slots": {},
        "assets": {},
    }


def _kit() -> dict:
    return {
        "id": "brand_kit_test",
        "version": "1",
        "name": "Test",
        "approval_status": "approved",
        "modes": {
            "defaults": {
                "theme": "light",
                "density": "comfortable",
                "accessibility": "standard",
                "medium": "digital",
            }
        },
        "tokens": {},
    }


class _ResolvingCoreClient(FakeCoreClient):
    """A fake whose `preflight_scene` performs the engine's job for THIS test:
    replace token paints with literal hex (resolution-once), mirroring the real
    helper's resolved-scene response that `_replace_scene_from_core_response`
    swaps in."""

    _RESOLVED = {
        "surface.brand": "#111827",
        "text.primary": "#111827",
        "text.inverse": "#FFFFFF",
        "accent.primary": "#0F766E",
    }

    def preflight_scene(self, scene, brand_kit, brand_fonts=None):
        updated = json.loads(json.dumps(scene))

        def resolve(entries):
            for entry in entries or []:
                paint = entry.get("paint") or {}
                if paint.get("kind") == "token":
                    hexv = self._RESOLVED.get(paint.get("token"), "#000000")
                    entry["paint"] = {
                        "kind": "solid",
                        "color": {"kind": "hex", "value": hexv},
                    }

        for page in (updated.get("pages") or {}).values():
            resolve(page.get("background"))
        for node in (updated.get("nodes") or {}).values():
            resolve(node.get("fills"))
            resolve(node.get("strokes"))
        meta = updated.setdefault("meta", {})
        if not meta.get("brand_kit"):
            meta["brand_kit"] = {"id": brand_kit["id"], "version": brand_kit["version"]}
        return {
            "scene": updated,
            "diagnostics": [],
            "preflight": {
                "has_errors": False,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }


def _tools(tmp_path, monkeypatch, core=FakeCoreClient, kit=None):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", core)
    config = runtime_config(tmp_path)
    if kit is not None:
        config = replace(config, brand_kit=kit, brand_kit_source="document")
    return LumenDesignTools(config, "Make a poster")


def _trace_events(tools) -> list[str]:
    path = tools.trace_dir / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["event"] for line in path.read_text().splitlines() if line]


# --- scanner unit tests -----------------------------------------------------


def test_paint_token_refs_direct_token_paint():
    assert _paint_token_refs({"kind": "token", "token": "surface.brand"}) == [
        "surface.brand"
    ]


def test_paint_token_refs_solid_over_token_color():
    paint = {"kind": "solid", "color": {"kind": "token", "token": "text.primary"}}
    assert _paint_token_refs(paint) == ["text.primary"]


def test_paint_token_refs_gradient_stops():
    paint = {
        "kind": "linear_gradient",
        "angle": 90.0,
        "stops": [
            {"color": {"kind": "token", "token": "a.b"}, "position": 0.0},
            {"color": {"kind": "hex", "value": "#fff"}, "position": 0.5},
            {"color": {"kind": "token", "token": "c.d"}, "position": 1.0},
        ],
    }
    assert _paint_token_refs(paint) == ["a.b", "c.d"]


def test_paint_token_refs_resolved_paint_is_empty():
    assert _paint_token_refs({"kind": "solid", "color": {"kind": "hex", "value": "#000"}}) == []
    assert _paint_token_refs({"kind": "solid", "color": {"kind": "oklch", "l": 0.5, "c": 0.1, "h": 20.0, "alpha": 1.0}}) == []


def test_paint_token_refs_tolerates_malformed():
    assert _paint_token_refs(None) == []
    assert _paint_token_refs("nope") == []
    assert _paint_token_refs({"kind": "token"}) == []  # no token key
    assert _paint_token_refs({"kind": "token", "token": ""}) == []  # empty
    assert _paint_token_refs({"stops": "not-a-list"}) == []


def test_unresolved_paint_refs_covers_page_fill_stroke_text():
    refs = _unresolved_paint_refs(_token_scene())
    assert ("page:p1", "surface.brand") in refs
    assert ("headline", "text.primary") in refs  # text color lives on node fills
    assert ("rule", "accent.primary") in refs
    assert len(refs) == 3


def test_unresolved_paint_refs_literal_scene_is_clean():
    assert _unresolved_paint_refs(_literal_scene()) == []


def test_unresolved_paint_refs_tolerates_malformed_scene():
    assert _unresolved_paint_refs(None) == []
    assert _unresolved_paint_refs({}) == []
    assert _unresolved_paint_refs({"pages": [1, 2], "nodes": "x"}) == []
    assert _unresolved_paint_refs(
        {"pages": {"p": {"background": [None, 5, {"paint": None}]}}, "nodes": {"n": None}}
    ) == []


# --- refusal behaviour ------------------------------------------------------


def test_export_preview_refuses_token_paint_scene(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    tools.scene = _token_scene()

    result = json.loads(tools.export_preview("png"))
    export = result["export"]
    assert export["status"] == "error"
    assert export["artifacts"] == []
    errors = " ".join(export["validation_errors"])
    assert "preflight_design" in errors
    assert "surface.brand" in errors
    assert "text.primary" in errors
    assert "accent.primary" in errors
    # loud refusal recorded; the refusal returns before any engine render.
    assert "export_refused_unresolved_tokens" in _trace_events(tools)
    assert tools.latest_export_summary is None


def test_export_preview_succeeds_after_real_preflight(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch, core=_ResolvingCoreClient, kit=_kit())
    tools.scene = _token_scene()
    tools.seeded_from_initial_scene = True  # skip retokenize/logo placement path

    # Before preflight: refused.
    assert json.loads(tools.export_preview("png"))["export"]["status"] == "error"

    tools.preflight_design()
    # Resolution consumed the token paints.
    assert _unresolved_paint_refs(tools.scene) == []

    after = json.loads(tools.export_preview("png"))["export"]
    assert after["status"] == "ok"
    assert after["artifacts"]


def test_export_preview_literal_scene_exports_directly(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    tools.scene = _literal_scene()

    result = json.loads(tools.export_preview("png"))["export"]
    assert result["status"] == "ok"
    assert result["artifacts"]
    assert "export_refused_unresolved_tokens" not in _trace_events(tools)


def test_export_preview_bundle_refuses_token_paint_scene(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    tools.scene = _token_scene()

    payload = json.loads(tools.export_preview_bundle(critic_format="png"))
    reviewer = payload["reviewer"]
    assert reviewer["status"] == "error"
    assert reviewer["artifacts"] == []
    errors = " ".join(reviewer["validation_errors"])
    assert "preflight_design" in errors
    assert "surface.brand" in errors
    assert tools.latest_preview_bundle is None
    assert "export_refused_unresolved_tokens" in _trace_events(tools)


def test_export_preview_bundle_succeeds_on_literal_scene(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    tools.scene = _literal_scene()

    payload = json.loads(tools.export_preview_bundle(critic_format="png"))
    assert payload["reviewer"]["status"] == "ok"
    assert payload["reviewer"]["artifacts"]
