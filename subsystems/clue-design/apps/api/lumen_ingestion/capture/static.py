"""Tier-1 static capture: async fetch the page, then fan out concurrently to
stylesheets (+ one level of @import) and assets (fonts/logos/images)."""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .imgsrc import background_image_urls, image_source_ladder
from .net import BoundedFetcher, FetchRequest
from .snapshot import Download, SiteSnapshot, Stylesheet, HTML_MAX_BYTES

_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?['\"]?([^'\")\s]+)['\"]?", re.IGNORECASE
)


async def fetch_static(
    url: str,
    fetcher: BoundedFetcher,
    reporter,
    *,
    fetched_at: str,
) -> SiteSnapshot:
    reporter("Visiting your website…", 0.05)
    page = await fetcher.fetch_page(url)
    final_url = page.final_url or url
    html_bytes = page.body or b""
    html = html_bytes.decode("utf-8", errors="replace")
    diagnostics: list[dict] = list(page.diagnostics)
    if len(html.encode("utf-8")) > HTML_MAX_BYTES:
        html = html.encode("utf-8")[:HTML_MAX_BYTES].decode("utf-8", errors="ignore")
        diagnostics.append(
            {
                "code": "LUMI0507",
                "severity": "warning",
                "message": "html truncated to 2 MB",
            }
        )

    tree = HTMLParser(html)

    reporter("Reading your styles…", 0.15)
    stylesheets, css_diagnostics = await _collect_stylesheets(tree, fetcher, final_url)
    diagnostics.extend(css_diagnostics)

    reporter("Collecting your logos…", 0.30)
    reporter("Gathering your visuals…", 0.45)
    downloads, asset_diagnostics = await _collect_assets(
        tree, fetcher, final_url, stylesheets
    )
    diagnostics.extend(asset_diagnostics)

    meta = _extract_meta(tree)

    return SiteSnapshot(
        requested_url=url,
        final_url=final_url,
        fetched_at=fetched_at,
        tier="static",
        html=html,
        stylesheets=stylesheets,
        downloads=downloads,
        meta=meta,
        diagnostics=diagnostics,
    )


async def _collect_stylesheets(
    tree, fetcher: BoundedFetcher, base_url: str
) -> tuple[list[Stylesheet], list[dict]]:
    sheets: list[Stylesheet] = []
    diagnostics: list[dict] = []

    # Inline <style> blocks first (no network).
    for index, node in enumerate(tree.css("style")):
        text = node.text() or ""
        if text.strip():
            sheets.append(Stylesheet(url=f"inline:{index}", text=text))

    hrefs: list[str] = []
    for node in tree.css("link[rel~=stylesheet], link[rel='stylesheet']"):
        href = node.attributes.get("href")
        if href:
            hrefs.append(urljoin(base_url, href))

    # Fetch ALL external stylesheets concurrently.
    if hrefs:
        results = await fetcher.fetch_many(
            [FetchRequest(url=h, kind="css") for h in hrefs]
        )
        for result in results:
            diagnostics.extend(result.diagnostics)
            if result.ok and result.body is not None:
                sheets.append(
                    Stylesheet(
                        url=result.url,
                        text=result.body.decode("utf-8", errors="replace"),
                    )
                )

    imported, import_diagnostics = await fetch_imported_sheets(sheets, fetcher)
    sheets.extend(imported)
    diagnostics.extend(import_diagnostics)

    return sheets, diagnostics


async def fetch_imported_sheets(
    sheets: list[Stylesheet], fetcher: BoundedFetcher
) -> tuple[list[Stylesheet], list[dict]]:
    """Follow ONE level of ``@import`` out of already-collected stylesheets.

    Shared with the rendered tier (``rendered.collect_stylesheets``) since the founder's
    2026-08-20 always-render ruling: a brand whose palette or ``@font-face`` block arrives
    through an ``@import`` used to be read by the static tier, and the rendered tier — which
    reads ``document.styleSheets``, where an import appears only as its own one-line rule text —
    would otherwise have silently stopped reading it the moment every ingestion started
    rendering. One level only, and INLINE sheets are skipped, exactly as the static tier has
    always done: a relative import inside an inline ``<style>`` has no sheet url to resolve
    against, and deeper chains are unbounded fan-out.
    """
    import_urls: list[str] = []
    for sheet in sheets:
        if sheet.url.startswith("inline:"):
            continue
        for match in _IMPORT_RE.finditer(sheet.text):
            import_urls.append(urljoin(sheet.url, match.group(1)))
    import_urls = list(dict.fromkeys(import_urls))
    if not import_urls:
        return [], []

    imported: list[Stylesheet] = []
    diagnostics: list[dict] = []
    results = await fetcher.fetch_many(
        [FetchRequest(url=u, kind="css") for u in import_urls]
    )
    for result in results:
        diagnostics.extend(result.diagnostics)
        if result.ok and result.body is not None:
            imported.append(
                Stylesheet(
                    url=result.url,
                    text=result.body.decode("utf-8", errors="replace"),
                )
            )
    return imported, diagnostics


async def _collect_assets(
    tree,
    fetcher: BoundedFetcher,
    base_url: str,
    stylesheets: list[Stylesheet],
) -> tuple[list[Download], list[dict]]:
    requests: list[FetchRequest] = []
    kinds: dict[str, str] = {}

    def add(url: str, kind: str) -> None:
        if url.startswith("data:"):
            return
        if url not in kinds:
            kinds[url] = kind
            requests.append(FetchRequest(url=url, kind="font" if kind == "font" else ("image")))

    # Fonts from @font-face src url() in fetched CSS.
    for sheet in stylesheets:
        for match in re.finditer(
            r"url\(\s*['\"]?([^'\")]+\.(?:woff2|woff|ttf|otf))['\"]?\s*\)",
            sheet.text,
            re.IGNORECASE,
        ):
            base = sheet.url if not sheet.url.startswith("inline:") else base_url
            add(urljoin(base, match.group(1)), "font")

    # Logos: header/nav/logo imgs, apple-touch-icon. Deliberately still the bare ``src``:
    # ``parse._parse_primary_logo_candidates`` scores and resolves logo candidates by their
    # ``src``, and a lockup is a vector or a small mark where the widest-rendition ladder
    # buys nothing. The ladder below re-adds these URLs anyway (dedup keeps the "logo" kind,
    # which is registered first).
    for node in tree.css("header img, nav img, [class*=logo] img, a[href='/'] img"):
        src = node.attributes.get("src")
        if src:
            add(urljoin(base_url, src), "logo")
    for node in tree.css("link[rel='apple-touch-icon']"):
        href = node.attributes.get("href")
        if href:
            add(urljoin(base_url, href), "logo")
    # Favicons were recorded into ``meta`` and never fetched, so the mark slot had exactly
    # one possible filler (apple-touch-icon). ``parse`` surfaces this as a fallback mark,
    # ranked BELOW apple-touch-icon.
    for node in tree.css("link[rel='icon'], link[rel='shortcut icon']"):
        href = node.attributes.get("href")
        if href:
            add(urljoin(base_url, href), "logo")

    # og:image + og:logo.
    for node in tree.css("meta[property='og:image'], meta[property='og:logo']"):
        content = node.attributes.get("content")
        if content:
            add(urljoin(base_url, content), "image")

    # Images. The ladder (srcset / <picture><source> / CDN width upgrade / bare src) is the
    # SHARED chooser `parse._parse_images` walks — see `imgsrc` for why implementing it twice
    # is the one way to lose every image. Enqueuing every rung multiplies the image fetch
    # count — measured ~3x on stripe.com (50 → 149 downloads), since a srcset-heavy page
    # spends all three rungs and only the first is ever used. Accepted, and bounded by the
    # async fan-out (`net.DEFAULT_CONCURRENCY` = 8) with every byte cap and timeout
    # unchanged. If that ever matters, the fix is a STAGED collector — fan out rung 1 for
    # every image, then a second round for only those whose rung 1 failed — not a shorter
    # ladder.
    for node in tree.css("img"):
        for url in image_source_ladder(node, base_url):
            add(url, "image")

    # CSS background-image: gradients and hero art a brand keeps in stylesheets rather than
    # in markup were never downloaded at all.
    for url in background_image_urls(tree, stylesheets, base_url):
        add(url, "image")

    if not requests:
        return [], []

    # ONE concurrent batch for all fonts + logos + images.
    results = await fetcher.fetch_many(requests)

    downloads: list[Download] = []
    diagnostics: list[dict] = []
    for result in results:
        diagnostics.extend(result.diagnostics)
        if not result.ok or result.body is None:
            continue
        sha = hashlib.sha256(result.body).hexdigest()
        downloads.append(
            Download(
                url=result.url,
                kind=kinds.get(result.url, "image"),
                content_type=result.content_type,
                bytes_b64=base64.b64encode(result.body).decode("ascii"),
                sha256=sha,
            )
        )
    return downloads, diagnostics


def _extract_meta(tree) -> dict:
    meta: dict = {}
    title = tree.css_first("title")
    if title:
        meta["title"] = title.text().strip()
    for node in tree.css("meta[name='description']"):
        meta["description"] = node.attributes.get("content")
        break
    for node in tree.css("meta[property^='og:'], meta[name^='og:']"):
        prop = node.attributes.get("property") or node.attributes.get("name")
        content = node.attributes.get("content")
        if prop and content:
            meta[prop] = content
    for node in tree.css("link[rel='icon'], link[rel='shortcut icon']"):
        href = node.attributes.get("href")
        if href:
            meta["favicon"] = href
            break
    for node in tree.css("link[rel='apple-touch-icon']"):
        href = node.attributes.get("href")
        if href:
            meta["apple_touch_icon"] = href
            break
    return meta
