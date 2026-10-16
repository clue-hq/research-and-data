"""CSS Color 4 colour functions read the way Chromium paints them (S6-3). Expected values are the
pixels Chromium 149 painted for each colour on 2026-10-16; the parity test re-asks the browser."""

from __future__ import annotations

import asyncio

import pytest

from lumen_ingestion.capture.geometry import _parse_box_shadow, _pointer
from lumen_ingestion.capture.parse import parse_color_value

PAINTED = {
    "oklch(0.546 0.245 262.881)": "#155DFC",   # Tailwind v4 blue-600
    "oklch(0.627 0.194 149.214)": "#00A63E",   # Tailwind v4 green-600
    "oklch(0.21 0.034 264.665)": "#101828",    # Tailwind v4 gray-900
    "oklch(0.623 0.214 259.815)": "#2B7FFF",
    "oklch(0.985 0 0)": "#FAFAFA",
    "oklch(0.7 0.4 30)": "#FF0000",            # out of gamut: clipped, as Chromium paints it
    "oklab(0.6 0.1 -0.1)": "#9F63BA",
    "lab(50 40 30)": "#BB5846",
    "lch(50 40 30)": "#B25D57",
    "hwb(120 10% 20%)": "#1ACC1A",
    "color(srgb 0.2 0.4 0.6)": "#336699",
    "color(display-p3 1 0 0)": "#FF0000",
}


@pytest.mark.parametrize("css, expected", sorted(PAINTED.items()))
def test_a_css_color4_colour_is_the_hex_chromium_paints(css: str, expected: str) -> None:
    assert parse_color_value(css, {}) == expected


def test_percentages_units_and_none_are_read() -> None:
    assert parse_color_value("oklch(54.6% 61.25% 262.881deg)", {}) == "#155DFC"
    assert parse_color_value("oklch(0.546 0.245 4.588rad)", {}) == "#155DFC"
    assert parse_color_value("oklch(0.985 0 none)", {}) == "#FAFAFA"


def test_alpha_is_kept_and_a_var_alpha_is_followed() -> None:
    opaque = parse_color_value("oklch(0.5 0.1 180)", {})
    assert parse_color_value("oklch(0.5 0.1 180 / 0.5)", {}) == opaque + "80"
    assert parse_color_value("oklch(0.5 0.1 180 / var(--a))", {"--a": "25%"}) == opaque + "40"


def test_an_unreadable_color4_value_is_one_skipped_swatch_with_a_reason() -> None:
    diagnostics: list[dict] = []
    assert parse_color_value("oklch(bogus 0 0)", {}, diagnostics=diagnostics) is None
    assert parse_color_value("color(rec2020 1 0 0)", {}, diagnostics=diagnostics) is None
    assert [d["code"] for d in diagnostics] == ["LUMI0511", "LUMI0511"]


def test_a_box_shadow_coloured_in_oklch_keeps_its_colour_and_lengths() -> None:
    [sample] = _parse_box_shadow(
        "oklch(0.21 0.034 264.665) 0px 4px 12px 0px", _pointer("https://x.test/", "shadow")
    )
    assert (sample.color, sample.y, sample.blur) == ("#101828", 4.0, 12.0)


def test_the_parser_agrees_with_the_browser() -> None:
    values = sorted(PAINTED) + [
        "oklch(0.4 0.15 30)", "lab(80 -20 60)", "lch(30 60 250)", "oklab(0.3 -0.05 0.08)",
        "color(display-p3 0.2 0.6 0.3)", "color(srgb-linear 0.1 0.5 0.9)", "hwb(300 0% 0%)",
    ]
    painted = asyncio.run(_paint(values))
    for value, pixel in zip(values, painted, strict=True):
        got = parse_color_value(value, {})
        assert got is not None, value
        channels = [int(got[i:i + 2], 16) for i in (1, 3, 5)]
        worst = max(abs(a - b) for a, b in zip(channels, pixel, strict=True))
        assert worst <= 1, (value, got, pixel)


async def _paint(values: list[str]) -> list[list[int]]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"chromium unavailable: {error}")
        try:
            page = await browser.new_page()
            return await page.evaluate(
                """(values) => {
                const c = document.createElement('canvas'); c.width = c.height = 1;
                const ctx = c.getContext('2d', { willReadFrequently: true });
                return values.map((v) => {
                    ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillStyle = v;
                    ctx.fillRect(0, 0, 1, 1);
                    return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3);
                }); }""",
                values,
            )
        finally:
            await browser.close()
