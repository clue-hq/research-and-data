"""The Composio REST gateway (CRM integration Task 3), against the v3.1 shapes verified in the
spike (docs/superpowers/specs/crm-integration/composio-api-notes.md)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from clue_api.crm.composio_gateway import (
    ComposioError,
    HttpComposioGateway,
    build_composio_gateway,
    composio_user_id,
)
from clue_config import Secrets, Settings

BASE = "https://backend.composio.dev/api/v3.1"


def _gateway(handler: Any) -> tuple[HttpComposioGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return HttpComposioGateway(api_key="key-1", base_url=BASE, client=client), seen


def test_create_link_posts_the_v31_body_and_parses_the_link() -> None:
    gateway, seen = _gateway(
        lambda _: httpx.Response(
            201,
            json={
                "link_token": "lk_1",
                "redirect_url": "https://connect.composio.dev/link/lk_1",
                "expires_at": "2026-10-20T12:57:30.599Z",
                "connected_account_id": "ca_1",
            },
        )
    )
    link = asyncio.run(
        gateway.create_link(
            auth_config_id="ac_1", user_id="ws_abc", callback_url="http://localhost:3020/cb?r=1"
        )
    )
    request = seen[0]
    assert request.method == "POST"
    assert request.url == f"{BASE}/connected_accounts/link"
    assert request.headers["x-api-key"] == "key-1"
    assert json.loads(request.content) == {
        "auth_config_id": "ac_1",
        "user_id": "ws_abc",
        "callback_url": "http://localhost:3020/cb?r=1",
    }
    assert link.redirect_url == "https://connect.composio.dev/link/lk_1"
    assert link.connected_account_id == "ca_1"
    assert link.expires_at is not None and link.expires_at.year == 2026


def test_get_account_reads_status_and_toolkit() -> None:
    gateway, seen = _gateway(
        lambda _: httpx.Response(
            200, json={"id": "ca_1", "status": "ACTIVE", "toolkit": {"slug": "hubspot"}}
        )
    )
    account = asyncio.run(gateway.get_account("ca_1"))
    assert seen[0].url == f"{BASE}/connected_accounts/ca_1"
    assert (account.id, account.status, account.toolkit) == ("ca_1", "ACTIVE", "hubspot")


def test_search_tools_scopes_to_the_toolkit() -> None:
    gateway, seen = _gateway(
        lambda _: httpx.Response(
            200,
            json={
                "items": [
                    {
                        "slug": "HUBSPOT_SEARCH_DEALS",
                        "description": "Searches deals.",
                        "input_parameters": {"type": "object"},
                        "tags": ["readOnlyHint"],
                    }
                ]
            },
        )
    )
    tools = asyncio.run(gateway.search_tools(toolkit="hubspot", query="search deals", limit=5))
    params = dict(seen[0].url.params)
    assert params == {"toolkit_slug": "hubspot", "query": "search deals", "limit": "5"}
    assert tools[0].slug == "HUBSPOT_SEARCH_DEALS"
    assert tools[0].tags == ("readOnlyHint",)
    assert tools[0].input_schema == {"type": "object"}


def test_execute_always_sends_the_pinned_version() -> None:
    gateway, seen = _gateway(
        lambda _: httpx.Response(
            200, json={"data": {"results": []}, "error": None, "successful": True, "log_id": "l"}
        )
    )
    result = asyncio.run(
        gateway.execute(
            slug="HUBSPOT_SEARCH_DEALS",
            arguments={"limit": 1},
            connected_account_id="ca_1",
            user_id="ws_abc",
            version="20261020_01",
        )
    )
    assert seen[0].url == f"{BASE}/tools/execute/HUBSPOT_SEARCH_DEALS"
    assert json.loads(seen[0].content) == {
        "arguments": {"limit": 1},
        "connected_account_id": "ca_1",
        "user_id": "ws_abc",
        "version": "20261020_01",
    }
    assert result.successful is True and result.data == {"results": []} and result.error is None


def test_a_tool_level_failure_is_a_result_not_an_exception() -> None:
    gateway, _ = _gateway(
        lambda _: httpx.Response(
            200,
            json={
                "data": {"status_code": 400},
                "error": [{"message": "No such column 'Nope'"}],
                "successful": False,
            },
        )
    )
    result = asyncio.run(
        gateway.execute(
            slug="SALESFORCE_RUN_SOQL_QUERY",
            arguments={"query": "SELECT Nope FROM Opportunity"},
            connected_account_id="ca_1",
            user_id="ws_abc",
            version="20261018_00",
        )
    )
    assert result.successful is False
    assert result.error is not None and "No such column 'Nope'" in result.error


EXPIRED_BODY = {
    "error": {
        "message": "Connected account ca_1 for toolkit 'hubspot' is in EXPIRED state",
        "code": 1820,
        "slug": "ActionExecute_ConnectedAccountExpired",
        "status": 410,
    }
}


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (401, {"error": {"message": "bad key"}}, "auth"),
        (403, {"error": {"message": "forbidden"}}, "auth"),
        (404, {"error": {"message": "missing"}}, "not_found"),
        (429, {"error": {"message": "slow down"}}, "rate_limited"),
        (410, EXPIRED_BODY, "connection_expired"),
        (400, {"error": {"message": "bad request"}}, "bad_request"),
        (502, {"error": {"message": "upstream"}}, "unavailable"),
    ],
)
def test_http_errors_map_to_a_kind(status: int, body: dict[str, Any], kind: str) -> None:
    gateway, _ = _gateway(lambda _: httpx.Response(status, json=body))
    with pytest.raises(ComposioError) as raised:
        asyncio.run(gateway.get_account("ca_1"))
    assert raised.value.kind == kind
    assert raised.value.status == status
    assert raised.value.message


def test_a_timeout_is_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    gateway, _ = _gateway(boom)
    with pytest.raises(ComposioError) as raised:
        asyncio.run(gateway.get_account("ca_1"))
    assert raised.value.kind == "unavailable"
    assert raised.value.status is None


def test_build_returns_none_without_a_key_or_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLUE_CRM_INTEGRATION_ENABLED", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    keyed = Secrets(_env_file=None, composio_api_key=SecretStr("k"))  # type: ignore[call-arg]
    blank = Secrets(_env_file=None, composio_api_key=SecretStr("  "))  # type: ignore[call-arg]
    assert build_composio_gateway(settings=settings, secrets=None) is None
    assert build_composio_gateway(settings=settings, secrets=blank) is None
    assert build_composio_gateway(settings=settings, secrets=keyed) is not None
    disabled = settings.model_copy(update={"crm_integration_enabled": False})
    assert build_composio_gateway(settings=disabled, secrets=keyed) is None


def test_the_composio_user_id_is_opaque() -> None:
    assert composio_user_id("abc") == "ws_abc"
