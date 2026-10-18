"""Site editor: the section and its background (founder 2026-10-19).

A first click on a section's blank space selects the section (Layers only: no box of its own rides
along, only the key of its background); a second click on blank space of that selected section
selects its background, its own outermost box, with the box the panel edits. Both get the canvas
outlines elements get: solid when selected, dashed under the pointer, where the dashed one previews
what the next click selects. Puck's own section outline and hover tint are not drawn.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_section_background.py
"""

from __future__ import annotations

from typing import Any

from .conftest import BROWSER_OPT_IN, received
from .test_editor_containers import boxes_init, click_at, open_boxes
from .test_editor_element_styling import wait_selected

pytestmark = BROWSER_OPT_IN
PROOF = '[data-puck-component="proof"]'
WRAPPED = '[data-puck-component="wrapped"]'


def outline_style(frame: Any, selector: str) -> str:
    return frame.evaluate("(sel) => getComputedStyle(document.querySelector(sel)).outlineStyle", selector)


def wait_background(page: Any, start: int, component: str) -> dict[str, Any]:
    page.wait_for_function(
        """([start, component]) => window.__received.slice(start).some((m) =>
          m.type === 'selected' && m.payload.componentId === component && !m.payload.element && m.payload.sectionBox)""",
        arg=[start, component],
        timeout=10000,
    )
    return [m["payload"] for m in received(page)[start:] if m["type"] == "selected" and m["payload"]["componentId"] == component][-1]


def blank_of_proof(page: Any, frame: Any) -> None:
    """The proof section's own bottom padding: blank space, no element under it."""
    frame.locator(f'{PROOF} [data-clue-el="root.inner"]').first.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    root = frame.locator(f'{PROOF} [data-clue-el="root.inner"]').first.bounding_box()
    assert root
    page.mouse.click(root["x"] + 2, root["y"] + root["height"] - 2)


def test_first_blank_click_selects_the_section_and_a_second_its_background(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    mark = len(received(page))
    blank_of_proof(page, frame)
    payload = wait_selected(page, mark, None, "proof")
    assert not payload.get("sectionBox"), "the whole section carries no box (Layers only)"
    assert payload["backgroundKey"] == "root", payload.get("backgroundKey")
    frame.locator(f"{PROOF}[data-clue-el-selected]").wait_for(timeout=5000)
    assert outline_style(frame, PROOF) == "solid", "the selected section is outlined like an element"

    mark = len(received(page))
    blank_of_proof(page, frame)
    payload = wait_background(page, mark, "proof")
    assert payload["sectionBox"]["outer"]["key"] == "root" and payload["sectionBox"]["inner"]["key"] == "root.inner", payload["sectionBox"]
    root = f'{PROOF} [data-clue-el="root"]'
    frame.locator(f"{root}[data-clue-el-selected]").wait_for(timeout=5000)
    assert outline_style(frame, root) == "solid"
    assert frame.locator(f"{PROOF}[data-clue-el-selected]").count() == 0, "only the background is selected now"


def test_a_copied_sections_background_is_its_one_top_element(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    section = f"{WRAPPED} section.wr"
    key = frame.locator(section).first.get_attribute("data-clue-el")
    mark = len(received(page))
    click_at(page, frame, section, 4, 4)
    assert wait_selected(page, mark, None, "wrapped")["backgroundKey"] == key
    mark = len(received(page))
    click_at(page, frame, section, 4, 4)
    payload = wait_background(page, mark, "wrapped")
    assert payload["sectionBox"]["outer"]["key"] == key == payload["sectionBox"]["inner"]["key"], payload["sectionBox"]
    assert payload["sectionBox"]["inner"]["container"]["paddingY"] == 40, payload["sectionBox"]


def test_the_dashed_outline_over_blank_space_previews_the_next_click(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    section = f"{WRAPPED} section.wr"
    frame.locator(section).first.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = frame.locator(section).first.bounding_box()
    assert box
    page.mouse.move(box["x"] + 4, box["y"] + 4)
    frame.locator(f"{WRAPPED}[data-clue-el-hovered]").wait_for(timeout=5000)
    assert outline_style(frame, WRAPPED) == "dashed", "an unselected section: the section"

    mark = len(received(page))
    page.mouse.click(box["x"] + 4, box["y"] + 4)
    wait_selected(page, mark, None, "wrapped")
    page.mouse.move(box["x"] + 6, box["y"] + 6)
    frame.locator(f"{section}[data-clue-el-hovered]").wait_for(timeout=5000)
    assert outline_style(frame, section) == "dashed", "the selected section: its background"
    assert frame.locator("[data-clue-el-hovered]").count() == 1


def test_puck_draws_no_section_outline_or_hover_tint_of_its_own(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    mark = len(received(page))
    blank_of_proof(page, frame)
    wait_selected(page, mark, None, "proof")
    page.wait_for_timeout(300)
    overlays = frame.evaluate(
        """() => [...document.querySelectorAll('[class*="_DraggableComponent-overlay_"]')].map((el) => {
          const s = getComputedStyle(el); return { outline: s.outlineStyle, background: s.backgroundColor };
        })"""
    )
    assert overlays, "Puck draws its overlay for the selected section"
    assert all(o["outline"] == "none" and o["background"] in ("rgba(0, 0, 0, 0)", "transparent") for o in overlays), overlays
