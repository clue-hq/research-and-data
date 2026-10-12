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

    # force: with drag off (C13), dnd-kit marks every Puck item aria-disabled, and Playwright treats
    # everything inside an aria-disabled element as not clickable. A real click still selects.
    frame.get_by_text(PROOF).first.click(force=True)
    page.wait_for_function("window.__received.some((m) => m.type === 'selected')")
    selected = next(message for message in received(page) if message["type"] == "selected")
    assert selected["payload"]["componentId"] == "proof"
    assert selected["payload"]["componentType"] == "StatsBand"
    assert any(
        f["name"] == "heading" and f["kind"] == "text" for f in selected["payload"]["fields"]
    )
    assert any(
        m["type"] == "annotate" and m["payload"]["componentId"] == "proof" for m in received(page)
    )

    frame.locator(".brand-root > header").click()
    page.wait_for_function(
        "window.__received.some((m) => m.type === 'selected' && m.payload.route === 'shell')"
    )
    shell = [
        m for m in received(page) if m["type"] == "selected" and m["payload"]["route"] == "shell"
    ][-1]
    assert shell["payload"]["componentId"] == "header"
    assert frame.locator(".brand-root > header[data-site-shell-selected]").count() == 1


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
        "window.__received.some((m) => m.type === 'navigated' && m.payload.route === '/analysis')"
    )
    frame.get_by_text("Request SCSD's free analysis").first.wait_for(timeout=10000)
    assert page.url == app.origin + "/"
