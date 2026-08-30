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
import time
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .geometry import GEOMETRY_JS
from .net import BoundedFetcher, FetchRequest, guard_url
from .snapshot import Download, SiteSnapshot, Stylesheet, HTML_MAX_BYTES
from .static import _collect_assets, _extract_meta, fetch_imported_sheets

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


#: Scroll budget. The old fixed 10 x 800px = 8000px starved every below-fold lazy-loaded
#: image on a long marketing page — extra harvest breadth is worthless if the images never
#: enter the DOM. We now scroll until the document stops growing AND the viewport has
#: reached the bottom, bounded two ways so a pathological infinite-scroll feed can never
#: hold the capture: at most `_MAX_SCROLL_STEPS` x `_SCROLL_STEP_PX` (60 x 1000 = 60_000px
#: of page) and at most `_SCROLL_BUDGET_SECONDS` of wall clock. Worst case therefore adds
#: ~12s to a render that already allows 30s for navigation.
_SCROLL_STEP_PX = 1000
_MAX_SCROLL_STEPS = 60
_SCROLL_BUDGET_SECONDS = 12.0
#: Consecutive steps with no height growth AND the viewport at the bottom before we stop.
_SCROLL_SETTLE_STEPS = 2
#: Let the last batch of lazy images actually fetch before the DOM is harvested.
_SCROLL_SETTLE_MS = 600

_SCROLL_STATE_JS = (
    "() => ({height: document.documentElement.scrollHeight, "
    "y: window.scrollY, viewport: window.innerHeight})"
)

#: Animated hero washes (auroras, gradient fades) paint in over a few seconds —
#: screenshot too early and the brand's biggest surface is simply absent (live
#: finding: sarvam.ai). Note the residual: a WebGL hero may STILL not paint in
#: headless Chromium's software renderer; the census flags a large near-blank
#: canvas loudly (LUMI0531) rather than pretending the page is white.
_HERO_SETTLE_MS = 3000

#: Modals, cookie scrims and their backdrops poison both the census and the
#: probe's region sampling (live finding: apollo.io's "Let's talk" modal).
#: Escape is pressed first, then any position:fixed element covering more than
#: this fraction of the viewport is removed — sticky navs and small banners
#: survive. Runs BEFORE the probe and the screenshot so the two stay aligned.
_OVERLAY_VIEWPORT_FRACTION = 0.25

_REMOVE_OVERLAYS_JS = """
() => {
  const vw = innerWidth, vh = innerHeight;
  let removed = 0;
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height > %f * vw * vh) { el.remove(); removed++; }
  }
  return removed;
}
""" % _OVERLAY_VIEWPORT_FRACTION

# The render probe (Phase-1 brand-color overhaul). Everything the census needs
# that the classic harvest above does not carry:
#  - custom properties RESOLVED through a probe element (an unregistered
#    property's computed value is its unresolved token stream — the probe is
#    the only correct path past var()/color-mix());
#  - visibility-filtered element samples WITH absolute page boxes (hidden menu
#    items otherwise sample as phantom grey buttons — live finding: apollo.io);
#  - media boxes for photo masking;
#  - computed gradient stops over large visible surfaces (a pixel census
#    structurally cannot elect a gradient; the resolved markup names its
#    endpoints — live finding: sarvam.ai);
#  - the viewport width (CSS px -> screenshot px scale) and the fraction of the
#    first viewport covered by <canvas> (WebGL-hero honesty flag).
_PROBE_JS = r"""
() => {
  const abs = (r) => ({l: r.left + scrollX, t: r.top + scrollY, w: r.width, h: r.height});
  const tokens = {};
  const probe = document.createElement('div');
  document.documentElement.append(probe);
  const rootCS = getComputedStyle(document.documentElement);
  for (let i = 0; i < rootCS.length; i++) {
    const name = rootCS[i];
    if (!name.startsWith('--')) continue;
    probe.style.color = 'rgb(1, 2, 3)';
    probe.style.color = `var(${name})`;
    const resolved = getComputedStyle(probe).color;
    if (resolved !== 'rgb(1, 2, 3)') tokens[name] = resolved;
  }
  probe.remove();

  const visible = (el) => {
    if (el.checkVisibility && !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) return false;
    const r = el.getBoundingClientRect();
    return r.width * r.height >= 80 && r.left + scrollX >= 0 && r.top + scrollY >= 0;
  };
  const samples = [];
  const push = (sel, kind, n) => {
    let i = 0;
    for (const el of document.querySelectorAll(sel)) {
      if (i >= n) break;
      if (kind !== 'body' && !visible(el)) continue;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      samples.push({kind, box: abs(r), bg: cs.backgroundColor, color: cs.color});
      i++;
    }
  };
  push('body', 'body', 1);
  push('button, [type="submit"], .btn, [class*="btn"], [class*="Btn"], [class*="cta"], [class*="Button"], a[class*="button"]', 'button', 80);
  push('h1,h2,h3', 'heading', 12);
  push('a', 'link', 25);
  push('nav,header,footer', 'chrome', 6);

  const media = [];
  let canvasArea = 0;
  for (const el of document.querySelectorAll('img,video,canvas,picture')) {
    const r = el.getBoundingClientRect();
    if (r.width > 8 && r.height > 8) media.push(abs(r));
    if (el.tagName === 'CANVAS' && r.top < innerHeight) canvasArea += r.width * r.height;
  }
  const gradients = [];
  let scanned = 0;
  for (const el of document.querySelectorAll('*')) {
    if (scanned++ > 6000) break;
    const cs = getComputedStyle(el);
    if (!cs.backgroundImage || cs.backgroundImage === 'none') continue;
    const r = el.getBoundingClientRect();
    if (cs.backgroundImage.includes('url(') && r.width > 40 && r.height > 40) media.push(abs(r));
    if (cs.backgroundImage.includes('gradient(') && r.width * r.height > 20000 && visible(el)) {
      const stops = cs.backgroundImage.match(/rgba?\([^)]+\)/g) || [];
      if (stops.length) gradients.push({box: abs(r), stops: stops.slice(0, 12)});
    }
  }
  return {
    viewport_width: document.documentElement.clientWidth || innerWidth,
    tokens, samples, media: media.slice(0, 400), gradients: gradients.slice(0, 60),
    canvas_viewport_fraction: canvasArea / (innerWidth * innerHeight),
  };
}
"""


async def _scroll_until_settled(page) -> None:
    """Scroll to the bottom so lazy-loaded imagery enters the DOM before harvesting."""
    deadline = time.monotonic() + _SCROLL_BUDGET_SECONDS
    last_height = -1.0
    settled = 0
    for _ in range(_MAX_SCROLL_STEPS):
        await page.mouse.wheel(0, _SCROLL_STEP_PX)
        await page.wait_for_timeout(200)
        state = await page.evaluate(_SCROLL_STATE_JS)
        height = float(state.get("height") or 0)
        at_bottom = (
            float(state.get("y") or 0) + float(state.get("viewport") or 0) >= height - 2
        )
        if at_bottom and height <= last_height:
            settled += 1
            if settled >= _SCROLL_SETTLE_STEPS:
                break
        else:
            settled = 0
        last_height = height
        if time.monotonic() >= deadline:
            break
    await page.wait_for_timeout(_SCROLL_SETTLE_MS)


async def collect_stylesheets(
    sheet_records: list[dict], fetcher: BoundedFetcher
) -> tuple[list[Stylesheet], list[dict]]:
    """The rendered tier's stylesheets, from one ``document.styleSheets`` harvest.

    Split out of :func:`fetch_rendered` so it is testable without a browser, and because since
    the founder's 2026-08-20 always-render ruling it carries the static tier's ``@import``
    follow as well: EVERY website ingestion now renders, so anything the static tier used to
    contribute for a well-server-rendered site has to survive here or it is lost outright. The
    CSSOM exposes an imported sheet only as the parent's one-line ``@import`` rule text, so
    without :func:`fetch_imported_sheets` a brand whose ``@font-face`` or palette lives behind
    an import would simply stop being read.

    An inline record (``text`` present) is taken verbatim from the CSSOM — that is the rendered
    tier's advantage over static, since it has the post-JS rules — and an ``href`` record is
    fetched, both exactly as before.
    """
    stylesheets: list[Stylesheet] = []
    diagnostics: list[dict] = []
    href_requests: list[FetchRequest] = []
    for index, sheet in enumerate(sheet_records):
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
                    Stylesheet(
                        url=result.url, text=result.body.decode("utf-8", errors="replace")
                    )
                )

    imported, import_diagnostics = await fetch_imported_sheets(stylesheets, fetcher)
    stylesheets.extend(imported)
    diagnostics.extend(import_diagnostics)
    return stylesheets, diagnostics


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
            page = await browser.new_page(
                viewport={"width": 1440, "height": 2000},
                # Never let prefers-reduced-motion suppress a brand's animated
                # hero — we are here to see what real visitors see.
                reduced_motion="no-preference",
            )
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

            await _scroll_until_settled(page)

            # Return to the top and clean the stage before ANY harvest or
            # pixel capture: probe boxes and screenshot must describe the same
            # page, and a modal/scrim must poison neither.
            await page.evaluate("window.scrollTo(0, 0)")
            await page.keyboard.press("Escape")
            removed_overlays = 0
            try:
                removed_overlays = await page.evaluate(_REMOVE_OVERLAYS_JS)
            except Exception:  # noqa: BLE001 — hygiene is fail-soft
                pass
            if removed_overlays:
                diagnostics.append(
                    {
                        "code": "LUMI0530",
                        "severity": "info",
                        "message": f"removed {removed_overlays} full-viewport fixed overlay(s) before capture",
                    }
                )
            await page.wait_for_timeout(_HERO_SETTLE_MS)

            final_url = page.url
            data = await page.evaluate(_EVALUATE_JS)
            render_probe = None
            try:
                render_probe = await page.evaluate(_PROBE_JS)
            except Exception as error:  # noqa: BLE001 — probe is fail-soft
                diagnostics.append(
                    {
                        "code": "LUMI0532",
                        "severity": "warning",
                        "message": f"render probe failed; palette election falls back to evidence clusters: {error}",
                    }
                )
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

    stylesheets, sheet_diagnostics = await collect_stylesheets(
        data.get("sheets", []), fetcher
    )
    diagnostics.extend(sheet_diagnostics)

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
        render_probe=render_probe if isinstance(render_probe, dict) else None,
        downloads=downloads,
        meta=meta,
        diagnostics=diagnostics,
    )
