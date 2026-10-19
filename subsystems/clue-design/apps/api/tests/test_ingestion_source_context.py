"""Source document inheritance survives minting without acquiring synthetic ancestors."""

from __future__ import annotations

import pytest
from lumen_api.fragments import build_fragment_artifact
from lumen_api.fragments.isolation import isolation_web_doc
from lumen_api.fragments.render import slot_kinds
from playwright.sync_api import sync_playwright
from test_ingestion_section_mint import _mint, _Sheet
from test_web_editor_candidates import _real_core

HTML = """<!doctype html><html lang="en"><head></head><body class="site">
<header><a href="/">Home</a><a href="/x">X</a></header>
<section class="section_home-hero" id="subject"><h1>Headline</h1><p id="copy">Copy</p>
<a href="/demo"><span>Book demo</span></a><button id="control">Control</button>
<div class="site"><span id="nested">Nested same class</span></div></section>
<section class="section_proof"><p>Proof</p></section><footer><p>Footer</p></footer>
</body></html>"""
BASE = """html {font-size:10px}
.site {font-size:14px;line-height:1.6;font-family:Arial,sans-serif;color:#333}
.site button {font:inherit;color:inherit} body {margin:0}
section {padding:0} h1 {margin:0} p {margin:0}"""


def _artifact(html, css):
    outcome, recorder = _mint(html, stylesheets=[_Sheet("https://source.example/main.css", css)])
    assert outcome.minted, outcome.diagnostics
    selected = [row for row in recorder.created if 'id="subject"' in row["html"]]
    assert len(selected) == 1, outcome.diagnostics
    row = selected[0]
    artifact = build_fragment_artifact(
        html=row["html"], css=row["css"], rehosted=row["rehosted"], slots=row["slots"]
    )
    return artifact, row


def _measure(page):
    return page.evaluate("""() => Object.fromEntries(
      ['subject','copy','control','nested'].map(id => {
      const el=document.getElementById(id),s=getComputedStyle(el);
      return [id,{font:s.fontFamily,size:s.fontSize,line:s.lineHeight,color:s.color,
        weight:s.fontWeight,padding:s.padding,border:s.borderTopWidth}];
    }))""")


@pytest.mark.parametrize(
    "extra",
    [
        "",
        "* {font-size:1.1em}",
        "div {font-size:23px} *:first-child {font-size:1.1em} "
        "section > p:first-of-type {color:blue}",
        "body.site > section {letter-spacing:2px;border-top:3px solid} "
        "body.site > section:first-child {font-size:99px}",
        "html {color:red!important} body.site {color:blue} .site .site {font-size:21px}",
    ],
)
def test_source_document_context_matches_real_delivery(monkeypatch, extra):
    css = BASE + extra
    # Keep the extracted root first in the source for this structural comparison;
    # omitted preceding siblings are a separate, explicitly unsupported context.
    html = HTML
    if "*:first-child" in extra:
        html = html.replace('<header><a href="/">Home</a><a href="/x">X</a></header>', "")
    artifact, _ = _artifact(html, css)
    core = _real_core(monkeypatch)
    delivery = core.web_render(
        isolation_web_doc(artifact.fragment_id),
        "home",
        mode="delivery",
        fragments={
            artifact.fragment_id: {
                "html": artifact.payload["html"],
                "slot_kinds": slot_kinds(artifact.payload["slot_manifest"]),
            }
        },
        fragment_css=artifact.payload["css"],
    )["html"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/*", lambda route: route.abort())
        page.set_content(html.replace("</head>", f"<style>{css}</style></head>"))
        expected = _measure(page)
        page.set_content(delivery)
        actual = _measure(page)
        browser.close()
    assert actual == expected


def test_context_prefixes_keep_real_engine_slots_and_internal_child_positions(monkeypatch):
    artifact, _ = _artifact(HTML, BASE)
    core = _real_core(monkeypatch)
    doc = isolation_web_doc(artifact.fragment_id)
    node_id = next(k for k, n in doc["pages"][0]["nodes"].items() if n["kind"] == "fragment")
    edited = core.web_apply_ops(
        doc,
        [
            {
                "kind": "set_node_props",
                "page_id": "home",
                "id": node_id,
                "props": {
                    "kind": "fragment",
                    "fragment_id": artifact.fragment_id,
                    "slots": {
                        "headline": {"text": "Edited headline"},
                        "visible": {"visible": True},
                    },
                },
            }
        ],
    )
    result = core.web_render(
        edited["web_doc"],
        "home",
        mode="delivery",
        fragments={
            artifact.fragment_id: {
                "html": artifact.payload["html"],
                "slot_kinds": slot_kinds(artifact.payload["slot_manifest"]),
            }
        },
        fragment_css=artifact.payload["css"],
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(result["html"])
        assert page.locator("#subject > h1:first-child").inner_text() == "Edited headline"
        assert page.locator("#subject > p:first-of-type").inner_text() == "Copy"
        assert page.locator("#subject").get_attribute("data-lumen-slot") == "visible"
        assert (
            page.locator("#subject").evaluate("el => el.parentElement.tagName").startswith("LS-B")
        )
        browser.close()


def test_private_context_tag_collision_checks_selectors_but_not_css_strings():
    from lumen_ingestion.sections.rootunits import prepare_root_units
    from lumen_ingestion.sections.source_context import SourceDocumentContext

    marker = "ls-h"
    root_units = prepare_root_units([], html=HTML)
    actual = SourceDocumentContext.prepare(
        HTML, [_Sheet("s.css", f"{marker} {{color:red}}")], root_units
    )
    assert actual.root_tag != marker
    strings = SourceDocumentContext.prepare(
        HTML, [_Sheet("s.css", f'p {{content:"{marker}"}}')], root_units
    )
    assert strings.root_tag == marker


def test_context_assets_remain_in_the_custody_gate():
    css = BASE + ".site {--context-image:url(/missing-context.png)}"
    outcome, _ = _mint(HTML, stylesheets=[_Sheet("https://cdn.example/theme.css", css)])
    assert not outcome.minted
    assert any(d.get("reference") == "/missing-context.png" for d in outcome.diagnostics)


def test_unsupported_sibling_and_document_state_are_named():
    _, row = _artifact(
        HTML, BASE + "body.site > section:first-child {font-size:99px} html:hover {color:red}"
    )
    limits = row["provenance"]["css"]["source_document_context"]["limitations"]
    assert any("sibling positions" in item for item in limits)
    assert any("structural selectors" in item for item in limits)
    assert any("state/selector" in item for item in limits)


@pytest.mark.parametrize("width", [1440, 375])
def test_inline_body_em_and_media_context_remain_responsive(monkeypatch, width):
    html = HTML.replace(
        '<body class="site">', '<body class="site" style="font-size:1.4em;color:navy;--space:1rem">'
    )
    css = (
        BASE + "@media(max-width:600px){html{font-size:12px}.site{line-height:1.8}} "
        "#copy{padding:var(--space)}"
    )
    artifact, _ = _artifact(html, css)
    delivery = _real_core(monkeypatch).web_render(
        isolation_web_doc(artifact.fragment_id),
        "home",
        mode="delivery",
        fragments={artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}},
        fragment_css=artifact.payload["css"],
    )["html"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.route("**/*", lambda r: r.abort())
        page.set_content(html.replace("</head>", f"<style>{css}</style></head>"))
        expected = _measure(page)
        page.set_content(delivery)
        actual = _measure(page)
        browser.close()
    assert actual == expected


@pytest.mark.parametrize("selector", [":where(body)", ":is(html,body)", ":where(.site)"])
def test_unsupported_functional_document_subject_is_explicit(selector):
    _, row = _artifact(HTML, BASE + f"{selector} {{font-size:17px}}")
    limits = row["provenance"]["css"]["source_document_context"]["limitations"]
    assert any("functional document selector" in item for item in limits)


def test_functional_document_only_stylesheet_is_not_marked_unneeded():
    _, row = _artifact(HTML.replace(' lang="en"', ""), ":where(body.site){font-size:23px}")
    context = row["provenance"]["css"]["source_document_context"]
    assert context["mode"] == "unsupported"
    assert any("functional document selector" in note for note in context["limitations"])


@pytest.mark.parametrize("direction", ["", "rtl"])
def test_source_context_does_not_inherit_host_writing_defaults(monkeypatch, direction):
    html = HTML.replace('lang="en"', f'lang="en" dir="{direction}"' if direction else 'lang="en"')
    artifact, _ = _artifact(html, BASE)
    doc = isolation_web_doc(artifact.fragment_id)
    doc["custom_css"] = "body{direction:rtl;writing-mode:vertical-rl;color-scheme:dark}"
    delivery = _real_core(monkeypatch).web_render(
        doc,
        "home",
        mode="delivery",
        fragments={artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}},
        fragment_css=artifact.payload["css"],
    )["html"]
    measure = """() => {const s=getComputedStyle(document.querySelector('#copy'));
      return {direction:s.direction,writing:s.writingMode,scheme:s.colorScheme}}"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(html.replace("</head>", f"<style>{BASE}</style></head>"))
        expected = page.evaluate(measure)
        page.set_content(delivery)
        actual = page.evaluate(measure)
        assert (
            page.eval_on_selector("body", "e => getComputedStyle(e).writingMode") == "vertical-rl"
        )
        browser.close()
    assert actual == expected


@pytest.mark.parametrize("selector", ["section", ".site", "#subject", "section.site:hover"])
def test_known_non_context_compounds_need_no_guard(selector):
    from lumen_ingestion.sections.rootunits import prepare_root_units
    from lumen_ingestion.sections.source_context import SourceDocumentContext

    context = SourceDocumentContext.prepare(
        HTML, [_Sheet("s.css", BASE)], prepare_root_units([], html=HTML)
    )
    section = context.for_section(context.tree.css_first("#subject"))
    assert section.guard_selector(selector) == selector


@pytest.mark.parametrize(
    "selector", ["*", ":first-child", "[lang]", ":not(.site)", ":is(section,*)"]
)
def test_ambiguous_context_compounds_keep_zero_specificity_guard(selector):
    from lumen_ingestion.sections.rootunits import prepare_root_units
    from lumen_ingestion.sections.source_context import SourceDocumentContext

    context = SourceDocumentContext.prepare(
        HTML, [_Sheet("s.css", BASE)], prepare_root_units([], html=HTML)
    )
    section = context.for_section(context.tree.css_first("#subject"))
    assert section.guard in section.guard_selector(selector)


def test_context_keeps_dormant_root_unhide_and_local_language(monkeypatch):
    html = HTML.replace('lang="en"', "").replace(
        'id="subject"', 'id="subject" style="display:none!important"'
    )
    artifact, row = _artifact(html, BASE + "#subject{display:none} #nested{display:none}")
    assert row["status"] == "dormant"
    assert row["provenance"]["hidden_on_source"]["unhidden_selectors"] == ["#subject"]
    delivery = _real_core(monkeypatch).web_render(
        isolation_web_doc(artifact.fragment_id),
        "home",
        mode="delivery",
        fragments={artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}},
        fragment_css=artifact.payload["css"],
    )["html"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(delivery)
        page.evaluate('document.documentElement.lang="fr"')
        assert page.eval_on_selector("#subject", "e=>getComputedStyle(e).display") == "block"
        assert page.eval_on_selector("#nested", "e=>getComputedStyle(e).display") == "none"
        assert not page.eval_on_selector("#copy", 'e=>e.matches(":lang(fr)")')
        for selector in ("section", ".site", "#subject", "section.site:hover"):
            assert page.eval_on_selector_all(
                "ls-h,ls-b", "(nodes,selector)=>nodes.every(n=>!n.matches(selector))", selector
            )
        browser.close()


@pytest.mark.parametrize(
    "attrs, owner", [('dir="rtl"', "html"), ('lang="ar"', "body"), ('dir="auto"', "html")]
)
def test_document_attributes_alone_activate_source_context(attrs, owner):
    html = HTML.replace(' lang="en"', "").replace("<" + owner, "<" + owner + " " + attrs, 1)
    _, row = _artifact(html, "section{color:red}")
    context = row["provenance"]["css"]["source_document_context"]
    assert context["mode"] == "source-html-body-inheritance"
    if "auto" in attrs:
        assert any("dir=auto" in note for note in context["limitations"])


def test_authored_direction_overrides_document_attribute_hints(monkeypatch):
    html = HTML.replace("<html ", '<html dir="rtl" ').replace("<body ", '<body dir="rtl" ')
    css = BASE + "html,body{direction:ltr}"
    artifact, _ = _artifact(html, css)
    delivery = _real_core(monkeypatch).web_render(
        isolation_web_doc(artifact.fragment_id),
        "home",
        mode="delivery",
        fragments={artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}},
        fragment_css=artifact.payload["css"],
    )["html"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(html.replace("</head>", f"<style>{css}</style></head>"))
        assert page.eval_on_selector("#copy", "e=>getComputedStyle(e).direction") == "ltr"
        page.set_content(delivery)
        assert page.eval_on_selector("#copy", "e=>getComputedStyle(e).direction") == "ltr"
        browser.close()


@pytest.mark.parametrize(
    "document_css, root_style, width, expected_width, expected_sizing",
    [
        pytest.param("html{box-sizing:border-box}", "", 1440, 100, "border-box", id="root"),
        pytest.param("", "", 1440, 160, "content-box", id="absent-root"),
        pytest.param(
            "html,body{box-sizing:var(--missing,inherit)} html{box-sizing:border-box}",
            "",
            1440,
            100,
            "border-box",
            id="shared-rule-keeps-body-inheritance",
        ),
        pytest.param(
            "html{box-sizing:var(--missing,inherit)}",
            "",
            1440,
            160,
            "content-box",
            id="missing-var-inherit",
        ),
        pytest.param(
            "html{box-sizing:var(--missing,var(--other,inherit))}",
            "",
            1440,
            160,
            "content-box",
            id="nested-var-inherit",
        ),
        pytest.param(
            "html{--box:border-box;box-sizing:var(--box,inherit)}",
            "",
            1440,
            100,
            "border-box",
            id="present-var-wins",
        ),
        pytest.param(
            "html{--box:inherit;box-sizing:var(--box)}",
            "",
            1440,
            160,
            "content-box",
            id="unset-custom-property",
        ),
        pytest.param(
            "html{box-sizing:var(--missing,inherit)!important}html[lang]{box-sizing:border-box}",
            "",
            1440,
            160,
            "content-box",
            id="var-inherit-important",
        ),
        pytest.param("html{box-sizing:content-box}", "", 1440, 160, "content-box", id="content"),
        pytest.param(
            "html{box-sizing:border-box} body{box-sizing:content-box}",
            "",
            1440,
            160,
            "content-box",
            id="body-content",
        ),
        pytest.param(
            "html{box-sizing:content-box} body{box-sizing:border-box}",
            "",
            1440,
            100,
            "border-box",
            id="body-border",
        ),
        pytest.param(
            "html{box-sizing:content-box}",
            "box-sizing:border-box",
            1440,
            100,
            "border-box",
            id="inline-root",
        ),
        pytest.param(
            "html{box-sizing:border-box} @media(max-width:600px){html{box-sizing:content-box}}",
            "",
            1440,
            100,
            "border-box",
            id="media-desktop",
        ),
        pytest.param(
            "html{box-sizing:border-box} @media(max-width:600px){html{box-sizing:content-box}}",
            "",
            375,
            160,
            "content-box",
            id="media-mobile",
        ),
        pytest.param(
            "html{box-sizing:border-box!important} html[lang]{box-sizing:content-box}",
            "",
            1440,
            100,
            "border-box",
            id="important",
        ),
        pytest.param(
            "@layer base{html{box-sizing:border-box!important}}"
            "@layer override{html{box-sizing:content-box}}",
            "",
            1440,
            100,
            "border-box",
            id="layer-priority",
        ),
        pytest.param(
            "html{box-sizing:border-box} #copy{box-sizing:content-box}",
            "",
            1440,
            160,
            "content-box",
            id="local-override",
        ),
    ],
)
def test_source_box_sizing_survives_removal_of_host_defaults(
    monkeypatch, document_css, root_style, width, expected_width, expected_sizing
):
    html = HTML.replace('<html lang="en">', f'<html lang="en" style="{root_style}">')
    css = (
        document_css
        + " *,*::before,*::after{box-sizing:inherit}"
        + " #copy,#copy::before{width:100px;padding:20px;border:10px solid black}"
        + ' #copy::before{content:"";display:block}'
    )
    artifact, row = _artifact(html, css)
    if "@layer" in document_css:
        limits = row["provenance"]["css"]["source_document_context"]["limitations"]
        assert any("layer ranking" in note for note in limits)
    # The real renderer leaves source descendants to their captured/browser defaults.
    # Its native wrapper still uses border-box; the source context must supply its own
    # document box model instead of inheriting that host fallback.
    delivery = _real_core(monkeypatch).web_render(
        isolation_web_doc(artifact.fragment_id),
        "home",
        mode="delivery",
        fragments={artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}},
        fragment_css=artifact.payload["css"],
    )["html"]
    measure = """() => {const el=document.querySelector('#copy');
      return {width:el.getBoundingClientRect().width,
        sizing:getComputedStyle(el).boxSizing,
        pseudoSizing:getComputedStyle(el,'::before').boxSizing}}"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.route("**/*", lambda route: route.abort())
        page.set_content(html.replace("</head>", f"<style>{css}</style></head>"))
        source = page.evaluate(measure)
        page.set_content(delivery)
        actual = page.evaluate(measure)
        browser.close()
    assert source == {
        "width": expected_width,
        "sizing": expected_sizing,
        "pseudoSizing": expected_sizing,
    }
    assert actual == source


def test_box_sizing_support_does_not_transport_document_layout_or_paint():
    _, row = _artifact(
        HTML,
        "html{box-sizing:border-box;width:123px;background:red} "
        "*,*::before,*::after{box-sizing:inherit}",
    )
    limits = row["provenance"]["css"]["source_document_context"]["limitations"]
    omitted = next(note for note in limits if note.startswith("omitted document layout/paint"))
    assert "width" in omitted
    assert "background" in omitted
    assert "box-sizing" not in omitted


def test_source_box_sizing_excessive_var_fallback_depth_is_explicit():
    # A bounded projection must retain unhandled source CSS and name the gap.
    value = "inherit"
    for _ in range(33):
        value = f"var(--missing,{value})"
    _, row = _artifact(HTML, f"html{{box-sizing:{value}}}")
    context = row["provenance"]["css"]["source_document_context"]
    assert any("box-sizing var fallback nesting" in note for note in context["limitations"])
    assert f"box-sizing:{value}" in row["css"]
