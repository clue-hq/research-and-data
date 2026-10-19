"""Omitting reference calls or binding only a source cannot qualify authored bands."""

import copy
import json

from test_web_substrate import _bare_tools
from test_web_typography_reference import bind, layouts, sample


def page(tools):
    nodes = tools.web_doc["pages"][0]["nodes"]
    nodes["root"]["children"] = ["source", "authored"]
    for key in ("source", "authored"):
        nodes[key] = {"id": key, "kind": "fragment", "fragment_id": "frag_" + key}
    tools._cloned_section_seen = {
        "frag_source": {"composed": None}, "frag_authored": {"composed": "agent"},
    }
    layouts(tools)
    for layout in tools._layout_by_width.values():
        for node in layout["nodes"]:
            node["complete"] = True


def coverage(tools):
    return tools._review_evidence_report()["typography_references"]["coverage"]


def test_zero_reference_calls_on_authored_text_cannot_be_accepted(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    final = json.loads(tools.finalize_web_run("accepted", "Finished"))
    assert final["outcome"] == "completed_with_warnings"
    assert coverage(tools)["status"] == "incomplete"
    assert coverage(tools)["uncovered_role_count"] == 1


def test_freezing_source_to_itself_does_not_cover_the_new_authored_heading(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    bind(tools, target_node_id="source")
    assert coverage(tools)["uncovered_role_count"] == 1
    assert json.loads(tools.finalize_web_run("accepted", "Finished"))["outcome"] != "accepted"


def test_equivalent_texts_share_one_mapping_but_a_second_style_needs_its_own(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    for layout in tools._layout_by_width.values():
        texts = layout["nodes"][1]["texts"]
        duplicate = copy.deepcopy(texts[0])
        duplicate.update(rendered_path=":nth-child(2)", text="Another heading")
        texts.append(duplicate)
    bind(tools)
    assert coverage(tools)["status"] == "covered"
    assert coverage(tools)["required_role_count"] == 1
    for layout in tools._layout_by_width.values():
        layout["nodes"][1]["texts"][1]["computed"]["font_weight"] = "500"
    assert coverage(tools)["uncovered_role_count"] == 1


def test_authored_self_reference_cannot_pose_as_captured_source(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    bind(tools, reference_node_id="authored")
    assert coverage(tools)["status"] == "incomplete"
    assert "captured_reference_required" in str(coverage(tools)["nodes"])


def test_unknown_fragment_provenance_cannot_silently_be_treated_as_capture(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    tools._cloned_section_seen.clear()
    report = coverage(tools)
    assert report["status"] == "incomplete"
    assert "fragment_provenance_unavailable" in str(report)
    assert json.loads(tools.finalize_web_run("accepted", "Finished"))["outcome"] != "accepted"


def test_no_authored_fragment_keeps_normal_clone_review_path(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    tools._cloned_section_seen["frag_authored"]["composed"] = None
    assert coverage(tools)["status"] == "not_applicable"


def test_unreachable_or_deleted_authored_node_does_not_leave_a_phantom_requirement(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    tools.web_doc["pages"][0]["nodes"]["root"]["children"] = ["source"]
    assert coverage(tools)["status"] == "not_applicable"


def test_matching_role_is_covered_and_does_not_promote_a_failed_outcome(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    bind(tools)
    assert coverage(tools)["status"] == "covered"
    assert json.loads(tools.finalize_web_run("failed", "Copy failed"))["outcome"] == "failed"


def test_uncaptured_text_or_missing_viewport_blocks_coverage(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    bind(tools)
    tools._layout_by_width[768]["nodes"][1].update(
        complete=False, omitted={"texts": 1, "descendants": 0},
    )
    assert coverage(tools)["status"] == "incomplete"
    assert "text_inventory_incomplete" in str(coverage(tools))
    del tools._layout_by_width[768]
    assert "current_measurement_missing" in str(coverage(tools))


def test_empty_image_band_needs_no_text_mapping_but_mobile_only_text_does(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    for layout in tools._layout_by_width.values():
        layout["nodes"][1]["texts"] = []
    assert coverage(tools)["status"] == "covered"
    for width, layout in tools._layout_by_width.items():
        text = sample()
        text["css_visible"] = width == 375
        layout["nodes"][1]["texts"] = [text]
    assert coverage(tools)["uncovered_role_count"] == 1


def test_active_page_scope_does_not_require_other_page_roles(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    tools.web_doc["pages"].append({
        "id": "second", "root": "root", "nodes": {"root": {"kind": "container"}},
    })
    tools.page_id = "second"
    assert coverage(tools)["status"] == "not_applicable"


def test_bounded_font_sampling_does_not_require_duplicate_style_mappings(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    for layout in tools._layout_by_width.values():
        duplicate = copy.deepcopy(layout["nodes"][1]["texts"][0])
        duplicate["rendered_path"] = ":nth-child(2)"
        duplicate["font_usage"] = {"status": "not_measured", "reason": "owner_cap"}
        layout["nodes"][1]["texts"].append(duplicate)
    bind(tools)
    assert coverage(tools)["status"] == "covered"
    assert coverage(tools)["required_role_count"] == 1
    assert coverage(tools)["nodes"][0]["roles"][0]["glyph_unmeasured_paths"] == [":nth-child(2)"]


def test_observed_glyph_variation_needs_a_separate_mapping(tmp_path):
    tools = _bare_tools(tmp_path)
    page(tools)
    for layout in tools._layout_by_width.values():
        duplicate = copy.deepcopy(layout["nodes"][1]["texts"][0])
        duplicate["rendered_path"] = ":nth-child(2)"
        duplicate["font_usage"]["fonts"][0]["postscript_name"] = "Fallback"
        layout["nodes"][1]["texts"].append(duplicate)
    bind(tools)
    assert coverage(tools)["status"] == "incomplete"
    assert "glyph_variation_unmapped" in str(coverage(tools))
