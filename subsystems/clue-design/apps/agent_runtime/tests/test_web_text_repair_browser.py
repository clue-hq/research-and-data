"""Offline engine/browser parity for captured styles and native disclosure after copy edits."""

import json

from playwright.sync_api import sync_playwright
from test_web_text_repair import prepare


def test_rendered_copy_edit_retains_source_typography_responsiveness_and_disclosure(tmp_path):
    registry, tools, _, edits = prepare(tmp_path)

    def render():
        return tools.core.web_render(
            tools.web_doc,
            "home",
            mode="delivery",
            fragments=tools._fragment_render_map(),
            fragment_css=tools._fragment_css(),
        )["html"]

    before = render()
    result = json.loads(
        tools.repair_cloned_section(
            registry.original,
            text_edits_json=json.dumps(edits),
            note="campaign variant: account handoff",
        )
    )
    assert result["status"] == "ok", result
    after = render()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for width in (1440, 768, 375):
                measurements = []
                for label, html in (("source", before), ("variant", after)):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.route("**/*", lambda route: route.abort())
                    page.set_content(html)
                    measurements.append(
                        page.locator(".features").evaluate("""el => {
                        const s=getComputedStyle(el), p=getComputedStyle(el.querySelector('p'));
                        return {family:p.fontFamily,size:p.fontSize,weight:p.fontWeight,
                                lineHeight:p.lineHeight,padding:s.padding,radius:s.borderRadius,
                                width:el.getBoundingClientRect().width,
                                overflow:document.documentElement.scrollWidth>innerWidth};
                    }""")
                    )
                    assert page.locator(".features h2").inner_text() == "Approved account headline"
                    assert page.locator(".features > p").inner_text() == (
                        edits[0]["expected"] if label == "source" else edits[0]["replacement"]
                    )
                    assert not page.locator("details p").is_visible()
                    page.locator("summary").click()
                    assert page.locator("details p").is_visible()
                    page.screenshot(path=str(tmp_path / f"{label}-{width}.png"), full_page=True)
                    page.close()
                assert measurements[0] == measurements[1]
                assert measurements[1]["size"] == ("18px" if width == 375 else "24px")
                assert measurements[1]["padding"] == ("16px" if width == 375 else "48px")
                assert measurements[1]["weight"] == "400"
                assert measurements[1]["radius"] == "12px"
                assert not measurements[1]["overflow"]
        finally:
            browser.close()
