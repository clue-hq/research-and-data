"""D2 contract tests for the typed Exa Websets v0 transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from clue_research.adapters.exa_websets import (
    ExaCreateCriterion,
    ExaCreateSearch,
    ExaCreateWebsetRequest,
    ExaWebsetEntity,
    ExaWebsetEntityType,
    ExaWebsetsClient,
    ExaWebsetsIndeterminateDispatch,
    ExaWebsetsRateLimited,
    ExaWebsetsTransientError,
)


def _request() -> ExaCreateWebsetRequest:
    return ExaCreateWebsetRequest(
        search=ExaCreateSearch(
            query="Independent neurosurgery practices in the United States",
            count=2,
            entity=ExaWebsetEntity(type=ExaWebsetEntityType.COMPANY),
            criteria=(ExaCreateCriterion(description="Is an independent specialty practice"),),
        ),
        external_id="clue-" + "a" * 48,
        metadata={"clueFingerprint": "a" * 64},
    )


def _response_payload(request: ExaCreateWebsetRequest) -> dict[str, object]:
    now = "2026-08-02T12:00:00Z"
    return {
        "id": "webset_test_d2",
        "object": "webset",
        "status": "running",
        "externalId": request.external_id,
        "title": "Independent neurosurgery practices",
        "searches": [
            {
                "id": "search_test_d2",
                "object": "webset_search",
                "websetId": "webset_test_d2",
                "status": "running",
                "query": request.search.query,
                "entity": {"type": "company"},
                "criteria": [
                    {"description": item.description, "successRate": 0}
                    for item in request.search.criteria
                ],
                "count": request.search.count,
                "maxPeoplePerCompany": None,
                "behavior": "override",
                "exclude": [],
                "scope": [],
                "progress": {"found": 0, "analyzed": 0, "completion": 0, "timeLeft": None},
                "recall": None,
                "canceledAt": None,
                "canceledReason": None,
                "createdAt": now,
                "updatedAt": now,
            }
        ],
        "imports": [],
        "enrichments": [],
        "monitors": [],
        "excludes": [],
        "metadata": request.metadata,
        "dashboardUrl": "https://websets.exa.ai/websets/webset_test_d2",
        "createdAt": now,
        "updatedAt": now,
    }


def test_request_bytes_are_stable_camel_case_and_contain_no_transport_secret() -> None:
    request = _request()
    first = request.canonical_bytes()
    second = ExaCreateWebsetRequest.model_validate(request.model_dump()).canonical_bytes()
    assert first == second
    payload = json.loads(first)
    assert payload["externalId"] == request.external_id
    assert payload["search"]["count"] == 2
    assert payload["search"]["entity"] == {"type": "company"}
    assert "behavior" not in payload["search"]
    assert "api_key" not in first.decode().lower()
    assert "x-api-key" not in first.decode().lower()


def test_create_parses_pinned_response_and_sends_one_secret_header() -> None:
    async def _run() -> None:
        request = _request()
        seen: list[httpx.Request] = []

        def respond(http_request: httpx.Request) -> httpx.Response:
            seen.append(http_request)
            return httpx.Response(
                201,
                headers={"x-request-id": "req_test_d2"},
                json=_response_payload(request),
                request=http_request,
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("test-secret"), client=http)
        exchange = await client.create_webset(request)
        await http.aclose()

        assert len(seen) == 1
        assert seen[0].headers["x-api-key"] == "test-secret"
        assert seen[0].content == request.canonical_bytes()
        assert exchange.request_id == "req_test_d2"
        assert exchange.webset.id == "webset_test_d2"
        assert exchange.webset.searches[0].count == 2

    asyncio.run(_run())


def test_create_never_retries_transient_or_indeterminate_outcomes() -> None:
    async def _five_hundred() -> None:
        calls = 0

        def respond(http_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                503,
                json={
                    "requestId": "req_503",
                    "error": "provider-body-marker",
                    "tag": "server_error",
                },
                request=http_request,
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("test-secret"), client=http)
        with pytest.raises(ExaWebsetsTransientError) as caught:
            await client.create_webset(_request())
        assert calls == 1
        assert caught.value.dispatch_uncertain is True
        assert "provider-body-marker" not in str(caught.value)
        assert "test-secret" not in str(caught.value)
        await http.aclose()

    async def _read_timeout() -> None:
        calls = 0

        def respond(http_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("secret must never escape", request=http_request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("test-secret"), client=http)
        with pytest.raises(ExaWebsetsIndeterminateDispatch) as caught:
            await client.create_webset(_request())
        assert calls == 1
        assert "secret must never escape" not in str(caught.value)
        await http.aclose()

    asyncio.run(_five_hundred())
    asyncio.run(_read_timeout())


def test_lookup_retries_rate_limit_but_returns_the_typed_webset() -> None:
    async def _run() -> None:
        request = _request()
        calls = 0
        sleeps: list[float] = []

        def respond(http_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429,
                    headers={"retry-after": "0.25"},
                    json={"error": "slow down"},
                    request=http_request,
                )
            return httpx.Response(200, json=_response_payload(request), request=http_request)

        async def sleep(delay: float) -> None:
            sleeps.append(delay)

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(
            api_key=SecretStr("test-secret"),
            client=http,
            lookup_attempts=2,
            sleep=sleep,
        )
        exchange = await client.get_webset(request.external_id)
        assert exchange.webset.external_id == request.external_id
        assert calls == 2
        assert sleeps == [0.25]
        await http.aclose()

    asyncio.run(_run())


def test_lookup_exhaustion_preserves_rate_limit_taxonomy() -> None:
    async def _run() -> None:
        def respond(http_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "slow down"}, request=http_request)

        async def no_sleep(_: float) -> None:
            return None

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(
            api_key=SecretStr("test-secret"),
            client=http,
            lookup_attempts=2,
            sleep=no_sleep,
        )
        with pytest.raises(ExaWebsetsRateLimited):
            await client.get_webset(_request().external_id)
        await http.aclose()

    asyncio.run(_run())
