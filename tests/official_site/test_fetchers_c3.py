"""C3 provider conformance, safety, spend, and static-boundary acceptance suite."""

from __future__ import annotations

import ast
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from clue_research.adapters.firecrawl_page import (
    FIRECRAWL_PROVIDER_KEY,
    FirecrawlPageFetcher,
)
from clue_research.adapters.scrapling_page import (
    SCRAPLING_PROVIDER_KEY,
    ScraplingPageFetcher,
    ScraplingPinnedTransport,
    ScraplingPolicyRefusal,
    ScraplingRedirectLimitExceeded,
    ScraplingResponseTooLarge,
    ScraplingTransportResponse,
)
from clue_research.official_site import (
    CostKind,
    LinkRelation,
    PageFetcher,
    PageFetchRequest,
    RedirectHop,
    RetryClass,
    SpendStatus,
    StaticAddressResolver,
)

REPO = Path(__file__).parents[2]
ADAPTER_ROOT = REPO / "subsystems" / "research" / "clue_research" / "adapters"
FIRECRAWL_ADAPTER_PATH = ADAPTER_ROOT / "firecrawl_page" / "__init__.py"
SCRAPLING_ADAPTER_PATH = ADAPTER_ROOT / "scrapling_page" / "__init__.py"
FIXED_NOW = datetime(2026, 8, 14, 8, 30, tzinfo=UTC)
HTML = b"""<!doctype html>
<html><head><link rel="canonical" href="https://example.com/product"></head>
<body><a href="/pricing">Pricing</a><a href="/about">About us</a></body></html>"""


def _request(**updates: Any) -> PageFetchRequest:
    values: dict[str, Any] = {
        "operation_key": "crawl-run:page:attempt-1",
        "requested_url": "https://example.com/product",
        "allowed_hosts": ("example.com",),
        "timeout_seconds": 1.0,
        "max_response_bytes": 10_000,
        "accepted_mime_types": ("text/html", "application/xhtml+xml", "text/plain"),
        "max_redirects": 3,
        "robots_decision_ref": "robots:example.com:v1:allow",
    }
    values.update(updates)
    return PageFetchRequest(**values)


class FakeFirecrawlClient:
    def __init__(self, result: Any = None, *, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def scrape(self, url: str, **kwargs: Any) -> Any:
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class FakeScraplingTransport:
    def __init__(
        self,
        response: ScraplingTransportResponse | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[PageFetchRequest] = []

    async def fetch(self, request: PageFetchRequest) -> ScraplingTransportResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@dataclass(slots=True)
class FetcherHarness:
    fetcher: PageFetcher
    calls: list[Any]
    provider_key: str


def _firecrawl_document(
    *,
    html: str | None = HTML.decode(),
    url: str = "https://example.com/product",
    source_url: str = "https://example.com/product",
    status: int = 200,
    content_type: str | None = "text/html; charset=utf-8",
    links: list[str] | None = None,
    credits_used: int | float | str | None = 1,
) -> Any:
    metadata = SimpleNamespace(
        url=url,
        source_url=source_url,
        status_code=status,
        content_type=content_type,
        scrape_id="scrape-safe-123",
        credits_used=credits_used,
        cache_state="miss",
    )
    return SimpleNamespace(
        html=html,
        metadata=metadata,
        links=links or ["https://example.com/pricing", "https://example.com/customers/acme"],
    )


def _success_harnesses() -> tuple[FetcherHarness, ...]:
    firecrawl = FakeFirecrawlClient(_firecrawl_document())
    scrapling = FakeScraplingTransport(
        ScraplingTransportResponse(
            final_url="https://example.com/product",
            http_status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=HTML,
        )
    )
    return (
        FetcherHarness(
            fetcher=FirecrawlPageFetcher(client=firecrawl, clock=lambda: FIXED_NOW),
            calls=firecrawl.calls,
            provider_key=FIRECRAWL_PROVIDER_KEY,
        ),
        FetcherHarness(
            fetcher=ScraplingPageFetcher(transport=scrapling, clock=lambda: FIXED_NOW),
            calls=scrapling.calls,
            provider_key=SCRAPLING_PROVIDER_KEY,
        ),
    )


@pytest.mark.parametrize("harness", _success_harnesses(), ids=lambda item: item.provider_key)
def test_common_provider_conformance_success_and_exactly_one_url_invocation(
    harness: FetcherHarness,
) -> None:
    assert isinstance(harness.fetcher, PageFetcher)
    request = _request()
    result = asyncio.run(harness.fetcher.fetch_one(request))

    assert result.provider_key == harness.provider_key
    assert result.requested_url == request.requested_url
    assert result.final_url == request.requested_url
    assert result.http_status == 200
    assert result.content == HTML
    assert result.media_type == "text/html"
    assert result.fetched_at == FIXED_NOW
    assert result.retry_class is RetryClass.SUCCESS
    assert result.provider_status == "ok"
    assert len(harness.calls) == 1
    discovered = {(link.discovered_url, link.relation) for link in result.outgoing_links}
    assert ("/pricing", LinkRelation.ANCHOR) in discovered
    assert ("/about", LinkRelation.ANCHOR) in discovered
    assert ("https://example.com/product", LinkRelation.CANONICAL_HINT) in discovered

    if harness.provider_key == FIRECRAWL_PROVIDER_KEY:
        url, kwargs = harness.calls[0]
        assert url == request.requested_url
        assert kwargs == {
            "formats": ["html", "links"],
            "only_main_content": False,
            "timeout": 1000,
        }
        assert result.spend_status is SpendStatus.SPEND_CONFIRMED
        assert result.cost_kind is CostKind.ESTIMATED
        assert result.cost_cents == Decimal("1")
    else:
        assert harness.calls == [request]
        assert result.spend_status is SpendStatus.NO_SPEND
        assert result.cost_kind is CostKind.NONE
        assert result.cost_cents is None


def test_capability_declarations_are_truthful_and_single_page_only() -> None:
    hosted = FirecrawlPageFetcher(client=FakeFirecrawlClient())
    local = ScraplingPageFetcher(transport=FakeScraplingTransport())
    assert hosted.capabilities.model_dump() == {
        "provider_key": "firecrawl",
        "single_page_only": True,
        "supports_operation_lookup": False,
        "supports_idempotency_key": False,
        "reports_redirect_chain": False,
        "reports_outgoing_links": True,
        "reports_actual_cost": False,
        "reports_provider_receipt": True,
        "proves_no_spend_before_dispatch": False,
    }
    assert local.capabilities.model_dump() == {
        "provider_key": "scrapling",
        "single_page_only": True,
        "supports_operation_lookup": False,
        "supports_idempotency_key": False,
        "reports_redirect_chain": True,
        "reports_outgoing_links": True,
        "reports_actual_cost": False,
        "reports_provider_receipt": False,
        "proves_no_spend_before_dispatch": True,
    }


@pytest.mark.parametrize("kind", ("firecrawl", "scrapling"))
def test_request_host_policy_refuses_before_any_provider_or_transport_call(kind: str) -> None:
    if kind == "firecrawl":
        dependency: Any = FakeFirecrawlClient(_firecrawl_document())
        fetcher: PageFetcher = FirecrawlPageFetcher(client=dependency, clock=lambda: FIXED_NOW)
    else:
        dependency = FakeScraplingTransport()
        fetcher = ScraplingPageFetcher(transport=dependency, clock=lambda: FIXED_NOW)
    result = asyncio.run(
        fetcher.fetch_one(
            _request(
                requested_url="https://evil.test/steal",
                allowed_hosts=("example.com",),
            )
        )
    )
    assert result.retry_class is RetryClass.POLICY_REFUSED
    assert result.spend_status is SpendStatus.NO_SPEND
    assert result.provider_status == "request_policy_refused"
    assert dependency.calls == []


def test_firecrawl_attribute_and_dict_results_preserve_safe_receipt_and_dedupe_links() -> None:
    result_shape = {
        "data": {
            "html": HTML.decode(),
            "links": ["/pricing", "/pricing", "/customers"],
            "metadata": {
                "url": "https://example.com/product",
                "sourceURL": "https://example.com/product",
                "statusCode": "200",
                "contentType": "text/html",
                "scrapeId": "receipt-42",
                "creditsUsed": "2.5",
                "cacheState": "hit",
                "secret": "must-not-survive",
            },
        }
    }
    client = FakeFirecrawlClient(result_shape)
    result = asyncio.run(
        FirecrawlPageFetcher(client=client, clock=lambda: FIXED_NOW).fetch_one(_request())
    )
    assert result.retry_class is RetryClass.SUCCESS
    assert result.provider_request_id == "receipt-42"
    assert result.receipt == {"scrape_id": "receipt-42", "credits_used": 2.5, "cache_state": "hit"}
    assert sum(link.discovered_url == "/pricing" for link in result.outgoing_links) == 1
    assert "secret" not in str(result.receipt)


def test_page_authored_metadata_url_cannot_override_firecrawl_source_url_provenance() -> None:
    client = FakeFirecrawlClient(
        _firecrawl_document(
            url="https://evil.test/page-authored-canonical",
            source_url="https://example.com/product",
        )
    )
    result = asyncio.run(FirecrawlPageFetcher(client=client).fetch_one(_request()))
    assert result.retry_class is RetryClass.SUCCESS
    assert result.final_url == "https://example.com/product"
    assert "evil.test" not in {link.discovered_url for link in result.outgoing_links}


def test_explicit_zero_credit_firecrawl_receipt_is_reported_as_no_spend() -> None:
    result = asyncio.run(
        FirecrawlPageFetcher(
            client=FakeFirecrawlClient(_firecrawl_document(credits_used=0)),
        ).fetch_one(_request())
    )
    assert result.retry_class is RetryClass.SUCCESS
    assert result.receipt is not None and result.receipt["credits_used"] == 0
    assert result.spend_status is SpendStatus.NO_SPEND
    assert result.cost_kind is CostKind.NONE
    assert result.cost_cents is None


@pytest.mark.parametrize(
    ("document", "expected_status", "expected_retry"),
    [
        (_firecrawl_document(html=None), "missing_html_content", RetryClass.PERMANENT),
        (_firecrawl_document(status=404), "origin_http_error", RetryClass.PERMANENT),
        (
            _firecrawl_document(source_url="https://evil.test/product"),
            "external_or_invalid_final_url",
            RetryClass.POLICY_REFUSED,
        ),
        (
            _firecrawl_document(content_type="application/pdf"),
            "unsupported_media_type",
            RetryClass.PERMANENT,
        ),
    ],
)
def test_firecrawl_known_paid_failures_are_never_blindly_retried(
    document: Any, expected_status: str, expected_retry: RetryClass
) -> None:
    result = asyncio.run(
        FirecrawlPageFetcher(
            client=FakeFirecrawlClient(document),
            clock=lambda: FIXED_NOW,
        ).fetch_one(_request())
    )
    assert result.provider_status == expected_status
    assert result.retry_class is expected_retry
    assert result.spend_status is SpendStatus.SPEND_CONFIRMED
    assert result.cost_kind is CostKind.ESTIMATED
    assert result.content is None


def test_firecrawl_oversize_result_is_paid_permanent_failure() -> None:
    result = asyncio.run(
        FirecrawlPageFetcher(
            client=FakeFirecrawlClient(_firecrawl_document(html="123456")),
            clock=lambda: FIXED_NOW,
        ).fetch_one(_request(max_response_bytes=5))
    )
    assert result.provider_status == "response_too_large"
    assert result.retry_class is RetryClass.PERMANENT
    assert result.spend_status is SpendStatus.SPEND_CONFIRMED


def test_paid_provider_exception_and_timeout_are_spend_unknown_not_retried() -> None:
    failed = FakeFirecrawlClient(error=OSError("token and URL must not be persisted"))
    result = asyncio.run(
        FirecrawlPageFetcher(client=failed, clock=lambda: FIXED_NOW).fetch_one(_request())
    )
    assert result.provider_status == "provider_outcome_unknown"
    assert result.retry_class is RetryClass.AMBIGUOUS
    assert result.spend_status is SpendStatus.SPEND_UNKNOWN
    assert result.receipt is None
    assert "token" not in result.model_dump_json()

    class SlowClient:
        calls = 0

        async def scrape(self, url: str, **kwargs: Any) -> Any:
            del url, kwargs
            self.calls += 1
            await asyncio.sleep(0.05)
            return _firecrawl_document()

    slow = SlowClient()
    timed_out = asyncio.run(
        FirecrawlPageFetcher(client=slow, clock=lambda: FIXED_NOW).fetch_one(
            _request(timeout_seconds=0.001)
        )
    )
    assert slow.calls == 1
    assert timed_out.retry_class is RetryClass.AMBIGUOUS
    assert timed_out.spend_status is SpendStatus.SPEND_UNKNOWN


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, RetryClass.PERMANENT),
        (408, RetryClass.RETRYABLE_NO_SPEND),
        (425, RetryClass.RETRYABLE_NO_SPEND),
        (429, RetryClass.RETRYABLE_NO_SPEND),
        (500, RetryClass.RETRYABLE_NO_SPEND),
        (503, RetryClass.RETRYABLE_NO_SPEND),
    ],
)
def test_scrapling_http_retry_classification_is_cost_free(
    status: int, expected: RetryClass
) -> None:
    transport = FakeScraplingTransport(
        ScraplingTransportResponse(
            final_url="https://example.com/product",
            http_status=status,
            headers={"content-type": "text/html"},
            content=HTML,
        )
    )
    result = asyncio.run(
        ScraplingPageFetcher(transport=transport, clock=lambda: FIXED_NOW).fetch_one(_request())
    )
    assert result.retry_class is expected
    assert result.spend_status is SpendStatus.NO_SPEND
    assert result.provider_status == "origin_http_error"
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (
            ScraplingTransportResponse(
                final_url="https://example.com/product",
                http_status=200,
                headers={},
                content=HTML,
            ),
            "unsupported_media_type",
        ),
        (
            ScraplingTransportResponse(
                final_url="https://example.com/product",
                http_status=200,
                headers={"content-type": "image/png"},
                content=b"png",
            ),
            "unsupported_media_type",
        ),
        (
            ScraplingTransportResponse(
                final_url="https://example.com/product",
                http_status=200,
                headers={"content-type": "text/html"},
                content=b"",
            ),
            "missing_content",
        ),
        (
            ScraplingTransportResponse(
                final_url="https://evil.test/product",
                http_status=200,
                headers={"content-type": "text/html"},
                content=HTML,
            ),
            "external_or_invalid_final_url",
        ),
    ],
)
def test_scrapling_response_validation_fails_closed(
    response: ScraplingTransportResponse, expected_status: str
) -> None:
    result = asyncio.run(
        ScraplingPageFetcher(
            transport=FakeScraplingTransport(response),
            clock=lambda: FIXED_NOW,
        ).fetch_one(_request())
    )
    assert result.provider_status == expected_status
    assert result.retry_class in {RetryClass.PERMANENT, RetryClass.POLICY_REFUSED}
    assert result.spend_status is SpendStatus.NO_SPEND


@pytest.mark.parametrize(
    ("error", "expected_retry", "expected_status"),
    [
        (ScraplingPolicyRefusal("private"), RetryClass.POLICY_REFUSED, "transport_policy_refused"),
        (
            ScraplingResponseTooLarge("large"),
            RetryClass.PERMANENT,
            "transport_limit_exceeded",
        ),
        (
            ScraplingRedirectLimitExceeded("redirects"),
            RetryClass.PERMANENT,
            "transport_limit_exceeded",
        ),
        (OSError("temporary"), RetryClass.RETRYABLE_NO_SPEND, "local_transport_error"),
    ],
)
def test_scrapling_transport_failures_have_no_spend_and_typed_retry(
    error: BaseException, expected_retry: RetryClass, expected_status: str
) -> None:
    result = asyncio.run(
        ScraplingPageFetcher(
            transport=FakeScraplingTransport(error=error),
            clock=lambda: FIXED_NOW,
        ).fetch_one(_request())
    )
    assert result.retry_class is expected_retry
    assert result.provider_status == expected_status
    assert result.spend_status is SpendStatus.NO_SPEND
    assert result.cost_kind is CostKind.NONE


def test_scrapling_timeout_is_retryable_no_spend_and_does_not_finish_late() -> None:
    class SlowTransport:
        calls = 0
        completed = False

        async def fetch(self, request: PageFetchRequest) -> ScraplingTransportResponse:
            del request
            self.calls += 1
            await asyncio.sleep(0.05)
            self.completed = True
            raise AssertionError("cancelled work must not continue")

    async def run() -> tuple[Any, SlowTransport]:
        transport = SlowTransport()
        result = await ScraplingPageFetcher(
            transport=transport,
            clock=lambda: FIXED_NOW,
        ).fetch_one(_request(timeout_seconds=0.001))
        await asyncio.sleep(0.01)
        return result, transport

    result, slow = asyncio.run(run())
    assert slow.calls == 1 and not slow.completed
    assert result.retry_class is RetryClass.RETRYABLE_NO_SPEND
    assert result.spend_status is SpendStatus.NO_SPEND


def test_caller_cancellation_propagates_for_both_adapters() -> None:
    async def cancel_firecrawl() -> None:
        client = FakeFirecrawlClient(error=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await FirecrawlPageFetcher(client=client).fetch_one(_request())

    async def cancel_scrapling() -> None:
        transport = FakeScraplingTransport(error=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await ScraplingPageFetcher(transport=transport).fetch_one(_request())

    asyncio.run(cancel_firecrawl())
    asyncio.run(cancel_scrapling())


def test_pinned_scrapling_transport_reresolves_and_pins_every_redirect_hop() -> None:
    resolver = StaticAddressResolver({"example.com": ("93.184.216.34",)})
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def connector(
        url: str,
        approved_addresses: tuple[str, ...],
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Any:
        assert timeout_seconds == 1.0
        assert max_response_bytes == 10_000
        calls.append((url, approved_addresses))
        if url.endswith("/product"):
            return SimpleNamespace(
                url=url,
                http_status=302,
                headers={"Location": "/pricing"},
                content=b"",
            )
        return SimpleNamespace(
            url=url,
            http_status=200,
            headers={"content-type": "text/html"},
            content=HTML,
        )

    result = asyncio.run(
        ScraplingPinnedTransport(resolver=resolver, connector=connector).fetch(_request())
    )
    assert calls == [
        ("https://example.com/product", ("93.184.216.34",)),
        ("https://example.com/pricing", ("93.184.216.34",)),
    ]
    assert result.final_url == "https://example.com/pricing"
    assert result.redirect_chain == (
        RedirectHop(
            from_url="https://example.com/product",
            to_url="https://example.com/pricing",
            http_status=302,
        ),
    )


def test_pinned_scrapling_transport_refuses_private_and_external_redirect_before_connect() -> None:
    calls: list[str] = []

    async def connector(
        url: str,
        approved_addresses: tuple[str, ...],
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Any:
        del approved_addresses, timeout_seconds, max_response_bytes
        calls.append(url)
        return SimpleNamespace(
            url=url,
            http_status=302,
            headers={"location": "https://evil.test/steal"},
            content=b"",
        )

    external = ScraplingPinnedTransport(
        resolver=StaticAddressResolver({"example.com": ("93.184.216.34",)}),
        connector=connector,
    )
    with pytest.raises(ScraplingPolicyRefusal, match="external_redirect"):
        asyncio.run(external.fetch(_request()))
    assert calls == ["https://example.com/product"]

    calls.clear()
    private = ScraplingPinnedTransport(
        resolver=StaticAddressResolver({"example.com": ("127.0.0.1",)}),
        connector=connector,
    )
    with pytest.raises(ScraplingPolicyRefusal, match="non_public_network_target"):
        asyncio.run(private.fetch(_request()))
    assert calls == []


def test_pinned_scrapling_transport_refuses_redirect_loop_and_ceiling() -> None:
    async def loop_connector(
        url: str,
        addresses: tuple[str, ...],
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Any:
        del addresses, timeout_seconds, max_response_bytes
        target = "/product" if url.endswith("/again") else "/again"
        return SimpleNamespace(
            url=url,
            http_status=302,
            headers={"location": target},
            content=b"",
        )

    transport = ScraplingPinnedTransport(
        resolver=StaticAddressResolver({"example.com": ("93.184.216.34",)}),
        connector=loop_connector,
    )
    with pytest.raises(ScraplingPolicyRefusal, match="redirect_loop"):
        asyncio.run(transport.fetch(_request(max_redirects=3)))
    with pytest.raises(ScraplingRedirectLimitExceeded):
        asyncio.run(transport.fetch(_request(max_redirects=0)))


def test_plain_text_scrapling_success_does_not_invent_html_links() -> None:
    transport = FakeScraplingTransport(
        ScraplingTransportResponse(
            final_url="https://example.com/product",
            http_status=200,
            headers={"content-type": "text/plain"},
            content=b"https://example.com/not-an-anchor",
        )
    )
    result = asyncio.run(ScraplingPageFetcher(transport=transport).fetch_one(_request()))
    assert result.retry_class is RetryClass.SUCCESS
    assert result.outgoing_links == ()


def test_scrapling_success_preserves_provider_neutral_redirect_provenance() -> None:
    chain = (
        RedirectHop(
            from_url="https://example.com/product",
            to_url="https://example.com/pricing",
            http_status=301,
        ),
    )
    transport = FakeScraplingTransport(
        ScraplingTransportResponse(
            final_url="https://example.com/pricing",
            http_status=200,
            headers={"content-type": "text/html"},
            content=HTML,
            redirect_chain=chain,
        )
    )
    result = asyncio.run(ScraplingPageFetcher(transport=transport).fetch_one(_request()))
    assert result.retry_class is RetryClass.SUCCESS
    assert result.final_url == "https://example.com/pricing"
    assert result.redirect_chain == chain


def test_scrapling_defense_in_depth_rejects_oversize_return_even_with_injected_transport() -> None:
    transport = FakeScraplingTransport(
        ScraplingTransportResponse(
            final_url="https://example.com/product",
            http_status=200,
            headers={"content-type": "text/html"},
            content=b"123456",
        )
    )
    result = asyncio.run(
        ScraplingPageFetcher(transport=transport).fetch_one(_request(max_response_bytes=5))
    )
    assert result.provider_status == "response_too_large"
    assert result.retry_class is RetryClass.PERMANENT
    assert result.spend_status is SpendStatus.NO_SPEND


def test_adapter_configuration_rejects_unsafe_or_incoherent_construction() -> None:
    with pytest.raises(ValueError, match="estimated_cost_cents"):
        FirecrawlPageFetcher(client=FakeFirecrawlClient(), estimated_cost_cents=Decimal("-1"))
    with pytest.raises(ValueError, match="transport or resolver"):
        ScraplingPageFetcher(
            transport=FakeScraplingTransport(),
            resolver=StaticAddressResolver({}),
        )
    with pytest.raises(RuntimeError, match="requires api_key"):
        FirecrawlPageFetcher()
    with pytest.raises(ValueError, match="not both"):
        FirecrawlPageFetcher(client=FakeFirecrawlClient(), api_key="conflict")


def test_live_firecrawl_builder_disables_hidden_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[dict[str, Any]] = []

    class FakeAsyncFirecrawl:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

        async def scrape(self, url: str, **kwargs: Any) -> Any:
            del url, kwargs
            return _firecrawl_document()

    monkeypatch.setitem(
        sys.modules, "firecrawl", SimpleNamespace(AsyncFirecrawl=FakeAsyncFirecrawl)
    )
    result = asyncio.run(
        FirecrawlPageFetcher(
            api_key="secret-not-in-result",
            api_url="https://provider.test",
        ).fetch_one(_request())
    )
    assert built == [
        {
            "api_key": "secret-not-in-result",
            "api_url": "https://provider.test",
            "max_retries": 0,
        }
    ]
    assert result.retry_class is RetryClass.SUCCESS
    assert "secret-not-in-result" not in result.model_dump_json()


def test_concurrent_invocations_still_issue_exactly_one_single_page_call_each() -> None:
    async def run() -> tuple[int, int]:
        firecrawl = FakeFirecrawlClient(_firecrawl_document())
        scrapling = FakeScraplingTransport(
            ScraplingTransportResponse(
                final_url="https://example.com/product",
                http_status=200,
                headers={"content-type": "text/html"},
                content=HTML,
            )
        )
        hosted = FirecrawlPageFetcher(client=firecrawl)
        local = ScraplingPageFetcher(transport=scrapling)
        results = await asyncio.gather(
            *(hosted.fetch_one(_request(operation_key=f"hosted:{index}")) for index in range(10)),
            *(local.fetch_one(_request(operation_key=f"local:{index}")) for index in range(10)),
        )
        assert all(result.retry_class is RetryClass.SUCCESS for result in results)
        return len(firecrawl.calls), len(scrapling.calls)

    assert asyncio.run(run()) == (10, 10)


def test_locked_provider_sdks_expose_the_exact_single_page_transport_primitives() -> None:
    from curl_cffi import CurlOpt
    from firecrawl import AsyncFirecrawl
    from scrapling.engines.toolbelt.convertor import ResponseFactory

    assert callable(AsyncFirecrawl(api_key="fc-test-only").scrape)
    assert callable(ResponseFactory.from_http_request)
    assert CurlOpt.RESOLVE.name == "RESOLVE"


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def test_provider_sdk_imports_are_lazy_and_confined_to_adapter_modules() -> None:
    package = REPO / "subsystems" / "research" / "clue_research"
    allowed = {
        package / "adapters" / "concrete.py",
        FIRECRAWL_ADAPTER_PATH,
        SCRAPLING_ADAPTER_PATH,
    }
    violations: list[tuple[Path, int, str]] = []
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text())
        parent = _parents(tree)
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.append(node.module.split(".", 1)[0])
            for root in roots:
                if root not in {"firecrawl", "scrapling", "curl_cffi"}:
                    continue
                if path not in allowed:
                    violations.append((path, node.lineno, root))
                    continue
                current: ast.AST | None = node
                while current is not None and not isinstance(
                    current, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    current = parent.get(current)
                if current is None:
                    violations.append((path, node.lineno, f"eager:{root}"))
    assert not violations


def test_firecrawl_adapter_ast_forbids_recursive_provider_operations_and_options() -> None:
    tree = ast.parse(FIRECRAWL_ADAPTER_PATH.read_text())
    forbidden_methods = {
        "crawl",
        "map",
        "start_crawl",
        "async_crawl",
        "batch_scrape",
        "start_batch_scrape",
    }
    forbidden_options = {
        "crawl_entire_domain",
        "crawl_depth",
        "depth",
        "limit",
        "max_depth",
        "sitemap",
    }
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    invoked = {
        node.func.attr
        for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_methods
    }
    used_options = {
        keyword.arg
        for node in calls
        for keyword in node.keywords
        if keyword.arg in forbidden_options
    }
    literal_options = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    scrape_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "scrape"
    ]
    assert not invoked
    assert not used_options
    assert not literal_options.intersection(forbidden_options)
    assert len(scrape_calls) == 1


def test_local_sdk_connector_ast_requires_dns_pinning_no_auto_redirect_and_no_retry() -> None:
    source = SCRAPLING_ADAPTER_PATH.read_text()
    tree = ast.parse(source)
    assert "CurlOpt.RESOLVE" in source
    keyword_constants: dict[str, list[Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg and isinstance(keyword.value, ast.Constant):
                keyword_constants.setdefault(keyword.arg, []).append(keyword.value.value)
    assert False in keyword_constants["allow_redirects"]
    assert False in keyword_constants["trust_env"]
    assert 0 in keyword_constants["retry"]


def test_no_provider_name_controls_coordinator_branching() -> None:
    package = REPO / "subsystems" / "research" / "clue_research" / "official_site"
    violations: list[tuple[str, int]] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            branch: ast.AST | None = None
            if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                branch = node.test
            elif isinstance(node, ast.Match):
                branch = node.subject
            if branch is None:
                continue
            literals = {
                value.value.casefold()
                for value in ast.walk(branch)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            if literals & {"firecrawl", "scrapling"}:
                violations.append((path.name, node.lineno))
    assert not violations
