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
