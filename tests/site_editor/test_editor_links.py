"""Links clicked in the editor's preview (founder, 2026-10-14).

A link to another website opens in a new browser tab: the frame may not open tabs (no popups in its
sandbox) and never navigates itself, so it asks the app (`open_link`), which opens it after a real
click. A link to a page of this site switches page inside the editor, as before.

    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_links.py
"""

from __future__ import annotations

from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."
EXTERNAL = "https://garnerhealth.com/provider-impact-analysis"


def open_preview(app: Any, browser_page: Any, editor_origin: str) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = garner_init(mode="preview")
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def test_an_external_link_in_the_preview_is_handed_to_the_app_and_never_navigates_the_frame(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_preview(app, browser_page, editor_origin)
    frame_url = frame.url
    mark = len(received(page))
    # (The preview renders no section wrappers: the link is found by its address and words.)
    frame.locator(f'a[href="{EXTERNAL}"]', has_text="Request the analysis").first.click(force=True)
    page.wait_for_timeout(800)
    asked = [m["payload"]["href"] for m in received(page)[mark:] if m["type"] == "open_link"]
    assert asked == [EXTERNAL], received(page)[mark:]
    assert frame.url == frame_url, "the frame stayed where it was"
    assert page.url == app.origin + "/"


def test_a_link_to_a_page_of_this_site_still_switches_page(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_preview(app, browser_page, editor_origin)
    mark = len(received(page))
    frame.locator('a[href="/analysis"]').first.click(force=True)
    page.wait_for_timeout(800)
    after = received(page)[mark:]
    assert [m["payload"]["route"] for m in after if m["type"] == "navigated"] == ["/analysis"]
    assert not any(m["type"] == "open_link" for m in after)
