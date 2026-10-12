"""The Puck site renderer (Wave 2 Lane A, Contract 3).

Every site render — publish, thumbnail, export, the agent's own preview — runs agent-written
section code inside ONE hardened headless Chromium page (D2, founder ruling 2026-10-11). Python and
Node never import or run it. The shared types and paths (Task 11), then the render, the section
schema read and the screenshot (Task 17; the browser itself is ``lumen_api.hardened_browser``).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import secrets
import time
from collections.abc import Mapping, Sequence
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
    """One route of a rendered site: a whole HTML document, without the site's compiled CSS."""

    route: str
    html: str


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
#: The render page's policy: the bundle runs inline, agent sections arrive as data: modules, and
#: nothing else may load, connect, frame or submit.
_RENDER_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' data:; style-src 'none'; img-src 'none'; "
    "font-src 'none'; media-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; "
    "worker-src 'none'; manifest-src 'none'; form-action 'none'; base-uri 'none'"
)
_DONE = "() => { const c = window.__clueRender; return !!c && c.done === true; }"
_HEAD = "() => { const c = window.__clueRender; return {nonce: c.nonce, size: c.size, code: c.code, error: c.error}; }"
_RESULT = "() => window.__clueRender.result"


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
        "</head><body>"
        f'<script id="clue-render-input" type="application/json">{data}</script>'
        "</body></html>"
    )


def _run_shell(payload: JsonObject, *, timeout_s: float, max_output_bytes: int) -> tuple[JsonObject, list[str]]:
    """Run the render bundle over ``payload`` in a hardened page; return (result, blocked URLs)."""
    try:
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout
    except ImportError as error:
        raise SiteRenderError(RENDER_FAILED, "playwright is not installed") from error
    bundle = _render_bundle()
    nonce = secrets.token_hex(16)
    deadline = time.monotonic() + timeout_s

    def remaining_ms() -> float:
        return max(1.0, (deadline - time.monotonic()) * 1000)

    try:
        with hardened_page(javascript=True) as (page, blocked):
            page.set_content(
                _shell_html({**payload, "nonce": nonce, "maxOutputBytes": max_output_bytes}),
                wait_until="domcontentloaded",
                timeout=remaining_ms(),
            )
            page.add_script_tag(content=bundle)
            page.wait_for_function(_DONE, timeout=remaining_ms(), polling=50)
            head = page.evaluate(_HEAD)
            if not isinstance(head, dict) or head.get("nonce") != nonce:
                raise SiteRenderError(RENDER_FAILED, "the render page answered without its nonce")
            if head.get("code"):
                raise SiteRenderError(str(head["code"]), str(head.get("error") or head["code"]))
            size = head.get("size")
            if not isinstance(size, int) or size > max_output_bytes:
                raise SiteRenderError(OUTPUT_TOO_LARGE, f"the rendered site is larger than {max_output_bytes} characters")
            result = page.evaluate(_RESULT)
            return (result if isinstance(result, dict) else {}), list(blocked)
    except PlaywrightTimeout as error:
        raise SiteRenderError(RENDER_TIMEOUT, f"the site did not render within {timeout_s:g}s") from error
    except PlaywrightError as error:
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
    timeout_s: float = 20.0,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    node_bin: str = "node",
) -> SiteRender:
    """Render ``site`` (Contract 1) with ``brand`` (site-kit BrandData) and its agent ``sections``.

    ``base_path`` is where the site is served ("/acme-site"); "" leaves /route links as written.
    Each page comes back as a whole document without CSS; ``css`` is the site's compiled Tailwind
    plus each agent section's own stored CSS. Raises :class:`SiteRenderError`."""
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
        "sections": [{"name": module.name, "moduleJs": module.module_js} for module in modules],
    }
    result, blocked = _run_shell(payload, timeout_s=timeout_s, max_output_bytes=max_output_bytes)
    pages = [RenderedPage(route=str(page["route"]), html=str(page["html"])) for page in result.get("pages") or []]
    css = _compile_css(pages, str(result.get("tailwindTheme") or ""), node_bin)
    module_css = "\n".join(module.css for module in modules if module.css)
    warnings = [str(warning) for warning in result.get("warnings") or []]
    warnings += [f"blocked a network request to {url[:160]}" for url in dict.fromkeys(blocked)]
    return SiteRender(pages=pages, css=f"{css}\n{module_css}" if module_css else css, warnings=warnings)


def read_section_schema(module_js: str, *, timeout_s: float = 10.0) -> JsonObject:
    """Import ONE compiled agent section inside the hardened render page and return its props JSON
    Schema (Lane B6 calls this at compile time; nothing else imports an agent module on the server).
    Refuses a module whose schema is not a zod object, lacks id or surface, carries className or
    style, or has no render function."""
    result, _ = _run_shell(
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


def capture_site_screenshot(
    page: RenderedPage,
    css: str,
    *,
    width: int,
    full_page: bool = True,
    height: int = 900,
    scale: float = 1.0,
    timeout_s: float = 20.0,
) -> bytes:
    """A PNG of ``page`` styled by ``css``, sanitized, in a hardened page with JavaScript OFF and
    the network blocked. Its images and fonts must already be ``data:`` URIs
    (``web_pdf.inline_asset_store_refs``): nothing else can load."""
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

    from .site_sanitize import sanitize_site_html

    html = sanitize_site_html(site_page_html(page, css)).html
    timeout_ms = timeout_s * 1000
    try:
        with hardened_page(javascript=False, viewport={"width": width, "height": height}, device_scale_factor=scale) as (shot, _blocked):
            shot.set_content(html, wait_until="load", timeout=timeout_ms)
            shot.wait_for_timeout(_FONT_SETTLE_MS)
            return shot.screenshot(type="png", full_page=full_page, timeout=timeout_ms)
    except PlaywrightTimeout as error:
        raise SiteRenderError(RENDER_TIMEOUT, f"the screenshot did not finish within {timeout_s:g}s") from error
    except PlaywrightError as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
    except HardenedBrowserUnavailable as error:
        raise SiteRenderError(RENDER_FAILED, str(error)) from error
