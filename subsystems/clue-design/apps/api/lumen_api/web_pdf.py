"""PDF export for website documents: every page of the site, in document order.

A website document is a SITE (F5), so its PDF is the whole site — one PDF page run
per site page, concatenated in document order — not the homepage alone.

The bytes rendered are the DELIVERY bytes: this module builds the same publish
package ``design_publish_web`` builds (``web_export.build_publish_package``) and
prints ``package.pages``. That is the cheapest correct path, because the delivery
HTML is the only render whose stylesheet is already statically compiled and
inlined (``<style id="lumen-static-css">``) — the editor-mode render carries an
uncompiled ``<style type="text/tailwindcss">`` block instead, which is why the
gallery thumbnail has to splice a browser Tailwind runtime in to be honest.

Nothing is PERSISTED. ``build_publish_package`` is a pure builder; the publish
write path (revision + pointer upsert) lives in ``toolbelt/publishes.py`` and is
deliberately not called here. Exporting a PDF must not put a site on the air.

Rasterization is Playwright Chromium, the same posture as
``document_thumbnails.web_thumbnail_png``: the shared capture-slot semaphore is
held for the whole browser-owning span, and the helpers (`_CAPTURE_SLOTS`,
``inline_tailwind``) are imported from there rather than copied. One browser
launch serves the whole document; each site page gets its own ``page``.

``main.py`` imports this module; this module never imports ``main.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import web_export
from .document_thumbnails import _CAPTURE_SLOTS, inline_tailwind

JsonObject = Dict[str, Any]

#: How long each page is given after `set_content` before it is printed. The same
#: settle the thumbnail capture uses, for the same reason: webfonts and any theme
#: block need a beat before the paint is worth photographing.
_SETTLE_MS = 400

#: Print geometry. A4 with print backgrounds on, because a landing page whose hero
#: is a background wash is a blank sheet without them.
_PDF_FORMAT = "A4"
_PDF_MARGIN = {"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"}


class WebPdfUnavailable(Exception):
    """No honest PDF could be produced. Carries a stable ``code`` for the route."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_web_pdf(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
    public_base: str,
    workspace_id: str,
    node_bin: str = "node",
    runtime: Optional[bytes] = None,
) -> bytes:
    """One PDF holding every page of ``document``'s site, in document order.

    ``runtime`` is the Tailwind BROWSER runtime's bytes, and it is optional on
    purpose: delivery HTML already carries its compiled stylesheet inline, so a
    machine with no ``npm install`` still gets a correctly styled PDF. When a
    runtime IS supplied it is spliced in exactly as the thumbnail capture splices
    it, which costs nothing and covers any page that still ships a theme block.

    Raises :class:`WebPdfUnavailable` when the browser cannot render; every
    package-build failure leaves as the ``web_export`` exception it already was,
    so the route maps it the way the ZIP route maps it.
    """

    package = web_export.build_publish_package(
        core,
        repo,
        document,
        blobs=blobs,
        # A throwaway slug: nothing is persisted and no pointer moves, but the
        # package mints canonical/og URLs and needs a slug to build them from.
        slug="pdf-export",
        public_base=public_base,
        workspace_id=workspace_id,
        node_bin=node_bin,
        noindex=False,
    )
    pages = list(package.pages) or [
        web_export.PublishedPage(
            page_id=document["id"],
            route="/",
            html=package.html,
            html_digest=package.html_digest,
        )
    ]
    return render_pages_pdf([page.html for page in pages], runtime=runtime)


def render_pages_pdf(htmls: List[str], *, runtime: Optional[bytes] = None) -> bytes:
    """Print each html to PDF in one browser, then merge the runs in order."""

    if not htmls:
        raise WebPdfUnavailable("web_pdf.render_failed", "the site has no pages")

    # The import is inside the function AND inside a refusal, as in
    # `document_thumbnails`: an API process without playwright installed must answer
    # this route's ONE typed channel, not crash the request with an ImportError.
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise WebPdfUnavailable(
            "web_pdf.render_failed", "playwright is not installed"
        ) from error

    parts: List[bytes] = []
    try:
        # One slot for the whole document: the span owns a browser process, and the
        # `with` gives it back on a refusal or a crash just as the thumbnail does.
        with _CAPTURE_SLOTS, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                for html in htmls:
                    page = context.new_page()
                    try:
                        content = (
                            inline_tailwind(html, runtime)
                            if runtime is not None
                            else html
                        )
                        page.set_content(content, wait_until="load")
                        page.wait_for_timeout(_SETTLE_MS)
                        parts.append(
                            page.pdf(
                                format=_PDF_FORMAT,
                                print_background=True,
                                margin=dict(_PDF_MARGIN),
                            )
                        )
                    finally:
                        page.close()
            finally:
                browser.close()
    except PlaywrightError as error:
        raise WebPdfUnavailable("web_pdf.render_failed", str(error)) from error

    return merge_pdfs(parts)


def merge_pdfs(parts: List[bytes]) -> bytes:
    """Concatenate PDF byte runs, in order, into one document.

    ``pymupdf`` and not ``pypdf``: pymupdf is the design API's ONE declared PDF
    library (``apps/api/pyproject.toml``), and the same file records that pypdf was
    deliberately dropped from this app because its legacy ``<6`` pin fought
    clue-research's ``>=6`` in the shared lockfile. Concatenation is one call in
    either library, so there is nothing here worth reopening that treaty for.
    """

    import pymupdf

    merged = pymupdf.open()
    try:
        for part in parts:
            with pymupdf.open(stream=part, filetype="pdf") as source:
                merged.insert_pdf(source)
        return merged.tobytes()
    finally:
        merged.close()
