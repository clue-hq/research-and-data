"""A live site package, served the way the page origin serves it, comes alive in a real browser:
no console error, no policy violation, and an agent section with state responds to a click
(publishing live sites, phase 1, Task 8).

The browser is an ordinary Playwright Chromium (not the hardened render page) talking to a local
server that serves each page under the live policy header (``delivery_csp(delivery="site_live")``)
and each ``/p-assets/<digest>.js`` file of the package, so a policy violation, a failed module load
or a hydration error shows up as a console error."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clue_design.publishes import delivery_csp
from lumen_api.design_store import DesignBlobStore
from site_kit_support import build_live_package_with_section, chromium_available, ensure_site_kit_dist

COUNTER_JS = (
    'import { jsx, jsxs } from "react/jsx-runtime";\n'
    'import { useState } from "react";\n'
    'import { z } from "zod";\n'
    "export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n"
    "function Counter() { const [n, setN] = useState(0);\n"
    '  return jsxs("button", { id: "counter", onClick: () => setN(n + 1), children: ["clicked ", n] }); }\n'
    "export function render() { return jsx(Counter, {}); }\n"
)


@pytest.fixture(autouse=True)
def _browser_and_bundle() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()


@pytest.fixture()
def blobs(design_storage, workspace_id: str) -> DesignBlobStore:
    return DesignBlobStore(design_storage, workspace_id)


def _serve(package) -> tuple[str, ThreadingHTTPServer]:
    pages = {f"/acme{'' if p.route == '/' else p.route}": p.html.encode() for p in package.pages}
    files = {f"/p-assets/{d}.js": data for d, data in package.assets.items()}
    hashes = package.manifest["live"]["script_hashes"]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in pages:
                body, kind = pages[self.path], "text/html; charset=utf-8"
                extra = {"Content-Security-Policy": delivery_csp(delivery="site_live", script_hashes=hashes)}
            elif self.path in files:
                body, kind, extra = files[self.path], "text/javascript; charset=utf-8", {}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def test_a_live_site_comes_alive_and_an_agent_section_with_state_answers_a_click(blobs: DesignBlobStore) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    package = build_live_package_with_section(blobs, "Counter", COUNTER_JS)
    origin, server = _serve(package)
    try:
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(f"{m.text} [{m.location.get('url', '')}]") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(origin + "/acme", wait_until="load")
            page.wait_for_function("() => window.__clueHydrated === true", timeout=10_000)
            assert page.locator("#counter").inner_text() == "clicked 0"
            page.locator("#counter").click()
            assert page.locator("#counter").inner_text() == "clicked 1"
            # The page data's brand still names its images and fonts by `/asset-store/<sha>`, and this
            # server serves only pages and `/p-assets` (the page origin serves the store), so those
            # loads 404. Chromium reports a failed load as a console error, but it is a network
            # failure, not a script, policy or hydration error: only exactly those are dropped.
            errors = [e for e in errors if not (e.startswith("Failed to load resource") and "/asset-store/" in e)]
            assert errors == [], errors
            browser.close()
    finally:
        server.shutdown()
