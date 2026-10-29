"""Rendered logos must keep their observed paint after leaving page CSS."""

import asyncio

import pytest
from selectolax.parser import HTMLParser

from lumen_ingestion import logo_ladder
from lumen_ingestion.capture import rendered


@pytest.mark.parametrize("ink, expected", [("#fff", "rgb(255, 255, 255)"), ("#161d26", "rgb(22, 29, 38)")])
def test_rendered_svg_is_self_contained_without_changing_the_live_page(ink, expected):
    playwright = pytest.importorskip("playwright.async_api")

    async def check():
        async with playwright.async_playwright() as pw:
            try:
                browser = await pw.chromium.launch()
            except playwright.Error as error:
                if "Executable doesn't exist" in str(error):
                    pytest.skip("Chromium is required for the rendered SVG integration check")
                raise
            try:
                page = await browser.new_page()
                await page.set_content('''<html><head><style>
                  header { color: #fff; background: #123456; }
                  header a { color: inherit; }
                  .ink { fill: currentColor; }
                  .accent { fill: #ff9900; }
                  .hidden { display: none; }
                </style></head><body><header><a href="/">
                  <svg width="100" height="50" viewBox="0 0 100 50" aria-label="Example logo">
                    <path class="ink" d="M0 0H100V30H0Z"/>
                    <path class="accent" d="M0 40H100V50H0Z"/>
                    <path class="hidden" fill="black" d="M0 0H100V50H0Z"/>
                  </svg>
                </a></header></body></html>''')
                await page.locator('header').evaluate('(node, ink) => node.style.color = ink', ink)
                before = await page.content()
                html = await rendered._capture_html(page)
                assert await page.content() == before
                svg = HTMLParser(html).css_first('svg')
                # The capture keeps artwork hidden at this width (a clone's own rules may show it)...
                assert len(svg.css('path')) == 3
                candidates = logo_ladder.harvest(html, 'https://example.com/')
                logo_ladder.attach_bytes(candidates, {})
                candidate = next(c for c in candidates if c.inline_svg_text)
                # ...and the logo file leaves it out, as before.
                assert len(HTMLParser(candidate.body.decode()).css('svg path')) == 2
                # Verify the exported SVG in a fresh document WITHOUT the site's CSS.
                await page.set_content(candidate.body.decode())
                paints = await page.locator('svg path').evaluate_all(
                    '(nodes) => nodes.map(n => getComputedStyle(n).fill)'
                )
                assert paints == [expected, 'rgb(255, 153, 0)']
            finally:
                await browser.close()

    asyncio.run(check())
