"""T7 + rest of T9: one shell edit reaches every route; image swap through the asset picker;
reorder sections with the keyboard (dnd-kit's accessible drag)."""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

SITE = Path(__file__).resolve().parents[1] / "data" / "sites" / "edit-test.json"
BASE = "http://localhost:3047"


async def publish(page) -> None:
    await page.locator("text=Publish >> visible=true").first.click()
    await page.wait_for_timeout(1500)


async def main() -> None:
    results = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})

        # T7: edit the shell once.
        await page.goto(f"{BASE}/edit/edit-test/_shell", wait_until="load", timeout=60000)
        await page.wait_for_timeout(4000)
        frame = page.frame_locator("iframe").first
        await frame.locator("[data-puck-component='site-header']").first.click(
            position={"x": 10, "y": 10}
        )
        await page.wait_for_timeout(600)
        field = page.locator("input[title='Prepared for']:visible").first
        await field.fill("SCSD Benefits Office")
        await page.wait_for_timeout(400)
        await publish(page)
        for route in ("", "/analysis"):
            pub = await browser.new_page()
            await pub.goto(f"{BASE}/s/edit-test{route}", wait_until="load")
            header = await pub.locator("header").first.inner_text()
            results[f"shell_edit_on_route{route or '/'}"] = "SCSD Benefits Office" in header
            await pub.close()

        # T9: image swap through the asset picker on /analysis.
        await page.goto(f"{BASE}/edit/edit-test/analysis", wait_until="load")
        await page.wait_for_timeout(4000)
        frame = page.frame_locator("iframe").first
        await frame.locator("[data-puck-component='what']").first.click(position={"x": 10, "y": 10})
        await page.wait_for_timeout(800)
        before = json.loads(SITE.read_text())["pages"]["/analysis"]["content"][0]["props"]["image"]
        picks = page.locator("button[title] img:visible")
        count = await picks.count()
        for i in range(count):
            src = await picks.nth(i).get_attribute("src")
            if src and src != before:
                await picks.nth(i).click()
                chosen = src
                break
        await page.wait_for_timeout(500)

        # T9: reorder: move the first section down one place with the keyboard.
        first_id = json.loads(SITE.read_text())["pages"]["/analysis"]["content"][0]["props"]["id"]
        handle = frame.locator(f"[data-puck-dnd='{first_id}']").first
        await handle.focus()
        await page.keyboard.press("Space")
        await page.wait_for_timeout(300)
        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Space")
        await page.wait_for_timeout(800)
        await publish(page)

        data = json.loads(SITE.read_text())["pages"]["/analysis"]["content"]
        what = next(item for item in data if item["props"]["id"] == "what")
        results["image_swapped"] = what["props"]["image"] == chosen and chosen != before
        results["reordered"] = data[0]["props"]["id"] != first_id
        results["order_now"] = [item["props"]["id"] for item in data]
        await browser.close()
    print(json.dumps(results, indent=1))


asyncio.run(main())
