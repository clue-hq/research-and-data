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

Each site page prints AT THE TABLET LAYOUT — a 768px-wide viewport under
``emulate_media(media="screen")``, paginated onto A4 sheets with NO margins.
Three decisions, each load-bearing:

* **768px**, because that is exactly Tailwind's ``md:`` breakpoint and the width
  the agent's own ``preview_768.png`` is captured at — the render a human
  approved. An A4 sheet is 794px wide, so a 768px layout drops onto it whole
  (13px of slack each side) with NO scaling; the layout box is pinned to that
  width by an injected ``html, body { width: 768px }`` so it cannot drift with
  the sheet. The old export laid out at 1440px on one enormous sheet; the older
  one printed A4 *with* 10mm margins, which left a ~718px content box — BELOW
  ``md:`` — so every page came back in the squeezed mobile layout. Margins are
  therefore zero here on purpose: a margin shrinks the box and reflows the site.
* **Screen media**, set BEFORE the content, because ``page.pdf`` emulates print
  by default: print media would lay the site out under rules it was never
  designed or previewed in, and would let any ``@media print`` block rewrite the
  design at the last moment.
* **A small injected print sheet** (``break-inside: avoid`` on the page's bands
  and images) so Chromium's pagination cuts BETWEEN bands rather than through a
  hero or a headline. The selectors are the tags the delivery renderer actually
  emits: top-level bands are ``section``/``header``/``footer`` (the engine's
  ``SectionTag``) and images are bare ``img``.

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

#: The viewport every site page is laid out at: Tailwind's `md:` breakpoint, which
#: is the width the agent's own `preview_768.png` is captured at and the layout a
#: human signed off on. The height is only the initial viewport — Chromium
#: paginates the full document onto A4 sheets below.
_VIEWPORT = {"width": 768, "height": 1024}

#: Injected AFTER load, so it wins the cascade over the page's own sheet. Two jobs:
#: keep the layout box exactly 768px whatever the sheet is, and make Chromium's
#: page breaks fall BETWEEN the page's bands instead of through them. The selectors
#: are the delivery renderer's real vocabulary — a top-level band is a
#: `section`/`header`/`footer` and an image is a bare `img`; there is no `figure`,
#: and `data-node-id` is emitted in EDITOR mode only, so neither is asked for here.
_PRINT_SHEET = (
    "section, header, footer, img { break-inside: avoid; }\n"
    "html, body { width: 768px; margin: 0; }"
)

#: Print backgrounds on, because a landing page whose hero is a background wash is
#: a blank sheet without them. No margins: A4 is 794px, so a zero-margin sheet
#: holds the 768px layout unscaled, while ANY margin shrinks the box under the
#: `md:` breakpoint and reflows the whole site into its mobile layout.
_PDF_MARGIN = {"top": "0", "right": "0", "bottom": "0", "left": "0"}


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
    """Print each html to PDF in one browser, then merge the runs in order.

    Every html is laid out at :data:`_VIEWPORT` — 768px, Tailwind's ``md:`` — under
    SCREEN media, and printed onto A4 sheets with no margins, so the sheets hold
    exactly the tablet layout the agent's ``preview_768.png`` shows, cut between
    bands rather than reflowed.
    """

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
                context = browser.new_context(viewport=dict(_VIEWPORT))
                for html in htmls:
                    page = context.new_page()
                    try:
                        # `BrowserContext.new_page()` takes no per-page options, so
                        # the viewport is set on the page itself. It is already the
                        # context's, and it is re-stated here because THIS is the
                        # number the layout depends on: 768 is the `md:` breakpoint.
                        page.set_viewport_size(dict(_VIEWPORT))
                        content = (
                            inline_tailwind(html, runtime)
                            if runtime is not None
                            else html
                        )
                        # BEFORE the content, so nothing ever lays out under print
                        # media: `page.pdf` emulates print by default, and that is
                        # exactly the reflow this export exists to stop.
                        page.emulate_media(media="screen")
                        page.set_content(content, wait_until="load")
                        page.wait_for_timeout(_SETTLE_MS)
                        # AFTER load, so it lands last in the cascade and pins the
                        # layout box + the break behaviour over the page's own sheet.
                        page.add_style_tag(content=_PRINT_SHEET)
                        parts.append(
                            page.pdf(
                                format="A4",
                                print_background=True,
                                prefer_css_page_size=False,
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
