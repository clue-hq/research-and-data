"""An HTTP client that fetches with a real Chrome TLS/HTTP fingerprint.

Cloudflare-walled sites score the TLS handshake and the HTTP/2 frame order, not the
User-Agent string, so the capture path's plain httpx client is refused (openai.com answers
a 403 challenge page) however browser-like our headers look. `curl_cffi` with
`impersonate="chrome"` replays a real Chrome handshake and gets the page. It is the engine
underneath scrapling's plain `Fetcher`, and the same call the platform's Stage-0 page
fetcher already makes, so the import rides on the `scrapling` dependency already declared
in `apps/api/pyproject.toml` — nothing new was added for it.

FOUNDER DECISION (2026-09-02): the logo ladder fetches this way by default, behind
`LUMEN_LADDER_IMPERSONATE_CHROME` (`0` restores plain httpx). Only the LADDER uses this
client; the brand-kit ingestion capture (`capture/evidence_builder.py`) keeps httpx.

`ImpersonatingClient` is duck-compatible with the slice of `httpx.AsyncClient` that
`BoundedFetcher` touches, so the SSRF guard, the manual redirect re-guard and the size
caps all keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .net import MAX_REDIRECT_HOPS


@dataclass(frozen=True)
class ImpersonatedResponse:
    """The slice of an `httpx.Response` that `BoundedFetcher` reads."""

    status_code: int
    headers: Mapping[str, str]
    url: httpx.URL
    content: bytes

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400 and "location" in self.headers


class ImpersonatingClient:
    """An async HTTP client that presents a real Chrome TLS/HTTP2 fingerprint (curl_cffi
    `impersonate="chrome"`, the engine under scrapling's Fetcher). Duck-compatible with the
    slice of `httpx.AsyncClient` that `BoundedFetcher` uses: `await client.get(url, headers=...,
    follow_redirects=...)` → a response with `.status_code`, `.headers` (case-insensitive `.get`),
    `.is_redirect`, `.url` (an `httpx.URL`, so `.url.join(location)` works), `.content`."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._session: Any | None = None

    async def __aenter__(self) -> ImpersonatingClient:
        # Lazy import, never at module scope — the same discipline `rendered.py` uses for
        # scrapling, so importing capture never costs a curl_cffi load.
        from curl_cffi.requests import AsyncSession

        self._session = await AsyncSession(trust_env=False).__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> bool:
        session, self._session = self._session, None
        if session is not None:
            await session.__aexit__(*exc_info)
        return False

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> ImpersonatedResponse:
        if self._session is None:
            raise RuntimeError("ImpersonatingClient must be used as an async context manager")
        # Our own `lumen-ingestion/1` User-Agent is dropped deliberately. The impersonation
        # works because the UA, the TLS handshake and the sec-ch-ua hints all agree on one
        # real Chrome build; pinning our UA on top is exactly the incoherence the walls
        # score. Everything else we send (Accept-Language) is kept.
        outgoing = {
            key: value
            for key, value in (headers or {}).items()
            if key.lower() != "user-agent"
        }
        response = await self._session.get(
            url,
            impersonate="chrome",
            allow_redirects=follow_redirects,
            max_redirects=MAX_REDIRECT_HOPS,
            timeout=self._timeout,
            headers=outgoing or None,
        )
        # Parity with the httpx path: the body arrives whole and
        # `BoundedFetcher._read_capped` truncates and flags it afterwards. No streaming
        # ceiling here either.
        return ImpersonatedResponse(
            status_code=int(response.status_code),
            headers=httpx.Headers(list(response.headers.multi_items())),
            url=httpx.URL(str(response.url)),
            content=response.content or b"",
        )
