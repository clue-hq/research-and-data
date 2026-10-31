"""The one place Clue talks to Composio: its REST API v3.1 over ``httpx``.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§9; request and response shapes verified live in ``composio-api-notes.md`` beside it. Composio's
Python SDK is not used (R-3.11): it is synchronous only, pins a pre-release client and pulls in an
LLM provider package, and the repo's convention is to call providers over plain HTTP.

Nothing here retries. A tool call is not idempotent, so retrying is the caller's decision (the
write executor's, in Phase 2); reads surface ``rate_limited`` / ``unavailable`` to the agent.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

import httpx

from clue_config import Secrets, Settings

__all__ = [
    "ComposioError",
    "ComposioErrorKind",
    "ComposioGateway",
    "ConnectLink",
    "ConnectedAccount",
    "CrmProvider",
    "ExecuteResult",
    "HttpComposioGateway",
    "ToolInfo",
    "build_composio_gateway",
    "composio_user_id",
]

CrmProvider = Literal["hubspot", "salesforce"]
ComposioErrorKind = Literal[
    "auth", "not_found", "rate_limited", "connection_expired", "bad_request", "unavailable"
]

#: Composio's error slug for executing on an expired connected account (HTTP 410).
_EXPIRED_SLUG = "ActionExecute_ConnectedAccountExpired"
_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class ConnectLink:
    redirect_url: str
    connected_account_id: str
    expires_at: datetime | None


@dataclass(frozen=True)
class ConnectedAccount:
    id: str
    status: str
    toolkit: str


@dataclass(frozen=True)
class ToolInfo:
    slug: str
    description: str
    input_schema: Mapping[str, Any]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ExecuteResult:
    successful: bool
    data: Any
    error: str | None


class ComposioError(Exception):
    """A Composio call that did not return a usable response."""

    def __init__(self, kind: ComposioErrorKind, status: int | None, message: str) -> None:
        super().__init__(f"composio {kind} ({status}): {message}")
        self.kind: ComposioErrorKind = kind
        self.status = status
        self.message = message


class ComposioGateway(Protocol):
    async def create_link(
        self,
        *,
        auth_config_id: str,
        user_id: str,
        callback_url: str,
        connection_data: Mapping[str, str] | None = None,
    ) -> ConnectLink: ...

    async def get_account(self, connected_account_id: str) -> ConnectedAccount: ...

    async def delete_account(self, connected_account_id: str) -> None: ...

    async def search_tools(
        self, *, toolkit: CrmProvider, query: str, limit: int
    ) -> list[ToolInfo]: ...

    async def execute(
        self,
        *,
        slug: str,
        arguments: Mapping[str, Any],
        connected_account_id: str,
        user_id: str,
        version: str,
    ) -> ExecuteResult: ...


def composio_user_id(workspace_id: str) -> str:
    """The opaque Composio user id for a workspace connection (R-5.2): never an email or a name."""
    return f"ws_{workspace_id}"


class HttpComposioGateway:
    """:class:`ComposioGateway` over Composio's REST API v3.1."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        observe: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._headers = {"x-api-key": api_key}
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
        # Every answer is reported to the spend layer so a refusal opens a provider incident
        # (design 2026-10-31); the gateway keeps its own transport and error kinds.
        self._observe = observe

    async def _report(
        self, method: str, path: str, response: httpx.Response, started: float
    ) -> None:
        if self._observe is None:
            return
        segment = path.strip("/").split("/", 1)[0] or "root"
        # A 4xx on a tool run or a connected account is about one customer's own CRM connection
        # (an expired token, a revoked grant), not Composio refusing Clue — no provider incident.
        # A 402 or 429 is still the account's.
        customer_scoped = (
            path.startswith(("/tools/execute", "/connected_accounts"))
            and 400 <= response.status_code < 500
            and response.status_code not in (402, 429)
        )
        try:
            await self._observe(
                operation=f"crm.composio.{method.lower()}_{segment}",
                label=f"composio:{method} {segment}",
                status=response.status_code,
                body=response.content,
                latency_ms=int((time.monotonic() - started) * 1000),
                classify=not customer_scoped,
            )
        except Exception:  # noqa: BLE001 - reporting must never break the call it observes
            return

    async def create_link(
        self,
        *,
        auth_config_id: str,
        user_id: str,
        callback_url: str,
        connection_data: Mapping[str, str] | None = None,
    ) -> ConnectLink:
        body: dict[str, Any] = {
            "auth_config_id": auth_config_id,
            "user_id": user_id,
            "callback_url": callback_url,
        }
        if connection_data:
            body["connection_data"] = dict(connection_data)
        payload = await self._request("POST", "/connected_accounts/link", json=body)
        expires = payload.get("expires_at")
        return ConnectLink(
            redirect_url=str(payload["redirect_url"]),
            connected_account_id=str(payload["connected_account_id"]),
            expires_at=datetime.fromisoformat(expires.replace("Z", "+00:00")) if expires else None,
        )

    async def get_account(self, connected_account_id: str) -> ConnectedAccount:
        payload = await self._request("GET", f"/connected_accounts/{connected_account_id}")
        toolkit = payload.get("toolkit") or {}
        return ConnectedAccount(
            id=str(payload["id"]),
            status=str(payload.get("status") or ""),
            toolkit=str(toolkit.get("slug") or ""),
        )

    async def delete_account(self, connected_account_id: str) -> None:
        """Delete Clue's grant at Composio (a disconnect, R-15.3). An account Composio no longer
        has is already deleted, so a 404 is success; the body is not read (it may be empty)."""
        started = time.monotonic()
        try:
            response = await self._client.request(
                "DELETE",
                f"{self._base_url}/connected_accounts/{connected_account_id}",
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise ComposioError("unavailable", None, str(exc) or type(exc).__name__) from exc
        await self._report("DELETE", "/connected_accounts", response, started)
        if response.status_code >= 400 and response.status_code != 404:
            raise _http_error(response)

    async def search_tools(self, *, toolkit: CrmProvider, query: str, limit: int) -> list[ToolInfo]:
        payload = await self._request(
            "GET", "/tools", params={"toolkit_slug": toolkit, "query": query, "limit": limit}
        )
        return [
            ToolInfo(
                slug=str(item["slug"]),
                description=str(item.get("description") or ""),
                input_schema=item.get("input_parameters") or {},
                tags=tuple(str(tag) for tag in item.get("tags") or ()),
            )
            for item in payload.get("items") or ()
        ]

    async def execute(
        self,
        *,
        slug: str,
        arguments: Mapping[str, Any],
        connected_account_id: str,
        user_id: str,
        version: str,
    ) -> ExecuteResult:
        payload = await self._request(
            "POST",
            f"/tools/execute/{slug}",
            json={
                "arguments": dict(arguments),
                "connected_account_id": connected_account_id,
                "user_id": user_id,
                "version": version,
            },
        )
        error = payload.get("error")
        return ExecuteResult(
            successful=bool(payload.get("successful")),
            data=payload.get("data"),
            error=None if error in (None, "", []) else _error_text(error),
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = await self._client.request(
                method, f"{self._base_url}{path}", headers=self._headers, **kwargs
            )
        except httpx.HTTPError as exc:  # timeouts, refused connections, protocol errors
            raise ComposioError("unavailable", None, str(exc) or type(exc).__name__) from exc
        await self._report(method, path, response, started)
        if response.status_code >= 400:
            raise _http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ComposioError(
                "unavailable", response.status_code, "response was not JSON"
            ) from exc
        return payload if isinstance(payload, dict) else {"items": payload}


def _http_error(response: httpx.Response) -> ComposioError:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    detail = error if isinstance(error, dict) else {}
    message = str(detail.get("message") or response.text[:500] or f"HTTP {status}")
    if detail.get("slug") == _EXPIRED_SLUG:
        kind: ComposioErrorKind = "connection_expired"
    elif status in (401, 403):
        kind = "auth"
    elif status == 404:
        kind = "not_found"
    elif status == 429:
        kind = "rate_limited"
    elif status >= 500:
        kind = "unavailable"
    else:
        kind = "bad_request"
    return ComposioError(kind, status, message)


def _error_text(error: Any) -> str:
    """Composio returns a tool's own error as a string, or as the CRM's JSON error list."""
    if isinstance(error, str):
        return error
    if isinstance(error, list):
        return "; ".join(
            str(item.get("message", item)) if isinstance(item, dict) else str(item)
            for item in error
        )
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def build_composio_gateway(
    *, settings: Settings, secrets: Secrets | None
) -> ComposioGateway | None:
    """The gateway, or ``None`` when the integration is off or no Composio key is configured."""
    if not settings.crm_integration_enabled or secrets is None or secrets.composio_api_key is None:
        return None
    key = secrets.composio_api_key.get_secret_value().strip()
    if not key:
        return None
    from clue_api.provider_observers import provider_observer

    return HttpComposioGateway(
        api_key=key,
        base_url=settings.composio_base_url,
        observe=provider_observer("composio"),
    )
