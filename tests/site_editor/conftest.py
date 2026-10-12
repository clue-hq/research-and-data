"""Browser harness for the site editor (Lane C). Every test here is opt-in.

It starts, on free ports: a stub design API (the token-checked section route, plan K1, and nothing
else), a stub app page that embeds the editor exactly as the app does (sandboxed iframe, nonce in
the URL fragment, the Contract 6 envelope, exact target origins), and the BUILT editor server at
http://<label>.editor.localhost:<port>. Build first:
    cd apps/frontend && npm run build -w @clue/site-editor
Playwright's Chromium must be installed in the repo venv (DEV_STACK.md prerequisites).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "apps/frontend"
EDITOR = FRONTEND / "packages/site-editor"
WORKSPACE_ID = "ws_containment_probe"
LABEL = hashlib.sha256(f"clue-site-editor-label:v1:{WORKSPACE_ID}".encode()).hexdigest()[:32]
TOKEN = "probe-token-0123456789abcdef"
NONCE = "harness-nonce-0123456789"
COOKIE_SECRET = "clue-session-secret-value"

BROWSER_OPT_IN = pytest.mark.skipif(
    os.environ.get("CLUE_SITE_EDITOR_BROWSER") != "1",
    reason=(
        "browser test: set CLUE_SITE_EDITOR_BROWSER=1 after `npm run build -w @clue/site-editor`"
    ),
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler's name
        return


def _serve(
    handler: type[http.server.BaseHTTPRequestHandler], port: int
) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@dataclass
class DesignApiStub:
    port: int
    modules: dict[str, bytes] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)


@dataclass
class AppStub:
    port: int
    init_payload: dict[str, Any] = field(default_factory=dict)
    secret_hits: list[str] = field(default_factory=list)

    @property
    def origin(self) -> str:
        return f"http://localhost:{self.port}"


HOST_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>app stub</title></head><body>
<script>
const EDITOR = __EDITOR__;
const NONCE = __NONCE__;
const INIT = __INIT__;
window.__received = [];
const frame = document.createElement("iframe");
frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
frame.setAttribute("referrerpolicy", "no-referrer");
frame.style.width = "1280px"; frame.style.height = "2400px"; frame.style.border = "0";
frame.src = EDITOR + "/#n=" + NONCE;
document.body.appendChild(frame);
window.__send = (type, payload) => frame.contentWindow.postMessage(
  { channel: "clue-site-editor", v: 1, documentId: "doc_probe", nonce: NONCE, type, payload },
  EDITOR);
window.addEventListener("message", (event) => {
  if (event.origin !== EDITOR || event.source !== frame.contentWindow) return;
  const message = event.data;
  if (!message || message.channel !== "clue-site-editor") return;
  if (message.v !== 1 || message.nonce !== NONCE) return;
  window.__received.push(message);
  if (message.type === "ready") window.__send("init", INIT);
});
</script></body></html>"""

CSP_RECORDER = """
window.__csp = [];
document.addEventListener("securitypolicyviolation", (event) => {
  window.__csp.push({ directive: event.effectiveDirective, blocked: event.blockedURI });
});
"""


@pytest.fixture(scope="session")
def design_api() -> Iterator[DesignApiStub]:
    stub = DesignApiStub(port=free_port())

    class Handler(_Quiet):
        def do_GET(self) -> None:  # noqa: N802 - http.server's method name
            stub.requests.append(self.path)
            path, _, query = self.path.partition("?")
            match = re.fullmatch(r"/site-sections/([0-9a-f]{64})\.(mjs|css)", path)
            if match and query == f"t={TOKEN}":
                digest, extension = match.groups()
                body = stub.modules.get(digest) if extension == "mjs" else b""
                if body is not None:
                    self.send_response(200)
                    self.send_header(
                        "content-type", "text/javascript" if extension == "mjs" else "text/css"
                    )
                    self.send_header("x-clue-workspace-id", WORKSPACE_ID)
                    self.end_headers()
                    self.wfile.write(body)
                    return
            self.send_response(404)
            self.end_headers()

    server = _serve(Handler, stub.port)
    yield stub
    server.shutdown()


@pytest.fixture(scope="session")
def editor_port() -> int:
    return free_port()


@pytest.fixture(scope="session")
def editor_origin(editor_port: int) -> str:
    return f"http://{LABEL}.editor.localhost:{editor_port}"


@pytest.fixture(scope="session")
def app(editor_origin: str) -> Iterator[AppStub]:
    stub = AppStub(port=free_port())

    class Handler(_Quiet):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/secret"):
                stub.secret_hits.append(self.headers.get("cookie") or "")
                self.send_response(200)
                self.send_header("access-control-allow-origin", "*")
                self.end_headers()
                self.wfile.write(b"secret")
                return
            page = (
                HOST_PAGE.replace("__EDITOR__", json.dumps(editor_origin))
                .replace("__NONCE__", json.dumps(NONCE))
                .replace("__INIT__", json.dumps(stub.init_payload))
            )
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("set-cookie", f"clue_session={COOKIE_SECRET}; Path=/; SameSite=Lax")
            self.end_headers()
            self.wfile.write(page.encode())

    server = _serve(Handler, stub.port)
    yield stub
    server.shutdown()


@pytest.fixture(scope="session")
def editor_server(design_api: DesignApiStub, app: AppStub, editor_port: int) -> Iterator[None]:
    server_bundle = EDITOR / "dist" / "server.mjs"
    if not server_bundle.exists():
        pytest.fail(
            "Build the editor first: cd apps/frontend && npm run build -w @clue/site-editor"
        )
    env = {
        **os.environ,
        "CLUE_APP_ORIGIN": app.origin,
        "CLUE_SITE_EDITOR_SUFFIX": f"editor.localhost:{editor_port}",
        "HOST": "127.0.0.1",
        "LUMEN_API_BASE_URL": f"http://127.0.0.1:{design_api.port}",
        "PORT": str(editor_port),
    }
    process = subprocess.Popen(
        ["node", str(server_bundle)],
        cwd=EDITOR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 15
    while True:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{editor_port}/healthz", timeout=1
            ) as response:
                if response.status == 200:
                    break
        except OSError:
            if time.time() > deadline:
                process.kill()
                pytest.fail("the editor server did not start")
            time.sleep(0.2)
    yield
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture()
def browser_page(editor_server: None) -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        context.add_init_script(script=CSP_RECORDER)
        page = context.new_page()
        yield page, context
        context.close()
        browser.close()


def editor_frame(page: Any, editor_origin: str) -> Any:
    deadline = time.time() + 20
    while time.time() < deadline:
        for frame in page.frames:
            if frame.url.startswith(editor_origin):
                return frame
        page.wait_for_timeout(100)
    raise AssertionError("the editor frame never loaded")


def received(page: Any) -> list[dict[str, Any]]:
    return page.evaluate("window.__received")


def garner_init(mode: str = "edit") -> dict[str, Any]:
    output = subprocess.run(
        ["npx", "tsx", "packages/site-editor/test/browser/fixture-init.ts"],
        capture_output=True,
        check=True,
        cwd=FRONTEND,
        text=True,
    ).stdout
    fixture = json.loads(output)
    return {
        "brand": fixture["brand"],
        "device": "Desktop",
        "mode": mode,
        "route": "/",
        "sections": [],
        "site": fixture["site"],
    }
