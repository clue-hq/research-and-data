"""Measure what the brand kit cannot express, from the brand's own cloned sections.

The kits record some buttons as "measured warm-dark with no kit token" (Conduit's primary CTA).
So the primary button is measured from the rendered hero clone itself: background, text colour,
radius, padding, font and weight. Writes data/brands/<brand>/measured.json, which lib/theme.ts
turns into --brand-button-* variables.

Needs the spike's dev server running (it renders /s/<brand>-v0, whose first section is the hero).

Usage (repo root):
    .venv/bin/python trials/puck-spike/export/measure_brand.py garner conduit
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SPIKE = Path(__file__).resolve().parents[1]

FIND_CTA = """() => {
  const hero = document.querySelector('[data-lumen-fragment]');
  const transparent = (c) => !c || c === 'transparent' || c === 'rgba(0, 0, 0, 0)';
  const candidates = [...hero.querySelectorAll('a, button')].filter((el) => {
    const r = el.getBoundingClientRect();
    const text = (el.innerText || '').trim();
    return r.width > 40 && r.height > 24 && text.length > 0 && text.length < 40;
  });
  const filled = candidates.find((el) => !transparent(getComputedStyle(el).backgroundColor))
    || candidates[0];
  if (!filled) return null;
  const s = getComputedStyle(filled);
  // The label may sit in a child (Webflow buttons put it in a div).
  const label = [...filled.querySelectorAll('*')].find((c) => (c.childElementCount === 0) && (c.textContent || '').trim()) || filled;
  const ls = getComputedStyle(label);
  return {
    text: filled.innerText.trim(),
    background: s.backgroundColor, color: ls.color, borderRadius: s.borderTopLeftRadius,
    borderColor: s.borderTopColor, borderWidth: s.borderTopWidth,
    paddingY: s.paddingTop, paddingX: s.paddingLeft, height: filled.getBoundingClientRect().height + 'px',
    fontFamily: ls.fontFamily, fontSize: ls.fontSize, fontWeight: ls.fontWeight, letterSpacing: ls.letterSpacing,
  };
}"""


FIND_HEADING = """() => {
  // The first section heading that sits on a light background: the brand's heading ink.
  const light = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const bg = getComputedStyle(node).backgroundColor;
      const m = bg.match(/[\\d.]+/g);
      if (m && (m.length < 4 || Number(m[3]) > 0.5)) {
        const [r, g, b] = m.map(Number);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b > 200;
      }
    }
    return true;
  };
  const h = [...document.querySelectorAll('[data-lumen-fragment] h2, [data-lumen-fragment] h3')]
    .find((el) => el.getBoundingClientRect().height > 0 && light(el));
  if (!h) return null;
  const s = getComputedStyle(h);
  return {text: h.innerText.slice(0, 60), color: s.color, fontFamily: s.fontFamily, fontWeight: s.fontWeight};
}"""


async def main(brands: list[str]) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        for brand in brands:
            await page.goto(f"http://localhost:3047/s/{brand}-v0", wait_until="load", timeout=60000)
            await page.wait_for_timeout(2000)
            button = await page.evaluate(FIND_CTA)
            heading = await page.evaluate(FIND_HEADING)
            out = {
                "primary_button": button,
                "heading_on_light": heading,
                "measured_from": f"{brand} clones on /s/{brand}-v0 at 1440",
            }
            (SPIKE / "data" / "brands" / brand / "measured.json").write_text(
                json.dumps(out, indent=2)
            )
            print(brand, json.dumps(button))
        await browser.close()


asyncio.run(main(sys.argv[1:] or ["garner", "conduit"]))
