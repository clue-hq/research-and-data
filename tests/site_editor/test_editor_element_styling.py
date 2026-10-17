"""Site element inspector, plan 1: selecting a text element and styling it in the real editor frame.

A click on text inside a section (Puck turns pointer events off there, so the frame finds the text
by its box), in a cloned section and in the header posts `selected` with that element; the app's
`select` can name an element; a `set_props` carrying `_edits` restyles the element on the canvas
without rebuilding a clone's markup. An agent section's element is selectable when the agent named
it, and a hostile name is never selectable.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_element_styling.py
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from .conftest import BROWSER_OPT_IN, TOKEN, editor_frame, garner_init, received
from .test_editor_agent_sections import compile_section, recorded_schema

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."
HEX = r"^#[0-9A-F]{6}$"


def selected_after(page: Any, start: int) -> list[dict[str, Any]]:
    return [m["payload"] for m in received(page)[start:] if m["type"] == "selected"]


def wait_selected(page: Any, start: int, key: str | None, component: str) -> dict[str, Any]:
    """The `selected` for this section and element; on a timeout, says what the frame did post."""
    try:
        page.wait_for_function(
            """([start, key, component]) => window.__received.slice(start).some((m) =>
              m.type === 'selected' && m.payload.componentId === component
              && ((m.payload.element && m.payload.element.key) || null) === key)""",
            arg=[start, key, component],
            timeout=10000,
        )
    except Exception as error:  # noqa: BLE001 - re-raised with what was received
        seen = [
            (m["type"], m["payload"].get("componentId"), (m["payload"].get("element") or {}).get("key"))
            for m in received(page)[start:]
        ]
        raise AssertionError(f"no selected for {component}#{key}; the frame posted {seen}") from error
    return [p for p in selected_after(page, start) if p["componentId"] == component][-1]


def open_site(app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def props_of(init: dict[str, Any], component_id: str) -> dict[str, Any]:
    for item in init["site"]["pages"]["/"]["content"]:
        if item["props"]["id"] == component_id:
            return copy.deepcopy(item["props"])
    raise AssertionError(component_id)


def computed(frame: Any, selector: str, prop: str) -> str:
    return str(frame.locator(selector).first.evaluate(f"(el) => getComputedStyle(el).{prop}"))


def test_a_click_on_text_selects_that_element_with_its_typography(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    mark = len(received(page))
    frame.locator('[data-puck-component="proof"] [data-clue-el="heading"]').click(force=True)
    payload = wait_selected(page, mark, "heading", "proof")
    import re

    assert re.match(HEX, payload["element"]["computed"]["color"]), payload["element"]
    assert payload["element"]["computed"]["fontSize"] > 0
    keys = [element["key"] for element in payload["elements"]]
    assert keys[:3] == ["eyebrow", "heading", "intro"] and "stats.0.value" in keys and "stats.0.label" in keys, keys

    mark = len(received(page))
    frame.locator('[data-puck-component="proof"] [data-clue-el="stats.0.value"]').click(force=True)
    wait_selected(page, mark, "stats.0.value", "proof")
    assert frame.locator('[data-clue-el="stats.0.value"][data-clue-el-selected]').count() == 1


def test_the_apps_select_names_an_element_and_set_props_restyles_it(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = garner_init(mode="edit")
    page, frame = open_site(app, browser_page, editor_origin, init)
    mark = len(received(page))
    page.evaluate("() => window.__send('select', { route: '/', componentId: 'proof', elementKey: 'heading' })")
    wait_selected(page, mark, "heading", "proof")
    heading = '[data-puck-component="proof"] [data-clue-el="heading"]'
    frame.locator(f"{heading}[data-clue-el-selected]").wait_for(timeout=5000)

    props = props_of(init, "proof")
    props["_edits"] = {"heading": {"fontSize": 48, "italic": True, "textAlign": "center"}}
    page.evaluate("(props) => window.__send('set_props', { route: '/', componentId: 'proof', props, rev: 2 })", props)
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).fontSize === '48px'; }""",
        arg=heading,
        timeout=10000,
    )
    assert computed(frame, heading, "fontStyle") == "italic"
    assert computed(frame, heading, "textAlign") == "center"
    assert frame.locator(f"{heading}[data-clue-el-selected]").count() == 1, "the outline survives the redraw"


def test_a_cloned_sections_text_is_selectable_and_its_styling_never_rebuilds_the_clone(
    app: Any, browser_page: Any, editor_origin: str
) -> None:
    init = garner_init(mode="edit")
    page, frame = open_site(app, browser_page, editor_origin, init)
    target = frame.locator('[data-puck-component="hero"] [data-clue-el]').first
    key = target.get_attribute("data-clue-el")
    assert key, "the clone's text carries a structural key"
    markup = frame.locator('[data-puck-component="hero"] [data-lumen-fragment]').first
    markup.evaluate("(el) => { el.__planOneTag = 'kept'; }")
    editable_before = frame.locator('[data-puck-component="hero"] [contenteditable="true"]').count()

    mark = len(received(page))
    target.click(force=True)
    wait_selected(page, mark, key, "hero")

    props = props_of(init, "hero")
    props["_edits"] = {key: {"italic": True}}
    page.evaluate("(props) => window.__send('set_props', { route: '/', componentId: 'hero', props, rev: 2 })", props)
    selector = f'[data-puck-component="hero"] [data-clue-el="{key}"]'
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).fontStyle === 'italic'; }""",
        arg=selector,
        timeout=10000,
    )
    assert markup.evaluate("(el) => el.__planOneTag") == "kept", "the clone's markup is the same node"
    assert frame.locator('[data-puck-component="hero"] [contenteditable="true"]').count() == editable_before


def test_the_headers_account_name_is_selected_through_the_shell(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_site(app, browser_page, editor_origin, garner_init(mode="edit"))
    mark = len(received(page))
    frame.locator('header [data-clue-el="preparedFor"]').click(force=True)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected'
          && m.payload.route === 'shell' && m.payload.componentId === 'header'
          && m.payload.element && m.payload.element.key === 'preparedFor')""",
        arg=mark,
        timeout=10000,
    )


NAMED_PROBE = """import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  headline: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <kit.Eyebrow el="kicker">Named eyebrow</kit.Eyebrow>
      <h2 className="font-title text-title" data-clue-el="headline">{props.headline}</h2>
      <p className="font-body text-body" data-clue-el='"]{}body{color:red'>Hostile name</p>
    </kit.Shell>
  );
}
"""


@pytest.fixture(scope="module")
def named_section() -> dict[str, Any]:
    brand = garner_init()["brand"]
    module = compile_section("NamedProbe", NAMED_PROBE, brand)
    return {"module": module, "schema": recorded_schema(module)}


def test_an_agent_sections_named_text_is_selectable_and_a_hostile_name_is_not(
    app: Any, browser_page: Any, editor_origin: str, design_api: Any, named_section: dict[str, Any]
) -> None:
    code = named_section["module"].encode()
    digest = hashlib.sha256(code).hexdigest()
    design_api.modules[digest] = code
    init = garner_init(mode="edit")
    init["site"]["agent_sections"] = {"NamedProbe": digest}
    init["site"]["pages"]["/"]["content"].append(
        {"type": "NamedProbe", "props": {"id": "named", "surface": "page", "headline": "Agent headline"}}
    )
    init["sections"] = [{"name": "NamedProbe", "digest": digest, "token": TOKEN, "propsSchema": named_section["schema"]}]
    page, frame = open_site(app, browser_page, editor_origin, init)
    frame.get_by_text("Agent headline").first.wait_for(timeout=20000)

    mark = len(received(page))
    frame.get_by_text("Agent headline").first.click(force=True)
    payload = wait_selected(page, mark, "headline", "named")
    assert [element["key"] for element in payload["elements"]] == ["kicker", "headline"]

    mark = len(received(page))
    frame.get_by_text("Hostile name").first.click(force=True)
    wait_selected(page, mark, None, "named")


TWELVE = ["display", "headline", "title", "subtitle", "body", "body.small", "caption", "eyebrow", "label", "cta", "stat", "legal"]


def test_a_hand_set_size_shrinks_on_a_phone_with_the_brand(app: Any, browser_page: Any, editor_origin: str) -> None:
    """Responsive brand type (founder 2026-10-18): in a kit that measured how its type changes with the
    window, a size set in the inspector is exact on desktop and shrinks with the headline's steps on a
    phone. The app's device preview narrows the editor's frame; the test narrows it the same way."""
    init = garner_init(mode="edit")
    roles = {f"type.{role}": [] for role in TWELVE}
    roles["type.headline"] = [{"max_width": 991, "font_size": 62}, {"max_width": 767, "font_size": 44}]
    init["brand"]["kit"]["responsive_type"] = {"version": 1, "measured_from": 1440, "widths": [991, 767], "source": {}, "roles": roles}
    proof = next(item for item in init["site"]["pages"]["/"]["content"] if item["props"]["id"] == "proof")
    proof["props"]["_edits"] = {"heading": {"fontSize": 60}}
    page, frame = open_site(app, browser_page, editor_origin, init)
    heading = '[data-puck-component="proof"] [data-clue-el="heading"]'
    size = lambda: float(computed(frame, heading, "fontSize").removesuffix("px"))  # noqa: E731
    assert frame.evaluate("() => innerWidth") > 991
    assert abs(size() - 60) < 0.5, size()
    page.evaluate("() => { document.querySelector('iframe').style.width = '390px'; }")
    frame.wait_for_function("() => innerWidth <= 767", timeout=10000)
    assert abs(size() - 60 * 44 / 87) < 0.5, size()
