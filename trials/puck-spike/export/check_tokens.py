"""Gate G3: computed styles of the token probe must equal the brand kit's values (1440 wide)."""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SPIKE = Path(__file__).resolve().parents[1]


def hex_rgb(value: str) -> str:
    h = value.lstrip("#")
    return f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"


def expected(brand: str) -> dict:
    kit = json.loads((SPIKE / "data" / "brands" / brand / "kit.json").read_text())
    t = kit["tokens"]
    color = lambda role: hex_rgb(t["colors"][role]["value"]["default"]["value"])
    def typ(role):
        s = t["typography"][f"type.{role}"]["value"]["default"]
        size = s["font_size"]
        return {"family": s["font_family"], "size": f"{size:g}px", "weight": str(s["font_weight"]),
                "lineHeight": f"{size * s['line_height']:g}px",
                "letterSpacing": "normal" if s["letter_spacing"] == 0 else f"{size * s['letter_spacing']:g}px"}
    radius = t["radii"]["radius.button"]["value"]["default"]["value"]
    return {"headline": {**typ("headline"), "color": color("text.inverse")},
            "body": typ("body"), "cta": {**typ("cta"), "color": color("text.primary")},
            "surfaceBrand": color("surface.brand"), "buttonRadius": f"{radius:g}px"}


JS = """(root) => {
  const d = root || document;
  const win = d.defaultView || window;
  const q = (s) => d.querySelector(`[data-probe=${s}]`);
  const style = (e) => { const s = win.getComputedStyle(e);
    return {family: s.fontFamily.split(',')[0].replace(/"/g,''), size: s.fontSize, weight: s.fontWeight,
            lineHeight: s.lineHeight, letterSpacing: s.letterSpacing, color: s.color}; };
  return {headline: style(q('token-headline')), body: style(q('token-body')), cta: style(q('token-button')),
          surfaceBrand: win.getComputedStyle(q('token-section')).backgroundColor,
          buttonRadius: win.getComputedStyle(q('token-button')).borderTopLeftRadius,
          fontsLoaded: [...d.fonts].filter(f => f.status === 'loaded').map(f => f.family).filter((v,i,a)=>a.indexOf(v)===i)};
}"""


def compare(want: dict, got: dict, path: str = "") -> list[str]:
    bad = []
    for key, value in want.items():
        if isinstance(value, dict):
            bad += compare(value, got.get(key, {}), f"{path}{key}.")
        else:
            g = got.get(key)
            close = False
            try:
                close = abs(float(str(g).rstrip("px")) - float(str(value).rstrip("px"))) < 0.05
            except ValueError:
                pass
            if g != value and not close:
                bad.append(f"{path}{key}: kit {value!r}, page {g!r}")
    return bad


async def main(brands: list[str]) -> int:
    failures = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        for brand in brands:
            want = expected(brand)
            for where in ("published", "editor"):
                url = f"http://localhost:3047/{'s' if where == 'published' else 'edit'}/tokens-{brand}"
                await page.goto(url, wait_until="load", timeout=60000)
                await page.wait_for_timeout(4000 if where == "editor" else 1500)
                if where == "editor":
                    frame = page.frame_locator("iframe").first
                    handle = await frame.locator("body").element_handle()
                    got = await handle.evaluate(f"(b) => ({JS})(b.ownerDocument)")
                else:
                    got = await page.evaluate(f"({JS})(document)")
                bad = compare(want, got)
                failures += len(bad)
                print(f"{brand:8} {where:9} {'PASS' if not bad else 'FAIL'}  fonts={got['fontsLoaded']}")
                for line in bad:
                    print("    ", line)
        await browser.close()
    return 1 if failures else 0


raise SystemExit(asyncio.run(main(sys.argv[1:] or ["garner", "conduit"])))
