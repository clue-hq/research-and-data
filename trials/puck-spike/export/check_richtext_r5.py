"""R5 spike probe: the skinned inline menu appears on the canvas, and Bold changes the stored value."""

import asyncio
import json

from playwright.async_api import async_playwright

BASE = "http://localhost:3049"


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(f"{BASE}/r5-richtext", wait_until="load", timeout=60000)
        # The richtext field's TipTap editor mounts ~0.5s after `load`; a click before that
        # selects the component without focusing an editor, so the inline menu never appears
        # (RICHTEXT-R5.md, row 1).
        await page.locator(".ProseMirror").first.wait_for(timeout=10000)
        await page.get_by_text("Lower medical spend").first.click()
        await page.keyboard.press("ControlOrMeta+a")
        menu = page.locator("[data-r5-inline-menu]")
        await menu.wait_for(timeout=10000)
        await menu.get_by_title("Bold").click()
        await page.wait_for_timeout(500)
        stored = json.loads(await page.locator("[data-r5-data]").inner_text())
        border = await menu.evaluate("(element) => getComputedStyle(element).borderTopColor")
        active = await menu.evaluate(
            "(element) => [...element.querySelectorAll('button')].map((b) => b.outerHTML.slice(0, 160))"
        )
        await page.screenshot(path="shots/r5-richtext.png")
        print(
            json.dumps(
                {
                    "menu_visible": await menu.is_visible(),
                    "menu_border": border,
                    "buttons": active,
                    "stored_body": stored.get("body"),
                },
                indent=2,
            )
        )
        await browser.close()


asyncio.run(main())
