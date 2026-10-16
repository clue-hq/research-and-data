"""Review focus 6 (master plan): agent-written section code loaded in the editor is contained.

The D2 spike's probes — a tracking pixel, a fetch reached through the Function constructor, top and
parent navigation, a cookie read, a beacon, an injected inline handler, and a credentialed read of
the app's own API — are compiled like real agent sections, served through the editor's token-checked
/sections route, and rendered by the built editor on a *.editor.localhost host inside the app's
sandboxed frame. Each must RUN (its headline is on screen) and none may escape.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .conftest import (
    BROWSER_OPT_IN,
    COOKIE_SECRET,
    FRONTEND,
    TOKEN,
    editor_frame,
    garner_init,
    received,
)

pytestmark = BROWSER_OPT_IN


def compile_probes(out: Path) -> dict[str, dict[str, str]]:
    result = subprocess.run(
        ["npx", "tsx", "packages/site-editor/test/containment/compile-probes.ts", str(out)],
        capture_output=True,
        check=True,
        cwd=FRONTEND,
        text=True,
    )
    return json.loads(result.stdout)


def test_hostile_agent_sections_run_and_are_contained(
    app: Any, browser_page: Any, design_api: Any, editor_origin: str, tmp_path: Path
) -> None:
    page, context = browser_page
    probes = compile_probes(tmp_path)
    for probe in probes.values():
        design_api.modules[probe["digest"]] = Path(probe["file"]).read_bytes()
    secret_url = f"{app.origin}/api/secret"
    base = garner_init(mode="preview")
    content = [
        {
            "type": name,
            "props": {
                "id": f"probe-{name.lower()}",
                "surface": "page",
                "headline": f"probe {name}",
                "probe": secret_url,
            },
        }
        for name in probes
    ]
    site = {
        **base["site"],
        "agent_sections": {name: probe["digest"] for name, probe in probes.items()},
        "pages": {"/": {"root": {"props": {"title": "Probes"}}, "content": content}},
    }
    schema = {
        "type": "object",
        "properties": {"headline": {"type": "string"}, "probe": {"type": "string"}},
    }
    sections = [
        {"name": name, "digest": probe["digest"], "token": TOKEN, "propsSchema": schema}
        for name, probe in probes.items()
    ]
    app.init_payload = {**base, "sections": sections, "site": site}
    escaped: list[str] = []

    def record_escape(route: Any) -> None:
        escaped.append(route.request.url)
        route.abort()

    context.route(re.compile(r"collector\.example"), record_escape)
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)

    # Every probe that does not crash itself rendered: the containment below is not vacuous.
    for name in ("ApiRead", "CookieRead", "InjectedScript", "NetworkCall", "TrackingPixel"):
        frame.get_by_text(f"probe {name}").first.wait_for(timeout=20000)
    page.wait_for_timeout(2000)
    assert all(
        f"/site-sections/{probe['digest']}.mjs?t={TOKEN}" in design_api.requests
        for probe in probes.values()
    )

    # 1. The app's cookie is not readable in the editor (another host).
    assert COOKIE_SECRET not in frame.evaluate("document.cookie")
    assert COOKIE_SECRET not in (
        frame.locator("[data-session]").first.get_attribute("data-session") or ""
    )
    # 2. No credentialed call reached the app's API (ApiRead; ConstructorEscape aims at it too).
    assert app.secret_hits == []
    # 3. Nothing reached any other host: pixel, beacon, injected onerror handler.
    assert escaped == []
    # 4. No top or parent navigation; the app ignored the probes' own messages.
    assert page.url == app.origin + "/"
    assert not any(message.get("type") == "puck:publish" for message in received(page))
    # 5. The policy reported what it blocked.
    violations = frame.evaluate("window.__csp")
    directives = {violation["directive"] for violation in violations}
    assert "img-src" in directives, violations
    assert "connect-src" in directives, violations
    assert any(
        v["directive"].startswith("script-src") and v["blocked"] == "eval" for v in violations
    ), violations
    # The two probes that throw (Function refused, top navigation refused) took nothing else down.
    assert frame.locator("[data-agent-section-failed]").count() >= 1
