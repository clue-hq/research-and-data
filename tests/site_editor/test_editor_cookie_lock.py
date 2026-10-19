"""Review K3-7, founder option 1 (2026-10-19): every workspace's editor shares one registrable domain
that is not on the Public Suffix List, so a section's code must not be able to set a cookie there.
The editor page locks cookies before any section loads; this section tries every route we know of
(a computed name, cookieStore, new frames reached three ways, a setter borrowed from a frame) and
the browser ends up holding none of them. The module is handed over as is, past the section check,
the way an injected module would meet the editor. The editor is a cross-site frame, where a browser
takes only a `SameSite=None; Secure` cookie, so every attempt asks for one (Chrome accepts them). The
test browser blocks cross-site cookies by itself, so the test also reads the lock: this page and every
frame the section made have the locked `document.cookie`, and no `cookieStore`. (A real cookie being
refused is proven on a published page, which is first-party: test_site_live_browser.py.)

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_cookie_lock.py
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from .conftest import BROWSER_OPT_IN, TOKEN, editor_frame, garner_init
from .test_editor_agent_sections import recorded_schema

pytestmark = BROWSER_OPT_IN

NAMES = ["direct", "store", "frame_window", "frame_document", "frames", "inner_html", "borrowed"]
TOSSER_JS = (
    'import { jsx } from "react/jsx-runtime";\n'
    'import { z } from "zod";\n'
    "export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n"
    'const d = self["docu" + "ment"];\n'
    'const frame = () => { const f = d.createElement("iframe"); d.body.appendChild(f); return f; };\n'
    "const tries = [\n"
    '  () => { d["coo" + "kie"] = "direct=1; path=/; SameSite=None; Secure"; },\n'
    '  () => { self.cookieStore.set({ name: "store", value: "1", sameSite: "none" }); },\n'
    '  () => { frame().contentWindow.document.cookie = "frame_window=1; path=/; SameSite=None; Secure"; },\n'
    '  () => { frame().contentDocument.cookie = "frame_document=1; path=/; SameSite=None; Secure"; },\n'
    '  () => { frame(); self.frames[self.frames.length - 1].document.cookie = "frames=1; path=/; SameSite=None; Secure"; },\n'
    '  () => { const box = d.createElement("div"); d.body.appendChild(box); box.innerHTML = "<iframe></iframe>";\n'
    '          self.frames[self.frames.length - 1].document.cookie = "inner_html=1; path=/; SameSite=None; Secure"; },\n'
    "  () => { frame(); const other = self.frames[self.frames.length - 1];\n"
    '          Object.getOwnPropertyDescriptor(other.Document.prototype, "cookie").set.call(d, "borrowed=1; path=/; SameSite=None; Secure"); },\n'
    "];\n"
    "for (const attempt of tries) { try { attempt(); } catch (e) {} }\n"
    'export function render() { return jsx("div", { "data-probe": "tosser", children: "tosser rendered" }); }\n'
)


def test_a_section_in_the_editor_cannot_set_a_cookie(
    app: Any, browser_page: Any, design_api: Any, editor_origin: str
) -> None:
    page, context = browser_page
    code = TOSSER_JS.encode()
    digest = hashlib.sha256(code).hexdigest()
    design_api.modules[digest] = code
    base = garner_init(mode="edit")
    site = copy.deepcopy(base["site"])
    site["agent_sections"] = {"Tosser": digest}
    site["pages"]["/"]["content"].append(
        {"type": "Tosser", "props": {"id": "tosser", "surface": "page"}}
    )
    app.init_payload = {
        **base,
        "site": site,
        "sections": [
            {
                "name": "Tosser",
                "digest": digest,
                "token": TOKEN,
                "propsSchema": recorded_schema(TOSSER_JS),
            }
        ],
    }
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.locator('[data-probe="tosser"]').first.wait_for(timeout=20000)
    page.wait_for_timeout(500)
    tossed = [cookie["name"] for cookie in context.cookies() if cookie["name"] in NAMES]
    assert tossed == [], tossed
    state = frame.evaluate(
        """() => {
          const lockedIn = (win) => Object.getOwnPropertyDescriptor(win.Document.prototype, "cookie").configurable === false;
          const frames = Array.from({ length: window.frames.length }, (_, i) => window.frames[i]);
          return { page: lockedIn(window), frames: frames.map(lockedIn), store: typeof window.cookieStore };
        }"""
    )
    assert state["page"] is True, state
    assert len(state["frames"]) >= 5 and all(state["frames"]), state
    assert state["store"] == "undefined", state
