"""Site element inspector, plan 2: highlighted words and links, in the real editor frame.

The frame reports words highlighted in a text element (offsets, the words, where the text is stored)
and where an element's link is written; after the app writes a styled span the canvas draws it and
the highlight comes back, so the panel goes on acting on the same words.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_words_and_links.py
"""

from __future__ import annotations

import copy
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received
from .test_editor_rich_text import HEADING, HERO_SLOT, PROOF, select_word

pytestmark = BROWSER_OPT_IN


def open_site(app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def selected_with_words(page: Any, start: int, component: str, text: str) -> dict[str, Any]:
    try:
        page.wait_for_function(
            """([start, component, text]) => window.__received.slice(start).some((m) => m.type === 'selected'
              && m.payload.componentId === component && m.payload.element && m.payload.element.words
              && m.payload.element.words.text === text)""",
            arg=[start, component, text],
            timeout=10000,
        )
    except Exception as error:  # noqa: BLE001 - re-raised with what was posted
        seen = [
            (m["payload"].get("componentId"), (m["payload"].get("element") or {}).get("key"), (m["payload"].get("element") or {}).get("words"))
            for m in received(page)[start:]
            if m["type"] == "selected"
        ]
        raise AssertionError(f"no selected with words {text!r}; posted {seen}") from error
    return [
        m["payload"]["element"]
        for m in received(page)[start:]
        if m["type"] == "selected" and (m["payload"].get("element") or {}).get("words", {}) and m["payload"]["element"]["words"]["text"] == text
    ][-1]


def props_of(init: dict[str, Any], component_id: str) -> dict[str, Any]:
    for item in init["site"]["pages"]["/"]["content"]:
        if item["props"]["id"] == component_id:
            return copy.deepcopy(item["props"])
    raise AssertionError(component_id)


def test_highlighting_words_in_a_heading_reports_them_and_a_styled_span_keeps_the_highlight(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    init = garner_init(mode="edit")
    page, frame = open_site(app, browser_page, editor_origin, init)
    frame.locator(HEADING).click(force=True)
    mark = len(received(page))
    select_word(frame, HEADING, "lower")
    element = selected_with_words(page, mark, "proof", "lower")
    assert element["key"] == "heading" and element["rich"] == {"prop": "heading"}, element
    assert element["words"]["start"] == 5 and element["words"]["end"] == 10 and element["words"]["count"] == 1, element

    # The app writes the words' styled span and its look, as the panel does.
    props = props_of(init, "proof")
    props["heading"] = '7.4% <span data-s="heading~1">lower</span> medical spend in year one. No plan changes.'
    props["_edits"] = {"heading~1": {"fontWeight": 700, "color": {"hex": "#0F59B0", "opacity": 100}}}
    mark = len(received(page))
    page.evaluate("(props) => window.__send('set_props', { route: '/', componentId: 'proof', props, rev: 2 })", props)
    span = frame.locator(f'{HEADING} [data-s="heading~1"]')
    span.wait_for(timeout=10000)
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).fontWeight === '700'; }""",
        arg=f'{HEADING} [data-s="heading~1"]',
        timeout=10000,
    )
    page.wait_for_timeout(500)
    assert frame.evaluate("() => document.getSelection().toString()") == "lower", "the highlight comes back after the redraw"
    later = [m for m in received(page)[mark:] if m["type"] == "selected"]
    assert all((m["payload"].get("element") or {}).get("words") for m in later), "no selected clears the words after a redraw"


def test_a_click_elsewhere_in_the_text_clears_the_words(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    frame.locator(HEADING).click(force=True)
    mark = len(received(page))
    select_word(frame, HEADING, "medical")
    selected_with_words(page, mark, "proof", "medical")
    mark = len(received(page))
    frame.locator(HEADING).click(force=True)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected' && m.payload.element
          && m.payload.element.key === 'heading' && !m.payload.element.words)""",
        arg=mark,
        timeout=10000,
    )


def test_words_in_a_clone_slot_name_the_slot_and_its_captured_words(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = garner_init(mode="edit")
    hero = next(c for c in init["site"]["pages"]["/"]["content"] if c["props"]["id"] == "hero")
    hero["props"]["slots"].pop("headline", None)
    page, frame = open_site(app, browser_page, editor_origin, init)
    slot = frame.locator(HERO_SLOT).first
    slot.click(force=True)
    word = slot.inner_text().split()[0]
    mark = len(received(page))
    select_word(frame, HERO_SLOT, word)
    element = selected_with_words(page, mark, "hero", word)
    assert element["rich"]["prop"] == "slots.headline", element
    assert word in element["rich"]["fallback"], element


def test_links_say_where_they_are_written(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = garner_init(mode="edit")
    init["site"]["shell"]["header"]["nav"] = [{"label": "Analysis", "href": "/analysis"}]
    page, frame = open_site(app, browser_page, editor_origin, init)
    mark = len(received(page))
    frame.locator('header [data-clue-el="nav.0"]').click(force=True)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected' && m.payload.element
          && m.payload.element.key === 'nav.0')""",
        arg=mark,
        timeout=10000,
    )
    element = [m for m in received(page)[mark:] if m["type"] == "selected"][-1]["payload"]["element"]
    assert element["link"] == {"source": {"kind": "prop", "href": "nav.0.href", "newTab": "nav.0.newTab"}, "href": "/analysis"}, element
    assert element["rich"] is None
