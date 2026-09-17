"""Fetch discipline for web capture: SSRF guard, size/timeout caps, and a
bounded-concurrency fetcher.

All multi-URL fan-out flows through ``BoundedFetcher.fetch_many`` which runs the
requests concurrently under a shared ``asyncio.Semaphore`` — capture never does a
serial download loop. Every fetched URL is deduped so its bytes are pulled at
most once.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional
from urllib.parse import urlparse

import httpx

from .budget import short_url
from .snapshot import HTML_MAX_BYTES

# Response size caps (bytes) per resource class.
PAGE_MAX_BYTES = HTML_MAX_BYTES
CSS_MAX_BYTES = 5 * 1024 * 1024
FONT_MAX_BYTES = 10 * 1024 * 1024
IMAGE_MAX_BYTES = 15 * 1024 * 1024

REQUEST_TIMEOUT_SECONDS = 15.0
MAX_REDIRECT_HOPS = 5
DEFAULT_CONCURRENCY = 8

# Ports we allow beyond the implicit 80/443 that map to http/https default.
ALLOWED_PORTS = {80, 443, 8080}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 lumen-ingestion/1"
)
_DEFAULT_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Language": "en"}

ResourceKind = Literal["page", "css", "font", "image", "logo", "screenshot"]

_CAP_BY_KIND: dict[str, int] = {
    "page": PAGE_MAX_BYTES,
    "css": CSS_MAX_BYTES,
    "font": FONT_MAX_BYTES,
    "image": IMAGE_MAX_BYTES,
    "logo": IMAGE_MAX_BYTES,
    "screenshot": IMAGE_MAX_BYTES,
}


class CaptureError(Exception):
    """Fatal capture error carrying a LUMI05xx code (e.g. blocked URL)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_complete_html(html: str) -> str:
    """Reject oversize HTML rather than silently dropping its body or footer."""
    if len(html.encode("utf-8")) > HTML_MAX_BYTES:
        raise CaptureError(
            "LUMI0507",
            f"HTML exceeds the {HTML_MAX_BYTES}-byte capture limit; "
            "no partial page was accepted. Capture a smaller source page.",
        )
    return html


@dataclass
class FetchRequest:
    url: str
    kind: ResourceKind = "page"


@dataclass
class FetchResult:
    url: str
    kind: ResourceKind
    ok: bool
    status: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    final_url: str | None = None
    diagnostics: list[dict] = field(default_factory=list)


def _is_blocked_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


async def _resolve_all(host: str, port: int) -> list[str]:
    def _getaddrinfo() -> list[str]:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        return [info[4][0] for info in infos]

    return await asyncio.to_thread(_getaddrinfo)


async def guard_url(url: str) -> str:
    """Validate a URL against SSRF: scheme, userinfo, port, and DNS.

    Resolves every address the host maps to and rejects the whole URL if any
    resolved address is loopback/private/link-local/multicast/reserved. Returns
    the URL unchanged on success; raises ``CaptureError(LUMI0501)`` otherwise.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise CaptureError("LUMI0501", f"blocked url scheme {scheme!r}: {url}")
    if parsed.username or parsed.password:
        raise CaptureError("LUMI0501", f"blocked url with credentials: {url}")
    host = parsed.hostname
    if not host:
        raise CaptureError("LUMI0501", f"blocked url with no host: {url}")

    try:
        port = parsed.port
    except ValueError as error:
        raise CaptureError("LUMI0501", f"blocked url with bad port: {url}") from error
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    if port is not None and port not in ALLOWED_PORTS:
        raise CaptureError("LUMI0501", f"blocked url port {port}: {url}")

    # A bracketed IPv6 or bare IPv4 literal is guarded directly; otherwise DNS.
    literal_host = host.strip("[]")
    try:
        ipaddress.ip_address(literal_host)
        addresses = [literal_host]
    except ValueError:
        try:
            addresses = await _resolve_all(host, effective_port)
        except socket.gaierror as error:
            raise CaptureError(
                "LUMI0501", f"blocked url — dns resolution failed: {url}"
            ) from error

    if not addresses:
        raise CaptureError("LUMI0501", f"blocked url — no addresses: {url}")
    for address in addresses:
        if _is_blocked_ip(address):
            raise CaptureError(
                "LUMI0501", f"blocked url — private/loopback address {address}: {url}"
            )
    return url


class BoundedFetcher:
    """Concurrency-bounded HTTP fetcher over a single ``httpx.AsyncClient``.

    Fan-out through :meth:`fetch_many` runs under a shared semaphore so at most
    ``concurrency`` requests are in flight at once — the whole point of the
    capture path. Individual failures never fail a batch; they surface as
    ``LUMI0503`` diagnostics on the per-item result. Size caps abort a stream
    early (``LUMI0502``). URLs are deduped so bytes are pulled at most once.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cache: dict[str, FetchResult] = {}
        self._diagnostics: list[dict] = []

    @property
    def diagnostics(self) -> list[dict]:
        return self._diagnostics

    async def fetch_page(self, url: str) -> FetchResult:
        """Fetch a page following redirects manually, re-guarding each hop."""
        current = await guard_url(url)
        for _ in range(MAX_REDIRECT_HOPS + 1):
            async with self._semaphore:
                response = await self._client.get(
                    current, headers=_DEFAULT_HEADERS, follow_redirects=False
                )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                current = str(response.url.join(location))
                await guard_url(current)
                continue
            body, capped = _read_capped(response, PAGE_MAX_BYTES)
            if capped:
                raise CaptureError(
                    "LUMI0507",
                    f"HTML response exceeds the {PAGE_MAX_BYTES}-byte capture limit; "
                    "no partial page was accepted. Capture a smaller source page.",
                )
            result = FetchResult(
                url=url,
                kind="page",
                ok=True,
                status=response.status_code,
                content_type=response.headers.get("content-type"),
                body=body,
                final_url=str(response.url),
            )
            return result
        raise CaptureError("LUMI0501", f"blocked url — too many redirects: {url}")

    async def fetch_many(self, requests: Iterable[FetchRequest]) -> list[FetchResult]:
        """Fetch many resources concurrently; failures are per-item, not fatal."""
        unique: list[FetchRequest] = []
        seen: set[str] = set()
        for request in requests:
            if request.url in seen:
                continue
            seen.add(request.url)
            unique.append(request)

        tasks = [self._fetch_one(request) for request in unique]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[FetchResult] = []
        for request, result in zip(unique, results):
            if isinstance(result, BaseException):
                diagnostic = _fetch_failure_diagnostic(
                    request.url, f"{type(result).__name__}: {result}"
                )
                self._diagnostics.append(diagnostic)
                out.append(
                    FetchResult(
                        url=request.url,
                        kind=request.kind,
                        ok=False,
                        diagnostics=[diagnostic],
                    )
                )
            else:
                out.append(result)
        return out

    async def _fetch_one(self, request: FetchRequest) -> FetchResult:
        if request.url in self._cache:
            return self._cache[request.url]
        # SSRF re-guard on every fetched resource (assets can be off-origin).
        await guard_url(request.url)
        cap = _CAP_BY_KIND.get(request.kind, IMAGE_MAX_BYTES)
        async with self._semaphore:
            response = await self._client.get(
                request.url, headers=_DEFAULT_HEADERS, follow_redirects=True
            )
        if response.status_code >= 400:
            diagnostic = _fetch_failure_diagnostic(
                request.url, f"HTTP {response.status_code}"
            )
            self._diagnostics.append(diagnostic)
            result = FetchResult(
                url=request.url,
                kind=request.kind,
                ok=False,
                status=response.status_code,
                diagnostics=[diagnostic],
            )
            self._cache[request.url] = result
            return result

        body, capped = _read_capped(response, cap)
        result = FetchResult(
            url=request.url,
            kind=request.kind,
            ok=True,
            status=response.status_code,
            content_type=response.headers.get("content-type"),
            body=body,
            final_url=str(response.url),
        )
        if capped:
            diagnostic = _size_cap_diagnostic(request.url, cap)
            result.ok = False
            result.body = None
            result.diagnostics.append(diagnostic)
            self._diagnostics.append(diagnostic)
        self._cache[request.url] = result
        return result


def _read_capped(response: httpx.Response, cap: int) -> tuple[bytes, bool]:
    body = response.content
    if len(body) > cap:
        return body[:cap], True
    return body, False


def _size_cap_diagnostic(url: str, cap: int) -> dict:
    return {
        "code": "LUMI0502",
        "severity": "warning",
        "message": f"resource exceeded {cap}-byte cap and was skipped: {short_url(url)}",
        "url": url,
        "reason": f"exceeded the {cap}-byte cap for its resource class",
    }


def _fetch_failure_diagnostic(url: str, reason: str) -> dict:
    """A failed fetch, said once and structurally.

    ``url`` and ``reason`` ride as their own keys (not only inside the message) because
    downstream consumers have to JOIN on them: the evidence builder reports a ``@font-face``
    file that never arrived and must state WHY, and string-parsing a human sentence to find
    that out is how the two drift apart. The MESSAGE quotes a bounded URL — a signed CDN URL
    runs to kilobytes and these diagnostics are persisted on the published kit — while the
    ``url`` key keeps the whole thing, because that is what consumers join on.
    """
    return {
        "code": "LUMI0503",
        "severity": "warning",
        "message": f"fetch failed for {short_url(url)}: {reason}",
        "url": url,
        "reason": reason,
    }
