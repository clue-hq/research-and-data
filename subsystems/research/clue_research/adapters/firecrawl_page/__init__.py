"""Firecrawl single-page acquisition boundary for the durable official-site crawl."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from pydantic import JsonValue

from clue_research.adapters.page_fetcher_common import (
    PageFetcherConfigurationError,
    accepted_media_type,
    extract_links,
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
    RetryClass,
    SpendStatus,
)

FIRECRAWL_PROVIDER_KEY = "firecrawl"


class _AsyncFirecrawlClient(Protocol):
    def scrape(self, url: str, **kwargs: Any) -> Awaitable[Any]: ...


def _lookup(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        result = getattr(value, name, None)
        if result is not None:
            return result
    return None


def _document(value: Any) -> Any:
    data = _lookup(value, "data")
    return data if data is not None else value


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _receipt_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


class FirecrawlPageFetcher:
    """Hosted Firecrawl ``scrape`` adapter restricted to one approved URL per invocation."""

    capabilities = PageFetcherCapabilities(
        provider_key=FIRECRAWL_PROVIDER_KEY,
        supports_operation_lookup=False,
        supports_idempotency_key=False,
        reports_redirect_chain=False,
        reports_outgoing_links=True,
        reports_actual_cost=False,
        reports_provider_receipt=True,
        proves_no_spend_before_dispatch=False,
    )

    def __init__(
        self,
        *,
        client: _AsyncFirecrawlClient | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        estimated_cost_cents: Decimal = Decimal("1"),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if estimated_cost_cents < 0:
            raise ValueError("estimated_cost_cents cannot be negative")
        if client is not None and (api_key is not None or api_url is not None):
            raise ValueError("pass an injected client or Firecrawl connection settings, not both")
        if client is None and not api_key:
            raise PageFetcherConfigurationError(
                "FirecrawlPageFetcher requires api_key or an injected async client"
            )
        self._estimated_cost_cents = estimated_cost_cents
        self._clock = clock
        self._client = client or self._build_client(api_key=api_key or "", api_url=api_url)

    @staticmethod
    def _build_client(*, api_key: str, api_url: str | None) -> _AsyncFirecrawlClient:
        try:
            from firecrawl import AsyncFirecrawl
        except ImportError as exc:  # pragma: no cover - locked runtime includes the SDK
            raise PageFetcherConfigurationError("firecrawl-py is not installed") from exc
        # The durable attempt ledger, not an SDK-local loop, owns every retry decision. A hidden
        # hosted retry would erase the one-dispatch/one-spend boundary C4 must recover.
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 0}
        if api_url is not None:
            kwargs["api_url"] = api_url
        return cast(_AsyncFirecrawlClient, AsyncFirecrawl(**kwargs))

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        if not url_is_allowed(request.requested_url, request):
            return pre_dispatch_refusal(
                provider_key=self.capabilities.provider_key,
                request=request,
                clock=self._clock,
            )
        try:
            async with asyncio.timeout(request.timeout_seconds):
                raw_result = await self._client.scrape(
                    request.requested_url,
                    formats=["html", "links"],
                    only_main_content=False,
                    timeout=max(1, int(request.timeout_seconds * 1000)),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Once the paid call has been handed to the SDK, a timeout/transport failure cannot
            # prove whether the provider completed and charged it. Recovery must reconcile it.
            return PageFetchResult(
                provider_key=self.capabilities.provider_key,
                requested_url=request.requested_url,
                provider_status="provider_outcome_unknown",
                fetched_at=self._clock(),
                cost_kind=CostKind.NONE,
                spend_status=SpendStatus.SPEND_UNKNOWN,
                retry_class=RetryClass.AMBIGUOUS,
            )
        return self._map_result(request, raw_result)

    def _map_result(self, request: PageFetchRequest, raw_result: Any) -> PageFetchResult:
        document = _document(raw_result)
        metadata = _lookup(document, "metadata") or {}
        request_id_value = _lookup(metadata, "scrape_id", "scrapeId")
        provider_request_id = str(request_id_value) if request_id_value not in (None, "") else None
        # ``sourceURL`` is Firecrawl's acquisition URL. The generic ``url`` metadata field may be
        # page-authored (for example OpenGraph/canonical metadata), so it cannot lead final-URL
        # provenance or silently turn a canonical hint into redirect authority.
        final_value = _lookup(metadata, "source_url", "sourceURL", "url")
        final_url = str(final_value) if final_value else request.requested_url
        http_status = _safe_int(_lookup(metadata, "status_code", "statusCode"))
        html = _lookup(document, "html", "raw_html", "rawHtml")
        content = html.encode("utf-8") if isinstance(html, str) else None
        reported_media = media_type(
            cast(str | None, _lookup(metadata, "content_type", "contentType"))
        )
        result_media_type = reported_media or ("text/html" if content is not None else None)
        receipt: dict[str, JsonValue] = {}
        if provider_request_id is not None:
            receipt["scrape_id"] = provider_request_id
        credits = _receipt_number(_lookup(metadata, "credits_used", "creditsUsed"))
        if credits is not None:
            receipt["credits_used"] = credits
        cache_state = _lookup(metadata, "cache_state", "cacheState")
        if isinstance(cache_state, str) and cache_state:
            receipt["cache_state"] = cache_state
        if credits == 0:
            cost_cents: Decimal | None = None
            cost_kind = CostKind.NONE
            spend_status = SpendStatus.NO_SPEND
        else:
            # Credits are not currency. Until C4 has a versioned credit-to-cents policy, retain
            # the configured monetary estimate instead of mislabelling a credit count as actual.
            cost_cents = self._estimated_cost_cents
            cost_kind = CostKind.ESTIMATED
            spend_status = SpendStatus.SPEND_CONFIRMED

        failure_status: str | None = None
        if not url_is_allowed(final_url, request):
            failure_status = "external_or_invalid_final_url"
        elif http_status is not None and not 200 <= http_status <= 299:
            failure_status = "origin_http_error"
        elif content is None or not content:
            failure_status = "missing_html_content"
        elif len(content) > request.max_response_bytes:
            failure_status = "response_too_large"
        elif not accepted_media_type(result_media_type, request):
            failure_status = "unsupported_media_type"

        if failure_status is not None:
            retry = (
                RetryClass.POLICY_REFUSED
                if failure_status == "external_or_invalid_final_url"
                else RetryClass.PERMANENT
            )
            return PageFetchResult(
                provider_key=self.capabilities.provider_key,
                provider_request_id=provider_request_id,
                requested_url=request.requested_url,
                provider_status=failure_status,
                http_status=http_status,
                fetched_at=self._clock(),
                cost_cents=cost_cents,
                cost_kind=cost_kind,
                spend_status=spend_status,
                retry_class=retry,
                receipt=receipt or None,
            )

        assert content is not None and result_media_type is not None
        provider_links = _lookup(document, "links")
        links = (
            provider_links
            if isinstance(provider_links, Sequence) and not isinstance(provider_links, (str, bytes))
            else ()
        )
        return PageFetchResult(
            provider_key=self.capabilities.provider_key,
            provider_request_id=provider_request_id,
            requested_url=request.requested_url,
            final_url=final_url,
            provider_status="ok",
            http_status=http_status,
            content=content,
            media_type=result_media_type,
            outgoing_links=extract_links(content, provider_links=links),
            fetched_at=self._clock(),
            cost_cents=cost_cents,
            cost_kind=cost_kind,
            spend_status=spend_status,
            retry_class=RetryClass.SUCCESS,
            receipt=receipt or None,
        )


__all__ = ["FIRECRAWL_PROVIDER_KEY", "FirecrawlPageFetcher"]
