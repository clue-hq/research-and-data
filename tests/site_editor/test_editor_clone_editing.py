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


STANDS = '[data-puck-component="stands"] [data-lumen-slot="{key}"]'
ACTIVE_SLOT = (
    "document.activeElement && "
    "(document.activeElement.getAttribute('data-lumen-slot') || document.activeElement.tagName)"
)


def click_into_sibling_and_type(page: Any, frame: Any, text: str) -> str:
    """Click straight from the stands headline into its body (no blur first), then type."""
    frame.locator(STANDS.format(key="body")).first.click(force=True)
    page.wait_for_timeout(400)
    active = frame.evaluate(ACTIVE_SLOT)
    page.keyboard.type(text)
    page.wait_for_timeout(200)
    return active


def assert_typing_reached_the_body(page: Any, frame: Any, active: str, mark: int) -> None:
    assert active == "body", f"the clicked slot keeps the caret, got {active!r}"
    assert "ZZTYPED" in frame.locator(STANDS.format(key="body")).first.inner_text()
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(1500)
    saved = [
        e
        for m in changed_after(page, mark)
        for e in m["payload"]["site"]["pages"]["/"]["content"]
        if e["props"]["id"] == "stands"
    ]
    assert saved and "ZZTYPED" in saved[-1]["props"]["slots"]["body"], "the typing was saved"


def test_clicking_from_a_cleared_clone_slot_into_its_sibling_keeps_the_caret_there(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """Sync-fix review F7: clearing a never-set slot redraws the clone's markup; that redraw must
    not detach the sibling slot the marketer just clicked into."""
    init = garner_init(mode="edit")
    stands = next(e for e in init["site"]["pages"]["/"]["content"] if e["props"]["id"] == "stands")
    stands["props"]["slots"].pop("headline")
    page, frame = open_site(app, browser_page, editor_origin, init)
    mark = len(received(page))
    frame.locator(STANDS.format(key="headline")).first.click(force=True)
    page.keyboard.press("Meta+a")
    page.keyboard.press("Delete")
    active = click_into_sibling_and_type(page, frame, "ZZTYPED")
    assert_typing_reached_the_body(page, frame, active, mark)


def test_clicking_from_an_edited_clone_slot_into_its_sibling_keeps_the_caret_there(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """Sync-fix review F7 (control): a real change re-renders the clone's markup the same way."""
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    mark = len(received(page))
    frame.locator(STANDS.format(key="headline")).first.click(force=True)
    page.keyboard.press("End")
    page.keyboard.type(" CHANGED")
    active = click_into_sibling_and_type(page, frame, "ZZTYPED")
    assert_typing_reached_the_body(page, frame, active, mark)


def stands_headline_in_changes(page: Any, mark: int) -> list[str]:
    return [
        str(e["props"]["slots"].get("headline", ""))
        for m in changed_after(page, mark)
        for e in m["payload"]["site"]["pages"]["/"]["content"]
        if e["props"]["id"] == "stands"
    ]


def test_typing_in_a_clone_slot_is_sent_after_a_pause_without_leaving_it(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """The founder's live walk (2026-10-14): typing reached the page only when the text box lost
    focus, so a reload while still in the box lost it. A pause in typing now sends it, and the caret
    stays where the marketer is typing while each save lands."""
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    mark = len(received(page))
    frame.locator(STANDS.format(key="headline")).first.click(force=True)
    page.keyboard.press("End")
    page.keyboard.type(" PAUSED")
    page.wait_for_timeout(2500)
    assert frame.evaluate(ACTIVE_SLOT) == "headline", "the caret stays in the box"
    sent = stands_headline_in_changes(page, mark)
    assert sent and sent[-1].endswith("PAUSED"), sent
    page.keyboard.type(" MORE")
    page.wait_for_timeout(2500)
    assert frame.evaluate(ACTIVE_SLOT) == "headline", "the caret stays in the box after a save"
    sent = stands_headline_in_changes(page, mark)
    assert sent[-1].endswith("PAUSED MORE"), sent
    assert frame.locator(STANDS.format(key="headline")).first.inner_text().endswith("PAUSED MORE")


def test_the_frame_tells_the_app_while_typing_is_unsent(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """The app asks before a reload while the frame holds unsent typing; the frame says so."""
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    mark = len(received(page))
    frame.locator(STANDS.format(key="headline")).first.click(force=True)
    page.keyboard.press("End")
    page.keyboard.type(" X")
    page.wait_for_timeout(200)
    pending = [m["payload"]["pending"] for m in received(page)[mark:] if m["type"] == "pending"]
    assert pending == [True], pending
    page.wait_for_timeout(3000)
    pending = [m["payload"]["pending"] for m in received(page)[mark:] if m["type"] == "pending"]
    assert pending == [True, False], pending
    assert stands_headline_in_changes(page, mark), "and the typing was sent"
