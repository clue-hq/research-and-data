"""Lane C task C3: the built editor renders a site under its own policy and speaks Contract 6."""

from __future__ import annotations

from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."


def test_the_editor_renders_a_site_and_reports_selections(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, _ = browser_page
    app.init_payload = garner_init()
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    assert [message["type"] for message in received(page)][:2] == ["ready", "navigated"]

    page.wait_for_timeout(1500)  # longer than the 600 ms change debounce
    assert "changed" not in [message["type"] for message in received(page)], (
        "opening a site must not save it"
    )
    own_code = [
        v
        for v in frame.evaluate("window.__csp")
        if v["directive"].startswith(("script-src", "style-src", "frame-src", "connect-src"))
    ]
    assert own_code == [], f"the editor's own code must run under its policy: {own_code}"

    # The canvas's own scroll, and the height of the cloned section above `proof`, at the moment of
    # the click, which is when the frame measures the section.
    frame.evaluate(
        "document.addEventListener('click', () => {"
        " window.__scrollAtClick = document.getElementById('root').scrollTop;"
        " window.__standsAtClick = document.querySelector('[data-puck-component=\"stands\"]')"
        ".getBoundingClientRect().height; }, true)"
    )
    # force: with drag off (C13), dnd-kit marks every Puck item aria-disabled, and Playwright treats
    # everything inside an aria-disabled element as not clickable. A real click still selects.
    frame.get_by_text(PROOF).first.click(force=True)
    page.wait_for_function("() => window.__received.some((m) => m.type === 'selected')")
    selected = next(message for message in received(page) if message["type"] == "selected")
    assert selected["payload"]["componentId"] == "proof"
    assert selected["payload"]["componentType"] == "StatsBand"
    assert any(
        f["name"] == "heading" and f["kind"] == "richtext" for f in selected["payload"]["fields"]
    )
    assert any(
        m["type"] == "annotate" and m["payload"]["componentId"] == "proof" for m in received(page)
    )
    # The canvas scrolls inside #root, never the window: document coordinates must add its scroll.
    geometry = [
        m
        for m in received(page)
        if m["type"] == "annotate" and m["payload"]["componentId"] == "proof"
    ][-1]["payload"]["geometry"]
    scroll_top = frame.evaluate("window.__scrollAtClick")
    assert scroll_top > 0, "the proof section is below the fold, so clicking it scrolls the canvas"
    assert abs(geometry["document"]["top"] - (geometry["viewport"]["top"] + scroll_top)) < 1, (
        f"document coordinates must include the canvas's scroll ({scroll_top}): {geometry}"
    )
    # A selection must not rebuild the page around it: the cloned section above keeps its height
    # and the canvas keeps its scroll, so the geometry reported at the click still places the
    # comment box (C7) once the page has settled.
    stands_at_click = frame.evaluate("window.__standsAtClick")
    page.wait_for_timeout(500)
    settled = frame.evaluate(
        "({ scroll: document.getElementById('root').scrollTop,"
        " stands: document.querySelector('[data-puck-component=\"stands\"]')"
        ".getBoundingClientRect().height })"
    )
    assert abs(settled["stands"] - stands_at_click) < 1, (
        f"selecting `proof` reflowed the section above it: {stands_at_click} -> {settled['stands']}"
    )
    assert abs(settled["scroll"] - scroll_top) < 1, (
        f"selecting `proof` moved the canvas's scroll: {scroll_top} -> {settled['scroll']}"
    )

    frame.locator(".brand-root > header").click()
    page.wait_for_function(
        "() => window.__received.some((m) => m.type === 'selected' && m.payload.route === 'shell')"
    )
    shell = [
        m for m in received(page) if m["type"] == "selected" and m["payload"]["route"] == "shell"
    ][-1]
    assert shell["payload"]["componentId"] == "header"
    assert frame.locator(".brand-root > header[data-site-shell-selected]").count() == 1


# The clones' state: their editable text slots, the canvas's scroll, the height of `stands`, and
# whether the first clone still holds the DOM node recorded in `window.__cloneNode`.
CLONE_STATE = """() => ({
  editable: document.querySelectorAll('[data-lumen-fragment] [contenteditable="true"]').length,
  sameNode: document.querySelector('[data-lumen-fragment] > *') === window.__cloneNode,
  scroll: document.getElementById('root').scrollTop,
  stands: document.querySelector('[data-puck-component="stands"]').getBoundingClientRect().height,
})"""


def test_an_edit_elsewhere_never_rebuilds_a_cloned_section(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, _ = browser_page
    app.init_payload = garner_init()
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    # The cloned sections sit above `proof`: with `proof` in view, a clone that shrinks moves the
    # canvas's scroll (scroll anchoring) as well as its own height.
    frame.evaluate(
        "document.querySelector('[data-puck-component=\"proof\"]')"
        ".scrollIntoView({ block: 'center' })"
    )
    page.wait_for_timeout(1000)
    frame.evaluate("window.__cloneNode = document.querySelector('[data-lumen-fragment] > *')")
    before = frame.evaluate(CLONE_STATE)
    assert before["editable"] > 0, "the clones' text slots are editable in place before the edit"
    assert before["scroll"] > 0

    # An inspector edit of `proof` (the app's `set_props`, with the section's full props). The new
    # heading has the same length, so `proof` keeps its own height: the canvas is scrolled to its
    # end, and a shorter `proof` would pull the scroll back by itself.
    proof = next(
        entry
        for entry in app.init_payload["site"]["pages"]["/"]["content"]
        if entry["props"]["id"] == "proof"
    )
    edited = PROOF.replace("changes.", "changes!")
    props = {**proof["props"], "heading": edited}
    page.evaluate(
        "(props) => window.__send("
        "'set_props', { route: '/', componentId: 'proof', props, rev: 2 })",
        props,
    )
    frame.get_by_text(edited).first.wait_for(timeout=10000)
    page.wait_for_timeout(500)

    after = frame.evaluate(CLONE_STATE)
    assert after["editable"] == before["editable"], (
        f"the clones' in-place editable slots went {before['editable']} -> {after['editable']}"
    )
    assert abs(after["stands"] - before["stands"]) < 1, (
        f"an edit of `proof` reflowed the section above it: {before['stands']} -> {after['stands']}"
    )
    assert abs(after["scroll"] - before["scroll"]) < 1, (
        f"an edit of `proof` moved the canvas's scroll: {before['scroll']} -> {after['scroll']}"
    )
    assert after["sameNode"], "an edit of another section rebuilt a cloned section's DOM"


def test_the_app_navigates_the_frame_and_the_frame_never_navigates_the_app(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, _ = browser_page
    app.init_payload = garner_init(mode="preview")
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.evaluate("window.__send('navigate', { route: '/analysis' })")
    page.wait_for_function(
        "() => window.__received.some((m) => m.type === 'navigated' && m.payload.route === '/analysis')"
    )
    frame.get_by_text("Request SCSD's free analysis").first.wait_for(timeout=10000)
    assert page.url == app.origin + "/"
