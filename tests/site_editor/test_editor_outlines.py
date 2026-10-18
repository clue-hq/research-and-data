"""Site editor canvas outlines (founder 2026-10-19): in edit mode the element under the pointer gets a
dashed outline and the selected element a solid one, the way the marketer can always see which box a
click picks. Both hold inside a copied section whose own stylesheet resets outlines (a seller's CSS is
scoped under the copy's wrapper and outranks a plain rule: the live sites showed no outline at all).

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_outlines.py
"""

from __future__ import annotations

import re
from typing import Any

from .conftest import BROWSER_OPT_IN, garner_init, received
from .test_editor_element_styling import open_site, wait_selected

pytestmark = BROWSER_OPT_IN

# What a seller's stylesheet does inside a copy: a reset scoped under the copy, stronger than a plain
# attribute rule.
SELLER_RESET = "[data-lumen-fragment] [data-clue-el] { outline: none; }"


def outline(frame: Any, selector: str) -> dict[str, str]:
    return frame.evaluate(
        """(sel) => { const s = getComputedStyle(document.querySelector(sel)); return { style: s.outlineStyle, width: s.outlineWidth }; }""",
        selector,
    )


def clone_text(frame: Any) -> tuple[Any, str]:
    target = frame.locator('[data-puck-component="hero"] [data-clue-el]:not(:has([data-clue-el]))').filter(has_text=re.compile(r"\w")).first
    key = target.get_attribute("data-clue-el")
    assert key
    return target, f'[data-puck-component="hero"] [data-clue-el="{key}"]'


def test_the_selected_element_has_a_solid_outline_even_inside_a_copy_that_resets_outlines(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    frame.evaluate("(css) => { const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); }", SELLER_RESET)
    target, selector = clone_text(frame)
    mark = len(received(page))
    target.click(force=True)
    wait_selected(page, mark, target.get_attribute("data-clue-el"), "hero")
    frame.locator(f"{selector}[data-clue-el-selected]").wait_for(timeout=5000)
    assert outline(frame, selector) == {"style": "solid", "width": "2px"}


def test_the_element_under_the_pointer_has_a_dashed_outline_and_loses_it_when_the_pointer_leaves(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    frame.evaluate("(css) => { const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); }", SELLER_RESET)
    target, selector = clone_text(frame)
    target.hover(force=True)
    frame.locator(f"{selector}[data-clue-el-hovered]").wait_for(timeout=5000)
    assert outline(frame, selector)["style"] == "dashed"
    assert frame.locator("[data-clue-el-hovered]").count() == 1, "one element at a time"
    page.mouse.move(2, 2)
    frame.wait_for_function("() => !document.querySelector('[data-clue-el-hovered]')", timeout=5000)


def test_hovering_the_selected_element_keeps_its_solid_outline(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    target, selector = clone_text(frame)
    mark = len(received(page))
    target.click(force=True)
    wait_selected(page, mark, target.get_attribute("data-clue-el"), "hero")
    target.hover(force=True)
    frame.locator(f"{selector}[data-clue-el-selected]").wait_for(timeout=5000)
    assert outline(frame, selector) == {"style": "solid", "width": "2px"}


def test_no_hover_outline_outside_edit_mode(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="preview"))
    # Outside edit mode the copy's words carry no element keys: hover any heading or paragraph.
    frame.locator("h1, h2, p").first.hover(force=True)
    page.wait_for_timeout(500)
    assert frame.locator("[data-clue-el-hovered]").count() == 0
