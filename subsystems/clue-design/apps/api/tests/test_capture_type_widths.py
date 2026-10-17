"""Responsive brand type, Task 1: the capture's last pass narrows the same page and re-reads the type
samples it already took. Offline: file:// pages, Playwright's and patchright's Chromium."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lumen_ingestion.capture.rendered import _EVALUATE_JS, _SERIALIZE_HTML_JS
from lumen_ingestion.capture.type_widths import media_query_widths, measure_type_widths, type_measure_widths

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "capture" / "type_widths"
ENGINES = ["playwright", "patchright"]


def test_media_query_widths_reads_max_and_min_width() -> None:
    css = ["@media (max-width: 991px){h2{font-size:40px}}", "@media screen and (min-width:48em){p{font-size:18px}}", "@media print{}"]
    assert media_query_widths(css) == [991, 767]


def test_measure_widths_stay_below_the_capture_width() -> None:
    assert type_measure_widths(1280, [991, 1440, 300, 479]) == [1024, 991, 768, 479, 390], "widest first"
    assert type_measure_widths(390, [991]) == []
    many = type_measure_widths(1440, [1300, 1200, 1100, 1000, 950, 900, 850, 800, 700, 600, 500, 450])
    assert len(many) == 8 and {1024, 768, 390} <= set(many)


async def _measure(engine: str, fixture: str) -> dict:
    if engine == "patchright":
        from patchright.async_api import async_playwright
    else:
        from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"{engine} chromium unavailable: {error}")
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto((FIXTURES / fixture).as_uri())
            data = await page.evaluate(_EVALUATE_JS)
            html_before = await page.evaluate(_SERIALIZE_HTML_JS)
            diagnostics: list[dict] = []
            widths = await measure_type_widths(page, data["sheets"], diagnostics)
            html_after = await page.evaluate(_SERIALIZE_HTML_JS)
        finally:
            await browser.close()
    return {"data": data, "widths": widths, "diagnostics": diagnostics, "html": (html_before, html_after)}


def _read(result: dict, width: int, selectorish: str, nth: int = 0) -> dict | None:
    indexes = [i for i, s in enumerate(result["data"]["samples"]) if s["selectorish"] == selectorish]
    entry = next(w for w in result["widths"]["widths"] if w["width"] == width)
    return entry["samples"][indexes[nth]]


@pytest.mark.parametrize("engine", ENGINES)
def test_a_stepping_page_is_read_at_each_width(engine: str) -> None:
    result = asyncio.run(_measure(engine, "steps.html"))
    assert result["widths"]["capture_width"] == 1440
    assert [w["width"] for w in result["widths"]["widths"]] == [1024, 991, 767, 390], "widest first; 768 gives way to 767"
    assert _read(result, 991, "h2")["fontSize"] == "40px"
    assert _read(result, 767, "h2")["fontSize"] == "34px"
    assert _read(result, 390, "h2")["fontSize"] == "34px"
    assert _read(result, 390, "body")["fontSize"] == "16px"
    assert next(s for s in result["data"]["samples"] if s["selectorish"] == "h2")["fontSize"] == "56px", "desktop untouched"


@pytest.mark.parametrize("engine", ENGINES)
def test_a_mobile_first_page_is_read_below_its_break_point(engine: str) -> None:
    result = asyncio.run(_measure(engine, "mobile_first.html"))
    assert 767 in [w["width"] for w in result["widths"]["widths"]]
    assert _read(result, 767, "body")["fontSize"] == "16px"
    assert _read(result, 767, "h2")["fontSize"] == "28px"


@pytest.mark.parametrize("engine", ENGINES)
def test_a_hidden_or_removed_sample_reads_none(engine: str) -> None:
    result = asyncio.run(_measure(engine, "hidden.html"))
    assert _read(result, 390, "h2", 0) is None, "display:none on phones"
    assert _read(result, 390, "h2", 1) is None, "removed by the page's script"
    assert _read(result, 1024, "h2", 0)["fontSize"] == "48px"
    assert _read(result, 390, "button") is None, "a label shrunk to font-size 0 sets no size (review 7)"


@pytest.mark.parametrize("engine", ENGINES)
def test_the_captured_html_is_unchanged_by_the_pass(engine: str) -> None:
    before, after = asyncio.run(_measure(engine, "steps.html"))["html"]
    assert before == after


def test_a_linked_stylesheet_is_fetched_for_its_break_points() -> None:
    async def run() -> list[int]:
        class Page:
            async def evaluate(self, script, *args):
                return {"innerWidth": 1440, "innerHeight": 900} if "innerWidth" in script else []
            async def set_viewport_size(self, size):
                return None
            async def wait_for_timeout(self, ms):
                return None
        seen: list[str] = []
        async def fetch_text(url: str) -> str | None:
            seen.append(url)
            return "@media (max-width: 600px){h1{font-size:20px}}"
        result = await measure_type_widths(Page(), [{"href": "https://cdn.example/site.css", "text": None}], [], fetch_text=fetch_text)
        assert seen == ["https://cdn.example/site.css"]
        return [w["width"] for w in result["widths"]]
    assert 600 in asyncio.run(run())


def test_bootstrap_and_tailwind_break_points_are_read_where_they_apply() -> None:
    """Review finding 1: fractional max-widths floor, min-widths ceil then step below; range syntax."""
    assert media_query_widths(["@media (max-width: 991.98px){}", "@media (max-width:767.98px){}"]) == [991, 767]
    assert media_query_widths(["@media (min-width: 768.02px){}"]) == [768]
    assert media_query_widths(["@media (width >= 48rem){}", "@media (width < 64rem){}"]) == [1023, 767]
    assert media_query_widths(["@media (width <= 991.98px){}", "@media (width > 767px){}"]) == [991, 767]
    assert media_query_widths(["@media (768px <= width){}", "@media (400px <= width <= 700px){}"]) == [767, 700, 399]


def test_a_fixed_width_next_to_a_break_point_gives_way() -> None:
    """Review finding 5: 768 beside 767 and 1024 beside 1023 are the same tier; keep the seller's."""
    widths = type_measure_widths(1920, [1919, 1679, 1439, 1365, 1279, 1023, 991, 767])
    assert 1024 not in widths and 768 not in widths and {991, 767, 390} <= set(widths), widths
    assert widths == sorted(widths, reverse=True) and len(widths) <= 8


def test_a_private_or_huge_stylesheet_is_never_fetched() -> None:
    """Review finding 8: the capture's URL guard applies, and a body past the limit is not read."""
    from lumen_ingestion.capture import type_widths

    calls: list[str] = []

    class Response:
        ok = True
        headers = {"content-length": str(type_widths.SHEET_MAX_BYTES + 1)}
        async def body(self):
            calls.append("body")
            return b"@media (max-width: 600px){}"

    class Request:
        async def get(self, url, timeout=None):
            calls.append(url)
            return Response()

    class Page:
        request = Request()

    fetch = type_widths._page_fetcher(Page())
    assert asyncio.run(fetch("http://10.0.0.5/admin.css")) is None
    assert asyncio.run(fetch("file:///etc/passwd")) is None
    assert calls == [], "refused before any request"
    assert asyncio.run(fetch("https://example.com/big.css")) is None
    assert "body" not in calls, "a declared size past the limit is not downloaded"


def test_a_page_that_hangs_on_resize_costs_only_the_steps() -> None:
    """Review finding 9: the pass has an overall time limit and reports it."""
    from lumen_ingestion.capture.type_widths import measure_type_widths_safely

    class Page:
        async def evaluate(self, script, *args):
            await asyncio.sleep(60)

    diagnostics: list[dict] = []
    assert asyncio.run(measure_type_widths_safely(Page(), [], diagnostics, timeout=0.2)) is None
    assert [d["code"] for d in diagnostics] == ["LUMI0547"]


def test_only_the_entry_page_is_measured_at_other_widths(monkeypatch) -> None:
    """Review finding 4: secondary pages of a capture (measure_states False) skip the pass."""
    from lumen_ingestion.capture import rendered

    seen: list[bool] = []

    async def fake_measure(page, sheets, diagnostics, **kwargs):
        seen.append(True)
        return {"capture_width": 1440, "widths": []}

    async def nothing(*args, **kwargs):
        return None

    class Keyboard:
        async def press(self, key):
            return None

    class Page:
        url = "https://seller.example/"
        keyboard = Keyboard()
        async def evaluate(self, script, *args):
            return {"samples": [], "sheets": []} if script is rendered._EVALUATE_JS else None
        async def wait_for_timeout(self, ms):
            return None
        async def screenshot(self, **kwargs):
            return b""

    monkeypatch.setattr(rendered, "measure_type_widths_safely", fake_measure)
    monkeypatch.setattr(rendered, "_scroll_until_settled", nothing)
    monkeypatch.setattr(rendered, "_capture_html", lambda page: nothing())
    secondary = asyncio.run(rendered._harvest_page(Page(), [], measure_states=False))
    assert seen == [] and secondary["type_widths"] is None
    monkeypatch.setattr(rendered, "probe_states", nothing)
    asyncio.run(rendered._harvest_page(Page(), [], measure_states=True))
    assert seen == [True]
