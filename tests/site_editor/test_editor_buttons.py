"""Site element inspector, plan 3: buttons in the real editor frame.

A click on a brand section's button, on a copied section's button (words in a span beside an icon)
and on the header's button posts `selected` with a button: its box as drawn, its words' key and
where they are stored. A `set_props` carrying the box's `_edits` redraws the button — fill, corners
and width — and a hand-set fill holds while the button is hovered; words styled inside its label
are drawn too.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_buttons.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received
from .test_editor_element_styling import computed, wait_selected

pytestmark = BROWSER_OPT_IN
KITS = Path(__file__).resolve().parents[2] / "apps" / "frontend" / "packages" / "site-kit" / "test" / "fixtures" / "kits"
WHAT = '[data-puck-component="what"]'
CLOSE_ID = "frag_00000000000000c1"
CLOSE = {
    "id": CLOSE_ID,
    "role": "section",
    "label": "Close",
    "page_url": "https://garnerhealth.com/",
    "section_index": 0,
    "wrapper_class": "lumen-frag-close",
    "html": (
        '<div class="close"><h2 data-lumen-slot="headline">Ready to see it?</h2>'
        '<a href="/book-a-demo" class="btn" data-lumen-slot="cta_href"><span>Book a demo</span>'
        '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M6 12h12" stroke="currentColor"/></svg></a></div>'
    ),
    "css": ".close{padding:48px}.close .btn{display:inline-flex;gap:8px;background:#0F59B0;color:#fff;padding:12px 20px;border-radius:4px}",
    "slots": {
        "headline": {"kind": "text", "fallback": "Ready to see it?"},
        "cta_href": {"kind": "href", "fallback": "/book-a-demo"},
    },
}


def analysis_init() -> dict[str, Any]:
    """Garner's site opened on its analysis page, whose first section (a FeatureSplit) has a button,
    with a copied close section added there whose button is a span and an icon."""
    init = garner_init(mode="edit")
    init["route"] = "/analysis"
    init["brand"]["clones"][CLOSE_ID] = CLOSE
    init["site"]["pages"]["/analysis"]["content"].append(
        {"type": "ClonedSection", "props": {"id": "close", "fragmentId": CLOSE_ID, "slots": {}, "replacements": [], "links": []}}
    )
    return init


def open_analysis(app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.locator(f'{WHAT} [data-clue-el="button"]').first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def what_props(init: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(next(item["props"] for item in init["site"]["pages"]["/analysis"]["content"] if item["props"]["id"] == "what"))


def test_a_click_on_a_brand_button_selects_the_button_with_its_box_and_words(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_analysis(app, browser_page, editor_origin, analysis_init())
    mark = len(received(page))
    frame.locator(f'{WHAT} [data-clue-el="button.label"]').click(force=True)
    element = wait_selected(page, mark, "button", "what")["element"]
    assert element["kind"] == "button" and element["label"] == "Request the analysis", element
    assert element["labelElement"]["key"] == "button.label"
    assert element["labelElement"]["rich"]["prop"] == "buttonLabel"
    assert element["labelSource"] == {"kind": "prop", "prop": "buttonLabel"}
    assert element["link"]["source"] == {"kind": "prop", "href": "buttonHref", "newTab": "buttonNewTab"}
    box = element["box"]
    assert box["fill"].startswith("#") and box["width"] > 0 and len(box["radius"]) == 4, box


def test_a_copied_button_with_an_icon_and_the_headers_button_are_buttons(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_analysis(app, browser_page, editor_origin, analysis_init())
    mark = len(received(page))
    frame.locator('[data-puck-component="close"] a.btn svg').click(force=True)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected' && m.payload.componentId === 'close'
          && m.payload.element && m.payload.element.kind === 'button')""",
        arg=mark,
        timeout=10000,
    )
    element = [m["payload"]["element"] for m in received(page)[mark:] if m["type"] == "selected" and m["payload"]["componentId"] == "close"][-1]
    assert element["label"] == "Book a demo", element
    assert element["box"]["fill"] == "#0F59B0" and element["box"]["paddingX"] == 20, element["box"]
    assert element["labelSource"] == {"kind": "replacement", "find": "Book a demo"}, element["labelSource"]
    assert element["link"]["source"]["kind"] == "slot", element["link"]

    mark = len(received(page))
    frame.locator('[data-clue-el="cta"]').first.click(force=True)
    header = wait_selected(page, mark, "cta", "header")["element"]
    assert header["kind"] == "button" and header["labelElement"]["key"] == "cta.label", header
    assert header["link"]["source"] == {"kind": "prop", "href": "ctaHref", "newTab": "ctaNewTab"}


def test_the_boxs_edits_redraw_the_button_and_a_hand_set_fill_holds_on_hover(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = analysis_init()
    # A kit whose filled buttons change fill on hover (the fixture's default kit has no hover look),
    # and the section's button in one of those looks.
    init["brand"]["kit"] = json.loads((KITS / "probe.minted.json").read_text())
    what = next(item["props"] for item in init["site"]["pages"]["/analysis"]["content"] if item["props"]["id"] == "what")
    what["buttonLook"] = "solid.0a4a8a"
    page, frame = open_analysis(app, browser_page, editor_origin, init)
    button = f'{WHAT} [data-clue-el="button"]'
    # Puck turns pointer events off inside sections; turn them on for the button so the pointer can
    # rest on it, as on the published page. Untouched, the brand's hover changes its colour.
    resting = computed(frame, button, "backgroundColor")
    frame.locator(button).first.evaluate("(el) => { el.style.pointerEvents = 'auto'; }")
    frame.locator(button).first.hover(force=True)
    frame.wait_for_function("(sel) => document.querySelector(sel).matches(':hover')", arg=button, timeout=5000)
    page.wait_for_timeout(400)  # the brand's hover transition
    assert computed(frame, button, "backgroundColor") != resting, "the brand's own hover look"
    page.mouse.move(0, 0)
    props = what_props(init)
    props["buttonLabel"] = 'Request <span data-s="button.label~1">the analysis</span>'
    props["_edits"] = {
        "button": {"fill": {"hex": "#FF0000", "opacity": 100}, "radius": "pill", "width": "fill", "padding": {"y": 10, "x": 30}},
        "button.label~1": {"fontWeight": 700, "italic": True},
    }
    page.evaluate("(props) => window.__send('set_props', { route: '/analysis', componentId: 'what', props, rev: 2 })", props)
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).backgroundColor === 'rgb(255, 0, 0)'; }""",
        arg=button,
        timeout=10000,
    )
    assert computed(frame, button, "borderTopLeftRadius") == "9999px"
    assert computed(frame, button, "paddingLeft") == "30px" and computed(frame, button, "paddingTop") == "10px"
    width = frame.locator(button).first.evaluate("(el) => el.getBoundingClientRect().width")
    parent = frame.locator(button).first.evaluate("(el) => el.parentElement.getBoundingClientRect().width")
    assert abs(width - parent) < 1, (width, parent)
    word = f'{WHAT} [data-s="button.label~1"]'
    assert computed(frame, word, "fontWeight") == "700" and computed(frame, word, "fontStyle") == "italic"

    frame.locator(button).first.evaluate("(el) => { el.style.pointerEvents = 'auto'; }")
    frame.locator(button).first.hover(force=True)
    page.wait_for_timeout(400)
    assert frame.locator(button).first.evaluate("(el) => el.matches(':hover')"), "the pointer rests on the button"
    assert computed(frame, button, "backgroundColor") == "rgb(255, 0, 0)", "the hand-set fill holds on hover"
