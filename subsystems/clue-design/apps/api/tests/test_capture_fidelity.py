"""Brand capture fidelity (review findings S6-1 to S6-12): the real capture — GEOMETRY_JS, the state
pass, parse_geometry, attach_keyframes, the minter — over local pages, in Playwright's and
patchright's Chromium. Offline: file:// pages only, no model, no network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lumen_ingestion.capture.geometry import GEOMETRY_JS, parse_geometry
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.capture.states import REVEAL_BEFORE_JS, probe_states
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "capture" / "fidelity"
GARNER = TESTS / "fixtures" / "ingestion" / "garner_kit.json"
ENGINES = ["playwright", "patchright"]


async def _capture(engine: str, fixture: str, extra_js: str | None = None) -> dict:
    if engine == "patchright":
        from patchright.async_api import async_playwright
    else:
        from playwright.async_api import async_playwright
    diagnostics: list[dict] = []
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"{engine} chromium unavailable: {error}")
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto((FIXTURES / fixture).as_uri())
            await page.wait_for_timeout(800)
            reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
            await page.evaluate("window.scrollTo(0, 0)")
            geometry = await page.evaluate(GEOMETRY_JS)
            extra = await page.evaluate(extra_js) if extra_js else None
            geometry["states"] = await probe_states(page, geometry, reveal_before=reveal_before, diagnostics=diagnostics)
        finally:
            await browser.close()
    return {"geometry": geometry, "diagnostics": diagnostics, "extra": extra}


def _css(fixture: str) -> str:
    text = (FIXTURES / fixture).read_text()
    return text.split("<style>", 1)[1].split("</style>", 1)[0]


def _run(engine: str, fixture: str, extra_js: str | None = None) -> dict:
    captured = asyncio.run(_capture(engine, fixture, extra_js))
    parsed = parse_geometry(captured["geometry"], page_url=f"https://{fixture}/")
    motion = attach_keyframes(parsed.motion, [Stylesheet(url=f"https://{fixture}/", text=_css(fixture))])
    kit = json.loads(GARNER.read_text())
    minted = mint_component_tokens(kit, parsed.styles, motion)
    return {"captured": captured, "parsed": parsed, "motion": motion, "kit": kit, "minted": minted}


def _buttons(run: dict) -> dict[str, object]:
    return {s.variant: s for s in run["parsed"].styles if s.surface == "button"}


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_3_oklch_buttons_keep_their_own_fills_and_hovers(engine: str) -> None:
    buttons = _buttons(_run(engine, "tailwind_v4.html"))
    assert "solid.155dfc" in buttons and "solid.00a63e" in buttons, sorted(buttons)
    assert "ghost.none" not in buttons, sorted(buttons)
    assert buttons["solid.155dfc"].rest.background == "#155DFC"
    assert buttons["solid.155dfc"].hover is not None and buttons["solid.155dfc"].hover.background == "#1447E6"
    assert buttons["solid.047464"].hover is not None and buttons["solid.047464"].hover.background is not None


def test_s6_3_an_oklch_band_is_a_band_with_its_oklch_text() -> None:
    # tailwind_v4.html's band sits outside <main>, where the section reader never looks, so the band
    # case is its own page: two sections in <main>, the first painted in oklch.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(
                '<body style="margin:0"><main>'
                '<section style="background:oklch(0.21 0.034 264.665);color:oklch(0.985 0 0);min-height:240px">'
                '<h2>The statement band</h2><p>Light text on a dark band, written in oklch.</p></section>'
                '<section style="min-height:240px"><p>Next.</p></section></main></body>'
            )
            geometry = page.evaluate(GEOMETRY_JS)
        finally:
            browser.close()
    band = parse_geometry(geometry, page_url="https://oklch.test/").background_sequence[0]
    assert (band.background, band.ink) == ("#101828", "#FAFAFA")


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_7_a_fully_transparent_fill_is_an_outline_not_a_filled_look(engine: str) -> None:
    variants = sorted(_buttons(_run(engine, "clear_fill.html")))
    assert "outline.ffffff" in variants and "outline.f5a623" in variants, variants
    assert not any(v.startswith("solid.ffffff00") for v in variants), variants


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_1_a_bands_text_colour_is_its_heading_and_body_not_an_eyebrow_or_a_card(engine: str) -> None:
    bands = {b.background: b.ink for b in _run(engine, "band_ink.html")["parsed"].background_sequence}
    assert bands.get("#F3F0E8") == "#333333", bands   # the body copy outweighs the orange eyebrow
    assert bands.get("#0B2545") == "#FFFFFF", bands   # the white card's text is not on the navy band


def test_behind_of_composites_translucent_layers_and_skips_alpha_zero() -> None:
    from playwright.sync_api import sync_playwright

    from lumen_ingestion.capture.geometry import COLOR_FN

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<div id="band" style="background:#0B2545"><div id="clear" style="background:rgba(255,255,255,0)">'
                '<div id="glass" style="background:rgba(255,255,255,0.5)"><p id="t">x</p></div></div></div>'
            )
            got = page.evaluate("() => {" + COLOR_FN + "return [behindOf(document.getElementById('clear')), behindOf(document.getElementById('t'))]; }")
        finally:
            browser.close()
    assert got[0] == "#0B2545"
    assert got[1] == "#8592A2"   # 50% white over #0B2545, rounded per channel


def test_s6_1_a_band_whose_only_text_sits_in_a_card_has_no_ink() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(
                '<body style="margin:0"><main>'
                '<section style="background:#0B2545;min-height:240px"><div style="background:#fff;color:#222;padding:24px">'
                '<p>Only a quote, in a white card.</p></div></section>'
                '<section style="min-height:240px"><p>Next.</p></section></main></body>'
            )
            geometry = page.evaluate(GEOMETRY_JS)
        finally:
            browser.close()
    band = parse_geometry(geometry, page_url="https://card.test/").background_sequence[0]
    assert (band.background, band.ink) == ("#0B2545", None)


def test_a_page_that_paints_no_background_is_drawn_on_white() -> None:
    from playwright.sync_api import sync_playwright

    from lumen_ingestion.capture.geometry import COLOR_FN

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('<p id="t">plain</p>')
            got = page.evaluate("() => {" + COLOR_FN + "return behindOf(document.getElementById('t')); }")
        finally:
            browser.close()
    assert got == "#FFFFFF"


def test_s6_1_screen_reader_only_text_does_not_set_a_bands_ink() -> None:
    from playwright.sync_api import sync_playwright

    hidden = "Opens in a new window. Skip to main content. This label is read aloud by screen readers and never painted."
    sr_only = (
        "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;"
        "clip:rect(0,0,0,0);white-space:nowrap;border-width:0;color:#FF0000"
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(
                '<body style="margin:0"><main>'
                f'<section style="background:#F3F0E8;min-height:240px"><span style="{sr_only}">{hidden}</span>'
                '<p style="color:#333333">Body copy.</p></section>'
                '<section style="min-height:240px"><p>Next.</p></section></main></body>'
            )
            geometry = page.evaluate(GEOMETRY_JS)
        finally:
            browser.close()
    band = parse_geometry(geometry, page_url="https://sr-only.test/").background_sequence[0]
    assert (band.background, band.ink) == ("#F3F0E8", "#333333")


def _icons(run: dict) -> dict[str, str]:
    return {s.variant: s.icon.svg for s in run["parsed"].styles if s.surface == "button" and s.icon and s.icon.svg}


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_2_a_css_stroked_icon_keeps_its_stroke_and_follows_the_label(engine: str) -> None:
    icons = _icons(_run(engine, "icons.html"))
    stroke = icons["solid.ad1457"]
    root = stroke.split(">", 1)[0]
    assert 'fill="none"' in root and 'stroke="currentColor"' in root and 'stroke-width="2"' in root, stroke
    assert 'stroke-linecap="round"' in root and 'stroke-linejoin="round"' in root, stroke
    hero = icons["solid.00695c"]
    assert 'fill="currentColor"' in hero.split(">", 1)[0], hero


@pytest.mark.parametrize("engine", ENGINES)
def test_s6_10_a_sprite_icon_is_drawn_at_the_size_the_page_drew_it(engine: str) -> None:
    sprite = _icons(_run(engine, "icons.html"))["solid.283593"]
    assert 'viewBox="0 0 24 24"' in sprite and 'transform="translate(0 0) scale(2 2)"' in sprite, sprite


def test_the_captured_icons_draw_like_the_page() -> None:
    """Rendered on a dark button with white text, the captured markup paints white, at full size."""
    from playwright.sync_api import sync_playwright

    icons = _icons(_run("playwright", "icons.html"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            out = {}
            for variant, markup in icons.items():
                sized = markup.replace("<svg", '<svg width="16" height="16"', 1)
                page.set_content(f'<div style="color:#fff;background:#222">{sized}</div>')
                out[variant] = page.evaluate("""() => { const p = document.querySelector('path');
                  const cs = getComputedStyle(p); const r = p.getBoundingClientRect();
                  return { fill: cs.fill, stroke: cs.stroke, w: Math.round(r.width) }; }""")
        finally:
            browser.close()
    assert out["solid.ad1457"]["stroke"] == "rgb(255, 255, 255)" and out["solid.ad1457"]["fill"] == "none", out
    assert out["solid.00695c"]["fill"] == "rgb(255, 255, 255)", out
    assert out["solid.283593"]["w"] >= 11, out   # the 12-unit arrow scaled into the 24-unit box: ~12px of 16


def test_an_icon_painted_through_a_gradient_or_in_a_translucent_colour_is_still_kept() -> None:
    from playwright.sync_api import sync_playwright

    from lumen_ingestion.capture.motion import clean_icon_svg
    from lumen_ingestion.capture.states import MOTION_JS

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<a id="b" href="#" style="color:#fff;background:#222;padding:12px 24px">Go '
                '<svg viewBox="0 0 24 24" style="width:16px;height:16px"><defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs>'
                '<path d="M5 12h14" style="fill:url(#g);stroke:rgba(255,255,255,0.5);stroke-width:2"/></svg></a>'
            )
            info = page.locator("#b").evaluate(MOTION_JS)["icon"]
        finally:
            browser.close()
    cleaned = clean_icon_svg(info["svg"])
    assert cleaned is not None and "url(" not in cleaned, info["svg"]
    assert 'stroke="#FFFFFF80"' in cleaned, cleaned
