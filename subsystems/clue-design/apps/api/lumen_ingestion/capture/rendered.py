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

from selectolax.parser import HTMLParser

from .geometry import COLOR_FN, GEOMETRY_JS
from .states import REVEAL_BEFORE_JS, probe_states
from .net import BoundedFetcher, CaptureError, guard_url, require_complete_html
from .snapshot import Download, SiteSnapshot, Stylesheet
from .static import _collect_assets, _extract_meta
from .stylesheets import collect_ordered_stylesheets
from .type_widths import measure_type_widths

# JS gathered in one page.evaluate: computed samples + custom props + stylesheets.
_EVALUATE_JS = r"""
() => {
""" + COLOR_FN + r"""
  const clip = (r) => ({
    w: Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)),
    h: Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)),
  });
  // The sampled elements, in sample order, kept on the page (never as attributes: the captured HTML
  // must not change) so the width pass can read the same elements again (type_widths.py).
  const sampled = [];
  const sample = (el, selectorish) => {
    sampled.push(el);
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
      // The colour behind the element and its whole box (not only the part in the first
      // viewport): the heading ink is read from headings on light backgrounds anywhere on the page.
      behind: behindOf(el), boxArea: r.width * r.height,
    };
  };
  // Only what a visitor can see is evidence of the brand's type: a heading inside a closed
  // cookie modal, behind opacity 0 or under display:none once became a kit's headline.
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    if (typeof el.checkVisibility === 'function'
        && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    return !el.closest('dialog, [role="dialog"], [role="alertdialog"], [aria-modal="true"]');
  };
  const take = (sel, n) => Array.from(document.querySelectorAll(sel)).filter(visible).slice(0, n);
  // Headings: enough of them to see the page's real section-heading size (the first few are
  // often tab labels), and none from navigation or footers, which are not section headings.
  const content = (el) => !el.closest('nav, footer');
  const takeHeadings = (sel, n) =>
    Array.from(document.querySelectorAll(sel)).filter((el) => visible(el) && content(el)).slice(0, n);
  const samples = [];
  for (const el of take('body', 1)) samples.push(sample(el, 'body'));
  for (const t of ['h1','h2','h3','h4','h5','h6']) for (const el of takeHeadings(t, 20)) samples.push(sample(el, t));
  for (const el of take('p', 3)) samples.push(sample(el, 'p'));
  for (const el of take('a', 5)) samples.push(sample(el, 'a'));
  for (const el of take('button, .btn', 5)) samples.push(sample(el, 'button'));
  for (const t of ['nav','header','footer']) for (const el of take(t, 1)) samples.push(sample(el, t));
  const all = Array.from(document.querySelectorAll('*')).map((el) => {
    const r = el.getBoundingClientRect(); const c = clip(r);
    return {el, area: c.w * c.h};
  }).filter((x) => x.area > 0).sort((a, b) => b.area - a.area)
    .filter((x) => visible(x.el) && (!/^H[1-6]$/.test(x.el.tagName) || content(x.el))).slice(0, 40);
  for (const x of all) samples.push(sample(x.el, x.el.tagName.toLowerCase()));

  const props = {};
  const rootCS = getComputedStyle(document.documentElement);
  for (let i = 0; i < rootCS.length; i++) {
    const name = rootCS[i];
    if (name.startsWith('--')) props[name] = rootCS.getPropertyValue(name).trim();
  }

  const sheets = [];
  for (const s of Array.from(document.styleSheets)) {
    const context = {media: s.media?.mediaText || "", disabled: !!s.disabled};
    if (s.href) { sheets.push({href: s.href, text: null, ...context}); continue; }
    try {
      const text = Array.from(s.cssRules).map((r) => r.cssText).join('\n');
      sheets.push({href: null, text, ...context});
    } catch (e) { /* cross-origin without href — skip */ }
  }
  window.__lumenTypeSamples = sampled;
  return {samples, props, sheets, base_url: document.baseURI};
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
      const stops = cs.backgroundImage.match(/(?:rgba?|hsla?|hwb|oklab|oklch|lab|lch|color)\([^)]+\)/g) || [];
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
    sheet_records: list[dict], fetcher: BoundedFetcher, *, base_url: str = ""
) -> tuple[list[Stylesheet], list[dict]]:
    """Retain CSSOM order, owner conditions and bounded in-place imports."""
    return await collect_ordered_stylesheets(sheet_records, fetcher, base_url=base_url)


#: The one viewport both render backends use; the probe also records the live
#: value so the census scale never depends on this constant being right.
_VIEWPORT = {"width": 1440, "height": 2000}


# Inline logos often inherit all their paint from page CSS. A bare outerHTML
# export silently turns these into black shapes. Bake the OBSERVED styles into
# a detached copy, keeping the live page and screenshot untouched. The bound is
# independent of HTML bytes so a pathological SVG cannot monopolize capture.
_SERIALIZE_HTML_JS = r"""
() => {
  const copy = document.documentElement.cloneNode(true);
  const source = Array.from(document.querySelectorAll('svg')).filter(n => !n.parentElement.closest('svg'));
  const targets = Array.from(copy.querySelectorAll('svg')).filter(n => !n.parentElement.closest('svg'));
  const common = ['display', 'visibility', 'opacity', 'transform', 'transform-origin',
                  'filter', 'clip-path', 'mask', 'mix-blend-mode'];
  const paint = ['fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-opacity',
                 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
                 'stroke-dasharray', 'stroke-dashoffset', 'vector-effect'];
  const typography = ['font-family', 'font-size', 'font-weight', 'font-style',
                      'letter-spacing', 'text-anchor', 'dominant-baseline'];
  let count = 0;
  const localPaint = value => value.replace(/url\(["']?([^"')]+)["']?\)/g, (match, ref) => {
    try {
      const u = new URL(ref, location.href);
      const here = new URL(location.href);
      if (u.hash && u.origin === here.origin && u.pathname === here.pathname && u.search === here.search)
        return `url("${u.hash}")`;
    } catch (_) {}
    return match;
  });
  source.forEach((svg, i) => {
    const originals = [svg, ...svg.querySelectorAll('*')];
    const clones = [targets[i], ...targets[i].querySelectorAll('*')];
    originals.forEach((node, j) => {
      if (++count > 20000) throw new Error('SVG style capture exceeds 20000 elements');
      const cs = getComputedStyle(node);
      const target = clones[j];
      // Invisible alternate artwork must not become visible when detached.
      if (cs.display === 'none') { target.remove(); return; }
      const properties = [...common];
      if (node.matches('path,rect,circle,ellipse,line,polyline,polygon,text,tspan,use'))
        properties.push(...paint);
      if (node.matches('text,tspan')) properties.push(...typography);
      if (node.matches('stop')) properties.push('stop-color', 'stop-opacity');
      for (const name of properties) {
        const value = cs.getPropertyValue(name);
        if (value) target.style.setProperty(name, localPaint(value), 'important');
      }
    });
  });
  const doctype = document.doctype ? new XMLSerializer().serializeToString(document.doctype) : '';
  return doctype + copy.outerHTML;
}
"""


async def _capture_html(page) -> str:
    require_complete_html(await page.content())
    try:
        html = await page.evaluate(_SERIALIZE_HTML_JS)
    except Exception as error:
        raise CaptureError("LUMI0507", f"Could not preserve rendered SVG styling: {error}") from error
    return require_complete_html(html)


async def _harvest_page(page, diagnostics: list[dict], *, measure_states: bool = False) -> dict:
    """Everything we take from a live, already-navigated page.

    Shared verbatim by the plain-Chromium and stealth backends so the two can
    never drift: scroll-settle for lazy content, stage hygiene (Escape +
    full-viewport overlay removal), the animated-hero dwell, then the classic
    harvest, the render probe, html, the full-page screenshot, and geometry
    LAST (it focuses elements and must never touch the captured pixels).
    """
    # Entrance reveals can only be seen before the page is scrolled (Wave 2 A9): read-only, so the
    # captured pixels and HTML are untouched.
    reveal_before = None
    if measure_states:
        try:
            reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
        except Exception:  # noqa: BLE001 — a reveal we cannot see is a reveal we do not record
            reveal_before = None
    await _scroll_until_settled(page)

    # Return to the top and clean the stage before ANY harvest or pixel
    # capture: probe boxes and screenshot must describe the same page, and a
    # modal/scrim must poison neither.
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

    harvest: dict = {"final_url": page.url}
    harvest["data"] = await page.evaluate(_EVALUATE_JS)
    harvest["render_probe"] = None
    try:
        harvest["render_probe"] = await page.evaluate(_PROBE_JS)
    except Exception as error:  # noqa: BLE001 — probe is fail-soft
        diagnostics.append(
            {
                "code": "LUMI0532",
                "severity": "warning",
                "message": f"render probe failed; palette election falls back to evidence clusters: {error}",
            }
        )
    harvest["html"] = await _capture_html(page)
    harvest["shot"] = await page.screenshot(full_page=True)
    # Brand geometry, measured LAST: the probe programmatically focuses a few
    # elements to read the focus ring, so it runs after the screenshot and can
    # never change the captured pixels. A probe that throws costs the ingest a
    # diagnostic and nothing else.
    harvest["geometry"] = None
    try:
        harvest["geometry"] = await page.evaluate(GEOMETRY_JS)
    except Exception as error:  # noqa: BLE001 — measurement is fail-soft
        diagnostics.append(
            {
                "code": "LUMI0509",
                "severity": "warning",
                "message": f"geometry measurement failed; scales fall back to the derived defaults: {error}",
            }
        )
    # Interaction states, motion and behaviour (Wave 2 A9), after everything that was captured. The
    # entry page only: it is the page the kit is about, and the pass costs up to ~10 s.
    if measure_states and isinstance(harvest["geometry"], dict):
        harvest["geometry"]["states"] = await probe_states(
            page, harvest["geometry"], reveal_before=reveal_before, diagnostics=diagnostics
        )
    # Responsive type, LAST of all: it narrows the window, which nothing above may see.
    harvest["type_widths"] = None
    try:
        harvest["type_widths"] = await measure_type_widths(
            page, (harvest["data"] or {}).get("sheets") or [], diagnostics
        )
    except Exception as error:  # noqa: BLE001 — measurement is fail-soft
        diagnostics.append(
            {
                "code": "LUMI0547",
                "severity": "warning",
                "message": f"type width measurement failed; the kit keeps one size per role: {error}",
            }
        )
    return harvest


async def fetch_rendered(
    url: str,
    fetcher: BoundedFetcher,
    reporter,
    *,
    fetched_at: str,
    measure_states: bool = False,
) -> SiteSnapshot:
    """Rendered capture behind the backend dispatcher.

    The STEALTH backend (scrapling's hardened Chromium) is the default: the
    capture PoC (2026-08-30) proved plain automation Chromium is refused the
    goods — sarvam.ai's WebGL hero stays unpainted, ramp.com serves an unstyled
    "machine version", openai.com serves a Cloudflare wall — while the stealth
    profile receives the real page everywhere. Plain Chromium remains as the
    automatic fallback, and the kit's diagnostics always say which backend
    captured (LUMI0535 info / LUMI0536 fallback warning), so a degraded capture
    can never impersonate a full one. `LUMEN_RENDER_STEALTH=0` disables the
    stealth lane outright (kill switch, e.g. a host where scrapling's browser
    is not provisioned).
    """
    import os

    if os.environ.get("LUMEN_RENDER_STEALTH", "1") != "0":
        try:
            snapshot = await _fetch_rendered_stealth(
                url, fetcher, reporter, fetched_at=fetched_at, measure_states=measure_states
            )
            snapshot.diagnostics.append(
                {
                    "code": "LUMI0535",
                    "severity": "info",
                    "message": "rendered via the stealth backend (scrapling hardened Chromium)",
                }
            )
            return snapshot
        except Exception as error:  # noqa: BLE001 — fallback, loudly
            if isinstance(error, CaptureError) and error.code in {
                "LUMI0501", "LUMI0503", "LUMI0507"
            }:
                # URL, HTTP and size refusals are not broken browser backends.
                raise
            fallback_note = {
                "code": "LUMI0536",
                "severity": "warning",
                "message": (
                    "stealth render backend failed; fell back to plain Chromium — "
                    f"bot-walled or WebGL-hero sites may capture degraded: {error}"
                ),
            }
    else:
        fallback_note = None

    snapshot = await _fetch_rendered_chromium(
        url, fetcher, reporter, fetched_at=fetched_at, measure_states=measure_states
    )
    if fallback_note is not None:
        snapshot.diagnostics.append(fallback_note)
    return snapshot


async def _fetch_rendered_stealth(
    url: str,
    fetcher: BoundedFetcher,
    reporter,
    *,
    fetched_at: str,
    measure_states: bool = False,
) -> SiteSnapshot:
    from scrapling.fetchers import StealthyFetcher  # lazy: never at import time

    await guard_url(url)
    reporter("Taking a closer look…", 0.55)

    diagnostics: list[dict] = []
    harvest: dict = {}

    async def _drive(page):
        harvest.update(await _harvest_page(page, diagnostics, measure_states=measure_states))
        return page

    # network_idle mirrors the chromium path's goto wait; the generous timeout
    # covers scroll-settle (<=12s) + hero dwell (3s) + the state pass (<=10s) on slow marketing pages.
    # NO context overrides: scrapling generates a COHERENT fingerprint
    # (screen/viewport/UA agree), and overriding the viewport to our chromium
    # constant broke it — sarvam.ai's WebGL hero refused to paint for a
    # 1440x2000 "screen" (live finding, 2026-08-30). The probe records the live
    # viewport width, so the census scale never depended on the constant.
    response = await StealthyFetcher.async_fetch(
        url,
        headless=True,
        network_idle=True,
        timeout=90_000,
        page_action=_drive,
    )
    if response.status >= 400:
        raise CaptureError("LUMI0503", f"page returned HTTP {response.status}: {url}")
    if not harvest.get("html"):
        raise RuntimeError("stealth backend returned no page harvest")
    return await _snapshot_from_harvest(
        url, harvest, fetcher, diagnostics, fetched_at=fetched_at
    )


async def _fetch_rendered_chromium(
    url: str,
    fetcher: BoundedFetcher,
    reporter,
    *,
    fetched_at: str,
    measure_states: bool = False,
) -> SiteSnapshot:
    from playwright.async_api import async_playwright  # lazy: never at import time

    await guard_url(url)
    reporter("Taking a closer look…", 0.55)

    diagnostics: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport=dict(_VIEWPORT),
                # Never let prefers-reduced-motion suppress a brand's animated
                # hero — we are here to see what real visitors see.
                reduced_motion="no-preference",
            )
            response = None
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception:  # noqa: BLE001 — networkidle timeout is non-fatal
                diagnostics.append(
                    {
                        "code": "LUMI0508",
                        "severity": "warning",
                        "message": "render wait_until=networkidle timed out; proceeding",
                    }
                )
            if response is not None and response.status >= 400:
                raise CaptureError("LUMI0503", f"page returned HTTP {response.status}: {url}")
            harvest = await _harvest_page(page, diagnostics, measure_states=measure_states)
        finally:
            await browser.close()

    return await _snapshot_from_harvest(
        url, harvest, fetcher, diagnostics, fetched_at=fetched_at
    )


async def _snapshot_from_harvest(
    url: str,
    harvest: dict,
    fetcher: BoundedFetcher,
    diagnostics: list[dict],
    *,
    fetched_at: str,
) -> SiteSnapshot:
    downloads: list[Download] = []
    html = require_complete_html(harvest["html"])
    shot = harvest["shot"]
    final_url = harvest["final_url"]
    data = harvest.get("data") or {}
    render_probe = harvest.get("render_probe")
    geometry = harvest.get("geometry")

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
        data.get("sheets", []), fetcher, base_url=data.get("base_url") or final_url
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
        type_widths=harvest.get("type_widths") if isinstance(harvest.get("type_widths"), dict) else None,
        downloads=downloads,
        meta=meta,
        diagnostics=diagnostics,
    )
