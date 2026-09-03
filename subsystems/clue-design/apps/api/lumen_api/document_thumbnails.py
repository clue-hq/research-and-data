"""Document-thumbnail generation for the platform gallery (2026-08-31 ruling).

A PNG for both document kinds, by the only means that tells the truth for each:

* **web** — a Playwright-Chromium screenshot of the composed render HTML. Only a
  browser rasterizes Tailwind HTML faithfully, and an editor-mode render carries
  its theme as a ``<style type="text/tailwindcss">`` block whose utilities are
  compiled at load time by the Tailwind v4 BROWSER runtime. So the runtime is
  INLINED into the html exactly the way the agent runtime's preview capture does
  it (``lumen_agent/tools/web_substrate.py``): ``set_content`` gives the page no
  origin, so a ``src=`` reference to a dev-server URL is not an option.
* **scene** — the engine's own Skia PNG (the route hands us an
  ``export_preview`` result), downscaled here.

The capture posture deliberately diverges from web_substrate's preview pass in
two places, because a THUMBNAIL is not a review screenshot: the shot is a
VIEWPORT crop, not ``full_page`` (a card frame shows the top of the page, not a
20,000px strip squeezed into 4:3), and a missing Tailwind runtime is a loud
refusal rather than a render-bare-and-warn (a layoutless card is worse than no
card — it lies about the document). Everything else — the search path, the
splice, the settle wait — is web_substrate's, which is the browser-verified one.

``main.py`` imports this module; this module never imports ``main.py``.
"""

from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from lumen_api.qa_render_ua import qa_render_context_kwargs

JsonObject = Dict[str, Any]

#: The monorepo root — `subsystems/clue-design/apps/api/lumen_api/<this file>`.
_REPO_ROOT = Path(__file__).resolve().parents[5]

#: The ordered Tailwind-runtime search path, mirroring `web_substrate.py:239-251`
#: and widening it: web_substrate resolves against the DESIGN subsystem's root, so
#: its two candidates are `apps/editor/...`. This module runs in the monorepo, and
#: the same 282KB dist file is vendored under `apps/frontend/` too — either copy
#: does. Both homes are generated artifacts (gitignored), so a fresh checkout has
#: none of the four until an `npm install` in one of the apps materializes it.
_TAILWIND_RUNTIME_ENV = "LUMEN_TAILWIND_RUNTIME"
_TAILWIND_RUNTIME_CANDIDATES = (
    ("subsystems", "clue-design", "apps", "editor", "public", "vendor", "tailwind-browser.js"),
    (
        "subsystems",
        "clue-design",
        "apps",
        "editor",
        "node_modules",
        "@tailwindcss",
        "browser",
        "dist",
        "index.global.js",
    ),
    ("apps", "frontend", "public", "vendor", "tailwind-browser.js"),
    (
        "apps",
        "frontend",
        "node_modules",
        "@tailwindcss",
        "browser",
        "dist",
        "index.global.js",
    ),
)

#: How long the page is given after `set_content` for the Tailwind JIT to scan the
#: document and emit its utilities. web_substrate's base preview pass waits exactly
#: this long (`web_substrate.py:8918`) on the same runtime and the same html.
_TAILWIND_SETTLE_MS = 400

#: How many web captures may run at once in this process.
#:
#: The route is a sync def, so each capture holds one of Starlette's 40 threadpool
#: tokens AND one whole Chromium process for the ~2s it takes — a cold gallery of N
#: web cards would otherwise launch N browsers simultaneously and take the machine's
#: memory with it. Three bounds that burst while keeping the common case (one or two
#: cards regenerating) unqueued. No knob: the eventual fix is the plan's pooled
#: persistent browser, not a tunable, so a constant is enough until that lands.
_CAPTURE_SLOTS = threading.Semaphore(3)


class ThumbnailUnavailable(Exception):
    """No honest thumbnail could be produced. Carries a stable `code` for the route."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_tailwind_runtime() -> Optional[bytes]:
    """The Tailwind browser runtime's bytes, or None when nothing supplies them.

    A set-but-missing ``LUMEN_TAILWIND_RUNTIME`` resolves to None rather than
    silently falling through to the search path: an operator who named a file must
    be told their path is wrong, not handed a different one (web_substrate's rule,
    `tailwind_runtime_path`).
    """

    override = os.environ.get(_TAILWIND_RUNTIME_ENV)
    if override:
        candidate = Path(override).expanduser()
        return candidate.read_bytes() if candidate.is_file() else None
    for parts in _TAILWIND_RUNTIME_CANDIDATES:
        candidate = _REPO_ROOT.joinpath(*parts)
        if candidate.is_file():
            return candidate.read_bytes()
    return None


def inline_tailwind(html: str, runtime: bytes) -> str:
    """Splice the runtime into `html` so it compiles the theme block at load time.

    The splice is web_substrate's (`web_substrate.py:8879-8882`) — before the first
    ``</head>`` when there is one. The runtime must load before the theme block it
    scans, so with no ``</head>`` the front of the document is the right place.

    The head-less branch is a DELIBERATE, documented divergence from
    web_substrate's degenerate fallback (which prepends unconditionally), per the
    controller ruling: our input set includes head-less documents that still open
    with a doctype, and a script in front of the doctype puts Chromium in QUIRKS
    MODE — the capture would then be a distorted picture of a page nobody ships.
    So a leading doctype is stepped over and the script goes right after it;
    everything else still prepends.
    """

    script = f"<script>{runtime.decode('utf-8')}</script>"
    if "</head>" in html:
        return html.replace("</head>", script + "\n</head>", 1)
    leading = len(html) - len(html.lstrip())
    if html[leading : leading + 9].lower() == "<!doctype":
        end = html.find(">", leading)
        if end != -1:
            return html[: end + 1] + script + html[end + 1 :]
    return script + html


def web_thumbnail_png(
    html: str, *, width: int = 1448, height: int = 1086, scale: float = 0.5
) -> bytes:
    """Screenshot the top of a composed web render, Tailwind and all.

    1448x1086 is exactly 4:3 — the gallery card's own aspect ratio — so the
    above-the-fold crop fills the frame with no letterboxing. ``scale=0.5`` makes
    that 724x543 output pixels, which is the card at 2x on a retina display.
    """

    runtime = resolve_tailwind_runtime()
    if runtime is None:
        raise ThumbnailUnavailable(
            "thumbnail.tailwind_runtime_missing",
            "no Tailwind browser runtime found (set LUMEN_TAILWIND_RUNTIME "
            "or npm install in an editor/frontend app)",
        )

    # The import is inside the function AND inside a refusal: an API process
    # without playwright installed must answer this route's ONE typed channel, not
    # crash the request with an untyped ImportError. Only the import is guarded
    # here — a blanket `except Exception` around the capture would swallow the
    # programming errors the block below is supposed to surface.
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise ThumbnailUnavailable(
            "thumbnail.capture_failed", "playwright is not installed"
        ) from error

    # The slot covers launch-through-screenshot — the whole span that owns a browser
    # process — and is taken with `with`, so a refusal or a crash inside gives it back.
    try:
        with _CAPTURE_SLOTS, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=scale,
                    # A normal Chrome UA when the flag is on — see `qa_render_ua.py`.
                    **qa_render_context_kwargs(),
                )
                page = context.new_page()
                page.set_content(inline_tailwind(html, runtime), wait_until="load")
                page.wait_for_timeout(_TAILWIND_SETTLE_MS)
                return page.screenshot(type="png")
            finally:
                browser.close()
    except PlaywrightError as error:
        raise ThumbnailUnavailable("thumbnail.capture_failed", str(error)) from error


def png_from_export_result(result: JsonObject) -> bytes:
    """The PNG bytes out of an engine ``export_preview`` result.

    The engine returns artifact bytes as a list of ints, decoded the way
    ``main.compact_export_artifact`` decodes them.

    Every failure leaves as :class:`ThumbnailUnavailable`, including the ones the
    shape checks below do not anticipate (a non-numeric entry makes ``int()``
    raise): the route answers this module through ONE typed channel, so an
    unwrapped ``ValueError`` from malformed engine bytes would 500 where a 502
    belongs.
    """

    try:
        export = result.get("export") or {}
        artifacts = [a for a in (export.get("artifacts") or []) if isinstance(a, dict)]
        if not result.get("ok", False) or not artifacts:
            raise ThumbnailUnavailable(
                "thumbnail.export_failed", "engine PNG export produced no artifact"
            )
        raw = artifacts[0].get("bytes", [])
        if not isinstance(raw, list) or not raw:
            raise ThumbnailUnavailable(
                "thumbnail.export_failed", "engine PNG artifact carried no bytes"
            )
        return bytes(int(value) & 0xFF for value in raw)
    except ThumbnailUnavailable:
        raise
    except Exception as error:
        raise ThumbnailUnavailable(
            "thumbnail.export_failed", f"engine PNG artifact could not be read: {error}"
        ) from error


def downscale_png(data: bytes, *, max_edge: int = 724) -> bytes:
    """Cap the long edge at `max_edge`, preserving aspect. Never upscales.

    Same one-channel rule as :func:`png_from_export_result`: PIL raises
    ``UnidentifiedImageError`` on bytes that are not an image, and that is a
    thumbnail refusal, not a server fault.
    """

    try:
        image = Image.open(io.BytesIO(data))
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except ThumbnailUnavailable:
        raise
    except Exception as error:
        raise ThumbnailUnavailable(
            "thumbnail.export_failed", f"the exported PNG could not be decoded: {error}"
        ) from error


def first_page_ids(scene: JsonObject) -> Optional[List[str]]:
    """The scene's first page id, as the single-element list the exporter takes.

    A scene's pages are a MAP keyed by page id (the engine's
    ``BTreeMap<PageId, Page>``; confirmed against a stored ``doc_kind='scene'``
    document), and the key is the id every other reader here uses — `page_summary`
    and `parent_map` in main.py both take it from the key.

    "First" means FIRST AS SERIALIZED, never client-side re-sorted. The engine
    writes that ``BTreeMap`` in key order, and this reader takes ``next(iter(...))``
    over the parsed object exactly as the editor takes ``Object.keys(...)[0]`` —
    both read document order. Sorting here would make the thumbnail show a
    different page from the one the editor opens on.

    Returns None — meaning "export every page, let the engine pick" — for any
    other shape, including a WEB document's page LIST. Guessing a key on an
    unrecognized shape would export the wrong page and call it the document.
    """

    pages = scene.get("pages")
    if isinstance(pages, dict) and pages:
        page_id = next(iter(pages))
        if isinstance(page_id, str):
            return [page_id]
    return None
