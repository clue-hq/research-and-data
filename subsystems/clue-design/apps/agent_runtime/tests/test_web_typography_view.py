"""Source typography is readable across viewports without another render or a guess."""

import copy
import json

import pytest
from lumen_agent.tools.web_substrate import make_web_view_tool
from test_web_substrate import _bare_tools
from test_web_typography_reference import layouts, sample


def read(tools, target="typography:node:source", *, can_render=True):
    result = make_web_view_tool(tools, can_render=can_render).invoke({"target": target})
    assert result[0]["text"].startswith("{"), "Native view must serve a typography report"
    return json.loads(result[0]["text"])


def measured(tools):
    layouts(tools)
    for layout in tools._layout_by_width.values():
        for node in layout["nodes"]:
            node.update(kind="fragment", fragment_id="frag_source", complete=True, omitted={})


def test_native_view_combines_source_values_without_changing_or_rendering_the_page(tmp_path):
    tools = _bare_tools(tmp_path)
    measured(tools)
    before = copy.deepcopy((tools.web_doc, tools._layout_by_width))
    result = read(tools)
    assert result["status"] == "observed"
    assert result["complete"] is True
    assert result["measurements_complete"] is True
    assert result["reference_node_id"] == "source"
    assert result["fragment_id"] == "frag_source"
    role = result["texts"][0]
    assert role["reference_path"] == ":nth-child(1)"
    assert [role["widths"][str(w)]["sample"]["font_size"] for w in (1440, 768, 375)] == [
        "48px", "48px", "32px",
    ]
    assert role["widths"]["1440"]["sample"]["glyph_faces"] == [
        ["Example", "Example-Regular", True],
    ]
    assert (tools.web_doc, tools._layout_by_width) == before
    assert tools._typography_references.bindings == []


@pytest.mark.parametrize("damage", ["missing", "stale", "other_document", "duplicate_node"])
def test_mixed_or_ambiguous_measurements_cannot_look_like_a_current_source(tmp_path, damage):
    tools = _bare_tools(tmp_path)
    measured(tools)
    if damage == "missing":
        del tools._layout_by_width[375]
    elif damage == "stale":
        tools._doc_version += 1
    elif damage == "other_document":
        tools._layout_by_width[375]["document_id"] = "other"
    else:
        tools._layout_by_width[375]["nodes"].append(
            copy.deepcopy(tools._layout_by_width[375]["nodes"][0])
        )
    result = read(tools, can_render=False)
    assert result["status"] == "error"
    assert "texts" not in result
    assert "render_web_preview()" not in result["message"]


def test_pagination_preserves_all_paths_and_reports_capture_omissions_and_font_gaps(tmp_path):
    tools = _bare_tools(tmp_path)
    measured(tools)
    for layout in tools._layout_by_width.values():
        node = layout["nodes"][0]
        node["texts"] = [dict(sample(), rendered_path=f":nth-child({i})") for i in range(1, 11)]
    phone = tools._layout_by_width[375]["nodes"][0]
    phone.update(complete=False, omitted={"texts": 2})
    phone["texts"][0]["font_usage"] = {"status": "unavailable"}
    first = read(tools)
    assert len(first["texts"]) == 8
    assert first["next_target"] == "typography:node:source:offset:8"
    assert first["complete"] is False
    assert first["capture_coverage"]["375"]["omitted"] == {"texts": 2}
    assert first["texts"][0]["widths"]["375"]["gaps"] == ["glyph_faces_unmeasured"]
    second = read(tools, first["next_target"])
    assert len(second["texts"]) == 2
    assert second["next_target"] is None
    assert second["complete"] is False  # end of this view is not complete source capture
    assert [x["reference_path"] for x in first["texts"] + second["texts"]] == [
        f":nth-child({i})" for i in range(1, 11)
    ]
    assert read(tools, "typography:node:source:offset:11")["status"] == "error"


def test_hidden_source_is_not_fabricated_as_visible_typography(tmp_path):
    tools = _bare_tools(tmp_path)
    measured(tools)
    tools._layout_by_width[375]["nodes"][0]["texts"][0]["css_visible"] = False
    role = read(tools)["texts"][0]["widths"]["375"]
    assert role["sample"] == {"tag": "h2", "css_visible": False}
    assert role["status"] == "hidden"


def test_last_page_does_not_hide_incomplete_measurements_on_an_earlier_page(tmp_path):
    tools = _bare_tools(tmp_path)
    measured(tools)
    for layout in tools._layout_by_width.values():
        layout["nodes"][0]["texts"] = [
            dict(sample(), rendered_path=f":nth-child({i})") for i in range(1, 10)
        ]
    tools._layout_by_width[375]["nodes"][0]["texts"][0]["font_usage"] = {}
    result = read(tools, "typography:node:source:offset:8")
    assert result["next_target"] is None
    assert result["complete"] is False
    assert result["measurements_complete"] is False


def test_complete_measurement_is_not_a_claim_that_this_slice_contains_the_whole_source(tmp_path):
    tools = _bare_tools(tmp_path)
    measured(tools)
    for layout in tools._layout_by_width.values():
        layout["nodes"][0]["texts"] = [
            dict(sample(), rendered_path=f":nth-child({i})") for i in range(1, 10)
        ]
    result = read(tools, "typography:node:source:offset:8")
    assert result["measurements_complete"] is True
    assert result["next_target"] is None
    assert result["complete"] is False
