"""D3 contract tests for Exa webhook verification and one-attempt cursor reads."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from clue_research.adapters.exa_websets import (
    ExaCreateWebhookRequest,
    ExaWebhookEventType,
    ExaWebhookVerificationError,
    ExaWebsetsClient,
    ExaWebsetsRateLimited,
    verify_exa_webhook_signature,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/discovery/exa_websets"


def _signature(secret: str, body: bytes, timestamp: int) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1=obsolete,v1={digest}"


def test_webhook_signature_uses_exact_raw_body_multi_signature_and_freshness() -> None:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    body = b'{"id":"evt_1","object":"event"}'
    header = _signature("webhook-secret", body, int(now.timestamp()))

    verified_at = verify_exa_webhook_signature(
        raw_body=body,
        signature_header=header,
        secret=SecretStr("webhook-secret"),
        now=now,
    )
    assert verified_at == now

    with pytest.raises(ExaWebhookVerificationError, match="invalid"):
        verify_exa_webhook_signature(
            raw_body=body + b" ",
            signature_header=header,
            secret=SecretStr("webhook-secret"),
            now=now,
        )
    with pytest.raises(ExaWebhookVerificationError, match="stale"):
        verify_exa_webhook_signature(
            raw_body=body,
            signature_header=header,
            secret=SecretStr("webhook-secret"),
            now=now + timedelta(minutes=6),
        )


def test_item_and_event_pages_are_typed_and_cursor_parameters_are_exact() -> None:
    async def _run() -> None:
        seen: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/items"):
                body = (_FIXTURES / "items-page-1.json").read_bytes()
            else:
                body = (_FIXTURES / "events-duplicate-out-of-order.json").read_bytes()
            return httpx.Response(200, content=body, request=request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("test-key"), client=http)
        items = await client.list_items("ws_fixture_running", cursor="cursor_before", limit=2)
        events = await client.list_events(cursor="event_cursor", limit=4)
        await http.aclose()

        assert [item.id for item in items.page.data] == [
            "wsi_fixture_northstar",
            "wsi_fixture_lakeside",
        ]
        assert items.page.next_cursor == "cursor_fixture_page_2"
        assert events.page.data[0].webset_id == "ws_fixture_running"
        assert dict(seen[0].url.params) == {"limit": "2", "cursor": "cursor_before"}
        assert dict(seen[1].url.params) == {"limit": "4", "cursor": "event_cursor"}

    asyncio.run(_run())


def test_lifecycle_reads_make_one_attempt_and_expose_retry_after() -> None:
    async def _run() -> None:
        calls = 0

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                429,
                headers={"retry-after": "7"},
                json={"error": "slow down"},
                request=request,
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("test-key"), client=http, lookup_attempts=5)
        with pytest.raises(ExaWebsetsRateLimited) as caught:
            await client.list_items("ws_fixture_running")
        assert calls == 1
        assert caught.value.retry_after_seconds == 7
        await http.aclose()

    asyncio.run(_run())


def test_team_webhook_admin_uses_collection_endpoints_and_one_time_secret() -> None:
    async def _run() -> None:
        seen: list[httpx.Request] = []
        now = "2026-08-03T12:00:00Z"
        webhook = {
            "id": "webhook_fixture",
            "object": "webhook",
            "status": "active",
            "events": ["webset.idle", "webset.item.enriched"],
            "url": "https://api.example.test/v1/webhooks/exa-websets",
            "secret": "one-time-secret",
            "metadata": {"clueEndpoint": "team-websets-v1"},
            "createdAt": now,
            "updatedAt": now,
        }

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "POST":
                return httpx.Response(200, json=webhook, request=request)
            listed = {"data": [{**webhook, "secret": None}], "hasMore": False, "nextCursor": None}
            return httpx.Response(200, json=listed, request=request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("test-key"), client=http)
        request = ExaCreateWebhookRequest(
            url=webhook["url"],
            events=(
                ExaWebhookEventType.WEBSET_IDLE,
                ExaWebhookEventType.ITEM_ENRICHED,
            ),
            metadata={"clueEndpoint": "team-websets-v1"},
        )
        created = await client.create_webhook(request)
        listed = await client.list_webhooks(limit=200)
        await http.aclose()

        assert created.secret is not None
        assert created.secret.get_secret_value() == "one-time-secret"
        assert listed.data[0].secret is None
        assert [item.url.path for item in seen] == [
            "/websets/v0/webhooks",
            "/websets/v0/webhooks",
        ]
        assert json.loads(seen[0].content) == request.model_dump(
            mode="json", by_alias=True, exclude_defaults=True
        )
        assert dict(seen[1].url.params) == {"limit": "200"}

    asyncio.run(_run())


def test_every_answer_is_reported_to_the_spend_layer_and_errors_are_unchanged() -> None:
    """Design 2026-10-31: the client keeps its own transport and error taxonomy, and reports each
    answer so a 402 opens a provider incident."""
    from clue_research.adapters.exa_websets import ExaWebsetsPaymentRequired

    async def _run() -> None:
        observed: list[dict[str, object]] = []

        async def observe(**call: object) -> None:
            observed.append(call)

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error": "payment_required"}, request=request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(
            api_key=SecretStr("test-key"), client=http, lookup_attempts=1, observe=observe
        )
        with pytest.raises(ExaWebsetsPaymentRequired):
            await client.list_items("ws_fixture_running")
        (call,) = observed
        assert call["status"] == 402 and b"payment_required" in call["body"]  # type: ignore[operator]
        assert str(call["operation"]).startswith("research.exa_websets.")
        assert "test-key" not in json.dumps({k: str(v) for k, v in call.items()})
        await http.aclose()

    asyncio.run(_run())


def test_a_failing_observer_never_breaks_the_call() -> None:
    async def _run() -> None:
        async def observe(**_call: object) -> None:
            raise RuntimeError("ledger down")

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [], "hasMore": False, "nextCursor": None}, request=request
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(
            api_key=SecretStr("test-key"), client=http, lookup_attempts=1, observe=observe
        )
        await client.list_items("ws_fixture_running")
        await http.aclose()

    asyncio.run(_run())


def test_a_retried_lookup_reports_only_its_last_answer() -> None:
    """A lookup the client retries reports only the answer it ends on, so retries never count
    toward a rate-limit incident."""

    async def _run() -> None:
        observed: list[int] = []

        async def observe(**call: object) -> None:
            observed.append(int(call["status"]))  # type: ignore[call-overload]

        answers = iter(
            [
                httpx.Response(429, json={"error": "slow down"}),
                httpx.Response(503, json={"error": "busy"}),
                httpx.Response(200, content=(_FIXTURES / "webset-running.json").read_bytes()),
            ]
        )
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(answers)))

        async def no_sleep(_: float) -> None:
            return None

        client = ExaWebsetsClient(
            api_key=SecretStr("test-key"),
            client=http,
            lookup_attempts=3,
            observe=observe,
            sleep=no_sleep,
        )
        await client.get_webset("ws_fixture_running")
        assert observed == [200]
        await http.aclose()

    asyncio.run(_run())
