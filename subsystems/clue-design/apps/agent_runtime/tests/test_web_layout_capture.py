"""Offline measured evidence for source/authored typography and media containers."""

import json

import pytest
from playwright.sync_api import sync_playwright
from test_web_substrate import _tools


@pytest.fixture
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/*", lambda route: route.abort())
        try:
            yield page
        finally:
            browser.close()


HTML = (
    """<style>
body{margin:0}.source h2{font:400 48px/1.1 Georgia}.authored h2{font:500 32px/1.2 Georgia}
.stage{padding:12px;background:linear-gradient(teal,gold);border-radius:10px;height:400px}
.stage img{width:100%;height:100%;object-fit:contain;object-position:25% 50%;border-radius:8px}
.copy{height:400px;display:flex;align-items:center}.copy p{font:400 16px/24px Arial}
@media(max-width:767px){.stage img{display:none}.source h2{font-size:28px}}
</style>
<section class="source" data-node-id="source"><h2>Source heading</h2></section>
<section class="authored" data-node-id="authored"><h2>Authored heading</h2>
<div class="copy"><p>Short explanation.</p></div>
<div class="stage"><img alt="Finished composite" src="https://fixture.test/asset-store/"""
    + "a" * 64
    + """"></div></section>"""
)


def measure(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    return capture_layout(
        page, [{"node_id": "source", "kind": "section"}, {"node_id": "authored", "kind": "section"}]
    )


def test_reports_actual_type_drift_and_image_container_without_claiming_fidelity(page):
    page.set_content(HTML)
    report = measure(page)
    source, authored = report["nodes"]
    assert source["texts"][0]["computed"]["font_size"] == "48px"
    assert source["texts"][0]["computed"]["font_weight"] == "400"
    assert authored["texts"][0]["computed"]["font_size"] == "32px"
    assert authored["texts"][0]["computed"]["font_weight"] == "500"
    shot = authored["images"][0]
    assert shot["asset_digest"] == "a" * 64
    assert shot["computed"]["object_fit"] == "contain"
    assert shot["computed"]["object_position"] == "25% 50%"
    frame = authored["containers"][shot["ancestor_container_ids"][0]]
    assert frame["computed"]["padding"] == "12px"
    assert "linear-gradient" in frame["computed"]["background_image"]
    assert shot["pixel_composition"] == "unclassified"
    assert shot["loaded"] is False
    assert report["actual_glyph_font"] == "not_measured"
    assert report["quality_verdict"] == "not_computed"
    parent = authored["containers"][authored["texts"][1]["parent_container_id"]]
    assert authored["texts"][1]["box"]["height"] < parent["box"]["height"]
    assert parent["computed"]["align_items"] == "center"


@pytest.mark.parametrize(
    "width,shown,size", [(767, False, "28px"), (768, True, "48px"), (769, True, "48px")]
)
def test_reports_hidden_product_at_exact_responsive_boundary(page, width, shown, size):
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(HTML)
    report = measure(page)
    assert report["nodes"][0]["texts"][0]["computed"]["font_size"] == size
    assert report["nodes"][1]["images"][0]["css_visible"] is shown


def test_visibility_accounts_for_hidden_ancestor_and_reports_omissions(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    page.set_content(
        '<section data-node-id="s"><div style="opacity:0"><p>Hidden</p></div>'
        + "".join(f"<p>Row {i}</p>" for i in range(20))
        + "</section>"
    )
    report = capture_layout(page, [{"node_id": "s", "kind": "section"}])
    row = report["nodes"][0]
    assert row["texts"][0]["css_visible"] is False
    assert len(row["texts"]) == 16 and row["omitted"]["texts"] == 5
    assert row["complete"] is False


def test_missing_and_duplicate_rendered_ids_are_not_measurements(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    page.set_content(
        '<section data-node-id="same"></section><section data-node-id="same"></section>'
    )
    report = capture_layout(
        page, [{"node_id": "same", "kind": "section"}, {"node_id": "absent", "kind": "fragment"}]
    )
    assert [row["status"] for row in report["nodes"]] == ["ambiguous", "missing"]
    assert all("box" not in row for row in report["nodes"])


def test_descendant_visibility_override_and_display_contents_are_not_false_hidden(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    page.set_content("""<section data-node-id="s">
      <div style="visibility:hidden"><p style="visibility:visible">Visible override</p>
        <p>Hidden inherited</p></div>
      <span style="display:contents">Visible direct text</span>
      <div style="height:10px;overflow:hidden"><p style="margin-top:30px">Clipped</p></div>
    </section>""")
    row = capture_layout(page, [{"node_id": "s", "kind": "section"}])["nodes"][0]
    assert row["texts"][0]["css_visible"] is True
    assert row["texts"][1]["css_visible"] is False
    assert row["texts"][2]["css_visible"] is None
    assert row["texts"][2]["visibility_note"] == "no_element_box_direct_text_unmeasured"
    assert row["texts"][3]["css_visible"] is False


def test_document_boxes_and_root_relative_paths_are_distinguished(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    page.set_content("""<style>body{margin:0}p{margin:0}</style>
      <div style="height:400px"></div><section data-node-id="s"><p>Lower section</p></section>""")
    report = capture_layout(page, [{"node_id": "s", "kind": "section"}])
    assert report["coordinate_space"] == "document_css_pixels"
    assert report["path_space"] == "rendered_node_relative"
    assert report["nodes"][0]["texts"][0]["box"]["y"] == 400
    assert report["nodes"][0]["texts"][0]["rendered_path"] == ":nth-child(1)"


def test_native_layout_view_requires_current_page_and_render(tmp_path):
    tools = _tools(tmp_path)
    result = tools._view_content("layout:1440", can_render=False)
    payload = json.loads(result[0]["text"])
    assert payload["status"] == "error" and payload["code"] == "layout.not_captured"
    assert "render_web_preview()" not in payload["message"]


def test_target_plan_excludes_other_pages_orphans_and_duplicate_references():
    from lumen_agent.tools.web_layout_capture import layout_targets

    doc = {
        "pages": [
            {
                "id": "active",
                "root": "r",
                "nodes": {
                    "r": {"kind": "container", "children": ["s", "s"]},
                    "s": {"kind": "section", "children": ["f"]},
                    "f": {"kind": "fragment", "fragment_id": "frag_x", "children": ["r"]},
                    "orphan": {"kind": "section"},
                },
            },
            {"id": "other", "root": "else", "nodes": {"else": {"kind": "section"}}},
        ]
    }
    assert [r["node_id"] for r in layout_targets(doc, "active")] == ["s", "f"]
    assert layout_targets(doc, "missing") == []


def test_observation_failure_is_explicit_and_node_cap_is_reported(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    page.set_content("".join(f'<section data-node-id="s{i}">Text</section>' for i in range(50)))
    result = capture_layout(page, [{"node_id": f"s{i}", "kind": "section"} for i in range(50)])
    assert len(result["nodes"]) == 48
    assert result["omitted_node_ids"] == ["s48", "s49"]
    page.close()
    result = capture_layout(page, [])
    assert result["status"] == "unavailable" and result["code"] == "layout.capture_failed"


def test_full_text_and_image_allowance_fits_native_view_byte_budget(page):
    from lumen_agent.tools.web_layout_capture import capture_layout

    page.set_content(
        '<section data-node-id="s"><div><div>'
        + "".join(
            '<p>Useful copy</p><img alt="Product" width="200" height="100">' for _ in range(16)
        )
        + "</div></div></section>"
    )
    report = capture_layout(page, [{"node_id": "s", "kind": "section"}])
    assert report["nodes"][0]["complete"] is True
    # Reserve room for document/version/media metadata in the 64 KiB view envelope.
    assert len(json.dumps(report).encode()) < 50_000


def test_native_capture_and_view_share_identity_and_refuse_stale_or_wrong_page(
    tmp_path, page, monkeypatch
):
    tools = _tools(tmp_path)
    assert (
        json.loads(
            tools.author_web_page('<section id="test"><h1>Heading</h1><p>Body</p></section>')
        )["status"]
        == "ok"
    )
    html, _, _ = tools._render_page_html()
    tools.iteration = 1
    monkeypatch.setattr(tools, "_browser_handle", lambda: page.context.browser)
    monkeypatch.setattr(tools, "_capture_states", lambda *args: {})
    # Block network in every temporary capture context, not only the fixture page.
    page.context.browser.on("page", lambda p: p.route("**/*", lambda route: route.abort()))
    tools._capture_pass(html, tmp_path, [])
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
    index = json.loads(tools._view_content("layout:375", can_render=False)[0]["text"])
    assert index["status"] == "observed" and index["page_id"] == tools.page_id
    assert index["local_document_version"] == tools._doc_version
    assert index["nodes"][0]["node_id"] == "test"
    assert "texts" not in index["nodes"][0]
    result = json.loads(tools._view_content("layout:375:node:test")[0]["text"])
    assert result["node"]["texts"][0]["text"] == "Heading"
    assert result["node"]["texts"][0]["computed"]["font_size"]
    saved = json.loads((tmp_path / "layout_375.json").read_text())
    assert saved["nodes"][0] == result["node"]
    tools._preview_iteration = 0
    assert json.loads(tools._view_content("layout:375")[0]["text"])["code"] == "layout.stale"
    tools._preview_iteration = 1
    assert json.loads(tools.add_page("other", "Other", "/other"))["status"] == "ok"
    assert not tools._layout_by_width
    assert json.loads(tools._view_content("layout:375")[0]["text"])["code"] == "layout.not_captured"
