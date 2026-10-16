"""After an outside copy (an undo, a restore, an agent turn), the selection stays on the SAME
section, never on whatever now sits at its old position (review finding S2a-4: Puck keeps its
selection by position, so the dock moved to another section and the next dock edit landed there).

    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_selection_follows_section.py
"""

from __future__ import annotations

import copy
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."


def selection_messages(page: Any, start: int) -> list[tuple[str, str | None]]:
    return [
        (m["type"], m["payload"].get("componentId"))
        for m in received(page)[start:]
        if m["type"] in ("selected", "deselected")
    ]


def test_a_replaced_site_keeps_the_selection_on_the_same_section(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, _ = browser_page
    app.init_payload = garner_init(mode="edit")
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(800)
    frame.get_by_text(PROOF).first.click(force=True)
    page.wait_for_function(
        "() => window.__received.some((m) => m.type === 'selected' && m.payload.componentId === 'proof')"
    )
    mark = len(received(page))

    # A new copy in which the first section is gone: `proof` moves up one position.
    site = copy.deepcopy(app.init_payload["site"])
    content = site["pages"]["/"]["content"]
    site["pages"]["/"]["content"] = [e for e in content if e["props"]["id"] != "hero"]
    page.evaluate("(site) => window.__send('replace_site', { site, rev: 9 })", site)
    page.wait_for_timeout(1500)

    after = selection_messages(page, mark)
    assert after, "the selected section is re-described after the outside copy"
    assert all(message == ("selected", "proof") for message in after), after


def test_a_replaced_site_without_the_selected_section_clears_the_selection(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, _ = browser_page
    app.init_payload = garner_init(mode="edit")
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(800)
    frame.get_by_text(PROOF).first.click(force=True)
    page.wait_for_function(
        "() => window.__received.some((m) => m.type === 'selected' && m.payload.componentId === 'proof')"
    )
    mark = len(received(page))
    site = copy.deepcopy(app.init_payload["site"])
    content = site["pages"]["/"]["content"]
    site["pages"]["/"]["content"] = [e for e in content if e["props"]["id"] != "proof"]
    page.evaluate("(site) => window.__send('replace_site', { site, rev: 9 })", site)
    page.wait_for_timeout(1500)
    assert selection_messages(page, mark) == [("deselected", None)]
