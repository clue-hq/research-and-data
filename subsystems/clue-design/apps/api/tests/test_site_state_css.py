"""The kit's state and motion CSS survives the published-page cleaner and the script-free policy, and
a screenshot shows revealed content where a visitor sees it (Wave 2 A9, Task 16b)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from lumen_api.site_render import RenderedPage, capture_site_screenshot
from lumen_api.site_sanitize import sanitize_site_html

PAGE = (Path(__file__).resolve().parent / "fixtures" / "site" / "probe_page.html").read_text()
#: Contract 3's published-page policy, verbatim.
CSP = (
    "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; media-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'"
)


def test_the_cleaner_keeps_every_state_and_motion_rule_and_the_icon() -> None:
    cleaned = sanitize_site_html(PAGE)
    for needle in (
        ":hover{", ":active{", ":focus-visible{", '[aria-disabled="true"]{', "@keyframes brand-kf-",
        "@media (prefers-reduced-motion:reduce),print", "@supports (animation-timeline:view())",
        '<span aria-hidden="true" class="brand-btn-icon"><svg',
    ):
        assert needle in cleaned.html, needle
    assert not [note for note in cleaned.removed if "css" in note or "@import" in note]


def test_hover_is_drawn_under_the_published_policy() -> None:
    cleaned = sanitize_site_html(PAGE).html
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.route("https://site.test/", lambda route: route.fulfill(
                status=200, headers={"content-type": "text/html", "content-security-policy": CSP}, body=cleaned,
            ))
            page.goto("https://site.test/")
            button = page.locator("a.brand-btn")
            rest = button.evaluate("e => getComputedStyle(e).backgroundColor")
            button.hover()
            page.wait_for_timeout(400)
            hovered = button.evaluate("e => getComputedStyle(e).backgroundColor")
            icon = page.locator(".brand-btn-icon").evaluate("e => getComputedStyle(e).transform")
        finally:
            browser.close()
    assert (rest, hovered, icon) == ("rgb(4, 116, 100)", "rgb(3, 90, 78)", "matrix(1, 0, 0, 1, 4, 0)")


def test_a_screenshot_shows_revealed_content_in_place() -> None:
    cleaned = sanitize_site_html(PAGE).html
    png = capture_site_screenshot(RenderedPage(route="/", html=cleaned), "", width=1440, full_page=True)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    inside_box = image.height - max(1, round(60 * image.width / 1440))
    assert image.getpixel((image.width // 2, inside_box)) == (1, 64, 54)
