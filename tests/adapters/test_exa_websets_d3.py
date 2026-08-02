"""D3 contract tests for Exa webhook verification and one-attempt cursor reads."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from clue_research.adapters.exa_websets import (
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
