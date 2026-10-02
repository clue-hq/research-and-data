"""The logo ladder's Chrome-fingerprint transport (founder decision 2026-09-02).

Every network test here runs against a stdlib HTTP server bound to 127.0.0.1 on an
ephemeral port. Nothing in this file touches the real internet.
"""

from __future__ import annotations

import asyncio
import http.server
import threading

import pytest

# --- a tiny local site -------------------------------------------------------

_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
_PAGE = b"<html><head><title>Local</title></head><body><h1>hello</h1></body></html>"


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves four fixed routes and records the headers it was sent."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self.server.seen_headers.append(dict(self.headers.items()))  # type: ignore[attr-defined]
        if self.path == "/page":
            self._send(200, "text/html; charset=utf-8", _PAGE)
        elif self.path == "/hop":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/logo.svg":
            self._send(200, "image/svg+xml", _SVG)
        else:
            self._send(404, "text/plain", b"nope")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the test output quiet
        return


@pytest.fixture
def local_site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.seen_headers = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _base(server) -> str:
    host, port = server.server_address[0], server.server_address[1]
    return f"http://{host}:{port}"


# --- 1. the settings flag ----------------------------------------------------


def test_flag_defaults_on_and_zero_turns_it_off(monkeypatch):
    from py_lumen_config.config import Settings

    monkeypatch.delenv("LUMEN_LADDER_IMPERSONATE_CHROME", raising=False)
    assert Settings(_env_file=None).lumen_ladder_impersonate_chrome is True

    monkeypatch.setenv("LUMEN_LADDER_IMPERSONATE_CHROME", "0")
    assert Settings(_env_file=None).lumen_ladder_impersonate_chrome is False


# --- 2. the client itself, against the local server --------------------------


def test_get_returns_a_page(local_site):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient

    url = f"{_base(local_site)}/page"

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await client.get(url)

    response = asyncio.run(go())
    assert response.status_code == 200
    assert response.headers.get("content-type") == "text/html; charset=utf-8"
    assert response.content == _PAGE
    assert str(response.url) == url


def test_redirect_is_reported_not_followed_when_asked(local_site):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await client.get(f"{base}/hop", follow_redirects=False)

    response = asyncio.run(go())
    assert response.status_code == 302
    assert response.is_redirect is True
    location = response.headers.get("location")
    assert location == "/page"
    # The ladder's per-hop SSRF re-guard joins exactly this way.
    assert str(response.url.join(location)).endswith("/page")


def test_redirect_is_followed_when_asked(local_site):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await client.get(f"{base}/hop", follow_redirects=True)

    response = asyncio.run(go())
    assert response.status_code == 200
    assert response.content == _PAGE
    assert str(response.url).endswith("/page")


def test_asset_bytes_come_back_intact(local_site):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await client.get(f"{base}/logo.svg")

    response = asyncio.run(go())
    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/svg+xml"
    assert response.content == _SVG


def test_a_404_is_a_response_not_an_exception(local_site):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await client.get(f"{base}/missing")

    assert asyncio.run(go()).status_code == 404


def test_the_user_agent_on_the_wire_is_chrome_not_ours(local_site):
    """Our `lumen-ingestion/1` UA is dropped; the impersonation's own UA is sent."""
    from lumen_ingestion.capture.impersonate import ImpersonatingClient
    from lumen_ingestion.capture.net import _DEFAULT_HEADERS

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            await client.get(f"{base}/page", headers=_DEFAULT_HEADERS)

    asyncio.run(go())
    seen = local_site.seen_headers[-1]
    user_agent = next(v for k, v in seen.items() if k.lower() == "user-agent")
    assert "Chrome/" in user_agent
    assert "lumen-ingestion" not in user_agent
    accept_language = next(v for k, v in seen.items() if k.lower() == "accept-language")
    assert accept_language == "en"


# --- 3. BoundedFetcher over the impersonating client -------------------------


@pytest.fixture
def no_ssrf_guard(monkeypatch):
    """`guard_url` refuses loopback as SSRF, so the local server is unreachable
    through the fetcher. Neutralize the guard for these two tests ONLY — the guard
    itself is unchanged and every non-test path still runs it."""
    from lumen_ingestion.capture import net

    async def identity(url: str) -> str:
        return url

    monkeypatch.setattr(net, "guard_url", identity)


def test_fetcher_follows_a_hop_through_the_impersonating_client(
    local_site, no_ssrf_guard
):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient
    from lumen_ingestion.capture.net import BoundedFetcher

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await BoundedFetcher(client).fetch_page(f"{base}/hop")

    result = asyncio.run(go())
    assert result.ok is True
    assert result.status == 200
    assert result.body == _PAGE
    assert (result.final_url or "").endswith("/page")


def test_fetcher_pulls_asset_bytes_through_the_impersonating_client(
    local_site, no_ssrf_guard
):
    from lumen_ingestion.capture.impersonate import ImpersonatingClient
    from lumen_ingestion.capture.net import BoundedFetcher, FetchRequest

    base = _base(local_site)

    async def go():
        async with ImpersonatingClient(timeout=10.0) as client:
            return await BoundedFetcher(client).fetch_many(
                [FetchRequest(url=f"{base}/logo.svg", kind="logo")]
            )

    results = asyncio.run(go())
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].body == _SVG


# --- 4. which client `fetch_logo_family` owns (network-free) -----------------

_STUB_PAGE = b"<html><head><title>Stub</title></head><body></body></html>"


class _StubResponse:
    def __init__(self, url: str) -> None:
        import httpx

        self.status_code = 200
        self.headers = httpx.Headers({"content-type": "text/html"})
        self.url = httpx.URL(url)
        self.content = _STUB_PAGE
        self.is_redirect = False


def _recorder_client(record: list[str], label: str):
    class _Recorder:
        def __init__(self, *args, **kwargs) -> None:
            record.append(label)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def get(self, url, **kwargs):
            return _StubResponse(url)

    return _Recorder


def test_the_flag_on_makes_the_ladder_own_an_impersonating_client(monkeypatch):
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.capture import impersonate, net

    async def identity(url: str) -> str:
        return url

    monkeypatch.setattr(net, "guard_url", identity)
    monkeypatch.setattr(logo_ladder, "_impersonate_chrome", lambda: True)

    used: list[str] = []
    monkeypatch.setattr(
        impersonate, "ImpersonatingClient", _recorder_client(used, "impersonate")
    )

    asyncio.run(logo_ladder.fetch_logo_family("example.com", with_brand_pages=False))
    assert used == ["impersonate"]


def test_the_flag_off_makes_the_ladder_own_a_plain_httpx_client(monkeypatch):
    import httpx
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.capture import net

    async def identity(url: str) -> str:
        return url

    monkeypatch.setattr(net, "guard_url", identity)
    monkeypatch.setattr(logo_ladder, "_impersonate_chrome", lambda: False)

    used: list[str] = []
    # `logo_ladder` imports httpx inside the function, so the module attribute on
    # `httpx` itself is the thing to swap.
    monkeypatch.setattr(httpx, "AsyncClient", _recorder_client(used, "httpx"))

    asyncio.run(logo_ladder.fetch_logo_family("example.com", with_brand_pages=False))
    assert used == ["httpx"]
