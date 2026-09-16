"""Feed observations describe current native typography, without certifying readability."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import runtime_config
from lumen_agent.native_copy import observe_native_text
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools.view import _normalize_image_bytes, _preview_text_table
from test_scene_preview_proxy import _decode, _view


@pytest.fixture
def scene_runtime(tmp_path, monkeypatch):
    from lumen_agent.tools import substrate
    from lumen_api import core as core_module

    root = Path(__file__).resolve().parents[3]
    helper = root / "target/release/lumen-api-helper"
    if not helper.exists():
        pytest.skip("release helper not built")
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(helper))
    core = core_module.CoreClient(repo_root=root)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    kit = core.platform_default_brand_kit()
    kit["tokens"]["numbers"]["type.size.sm"]["value"]["default"]["value"] = 17.0
    config = replace(runtime_config(tmp_path), scene_skill_bundle="candidate", brand_kit=kit)

    def prepare(dsl, *, preflight=True):
        tools = LumenDesignTools(config, "Observe native copy")
        assert json.loads(tools.compile_dsl_block(dsl))["compile"]["status"] == "ok"
        if preflight:
            json.loads(tools.preflight_design())
        assert json.loads(tools.export_preview("png"))["export"]["status"] == "ok"
        return tools, core

    return prepare


def _caption(content):
    return next(
        block["text"]
        for block in content
        if block["type"] == "text" and "source_preview_sha256" in block["text"]
    )


@pytest.mark.parametrize(
    ("page", "preview_em", "proxy_em"),
    [
        ("size(1080,1080,px)", "17.00", "5.67"),
        # The core normalizes this physical page to 720 x 360 pt before rasterizing.
        ("size(254,127,mm)", "22.67", "8.50"),
        ("size(10,5,in)", "22.67", "8.50"),
        # Rounded proxy height (188) matters: using only 360/width gives 5.10.
        ("size(1200,628,px)", "17.00", "5.09"),
    ],
)
def test_actual_resolved_font_size_maps_to_the_actual_proxy_without_another_call(
    scene_runtime,
    monkeypatch,
    page,
    preview_em,
    proxy_em,
):
    tools, core = scene_runtime(
        f"page square {page}\n"
        '  support text "Practical support" p(20,20) s(400,80) '
        "style($type.body) font_size($type.size.sm) fill($text.primary)\n"
    )
    assert tools.scene["nodes"]["support"]["kind"]["font_size"] == 17.0
    assert "font_size_token" not in tools.scene["nodes"]["support"]["kind"]
    scene, receipt = copy.deepcopy(tools.scene), copy.deepcopy(tools._preview_receipt)
    raw = Path(tools.latest_export_summary["artifacts"][0]["path"]).read_bytes()

    def no_new_core_or_provider_call(*args, **kwargs):
        pytest.fail("view must use its already-resolved scene and already-rendered pixels")

    monkeypatch.setattr(core, "_run", no_new_core_or_provider_call)
    content = _view(tools)
    caption = _caption(content)

    assert f"| support | Practical support | {preview_em} | {proxy_em} |" in caption
    assert "resolved em size" in caption and "glyph" in caption
    assert "clipping" in caption.lower() and "occlusion" in caption
    assert len(content) == 4 and _decode(content[1]) == _normalize_image_bytes(raw)[0]
    assert tools.scene == scene and tools._preview_receipt == receipt
    assert tools._current_preview_receipt() == receipt


def test_table_follows_the_rendered_page_and_reports_hidden_and_transformed_text(scene_runtime):
    tools, _ = scene_runtime("""page first size(1080,1080,px)
  other_page text "Only on first page" p(20,20) s(400,80) font_size($type.size.sm)
page last size(1080,1080,px)
  visible text "Visible copy" p(20,20) s(400,80) font_size($type.size.sm)
  hidden_group fr p(20,100) s(400,100) opacity(0)
    invisible text "Hidden copy" s(400,80) font_size($type.size.sm)
  rotated_group fr p(20,240) s(400,100) rot(15)
    transformed text "Rotated copy" s(400,80) font_size($type.size.sm)
""")
    assert tools.latest_export_summary["artifacts"][-1]["page_id"] == "last"
    caption = _caption(_view(tools))
    assert "| visible | Visible copy | 17.00 | 5.67 |" in caption
    assert "other_page" not in caption and "invisible" not in caption
    assert "1 zero-opacity" in caption
    assert "| transformed | Rotated copy | unavailable" in caption
    assert "transform" in caption


def test_unresolved_font_size_is_not_presented_as_measured_from_its_fallback(scene_runtime):
    tools, _ = scene_runtime("""page square size(1080,1080,px)
  support text "Unresolved copy" p(20,20) s(400,80) font_size($type.size.missing)
""")
    assert tools.scene["nodes"]["support"]["kind"]["font_size_token"] == "type.size.missing"
    caption = _caption(_view(tools))
    assert "| support | Unresolved copy | unavailable" in caption
    assert "unresolved typography" in caption
    assert "| 16.00 |" not in caption


def test_export_without_current_preflight_does_not_claim_resolved_metrics(scene_runtime):
    tools, _ = scene_runtime(
        """page square size(1080,1080,px)
  support text "Not preflighted" p(20,20) s(400,80) font_size(17)
""",
        preflight=False,
    )
    caption = _caption(_view(tools))
    assert "native text metrics unavailable" in caption
    assert "current preflight" in caption
    assert "| 17.00 |" not in caption


def test_old_png_fallback_after_svg_export_has_no_current_text_measurement(scene_runtime):
    tools, _ = scene_runtime("""page square size(1080,1080,px)
  support text "First copy" p(20,20) s(400,80) font_size($type.size.sm)
""")
    assert (
        json.loads(tools.compile_dsl_block("#support font_size($type.size.xl)"))["compile"][
            "status"
        ]
        == "ok"
    )
    assert json.loads(tools.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(tools.export_preview("svg"))["export"]["status"] == "ok"
    caption = _caption(_view(tools))
    assert "native text metrics unavailable" in caption
    assert "page association" in caption
    assert "| 24.00 |" not in caption


def test_repaired_text_uses_new_resolution_after_fresh_render(scene_runtime):
    tools, _ = scene_runtime("""page square size(1080,1080,px)
  support text "Repair this size" p(20,20) s(400,80) font_size($type.size.sm)
""")
    assert "| 17.00 | 5.67 |" in _caption(_view(tools))
    assert (
        json.loads(tools.compile_dsl_block("#support font_size($type.size.xl)"))["compile"][
            "status"
        ]
        == "ok"
    )
    assert "STALE" in _view(tools)[0]["text"]
    assert json.loads(tools.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(tools.export_preview("png"))["export"]["status"] == "ok"
    caption = _caption(_view(tools))
    assert "| support | Repair this size | 24.00 | 8.00 |" in caption
    assert "| 17.00 |" not in caption


def test_pinned_text_escapes_hidden_transformed_ancestor_in_actual_raster_pass(scene_runtime):
    tools, _ = scene_runtime("""page square size(1080,1080,px)
  parent fr p(20,20) s(500,200) opacity(0) rot(15)
    support text "Pinned copy" s(400,80) font_size($type.size.sm)
""")
    assert (
        json.loads(tools.compile_dsl_block("detach_to_freehand(support)"))["compile"]["status"]
        == "ok"
    )
    assert tools.scene["nodes"]["support"]["position_mode"] == "absolute"
    assert json.loads(tools.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(tools.export_preview("png"))["export"]["status"] == "ok"
    caption = _caption(_view(tools))
    assert "| support | Pinned copy | 17.00 | 5.67 |" in caption
    assert "0 zero-opacity" in caption


@pytest.mark.parametrize("unit", [None, "px", "mm", "in"])
def test_unnormalized_page_units_are_never_guessed_from_authored_dimensions(unit):
    # Import/historical JSON without the core's canonical unit must not gain
    # invented dimensions, even if it has plausible numbers and a numeric font.
    scene = {"pages": {"page": {"size": {"width": 1080, "height": 1080, "unit": unit}}}}
    caption = _preview_text_table(scene, "page", 1080, 360, resolved=True)
    assert "native text metrics unavailable" in caption
    assert "canonical page dimensions" in caption


def test_unresolved_opacity_does_not_certify_a_text_node_as_hidden():
    scene = {
        "pages": {
            "page": {"size": {"width": 1080, "height": 1080, "unit": "pt"}, "children": ["copy"]}
        },
        "nodes": {
            "copy": {
                "opacity": 0,
                "opacity_token": "opacity.missing",
                "kind": {"kind": "text", "content": "Unknown opacity", "font_size": 17},
            }
        },
    }
    caption = _preview_text_table(scene, "page", 1080, 360, resolved=True)
    assert "| copy | Unknown opacity | unavailable (unresolved opacity) | unavailable |" in caption
    assert "0 zero-opacity" in caption


def _line_scene():
    # Measured vertical geometry from the failed Clue grouping review, with
    # neutral copy. The allocated bottom is 320; the last painted line ends
    # at 284.5. Treating 320 as the text edge understates the gap by 35.5pt.
    return {
        "pages": {"page": {
            "size": {"width": 1080, "height": 1080, "unit": "pt"},
            "children": ["support"],
        }},
        "nodes": {"support": {
            "kind": {"kind": "text", "content": "Supporting message", "font_size": 21},
            "computed": {
                "layout_bounds": {"x": 64, "y": 252, "width": 820, "height": 68},
                "text_lines": [{"x": 64, "y": 252.5, "width": 696.42, "height": 32}],
            },
        }},
    }


def test_review_evidence_distinguishes_painted_line_edges_from_allocated_box_slack():
    scene = _line_scene()
    row = observe_native_text(scene, "page")["occurrences"][0]
    geometry = row.get("line_geometry")
    assert geometry is not None, "copy review omits measured line-edge evidence"
    assert geometry["status"] == "ok"
    assert geometry["line_count"] == 1
    assert geometry["line_top"] == 252.5
    assert geometry["line_bottom"] == 284.5
    assert geometry["allocated_bottom"] == 320
    assert 344 - geometry["line_bottom"] == 59.5
    caption = _preview_text_table(scene, "page", 1080, 360, resolved=True)
    assert "| support | 1 | 252.50 | 284.50 | 252.00 | 320.00 |" in caption
    assert "not pixel-tight glyph ink" in caption
    assert "page-space pt" in caption


def test_multiline_geometry_reports_full_measured_extent_not_allocated_height():
    scene = _line_scene()
    scene["nodes"]["support"]["computed"].update(
        layout_bounds={"x": 72, "y": 168, "width": 936, "height": 142},
        text_lines=[
            {"x": 72, "y": 168.125, "width": 907.32, "height": 71},
            {"x": 72, "y": 239.125, "width": 323.11, "height": 71},
        ],
    )
    geometry = observe_native_text(scene, "page")["occurrences"][0].get("line_geometry")
    assert geometry is not None
    assert geometry["line_count"] == 2
    assert geometry["line_bottom"] == 310.125
    assert 391.5 - geometry["line_bottom"] == 81.375


@pytest.mark.parametrize("invalid", [
    None, [], [{"x": 0, "y": 252, "width": 20, "height": float("nan")}],
    [{"x": 0, "y": 252, "width": 20, "height": -1}],
])
def test_missing_or_invalid_line_geometry_never_falls_back_to_allocated_box(invalid):
    scene = _line_scene()
    scene["nodes"]["support"]["computed"]["text_lines"] = invalid
    geometry = observe_native_text(scene, "page")["occurrences"][0].get("line_geometry")
    assert geometry is not None
    assert geometry["status"] == "unavailable"
    assert "line_bottom" not in geometry


def test_live_preview_and_copy_inventory_share_current_line_geometry_without_more_calls(
    scene_runtime, monkeypatch,
):
    tools, core = scene_runtime('''page square size(1080,1080,px)
  support text "A short second read" p(64,252) s(820,68) font_size(21) line_height(1.5)
''')
    scene = copy.deepcopy(tools.scene)
    receipt = copy.deepcopy(tools._preview_receipt)

    def no_new_call(*args, **kwargs):
        pytest.fail("line evidence must use the current preflight geometry")

    monkeypatch.setattr(core, "_run", no_new_call)
    row = json.loads(tools.inspect("copy_review"))["occurrences"][0]
    geometry = row.get("line_geometry")
    assert geometry is not None
    assert geometry["status"] == "ok"
    assert geometry["allocated_bottom"] == 320
    assert 280 < geometry["line_bottom"] < 290
    caption = _caption(_view(tools))
    assert (
        f"| support | 1 | {geometry['line_top']:.2f} | {geometry['line_bottom']:.2f} |"
    ) in caption
    assert tools.scene == scene and tools._preview_receipt == receipt


@pytest.mark.parametrize("transform", [{"rotation": 15}, {"skew_y": 10}, {"flip_y": True}])
def test_transformed_ancestor_does_not_report_unrotated_lines_as_visible_edges(transform):
    scene = _line_scene()
    scene["pages"]["page"]["children"] = ["parent"]
    scene["nodes"]["parent"] = {
        "kind": {"kind": "frame"}, "children": ["support"], "transform": transform,
    }
    geometry = observe_native_text(scene, "page")["occurrences"][0].get("line_geometry")
    assert geometry is not None
    assert geometry["status"] == "unavailable"
    assert "transform" in geometry["reason"]
    scene["nodes"]["support"]["position_mode"] = "absolute"
    geometry = observe_native_text(scene, "page")["occurrences"][0]["line_geometry"]
    assert geometry["status"] == "ok"
    assert geometry["line_bottom"] == 284.5
