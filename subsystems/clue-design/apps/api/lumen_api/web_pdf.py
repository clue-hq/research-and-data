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
  approved. That viewport governs the INITIAL layout and any width-sensitive JS
  only: the print layout box IS the sheet, so the bands fill the full 794px of
  A4 (no bare strip down the right edge), and 794 is still above the ``md:``
  breakpoint, so the same tablet layout applies. The old export laid out at
  1440px on one enormous sheet; the older
  one printed A4 *with* 10mm margins, which left a ~718px content box — BELOW
  ``md:`` — so every page came back in the squeezed mobile layout. Margins are
  therefore zero here on purpose: a margin shrinks the box and reflows the site.
* **Screen media**, set BEFORE the content, because ``page.pdf`` emulates print
  by default: print media would lay the site out under rules it was never
  designed or previewed in, and would let any ``@media print`` block rewrite the
  design at the last moment.
* **A small injected print sheet** that keeps the ATOMS whole and lets the BANDS
  split. A band is routinely taller than whatever is left of the current sheet,
  so pinning ``section``/``header``/``footer`` with ``break-inside: avoid`` made
  the whole band jump to the next sheet and left the rest of this one as a void
  — half a page of bare background. Bands may therefore break across sheets now;
  only the small things Chromium would otherwise cut THROUGH (a heading, a
  paragraph, a list item, an image, a figure, a quote) are unbreakable, and a
  heading is additionally kept with the text under it (``break-after: avoid``).

Delivery HTML names its bytes ROOT-RELATIVELY — ``/asset-store/<digest>`` in
``src``, in ``srcset``, in inline ``style`` ``url()``, in the fragment CSS in the
head, and inside the compiled site stylesheet — and ``page.set_content`` gives
the document no origin, so every one of those references resolved against
nothing: the header logo printed as a broken-image icon and a photo band printed
its alt text. :func:`inline_asset_store_refs` therefore rewrites each reference
into a ``data:`` URI read straight from the blob store BEFORE the html reaches
Chromium. A digest with no blob is left exactly as it was and reported, never
raised: a missing picture is a poorer PDF, a failed export is no PDF at all.

``main.py`` imports this module; this module never imports ``main.py``.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import web_export
from .database import NotFoundError
from .document_thumbnails import _CAPTURE_SLOTS, inline_tailwind
from .public_pages import site_address

logger = logging.getLogger("lumen_api.web_pdf")

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
#: zero the body margin so the bands fill the whole 794px sheet (a pinned 768px
#: width left a bare 26px strip of page background down every page's right edge,
#: and 794 is still above `md:` so nothing reflows), and decide WHAT Chromium is
#: allowed to cut. The rule is: a band may split, a small thing may not. Pinning
#: the bands themselves (`section`/`header`/`footer`) was the earlier attempt and
#: it produced half-page voids — a band taller than the sheet's remainder moved
#: whole to the next sheet and left the background behind. So only the atoms are
#: unbreakable here, and a heading additionally stays with the text it
#: introduces.
_PRINT_SHEET = (
    "h1, h2, h3, h4, p, li, img, figure, blockquote { break-inside: avoid; }\n"
    "h1, h2, h3, h4 { break-after: avoid; }\n"
    "html, body { margin: 0; }"
)

#: Print backgrounds on, because a landing page whose hero is a background wash is
#: a blank sheet without them. No margins: A4 is 794px, so a zero-margin sheet
#: holds the 768px layout unscaled, while ANY margin shrinks the box under the
#: `md:` breakpoint and reflows the whole site into its mobile layout.
_PDF_MARGIN = {"top": "0", "right": "0", "bottom": "0", "left": "0"}


#: Every way the delivery bytes name a stored asset is this one absolute path with
#: a sha256 after it — `src="/asset-store/<d>"`, a `srcset` candidate, a CSS
#: `url(/asset-store/<d>)` in an inline `style`, in the fragment CSS, or in the
#: compiled site stylesheet. One pattern therefore covers markup and CSS alike,
#: which is exactly how `web_export` repoints the same references into a zip.
_ASSET_STORE_REF = re.compile(r"/asset-store/([0-9a-fA-F]{64})")


class WebPdfUnavailable(Exception):
    """No honest PDF could be produced. Carries a stable ``code`` for the route."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def inline_asset_store_refs(
    html: str,
    read_blob: Callable[[str], Tuple[str, bytes]],
    *,
    cache: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[str, List[str]]:
    """Replace every ``/asset-store/<digest>`` with a ``data:`` URI of its bytes.

    Pure: it reads blobs through the ``read_blob`` it is handed (the blob store's
    ``read_blob``, i.e. ``digest -> (media_type, bytes)``) and touches nothing
    else. It exists because ``page.set_content`` gives the document NO origin, so
    a root-relative asset path resolves against nothing and prints as a broken
    image; a ``data:`` URI carries its own bytes and needs no origin at all.

    Returns ``(html, missing)``. A digest the store does not have is LEFT IN THE
    HTML untouched and named in ``missing`` — an export that loses one picture is
    still an honest export, while raising here would turn a dangling asset row
    into a 502 for the whole site.

    ``cache`` maps digest -> data URI (or ``None`` for a known-missing digest) and
    may be shared across the pages of ONE export, because a site's header logo is
    on every page and its bytes should be read once. Passing nothing gives each
    call its own cache, which still de-duplicates within a single page.
    """

    resolved: Dict[str, Optional[str]] = {} if cache is None else cache
    missing: List[str] = []

    def data_uri(digest: str) -> Optional[str]:
        if digest not in resolved:
            try:
                media_type, data = read_blob(digest)
            except NotFoundError:
                resolved[digest] = None
                missing.append(digest)
            else:
                encoded = base64.b64encode(data).decode("ascii")
                resolved[digest] = f"data:{media_type};base64,{encoded}"
        return resolved[digest]

    def replace(match: "re.Match[str]") -> str:
        # A function replacement, not a template: base64 is `+/=`-safe but a
        # template would still make `\` in a media type a backreference.
        return data_uri(match.group(1)) or match.group(0)

    return _ASSET_STORE_REF.sub(replace, html), missing


def build_web_pdf(
    core: Any,
    repo: Any,
    document: JsonObject,
    *,
    blobs: Any,
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

    # A throwaway slug: nothing is persisted and no pointer moves, but the
    # package builds its manifest link and internal links from the site's
    # address, which the hostname registry answers for a slug.
    slug = "pdf-export"
    package = web_export.build_publish_package(
        core,
        repo,
        document,
        blobs=blobs,
        slug=slug,
        site_address=site_address(repo, slug),
        workspace_id=workspace_id,
        node_bin=node_bin,
        noindex=False,
        # The custom-component runtimes ride INSIDE the html: `set_content` gives the page no
        # origin, so a root-relative `/p-assets/<digest>` reference would resolve nowhere.
        embed_runtime_assets=True,
    )
    pages = list(package.pages) or [
        web_export.PublishedPage(
            page_id=document["id"],
            route="/",
            html=package.html,
            html_digest=package.html_digest,
        )
    ]
    # The bytes each page names have to travel WITH it: `set_content` gives the
    # document no origin, so `/asset-store/<digest>` resolves nowhere. One cache
    # for the whole export — the same logo appears on every page of a site.
    asset_cache: Dict[str, Optional[str]] = {}
    htmls: List[str] = []
    missing: List[str] = []
    for page in pages:
        inlined, page_missing = inline_asset_store_refs(
            page.html, blobs.read_blob, cache=asset_cache
        )
        htmls.append(inlined)
        missing.extend(page_missing)
    if missing:
        # Reported, not raised: those references stay in the html and print as
        # whatever a missing image prints as, which is a truer answer than a 502.
        logger.warning(
            "web_pdf_assets_missing document_id=%s digests=%s",
            document.get("id"),
            ",".join(digest[:12] for digest in missing),
        )
    return render_pages_pdf(htmls, runtime=runtime)


def render_pages_pdf(htmls: List[str], *, runtime: Optional[bytes] = None) -> bytes:
    """Print each html to PDF in one browser, then merge the runs in order.

    Every html is laid out at :data:`_VIEWPORT` — 768px, Tailwind's ``md:`` — under
    SCREEN media, and printed onto A4 sheets with no margins, so the sheets hold
    exactly the tablet layout the agent's ``preview_768.png`` shows, cut through
    the bands where a sheet ends (never through a heading or an image) rather
    than reflowed.

    It prints whatever html it is handed: asset inlining belongs to
    :func:`build_web_pdf`, which has the blob store this function does not.
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
