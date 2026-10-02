"""L4 wasted-round elimination: the raster sentinel/uniform guard (D1) and the
unchanged-scene re-review fact (D2).

The PNG-black bug class is root-cause-fixed at the engine (white clear + magenta
UNRESOLVED_PAINT_SENTINEL + LUME0213) and the agent (pre-render token-paint
refusal). This suite covers the residual last-mile net: a magenta-sentinel frame
that slips the token refusal must be a HARD export error (never reviewable as
ok); a near-uniform frame is a LOUD but non-blocking warning; and re-rendering a
byte-identical scene surfaces a deterministic `unchanged` fact + trace event so
the orchestrator does not burn an author+reviewer round on identical pixels.
"""
from __future__ import annotations

import io
import json
from dataclasses import replace

from lumen_agent.tools.substrate import (
    LumenDesignTools,
    _png_uniformity_guard,
)

from agent_fixtures import FakeCoreClient, runtime_config


# --- helpers ----------------------------------------------------------------


def _png(color_fn, size=(80, 80)) -> bytes:
    """Synthesize a real, decodable PNG whose pixel at (x, y) is color_fn(x, y)."""
    from PIL import Image

    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = color_fn(x, y)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _magenta_png() -> bytes:
    return _png(lambda x, y: (255, 0, 255))


def _near_uniform_black_png() -> bytes:
    # >=99% black: only a tiny 4x4 corner (16 / 6400 px = 0.25%) is red.
    return _png(lambda x, y: (200, 0, 0) if (x < 4 and y < 4) else (0, 0, 0))


def _multicolor_png() -> bytes:
    return _png(lambda x, y: ((x * 7) % 256, (y * 7) % 256, (x + y) % 256))


def _literal_scene() -> dict:
    """A resolved scene (no token paints) so export never hits the refusal."""
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


class _PngCore(FakeCoreClient):
    """A fake whose PNG export returns a preset, real PNG (set PNG_BYTES on the
    class before constructing the tools). SVG stays a valid stub."""

    PNG_BYTES = b""

    def export_preview(
        self, scene, export_format="svg", page_ids=None, asset_store_root=None,
        brand_fonts=None,
    ):
        if export_format == "png":
            raw = type(self).PNG_BYTES
            mime = "image/png"
        else:
            raw = b"<svg></svg>"
            mime = "image/svg+xml"
        return {
            "diagnostics": [],
            "export": {
                "artifacts": [
                    {
                        "format": export_format,
                        "mime_type": mime,
                        "page_id": "p1",
                        "bytes": list(raw),
                    }
                ]
            },
        }


def _tools(tmp_path, monkeypatch, core=FakeCoreClient):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", core)
    config = runtime_config(tmp_path)
    return LumenDesignTools(config, "Make a poster")


def _trace_events(tools) -> list[str]:
    path = tools.trace_dir / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["event"] for line in path.read_text().splitlines() if line]


# --- D1 guard: pure unit -----------------------------------------------------


def test_guard_flags_magenta_sentinel_as_hard_error():
    error, warning = _png_uniformity_guard(_magenta_png())
    assert warning is None
    assert error is not None
    assert "magenta LUME0213" in error
    assert "not reviewable" in error


def test_guard_warns_on_near_uniform_black_but_does_not_error():
    error, warning = _png_uniformity_guard(_near_uniform_black_png())
    assert error is None
    assert warning is not None
    assert "raster suspicious" in warning
    assert "one uniform color" in warning


def test_guard_is_silent_on_normal_multicolor():
    assert _png_uniformity_guard(_multicolor_png()) == (None, None)


def test_guard_never_raises_on_undecodable_bytes():
    # The FakeCoreClient's stub PNG bytes are not a decodable image; the guard
    # must degrade to no-guard rather than raise into the turn.
    assert _png_uniformity_guard(b"\x89PNG\r\n\x1a\nfake") == (None, None)
    assert _png_uniformity_guard(b"") == (None, None)


# --- D1 guard: full export status flip (case a) ------------------------------


def test_export_sentinel_png_is_hard_error(tmp_path, monkeypatch):
    _PngCore.PNG_BYTES = _magenta_png()
    tools = _tools(tmp_path, monkeypatch, core=_PngCore)
    tools.scene = _literal_scene()

    export = json.loads(tools.export_preview("png"))["export"]
    assert export["status"] == "error"
    artifact = export["artifacts"][0]
    assert artifact["valid"] is False
    joined = " ".join(artifact["validation_errors"])
    assert "magenta LUME0213" in joined
    assert tools.latest_export_summary is None


# --- D1 guard: near-uniform warning, still ok (case b) -----------------------


def test_export_near_uniform_png_warns_but_stays_ok(tmp_path, monkeypatch):
    _PngCore.PNG_BYTES = _near_uniform_black_png()
    tools = _tools(tmp_path, monkeypatch, core=_PngCore)
    tools.scene = _literal_scene()

    export = json.loads(tools.export_preview("png"))["export"]
    assert export["status"] == "ok"
    artifact = export["artifacts"][0]
    assert artifact["valid"] is True
    assert artifact["validation_errors"] == []
    assert any("raster suspicious" in w for w in artifact["warnings"])


# --- D1 guard: normal multicolor, no guard text (case c) ---------------------


def test_export_multicolor_png_has_no_guard_text(tmp_path, monkeypatch):
    _PngCore.PNG_BYTES = _multicolor_png()
    tools = _tools(tmp_path, monkeypatch, core=_PngCore)
    tools.scene = _literal_scene()

    export = json.loads(tools.export_preview("png"))["export"]
    assert export["status"] == "ok"
    artifact = export["artifacts"][0]
    assert artifact["warnings"] == []
    joined = " ".join(artifact["validation_errors"])
    assert "magenta" not in joined
    assert "raster suspicious" not in joined


# --- D2 unchanged-scene re-review fact (case d) ------------------------------


def test_unchanged_scene_rerender_surfaces_fact_and_trace(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)  # FakeCoreClient: valid stub PNG bytes
    tools.scene = _literal_scene()

    # First render: nothing to compare against — no unchanged fact.
    first = json.loads(tools.export_preview_bundle(critic_format="png"))
    assert "unchanged" not in first
    assert "unchanged_rerender_recorded" not in _trace_events(tools)

    # Second render, no scene mutation in between: identical pixels → the fact.
    second = json.loads(tools.export_preview_bundle(critic_format="png"))
    assert "unchanged" in second
    assert "no new information" in second["unchanged"]
    assert "unchanged_rerender_recorded" in _trace_events(tools)

    # A mutation between renders → the next export carries NO unchanged fact.
    tools.scene["meta"]["title"] = "A changed scene"
    tools.scene_update_sources.append("structured_edit")
    third = json.loads(tools.export_preview_bundle(critic_format="png"))
    assert "unchanged" not in third
