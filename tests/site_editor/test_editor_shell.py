"""Site element inspector, plan 6: the header and footer as sections in the real editor frame.

A template header's account line is typed in place and saved into its slot; the header kept at the top
stays there while the canvas scrolls; the header over the first section has the first section start
under it; a menu label typed in place is saved by page, and a hidden menu item is not drawn.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_shell.py
"""

from __future__ import annotations

import copy
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
TEMPLATE_ID = "frag_00000000000000d1"
# A header template as the extraction derives one (lumen_api/fragments/site_templates.py): the seller's
# logo, the account parts after it, the menu reduced to one marked pattern, one button.
TEMPLATE = {
    "id": TEMPLATE_ID,
    "role": "site_header",
    "label": "Header template — garnerhealth.com",
    "page_url": "https://garnerhealth.com/",
    "section_index": None,
    "wrapper_class": "lumen-frag-tmpl",
    "html": (
        '<ls-h style="display:contents!important" data-lumen-slot="visible"><ls-b style="display:contents!important">'
        '<header class="th"><div class="tr"><a class="logo" href="/"><svg viewBox="0 0 10 10" width="40" height="20"><rect width="10" height="10"></rect></svg></a>'
        '<span class="clue-account" data-lumen-slot="account_shown"><span class="clue-account-rule" aria-hidden="true"></span></span>'
        '<span class="nl clue-account-line" data-lumen-slot="account_line">Prepared for you</span>'
        '<nav class="menu" data-clue-menu=""><a class="nl" data-clue-menu-item="" href="/x"><span data-clue-menu-label="">X</span></a></nav>'
        '<a class="btn" href="/demo" data-lumen-slot="cta_href"><span data-lumen-slot="cta_label">Book a demo</span></a>'
        "</div></header></ls-b></ls-h>"
    ),
    "css": ".th{background:#ffffff}.tr{display:flex;align-items:center;gap:24px;padding:16px 32px}.menu{display:flex;gap:16px}",
    "slots": {
        "visible": {"kind": "visibility", "fallback": True},
        "account_shown": {"kind": "visibility", "fallback": True},
        "account_line": {"kind": "text", "fallback": "Prepared for you"},
        "cta_href": {"kind": "href", "fallback": "/demo"},
        "cta_label": {"kind": "text", "fallback": "Book a demo"},
    },
}
HEADER = '[data-puck-component="header"]'


def shell_init() -> dict[str, Any]:
    init = garner_init(mode="edit")
    init["brand"]["clones"][TEMPLATE_ID] = TEMPLATE
    init["site"]["shell"]["header"] = {
        "type": "ClonedSection",
        "props": {"id": "header", "fragmentId": TEMPLATE_ID, "slots": {"account_line": "Built for Carmel"}, "replacements": [], "links": []},
    }
    return init


def open_shell(app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.locator(f"{HEADER} .clue-account-line").first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def changed_headers(page: Any, start: int) -> list[dict[str, Any]]:
    return [m["payload"]["site"]["shell"]["header"] for m in received(page)[start:] if m["type"] == "changed"]


def with_header_edits(init: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    props = copy.deepcopy(init["site"]["shell"]["header"]["props"])
    props["_edits"] = edits
    return props


def top_of(frame: Any, selector: str) -> float:
    return frame.evaluate("(sel) => document.querySelector(sel).getBoundingClientRect().top", selector)


def test_header_template_words_edit_in_place(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_shell(app, browser_page, editor_origin, shell_init())
    mark = len(received(page))
    frame.locator(f"{HEADER} .clue-account-line").first.click(force=True)
    page.keyboard.press("End")
    page.keyboard.type(" Clay")
    frame.locator('[data-puck-component="proof"]').first.click(force=True)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'changed'
          && /Clay/.test(String(m.payload.site.shell.header.props.slots.account_line || ''))
          && /Carmel/.test(String(m.payload.site.shell.header.props.slots.account_line || '')))""",
        arg=mark,
        timeout=10000,
    )
    header = changed_headers(page, mark)[-1]
    assert header["type"] == "ClonedSection" and header["props"]["id"] == "header"


def test_sticky_header_stays_while_canvas_scrolls(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = shell_init()
    page, frame = open_shell(app, browser_page, editor_origin, init)
    props = with_header_edits(init, {"root": {"sticky": True}})
    page.evaluate("(props) => window.__send('set_props', { route: 'shell', componentId: 'header', props, rev: 2 })", props)
    frame.wait_for_function("(sel) => !!document.querySelector(sel + ' > .clue-section[data-clue-sticky]')", arg=HEADER, timeout=10000)
    frame.evaluate("() => { document.getElementById('root').scrollTop = 800; }")
    page.wait_for_timeout(300)
    assert frame.evaluate("() => document.getElementById('root').scrollTop") > 0, "the canvas scrolled"
    assert abs(top_of(frame, HEADER) - top_of(frame, "#root")) < 2, "the header stays at the top of the canvas"


def test_overlay_starts_first_section_under_header(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = shell_init()
    page, frame = open_shell(app, browser_page, editor_origin, init)
    first = init["site"]["pages"]["/"]["content"][0]["props"]["id"]
    before = top_of(frame, f'[data-puck-component="{first}"]')
    props = with_header_edits(init, {"root": {"overlay": True}})
    page.evaluate("(props) => window.__send('set_props', { route: 'shell', componentId: 'header', props, rev: 2 })", props)
    frame.wait_for_function("(sel) => !!document.querySelector(sel + ' > .clue-section[data-clue-overlay]')", arg=HEADER, timeout=10000)
    page.wait_for_timeout(300)
    assert top_of(frame, f'[data-puck-component="{first}"]') < before, "the first section moved up under the header"
    assert abs(top_of(frame, f'[data-puck-component="{first}"]') - top_of(frame, f"{HEADER} header")) < 2


def test_menu_label_and_hide(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = shell_init()
    page, frame = open_shell(app, browser_page, editor_origin, init)
    label = f'{HEADER} [data-clue-el="menu.analysis"] [data-clue-menu-label]'
    assert frame.locator(label).first.inner_text() == "Analysis"
    mark = len(received(page))
    frame.locator(label).first.click(force=True)
    page.keyboard.press("Meta+a")
    page.keyboard.type("The analysis")
    page.keyboard.press("Enter")
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'changed'
          && (m.payload.site.shell.header.props.menuLabels || {}).analysis === 'The analysis')""",
        arg=mark,
        timeout=10000,
    )
    props = with_header_edits(init, {"menu._home": {"hidden": True}})
    page.evaluate("(props) => window.__send('set_props', { route: 'shell', componentId: 'header', props, rev: 3 })", props)
    frame.wait_for_function(
        """(sel) => { const el = document.querySelector(sel); return el && getComputedStyle(el).display === 'none'; }""",
        arg=f'{HEADER} [data-clue-el="menu._home"]',
        timeout=10000,
    )


# Final review I5: a template header's extra menu link is edited where it lives, in menuExtra.
def test_a_template_menu_extra_link_is_written_in_menu_extra(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = shell_init()
    init["site"]["shell"]["header"]["props"]["menuExtra"] = [{"label": "Pricing", "href": "https://garnerhealth.com/pricing"}]
    page, frame = open_shell(app, browser_page, editor_origin, init)
    mark = len(received(page))
    frame.locator(f'{HEADER} [data-clue-el="menu._0"]').first.click(force=True)
    page.wait_for_function(
        """(start) => window.__received.slice(start).some((m) => m.type === 'selected' && m.payload.element
          && String(m.payload.element.key).startsWith('menu._0'))""",
        arg=mark,
        timeout=10000,
    )
    element = [m for m in received(page)[mark:] if m["type"] == "selected"][-1]["payload"]["element"]
    assert element["link"]["source"] == {"kind": "prop", "href": "menuExtra.0.href", "newTab": "menuExtra.0.newTab"}, element["link"]
