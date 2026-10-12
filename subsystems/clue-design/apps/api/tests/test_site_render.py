"""The hardened-Chromium site renderer (Wave 2 Contract 3) — the master plan's Review focus 8: a section that loops,
prints a huge page, tries the network or reads local files ends as a typed failure, nothing leaves,
and the next render still works."""

from __future__ import annotations

import io
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PIL import Image

from lumen_api import web_export
from lumen_api.hardened_browser import CHROMIUM_SANDBOX_ENV, chromium_sandbox_enabled
from lumen_api.site_render import (
    OUTPUT_TOO_LARGE,
    RENDER_FAILED,
    RENDER_TIMEOUT,
    SECTION_MODULE_MISSING,
    RenderedPage,
    SiteRenderError,
    capture_site_screenshot,
    read_section_schema,
    render_site,
)
from site_kit_support import (
    QUOTE_JS,
    chromium_available,
    conduit_brand,
    conduit_site,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    section_module,
    site_with_section,
)

HEAD = 'import { jsx } from "react/jsx-runtime";\nimport { z } from "zod";\nexport const schema = z.object({ id: z.string(), surface: z.enum(["page"]) }).strict();\n'
HOSTILE_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "surface": {"type": "string", "enum": ["page"]}},
    "required": ["id", "surface"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _browser_and_bundle() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()


def hostile(name: str, body: str):
    module = section_module(name, HEAD + body, props_schema=HOSTILE_SCHEMA)
    return site_with_section(f"doc_{name.lower()}", name, module.digest, {"id": "h", "surface": "page"}), module


class _Recorder(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        _Recorder.hits.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture()
def listener():
    _Recorder.hits = []
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def test_a_site_renders_every_route_with_its_css_and_rebased_links() -> None:
    result = render_site(garner_site("doc_render"), garner_brand(), [], base_path="/acme-site")
    assert [page.route for page in result.pages] == ["/", "/analysis"]
    assert 'class="brand-root"' in result.pages[0].html
    assert 'href="/acme-site/analysis"' in result.pages[0].html
    assert ".bg-surface-brand-subtle" in result.css  # the StatsBand's surface, compiled from the HTML


def test_an_agent_section_renders_from_its_module_with_its_own_css() -> None:
    module = section_module("Quote", QUOTE_JS, css=".quote-extra{color:inherit}")
    site = site_with_section("doc_quote", "Quote", module.digest, {"id": "q", "surface": "brand", "quote": "Fewer surprises."})
    result = render_site(site, garner_brand(), [module], base_path="")
    html = result.pages[0].html
    assert '<div data-agent-section="Quote"><section class="bg-surface-brand text-on-surface-brand">' in html
    assert "Fewer surprises." in html
    assert ".quote-extra{color:inherit}" in result.css


def test_a_missing_or_stale_module_is_a_typed_refusal() -> None:
    module = section_module("Quote", QUOTE_JS)
    site = site_with_section("doc_missing", "Quote", module.digest, {"id": "q", "surface": "page", "quote": "Q"})
    with pytest.raises(SiteRenderError) as missing:
        render_site(site, garner_brand(), [], base_path="")
    assert missing.value.code == SECTION_MODULE_MISSING
    stale = section_module("Quote", QUOTE_JS + "// changed\n")
    with pytest.raises(SiteRenderError) as tampered:
        render_site(site, garner_brand(), [type(stale)(name="Quote", digest=module.digest, module_js=stale.module_js, css="", props_schema={})], base_path="")
    assert tampered.value.code == SECTION_MODULE_MISSING


def test_read_section_schema_reads_the_props_schema_inside_the_page() -> None:
    schema = read_section_schema(QUOTE_JS)
    assert sorted(schema["properties"]) == ["id", "quote", "surface"]
    no_id = 'import { z } from "zod";\nexport const schema = z.object({ surface: z.string() }).strict();\nexport function render() { return null; }\n'
    with pytest.raises(SiteRenderError) as refused:
        read_section_schema(no_id)
    assert refused.value.code == RENDER_FAILED and 'the props need "id"' in refused.value.message


def test_a_section_that_never_finishes_times_out() -> None:
    site, module = hostile("Loop", "export function render(props, kit) { for (;;) {} }\n")
    started = time.monotonic()
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", timeout_s=3)
    assert refused.value.code == RENDER_TIMEOUT
    assert time.monotonic() - started < 15


def test_a_huge_page_is_refused_by_size() -> None:
    body = 'export function render(props, kit) { return jsx("div", { children: Array.from({ length: 20000 }, (_, i) => jsx("p", { children: "x".repeat(100) }, i)) }); }\n'
    site, module = hostile("Huge", body)
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", max_output_bytes=1_000_000)
    assert refused.value.code == OUTPUT_TOO_LARGE


def test_nothing_leaves_the_page_and_the_next_render_still_works(listener: int) -> None:
    body = f"""
try {{ fetch("http://127.0.0.1:{listener}/fetch").catch(() => {{}}); }} catch (e) {{}}
try {{ new Image().src = "http://127.0.0.1:{listener}/img"; }} catch (e) {{}}
try {{ new WebSocket("ws://127.0.0.1:{listener}/ws"); }} catch (e) {{}}
try {{ navigator.sendBeacon("http://127.0.0.1:{listener}/beacon", "x"); }} catch (e) {{}}
let evalBlocked = false;
try {{ (() => 0).constructor("return 1")(); }} catch (e) {{ evalBlocked = true; }}
await new Promise((resolve) => setTimeout(resolve, 400));
export function render(props, kit) {{ return jsx("div", {{ children: "rendered eval-blocked=" + evalBlocked }}); }}
"""
    site, module = hostile("Beacon", body)
    result = render_site(site, garner_brand(), [module], base_path="")
    time.sleep(0.5)
    assert _Recorder.hits == []
    assert "rendered eval-blocked=true" in result.pages[0].html
    assert any("blocked a network request to ws://127.0.0.1" in warning for warning in result.warnings)
    again = render_site(garner_site("doc_after"), garner_brand(), [], base_path="")
    assert len(again.pages) == 2


def test_a_section_cannot_read_local_files(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-1f2e3d")
    body = f"""
let text = "blocked";
try {{ const request = new XMLHttpRequest(); request.open("GET", "file://{secret}", false); request.send(); text = request.responseText || "blocked"; }} catch (e) {{}}
export function render(props, kit) {{ return jsx("div", {{ children: text }}); }}
"""
    site, module = hostile("FileRead", body)
    result = render_site(site, garner_brand(), [module], base_path="")
    assert "SECRET-1f2e3d" not in result.pages[0].html
    assert "blocked" in result.pages[0].html


def test_the_screenshot_shows_the_page_and_fetches_nothing(listener: int) -> None:
    page = RenderedPage(
        route="/",
        html=f'<!doctype html><html><head><title>T</title></head><body><div class="hero"></div><img src="http://127.0.0.1:{listener}/x.png"></body></html>',
    )
    png = capture_site_screenshot(page, ".hero{background:rgb(255,0,0);height:2000px}", width=400, height=300, full_page=False)
    time.sleep(0.3)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    assert image.size == (400, 300) and image.getpixel((200, 150)) == (255, 0, 0)
    assert _Recorder.hits == []


def test_compile_tailwind_css_is_the_shared_compile() -> None:
    css = web_export.compile_tailwind_css(
        '<div class="bg-surface-page"></div>',
        '@import "tailwindcss";\n@theme inline {\n  --color-surface-page: var(--brand-surface-page);\n}\n',
        "node",
        timeout_seconds=60,
    )
    assert ".bg-surface-page" in css


# --- Business-logic scenarios: the renderer driven the way the product drives it -----------------


def _browser_processes() -> list[tuple[int, str]]:
    """Every Chromium process this test process owns, with its command line. Playwright's node
    driver is our child and Chromium its child (the renderer, GPU and utility processes are
    Chromium's), so this walks the whole process tree under ``os.getpid()``, not only direct
    children."""
    out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,command="], capture_output=True, text=True, check=True).stdout
    children: dict[int, list[tuple[int, str]]] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            children.setdefault(int(parts[1]), []).append((int(parts[0]), parts[2]))
    found: list[tuple[int, str]] = []
    stack = [os.getpid()]
    while stack:
        for pid, command in children.get(stack.pop(), []):
            found.append((pid, command))
            stack.append(pid)
    return [(pid, command) for pid, command in found if "chrom" in command.lower()]


class _ProcessSampler:
    """Samples the browser processes in the background while a render runs."""

    def __init__(self) -> None:
        self.samples: list[list[tuple[int, str]]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append(_browser_processes())
            self._stop.wait(0.1)

    def __enter__(self) -> _ProcessSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def test_a_second_real_site_renders_every_route() -> None:
    """Conduit's Atrium site with Conduit's own kit, built as site-kit's kitBrand("conduit")
    builds it: no clones, so its six ClonedSections render the kit's "Choose a cloned section"
    placeholder and each one is named in the warnings — the render still finishes."""
    result = render_site(conduit_site("doc_conduit"), conduit_brand(), [], base_path="/conduit-atrium")
    assert [page.route for page in result.pages] == ["/", "/stories"]
    for page in result.pages:
        assert page.html.startswith('<!doctype html><html lang="en"><head><title>') and page.html.endswith("</body></html>")
        assert 'class="brand-root"' in page.html
        assert 'class="text-ink-muted' in page.html or " text-ink-muted" in page.html  # the clone placeholder
    assert "<title>How hospitality" in result.pages[1].html  # /stories carries its own page title
    assert "bg-surface-brand" in result.pages[0].html  # the CtaBand on the brand surface
    assert ".bg-surface-brand" in result.css and ".text-ink-muted" in result.css
    assert sorted(w for w in result.warnings if "is not one of the brand's clones" in w) == sorted(
        [
            "/: cloned section frag_459fcb8c5790a40a is not one of the brand's clones",
            "/: cloned section frag_f0f8e5711b83f0ff is not one of the brand's clones",
            "/: cloned section frag_515a5d57be6c0aff is not one of the brand's clones",
            "/stories: cloned section frag_99b68501cf3bc5f3 is not one of the brand's clones",
            "/stories: cloned section frag_ef9fbe18007c5195 is not one of the brand's clones",
            "/stories: cloned section frag_9c9f2ec5f397f795 is not one of the brand's clones",
        ]
    )


def test_two_renders_at_once_both_finish_with_the_same_pages() -> None:
    """Two requests rendering the same site at the same moment (two publishes, or a publish and a
    thumbnail): each gets its own browser inside the shared capture slots; neither fails."""
    results: dict[int, object] = {}

    def render(index: int) -> None:
        try:
            results[index] = render_site(garner_site("doc_twice"), garner_brand(), [], base_path="/acme-site")
        except BaseException as error:  # noqa: BLE001 - the assertion below reports it
            results[index] = error

    threads = [threading.Thread(target=render, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert all(not isinstance(result, BaseException) for result in results.values()), results
    first, second = results[0], results[1]
    assert [page.route for page in first.pages] == ["/", "/analysis"]  # type: ignore[attr-defined]
    assert [page.html for page in first.pages] == [page.html for page in second.pages]  # type: ignore[attr-defined]


def _reach_body(listener: int, *, navigates: bool) -> str:
    attempts = [
        'try { window.parent.postMessage({ type: "puck:publish" }, "*"); outcome.push("postMessage=" + (window.parent === window ? "to-itself" : "to-a-parent")); } catch (e) { outcome.push("postMessage=threw-" + e.name); }',
        'try { document.cookie = "a=b"; outcome.push("cookie=" + (document.cookie || "empty")); } catch (e) { outcome.push("cookie=threw-" + e.name); }',
        'try { localStorage.setItem("k", "v"); outcome.push("storage=" + localStorage.getItem("k")); } catch (e) { outcome.push("storage=threw-" + e.name); }',
        f'try {{ await import("http://127.0.0.1:{listener}/x.mjs"); outcome.push("import=loaded"); }} catch (e) {{ outcome.push("import=threw-" + e.name); }}',
    ]
    if navigates:
        attempts.insert(
            1,
            f'try {{ top.location.assign("http://127.0.0.1:{listener}/top"); outcome.push("navigate=called"); }} catch (e) {{ outcome.push("navigate=threw-" + e.name); }}',
        )
    return (
        "const outcome = [];\n"
        + "\n".join(attempts)
        # Long enough for a navigation to land before the render answers, so the outcome is decided.
        + "\nawait new Promise((resolve) => setTimeout(resolve, 400));\n"
        + 'export function render(props, kit) { return jsx("div", { children: "reach " + outcome.join(" ") }); }\n'
    )


@pytest.mark.parametrize("navigates", [False, True], ids=["in-page", "with-top-navigation"])
def test_a_section_reaching_for_the_parent_the_top_storage_and_remote_code_gets_nothing(listener: int, navigates: bool) -> None:
    """What each reach does inside the hardened render page (the page is a top-level
    ``set_content`` document: no parent, an opaque origin, and the render CSP):

    - ``window.parent.postMessage`` — the render page IS the top window, so ``parent`` is itself:
      the message goes to the page's own window, where nothing listens. No editor ever receives it.
    - ``top.location.assign(<listener>)`` — the navigation request reaches the context's route and
      is refused there (and the proxy/resolver layers would refuse it again); the page must stay put.
    - ``document.cookie`` — the opaque-origin document has no cookie jar: setting it throws
      ``SecurityError``.
    - ``localStorage`` — likewise refused for an opaque origin: ``SecurityError``.
    - dynamic ``import(<listener>)`` — the CSP allows only inline and ``data:`` scripts, so the
      import is refused before any request: ``TypeError`` ("Failed to fetch dynamically imported
      module")."""
    module = section_module("Reach", HEAD + _reach_body(listener, navigates=navigates), props_schema=HOSTILE_SCHEMA)
    site = site_with_section("doc_reach", "Reach", module.digest, {"id": "h", "surface": "page"})
    result = render_site(site, garner_brand(), [module], base_path="", timeout_s=8)
    time.sleep(0.5)
    assert _Recorder.hits == []
    expected = ["postMessage=to-itself", "cookie=threw-SecurityError", "storage=threw-SecurityError", "import=threw-TypeError"]
    if navigates:
        expected.insert(1, "navigate=called")
    # The page did not navigate away: its HTML is the section's own output, every attempt reported.
    assert '<div data-agent-section="Reach"><div>reach ' + " ".join(expected) + "</div></div>" in result.pages[0].html


def test_a_timed_out_render_leaves_no_browser_behind() -> None:
    before = _browser_processes()
    site, module = hostile("Spin", "export function render(props, kit) { for (;;) {} }\n")
    with _ProcessSampler() as sampler, pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", timeout_s=3)
    assert refused.value.code == RENDER_TIMEOUT
    # The sampler saw the render's own browser (so the count below is not vacuous)...
    assert max(len(sample) for sample in sampler.samples) > len(before)
    # ...and, a moment after the refusal, every one of its processes is gone.
    deadline = time.monotonic() + 5
    while len(_browser_processes()) > len(before) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert len(_browser_processes()) == len(before)


def test_the_sandbox_switch_reaches_the_browser_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("0", "1"):
        monkeypatch.setenv(CHROMIUM_SANDBOX_ENV, value)
        with _ProcessSampler() as sampler:
            result = render_site(garner_site("doc_sandbox"), garner_brand(), [], base_path="")
        assert len(result.pages) == 2
        # The browser process itself is the one Playwright launched over its pipe (its renderer, GPU
        # and utility children carry --type=; an exiting process shows as a bare "(chrome-...)").
        launched = [command for sample in sampler.samples for _pid, command in sample if "--remote-debugging-pipe" in command]
        assert launched, "the sampler never saw the browser process"
        assert all(("--no-sandbox" in command) == (value == "0") for command in launched), (value, launched[:1])


def test_chromium_sandbox_enabled_reads_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CHROMIUM_SANDBOX_ENV, raising=False)
    assert chromium_sandbox_enabled() is True
    for value, enabled in [("1", True), ("0", False), ("false", False), ("no", False), ("off", False), (" OFF ", False)]:
        monkeypatch.setenv(CHROMIUM_SANDBOX_ENV, value)
        assert chromium_sandbox_enabled() is enabled, value
