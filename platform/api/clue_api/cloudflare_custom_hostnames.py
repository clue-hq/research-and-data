"""Cloudflare for SaaS custom hostnames — the three calls the control plane makes (spec §7.7).

The ONLY module that knows Cloudflare's field names. ``httpx`` bearer auth, 10 s timeouts, one
retry on a 5xx or a transport failure, never on a 4xx. Field names follow the v4 API reference
for ``/zones/{zone_id}/custom_hostnames`` and are pinned by
``tests/api/test_cloudflare_custom_hostnames.py``.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from clue_obs import get_logger

log = get_logger("clue_api.cloudflare_custom_hostnames")
_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class CustomHostnameRecord:
    id: str
    status: str
    ssl_status: str | None
    ownership_txt_name: str | None
    ownership_txt_value: str | None
    verification_errors: tuple[str, ...]
    ssl_validation_errors: tuple[str, ...]


class CloudflareError(Exception):
    def __init__(self, message: str, *, status: int | None, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable


def _messages(items: Any) -> tuple[str, ...]:
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("message"), str):
            out.append(item["message"])
        elif isinstance(item, str):
            out.append(item)
    return tuple(out)


def _record(result: Any) -> CustomHostnameRecord:
    if not isinstance(result, dict) or not isinstance(result.get("id"), str):
        raise CloudflareError(
            "Cloudflare returned no custom hostname record", status=None, retryable=False
        )
    # Bound to locals first so ``isinstance`` actually narrows: a check on ``result.get("ssl")``
    # narrows nothing, because the ternary's other arm re-evaluates a fresh call expression.
    raw_ssl = result.get("ssl")
    ssl: dict[str, Any] = raw_ssl if isinstance(raw_ssl, dict) else {}
    raw_ownership = result.get("ownership_verification")
    ownership: dict[str, Any] = raw_ownership if isinstance(raw_ownership, dict) else {}
    ssl_status = ssl.get("status")
    txt_name = ownership.get("name")
    txt_value = ownership.get("value")
    return CustomHostnameRecord(
        id=result["id"],
        status=str(result.get("status") or "pending"),
        ssl_status=str(ssl_status) if isinstance(ssl_status, str) else None,
        ownership_txt_name=txt_name if isinstance(txt_name, str) else None,
        ownership_txt_value=txt_value if isinstance(txt_value, str) else None,
        verification_errors=_messages(result.get("verification_errors")),
        ssl_validation_errors=_messages(ssl.get("validation_errors")),
    )


class CloudflareCustomHostnames:
    def __init__(
        self,
        *,
        zone_id: str,
        api_token: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.cloudflare.com/client/v4",
        observe: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
        # Every answer is reported to the spend layer so a refusal opens a provider incident
        # (design 2026-10-31); the client keeps its own two-attempt retry and error type.
        self._observe = observe
        self._base = f"{base_url.rstrip('/')}/zones/{zone_id}/custom_hostnames"
        self._headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}

    async def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        last: CloudflareError | None = None
        for _attempt in (1, 2):
            started = time.monotonic()
            try:
                response = await self._client.request(
                    method,
                    f"{self._base}{path}",
                    json=json,
                    headers=self._headers,
                    timeout=_TIMEOUT_S,
                )
            except httpx.HTTPError as error:
                last = CloudflareError(
                    f"Cloudflare unreachable: {error}", status=None, retryable=True
                )
                continue
            await self._report(method, response, started)
            if response.status_code >= 500:
                last = CloudflareError(
                    f"Cloudflare {response.status_code}: {response.text[:200]}",
                    status=response.status_code,
                    retryable=True,
                )
                continue
            return response
        assert last is not None
        log.warning(
            "cloudflare.custom_hostnames.failed", method=method, path=path, status=last.status
        )
        raise last

    async def _report(self, method: str, response: httpx.Response, started: float) -> None:
        if self._observe is None:
            return
        try:
            await self._observe(
                operation=f"pages.cloudflare.{method.lower()}_custom_hostname",
                label=f"cloudflare:{method} custom hostname",
                status=response.status_code,
                body=response.content,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception:  # noqa: BLE001 - reporting must never break the call it observes
            return

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:200] or f"HTTP {response.status_code}"
        messages = _messages(body.get("errors")) if isinstance(body, dict) else ()
        return "; ".join(messages) or f"HTTP {response.status_code}"

    async def create(self, hostname: str) -> CustomHostnameRecord:
        response = await self._request(
            "POST", "", json={"hostname": hostname, "ssl": {"method": "http", "type": "dv"}}
        )
        if response.status_code >= 400:
            raise CloudflareError(
                self._error_message(response), status=response.status_code, retryable=False
            )
        return _record(response.json().get("result"))

    async def get(self, custom_hostname_id: str) -> CustomHostnameRecord | None:
        response = await self._request("GET", f"/{custom_hostname_id}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CloudflareError(
                self._error_message(response), status=response.status_code, retryable=False
            )
        return _record(response.json().get("result"))

    async def delete(self, custom_hostname_id: str) -> None:
        response = await self._request("DELETE", f"/{custom_hostname_id}")
        if response.status_code == 404 or response.status_code < 400:
            return
        raise CloudflareError(
            self._error_message(response), status=response.status_code, retryable=False
        )
