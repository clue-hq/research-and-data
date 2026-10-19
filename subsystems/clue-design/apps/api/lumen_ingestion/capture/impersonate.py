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

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx

from .net import MAX_REDIRECT_HOPS


@dataclass(frozen=True)
class _ResponseHead:
    """Shared metadata for buffered and streaming responses."""

    status_code: int
    headers: Mapping[str, str]
    url: httpx.URL

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400 and "location" in self.headers


@dataclass(frozen=True)
class ImpersonatedResponse(_ResponseHead):
    """The buffered response returned by :meth:`ImpersonatingClient.get`."""

    content: bytes


@dataclass(frozen=True)
class _StreamResponse(_ResponseHead):
    _response: Any

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        async for chunk in self._response.aiter_content():
            yield chunk


def _outgoing_headers(headers: Mapping[str, str] | None) -> dict[str, str] | None:
    # Keep Chrome's UA consistent with its TLS fingerprint and client hints.
    return {
        key: value
        for key, value in (headers or {}).items()
        if key.lower() != "user-agent"
    } or None


@dataclass
class _StreamLease:
    curl: Any | None = None
    released: asyncio.Event = field(default_factory=asyncio.Event)


_stream_lease: ContextVar[_StreamLease | None] = ContextVar("stream_lease", default=None)


class ImpersonatingClient:
    """An async HTTP client that presents a real Chrome TLS/HTTP2 fingerprint (curl_cffi
    `impersonate="chrome"`, the engine under scrapling's Fetcher). Duck-compatible with the
    slice of `httpx.AsyncClient` that `BoundedFetcher` uses: `await client.get(url, headers=...,
    follow_redirects=...)` → a response with `.status_code`, `.headers` (case-insensitive `.get`),
    `.is_redirect`, `.url` (an `httpx.URL`, so `.url.join(location)` works), `.content`.
    `stream()` exposes the same metadata and native incremental `aiter_bytes()`."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._session: Any | None = None

    async def __aenter__(self) -> ImpersonatingClient:
        # Lazy import, never at module scope — the same discipline `rendered.py` uses for
        # scrapling, so importing capture never costs a curl_cffi load.
        from curl_cffi.requests import AsyncSession

        class _TrackedSession(AsyncSession):
            async def pop_curl(self):
                curl = await super().pop_curl()
                if (lease := _stream_lease.get()) is not None:
                    lease.curl = curl
                return curl

            def release_curl(self, curl):
                lease = _stream_lease.get()
                owns_lease = lease is not None and lease.curl is curl
                # curl_cffi's early stream error and done callback both release.
                # A duplicate pooled handle can be leased to two later requests.
                if owns_lease and lease.released.is_set():
                    return
                try:
                    super().release_curl(curl)
                finally:
                    if owns_lease:
                        lease.released.set()

        self._session = await _TrackedSession(trust_env=False).__aenter__()
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
        response = await self._session.get(
            url,
            impersonate="chrome",
            allow_redirects=follow_redirects,
            max_redirects=MAX_REDIRECT_HOPS,
            timeout=self._timeout,
            headers=_outgoing_headers(headers),
        )
        # Preserve the buffered page-fetch contract; resource fan-out uses stream().
        return ImpersonatedResponse(
            status_code=int(response.status_code),
            headers=httpx.Headers(list(response.headers.multi_items())),
            url=httpx.URL(str(response.url)),
            content=response.content or b"",
        )

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> AsyncIterator[_StreamResponse]:
        """Yield native chunks within the total deadline, aborting on context exit.

        BoundedFetcher caps retained bodies; curl's own queue may read ahead, so
        this is not a hard ceiling on transport buffering.
        """
        if self._session is None:
            raise RuntimeError("ImpersonatingClient must be used as an async context manager")
        # curl's streaming timeout is a low-speed/connect limit; retain the total
        # request deadline across response acquisition and body consumption too.
        async with asyncio.timeout(self._timeout):
            # curl_cffi starts its transfer before returning response metadata. A
            # request-local lease also covers cancellation while that await is pending.
            session = self._session
            lease = _StreamLease()
            token = _stream_lease.set(lease)
            try:
                response = await session.request(
                    method,
                    url,
                    stream=True,
                    impersonate="chrome",
                    allow_redirects=follow_redirects,
                    max_redirects=MAX_REDIRECT_HOPS,
                    timeout=self._timeout,
                    headers=_outgoing_headers(headers),
                )
            except asyncio.CancelledError:
                if lease.curl is not None and not lease.released.is_set():
                    session.acurl.remove_handle(lease.curl)
                    # The native perform-task callback owns release; never reset or
                    # return an active handle to the shared pool ourselves.
                    await lease.released.wait()
                raise
            finally:
                _stream_lease.reset(token)
            try:
                yield _StreamResponse(
                    status_code=int(response.status_code),
                    headers=httpx.Headers(list(response.headers.multi_items())),
                    url=httpx.URL(str(response.url)),
                    _response=response,
                )
            finally:
                # curl_cffi 0.15's async aclose() only awaits the transfer. Cancel its
                # native stream task so early exits (including caps) stop reception,
                # even if the server stalls. Its done callback releases the handle.
                response.quit_now.set()
                task = response.astream_task
                if task is not None and not task.done():
                    task.cancel()
                caller = asyncio.current_task()
                cancel_count = caller.cancelling() if caller is not None else 0
                try:
                    await response.aclose()
                except asyncio.CancelledError:
                    if caller is not None and caller.cancelling() > cancel_count:
                        raise
                await lease.released.wait()
