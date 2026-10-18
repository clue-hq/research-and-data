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

import io
from typing import Any

from PIL import Image

from .conftest import BROWSER_OPT_IN, received
from .test_editor_containers import boxes_init, click_at, open_boxes
from .test_editor_element_styling import wait_selected

pytestmark = BROWSER_OPT_IN
PROOF = '[data-puck-component="proof"]'
WRAPPED = '[data-puck-component="wrapped"]'
LAYERED = '[data-puck-component="layered"]'
LAYERED_ID = "frag_00000000000000c5"
# A copied section drawn the way Webflow heroes are: its colour is a positioned layer above the section's
# own box (live check 2026-10-19: Oliver's copied hero showed no outline at all). Its margin keeps its own
# box (the background) smaller than the section.
LAYERED_CLONE = {
    "id": LAYERED_ID,
    "role": "section",
    "label": "Layered hero",
    "page_url": "https://garnerhealth.com/",
    "section_index": 1,
    "wrapper_class": "lumen-frag-layered",
    "html": (
        '<ls-h style="display:contents!important"><ls-b style="display:contents!important">'
        '<section class="lh"><div class="lh-bg"></div><div class="lh-in"><h2>Layered</h2></div></section></ls-b></ls-h>'
    ),
    "css": (
        ".lh{position:relative;padding:80px 40px;min-height:200px;margin:0 24px}"
        ".lh-bg{position:absolute;inset:0;z-index:1;background:#2D6A4F}"
        ".lh-in{position:relative;z-index:2;max-width:400px;margin:0 auto}"
    ),
    "slots": {},
}
AZURE = (1, 88, 173)


def layered_init() -> dict[str, Any]:
    init = boxes_init()
    init["brand"]["clones"][LAYERED_ID] = LAYERED_CLONE
    init["site"]["pages"]["/"]["content"].insert(2, {"type": "ClonedSection", "props": {"id": "layered", "fragmentId": LAYERED_ID, "slots": {}, "replacements": [], "links": []}})
    return init


def azure_at_left_edge(page: Any, frame: Any, selector: str) -> bool:
    """Whether the outline's colour is painted just inside the element's left edge, halfway down."""
    box = frame.locator(selector).first.bounding_box()
    assert box
    shot = Image.open(io.BytesIO(page.screenshot(clip={"x": box["x"], "y": box["y"] + box["height"] / 2 - 2, "width": 6, "height": 4}))).convert("RGB")
    return any(all(abs(a - b) <= 40 for a, b in zip(shot.getpixel((x, y)), AZURE)) for x in range(shot.width) for y in range(shot.height))


def drawn(frame: Any, wrapper: str, pseudo: str) -> dict[str, Any]:
    """The outline the section's wrapper draws (::after selected, ::before under the pointer): its
    line, and its box relative to the wrapper."""
    return frame.evaluate(
        """([sel, pseudo]) => { const s = getComputedStyle(document.querySelector(sel), pseudo);
          return { style: s.borderTopStyle, box: [s.top, s.left, s.width, s.height].map((v) => Math.round(parseFloat(v))) }; }""",
        [wrapper, pseudo],
    )


def box_in(frame: Any, wrapper: str, selector: str) -> list[int]:
    """The element's box relative to the wrapper, as [top, left, width, height]."""
    return frame.evaluate(
        """([w, sel]) => { const a = document.querySelector(w).getBoundingClientRect(); const b = document.querySelector(sel).getBoundingClientRect();
          return [b.top - a.top, b.left - a.left, b.width, b.height].map(Math.round); }""",
        [wrapper, selector],
    )


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
    assert drawn(frame, PROOF, "::after") == {"style": "solid", "box": box_in(frame, PROOF, PROOF)}, "the selected section is outlined"

    mark = len(received(page))
    blank_of_proof(page, frame)
    payload = wait_background(page, mark, "proof")
    assert payload["sectionBox"]["outer"]["key"] == "root" and payload["sectionBox"]["inner"]["key"] == "root.inner", payload["sectionBox"]
    root = f'{PROOF} [data-clue-el="root"]'
    page.wait_for_timeout(300)
    assert drawn(frame, PROOF, "::after") == {"style": "solid", "box": box_in(frame, PROOF, root)}, "now around the background"
    assert frame.locator("[data-clue-el-selected]").count() == 1, "only the background is selected now"


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
    page, frame = open_boxes(app, browser_page, editor_origin, layered_init())
    section = f"{LAYERED} section.lh"
    frame.locator(section).first.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = frame.locator(section).first.bounding_box()
    assert box
    assert box_in(frame, LAYERED, section) != box_in(frame, LAYERED, LAYERED), "the background is smaller than the section"
    page.mouse.move(box["x"] + 20, box["y"] + 20)
    frame.locator(f"{LAYERED}[data-clue-el-hovered]").wait_for(timeout=5000)
    assert drawn(frame, LAYERED, "::before") == {"style": "dashed", "box": box_in(frame, LAYERED, LAYERED)}, "an unselected section: the section"

    mark = len(received(page))
    page.mouse.click(box["x"] + 20, box["y"] + 20)
    wait_selected(page, mark, None, "layered")
    page.mouse.move(box["x"] + 24, box["y"] + 24)
    expected = box_in(frame, LAYERED, section)
    frame.wait_for_function(
        """([w, top]) => Math.round(parseFloat(getComputedStyle(document.querySelector(w), '::before').top)) === top""",
        arg=[LAYERED, expected[0]],
        timeout=5000,
    )
    assert drawn(frame, LAYERED, "::before") == {"style": "dashed", "box": expected}, "the selected section: its background"
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


def test_the_outline_of_a_copied_section_is_painted_above_its_own_layers(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, layered_init())
    inner = f"{LAYERED} .lh-in"
    frame.locator(LAYERED).first.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    section = frame.locator(f"{LAYERED} section.lh").first.bounding_box()
    assert section
    mark = len(received(page))
    page.mouse.click(section["x"] + 20, section["y"] + 20)  # its padding, beside the inner column
    wait_selected(page, mark, None, "layered")
    page.mouse.move(2, 2)
    page.wait_for_timeout(400)
    assert azure_at_left_edge(page, frame, LAYERED), "the selected section's outline is visible over its colour layer"
    mark = len(received(page))
    page.mouse.click(section["x"] + 20, section["y"] + 20)
    wait_background(page, mark, "layered")
    page.mouse.move(2, 2)
    page.wait_for_timeout(400)
    assert azure_at_left_edge(page, frame, f"{LAYERED} section.lh"), "the background's outline is visible too"
    assert frame.locator(inner).count() == 1
