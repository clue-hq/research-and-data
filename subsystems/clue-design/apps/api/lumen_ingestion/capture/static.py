"""Tier-1 static capture: async fetch the page, then fan out concurrently to
stylesheets (+ one level of @import) and assets (fonts/logos/images)."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .budget import MAX_ASSET_BYTES, budget_diagnostic
from .candidates import collect_asset_candidates
from .net import BoundedFetcher, FetchRequest, require_complete_html
from .snapshot import Download, SiteSnapshot, Stylesheet
from .stylesheets import collect_ordered_stylesheets


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
    html = require_complete_html(html_bytes.decode("utf-8", errors="replace"))
    diagnostics: list[dict] = list(page.diagnostics)

    tree = HTMLParser(html)

    reporter("Reading your styles…", 0.15)
    stylesheets, css_diagnostics = await _collect_stylesheets(tree, fetcher, final_url)
    diagnostics.extend(css_diagnostics)

    reporter("Collecting your logos…", 0.30)
    reporter("Gathering your visuals…", 0.45)
    downloads, asset_diagnostics = await _collect_assets(tree, fetcher, final_url, stylesheets)
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
    records = []
    base = tree.css_first("base[href]")
    if base is not None:
        base_url = urljoin(base_url, base.attributes["href"])
    for node in tree.css("style, link[rel~=stylesheet]"):
        attrs = node.attributes
        record = {"media": attrs.get("media") or "", "disabled": "disabled" in attrs}
        if node.tag == "style":
            record.update(href=None, text=node.text() or "")
        elif attrs.get("href"):
            record.update(href=urljoin(base_url, attrs["href"]), text=None)
        else:
            continue
        records.append(record)
    return await collect_ordered_stylesheets(records, fetcher, base_url=base_url)


async def _collect_assets(
    tree,
    fetcher: BoundedFetcher,
    base_url: str,
    stylesheets: list[Stylesheet],
) -> tuple[list[Download], list[dict]]:
    """Fetch EVERY asset the page references, in one concurrent batch.

    The enumeration is not done here — it is
    :func:`lumen_ingestion.capture.candidates.collect_asset_candidates`, the single list that
    also feeds every scorer, so the scorer can never rank a URL the fetcher never saw (see
    that module's docstring for the defect this shape exists to close). This function's whole
    job is: fetch that list, keep what fits the byte budget, and say out loud what it dropped.
    """
    harvest = collect_asset_candidates(tree, base_url, stylesheets)
    diagnostics: list[dict] = list(harvest.diagnostics)
    if not harvest.candidates:
        return [], diagnostics

    # ONE concurrent batch for all fonts + logos + images, bounded by
    # `net.DEFAULT_CONCURRENCY` with every per-resource byte cap and timeout unchanged.
    results = await fetcher.fetch_many(
        [FetchRequest(url=c.url, kind=c.kind) for c in harvest.candidates]
    )
    by_url = {candidate.url: candidate for candidate in harvest.candidates}

    downloads: list[Download] = []
    total_bytes = 0
    over_budget: list[str] = []
    for result in results:
        diagnostics.extend(result.diagnostics)
        if not result.ok or result.body is None:
            continue
        # The byte budget can only be spent once the bodies are in hand — nothing tells us an
        # asset's size before we fetch it — so this bounds what the snapshot CARRIES (and
        # therefore stores, ingests and replays), not what was requested. Candidate order is
        # identity-first, so what a full budget costs is the least identity-critical tail.
        if total_bytes + len(result.body) > MAX_ASSET_BYTES:
            over_budget.append(result.url)
            continue
        total_bytes += len(result.body)
        candidate = by_url.get(result.url)
        sha = hashlib.sha256(result.body).hexdigest()
        downloads.append(
            Download(
                url=result.url,
                kind=_download_kind(candidate),
                content_type=result.content_type,
                bytes_b64=base64.b64encode(result.body).decode("ascii"),
                sha256=sha,
                origin=candidate.origin if candidate else None,
                dark_scheme=bool(candidate and candidate.dark_scheme),
            )
        )
    if over_budget:
        diagnostics.append(
            budget_diagnostic(budget="asset bytes", limit=MAX_ASSET_BYTES, dropped=over_budget)
        )
    return downloads, diagnostics


def _download_kind(candidate) -> str:
    """The ``Download.kind`` an origin maps to — the snapshot's own three-way split."""
    if candidate is None:
        return "image"
    if candidate.origin == "video":
        return "video"
    if candidate.origin == "font":
        return "font"
    if candidate.origin == "logo-rung":
        return "logo"
    return "image"


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
