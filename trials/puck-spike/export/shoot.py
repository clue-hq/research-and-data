"""Full-page screenshots of spike pages at 1440 and 375 wide, plus a few runtime checks."""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parents[1] / "shots"


async def main(urls: list[str]) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for url in urls:
            name = url.rstrip("/").split("/s/")[-1].replace("/", "_") or "root"
            for width in (1440, 375):
                page = await browser.new_page(viewport={"width": width, "height": 900})
                errors: list[str] = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                await page.goto(url, wait_until="load", timeout=60000)
                await page.wait_for_timeout(2500)
                height = await page.evaluate("document.body.scrollHeight")
                for y in range(0, height, 500):
                    await page.evaluate(f"window.scrollTo(0,{y})")
                    await page.wait_for_timeout(80)
                await page.evaluate("window.scrollTo(0,0)")
                await page.wait_for_timeout(600)
                checks = await page.evaluate("""async () => {
                    const v = document.querySelector('video');
                    let t0 = v ? v.currentTime : null;
                    await new Promise(r => setTimeout(r, 1200));
                    return {
                      videoAdvancing: v ? v.currentTime > t0 : null,
                      brokenImages: [...document.images].filter(i => i.complete && i.naturalWidth === 0).length,
                      fontErrors: [...document.fonts].filter(f => f.status === 'error').length,
                      overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
                    };
                }""")
                path = OUT / f"{name}-{width}.png"
                await page.screenshot(path=str(path), full_page=True)
                print(json.dumps({"page": name, "width": width, "height": height, **checks,
                                  "errors": errors[:5]}))
                await page.close()
        await browser.close()


asyncio.run(main(sys.argv[1:]))
