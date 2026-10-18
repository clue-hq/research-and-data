"""The Puck site renderer (Wave 2 Lane A, Contract 3).

Every site render — publish, thumbnail, the agent's own preview — runs agent-written
section code inside ONE hardened headless Chromium page (D2, founder ruling 2026-10-11). Python and
Node never import or run it. The shared types and paths (Task 11), then the render, the section
schema read and the screenshot (Task 17; the browser itself is ``lumen_api.hardened_browser``).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from . import web_export
from .hardened_browser import HardenedBrowserUnavailable, hardened_page

JsonObject = dict[str, Any]

RENDER_TIMEOUT = "render.timeout"
OUTPUT_TOO_LARGE = "render.output_too_large"
SECTION_MODULE_MISSING = "render.section_module_missing"
RENDER_FAILED = "render.failed"

#: The monorepo root — `subsystems/clue-design/apps/api/lumen_api/<this file>`.
_REPO_ROOT = Path(__file__).resolve().parents[5]
SITE_KIT_DIST_ENV = "LUMEN_SITE_KIT_DIST"
DEFAULT_SITE_KIT_DIST = _REPO_ROOT / "apps" / "frontend" / "packages" / "site-kit" / "dist"


class SiteRenderError(Exception):
    """A site render, a screenshot or a section-schema read that could not finish.

    ``code`` is one of the four contract codes above; ``message`` says why, in words a caller can
    show (a route's 409/502 body, or the agent's tool answer)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class SectionModule:
    """One compiled agent section as Lane B6's store returns it (Contract 4)."""

    name: str
    digest: str
    module_js: str
    css: str
    props_schema: JsonObject


@dataclass(frozen=True)
class RenderedPage:
    """One route of a rendered site: a whole HTML document, without the site's compiled CSS. In live
    mode ``data`` is the page's data (site-kit ``LivePageData``) the published page hydrates from."""

    route: str
    html: str
    data: JsonObject | None = None


@dataclass(frozen=True)
class SiteRender:
    pages: list[RenderedPage]
    css: str
    warnings: list[str] = field(default_factory=list)


def site_kit_dist() -> Path:
    """Where site-kit's built files are: ``LUMEN_SITE_KIT_DIST``, else the checkout's
    ``apps/frontend/packages/site-kit/dist`` (which ``npm run build -w @clue/site-kit`` writes and
    the backend image builds)."""
    override = os.environ.get(SITE_KIT_DIST_ENV, "").strip()
    return Path(override).expanduser() if override else DEFAULT_SITE_KIT_DIST


def site_routes(site: JsonObject) -> list[str]:
    """A site's routes in render order: "/" first, then the others alphabetically."""
    pages = site.get("pages") or {}
    return (["/"] if "/" in pages else []) + sorted(route for route in pages if route != "/")


def pinned_modules(site: JsonObject, sections: Sequence[SectionModule]) -> list[SectionModule]:
    """The modules the site's ``agent_sections`` pin, in pin order. Every pinned name must come
    with exactly its digest, and the module's bytes must hash to it: a module whose bytes changed is
    stale and is refused like a missing one, never rendered as a blank section (the master plan's Review focus 5)."""
    by_name = {module.name: module for module in sections}
    modules: list[SectionModule] = []
    for name, digest in (site.get("agent_sections") or {}).items():
        module = by_name.get(str(name))
        if module is None or module.digest != digest:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name} has no stored module {str(digest)[:12]}")
        if hashlib.sha256(module.module_js.encode("utf-8")).hexdigest() != digest:
            raise SiteRenderError(
                SECTION_MODULE_MISSING,
                f"agent section {name}'s stored module is stale (its bytes do not match {str(digest)[:12]})",
            )
        modules.append(module)
    return modules


DEFAULT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
SCHEMA_MAX_OUTPUT_BYTES = 1024 * 1024
CSS_TIMEOUT_SECONDS = 60
_FONT_SETTLE_MS = 300
#: How long the render wait runs before it looks up to see whether the main frame moved. A move that
#: replaced the render document (a reload, a navigation that committed another document) is refused
#: within about this long, never left to run out ``timeout_s``; a move that kept it (a hash change)
#: becomes a warning and the wait goes on.
_NAVIGATION_CHECK_MS = 250
#: At most this many distinct in-place URL changes are named (each cut to 160 characters), so a
#: section changing the URL in a loop cannot flood the warnings.
_MAX_URL_CHANGES = 20
#: The render page's policy: the bundle runs inline, agent sections arrive as data: modules, and
#: nothing else may load, connect, frame or submit.
_RENDER_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' data:; style-src 'none'; img-src 'none'; "
    "font-src 'none'; media-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; "
    "worker-src 'none'; manifest-src 'none'; form-action 'none'; base-uri 'none'"
)
#: Polled until a live preview page has come alive (``site_live``'s runtime sets the flag).
_HYDRATED = "() => window.__clueHydrated === true"
#: Polled until the render answers: ``true`` once it has; ``'replaced'`` once the page shows a
#: document other than the one the shell pinned (a ``javascript:`` URL whose script returns a string
#: replaces it, and Chromium reports no navigation for that, so only this question catches it).
_DONE = (
    "() => { if (window.__clueRenderDocument !== document) return 'replaced';"
    " const c = window.__clueRender; return !!c && c.done === true; }"
)
#: The channel's head, plus the shell's URL-change log (read in the same call, so the reads after
#: the render answers take no extra round trip).
_HEAD = (
    "() => { const c = window.__clueRender; "
    "return {nonce: c.nonce, length: typeof c.json === 'string' ? c.json.length : -1, code: c.code, error: c.error, "
    "urlChanges: window.__clueUrlChanges}; }"
)
#: The answer as ONE string (review S3-1): read only after its length — a string's own length, which no
#: section can change — is within the limit.
_RESULT = "() => window.__clueRender.json"
#: The error codes the render page itself produces (render-browser.tsx); any other is not its own.
_PAGE_CODES = frozenset({RENDER_FAILED, OUTPUT_TOO_LARGE})
#: The render page's own script, before the input and before any section loads (founder ruling
#: 2026-10-13: an in-place URL change is a warning, not a failed render). ``history.pushState`` and
#: ``replaceState`` record what a section asked for and change nothing: on this ``about:blank``
#: document the real ones throw on a path URL (inside the section's own code) and move the page on a
#: hash URL, and either way the published page runs no script, so the change could never do
#: anything there. The record lives in a closure, and Python reads it as ONE string through a getter
#: no section can replace — at most ``_MAX_URL_CHANGES`` distinct entries of 160 characters, whatever
#: a section later does to the page's builtins (the ones used are taken here, before any section
#: runs). The document is pinned too, so after a move Python can ask whether it is still this one.
_URL_CHANGE_SHIM = (
    "(() => {"
    " const apply = Reflect.apply, slice = String.prototype.slice, includes = String.prototype.includes;"
    " const quote = JSON.stringify, text = String, define = Object.defineProperty;"
    ' let log = "", count = 0;'
    " const record = (method) => function (state, unused, url) {"
    f"  if (url === undefined || url === null || count >= {_MAX_URL_CHANGES}) return;"
    "  let value = text(url);"
    "  if (value.length > 160) value = apply(slice, value, [0, 160]);"
    '  const entry = "[" + quote(method) + "," + quote(value) + "]";'
    '  if (!apply(includes, log, [entry])) log += (count++ ? "," : "") + entry;'
    " };"
    ' History.prototype.pushState = record("pushState");'
    ' History.prototype.replaceState = record("replaceState");'
    ' define(window, "__clueUrlChanges", { get: () => "[" + log + "]" });'
    ' define(window, "__clueRenderDocument", { value: document });'
    " })();"
)
#: Whether the main frame still shows the document the shell pinned. Asked through
#: ``wait_for_function``, which answers at once either way.
_SAME_DOCUMENT = "() => window.__clueRenderDocument === document ? 'same' : 'replaced'"


class _CloseAtDeadline:
    """Closes ``page`` at ``deadline`` (``time.monotonic()``), even while this thread is waiting
    inside a call into it, so that call returns.

    A section may start a busy loop at any moment. A call into the page that is already waiting
    when the loop starts never gets its answer, and no Playwright timeout fully covers that:
    ``evaluate`` has no time limit, and ``wait_for_function``'s own timeout still waits on the page
    to cancel its poll (Playwright 1.61, probed 2026-10-13). Closing the page ends every call into
    it at once; the browser is closed as usual when the render's block ends.

    The sync API waits on a call by running its asyncio loop on this same thread, so the close is
    scheduled on that loop (``_loop`` and ``_impl_obj`` are the sync wrapper's private links to it
    and to the async page). It needs no second thread."""

    def __init__(self, page: Any, deadline: float) -> None:
        from playwright.sync_api import Error as PlaywrightError

        impl, loop = page._impl_obj, page._loop
        self.fired = False

        async def close() -> None:
            try:
                await impl.close()
            except PlaywrightError:
                pass  # closed already: nothing left to stop

        def fire() -> None:
            self.fired = True
            loop.create_task(close())

        self._timer = loop.call_at(loop.time() + max(0.0, deadline - time.monotonic()), fire)

    def disarm(self) -> None:
        self._timer.cancel()


@functools.lru_cache(maxsize=4)
def _read_bundle(path: str, mtime_ns: int) -> str:
    return Path(path).read_text(encoding="utf-8")


def _render_bundle() -> str:
    path = site_kit_dist() / "render-browser.js"
    if not path.is_file():
        raise SiteRenderError(
            RENDER_FAILED,
            f"the site render bundle is not built ({path} is missing): run `npm run build -w @clue/site-kit` in apps/frontend",
        )
    return _read_bundle(str(path), path.stat().st_mtime_ns)


def _shell_html(payload: JsonObject) -> str:
    # "<" escaped everywhere, so no string in the data can end or confuse the inert script element.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_RENDER_CSP}">'
        f"<script>{_URL_CHANGE_SHIM}</script>"
        "</head><body>"
        f'<script id="clue-render-input" type="application/json">{data}</script>'
        "</body></html>"
    )


def _url_change_warning(method: str, url: str) -> str:
    # The URL is the section's own text: cut, and made printable (no line breaks, NULs or lone
    # surrogates) before it goes where people and the agent read it.
    shown = "".join(char if char.isprintable() else "\ufffd" for char in url[:160])
    return f"a section changed the page URL in place ({method} {shown}); this has no effect on the published page, which runs no script"


def _run_shell(payload: JsonObject, *, timeout_s: float, max_output_bytes: int) -> tuple[JsonObject, list[str], list[str]]:
    """Run the render bundle over ``payload`` in a hardened page; return (result, blocked URLs, one
    warning line per distinct in-place URL change)."""
    try:
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout
    except ImportError as error:
        raise SiteRenderError(RENDER_FAILED, "playwright is not installed") from error
    bundle = _render_bundle()
    nonce = secrets.token_hex(16)
    closer: _CloseAtDeadline | None = None
    try:
        with hardened_page(javascript=True) as (page, blocked):
            # The time limit starts now that the page is ready: it bounds the page's work, not the
            # wait for a capture slot or the browser launch (that has its own launch timeout).
            deadline = time.monotonic() + timeout_s

            def remaining_ms() -> float:
                return max(1.0, (deadline - time.monotonic()) * 1000)

            page.set_content(
                _shell_html({**payload, "nonce": nonce, "maxOutputBytes": max_output_bytes}),
                wait_until="domcontentloaded",
                timeout=remaining_ms(),
            )
            # From here the page holds the render input. A navigation REQUEST is answered locally
            # (hardened_browser: an empty 204, so the page stays put). What can still move the main
            # frame is one of two things, and Chromium fires framenavigated for both:
            # - a move IN PLACE (a hash change): it loads nothing and keeps this document, and the
            #   published page runs no script, so it can never do anything there — it becomes a
            #   warning and the render goes on (founder ruling 2026-10-13). pushState/replaceState
            #   never move the page at all: the shell's own script records them (_URL_CHANGE_SHIM).
            # - a REAL navigation: a reload of this about:blank document never reaches the network,
            #   and it (like any navigation that commits) replaces the document, so the render is
            #   over and is refused at once and by name.
            # Each move is told apart by asking the page whether it still shows the document the
            # shell pinned. (Not by the input element: the bundle removes it before any section runs.)
            # One replacement fires no framenavigated at all (a javascript: URL whose script returns
            # a string), so the poll for the render's answer asks the same question each time.
            # document.open()/write() keeps the document and loads nothing, and the render's output
            # does not come from the DOM, so it changes nothing here (ruling 2026-10-13).
            moved: list[str] = []
            hash_changes: list[str] = []

            def on_navigated(frame: Any) -> None:
                if frame.parent_frame is None:
                    moved.append(frame.url)

            def still_the_render_document() -> bool:
                try:
                    handle = page.wait_for_function(_SAME_DOCUMENT, timeout=remaining_ms(), polling=50)
                except PlaywrightTimeout:
                    raise  # the page is busy past the time limit: a timeout, as anywhere else
                except PlaywrightError:
                    if closer.fired:
                        raise  # closed at the deadline: a timeout, not a navigation
                    return False  # the page was mid-navigation: its document is being replaced
                return handle.json_value() == "same"  # a primitive: no second call to the page

            def navigated_away(where: str) -> SiteRenderError:
                return SiteRenderError(
                    RENDER_FAILED, f"a section navigated the render page away ({where}); a section may not navigate or reload the page"
                )

            def refuse_if_moved() -> None:
                if not moved:
                    return
                checked = len(moved)
                if not still_the_render_document():
                    raise navigated_away(f"to {moved[-1][:160]}")
                for url in moved[:checked]:
                    fragment = (url[url.index("#") :] if "#" in url else url)[:160]
                    if fragment not in hash_changes and len(hash_changes) < _MAX_URL_CHANGES:
                        hash_changes.append(fragment)
                del moved[:checked]

            page.on("framenavigated", on_navigated)
            # From here sections run: nothing waits on the page past the deadline (it is closed
            # then, under whatever call is waiting).
            closer = _CloseAtDeadline(page, deadline)
            try:
                try:
                    page.add_script_tag(content=bundle)
                except PlaywrightError as error:
                    # Playwright fails add_script_tag on ANY Content-Security-Policy console error
                    # printed while it waits, taking it for its own script being blocked. This page
                    # allows inline script, so the bundle is never blocked; such an error comes from
                    # what the bundle is doing — a live render's hydration check puts the drawn HTML
                    # into this page, and its style attributes break the page's style-src 'none'
                    # (harmless: nothing here is looked at). The bundle runs on, and the wait below
                    # takes its answer; were it ever truly blocked, that wait would time out.
                    if isinstance(error, PlaywrightTimeout) or "Content Security Policy" not in str(error).replace("-", " "):
                        raise
                while True:
                    refuse_if_moved()
                    try:
                        answer = page.wait_for_function(_DONE, timeout=min(_NAVIGATION_CHECK_MS, remaining_ms()), polling=50)
                        break
                    except PlaywrightTimeout:
                        if time.monotonic() >= deadline:
                            raise
                if answer.json_value() == "replaced":  # true or 'replaced': a primitive, no second call
                    refuse_if_moved()  # a move Chromium reported is named by its URL, as before
                    raise navigated_away("it replaced the render document")
                refuse_if_moved()
                head = page.evaluate(_HEAD)
                if not isinstance(head, dict) or head.get("nonce") != nonce:
                    raise SiteRenderError(RENDER_FAILED, "the render page answered without its nonce")
                if head.get("code"):
                    code = str(head["code"])
                    if code not in _PAGE_CODES:
                        raise SiteRenderError(RENDER_FAILED, "the render page answered with an error it does not produce")
                    raise SiteRenderError(code, str(head.get("error") or code))
                # Review S3-1: the size is measured here, from what the page actually answers.
                length = head.get("length")
                if not isinstance(length, int) or length < 0:
                    raise SiteRenderError(RENDER_FAILED, "the render page answered nothing")
                if length > max_output_bytes:
                    raise SiteRenderError(OUTPUT_TOO_LARGE, f"the rendered site is larger than {max_output_bytes} characters")
                answer_json = page.evaluate(_RESULT)
                refuse_if_moved()
                if not isinstance(answer_json, str) or len(answer_json) > max_output_bytes:
                    raise SiteRenderError(OUTPUT_TOO_LARGE, f"the rendered site is larger than {max_output_bytes} characters")
                try:
                    result = json.loads(answer_json)
                except ValueError as error:
                    raise SiteRenderError(RENDER_FAILED, "the render page's answer is not JSON") from error
            except PlaywrightTimeout:
                raise  # the time limit: no time is left to ask the page anything
            except PlaywrightError:
                if not closer.fired:
                    refuse_if_moved()  # a call the page moved out from under: name the move, not the call
                raise
            finally:
                closer.disarm()
            logged = head.get("urlChanges")
            history_changes = json.loads(logged) if isinstance(logged, str) else []
            changes = [("hash", fragment) for fragment in hash_changes] + [(method, url) for method, url in history_changes]
            url_changes = list(dict.fromkeys(_url_change_warning(method, url) for method, url in changes))
            return (result if isinstance(result, dict) else {}), list(blocked), url_changes
    except PlaywrightError as error:
        if isinstance(error, PlaywrightTimeout) or (closer is not None and closer.fired):
            raise SiteRenderError(RENDER_TIMEOUT, f"the site did not render within {timeout_s:g}s") from error
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
    except HardenedBrowserUnavailable as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error


def _scan_text(html: str) -> str:
    """What the Tailwind scanner reads: the page without the clones (their captured class names
    must not mint utilities for our markup — the WebDoc W7 lesson, web_export._document_only_html)
    and without <style> text."""
    tree = LexborHTMLParser(html)
    for node in list(tree.css("[data-lumen-fragment]")):
        node.decompose()
    for node in list(tree.css("style")):
        node.decompose()
    return tree.html or ""


#: One line of site-kit's Tailwind theme (theme.ts `themeBlock`): a theme variable naming a brand one.
#: Names come from kit token paths (brand-values.ts TOKEN_PATH, dots written as dashes).
_THEME_LINE = re.compile(r"  --[A-Za-z0-9_-]+: var\(--brand-[A-Za-z0-9_-]+\);")


def _checked_theme(tailwind_theme: str) -> str:
    """Review K5-5: the theme comes back from the render page, where a section's code runs, and is
    compiled into the published stylesheet. Only site-kit's exact shape is taken — ONE ``@theme inline``
    block of ``--name: var(--brand-name);`` lines — so no CSS of a section's can reach the stylesheet."""
    lines = tailwind_theme.split("\n")
    if (
        len(lines) < 3
        or lines[0] != "@theme inline {"
        or lines[-2:] != ["}", ""]
        or not all(_THEME_LINE.fullmatch(line) for line in lines[1:-2])
    ):
        raise SiteRenderError(RENDER_FAILED, "the render page's theme is not site-kit's theme")
    return tailwind_theme


def _compile_css(pages: Sequence[RenderedPage], tailwind_theme: str, node_bin: str) -> str:
    try:
        web_export.require_static_css_toolchain(node_bin)
        return web_export.compile_tailwind_css(
            "\n".join(_scan_text(page.html) for page in pages),
            '@import "tailwindcss";\n' + tailwind_theme,
            node_bin,
            timeout_seconds=CSS_TIMEOUT_SECONDS,
        )
    except web_export.WebExportCompileError as error:
        raise SiteRenderError(RENDER_FAILED, f"the site's stylesheet did not compile: {error.stderr}") from error


def render_site(
    site: Mapping[str, Any],
    brand: Mapping[str, Any],
    sections: Sequence[SectionModule],
    *,
    base_path: str,
    routes: Sequence[str] | None = None,
    live: bool = False,
    timeout_s: float = 20.0,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    node_bin: str = "node",
) -> SiteRender:
    """Render ``site`` (Contract 1) with ``brand`` (site-kit BrandData) and its agent ``sections``.

    ``base_path`` is where the site is served ("/acme-site"); "" leaves /route links as written.
    Each page comes back as a whole document without CSS; ``css`` is the site's compiled Tailwind
    plus each agent section's own stored CSS. ``timeout_s`` bounds the page's work, not the wait for
    a capture slot or the browser launch. With ``live``, each page is drawn into ``#clue-site`` for
    the browser to take over, comes back with its ``data``, and is taken over once inside the render
    page: each mismatch or failure there is a warning ``"hydration on <route>: <message>"``. Raises
    :class:`SiteRenderError`."""
    modules = pinned_modules(dict(site), sections)
    known = site_routes(dict(site))
    wanted = list(routes) if routes is not None else known
    missing = [route for route in wanted if route not in known]
    if missing:
        raise SiteRenderError(RENDER_FAILED, "the site has no page " + ", ".join(missing))
    payload = {
        "mode": "render",
        "site": {"title": site.get("title") or "", "pages": site.get("pages") or {}, "shell": site.get("shell")},
        "brand": dict(brand),
        "basePath": base_path,
        "routes": wanted,
        "live": live,
        "sections": [{"name": module.name, "moduleJs": module.module_js} for module in modules],
    }
    result, blocked, url_changes = _run_shell(payload, timeout_s=timeout_s, max_output_bytes=max_output_bytes)
    pages = [
        RenderedPage(route=str(page["route"]), html=str(page["html"]), data=page.get("data") if live else None)
        for page in result.get("pages") or []
    ]
    css = _compile_css(pages, _checked_theme(str(result.get("tailwindTheme") or "")), node_bin)
    module_css = "\n".join(module.css for module in modules if module.css)
    warnings = [str(warning) for warning in result.get("warnings") or []]
    warnings += url_changes
    warnings += [f"blocked a network request to {url[:160]}" for url in dict.fromkeys(blocked)]
    return SiteRender(pages=pages, css=f"{css}\n{module_css}" if module_css else css, warnings=warnings)


def read_section_schema(module_js: str, *, timeout_s: float = 10.0) -> JsonObject:
    """Import ONE compiled agent section inside the hardened render page and return its props JSON
    Schema (Lane B6 calls this at compile time; nothing else imports an agent module on the server).
    Refuses a module whose schema is not a zod object, lacks id or surface, carries className or
    style, or has no render function."""
    result, _blocked, _url_changes = _run_shell(
        {"mode": "schema", "sections": [{"name": "Section", "moduleJs": module_js}]},
        timeout_s=timeout_s,
        max_output_bytes=SCHEMA_MAX_OUTPUT_BYTES,
    )
    errors = result.get("errors")
    if errors:
        raise SiteRenderError(RENDER_FAILED, "; ".join(str(error) for error in errors))
    props = result.get("props")
    if not isinstance(props, dict):
        raise SiteRenderError(RENDER_FAILED, "the section's props schema is not an object")
    return props


def site_page_html(page: RenderedPage, css: str) -> str:
    """The page as one document with the site's compiled CSS in its head."""
    if not css:
        return page.html
    style = '<style id="site-static-css">' + css.replace("</", "<\\/") + "</style>"
    return web_export._inject_before_head_close(page.html, style)


#: Where a preview document is served to the hardened browser when its assets are answered on
#: request (``capture_site_screenshot(read_blob=...)``). Only this origin is ever answered.
PREVIEW_ORIGIN = "http://site.preview.local"
_ASSET_PATH = re.compile(r"^/asset-store/([0-9a-f]{64})$")


def _load_document(page: Any, document: str, read_blob: Callable[[str], tuple[str, bytes]] | None, *, timeout_ms: float) -> None:
    """Put ``document`` in the hardened page: served at :data:`PREVIEW_ORIGIN` with its
    ``/asset-store/<sha256>`` files answered from ``read_blob`` on request, or set as is."""
    if read_blob is None:
        page.set_content(document, wait_until="load", timeout=timeout_ms)
        return

    def answer(route: Any) -> None:
        path = route.request.url[len(PREVIEW_ORIGIN):]
        if path in ("", "/"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=document)
            return
        match = _ASSET_PATH.match(path)
        if match is None:
            route.abort("blockedbyclient")
            return
        try:
            media_type, data = read_blob(match.group(1))
        except Exception:  # noqa: BLE001 - a missing file is a missing picture, never a failed shot
            route.fulfill(status=404)
            return
        route.fulfill(status=200, content_type=media_type, body=data)

    page.route(PREVIEW_ORIGIN + "/**", answer)
    page.goto(PREVIEW_ORIGIN + "/", wait_until="load", timeout=timeout_ms)


def capture_site_screenshot(
    page: RenderedPage,
    css: str,
    *,
    width: int,
    full_page: bool = True,
    height: int = 900,
    scale: float = 1.0,
    timeout_s: float = 20.0,
    clip_selector: str | None = None,
    live_document: str | None = None,
    read_blob: Callable[[str], tuple[str, bytes]] | None = None,
) -> bytes:
    """A PNG of ``page`` styled by ``css``, sanitized, in a hardened page with JavaScript OFF and
    the network blocked.

    With ``read_blob`` (``digest -> (media type, bytes)``) the document is served to the browser at
    :data:`PREVIEW_ORIGIN`, and every ``/asset-store/<sha256>`` it asks for is answered from
    ``read_blob`` on request; nothing else is ever answered. The browser then fetches only the
    files the page uses. Inlining every image, font and video as ``data:`` text instead made the
    Garner Syracuse page a 44 MB document (643 inlined files, 501 of them fonts) that took 4 s to
    load, three times per preview (2026-10-17); served on request it is 1 MB and loads in 0.3 s.
    Without ``read_blob`` the document is set as is, and its images and fonts must already be ``data:`` URIs
    (``web_pdf.inline_asset_store_refs``): nothing else can load. With ``clip_selector``, the PNG is
    an element shot of the first element it matches (a refusal when nothing matches).

    With ``live_document`` (``site_live.live_preview_document``, publishing live sites), that
    self-contained document is shot instead, with JavaScript ON and the network still blocked,
    once the page has come alive (``window.__clueHydrated``) — or when the wait runs out (at most
    half the time limit), shot anyway. The page's own script may freeze it at any moment, so the
    whole live shot ends at ``timeout_s`` (counted from when the page is ready): the page is closed
    then, under whatever call is waiting on it, and the shot is a timeout."""
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

    from .site_sanitize import sanitize_site_html

    html = live_document if live_document is not None else sanitize_site_html(site_page_html(page, css)).html
    timeout_ms = timeout_s * 1000
    closer: _CloseAtDeadline | None = None
    try:
        with hardened_page(
            javascript=live_document is not None,
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
            # A scroll-driven reveal leaves below-the-fold content at its starting look in a full-page
            # capture (verified 2026-10-12); the theme's reduced-motion rule shows everything in place.
            reduced_motion="reduce",
        ) as (shot, _blocked):
            if live_document is not None:
                # Each Playwright call's own timeout is not enough here: they would add up, and a
                # call waiting on a page whose script is spinning may not return at all
                # (_CloseAtDeadline). One deadline bounds the shot instead.
                deadline = time.monotonic() + timeout_s

                def remaining_ms() -> float:
                    return max(1.0, (deadline - time.monotonic()) * 1000)

                closer = _CloseAtDeadline(shot, deadline)
                try:
                    _load_document(shot, html, read_blob, timeout_ms=remaining_ms())
                    try:
                        # At most half the time limit, so a page that never comes alive still has
                        # the other half to be shot in. A FUNCTION, like ``_DONE``: Playwright polls a
                        # bare expression with eval inside the page, which the preview policy forbids,
                        # so every page not yet alive at the first check failed (two agent sections
                        # made that certain; lane run run_site_590eb594523c, 2026-10-16).
                        shot.wait_for_function(_HYDRATED, timeout=min(remaining_ms(), timeout_ms / 2), polling=50)
                    except PlaywrightTimeout:
                        pass  # a page that never comes alive is still what the agent should see
                    shot.wait_for_timeout(_FONT_SETTLE_MS)
                    if clip_selector is not None:
                        target = shot.locator(clip_selector)
                        if target.count() == 0:
                            raise SiteRenderError(RENDER_FAILED, f"nothing to draw: {clip_selector}")
                        return target.first.screenshot(type="png", timeout=remaining_ms())
                    return shot.screenshot(type="png", full_page=full_page, timeout=remaining_ms())
                finally:
                    closer.disarm()
            _load_document(shot, html, read_blob, timeout_ms=timeout_ms)
            shot.wait_for_timeout(_FONT_SETTLE_MS)
            if clip_selector is not None:
                target = shot.locator(clip_selector)
                if target.count() == 0:
                    raise SiteRenderError(RENDER_FAILED, f"nothing to draw: {clip_selector}")
                return target.first.screenshot(type="png", timeout=timeout_ms)
            return shot.screenshot(type="png", full_page=full_page, timeout=timeout_ms)
    except PlaywrightError as error:
        if isinstance(error, PlaywrightTimeout) or (closer is not None and closer.fired):
            raise SiteRenderError(RENDER_TIMEOUT, f"the screenshot did not finish within {timeout_s:g}s") from error
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
    except HardenedBrowserUnavailable as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
