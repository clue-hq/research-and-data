"""Source-authored shared envelopes; no inferred spacing or source acquisition."""

from importlib.util import find_spec
from types import SimpleNamespace

import pytest


def compiler():
    assert find_spec("lumen_ingestion.sections.source_flow"), (
        "shared source-flow compiler is missing"
    )
    from lumen_ingestion.sections.source_flow import compile_source_flow

    return compile_source_flow


def snapshot(css="", html=None):
    return SimpleNamespace(
        snapshot_id="snapshot_held",
        page_url="https://example.test/",
        meta={},
        html=html
        or (
            '<html style="--offset:31px"><body style="margin:0">'
            '<div class="outer"><div class="inner">'
            '<section id="a">A</section><section id="b">B</section>'
            "</div></div><footer>F</footer></body></html>"
        ),
        stylesheets=(
            SimpleNamespace(
                url="https://example.test/site.css",
                text=css,
                source_order=0,
                media=None,
                disabled=False,
            ),
        ),
    )


def members():
    return [
        {
            "fragment_id": f"frag_{i:016x}",
            "provenance": {
                "snapshot_id": "snapshot_held",
                "page_url": "https://example.test/",
                "section_index": i + 3,
                "dom_path": [1, 0, 0, i],
                "tag": "section",
                "element_id": name,
                "recovery": {
                    "mode": "authored-descendant-after-refusal",
                    "parent_section_index": 0,
                    "parent_dom_path": [1, 0],
                    "wrapper_layout_preserved": False,
                },
            },
        }
        for i, name in enumerate(("a", "b"))
    ]


def test_projects_one_shared_chain_and_preserves_responsive_source_values():
    result = compiler()(
        snapshot(
            ".outer{display:flow-root;padding-top:var(--offset)} .inner{margin-top:17px} "
            "@media(max-width:500px){.inner{margin-top:9px}}"
        ),
        members(),
    )
    assert result["member_ids"] == [r["fragment_id"] for r in members()]
    assert [n["source_tag"] for n in result["nodes"]] == ["html", "body", "div", "div"]
    assert "padding-top:var(--offset)" in result["css"]
    assert "margin-top:17px" in result["css"] and "margin-top:9px" in result["css"]
    assert "--offset:31px" in result["css"]
    assert result["fidelity_verified"] is False
    assert result["snapshot_id"] == "snapshot_held"


def test_source_order_is_verified_not_input_order():
    result = compiler()(snapshot(), list(reversed(members())))
    assert result["member_ids"] == [r["fragment_id"] for r in members()]


@pytest.mark.parametrize(
    "css",
    [
        ".inner{display:grid}",
        ".inner{display:flex}",
        ".inner{position:fixed}",
        ".inner{padding-top:var(--unknown)}",
        ".inner{background-image:url(/held.png)}",
        ".inner:hover{padding:20px}",
        '.inner::before{content:"";display:block;height:20px}',
        "@layer base{.inner{padding:20px}}",
        ".inner{transform:translateY(20px)}",
    ],
)
def test_unsupported_layout_refuses_instead_of_guessing(css):
    with pytest.raises(ValueError, match=r"source_flow\."):
        compiler()(snapshot(css), members())


def test_later_source_rule_can_restore_normal_flow():
    result = compiler()(
        snapshot(".outer{position:absolute}.outer{position:relative;display:flow-root}"), members()
    )
    assert result["css"].index("position:absolute") < result["css"].index("position:relative")


@pytest.mark.parametrize("mutation", ["snapshot", "path", "identity", "derived"])
def test_member_custody_and_source_identity(mutation):
    rows = members()
    if mutation == "snapshot":
        rows[1]["provenance"]["snapshot_id"] = "other"
    if mutation == "path":
        rows[1]["provenance"]["dom_path"] = [1, 1]
    if mutation == "identity":
        rows[1]["provenance"]["element_id"] = "not-b"
    if mutation == "derived":
        rows[1]["derived_from"] = "frag_original"
    with pytest.raises(ValueError, match=r"source_flow\."):
        compiler()(snapshot(), rows)


def test_intervening_non_section_content_cannot_disappear():
    s = snapshot(
        html=(
            '<html><body style="margin:0"><div class="outer"><div class="inner">'
            '<section id="a">A</section><p>Required spacer text</p>'
            '<section id="b">B</section></div></div></body></html>'
        )
    )
    rows = members()
    rows[1]["provenance"]["dom_path"][-1] = 2
    with pytest.raises(ValueError, match=r"source_flow\.unsupported_topology"):
        compiler()(s, rows)


@pytest.mark.parametrize(
    "css",
    [
        ".inner{column-count:2}",
        ".inner{border:10px solid;border-image:url(/held.png) 30}",
        "body{direction:rtl}.inner{margin-inline-start:20px}",
        ".outer{font-size:30px}.inner{margin-top:2em}",
        ".outer{--space:2em}.inner{margin-top:var(--space)}",
        "body{width:600px}.inner{width:50%}",
    ],
)
def test_unsupported_context_is_never_silently_discarded(css):
    with pytest.raises(ValueError, match=r"source_flow\."):
        compiler()(snapshot(css), members())


def test_source_box_initial_and_root_inherit_are_explicit():
    result = compiler()(
        snapshot(
            "html{box-sizing:border-box} *{box-sizing:inherit}.inner{width:100px;padding:20px}"
        ),
        members(),
    )
    assert "box-sizing:content-box" in result["css"]
    assert "box-sizing:border-box" in result["css"]
    assert "box-sizing:inherit" in result["css"]


def test_root_unit_prelude_keeps_original_media_association():
    s = snapshot("html{font-size:10px}.inner{padding-top:2rem}")
    result = compiler()(s, members())
    assert "--lumen-source-rem-" in result["css"] and "calc(" in result["css"]


def test_malformed_source_selector_has_named_gap():
    with pytest.raises(ValueError, match=r"source_flow\."):
        compiler()(snapshot(".inner[foo^]{padding:20px}"), members())


def test_deep_source_and_unrepresented_outer_ancestor_refuse():
    with pytest.raises(ValueError, match=r"source_flow\.bound"):
        compiler()(
            snapshot("@supports(display:block){" * 40 + ".inner{padding:1px}" + "}" * 40), members()
        )
    s = snapshot()
    s.html = s.html.replace('<div class="outer">', '<main><div class="outer">').replace(
        "</div><footer>", "</div></main><footer>"
    )
    rows = members()
    for row in rows:
        row["provenance"]["dom_path"].insert(1, 0)
        row["provenance"]["recovery"]["parent_dom_path"].append(0)
    with pytest.raises(ValueError, match=r"source_flow\.unsupported_topology"):
        compiler()(s, rows)


@pytest.mark.parametrize(
    "css",
    [
        "@media(min-width:0px){body{width:600px}}.inner{width:50%}",
        "@media(min-width:0px){body{padding:40px}}",
    ],
)
def test_conditional_document_layout_refuses(css):
    with pytest.raises(ValueError, match=r"source_flow\."):
        compiler()(snapshot(css), members())


@pytest.mark.parametrize(
    "css",
    [
        "body{background-image:url(/held.png)}.outer{background-image:inherit}",
        "body{color:red}.outer{border:1px solid currentColor}",
        "body{padding:0}.outer{padding:inherit}",
    ],
)
def test_ancestor_cannot_inherit_discarded_document_paint_or_layout(css):
    with pytest.raises(ValueError, match=r"source_flow\."):
        compiler()(snapshot(css), members())


def test_implicit_body_margin_requires_a_document_layout_gap():
    from playwright.sync_api import sync_playwright

    source = snapshot()
    source.html = source.html.replace('style="margin:0"', "")
    with sync_playwright() as browser:
        chromium = browser.chromium.launch(headless=True)
        try:
            page = chromium.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(source.html)
            assert page.locator("#a").bounding_box()["x"] == 8
        finally:
            chromium.close()
    with pytest.raises(ValueError, match=r"source_flow\.unsupported_document_layout"):
        compiler()(source, members())


def test_variable_allow_inherit_check_is_specific_to_the_consuming_property():
    with pytest.raises(ValueError, match=r"source_flow\.unsupported_context"):
        compiler()(snapshot(".outer{--x:inherit;box-sizing:var(--x);width:var(--x)}"), members())
