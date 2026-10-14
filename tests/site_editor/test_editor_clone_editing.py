"""Editing cloned sections on the canvas (review findings S1-1, S1-2, S1-4).

- S1-1: Puck re-ran the clone's "refill with the seller's wording" rule on every page mount,
  comparing with the last section it saw with the same id on ANY page, so moving to a page whose
  "hero" is another clone reset the agent's copy to the seller's, and the frame saved that.
- S1-2: leaving a clone's text without typing rewrote it (line breaks flattened) and saved it.
- S1-4: clearing a clone's text left the canvas empty while the saved page shows the seller's words.

    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_clone_editing.py
"""

from __future__ import annotations

from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."
HERO_SLOT = '[data-puck-component="hero"] [data-lumen-slot="headline"][contenteditable="true"]'
AGENT_COPY = "Better data for Syracuse City School District"


def changed_after(page: Any, start: int) -> list[dict[str, Any]]:
    return [m for m in received(page)[start:] if m["type"] == "changed"]


def open_site(
    app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]
) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def test_moving_to_a_page_whose_hero_is_another_clone_keeps_the_agents_copy_and_saves_nothing(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    init = garner_init(mode="edit")
    analysis = init["site"]["pages"]["/analysis"]["content"]
    analysis.insert(
        0,
        {
            "type": "ClonedSection",
            "props": {
                "id": "hero",
                "fragmentId": "frag_9a8550d2f42f1196",
                "slots": {"headline": AGENT_COPY},
                "replacements": [],
                "links": [],
            },
        },
    )
    page, frame = open_site(app, browser_page, editor_origin, init)
    mark = len(received(page))
    page.evaluate("window.__send('navigate', { route: '/analysis' })")
    frame.get_by_text(AGENT_COPY).first.wait_for(timeout=10000)
    page.wait_for_timeout(1500)
    assert changed_after(page, mark) == [], "moving between pages never saves"
    page.evaluate("window.__send('navigate', { route: '/' })")
    frame.get_by_text(PROOF).first.wait_for(timeout=10000)
    page.evaluate("window.__send('navigate', { route: '/analysis' })")
    frame.get_by_text(AGENT_COPY).first.wait_for(timeout=10000)
    page.wait_for_timeout(1500)
    assert changed_after(page, mark) == []


def never_set_hero_headline() -> dict[str, Any]:
    init = garner_init(mode="edit")
    hero = next(e for e in init["site"]["pages"]["/"]["content"] if e["props"]["id"] == "hero")
    hero["props"]["slots"].pop("headline", None)  # the seller's own two-line headline
    return init


def test_leaving_a_clone_headline_without_typing_saves_nothing(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, never_set_hero_headline())
    mark = len(received(page))
    frame.locator(HERO_SLOT).first.click(force=True)
    page.wait_for_timeout(300)
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(1500)
    assert changed_after(page, mark) == []
    assert frame.locator(HERO_SLOT).first.evaluate("e => e.querySelectorAll('br').length") > 0, (
        "the headline keeps its line break"
    )


def test_clearing_a_never_set_clone_headline_shows_what_will_publish(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, never_set_hero_headline())
    slot = frame.locator(HERO_SLOT).first
    slot.click(force=True)
    page.keyboard.press("Meta+a")
    page.keyboard.press("Delete")
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(1500)
    # An empty text slot publishes the seller's original words, so the canvas must show them too.
    text = frame.locator(
        '[data-puck-component="hero"] [data-lumen-slot="headline"]'
    ).first.inner_text()
    assert "Top Providers" in text, repr(text)
