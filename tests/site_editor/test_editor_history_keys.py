"""Puck's own undo history never runs inside the site editor frame (review finding S2a-1).

Puck registers undo/redo on `document`, matches physical keys and never checks for editable text, so
before the fix Cmd+Z in a cloned section's text rewound the page to an old snapshot (dropping dock
edits and the agent's replacements) and the frame SAVED it. Undo is the server's stack: in editable
text the browser's own text undo runs; elsewhere the frame asks the app for a server undo.

    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_history_keys.py
"""

from __future__ import annotations

import copy
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."
HERO_SLOT = '[data-puck-component="hero"] [data-lumen-slot="headline"][contenteditable="true"]'
STANDS_SLOT = '[data-puck-component="stands"] [data-lumen-slot="headline"][contenteditable="true"]'


def entry(site: dict[str, Any], component_id: str) -> dict[str, Any]:
    return next(e for e in site["pages"]["/"]["content"] if e["props"]["id"] == component_id)


def proof_heading(site: dict[str, Any]) -> str:
    return entry(site, "proof")["props"]["heading"]


def hero_headline(site: dict[str, Any]) -> str:
    hero = next(e for e in site["pages"]["/"]["content"] if e["props"]["id"] == "hero")
    return str((hero["props"].get("slots") or {}).get("headline", "<seller default>"))


def changed_after(page: Any, start: int) -> list[dict[str, Any]]:
    return [m for m in received(page)[start:] if m["type"] == "changed"]


def type_in_slot(page: Any, frame: Any, selector: str, text: str) -> None:
    frame.locator(selector).first.click(force=True)
    page.keyboard.press("End")
    page.keyboard.type(text)
    frame.evaluate("document.activeElement && document.activeElement.blur()")


def dock_edit(page: Any, app: Any, frame: Any) -> None:
    proof = entry(app.init_payload["site"], "proof")
    page.evaluate(
        "(props) => window.__send("
        "'set_props', { route: '/', componentId: 'proof', props, rev: 2 })",
        {**proof["props"], "heading": "DOCK EDIT"},
    )
    frame.get_by_text("DOCK EDIT").first.wait_for(timeout=10000)


def open_garner(app: Any, browser_page: Any, editor_origin: str) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = garner_init(mode="edit")
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def test_cmd_z_in_a_clone_slot_never_rewinds_a_dock_edit(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_garner(app, browser_page, editor_origin)
    type_in_slot(page, frame, HERO_SLOT, " EDITED")
    page.wait_for_timeout(1200)
    dock_edit(page, app, frame)
    mark = len(received(page))

    frame.locator(STANDS_SLOT).first.click(force=True)
    page.keyboard.press("Meta+z")
    page.wait_for_timeout(1500)
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(1200)

    after = changed_after(page, mark)
    assert all(proof_heading(m["payload"]["site"]) == "DOCK EDIT" for m in after), [
        proof_heading(m["payload"]["site"]) for m in after
    ]
    assert frame.get_by_text("DOCK EDIT").count() > 0, "the canvas still shows the dock edit"


def test_cmd_z_in_a_clone_slot_never_rewinds_an_agent_replacement(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_garner(app, browser_page, editor_origin)
    agent_site = copy.deepcopy(app.init_payload["site"])
    for entry in agent_site["pages"]["/"]["content"]:
        if entry["props"]["id"] == "proof":
            entry["props"]["heading"] = "AGENT REWROTE THIS"
    page.evaluate("(site) => window.__send('replace_site', { site, rev: 9 })", agent_site)
    frame.get_by_text("AGENT REWROTE THIS").first.wait_for(timeout=10000)
    type_in_slot(page, frame, HERO_SLOT, "!")
    page.wait_for_timeout(1200)
    mark = len(received(page))

    frame.locator(HERO_SLOT).first.click(force=True)
    page.keyboard.press("Meta+z")
    page.wait_for_timeout(1500)
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(1200)

    after = changed_after(page, mark)
    assert all(proof_heading(m["payload"]["site"]) == "AGENT REWROTE THIS" for m in after), [
        proof_heading(m["payload"]["site"]) for m in after
    ]
    assert frame.get_by_text("AGENT REWROTE THIS").count() > 0


def test_cmd_z_outside_text_asks_the_app_for_a_server_undo_and_saves_nothing(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    page, frame = open_garner(app, browser_page, editor_origin)
    type_in_slot(page, frame, HERO_SLOT, " EDITED")
    page.wait_for_timeout(1200)
    dock_edit(page, app, frame)
    mark = len(received(page))
    frame.evaluate("document.activeElement && document.activeElement.blur(); document.body.focus()")
    frame.locator("body").press("Meta+z")
    page.wait_for_timeout(1500)
    shortcuts = [m for m in received(page)[mark:] if m["type"] == "shortcut"]
    assert [m["payload"]["action"] for m in shortcuts] == ["undo"], shortcuts
    assert all(
        proof_heading(m["payload"]["site"]) == "DOCK EDIT" for m in changed_after(page, mark)
    )


def test_on_a_dvorak_layout_cmd_semicolon_runs_nothing(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """Puck matches physical key codes (KeyZ); on Dvorak the KeyZ key types ";". Synthetic events
    with the layout's real key/code pair."""
    page, frame = open_garner(app, browser_page, editor_origin)
    type_in_slot(page, frame, HERO_SLOT, " EDITED")
    page.wait_for_timeout(1200)
    dock_edit(page, app, frame)
    mark = len(received(page))
    frame.evaluate(
        """() => {
          const fire = (type, init) => document.body.dispatchEvent(
            new KeyboardEvent(type, { bubbles: true, cancelable: true, ...init }));
          fire('keydown', { key: 'Meta', code: 'MetaLeft', metaKey: true });
          fire('keydown', { key: ';', code: 'KeyZ', metaKey: true });
          fire('keyup', { key: ';', code: 'KeyZ', metaKey: true });
          fire('keyup', { key: 'Meta', code: 'MetaLeft' });
        }"""
    )
    page.wait_for_timeout(1500)
    # Nothing rewinds the dock edit (the frame may re-propose its copy, which carries it) and no
    # history step is asked for; the canvas still shows it.
    assert all(
        proof_heading(m["payload"]["site"]) == "DOCK EDIT" for m in changed_after(page, mark)
    )
    assert [m for m in received(page)[mark:] if m["type"] == "shortcut"] == []
    assert frame.get_by_text("DOCK EDIT").count() > 0


def test_cmd_z_in_a_puck_inline_field_keeps_the_dock_edit(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """Puck's own inline text fields (brand sections) keep the browser's text undo."""
    page, frame = open_garner(app, browser_page, editor_origin)
    type_in_slot(page, frame, HERO_SLOT, " EDITED")
    page.wait_for_timeout(1200)
    dock_edit(page, app, frame)
    mark = len(received(page))
    eyebrow = frame.get_by_text("Aon study, published by Garner").first
    eyebrow.hover(force=True)
    eyebrow.click(force=True)
    page.keyboard.press("Meta+z")
    page.wait_for_timeout(1500)
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(1200)
    assert all(
        proof_heading(m["payload"]["site"]) == "DOCK EDIT" for m in changed_after(page, mark)
    )
    assert frame.get_by_text("DOCK EDIT").count() > 0, "the canvas still shows the dock edit"


DVORAK_COPY = """(code) => {
  const fire = (type, init) => document.body.dispatchEvent(
    new KeyboardEvent(type, { bubbles: true, cancelable: true, ...init }));
  fire('keydown', { key: 'Meta', code: 'MetaLeft', metaKey: true });
  fire('keydown', { key: 'c', code, metaKey: true });
  fire('keyup', { key: 'c', code, metaKey: true });
  fire('keyup', { key: 'Meta', code: 'MetaLeft' });
}"""


def test_on_a_dvorak_layout_cmd_c_never_toggles_puck_preview(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    """Sync-fix review F6: Puck's preview toggle matches the PHYSICAL KeyI, which types "c" on
    Dvorak. Copy must not flip Puck into interactive mode, where a click selects nothing."""
    page, frame = open_garner(app, browser_page, editor_origin)
    frame.evaluate(DVORAK_COPY, "KeyI")
    page.wait_for_timeout(500)
    mark = len(received(page))
    frame.get_by_text(PROOF).first.click(force=True)
    page.wait_for_timeout(1000)
    after = [m["type"] for m in received(page)[mark:]]
    assert "selected" in after, f"a click after Dvorak Cmd+C still selects the section: {after}"
