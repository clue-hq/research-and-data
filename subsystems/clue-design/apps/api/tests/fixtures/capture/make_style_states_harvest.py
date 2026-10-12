"""Write style_states.harvest.json: the real probe's harvest of style_states.html (Wave 2 A9).

Run from subsystems/clue-design:
  PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python apps/api/tests/fixtures/capture/make_style_states_harvest.py
Offline (a file:// page). Deterministic: computed styles only; re-running writes the same bytes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from lumen_ingestion.capture.geometry import GEOMETRY_JS
from lumen_ingestion.capture.states import REVEAL_BEFORE_JS, probe_states

HERE = Path(__file__).resolve().parent


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto((HERE / "style_states.html").as_uri())
        reveal_before = await page.evaluate(REVEAL_BEFORE_JS)
        for y in range(0, 4200, 600):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(120)
        await page.wait_for_timeout(700)
        await page.evaluate("window.scrollTo(0, 0)")
        geometry = await page.evaluate(GEOMETRY_JS)
        geometry["fixture_ids"] = await page.evaluate(
            "() => Object.fromEntries([...document.querySelectorAll('[data-lumen-probe]')]"
            ".map((el) => [el.dataset.lumenProbe, el.id]))"
        )
        geometry["states"] = await probe_states(page, geometry, reveal_before=reveal_before, diagnostics=[])
        geometry["url"] = "https://fixture.test/"
        await browser.close()
    (HERE / "style_states.harvest.json").write_text(json.dumps(geometry, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
