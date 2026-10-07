"""T9: drive the Puck editor like a person and check every edit lands in the saved page."""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

SITE = Path(__file__).resolve().parents[1] / "data" / "sites" / "edit-test.json"
BASE = "http://localhost:3047"


def saved() -> dict:
    return json.loads(SITE.read_text())["pages"]["/"]


async def type_into(frame, selector: str, text: str) -> None:
    el = frame.locator(selector).first
    await el.scroll_into_view_if_needed()
    await el.click()
    await el.press("Meta+a")
    await el.type(text, delay=5)
    await frame.locator("body").press("Tab")  # blur


async def main() -> None:
    results = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        await page.goto(f"{BASE}/edit/edit-test", wait_until="load", timeout=60000)
        await page.wait_for_timeout(5000)
        frame = page.frame_locator("iframe").first

        # 1. Inline edit in our own section (StatsBand heading, a contentEditable field).
        await type_into(frame, "section h2.brand-heading", "Inline edit in our own section.")
        await page.wait_for_timeout(500)

        # 2. Inline edit of a clone's text slot (hero headline).
        await type_into(frame, "[data-fragment-id=frag_95041c54da629d99] h1", "Inline edit inside a clone.")
        await page.wait_for_timeout(500)

        # 3. Variant change from the field panel: select the stats band, set Surface to Brand.
        await frame.locator("[data-puck-component='proof']").first.click(position={"x": 20, "y": 20})
        await page.wait_for_timeout(800)
        surface = page.locator("select[title='Surface']:visible").first
        await surface.select_option(label="Brand")
        await page.wait_for_timeout(600)

        # 4. Undo the variant change (Puck's undo shortcut), then redo-free: expect brandSubtle back.
        await page.keyboard.press("Meta+z")
        await page.wait_for_timeout(600)

        # 5. Publish and read back the saved file and the published page.
        await page.locator("text=Publish >> visible=true").first.click()
        await page.wait_for_timeout(1500)
        data = saved()
        stats = next(i for i in data["content"] if i["type"] == "StatsBand")["props"]
        hero = next(i for i in data["content"] if i["props"].get("id") == "hero")["props"]
        results["own_section_inline_edit_saved"] = stats["heading"] == "Inline edit in our own section."
        results["clone_inline_edit_saved"] = hero["slots"].get("headline") == "Inline edit inside a clone."
        results["undo_restored_surface"] = stats["surface"] == "brandSubtle"

        pub = await browser.new_page(viewport={"width": 1440, "height": 900})
        await pub.goto(f"{BASE}/s/edit-test", wait_until="load")
        await pub.wait_for_timeout(1500)
        text = await pub.evaluate("document.body.innerText")
        results["published_shows_both_edits"] = (
            "Inline edit in our own section." in text and "Inline edit inside a clone." in text
        )
        await browser.close()
    print(json.dumps(results, indent=1))


asyncio.run(main())
