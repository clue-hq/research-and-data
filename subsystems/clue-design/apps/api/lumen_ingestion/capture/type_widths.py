"""Responsive brand type (spec docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md §3.1).

The capture's last pass: the same page, narrowed to the seller's own break points (read from the
media queries of its stylesheets) and to 1024, 768 and 390px, re-reads the type samples
``_EVALUATE_JS`` took at the capture's own width. Reading the drawn page, not parsing the seller's
CSS, keeps this general: Webflow steps, ``clamp()``/``vw`` and sizes set by JavaScript all read the
same way. Only widths narrower than the capture's own are measured, so desktop stays as captured.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

#: Widths every site is read at (when narrower than the capture), so a site whose sizes slide
#: smoothly is caught even where it has no break point.
FIXED_WIDTHS = (1024, 768, 390)
NARROWEST_WIDTH = 320
MAX_WIDTHS = 8
#: Layout settles (and a font-size transition ends) before the samples are read again.
SETTLE_MS = 400
#: Bounds on fetching a cross-origin stylesheet the page could not read itself.
SHEET_FETCH_BUDGET_SECONDS = 5.0
SHEET_MAX_BYTES = 2_000_000

_MEDIA = re.compile(r"@media([^{]*)\{", re.IGNORECASE)
_WIDTH = re.compile(r"\((max|min)-width\s*:\s*([\d.]+)\s*(px|em|rem)\s*\)", re.IGNORECASE)

_SIZE_JS = "() => ({innerWidth: window.innerWidth, innerHeight: window.innerHeight})"

#: One entry per element ``_EVALUATE_JS`` sampled, in its order: the element's type now, or null
#: when it is gone, hidden or has no box at this width (it then sets no size here).
TYPE_READ_JS = r"""
() => (window.__lumenTypeSamples || []).map((el) => {
  if (!el || !el.isConnected) return null;
  const box = el.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0) return null;
  const cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden') return null;
  return {fontSize: cs.fontSize, lineHeight: cs.lineHeight, letterSpacing: cs.letterSpacing};
})
"""


def media_query_widths(css_texts: list[str]) -> list[int]:
    """The widths the stylesheets change at: a ``max-width: W`` applies at W, a ``min-width: W``
    stops applying at W−1. ``em``/``rem`` count as 16px. Widest first."""
    found: set[int] = set()
    for text in css_texts:
        for prelude in _MEDIA.findall(text or ""):
            for kind, number, unit in _WIDTH.findall(prelude):
                px = float(number) * (16 if unit.lower() in ("em", "rem") else 1)
                found.add(int(round(px)) - (1 if kind.lower() == "min" else 0))
    return sorted(found, reverse=True)


def type_measure_widths(capture_width: int, media_widths: list[int]) -> list[int]:
    """The widths to read: the fixed three, then the seller's break points from the widest, all
    narrower than the capture and no narrower than a phone; at most ``MAX_WIDTHS``."""
    keep = lambda width: NARROWEST_WIDTH <= width < capture_width  # noqa: E731
    fixed = [width for width in FIXED_WIDTHS if keep(width)]
    media = [width for width in sorted(set(media_widths), reverse=True) if keep(width) and width not in fixed]
    return (fixed + media)[:MAX_WIDTHS]


def _page_fetcher(page) -> Callable[[str], Awaitable[str | None]]:
    async def fetch_text(url: str) -> str | None:
        response = await page.request.get(url, timeout=3_000)
        if not response.ok:
            return None
        body = await response.body()
        return body[:SHEET_MAX_BYTES].decode("utf-8", errors="replace")

    return fetch_text


async def _sheet_texts(sheets: list[dict], fetch_text: Callable[[str], Awaitable[str | None]]) -> list[str]:
    texts = [str(sheet["text"]) for sheet in sheets if sheet.get("text")]
    started = time.monotonic()
    for sheet in sheets:
        href = sheet.get("href")
        if sheet.get("text") or not href or time.monotonic() - started > SHEET_FETCH_BUDGET_SECONDS:
            continue
        try:
            text = await fetch_text(str(href))
        except Exception:  # noqa: BLE001 — a sheet we cannot fetch only costs its break points
            text = None
        if text:
            texts.append(text)
    return texts


async def measure_type_widths(
    page,
    sheets: list[dict],
    diagnostics: list[dict],
    *,
    fetch_text: Callable[[str], Awaitable[str | None]] | None = None,
) -> dict:
    """Narrow the page to each width and re-read the sampled elements' type.

    Returns ``{"capture_width", "widths": [{"width", "samples": [...]}, ...]}``, one sample entry per
    element ``_EVALUATE_JS`` sampled (None where it sets no size at that width). Runs last: it leaves
    the page at the narrowest width read."""
    size = await page.evaluate(_SIZE_JS)
    capture_width = int(size["innerWidth"])
    height = int(size.get("innerHeight") or 900)
    texts = await _sheet_texts(sheets, fetch_text or _page_fetcher(page))
    widths = type_measure_widths(capture_width, media_query_widths(texts))
    measured: list[dict] = []
    for width in widths:
        await page.set_viewport_size({"width": width, "height": height})
        await page.wait_for_timeout(SETTLE_MS)
        measured.append({"width": width, "samples": await page.evaluate(TYPE_READ_JS)})
    return {"capture_width": capture_width, "widths": measured}
