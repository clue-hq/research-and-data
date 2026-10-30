"""What capture observed on an SVG is a fallback for clones and the full paint for logo files.

Capture used to stamp every observed SVG value inline with ``!important``. That kept lifted logos
from turning black, but it also beat every rule of the site's own that a clone carries: a pill's
arrow could never nudge on hover (Pallet's hero, 2026-10-28), an icon could never change colour,
and an icon shown only on phones was deleted because it was hidden at 1440 px.

Now capture records the observed values as data (``data-clue-svg-look`` on each element, the
values the page passed down to the root in ``data-clue-svg-context``). A logo lifted into its own
file bakes both back inline, as before. A clone turns the look into zero-specificity rules placed
before the site's own, so the site wins wherever its rules travelled with the clone.
"""

from __future__ import annotations

import asyncio

import pytest
from selectolax.parser import HTMLParser

from lumen_ingestion.capture import rendered
from lumen_ingestion.capture.svg_looks import (
    CONTEXT_ATTR,
    FALLBACK_ATTR,
    LOOK_ATTR,
    bake_svg_looks,
    lift_svg_looks,
    look_hides,
)


def _svg(markup: str):
    return HTMLParser(markup).css_first("svg")


# --------------------------------------------------------------------------- #
# Logo files: the look and the context are baked back inline
# --------------------------------------------------------------------------- #


def test_a_logo_file_bakes_the_context_and_the_look_inline() -> None:
    markup = (
        f'<svg viewBox="0 0 10 10" {CONTEXT_ATTR}="color: rgb(255, 255, 255)" '
        f'{LOOK_ATTR}="fill: rgb(255, 255, 255)">'
        f'<path d="M0 0H10V10H0Z" {LOOK_ATTR}="fill: rgb(255, 153, 0)"></path></svg>'
    )
    baked = _svg(bake_svg_looks(markup))
    assert LOOK_ATTR not in baked.attributes and CONTEXT_ATTR not in baked.attributes
    assert baked.attributes["style"] == (
        "color: rgb(255, 255, 255) !important; fill: rgb(255, 255, 255) !important"
    )
    assert baked.css_first("path").attributes["style"] == "fill: rgb(255, 153, 0) !important"


def test_a_logo_file_keeps_the_svgs_own_inline_style_and_drops_hidden_artwork() -> None:
    markup = (
        f'<svg style="width: 10px" {LOOK_ATTR}="opacity: 0.5">'
        f'<path d="M0 0H1V1H0Z"></path>'
        f'<path d="M0 0H9V9H0Z" {LOOK_ATTR}="display: none"></path></svg>'
    )
    baked = _svg(bake_svg_looks(markup))
    assert baked.attributes["style"] == "width: 10px; opacity: 0.5 !important"
    assert len(baked.css("path")) == 1


def test_an_svg_hidden_where_it_was_captured_is_known_to_be_hidden() -> None:
    assert look_hides(_svg(f'<svg {LOOK_ATTR}="display: none"></svg>').attributes)
    assert look_hides(_svg(f'<svg {LOOK_ATTR}="visibility: hidden"></svg>').attributes)
    assert not look_hides(_svg(f'<svg {LOOK_ATTR}="display: block"></svg>').attributes)
    assert not look_hides(_svg("<svg></svg>").attributes)


HEADER_WITH_A_HIDDEN_MOBILE_LOGO = (
    f'<html><body><header><a href="/">'
    f'<svg class="mobile-logo" {LOOK_ATTR}="display: none" width="80" aria-label="Acme">'
    f'<path d="M0 0H80V20H0Z" fill="red"></path></svg>'
    f'<svg class="logo" {LOOK_ATTR}="fill: rgb(255, 255, 255)" width="80" aria-label="Acme logo">'
    f'<path d="M0 0H80V20H0Z"></path><path d="M0 0H8V2H0Z"></path></svg>'
    f"</a></header></body></html>"
)


def test_both_logo_readers_skip_a_logo_hidden_at_capture_and_bake_the_visible_one() -> None:
    """Capture now keeps artwork hidden at 1440 px; a hidden logo must never become the brand's."""

    from lumen_ingestion import logo_ladder
    from lumen_ingestion.capture.parse import ParsedSite, _parse_primary_logo_candidates

    parsed = ParsedSite()
    _parse_primary_logo_candidates(None, HTMLParser(HEADER_WITH_A_HIDDEN_MOBILE_LOGO), parsed, "https://acme.test/")
    (inline,) = parsed._inline_svgs
    candidates = logo_ladder.harvest(HEADER_WITH_A_HIDDEN_MOBILE_LOGO, "https://acme.test/")
    ladder = [c.inline_svg_text for c in candidates if c.inline_svg_text]
    assert ladder
    for markup in [inline, *ladder]:
        svg = _svg(markup)
        assert svg.attributes["class"] == "logo"
        assert svg.attributes["style"] == "fill: rgb(255, 255, 255) !important"
        assert LOOK_ATTR not in markup


# --------------------------------------------------------------------------- #
# Clones: the look becomes fallback rules, the attributes leave the markup
# --------------------------------------------------------------------------- #


def test_a_clone_turns_each_look_into_a_zero_specificity_rule() -> None:
    markup = (
        f'<section><a class="pill"><svg class="arrow" {CONTEXT_ATTR}="color: rgb(1, 2, 3)" '
        f'{LOOK_ATTR}="fill: rgb(20, 20, 20); transform-origin: 5px 5px; transform: matrix(1, 0, 0, 1, 0, 0)">'
        f'<path d="M0 0H10V10H0Z"></path>'
        f'<path d="M0 0H5V5H0Z" {LOOK_ATTR}="fill: url(&quot;#grad&quot;)"></path>'
        f"</svg></a></section>"
    )
    html, css = lift_svg_looks(markup)
    assert LOOK_ATTR not in html and CONTEXT_ATTR not in html
    tree = HTMLParser(html)
    assert tree.css_first("svg").attributes[FALLBACK_ATTR] == "1"
    paths = tree.css("path")
    assert FALLBACK_ATTR not in paths[0].attributes
    assert paths[1].attributes[FALLBACK_ATTR] == "2"
    assert css == (
        f':where([{FALLBACK_ATTR}="1"]) {{ fill: rgb(20, 20, 20); transform-origin: 5px 5px; '
        "transform: matrix(1, 0, 0, 1, 0, 0) }\n"
        f':where([{FALLBACK_ATTR}="2"]) {{ fill: url("#grad") }}\n'
    )


def test_a_section_with_no_observed_svgs_is_left_byte_for_byte() -> None:
    markup = "<section><h1>Ship</h1><svg><path d=\"M0 0H1\"></path></svg></section>"
    assert lift_svg_looks(markup) == (markup, "")


def test_a_minted_clone_carries_its_fallback_rules_before_the_sites_own() -> None:
    from test_ingestion_section_mint import _BANDS, _Sheet, _mint

    page = (
        "<html><body>"
        '<header class="nav_component"><a href="/">Home</a><a href="/x">X</a></header>'
        '<main><section class="section_home-hero"><h1>Ship</h1>'
        f'<a class="pill" href="/go">Go <svg class="arrow" {LOOK_ATTR}="fill: rgb(20, 20, 20)" '
        f'{CONTEXT_ATTR}="color: rgb(20, 20, 20)" width="10"><path d="M0 0H10V10H0Z"></path></svg></a>'
        "</section>"
        '<section class="section_proof"><p>Trusted by</p></section></main>'
        '<footer class="footer_component"><p>&copy; 2026 Example</p></footer>'
        "</body></html>"
    )
    sheet = _Sheet("s.css", ".section_home-hero .pill:hover .arrow { transform: translate(2px, -2px) }")
    _, recorder = _mint(page, stylesheets=[sheet], bands=_BANDS)
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    assert f'{FALLBACK_ATTR}="1"' in hero["html"]
    assert LOOK_ATTR not in hero["html"] and CONTEXT_ATTR not in hero["html"]
    css = hero["css"]
    fallback = css.index(f':where([{FALLBACK_ATTR}="1"])')
    assert css.index(".pill:hover .arrow") > fallback, "the site's own rule comes after, so it wins"


# --------------------------------------------------------------------------- #
# End to end in a browser: capture, lift, and the site's own rules still win
# --------------------------------------------------------------------------- #

SITE_CSS = """
  body { color: rgb(17, 17, 17); }
  .pill { display: inline-flex; color: rgb(20, 20, 20); }
  .pill:hover { color: rgb(200, 0, 0); }
  .pill:hover .arrow { transform: translate(2px, -2px); }
  .arrow { fill: currentColor; }
  .burger { display: none; }
  @media (max-width: 600px) { .burger { display: block; } }
"""

PAGE = f"""<html><head><style>{SITE_CSS}</style></head><body>
<section id="s">
  <a class="pill" href="/x">Go <svg class="arrow" width="10" height="10"><path d="M0 0H10V10H0Z"/></svg></a>
  <svg class="burger" width="10" height="10"><path d="M0 0H10V10H0Z"/></svg>
</section></body></html>"""


def test_a_cloned_icon_still_moves_and_recolours_on_hover_and_a_phone_only_icon_survives() -> None:
    playwright = pytest.importorskip("playwright.async_api")

    async def check() -> None:
        async with playwright.async_playwright() as pw:
            try:
                browser = await pw.chromium.launch()
            except playwright.Error as error:
                if "Executable doesn't exist" in str(error):
                    pytest.skip("Chromium is required for the rendered SVG integration check")
                raise
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                await page.set_content(PAGE)
                html = await rendered._capture_html(page)
                section = HTMLParser(html).css_first("section").html
                assert section.count("<svg") == 2, "an icon hidden at 1440 px is kept"
                markup, fallback = lift_svg_looks(section)

                # The clone: fallback rules first, then the site's rules that travelled with it.
                await page.set_content(
                    f"<html><head><style>{fallback}</style><style>{SITE_CSS}</style></head>"
                    f"<body>{markup}</body></html>"
                )
                arrow = page.locator(".arrow")
                path = page.locator(".arrow path")
                assert await path.evaluate("n => getComputedStyle(n).fill") == "rgb(20, 20, 20)"
                await page.hover(".pill")
                assert await arrow.evaluate("n => getComputedStyle(n).transform") == (
                    "matrix(1, 0, 0, 1, 2, -2)"
                )
                assert await path.evaluate("n => getComputedStyle(n).fill") == "rgb(200, 0, 0)"
                await page.set_viewport_size({"width": 500, "height": 900})
                assert await page.locator(".burger").evaluate(
                    "n => getComputedStyle(n).display"
                ) == "block"

                # Where none of the site's rules travelled, the fallback keeps the observed look.
                await page.set_viewport_size({"width": 1440, "height": 900})
                await page.set_content(f"<html><head><style>{fallback}</style></head><body>{markup}</body></html>")
                assert await page.locator(".arrow path").evaluate(
                    "n => getComputedStyle(n).fill"
                ) == "rgb(20, 20, 20)"
                assert await page.locator(".burger").evaluate(
                    "n => getComputedStyle(n).display"
                ) == "none"
            finally:
                await browser.close()

    asyncio.run(check())
