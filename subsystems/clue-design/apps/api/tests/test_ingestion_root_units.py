"""Source root units survive section extraction without changing the host document."""

from __future__ import annotations

import pytest
from lumen_api.fragments import build_fragment_artifact
from lumen_api.fragments.refs import fragment_wrapper_class
from playwright.sync_api import sync_playwright
from test_ingestion_section_mint import BANDED_PAGE, _mint, _Sheet

CSS = """
html { font-size: 62.5% }
body { font-size: 14px }
:root { --gap: 2rem }
h1 { font-size: 4rem; margin: 0 0 var(--gap); line-height: 1.1 }
section { padding: 1rem }
p { font-size: 1.6rem }
@media (max-width: 40rem) {
  html { font-size: 75% }
  h1 { font-size: 2.8rem }
}
@keyframes travel { to { transform: translateX(2rem) } }
p { animation: travel 1s -1s paused forwards }
"""
HTML = BANDED_PAGE.replace("<h1>", '<h1 style="padding-top:1.2rem">')


@pytest.mark.parametrize("width", [1440, 600, 375])
def test_minted_root_units_match_source_at_responsive_widths(width):
    outcome, recorder = _mint(HTML, stylesheets=[_Sheet("s.css", CSS)])
    assert len(outcome.minted) == 4
    hero = recorder.created[1]
    artifact = build_fragment_artifact(
        html=hero["html"],
        css=hero["css"],
        rehosted={},
        slots=hero["slots"],
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.set_content(f"<style>{CSS}</style>{HTML}")
        source = _measure(page)
        page.set_content(
            "<style>html{font-size:20px}body{margin:0}</style>"
            f"<style>{artifact.payload['css']}</style>"
            '<div id="host">Host content</div>'
            f'<div class="{fragment_wrapper_class(artifact.fragment_id)}">'
            f"{artifact.payload['html']}</div>"
        )
        assert page.eval_on_selector("html", "el => getComputedStyle(el).fontSize") == "20px"
        assert page.eval_on_selector("#host", "el => getComputedStyle(el).fontSize") == "20px"
        assert _measure(page) == source
        browser.close()


def _measure(page):
    return page.evaluate("""() => {
      const h = getComputedStyle(document.querySelector('h1'));
      const p = getComputedStyle(document.querySelector('section p'));
      return {size:h.fontSize, line:h.lineHeight, gap:h.marginBottom,
        inlinePadding:h.paddingTop, bodySize:p.fontSize, animation:p.transform};
    }""")


def test_geometry_measures_initial_font_independently_of_source_styles():
    from lumen_ingestion.capture.geometry import GEOMETRY_JS

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<style>html{font-size:62.5%}*{font-size:32px}</style><h1>Source</h1>")
        before = page.content()
        result = page.evaluate(GEOMETRY_JS)
        assert result["initial_font_px"] == 16
        assert result["root_font_px"] == 10
        assert page.content() == before
        browser.close()


@pytest.mark.parametrize(
    "css",
    [
        ":root {font-size:12px} html {font-size:10px}",
        "@layer theme {html {font-size:10px}}",
        "html {font-size:var(--size)}",
        "html {font:12px sans-serif}",
        "html.big {font-size:20px}",
    ],
)
def test_unsupported_root_cascades_are_reported_without_guessing(css):
    from lumen_ingestion.sections.rootunits import prepare_root_units

    sheets = [_Sheet("s.css", css)]
    plan = prepare_root_units(sheets, html=HTML)
    assert plan.variable is None
    assert plan.notes
    assert plan.stylesheets is sheets


def test_unit_transport_keeps_strings_urls_and_query_thresholds_unchanged():
    from lumen_ingestion.sections.rootunits import prepare_root_units

    css = """html {font-size:10px} h1 {content:"4rem";background:url("4rem.png")}
      @media (min-width:40rem) {h1 {margin:calc(2rem + 5px)}}"""
    plan = prepare_root_units([_Sheet("s.css", css)], html=HTML)
    result = "\n".join(s.text for s in plan.stylesheets)
    assert '"4rem"' in result and '"4rem.png"' in result
    assert "(min-width:40rem)" in result
    assert "var(" in result
    assert plan.markup("<p style=\"content: '3rem';margin:1rem\">hello</p>").count("3rem") == 1


def test_source_inputs_are_immutable_and_captured_initial_size_is_used():
    from lumen_ingestion.sections.rootunits import prepare_root_units

    sheets = [_Sheet("s.css", "html{font-size:50%}p{font-size:2rem}")]
    plan = prepare_root_units(sheets, html=HTML, initial_font_px=18)
    assert sheets[0].text == "html{font-size:50%}p{font-size:2rem}"
    assert "9px" in plan.stylesheets[1].text
    assert plan.provenance()["initial_font_basis"] == "captured_browser_medium"


def test_unrehosted_images_still_refuse_after_unit_transport():
    outcome, _ = _mint(
        HTML,
        stylesheets=[
            _Sheet("s.css", "html{font-size:10px}h1{font-size:4rem;background:url(/missing.png)}")
        ],
    )
    assert any(d.get("reference") == "/missing.png" for d in outcome.diagnostics)


def test_unparseable_declaration_does_not_abort_whole_page_minting():
    outcome, _ = _mint(
        HTML, stylesheets=[_Sheet("s.css", "html{font-size:10px}h1{broken; font-size:4rem}")]
    )
    assert outcome.minted
    assert any(d.get("reason") == "unsupported_root_units" for d in outcome.diagnostics)
