"""Site element inspector, plan 4: boxes in the real editor frame.

A click on a card selects it as a box named "Card" with its look as drawn; a click between stats
selects their grid; a click on blank section space selects the section with its own box; a copied
card three wrappers deep is selected itself, and Layers leaves the wrappers out. A `set_props`
carrying a box's `_edits` redraws it; a content alignment set on the footer's row keeps its property
when the footer becomes a stack on a phone; a hidden header logo is drawn hidden and still listed.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_containers.py
"""

from __future__ import annotations

import copy
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received
from .test_editor_element_styling import computed, wait_selected

pytestmark = BROWSER_OPT_IN
CARD = '[data-puck-component="card_proof"] [data-clue-el="card"]'
PROOF = {
    "id": "card_proof",
    "surface": "card",
    "kicker": "Carmel Clay",
    "metric": "13%",
    "metricLabel": "lower cost",
    "heading": "What changed",
    "body": "Fewer surprises.",
    "source": "",
    "linkLabel": "",
    "linkHref": "",
}
WRAPPED_ID = "frag_00000000000000c4"
WRAPPED = {
    "id": WRAPPED_ID,
    "role": "section",
    "label": "Wrapped cards",
    "page_url": "https://garnerhealth.com/",
    "section_index": 0,
    "wrapper_class": "lumen-frag-wrapped",
    # A Webflow-like section: three wrappers around a row of cards.
    "html": (
        '<section class="wr"><div class="w1"><div class="w2"><div class="row">'
        '<div class="card"><h3>Alpha</h3><p>One</p></div><div class="card"><h3>Beta</h3><p>Two</p></div>'
        "</div></div></div></section>"
    ),
    "css": (
        ".wr{padding:40px}.row{display:flex;gap:24px}"
        ".card{background:#F4F6F5;border-radius:12px;padding:24px;flex:1}"
    ),
    "slots": {},
}


def boxes_init() -> dict[str, Any]:
    init = garner_init(mode="edit")
    init["brand"]["clones"][WRAPPED_ID] = WRAPPED
    content = init["site"]["pages"]["/"]["content"]
    content.insert(0, {"type": "ProofCard", "props": dict(PROOF)})
    content.insert(1, {"type": "ClonedSection", "props": {"id": "wrapped", "fragmentId": WRAPPED_ID, "slots": {}, "replacements": [], "links": []}})
    return init


def open_boxes(app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.locator(CARD).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def click_at(page: Any, frame: Any, selector: str, dx: float, dy: float) -> None:
    """A click at an offset inside the element's box, in page coordinates (through the frame)."""
    frame.locator(selector).first.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = frame.locator(selector).first.bounding_box()
    assert box, selector
    page.mouse.click(box["x"] + dx, box["y"] + dy)


def last_selected(page: Any, component: str) -> dict[str, Any]:
    return [m["payload"] for m in received(page) if m["type"] == "selected" and m["payload"]["componentId"] == component][-1]


def test_a_click_on_a_card_selects_the_box_with_its_look(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    mark = len(received(page))
    click_at(page, frame, CARD, 6, 6)  # the card's padding, outside its texts
    element = wait_selected(page, mark, "card", "card_proof")["element"]
    assert element["kind"] == "container" and element["label"] == "Card", element
    container = element["container"]
    assert container["layout"] == "grid" and container["name"] == "Card" and container["paddingY"] > 0, container


def test_between_stats_the_grid_and_blank_section_space_the_section_with_its_box(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    frame.locator('[data-puck-component="proof"] [data-clue-el="stats"]').first.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    first = frame.locator('[data-puck-component="proof"] [data-clue-el="stats.0"]').first.bounding_box()
    second = frame.locator('[data-puck-component="proof"] [data-clue-el="stats.1"]').first.bounding_box()
    assert first and second
    mark = len(received(page))
    page.mouse.click((first["x"] + first["width"] + second["x"]) / 2, first["y"] + 10)
    payload = wait_selected(page, mark, "stats", "proof")
    assert payload["element"]["container"]["layout"] == "grid", payload["element"]
    parents = {element["key"]: element.get("parent") for element in payload["elements"]}
    assert parents["stats.0"] == "stats" and parents["stats.0.value"] == "stats.0", parents

    root = frame.locator('[data-puck-component="proof"] [data-clue-el="root.inner"]').first.bounding_box()
    assert root
    mark = len(received(page))
    page.mouse.click(root["x"] + 2, root["y"] + root["height"] - 2)  # the section's own padding
    payload = wait_selected(page, mark, None, "proof")
    assert payload["sectionBox"]["outer"]["key"] == "root" and payload["sectionBox"]["inner"]["key"] == "root.inner", payload.get("sectionBox")


def test_a_copied_card_through_three_wrappers_is_selected_and_layers_skip_the_wrappers(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_boxes(app, browser_page, editor_origin, boxes_init())
    card = '[data-puck-component="wrapped"] .card'
    mark = len(received(page))
    click_at(page, frame, card, 6, 6)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected' && m.payload.componentId === 'wrapped' && m.payload.element)""",
        arg=mark,
        timeout=10000,
    )
    payload = last_selected(page, "wrapped")
    key = frame.locator(card).first.get_attribute("data-clue-el")
    assert payload["element"]["key"] == key and payload["element"]["label"] == "Card", payload["element"]
    assert payload["element"]["arrange"]["siblings"] == [key, frame.locator(card).nth(1).get_attribute("data-clue-el")], payload["element"]["arrange"]
    listed = [element["key"] for element in payload["elements"]]
    for wrapper in (".w1", ".w2"):
        assert frame.locator(f'[data-puck-component="wrapped"] {wrapper}').first.get_attribute("data-clue-el") not in listed, (wrapper, listed)


def test_a_boxs_edits_redraw_it(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = boxes_init()
    page, frame = open_boxes(app, browser_page, editor_origin, init)
    props = copy.deepcopy(PROOF)
    props["_edits"] = {
        "card": {"fill": {"hex": "#FF0000", "opacity": 100}, "radius": 20, "gap": 40, "contentAlign": {"along": "grid", "to": "center"}},
        "root": {"fill": {"hex": "#00FF00", "opacity": 100}},
    }
    page.evaluate("(props) => window.__send('set_props', { route: '/', componentId: 'card_proof', props, rev: 2 })", props)
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).backgroundColor === 'rgb(255, 0, 0)'; }""",
        arg=CARD,
        timeout=10000,
    )
    assert computed(frame, CARD, "borderTopLeftRadius") == "20px"
    assert computed(frame, CARD, "columnGap") == "40px"
    assert computed(frame, CARD, "justifyItems") == "center"
    assert computed(frame, '[data-puck-component="card_proof"] [data-clue-el="root"]', "backgroundColor") == "rgb(0, 255, 0)"


def test_footer_alignment_keeps_its_property_on_a_phone_and_a_hidden_logo_is_listed(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = boxes_init()
    page, frame = open_boxes(app, browser_page, editor_origin, init)
    shell = copy.deepcopy(init["site"]["shell"])
    shell["footer"]["_edits"] = {"root.inner": {"contentAlign": {"along": "row", "to": "center"}}}
    shell["header"]["_edits"] = {"logo": {"hidden": True}}
    site = copy.deepcopy(init["site"])
    site["shell"] = shell
    page.evaluate("(site) => window.__send('replace_site', { site, rev: 3 })", site)
    inner = 'footer [data-clue-el="root.inner"]'
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).justifyContent === 'center'; }""",
        arg=inner,
        timeout=10000,
    )
    assert computed(frame, inner, "flexDirection") == "row"
    page.evaluate("() => { document.querySelector('iframe').style.width = '390px'; }")
    frame.wait_for_function("(sel) => getComputedStyle(document.querySelector(sel)).flexDirection === 'column'", arg=inner, timeout=10000)
    assert computed(frame, inner, "justifyContent") == "center", "the same property on a phone"
    page.evaluate("() => { document.querySelector('iframe').style.width = ''; }")

    assert computed(frame, 'header [data-clue-el="logo"]', "display") == "none"
    mark = len(received(page))
    click_at(page, frame, 'header [data-clue-el="root.inner"]', 2, 2)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected' && m.payload.componentId === 'header')""",
        arg=mark,
        timeout=10000,
    )
    logo = [element for element in last_selected(page, "header")["elements"] if element["key"] == "logo"]
    assert logo and logo[0].get("hidden") is True and logo[0]["kind"] == "image", logo
