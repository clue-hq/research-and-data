"""A reusable section must retain the styling accepted on its authoring page.

The synthetic four-state fixture exercises rich labels and responsive placement;
it is not a brand-quality benchmark or a generated customer page.
"""

import json

import pytest
from playwright.sync_api import expect, sync_playwright

from test_native_fragment_reuse import ArtifactRegistry, _render
from test_web_recreate_and_repair import PROOF_ID, _tools


CARD_CSS = """
.feature-switch {display:grid;gap:8px;grid-template-columns:minmax(0,1fr);}
.feature-switch > .lumen-tabs-list {display:contents;}
.feature-switch > .lumen-tabs-list > .lumen-tab {
  display:flex;flex-direction:column;text-align:left;gap:16px;padding:20px;
  border-radius:6px;opacity:1;background:rgb(230,230,230);color:rgb(20,20,20);
}
.feature-switch > .lumen-tabs-list > .lumen-tab[aria-selected="true"] {
  background:rgb(190,210,230);
}
.feature-number,.feature-title,.feature-description {display:block;}
.feature-number {font-size:12px;line-height:1.2;}
.feature-title {font-family:serif;font-size:24px;font-weight:400;line-height:1.1;}
.feature-description {font-size:16px;line-height:1.25;}
.feature-switch > [role="tabpanel"] {
  grid-column:1;grid-row:1;aspect-ratio:1.2;overflow:hidden;border-radius:6px;
}
.feature-switch > [role="tabpanel"][hidden] {display:none;}
@media(min-width:768px) and (max-width:1023px) {
 .feature-switch {grid-template-columns:repeat(2,minmax(0,1fr));}
 .feature-switch > [role="tabpanel"] {grid-column:1 / -1;}
}
@media(min-width:1024px) {
 .feature-switch {grid-template-columns:300px minmax(0,1fr) 300px;
                  grid-template-rows:1fr 1fr;height:420px;}
 .feature-switch > [role="tabpanel"] {grid-column:2;grid-row:1 / 3;aspect-ratio:auto;}
 .feature-switch > .lumen-tabs-list > .lumen-tab:nth-child(1) {grid-column:1;grid-row:1;}
 .feature-switch > .lumen-tabs-list > .lumen-tab:nth-child(2) {grid-column:1;grid-row:2;}
 .feature-switch > .lumen-tabs-list > .lumen-tab:nth-child(3) {grid-column:3;grid-row:1;}
 .feature-switch > .lumen-tabs-list > .lumen-tab:nth-child(4) {grid-column:3;grid-row:2;}
}
"""


def rich_tab_markup():
    items = "".join(
        f'<div id="item_{i}"><p><span class="feature-number">0{i + 1}</span>'
        f'<span class="feature-title">Capability {i + 1}</span>'
        '<span class="feature-description">A useful explanation of this state.</span>'
        f'</p><p>Panel {i}</p></div>' for i in range(4)
    )
    return ('<section id="feature"><div id="switcher" class="feature-switch" '
            'data-component="tabs">' + items + '</div></section>')


def _styles(group):
    return group.evaluate("""e => ({
      layout:getComputedStyle(e).display,
      title:[...e.querySelectorAll('.feature-title')].map(x => {
        const s=getComputedStyle(x);
        return [s.display,s.fontFamily,s.fontSize,s.fontWeight,s.lineHeight];
      }),
      controls:[...e.querySelectorAll('[role="tab"]')].map(x => {
        const s=getComputedStyle(x);
        return [x.getAttribute('aria-selected'),s.backgroundColor,s.color,s.opacity,s.borderRadius,s.padding];
      }),
      boxes:[...e.querySelectorAll('[role="tab"], [role="tabpanel"]:not([hidden])')]
        .map(x => {const r=x.getBoundingClientRect(),o=e.getBoundingClientRect();
          return [r.x-o.x,r.y-o.y,r.width,r.height];}),
      overflowing:e.scrollWidth > e.clientWidth
    })""")


def test_custom_card_styles_survive_repair_and_repeated_pin(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    registry.add(PROOF_ID, role="features", label="Inert fixture", index=0,
                 degraded=True, degraded_reason="missing_controller")
    authored = _tools(tmp_path / "author", registry)
    assert json.loads(authored.author_web_page(
        '<section id="seed"><p>Fixture</p></section>', custom_css=CARD_CSS,
    ))["status"] == "ok"
    assert json.loads(authored.insert_cloned_section(PROOF_ID))["status"] == "ok"
    result = json.loads(authored.repair_cloned_section(
        PROOF_ID, rich_tab_markup(), 2, "Offline rich-label regression",
    ))
    assert result["status"] == "ok", result
    fid = result["repair_fragment_id"]
    original = _render(authored)
    assert json.loads(authored.release_repair(fid))["status"] == "ok"
    pinned = _tools(tmp_path / "pin", registry)
    # Same class outside the repair must not acquire its scoped styles.
    assert json.loads(pinned.author_web_page(
        '<section id="outside"><p><span class="feature-title">Outside</span></p></section>',
    ))["status"] == "ok"
    for _ in range(2):
        assert json.loads(pinned.insert_cloned_section(fid))["status"] == "ok"
    delivered = _render(pinned)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for width in (1440, 768, 375):
                pages = [browser.new_page(viewport={"width": width, "height": 900})
                         for _ in range(2)]
                for page, html in zip(pages, (original, delivered), strict=True):
                    page.route("**/*", lambda route: route.abort())
                    page.emulate_media(reduced_motion="reduce")
                    page.set_content(html, wait_until="domcontentloaded")
                before = pages[0].locator(".feature-switch")
                groups = pages[1].locator(".feature-switch")
                assert groups.count() == 2
                assert _styles(before)["layout"] == "grid"
                assert not _styles(before)["overflowing"]
                for i in range(4):
                    before.get_by_role("tab").nth(i).click()
                    groups.nth(1).get_by_role("tab").nth(i).click()
                    assert groups.nth(1).get_by_role("tabpanel").inner_text() == f"Panel {i}"
                    assert groups.nth(0).get_by_role("tabpanel").inner_text() == "Panel 0"
                    # Even reduced-motion CSS settles on a later style frame.
                    for group in (before, groups.nth(1)):
                        for index in range(4):
                            expect(group.get_by_role("tab").nth(index)).to_have_css(
                                "background-color",
                                "rgb(190, 210, 230)" if index == i else "rgb(230, 230, 230)",
                            )
                    # Compare the actual pre-mint render, not a second CSS implementation.
                    assert _styles(groups.nth(1)) == _styles(before)
                groups.nth(1).get_by_role("tab").nth(3).press("ArrowRight")
                assert groups.nth(1).get_by_role("tabpanel").inner_text() == "Panel 0"
                assert groups.nth(0).get_by_role("tabpanel").inner_text() == "Panel 0"
                assert pages[1].get_by_text("Outside", exact=True).evaluate(
                    "e => getComputedStyle(e).display"
                ) == "inline"
                for page in pages:
                    page.close()
        finally:
            browser.close()


@pytest.mark.parametrize("css", [
    "#item_0_tab {color:red}",
    ".feature-switch :is(#item_0_tab) {color:red}",
    '.feature-switch [id^="item_"] {color:red}',
    '.feature-switch [aria-controls="item_0_panel"] {color:red}',
    ".feature-title {clip-path:url(#item_0_panel)}",
    '.feature-title {clip-path:url("#item_0_panel")}',
    "@page {size:A5}",
    '@property --foreign {syntax:"<color>";inherits:true;initial-value:red}',
    '@font-face {font-family:Foreign;src:local(Arial)}',
    '@counter-style other {system:cyclic;symbols:"*"}',
    "@media (min-width:1px) {@layer utilities {.p-5 {padding:0}}}",
    ".feature-title {--motion:pulse;animation:var(--motion) 1s infinite}"
    "@keyframes pulse {to {opacity:.5}}",
])
def test_nonportable_custom_styles_refuse_mint_without_losing_typed_section(tmp_path, css):
    registry = ArtifactRegistry(tmp_path)
    registry.add(PROOF_ID, role="features", label="Inert fixture", index=0,
                 degraded=True, degraded_reason="missing_controller")
    authored = _tools(tmp_path / "author", registry)
    assert json.loads(authored.author_web_page(
        '<section id="seed"><p>Fixture</p></section>', custom_css=css,
    ))["status"] == "ok"
    assert json.loads(authored.insert_cloned_section(PROOF_ID))["status"] == "ok"
    result = json.loads(authored.repair_cloned_section(
        PROOF_ID, rich_tab_markup(), 2, "Offline nonportable CSS fixture",
    ))
    assert result["status"] == "error", result
    assert result["error_code"] == "repair.css_compile_failed"
    assert "reusable section" in result["message"]
    assert not registry.mint_calls
    assert "Capability 1" in _render(authored)
