"""Tier-2 rendered capture via Playwright (async API).

Playwright is imported lazily *inside* ``fetch_rendered`` — never at module
import time — so ``import lumen_ingestion.capture`` and every unit test run
without playwright or a browser installed. This module is exercised only by the
live e2e; its parse integration is covered by a hand-authored rendered-tier
snapshot fixture.
"""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .geometry import GEOMETRY_JS
from .net import BoundedFetcher, FetchRequest, guard_url
from .snapshot import Download, SiteSnapshot, Stylesheet, HTML_MAX_BYTES
from .static import _collect_assets, _extract_meta

# JS gathered in one page.evaluate: computed samples + custom props + stylesheets.
_EVALUATE_JS = r"""
() => {
  const clip = (r) => ({
    w: Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)),
    h: Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)),
  });
  const sample = (el, selectorish) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const c = clip(r);
    const bgRaw = cs.backgroundColor;
    const transparent = !bgRaw || bgRaw === 'transparent' || bgRaw === 'rgba(0, 0, 0, 0)';
    return {
      selectorish, tag: el.tagName.toLowerCase(),
      bg: transparent ? null : bgRaw,
      color: cs.color,
      fontFamily: cs.fontFamily, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
      lineHeight: cs.lineHeight, letterSpacing: cs.letterSpacing,
      borderRadius: cs.borderRadius, area: c.w * c.h,
    };
  };
  const take = (sel, n) => Array.from(document.querySelectorAll(sel)).slice(0, n);
  const samples = [];
  for (const el of take('body', 1)) samples.push(sample(el, 'body'));
  for (const t of ['h1','h2','h3','h4','h5','h6']) for (const el of take(t, 3)) samples.push(sample(el, t));
  for (const el of take('p', 3)) samples.push(sample(el, 'p'));
  for (const el of take('a', 5)) samples.push(sample(el, 'a'));
  for (const el of take('button, .btn', 5)) samples.push(sample(el, 'button'));
  for (const t of ['nav','header','footer']) for (const el of take(t, 1)) samples.push(sample(el, t));
  const all = Array.from(document.querySelectorAll('*')).map((el) => {
    const r = el.getBoundingClientRect(); const c = clip(r);
    return {el, area: c.w * c.h};
  }).filter((x) => x.area > 0).sort((a, b) => b.area - a.area).slice(0, 40);
  for (const x of all) samples.push(sample(x.el, x.el.tagName.toLowerCase()));

  const props = {};
  const rootCS = getComputedStyle(document.documentElement);
  for (let i = 0; i < rootCS.length; i++) {
    const name = rootCS[i];
    if (name.startsWith('--')) props[name] = rootCS.getPropertyValue(name).trim();
  }

  const sheets = [];
  for (const s of Array.from(document.styleSheets)) {
    if (s.href) { sheets.push({href: s.href, text: null}); continue; }
    try {
      const text = Array.from(s.cssRules).map((r) => r.cssText).join('\n');
      sheets.push({href: null, text});
    } catch (e) { /* cross-origin without href — skip */ }
  }
  return {samples, props, sheets};
}
"""


async def fetch_rendered(
    url: str,
    fetcher: BoundedFetcher,
    reporter,
    *,
    fetched_at: str,
) -> SiteSnapshot:
    from playwright.async_api import async_playwright  # lazy: never at import time

    await guard_url(url)
    reporter("Taking a closer look…", 0.55)

    diagnostics: list[dict] = []
    downloads: list[Download] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 2000})
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception:  # noqa: BLE001 — networkidle timeout is non-fatal
                diagnostics.append(
                    {
                        "code": "LUMI0508",
                        "severity": "warning",
                        "message": "render wait_until=networkidle timed out; proceeding",
                    }
                )

            for _ in range(10):
                await page.mouse.wheel(0, 800)
                await page.wait_for_timeout(200)

            final_url = page.url
            data = await page.evaluate(_EVALUATE_JS)
            html = await page.content()
            shot = await page.screenshot(full_page=True)
            # Brand geometry, measured LAST: the probe programmatically focuses a
            # few elements to read the focus ring, so it runs after the
            # screenshot and can never change the captured pixels. A probe that
            # throws costs the ingest a diagnostic and nothing else.
            geometry = None
            try:
                geometry = await page.evaluate(GEOMETRY_JS)
            except Exception as error:  # noqa: BLE001 — measurement is fail-soft
                diagnostics.append(
                    {
                        "code": "LUMI0509",
                        "severity": "warning",
                        "message": f"geometry measurement failed; scales fall back to the derived defaults: {error}",
                    }
                )
        finally:
            await browser.close()

    if len(html.encode("utf-8")) > HTML_MAX_BYTES:
        html = html.encode("utf-8")[:HTML_MAX_BYTES].decode("utf-8", errors="ignore")
        diagnostics.append(
            {"code": "LUMI0507", "severity": "warning", "message": "html truncated to 2 MB"}
        )

    shot_sha = hashlib.sha256(shot).hexdigest()
    downloads.append(
        Download(
            url=f"{final_url}#screenshot",
            kind="screenshot",
            content_type="image/png",
            bytes_b64=base64.b64encode(shot).decode("ascii"),
            sha256=shot_sha,
        )
    )

    # Stylesheets: inline css inline, hrefs fetched concurrently via fetcher.
    stylesheets: list[Stylesheet] = []
    href_requests: list[FetchRequest] = []
    for index, sheet in enumerate(data.get("sheets", [])):
        if sheet.get("text") is not None:
            stylesheets.append(Stylesheet(url=f"inline:{index}", text=sheet["text"]))
        elif sheet.get("href"):
            href_requests.append(FetchRequest(url=sheet["href"], kind="css"))
    if href_requests:
        results = await fetcher.fetch_many(href_requests)
        for result in results:
            diagnostics.extend(result.diagnostics)
            if result.ok and result.body is not None:
                stylesheets.append(
                    Stylesheet(url=result.url, text=result.body.decode("utf-8", errors="replace"))
                )

    # Reuse static's asset identification on the rendered DOM.
    tree = HTMLParser(html)
    asset_downloads, asset_diagnostics = await _collect_assets(
        tree, fetcher, final_url, stylesheets
    )
    diagnostics.extend(asset_diagnostics)
    downloads.extend(asset_downloads)

    meta = _extract_meta(tree)

    return SiteSnapshot(
        requested_url=url,
        final_url=final_url,
        fetched_at=fetched_at,
        tier="rendered",
        html=html,
        stylesheets=stylesheets,
        custom_props=data.get("props") or {},
        computed_samples=data.get("samples") or [],
        geometry=geometry if isinstance(geometry, dict) else None,
        downloads=downloads,
        meta=meta,
        diagnostics=diagnostics,
    )
