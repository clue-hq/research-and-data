"""Shared provider-neutral helpers for C3 single-page adapter packages."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit

from clue_research.official_site.contracts import (
    CostKind,
    LinkObservation,
    LinkRelation,
    PageFetchRequest,
    PageFetchResult,
    RetryClass,
    SpendStatus,
)
from clue_research.official_site.discovery import extract_html_links


class PageFetcherConfigurationError(RuntimeError):
    """The selected provider adapter cannot be constructed safely."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalized_host(value: str) -> str | None:
    host = urlsplit(value).hostname
    if host is None:
        return None
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None


def allowed_hosts(request: PageFetchRequest) -> frozenset[str]:
    normalized = {normalized_host(f"https://{host}") for host in request.allowed_hosts}
    return frozenset(host for host in normalized if host is not None)


def url_is_allowed(url: str, request: PageFetchRequest) -> bool:
    parts = urlsplit(url)
    return parts.scheme.lower() in {"http", "https"} and normalized_host(url) in allowed_hosts(
        request
    )


def media_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.split(";", 1)[0].strip().lower()
    return normalized or None


def accepted_media_type(value: str | None, request: PageFetchRequest) -> bool:
    normalized = media_type(value)
    accepted = {media_type(candidate) for candidate in request.accepted_mime_types}
    return normalized is not None and normalized in accepted


def dedupe_links(links: Sequence[LinkObservation]) -> tuple[LinkObservation, ...]:
    retained: list[LinkObservation] = []
    seen: set[tuple[str, LinkRelation]] = set()
    for link in links:
        key = (link.discovered_url, link.relation)
        if key in seen:
            continue
        seen.add(key)
        retained.append(link)
    return tuple(retained)


def extract_links(
    content: bytes,
    *,
    provider_links: Sequence[object] = (),
) -> tuple[LinkObservation, ...]:
    extracted = extract_html_links(content)
    supplied = tuple(
        LinkObservation(discovered_url=value)
        for value in provider_links
        if isinstance(value, str) and value.strip()
    )
    return dedupe_links((*extracted.links, *extracted.canonical_hints, *supplied))


def pre_dispatch_refusal(
    *, provider_key: str, request: PageFetchRequest, clock: Callable[[], datetime]
) -> PageFetchResult:
    return PageFetchResult(
        provider_key=provider_key,
        requested_url=request.requested_url,
        provider_status="request_policy_refused",
        fetched_at=clock(),
        cost_kind=CostKind.NONE,
        spend_status=SpendStatus.NO_SPEND,
        retry_class=RetryClass.POLICY_REFUSED,
    )


def header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == target:
            return str(value)
    return None


__all__ = [
    "PageFetcherConfigurationError",
    "accepted_media_type",
    "allowed_hosts",
    "dedupe_links",
    "extract_links",
    "header",
    "media_type",
    "normalized_host",
    "pre_dispatch_refusal",
    "url_is_allowed",
    "utc_now",
]
