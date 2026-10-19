"""Site element inspector, plan 2 (Task 5): rich text on the canvas.

Our sections' in-place text is Puck's rich text field (TipTap) narrowed to the stored grammar, and a
clone's text slots save rich text: bold typed with the keyboard is kept, a stored styled span and a
link survive typing, and a paste with styles the grammar does not have saves cleanly.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_rich_text.py
"""

from __future__ import annotations

from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."
HEADING = '[data-puck-component="proof"] [data-clue-el="heading"] .ProseMirror'
HERO_SLOT = '[data-puck-component="hero"] [data-lumen-slot="headline"][contenteditable="true"]'


def open_site(
    app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any], shown: str = PROOF
) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(shown).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def saved_value(page: Any, start: int, component: str, prop: str, needle: str) -> str:
    """The prop's value in the first `changed` after `start` that holds `needle`; fails naming what was sent."""
    try:
        page.wait_for_function(
            """([start, component, prop, needle]) => window.__received.slice(start).some((m) => m.type === 'changed'
              && JSON.stringify(m.payload.site.pages['/'].content.find((c) => c.props.id === component).props).includes(needle))""",
            arg=[start, component, prop, needle],
            timeout=10000,
        )
    except Exception as error:  # noqa: BLE001 - re-raised with what was sent
        sent = [
            next(
                c
                for c in m["payload"]["site"]["pages"]["/"]["content"]
                if c["props"]["id"] == component
            )["props"]
            for m in received(page)[start:]
            if m["type"] == "changed"
        ]
        raise AssertionError(
            f"no save of {component}.{prop} holding {needle!r}; sent {sent}"
        ) from error
    for message in received(page)[start:]:
        if message["type"] != "changed":
            continue
        props = next(
            c
            for c in message["payload"]["site"]["pages"]["/"]["content"]
            if c["props"]["id"] == component
        )["props"]
        value = props
        for part in prop.split("."):
            value = value[part]
        if needle in str(value):
            return str(value)
    raise AssertionError("unreachable")


def focus_heading(frame: Any) -> Any:
    editor = frame.locator(HEADING)
    editor.wait_for(timeout=10000)
    # Playwright counts an element inside Puck's component (aria-disabled for dragging) as disabled.
    editor.click(force=True)
    # TipTap takes the keyboard only once it has focus (it mounts a moment after Puck draws it).
    frame.wait_for_function(
        "(sel) => document.activeElement && document.activeElement.matches(sel)",
        arg=HEADING,
        timeout=10000,
    )
    return editor


def select_word(frame: Any, selector: str, word: str) -> None:
    """Highlight the word as a person would leave it, then give the editor a moment to read it."""
    frame.locator(selector).first.evaluate(
        """(root, word) => {
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            const at = node.nodeValue.indexOf(word);
            if (at === -1) continue;
            const range = document.createRange();
            range.setStart(node, at);
            range.setEnd(node, at + word.length);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return;
          }
          throw new Error('word not found: ' + word);
        }""",
        word,
    )
    frame.page.wait_for_timeout(300)


def test_bold_and_italic_typed_in_a_heading_are_saved_as_rich_text(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    focus_heading(frame)
    select_word(frame, HEADING, "lower")
    page.wait_for_timeout(200)
    mark = len(received(page))
    page.keyboard.press("Meta+b")
    value = saved_value(page, mark, "proof", "heading", "<strong>lower</strong>")
    assert value == "7.4% <strong>lower</strong> medical spend in year one. No plan changes.", value
    select_word(frame, HEADING, "medical")
    page.wait_for_timeout(200)
    mark = len(received(page))
    page.keyboard.press("Meta+i")
    saved_value(page, mark, "proof", "heading", "<em>medical</em>")


def test_a_stored_styled_span_and_link_survive_typing(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    init = garner_init(mode="edit")
    proof = next(c for c in init["site"]["pages"]["/"]["content"] if c["props"]["id"] == "proof")
    proof["props"]["heading"] = (
        '7.4% <span data-s="heading~1">lower</span> spend. <a href="/analysis" data-new-tab="">See how</a>'
    )
    proof["props"]["_edits"] = {"heading~1": {"fontWeight": 700}}
    page, frame = open_site(app, browser_page, editor_origin, init, shown="See how")
    frame.locator(f'{HEADING} [data-s="heading~1"]').wait_for(timeout=10000)
    focus_heading(frame)
    select_word(frame, HEADING, "spend.")
    page.keyboard.press("ArrowRight")
    mark = len(received(page))
    page.keyboard.type(" Now")
    value = saved_value(page, mark, "proof", "heading", "Now")
    assert '<span data-s="heading~1">lower</span>' in value, value
    assert '<a href="/analysis" data-new-tab="">See how</a>' in value, value
    weight = frame.locator(f'{HEADING} [data-s="heading~1"]').evaluate(
        "(el) => getComputedStyle(el).fontWeight"
    )
    assert weight == "700", "the span's _edits rule styles it on the canvas"


def test_a_paste_with_styles_the_grammar_has_not_saves_cleanly(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    editor = focus_heading(frame)
    select_word(frame, HEADING, "No plan changes.")
    mark = len(received(page))
    editor.evaluate(
        """(el) => {
          const data = new DataTransfer();
          data.setData('text/html', '<p style="text-align:center">Pasted <span style="color:red">words</span></p><p>two</p>');
          data.setData('text/plain', 'Pasted words two');
          el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
        }"""
    )
    value = saved_value(page, mark, "proof", "heading", "Pasted")
    assert "style" not in value and "<p" not in value, value
    assert value.endswith("Pasted words<br>two"), value


def test_bold_typed_in_a_clone_slot_is_saved_as_rich_text(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    slot = frame.locator(HERO_SLOT).first
    slot.wait_for(timeout=10000)
    slot.click(force=True)
    text = slot.inner_text().split()[0]
    select_word(frame, HERO_SLOT, text)
    mark = len(received(page))
    page.keyboard.press("Meta+b")
    frame.locator("body").click(position={"x": 5, "y": 5})
    saved_value(page, mark, "hero", "slots.headline", f"<strong>{text}</strong>")
