"""Responsive brand type (spec docs/superpowers/specs/2026-10-18-responsive-brand-type-design.md §3.1).

The capture's last pass: the same page, narrowed to the seller's own break points (read from the
media queries of its stylesheets) and to 1024, 768 and 390px, re-reads the type samples
``_EVALUATE_JS`` took at the capture's own width. Reading the drawn page, not parsing the seller's
CSS, keeps this general: Webflow steps, ``clamp()``/``vw`` and sizes set by JavaScript all read the
same way. Only widths narrower than the capture's own are measured, so desktop stays as captured.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Awaitable, Callable

from .net import CaptureError, guard_url

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
#: The whole pass, sheets and resizes included; a page whose resize handlers hang costs only the steps.
PASS_TIMEOUT_SECONDS = 20.0
DIAGNOSTIC = "LUMI0547"

_MEDIA = re.compile(r"@media([^{]*)\{", re.IGNORECASE)
_LENGTH = r"([\d.]+)\s*(px|em|rem)"
#: `(max-width: 991.98px)`, `(min-width: 48em)`.
_PREFIXED = re.compile(r"\((max|min)-width\s*:\s*" + _LENGTH + r"\s*\)", re.IGNORECASE)
#: Media Queries 4 ranges: `width >= 48rem` and the reversed `768px <= width` (both halves of
#: `400px <= width <= 700px` are read).
_WIDTH_FIRST = re.compile(r"width\s*(<=|<|>=|>)\s*" + _LENGTH, re.IGNORECASE)
_LENGTH_FIRST = re.compile(_LENGTH + r"\s*(<=|<|>=|>)\s*width", re.IGNORECASE)
#: Reading `X op width` as `width op' X`.
_FLIPPED = {"<=": ">=", "<": ">", ">=": "<=", ">": "<"}

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
  // A label shrunk to nothing (font-size: 0, icon only) sets no size either.
  if (!(parseFloat(cs.fontSize) > 0)) return null;
  return {fontSize: cs.fontSize, lineHeight: cs.lineHeight, letterSpacing: cs.letterSpacing};
})
"""


def _px(number: str, unit: str) -> float:
    return float(number) * (16 if unit.lower() in ("em", "rem") else 1)


def _widest_where(op: str, px: float) -> int:
    """The widest whole window width at which ``width op px`` changes the page: a rule that applies
    up to X applies at floor(X); one that applies from X stops applying at ceil(X) − 1."""
    return math.floor(px) if op in ("<=", ">") else math.ceil(px) - 1


def media_query_widths(css_texts: list[str]) -> list[int]:
    """The widths the stylesheets change at, widest first: ``max-width``/``min-width`` (fractional
    Bootstrap values included) and Media Queries 4 ranges (``width >= 48rem``). ``em``/``rem`` count
    as 16px."""
    found: set[int] = set()
    for text in css_texts:
        for prelude in _MEDIA.findall(text or ""):
            for kind, number, unit in _PREFIXED.findall(prelude):
                found.add(_widest_where("<=" if kind.lower() == "max" else ">=", _px(number, unit)))
            for op, number, unit in _WIDTH_FIRST.findall(prelude):
                found.add(_widest_where(op, _px(number, unit)))
            for number, unit, op in _LENGTH_FIRST.findall(prelude):
                found.add(_widest_where(_FLIPPED[op], _px(number, unit)))
    return sorted(found, reverse=True)


#: A fixed width this close to one of the seller's break points is the same tier; the seller's wins.
NEAR_PX = 2


def type_measure_widths(capture_width: int, media_widths: list[int]) -> list[int]:
    """The widths to read, widest first: the seller's break points and the fixed three (each fixed
    width only where no break point is next to it), narrower than the capture and no narrower than
    a phone. Capped at ``MAX_WIDTHS``, keeping the fixed ones and the narrowest break points (phones
    and tablets are where type changes)."""
    keep = lambda width: NARROWEST_WIDTH <= width < capture_width  # noqa: E731
    media = sorted({width for width in media_widths if keep(width)})
    fixed = [width for width in FIXED_WIDTHS if keep(width) and not any(abs(width - m) <= NEAR_PX for m in media)]
    chosen = fixed + [width for width in media if width not in fixed][: max(0, MAX_WIDTHS - len(fixed))]
    return sorted(set(chosen), reverse=True)


def _page_fetcher(page) -> Callable[[str], Awaitable[str | None]]:
    """Fetches a stylesheet the page could not read itself, under the capture's own URL guard (no
    private hosts, schemes or credentials) and size limit (a declared size past it is not read)."""
    async def fetch_text(url: str) -> str | None:
        try:
            await guard_url(url)
        except CaptureError:
            return None
        response = await page.request.get(url, timeout=3_000)
        if not response.ok:
            return None
        declared = (response.headers or {}).get("content-length")
        if declared and declared.isdigit() and int(declared) > SHEET_MAX_BYTES:
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


async def measure_type_widths_safely(
    page, sheets: list[dict], diagnostics: list[dict], *, timeout: float = PASS_TIMEOUT_SECONDS
) -> dict | None:
    """``measure_type_widths`` that can only cost the steps: any failure, or the pass running past
    ``timeout``, is one warning and no readings (the kit then keeps one size per role)."""
    try:
        return await asyncio.wait_for(measure_type_widths(page, sheets, diagnostics), timeout=timeout)
    except Exception as error:  # noqa: BLE001 — measurement is fail-soft (TimeoutError included)
        reason = "timed out" if isinstance(error, (asyncio.TimeoutError, TimeoutError)) else f"failed: {error}"
        diagnostics.append(
            {"code": DIAGNOSTIC, "severity": "warning", "message": f"type width measurement {reason}; the kit keeps one size per role"}
        )
        return None
