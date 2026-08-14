"""Bounded sitemap parsing and index traversal over already-captured bytes (C2)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urljoin

from clue_research.official_site.url_policy import ConservativeUrlPolicy

SITEMAP_POLICY_VERSION = "official-site-sitemap-v1"
SITEMAP_MIME_TYPES = frozenset(
    {"application/xml", "application/xhtml+xml", "text/xml", "text/plain"}
)


class SitemapPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SitemapParsePolicy:
    version: str = SITEMAP_POLICY_VERSION
    max_bytes: int = 1_000_000
    max_urls: int = 10_000
    max_index_documents: int = 16
    max_index_depth: int = 2
    max_url_chars: int = 4_096

    def __post_init__(self) -> None:
        if self.version != SITEMAP_POLICY_VERSION:
            raise ValueError(f"unsupported sitemap policy version: {self.version}")
        if (
            min(
                self.max_bytes,
                self.max_urls,
                self.max_index_documents,
                self.max_url_chars,
            )
            < 1
        ):
            raise ValueError("sitemap ceilings must be positive")
        if self.max_index_depth < 0:
            raise ValueError("max_index_depth cannot be negative")


DEFAULT_SITEMAP_PARSE_POLICY = SitemapParsePolicy()


@dataclass(frozen=True, slots=True)
class SitemapPayload:
    body: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class SitemapDocument:
    sitemap_url: str
    kind: str
    page_urls: tuple[str, ...]
    child_sitemap_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    discovered_url: str
    sitemap_url: str


@dataclass(frozen=True, slots=True)
class SitemapInventory:
    entries: tuple[SitemapEntry, ...]
    documents_visited: tuple[str, ...]
    refused_documents: tuple[tuple[str, str], ...]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def parse_sitemap(
    payload: SitemapPayload,
    *,
    sitemap_url: str,
    policy: SitemapParsePolicy = DEFAULT_SITEMAP_PARSE_POLICY,
) -> SitemapDocument:
    if len(payload.body) > policy.max_bytes:
        raise SitemapPolicyError("sitemap_size_ceiling_exceeded")
    mime = payload.media_type.split(";", 1)[0].strip().lower()
    if mime not in SITEMAP_MIME_TYPES:
        raise SitemapPolicyError("unsupported_sitemap_media_type")
    lowered_body = payload.body.lower()
    if b"<!doctype" in lowered_body or b"<!entity" in lowered_body:
        raise SitemapPolicyError("sitemap_dtd_or_entity_refused")
    try:
        root = ET.fromstring(payload.body)
    except ET.ParseError as exc:
        raise SitemapPolicyError("malformed_sitemap_xml") from exc
    root_kind = _local_name(root.tag)
    if root_kind not in {"urlset", "sitemapindex"}:
        raise SitemapPolicyError("unsupported_sitemap_root")

    locations: list[str] = []
    expected_item = "url" if root_kind == "urlset" else "sitemap"
    for item in root:
        if _local_name(item.tag) != expected_item:
            continue
        location: str | None = None
        for child in item:
            if _local_name(child.tag) == "loc" and child.text:
                location = child.text.strip()
                break
        if not location:
            continue
        if len(location) > policy.max_url_chars:
            raise SitemapPolicyError("sitemap_url_size_ceiling_exceeded")
        locations.append(urljoin(sitemap_url, location))
        if len(locations) > policy.max_urls:
            raise SitemapPolicyError("sitemap_url_ceiling_exceeded")
    return SitemapDocument(
        sitemap_url=sitemap_url,
        kind=root_kind,
        page_urls=tuple(locations) if root_kind == "urlset" else (),
        child_sitemap_urls=tuple(locations) if root_kind == "sitemapindex" else (),
    )


def build_sitemap_inventory(
    *,
    root_sitemap_urls: tuple[str, ...],
    captured_documents: Mapping[str, SitemapPayload],
    url_policy: ConservativeUrlPolicy,
    policy: SitemapParsePolicy = DEFAULT_SITEMAP_PARSE_POLICY,
) -> SitemapInventory:
    """Traverse captured sitemap indexes with depth/document/URL bounds and loop detection.

    Acquisition remains outside this parser.  Missing documents are explicit refused inventory;
    callers can fetch an admitted child and invoke this function again without hidden recursion.
    """

    stack = [(url, 0) for url in reversed(root_sitemap_urls)]
    visited: list[str] = []
    seen: set[str] = set()
    entries: list[SitemapEntry] = []
    refused: list[tuple[str, str]] = []
    while stack:
        sitemap_url, depth = stack.pop()
        key_decision = url_policy.decide(sitemap_url)
        if not key_decision.admitted or key_decision.fetch_key is None:
            refused.append((sitemap_url, key_decision.reason))
            continue
        sitemap_key = key_decision.fetch_key
        if sitemap_key in seen:
            refused.append((sitemap_url, "sitemap_loop_or_duplicate"))
            continue
        seen.add(sitemap_key)
        if len(visited) >= policy.max_index_documents:
            refused.append((sitemap_url, "sitemap_index_document_ceiling_exceeded"))
            continue
        payload = captured_documents.get(sitemap_url) or captured_documents.get(sitemap_key)
        if payload is None:
            refused.append((sitemap_url, "sitemap_document_not_captured"))
            continue
        document = parse_sitemap(payload, sitemap_url=sitemap_url, policy=policy)
        visited.append(sitemap_url)
        for page_url in document.page_urls:
            if len(entries) >= policy.max_urls:
                raise SitemapPolicyError("sitemap_inventory_url_ceiling_exceeded")
            entries.append(SitemapEntry(page_url, sitemap_url))
        if document.child_sitemap_urls:
            if depth >= policy.max_index_depth:
                refused.extend(
                    (child_url, "sitemap_index_depth_ceiling_exceeded")
                    for child_url in document.child_sitemap_urls
                )
                continue
            stack.extend(
                (child_url, depth + 1) for child_url in reversed(document.child_sitemap_urls)
            )
    return SitemapInventory(tuple(entries), tuple(visited), tuple(refused))


__all__ = [
    "SITEMAP_MIME_TYPES",
    "SITEMAP_POLICY_VERSION",
    "DEFAULT_SITEMAP_PARSE_POLICY",
    "SitemapDocument",
    "SitemapEntry",
    "SitemapInventory",
    "SitemapParsePolicy",
    "SitemapPayload",
    "SitemapPolicyError",
    "build_sitemap_inventory",
    "parse_sitemap",
]
