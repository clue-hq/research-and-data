"""Scrapling single-page acquisition boundary for the durable official-site crawl."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from urllib.parse import urljoin, urlsplit

from clue_research.adapters.page_fetcher_common import (
    PageFetcherConfigurationError,
    accepted_media_type,
    extract_links,
    header,
    media_type,
    pre_dispatch_refusal,
    url_is_allowed,
    utc_now,
)
from clue_research.official_site.contracts import (
    CostKind,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    RedirectHop,
    RetryClass,
    SpendStatus,
)
from clue_research.official_site.safety import (
    AddressResolver,
    CrawlSafetyPolicy,
    SystemAddressResolver,
    make_pinned_resolver,
)

SCRAPLING_PROVIDER_KEY = "scrapling"


class ScraplingTransportError(RuntimeError):
    """Base error for the pinned local single-page transport."""


class ScraplingPolicyRefusal(ScraplingTransportError):
    """The local transport refused a target before connecting to it."""


class ScraplingResponseTooLarge(ScraplingTransportError):
    """The response crossed the request's decompressed-byte ceiling."""


class ScraplingRedirectLimitExceeded(ScraplingTransportError):
    """The response required more redirects than the request permits."""


@dataclass(frozen=True, slots=True)
class ScraplingTransportResponse:
    """Provider-local response shape used between the pinned transport and adapter."""

    final_url: str
    http_status: int
    headers: Mapping[str, str]
    content: bytes
    redirect_chain: tuple[RedirectHop, ...] = ()


class ScraplingTransport(Protocol):
    async def fetch(self, request: PageFetchRequest) -> ScraplingTransportResponse: ...


@dataclass(frozen=True, slots=True)
class _HttpHopResponse:
    url: str
    http_status: int
    headers: Mapping[str, str]
    content: bytes


class _ScraplingHopConnector(Protocol):
    def __call__(
        self,
        url: str,
        approved_addresses: tuple[str, ...],
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Awaitable[_HttpHopResponse]: ...


def _status_retryable_without_spend(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status <= 599


class _SdkScraplingHopConnector:
    """One curl-backed Scrapling response, pinned to C2-approved DNS answers."""

    def __init__(self) -> None:
        try:
            from curl_cffi import CurlOpt
            from curl_cffi.requests import AsyncSession
            from scrapling.engines.toolbelt.convertor import ResponseFactory
        except ImportError as exc:  # pragma: no cover - locked runtime includes both packages
            raise PageFetcherConfigurationError(
                "scrapling[fetchers] and its curl transport are required"
            ) from exc
        self._resolve_option = CurlOpt.RESOLVE
        self._session_type = AsyncSession
        self._response_factory = ResponseFactory

    async def __call__(
        self,
        url: str,
        approved_addresses: tuple[str, ...],
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> _HttpHopResponse:

        parts = urlsplit(url)
        host = parts.hostname
        if host is None:
            raise ScraplingPolicyRefusal("missing_host")
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        resolve_entries = [
            f"{host}:{port}:{f'[{address}]' if ':' in address else address}"
            for address in approved_addresses
        ]
        body = bytearray()

        def receive(chunk: bytes) -> None:
            if len(body) + len(chunk) > max_response_bytes:
                raise ScraplingResponseTooLarge("decompressed_response_too_large")
            body.extend(chunk)

        async with self._session_type(
            curl_options={self._resolve_option: resolve_entries},
            retry=0,
            trust_env=False,
        ) as session:
            response = await session.get(
                url,
                timeout=timeout_seconds,
                allow_redirects=False,
                impersonate="chrome",
                content_callback=receive,
            )
        response.content = bytes(body)
        page = self._response_factory.from_http_request(
            response,
            {},
            meta={"connect_address_pinned": True},
        )
        return _HttpHopResponse(
            url=str(page.url),
            http_status=int(page.status),
            headers={str(key): str(value) for key, value in page.headers.items()},
            content=page.body,
        )


class ScraplingPinnedTransport:
    """Local single-page transport with manual, re-resolved, host-pinned redirects."""

    def __init__(
        self,
        *,
        resolver: AddressResolver | None = None,
        connector: _ScraplingHopConnector | None = None,
    ) -> None:
        self._resolver = resolver or SystemAddressResolver()
        self._connector = connector or _SdkScraplingHopConnector()

    async def fetch(self, request: PageFetchRequest) -> ScraplingTransportResponse:
        current = request.requested_url
        redirects: list[RedirectHop] = []
        seen = {current}
        safety = CrawlSafetyPolicy(
            dns_timeout_seconds=min(2.0, request.timeout_seconds),
            max_redirects=request.max_redirects,
            max_response_bytes=request.max_response_bytes,
            accepted_mime_types=frozenset(request.accepted_mime_types),
        )

        async def connector(url: str, addresses: tuple[str, ...]) -> object:
            return await self._connector(
                url,
                addresses,
                timeout_seconds=request.timeout_seconds,
                max_response_bytes=request.max_response_bytes,
            )

        connect = make_pinned_resolver(self._resolver, connector, safety=safety)
        while True:
            if not url_is_allowed(current, request):
                raise ScraplingPolicyRefusal("external_or_invalid_target")
            try:
                hop = cast(_HttpHopResponse, await connect(current))
            except ScraplingTransportError:
                raise
            except ValueError as exc:
                raise ScraplingPolicyRefusal(str(exc) or "target_refused") from exc
            location = header(hop.headers, "location")
            if hop.http_status not in {301, 302, 303, 307, 308} or not location:
                return ScraplingTransportResponse(
                    final_url=hop.url,
                    http_status=hop.http_status,
                    headers=hop.headers,
                    content=hop.content,
                    redirect_chain=tuple(redirects),
                )
            if len(redirects) >= request.max_redirects:
                raise ScraplingRedirectLimitExceeded("redirect_ceiling_exceeded")
            target = urljoin(current, location)
            if not url_is_allowed(target, request):
                raise ScraplingPolicyRefusal("external_redirect")
            if target in seen:
                raise ScraplingPolicyRefusal("redirect_loop")
            redirects.append(
                RedirectHop(from_url=current, to_url=target, http_status=hop.http_status)
            )
            seen.add(target)
            current = target


class ScraplingPageFetcher:
    """Credit-free local Scrapling adapter for one approved URL acquisition."""

    capabilities = PageFetcherCapabilities(
        provider_key=SCRAPLING_PROVIDER_KEY,
        supports_operation_lookup=False,
        supports_idempotency_key=False,
        reports_redirect_chain=True,
        reports_outgoing_links=True,
        reports_actual_cost=False,
        reports_provider_receipt=False,
        proves_no_spend_before_dispatch=True,
    )

    def __init__(
        self,
        *,
        transport: ScraplingTransport | None = None,
        resolver: AddressResolver | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if transport is not None and resolver is not None:
            raise ValueError("pass transport or resolver, not both")
        self._transport = transport or ScraplingPinnedTransport(resolver=resolver)
        self._clock = clock

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        if not url_is_allowed(request.requested_url, request):
            return pre_dispatch_refusal(
                provider_key=self.capabilities.provider_key,
                request=request,
                clock=self._clock,
            )
        try:
            async with asyncio.timeout(request.timeout_seconds):
                response = await self._transport.fetch(request)
        except asyncio.CancelledError:
            raise
        except ScraplingPolicyRefusal:
            return self._failure(request, "transport_policy_refused", RetryClass.POLICY_REFUSED)
        except (ScraplingResponseTooLarge, ScraplingRedirectLimitExceeded):
            return self._failure(request, "transport_limit_exceeded", RetryClass.PERMANENT)
        except Exception:
            return self._failure(
                request,
                "local_transport_error",
                RetryClass.RETRYABLE_NO_SPEND,
            )

        if not url_is_allowed(response.final_url, request):
            return self._failure(
                request,
                "external_or_invalid_final_url",
                RetryClass.POLICY_REFUSED,
                http_status=response.http_status,
            )
        if not 200 <= response.http_status <= 299:
            retry = (
                RetryClass.RETRYABLE_NO_SPEND
                if _status_retryable_without_spend(response.http_status)
                else RetryClass.PERMANENT
            )
            return self._failure(
                request,
                "origin_http_error",
                retry,
                http_status=response.http_status,
            )
        result_media_type = media_type(header(response.headers, "content-type"))
        if not response.content:
            return self._failure(
                request,
                "missing_content",
                RetryClass.PERMANENT,
                http_status=response.http_status,
            )
        if len(response.content) > request.max_response_bytes:
            return self._failure(
                request,
                "response_too_large",
                RetryClass.PERMANENT,
                http_status=response.http_status,
            )
        if not accepted_media_type(result_media_type, request):
            return self._failure(
                request,
                "unsupported_media_type",
                RetryClass.PERMANENT,
                http_status=response.http_status,
            )
        assert result_media_type is not None
        outgoing = (
            extract_links(response.content)
            if result_media_type in {"text/html", "application/xhtml+xml"}
            else ()
        )
        return PageFetchResult(
            provider_key=self.capabilities.provider_key,
            requested_url=request.requested_url,
            final_url=response.final_url,
            redirect_chain=response.redirect_chain,
            provider_status="ok",
            http_status=response.http_status,
            content=response.content,
            media_type=result_media_type,
            outgoing_links=outgoing,
            fetched_at=self._clock(),
            cost_kind=CostKind.NONE,
            spend_status=SpendStatus.NO_SPEND,
            retry_class=RetryClass.SUCCESS,
        )

    def _failure(
        self,
        request: PageFetchRequest,
        status: str,
        retry_class: RetryClass,
        *,
        http_status: int | None = None,
    ) -> PageFetchResult:
        return PageFetchResult(
            provider_key=self.capabilities.provider_key,
            requested_url=request.requested_url,
            provider_status=status,
            http_status=http_status,
            fetched_at=self._clock(),
            cost_kind=CostKind.NONE,
            spend_status=SpendStatus.NO_SPEND,
            retry_class=retry_class,
        )


__all__ = [
    "SCRAPLING_PROVIDER_KEY",
    "ScraplingPageFetcher",
    "ScraplingPinnedTransport",
    "ScraplingPolicyRefusal",
    "ScraplingRedirectLimitExceeded",
    "ScraplingResponseTooLarge",
    "ScraplingTransport",
    "ScraplingTransportError",
    "ScraplingTransportResponse",
]
