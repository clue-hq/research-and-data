"""Real-engine assembly keeps shared context once and immutable pin editing intact."""

import copy
import json

import pytest
from test_web_cloned_sections import HERO_HTML, HERO_ID, NAV_HTML, NAV_ID, FakeRegistry, _tools


def setup_tools(tmp_path, flow):
    registry = FakeRegistry(tmp_path)
    registry.add(
        HERO_ID,
        role="hero",
        label="Hero",
        html=HERO_HTML,
        slots=[{"key": "headline", "kind": "text"}],
    )
    registry.add(NAV_ID, role="proof", label="Proof", html=NAV_HTML)
    registry.prepare_source_flows = lambda ids: flow
    tools = _tools(tmp_path, registry)
    tools.web_doc["pages"][0]["nodes"]["root"]["children"] = []
    tools.web_doc["custom_css"] = ".existing{color:red}"
    return tools, registry


def flow():
    return {
        "groups": [
            {
                "group_id": "lumen-source-flow-test",
                "snapshot_id": "snapshot_held",
                "member_ids": [HERO_ID, NAV_ID],
                "nodes": [
                    {"classes": "flow-outer", "source_tag": "div"},
                    {"classes": "flow-inner", "source_tag": "div"},
                ],
                "css": ".flow-outer{padding-top:31px}.flow-inner{margin-top:17px}",
                "fidelity_verified": False,
            }
        ],
        "gaps": [],
    }


def test_real_engine_groups_once_preserves_pin_slots_and_existing_css(tmp_path):
    tools, _ = setup_tools(tmp_path, flow())
    result = json.loads(
        tools.recreate_cloned_page(json.dumps({HERO_ID: {"headline": "Edited heading"}}))
    )
    assert result["status"] == "ok"
    page = tools.web_doc["pages"][0]
    nodes = page["nodes"]
    assert len(nodes["root"]["children"]) == 1
    root = nodes[nodes["root"]["children"][0]]
    assert root["kind"] == "section" and root["classes"] == "flow-outer"
    inner = nodes[root["children"][0]]
    assert len(inner["children"]) == 2
    pins = [nodes[nodes[sid]["children"][0]] for sid in inner["children"]]
    assert [p["fragment_id"] for p in pins] == [HERO_ID, NAV_ID]
    assert pins[0]["slots"]["headline"]["text"] == "Edited heading"
    assert all(nodes[sid]["classes"] == "w-full" for sid in inner["children"])
    assert tools.web_doc["custom_css"].startswith(".existing{color:red}")
    assert tools.web_doc["custom_css"].count("padding-top:31px") == 1
    assert result["source_flow"]["groups"][0]["snapshot_id"] == "snapshot_held"
    assert result["source_flow"]["fidelity_verified"] is False
    # Existing scalar edit contract remains a leaf operation after grouping.
    leaf = copy.deepcopy(pins[0])
    leaf["slots"]["headline"]["text"] = "Second edit"
    response = tools.core.web_apply_ops(
        tools.web_doc,
        [
            {
                "kind": "set_node_props",
                "page_id": "home",
                "id": leaf["id"],
                "props": {
                    k: v for k, v in leaf.items() if k not in ("id", "classes", "children", "name")
                },
            }
        ],
    )
    assert (
        response["ok"]
        and response["web_doc"]["pages"][0]["nodes"][leaf["id"]]["slots"]["headline"]["text"]
        == "Second edit"
    )


def test_source_gap_is_prominent_and_never_fabricates_layout(tmp_path):
    tools, _ = setup_tools(
        tmp_path,
        {
            "groups": [],
            "gaps": [
                {
                    "code": "source_flow.snapshot_unavailable",
                    "member_ids": [HERO_ID, NAV_ID],
                    "message": "immutable source absent",
                }
            ],
        },
    )
    result = json.loads(tools.recreate_cloned_page())
    assert result["status"] == "ok"
    assert len(tools.web_doc["pages"][0]["nodes"]["root"]["children"]) == 2
    assert tools.web_doc["custom_css"] == ".existing{color:red}"
    assert result["source_flow"]["gaps"][0]["code"] == "source_flow.snapshot_unavailable"
    assert any(w["code"] == "source_flow.snapshot_unavailable" for w in result["warnings"])


def test_noncontiguous_or_reordered_group_never_reorders_pins(tmp_path):
    supplied = flow()
    supplied["groups"][0]["member_ids"].reverse()
    tools, _ = setup_tools(tmp_path, supplied)
    before = copy.deepcopy(tools.web_doc)
    result = json.loads(tools.recreate_cloned_page())
    assert result["status"] == "error" and result["error_code"] == "source_flow.order_mismatch"
    assert tools.web_doc == before


@pytest.mark.parametrize(
    "extra_css, expected_width, expected_y",
    [
        ("", 140, 68),
        ("*{box-sizing:inherit}", 140, 68),
        ("html{box-sizing:border-box}*{box-sizing:inherit}", 100, 68),
        ("html{font-size:10px}.inner{padding-top:2rem}", 140, 68),
    ],
)
def test_actual_render_preserves_source_box_width_and_shared_spacing(
    tmp_path, extra_css, expected_width, expected_y
):
    from types import SimpleNamespace

    from lumen_ingestion.sections.source_flow import compile_source_flow
    from playwright.sync_api import sync_playwright

    source_css = (
        ".outer{display:flow-root;padding-top:31px}"
        ".inner{width:100px;padding:20px;margin-top:17px}"
        "@media(max-width:500px){.inner{margin-top:9px}}"
    )
    source_css += extra_css
    source_html = (
        '<html><body style="margin:0"><div class="outer"><div class="inner">'
        '<section id="a" style="height:20px">A</section>'
        '<section id="b" style="height:20px">B</section></div></div></body></html>'
    )
    snap = SimpleNamespace(
        snapshot_id="snapshot_held",
        page_url="https://example.test/",
        html=source_html,
        meta={},
        stylesheets=[
            SimpleNamespace(
                text=source_css, url="https://example.test/style.css", media=None, disabled=False
            )
        ],
    )
    rows = [
        {
            "fragment_id": fid,
            "provenance": {
                "snapshot_id": "snapshot_held",
                "page_url": snap.page_url,
                "dom_path": [1, 0, 0, i],
                "tag": "section",
                "element_id": name,
                "recovery": {
                    "mode": "authored-descendant-after-refusal",
                    "parent_section_index": 0,
                    "parent_dom_path": [1, 0],
                },
            },
        }
        for i, (fid, name) in enumerate(((HERO_ID, "a"), (NAV_ID, "b")))
    ]
    group = compile_source_flow(snap, rows)
    tools, registry = setup_tools(tmp_path, {"groups": [group], "gaps": []})
    registry.sections[HERO_ID]["html"] = '<section id="a" style="height:20px">A</section>'
    registry.sections[NAV_ID]["html"] = '<section id="b" style="height:20px">B</section>'
    result = json.loads(tools.recreate_cloned_page())
    assert result["status"] == "ok"
    rendered = tools.core.web_render(
        tools.web_doc,
        "home",
        mode="delivery",
        fragments={
            fid: {"html": registry.sections[fid]["html"], "slot_kinds": {}}
            for fid in (HERO_ID, NAV_ID)
        },
    )["html"]
    source = (
        source_html.replace("</head>", "</head>")
        if "<head>" in source_html
        else source_html.replace("<html>", "<html><head><style>" + source_css + "</style></head>")
    )
    with sync_playwright() as browser:
        chromium = browser.chromium.launch(headless=True)
        try:
            for width in (1440, 375):
                boxes = []
                for text, inner in (
                    (source, ".inner"),
                    (rendered, "." + group["nodes"][-1]["classes"]),
                ):
                    page = chromium.new_page(viewport={"width": width, "height": 900})
                    page.route("**/*", lambda route: route.abort())
                    page.set_content(text)
                    boxes.append(
                        page.evaluate(
                            """selector=>{
                                let a=document.querySelector('#a').getBoundingClientRect(),
                                    b=document.querySelector('#b').getBoundingClientRect(),
                                    w=document.querySelector(selector).getBoundingClientRect();
                                return [a.x,a.y,b.x,b.y,w.width]
                            }""",
                            inner,
                        )
                    )
                    page.close()
                assert boxes[0] == boxes[1]
                assert boxes[1][-1] == expected_width
                assert boxes[1][1] == expected_y if width == 1440 else boxes[1][1] == expected_y - 8
        finally:
            chromium.close()
