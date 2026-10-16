"""Selected source roles survive edits; stale or drifting roles cannot be accepted."""

import copy
import json

import pytest
from test_web_substrate import _bare_tools

PATH = ":nth-child(1)"


def sample(size="48px", *, weight="400", face="Example-Regular"):
    return {
        "tag": "h2",
        "rendered_path": PATH,
        "css_visible": True,
        "text": "Example",
        "computed": {
            "font_family": "Example, serif",
            "font_size": size,
            "font_weight": weight,
            "font_style": "normal",
            "line_height": size,
            "letter_spacing": "-1.44px",
            "text_transform": "none",
            "font_synthesis": "weight style small-caps",
            "text_align": "left",
        },
        "font_usage": {
            "status": "observed",
            "fonts": [
                {
                    "family_name": "Example",
                    "postscript_name": face,
                    "is_custom_font": True,
                    "glyph_count": 10,
                }
            ],
        },
    }


def layouts(tools, *, authored_weight="400"):
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
    tools._layout_by_width = {
        width: {
            "status": "observed",
            "document_id": tools.web_doc["id"],
            "page_id": tools.page_id,
            "local_document_version": tools._doc_version,
            "iteration": 1,
            "viewport_width": width,
            "nodes": [
                {"node_id": "source", "status": "measured", "texts": [sample(size)]},
                {
                    "node_id": "authored",
                    "status": "measured",
                    "texts": [sample(size, weight=authored_weight)],
                },
            ],
        }
        for width, size in ((1440, "48px"), (768, "48px"), (375, "32px"))
    }


def bind(tools, **overrides):
    method = getattr(tools, "set_web_typography_reference", None)
    assert callable(method), (
        "Native tool must pin measured source roles before accepting typography"
    )
    return json.loads(
        method(
            json.dumps(
                [
                    {
                        "role": "section heading",
                        "reference_node_id": "source",
                        "reference_path": PATH,
                        "target_node_id": "authored",
                        "target_path": PATH,
                        **overrides,
                    }
                ]
            )
        )
    )


def test_role_reference_detects_authored_weight_and_mobile_scale_drift(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools, authored_weight="500")
    tools._layout_by_width[375]["nodes"][1]["texts"][0]["computed"]["font_size"] = "28px"
    result = bind(tools)
    assert result["status"] == "registered"
    report = result["typography_references"]
    assert report["status"] == "mismatch"
    differences = report["bindings"][0]["widths"]["375"]["differences"]
    assert differences["font_weight"] == {"expected": "400", "actual": "500"}
    assert differences["font_size"] == {"expected": "32px", "actual": "28px"}
    assert report["quality_verdict"] == "not_computed"


def test_retained_source_can_be_frozen_before_composition_then_bound_to_real_new_node(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    assert bind(tools, target_node_id="source")["status"] == "registered"
    original_version = tools._doc_version
    tools._doc_version += 1  # composition/pinning returned the new target ID; old render is stale
    result = bind(tools)
    assert result["status"] == "registered"
    assert result["typography_references"]["status"] == "incomplete"
    layouts(tools, authored_weight="500")
    # Even if the retained source is later restyled, the new target keeps the original reference.
    tools._layout_by_width[1440]["nodes"][0]["texts"][0]["computed"]["font_size"] = "40px"
    report = tools._review_evidence_report()["typography_references"]
    target = next(b for b in report["bindings"] if b["target_node_id"] == "authored")
    assert target["reference_document_version"] == original_version
    assert target["status"] == "mismatch"
    assert target["widths"]["1440"]["differences"]["font_weight"] == {
        "expected": "400", "actual": "500",
    }
    assert "font_size" not in target["widths"]["1440"]["differences"]


@pytest.mark.parametrize("change", ["new_source", "different_document", "different_page"])
def test_frozen_source_reuse_does_not_authorize_other_sources_or_scopes(tmp_path, change):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    bind(tools, target_node_id="source")
    tools._doc_version += 1
    args = {}
    if change == "new_source":
        args["reference_node_id"] = "another_source"
    elif change == "different_document":
        tools.web_doc["id"] = "another_document"
    else:
        tools.page_id = "another_page"
    assert bind(tools, **args)["status"] == "error"
    assert len(tools._typography_references.bindings) == 1


def test_copy_and_glyph_counts_can_change_while_selected_type_stays_exact(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    before = copy.deepcopy(tools.web_doc)
    assert bind(tools)["typography_references"]["status"] == "matched"
    for report in tools._layout_by_width.values():
        target = report["nodes"][1]["texts"][0]
        target["text"] = "Longer account-specific copy with the same type role"
        target["font_usage"]["fonts"][0]["glyph_count"] = 99
    report = tools._review_evidence_report()["typography_references"]
    assert report["status"] == "matched"
    assert tools.web_doc == before


@pytest.mark.parametrize("defect", ["css", "face", "hidden", "missing", "stale", "wrong_page"])
def test_acceptance_is_downgraded_for_drift_or_missing_current_measurements(tmp_path, defect):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    assert bind(tools)["status"] == "registered"
    report = tools._layout_by_width[375]
    target = report["nodes"][1]["texts"][0]
    if defect == "css":
        target["computed"]["font_weight"] = "500"
    elif defect == "face":
        target["font_usage"]["fonts"][0]["postscript_name"] = "Example-Medium"
    elif defect == "hidden":
        target["css_visible"] = False
    elif defect == "missing":
        report["nodes"] = report["nodes"][:1]
    elif defect == "stale":
        tools._doc_version += 1
    else:
        report["page_id"] = "another-page"
    final = json.loads(tools.finalize_web_run("accepted", "Draft complete"))
    assert final["outcome"] == "completed_with_warnings"
    assert final["requested_outcome"] == "accepted"
    assert "Typography reference checks" in final["summary"]
    assert final["review_evidence"]["typography_references"]["status"] != "matched"
    assert (
        json.loads((tools.turn_dir / "final.json").read_text())["outcome"]
        == "completed_with_warnings"
    )


def test_pinned_reference_cannot_follow_a_later_source_restyle(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    assert bind(tools)["typography_references"]["status"] == "matched"
    for report in tools._layout_by_width.values():
        for node in report["nodes"]:
            node["texts"][0]["computed"]["font_weight"] = "500"
    # An idempotent repeated registration must not reset the expectation to the new draft.
    assert bind(tools)["typography_references"]["status"] == "mismatch"
    changed = bind(tools, reference_node_id="authored")
    assert changed["status"] == "error"
    assert changed["error_code"] == "typography.reference_locked"
    assert tools._review_evidence_report()["typography_references"]["status"] == "mismatch"


@pytest.mark.parametrize("defect", ["missing_width", "unobserved_face", "ambiguous_path"])
def test_reference_registration_refuses_incomplete_or_ambiguous_evidence(tmp_path, defect):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    if defect == "missing_width":
        del tools._layout_by_width[768]
    elif defect == "unobserved_face":
        tools._layout_by_width[768]["nodes"][0]["texts"][0]["font_usage"] = {
            "status": "unavailable"
        }
    else:
        row = tools._layout_by_width[768]["nodes"][0]
        row["texts"].append(copy.deepcopy(row["texts"][0]))
    result = bind(tools)
    assert result["status"] == "error"
    assert result["error_code"] == "typography.reference_unavailable"
    assert tools._review_evidence_report()["typography_references"]["status"] == "not_declared"


def test_hidden_mobile_reference_requires_hidden_mobile_target(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    ref, target = (n["texts"][0] for n in tools._layout_by_width[375]["nodes"])
    ref["css_visible"] = target["css_visible"] = False
    ref["font_usage"] = target["font_usage"] = {"status": "not_measured", "reason": "css_hidden"}
    assert bind(tools)["typography_references"]["status"] == "matched"
    target["css_visible"] = True
    assert tools._review_evidence_report()["typography_references"]["status"] == "mismatch"


def test_failed_finalization_is_not_promoted_by_a_matching_contract(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    assert bind(tools)["typography_references"]["status"] == "matched"
    final = json.loads(tools.finalize_web_run("failed", "Other requirements failed"))
    assert final["outcome"] == "failed"


def test_batch_registration_is_atomic_when_a_later_reference_is_invalid(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    valid = {
        "role": "heading",
        "reference_node_id": "source",
        "reference_path": PATH,
        "target_node_id": "authored",
        "target_path": PATH,
    }
    invalid = {**valid, "target_node_id": "later", "reference_node_id": "missing"}
    result = json.loads(tools.set_web_typography_reference(json.dumps([valid, invalid])))
    assert result["error_code"] == "typography.reference_unavailable"
    assert tools._review_evidence_report()["typography_references"]["bindings"] == []
    assert not (tools.turn_dir / "typography_references.json").exists()


@pytest.mark.parametrize("raw", ["{}", "[]", "null", "[1]", "not-json", "[{}]", "[" * 32_001])
def test_malformed_reference_requests_never_create_partial_constraints(tmp_path, raw):
    tools = _bare_tools(tmp_path)
    result = json.loads(tools.set_web_typography_reference(raw))
    assert result["error_code"] == "typography.bad_bindings"
    assert tools._review_evidence_report()["typography_references"]["status"] == "not_declared"


def test_role_limit_refuses_new_bindings_without_discarding_existing_ones(tmp_path):
    tools = _bare_tools(tmp_path)
    layouts(tools)
    for index in range(24):
        assert bind(tools, target_node_id=f"new-{index}")["status"] == "registered"
    assert bind(tools)["error_code"] == "typography.reference_limit"
    report = tools._review_evidence_report()["typography_references"]
    assert len(report["bindings"]) == 24
    assert report["status"] == "incomplete"


def test_real_browser_measurements_detect_drift_then_verify_css_repair(tmp_path):
    from langchain_core.tools import StructuredTool
    from lumen_agent.tools.web_layout_capture import capture_layout
    from lumen_agent.tools.web_substrate import make_web_view_tool
    from playwright.sync_api import sync_playwright

    tools = _bare_tools(tmp_path)
    targets = [{"node_id": n, "kind": "section"} for n in ("source", "authored")]
    authored_html = (
        '<section class="authored" data-node-id="authored"><h2>Account heading</h2></section>'
    )
    html = """<style>
        body{margin:0}
        h2{font-family:serif;line-height:1;letter-spacing:-1px;text-align:left}
        .source h2{font-size:48px;font-weight:400}
        .authored h2{font-size:32px;font-weight:500}
        @media(max-width:767px){.source h2{font-size:32px}.authored h2{font-size:28px}}
        </style>
        <section class="source" data-node-id="source"><h2>Reference heading</h2></section>"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:

            def measure(*, source_only=False, repaired=False):
                tools._preview_iteration = (tools._preview_iteration or 0) + 1
                tools._preview_doc_version = tools._doc_version
                for width in (1440, 768, 375):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.route("**/*", lambda route: route.abort())
                    page.set_content(html if source_only else html + authored_html)
                    if repaired:
                        page.add_style_tag(
                            content=".authored h2{font-size:48px;font-weight:400}"
                            "@media(max-width:767px){.authored h2{font-size:32px}}"
                        )
                    report = capture_layout(page, targets[:1] if source_only else targets)
                    report.update(
                        {
                            k: v
                            for k, v in tools._typography_identity().items()
                            if k != "preview_version"
                        }
                    )
                    tools._layout_by_width[width] = report
                    page.close()

            measure(source_only=True)
            source = json.loads(make_web_view_tool(tools).invoke(
                {"target": "typography:node:source"}
            )[0]["text"])
            assert source["complete"] is True
            heading = source["texts"][0]
            assert heading["widths"]["1440"]["sample"]["font_size"] == "48px"
            assert heading["widths"]["375"]["sample"]["font_size"] == "32px"
            assert heading["widths"]["1440"]["sample"]["font_weight"] == "400"
            exposed = StructuredTool.from_function(tools.set_web_typography_reference)
            # Pin a retained source before the new section has a node ID or rendered path.
            frozen = json.loads(exposed.invoke({"bindings_json": json.dumps([{
                "role": "retained heading",
                "reference_node_id": source["reference_node_id"],
                "reference_path": heading["reference_path"],
                "target_node_id": source["reference_node_id"],
                "target_path": heading["reference_path"],
            }])}))
            assert frozen["typography_references"]["status"] == "matched"
            source_iteration = tools._preview_iteration
            tools._doc_version += 1  # a new section is composed and pinned
            measure()
            target = json.loads(make_web_view_tool(tools).invoke(
                {"target": "typography:node:authored"}
            )[0]["text"])
            result = json.loads(
                exposed.invoke(
                    {
                        "bindings_json": json.dumps(
                            [
                                {
                                    "role": "heading",
                                    "reference_node_id": source["reference_node_id"],
                                    "reference_path": heading["reference_path"],
                                    "target_node_id": target["reference_node_id"],
                                    "target_path": target["texts"][0]["reference_path"],
                                }
                            ]
                        )
                    }
                )
            )
            assert result["typography_references"]["status"] == "mismatch"
            authored = result["typography_references"]["bindings"][1]
            assert authored["reference_render_iteration"] == source_iteration
            assert authored["widths"]["1440"]["differences"]["font_size"] == {
                "expected": "48px", "actual": "32px",
            }
            tools._doc_version += 1
            measure(repaired=True)
            report = tools._review_evidence_report()["typography_references"]
            assert report["status"] == "matched", report
            assert all(
                b["reference_render_iteration"] == source_iteration for b in report["bindings"]
            )
            assert (
                json.loads(tools.finalize_web_run("accepted", "Other checks assumed by fixture"))[
                    "outcome"
                ]
                == "accepted"
            )
        finally:
            browser.close()
