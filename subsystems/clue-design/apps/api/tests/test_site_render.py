"""The hardened-Chromium site renderer (Wave 2 Contract 3) — the master plan's Review focus 8: a section that loops,
prints a huge page, tries the network or reads local files ends as a typed failure, nothing leaves,
and the next render still works."""

from __future__ import annotations

import io
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PIL import Image

from lumen_api import web_export
from lumen_api.document_thumbnails import _CAPTURE_SLOTS
from lumen_api.hardened_browser import CHROMIUM_SANDBOX_ENV, chromium_sandbox_enabled
from lumen_api import site_render
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
    site_with_agent_section,
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
    - ``top.location.assign(<listener>)`` — the navigation request reaches the context's route,
      which answers it LOCALLY with an empty 204 (nothing is fetched; the proxy/resolver layers
      would refuse it again), so the page stays where it is and the URL surfaces as a warning.
      (An aborted navigation would commit Chromium's error page in place of the render.)
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
        assert f"blocked a network request to http://127.0.0.1:{listener}/top" in result.warnings
    # The page did not navigate away: its HTML is the section's own output, every attempt reported.
    assert '<div data-agent-section="Reach"><div>reach ' + " ".join(expected) + "</div></div>" in result.pages[0].html


def test_a_section_that_reloads_the_page_fails_fast_and_typed() -> None:
    """A reload never reaches the network (the render page is an ``about:blank`` document), so no
    local 204 can stop it: the page is replaced by a blank one. The render notices the main frame
    navigating and refuses at once, naming it — never a stall until ``timeout_s``."""
    # The wait keeps the render from answering before the reload lands (the reload ends the module).
    body = 'location.reload();\nawait new Promise((resolve) => setTimeout(resolve, 400));\nexport function render(props, kit) { return jsx("div", { children: "reloaded" }); }\n'
    site, module = hostile("Reload", body)
    started = time.monotonic()
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", timeout_s=15)
    elapsed = time.monotonic() - started
    assert refused.value.code == RENDER_FAILED
    assert "navigat" in refused.value.message and "about:blank" in refused.value.message
    assert elapsed < 5, elapsed


def url_change_warning(change: str) -> str:
    return f"a section changed the page URL in place ({change}); this has no effect on the published page, which runs no script"


@pytest.mark.parametrize(
    ("call", "change"),
    [
        ('location.hash = "#pricing";', "hash #pricing"),
        ('history.pushState({}, "", "#tab-2");', "pushState #tab-2"),
        ('history.pushState({}, "", "/pricing");', "pushState /pricing"),
        ('history.replaceState(null, "", "/x?y=1");', "replaceState /x?y=1"),
        ('history.pushState({}, "", "http://127.0.0.1:LISTENER/elsewhere");', "pushState http://127.0.0.1:LISTENER/elsewhere"),
    ],
    ids=["hash", "push-fragment", "push-path", "replace-path-and-query", "push-absolute-url"],
)
def test_a_section_that_changes_the_url_in_place_renders_with_a_warning(listener: int, call: str, change: str) -> None:
    """Founder ruling 2026-10-13: an in-place URL change loads nothing and does nothing on the
    published page (which runs no script), so it is a warning, not a failed render. The wait lets a
    navigation land before the render answers, as in the reload test, so a change that DID move the
    page could not slip through."""
    call, change = call.replace("LISTENER", str(listener)), change.replace("LISTENER", str(listener))
    body = call + '\nawait new Promise((resolve) => setTimeout(resolve, 300));\nexport function render(props, kit) { return jsx("div", { children: "in place" }); }\n'
    site, module = hostile("InPlace", body)
    result = render_site(site, garner_brand(), [module], base_path="", timeout_s=8)
    time.sleep(0.3)
    assert '<div data-agent-section="InPlace"><div>in place</div></div>' in result.pages[0].html
    assert [warning for warning in result.warnings if "changed the page URL" in warning] == [url_change_warning(change)]
    assert _Recorder.hits == []


def test_a_section_that_changes_the_hash_and_then_reloads_still_fails_fast() -> None:
    """The hash change is accepted (the wait lets the render look at it first); the reload that
    follows replaces the document, and that is still refused at once and by name."""
    body = (
        'location.hash = "#pricing";\n'
        "await new Promise((resolve) => setTimeout(resolve, 400));\n"
        "location.reload();\n"
        "await new Promise((resolve) => setTimeout(resolve, 400));\n"
        'export function render(props, kit) { return jsx("div", { children: "reloaded" }); }\n'
    )
    site, module = hostile("HashReload", body)
    started = time.monotonic()
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", timeout_s=15)
    elapsed = time.monotonic() - started
    assert refused.value.code == RENDER_FAILED
    assert "a section navigated the render page away (to about:blank" in refused.value.message
    assert "a section may not navigate or reload the page" in refused.value.message
    assert elapsed < 5, elapsed


def test_a_section_that_changes_the_hash_and_then_spins_still_times_out() -> None:
    """Telling a hash change from a real navigation means asking the page — and this page is busy
    forever. The question is bounded by the render's time limit, so the render still ends there."""
    site, module = hostile("HashSpin", 'location.hash = "#pricing";\nfor (;;) {}\nexport function render(props, kit) { return null; }\n')
    started = time.monotonic()
    with pytest.raises(SiteRenderError) as refused:
        render_site(site, garner_brand(), [module], base_path="", timeout_s=3)
    assert refused.value.code == RENDER_TIMEOUT
    assert time.monotonic() - started < 15


def test_read_section_schema_reads_a_module_that_changes_the_url_at_its_top_level() -> None:
    schema = read_section_schema(QUOTE_JS + 'history.pushState({}, "", "/p");\n')
    assert sorted(schema["properties"]) == ["id", "quote", "surface"]


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


# --- Every step of a render is bounded by its time limit ------------------------------------------
# A section may start a busy loop at any moment: before its render answers, a few milliseconds
# after, or while the renderer is reading the answer. Each test runs the render on its own thread
# and waits for it with a join timeout, so a render that hangs fails the test instead of hanging
# the suite.

SPIN_TIMEOUT_S = 4
#: Long enough to tell a hang from a slow render; a hang fails the test at this point.
HANG_AFTER_S = SPIN_TIMEOUT_S + 15
#: A microtask queued in render() runs once the render has answered and before anything else can
#: run in the page — before any read can arrive. It swaps the answer's pages for a getter that
#: never returns, so the busy loop starts inside the renderer's own read of the result. This is
#: the deterministic form of "a section that spins a few milliseconds after its render".
SPIN_ON_READ = 'queueMicrotask(() => { Object.defineProperty(window.__clueRender.result, "pages", { get() { for (;;) {} } }); });'


class _Bounded:
    """Runs ``call`` on its own thread; ``outcome(within)`` waits at most ``within`` seconds and
    returns what the call returned or raised, and how long it took."""

    def __init__(self, call: Callable[[], object]) -> None:
        self._call = call
        self._outcome: dict[str, object] = {}
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        started = time.monotonic()
        try:
            self._outcome["value"] = self._call()
        except BaseException as error:  # noqa: BLE001 - the test asserts on it
            self._outcome["value"] = error
        self._outcome["elapsed"] = time.monotonic() - started

    def outcome(self, within: float = HANG_AFTER_S) -> tuple[object, float]:
        self._thread.join(within)
        assert not self._thread.is_alive(), f"the render was still running after {within:g}s: it hung"
        return self._outcome["value"], float(self._outcome["elapsed"])  # type: ignore[arg-type]


def _assert_timed_out(value: object, elapsed: float, timeout_s: float = SPIN_TIMEOUT_S) -> None:
    assert isinstance(value, SiteRenderError), value
    assert (value.code, value.message) == (RENDER_TIMEOUT, f"the site did not render within {timeout_s:g}s")
    assert elapsed < timeout_s + 3, elapsed


def _assert_no_browser_left(before: list[tuple[int, str]]) -> None:
    deadline = time.monotonic() + 5
    while len(_browser_processes()) > len(before) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert len(_browser_processes()) == len(before)


def _assert_the_next_render_works() -> None:
    again, _elapsed = _Bounded(lambda: render_site(garner_site("doc_after_spin"), garner_brand(), [], base_path="")).outcome(60)
    assert not isinstance(again, BaseException), again
    assert [page.route for page in again.pages] == ["/", "/analysis"]  # type: ignore[attr-defined]


def _spinning_section(name: str, spin: str):
    return hostile(name, f'export function render(props, kit) {{ {spin} return jsx("div", {{ children: "spun" }}); }}\n')


@pytest.mark.parametrize(
    ("spin", "may_be_read_first"),
    [
        ("setTimeout(() => { for (;;) {} }, 5);", True),
        # Runs once the render has answered and before anything else can run: never read first.
        ("queueMicrotask(() => { for (;;) {} });", False),
        ("requestAnimationFrame(() => { for (;;) {} });", True),
    ],
    ids=["timeout", "microtask", "animation-frame"],
)
def test_a_section_that_spins_just_after_its_render_cannot_hang_the_render(spin: str, may_be_read_first: bool) -> None:
    """The section renders normally and starts a busy loop a moment later. Wherever the loop lands
    (before the render's answer is seen, or between the reads of it), the render ends at its time
    limit as a typed timeout, its browser is gone, and the next render in the process works.

    A loop on a timer or an animation frame can, rarely, start only after the renderer has read the
    whole answer. Then the render has finished, correctly, and the loop dies with the browser; the
    test accepts that outcome for those two (not seen in 49 timer and animation-frame runs on
    2026-10-13, but not ruled out)."""
    before = _browser_processes()
    site, module = _spinning_section("SpinAfter", spin)
    value, elapsed = _Bounded(lambda: render_site(site, garner_brand(), [module], base_path="", timeout_s=SPIN_TIMEOUT_S)).outcome()
    if may_be_read_first and not isinstance(value, BaseException):
        assert '<div data-agent-section="SpinAfter"><div>spun</div></div>' in value.pages[0].html  # type: ignore[attr-defined]
    else:
        _assert_timed_out(value, elapsed)
    _assert_no_browser_left(before)
    _assert_the_next_render_works()


def test_a_section_that_spins_while_its_answer_is_read_still_times_out() -> None:
    """The busy loop starts inside the renderer's read of the result (``SPIN_ON_READ``). That read
    is bounded by the render's time limit like every other call into the page."""
    before = _browser_processes()
    site, module = _spinning_section("SpinOnRead", SPIN_ON_READ)
    value, elapsed = _Bounded(lambda: render_site(site, garner_brand(), [module], base_path="", timeout_s=SPIN_TIMEOUT_S)).outcome()
    _assert_timed_out(value, elapsed)
    _assert_no_browser_left(before)
    _assert_the_next_render_works()


@pytest.mark.parametrize(
    ("spin", "may_be_read_first"),
    [
        ("setTimeout(() => { for (;;) {} }, 5);", True),
        # Fires once the module has loaded and the schema has been answered (both happen in the
        # microtasks right after the module runs), so the loop starts inside the read of it.
        ('setTimeout(() => { Object.defineProperty(window.__clueRender.result, "props", { get() { for (;;) {} } }); }, 0);', False),
    ],
    ids=["timeout", "spin-on-read"],
)
def test_read_section_schema_of_a_module_that_spins_after_loading_is_bounded(spin: str, may_be_read_first: bool) -> None:
    """The same bounds for the compile-time schema read (it runs the same render page). As above,
    a timer loop may, rarely, start only after the schema has been read: then the read succeeds."""
    before = _browser_processes()
    value, elapsed = _Bounded(lambda: read_section_schema(QUOTE_JS + spin + "\n", timeout_s=SPIN_TIMEOUT_S)).outcome()
    if may_be_read_first and not isinstance(value, BaseException):
        assert sorted(value["properties"]) == ["id", "quote", "surface"]  # type: ignore[index]
    else:
        _assert_timed_out(value, elapsed)
    _assert_no_browser_left(before)


def test_a_spinning_render_does_not_hold_up_a_normal_render_beside_it() -> None:
    """Two renders at once on two threads: the hostile one (its loop starts while its answer is
    read) times out at its own limit; the normal one finishes normally within its own."""
    before = _browser_processes()
    site, module = _spinning_section("SpinBeside", SPIN_ON_READ)
    spinning = _Bounded(lambda: render_site(site, garner_brand(), [module], base_path="", timeout_s=SPIN_TIMEOUT_S))
    normal = _Bounded(lambda: render_site(garner_site("doc_beside"), garner_brand(), [], base_path="/acme-site", timeout_s=20))
    rendered, normal_elapsed = normal.outcome()
    value, elapsed = spinning.outcome()
    assert not isinstance(rendered, BaseException), rendered
    assert [page.route for page in rendered.pages] == ["/", "/analysis"]  # type: ignore[attr-defined]
    assert normal_elapsed < 20, normal_elapsed
    _assert_timed_out(value, elapsed)
    _assert_no_browser_left(before)


def test_the_time_limit_starts_when_the_page_is_ready_not_while_waiting_for_a_slot() -> None:
    """``timeout_s`` bounds the page's work, not the wait for a capture slot or the browser launch.
    A normal render queued behind busy capture slots (thumbnails, PDFs and other renders share
    them) gets its whole time limit once its page is ready: it is not refused as a timeout."""
    held = threading.Event()

    def hold_every_slot() -> None:
        taken = 0
        try:
            while _CAPTURE_SLOTS.acquire(blocking=False):
                taken += 1
            held.set()
            time.sleep(2.5)
        finally:
            for _ in range(taken):
                _CAPTURE_SLOTS.release()

    holder = threading.Thread(target=hold_every_slot, daemon=True)
    holder.start()
    assert held.wait(10)
    rendered, elapsed = _Bounded(lambda: render_site(garner_site("doc_queued"), garner_brand(), [], base_path="", timeout_s=2)).outcome(60)
    holder.join(10)
    assert not isinstance(rendered, BaseException), rendered
    assert [page.route for page in rendered.pages] == ["/", "/analysis"]  # type: ignore[attr-defined]
    assert elapsed > 2.4, elapsed  # it did wait for a slot, longer than its whole time limit


def test_a_javascript_url_that_replaces_the_document_fails_fast() -> None:
    """A ``javascript:`` URL whose script returns a string replaces the render document with that
    string, and Chromium reports no navigation for it. The render notices that the page no longer
    shows the document the shell pinned, and refuses at once and by name, never a stall until
    ``timeout_s``."""
    body = (
        "location.href = \"javascript:'<p>replaced</p>'\";\n"
        "await new Promise((resolve) => setTimeout(resolve, 400));\n"
        'export function render(props, kit) { return jsx("div", { children: "replaced" }); }\n'
    )
    site, module = hostile("JsUrl", body)
    value, elapsed = _Bounded(lambda: render_site(site, garner_brand(), [module], base_path="", timeout_s=20)).outcome(40)
    assert isinstance(value, SiteRenderError), value
    assert value.code == RENDER_FAILED
    assert "a section navigated the render page away" in value.message
    assert "a section may not navigate or reload the page" in value.message
    assert elapsed < 5, elapsed


@pytest.mark.parametrize(
    "call",
    ['document.open(); document.write("<p>x</p>"); document.close();', "location.href = \"javascript:document.write('x')\";"],
    ids=["document-open-and-write", "javascript-url-that-only-writes"],
)
def test_a_section_that_rewrites_the_document_in_place_renders_normally(call: str) -> None:
    """Ruling 2026-10-13 (Lane A Task 29): ``document.open()``/``write()``, called directly or from
    a ``javascript:`` URL whose script returns nothing, keeps the same Document and Window and loads
    nothing. The render's output comes from react-dom/server, not from the DOM, so the render is
    unaffected: it is neither refused nor warned about. (Only a ``javascript:`` URL that RETURNS a
    string replaces the document; see the test above.) The wait lets the rewrite land before the
    render answers."""
    body = call + '\nawait new Promise((resolve) => setTimeout(resolve, 400));\nexport function render(props, kit) { return jsx("div", { children: "rewritten" }); }\n'
    site, module = hostile("Rewrite", body)
    value, elapsed = _Bounded(lambda: render_site(site, garner_brand(), [module], base_path="", timeout_s=8)).outcome(30)
    assert not isinstance(value, BaseException), value
    assert '<div data-agent-section="Rewrite"><div>rewritten</div></div>' in value.pages[0].html  # type: ignore[attr-defined]
    assert value.warnings == []  # type: ignore[attr-defined]


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


def test_live_render_returns_page_data_and_takes_the_html_over_without_a_mismatch() -> None:
    site = garner_site("doc_live")
    result = site_render.render_site(site, garner_brand(), [], base_path="/acme", live=True)
    home = result.pages[0]
    assert '<body><div id="clue-site">' in home.html
    assert home.data is not None and home.data["route"] == "/" and home.data["sections"] == {}
    assert not [w for w in result.warnings if w.startswith("hydration")], result.warnings


def test_a_section_that_draws_differently_in_the_browser_is_reported_by_route() -> None:
    module_js = (
        'import { jsx } from "react/jsx-runtime";\n'
        'import { z } from "zod";\n'
        'export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n'
        'export function render() { return jsx("p", { children: typeof window.__clueRender === "object" && document.getElementById("clue-site") ? "browser" : "server" }); }\n'
    )
    site, sections = site_with_agent_section("Drift", module_js)
    result = site_render.render_site(site, garner_brand(), sections, base_path="", live=True)
    assert any(w.startswith("hydration on /: mismatch") for w in result.warnings), result.warnings
    # Production React minifies the message; the agent reads a plain sentence instead (final review F3).
    mismatches = [w for w in result.warnings if w.startswith("hydration on /: mismatch")]
    assert all(re.fullmatch(r"hydration on /: mismatch: the server and the browser drew this page differently \(React #4\d\d\)", w) for w in mismatches), mismatches


def test_review_focus_5_a_stored_module_importing_a_missing_name_fails_by_name() -> None:
    module_js = 'import { useNotAHook } from "react";\nexport const schema = null;\nexport function render() { useNotAHook(); return null; }\n'
    site, sections = site_with_agent_section("Broken", module_js)
    with pytest.raises(site_render.SiteRenderError) as refused:
        site_render.render_site(site, garner_brand(), sections, base_path="", live=True)
    assert "useNotAHook" in refused.value.message


def test_static_render_is_unchanged_and_carries_no_page_data() -> None:
    result = site_render.render_site(garner_site("doc_static"), garner_brand(), [], base_path="/acme")
    assert all(page.data is None for page in result.pages)
    assert 'id="clue-site"' not in result.pages[0].html
