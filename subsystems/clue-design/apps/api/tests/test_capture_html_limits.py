"""Large page heads must not erase body logos/backgrounds or become successful prefixes."""

from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from lumen_ingestion.capture import net, rendered
from lumen_ingestion.capture.net import BoundedFetcher, CaptureError, PAGE_MAX_BYTES
from lumen_ingestion.capture.static import fetch_static


BASE = "https://example.com/"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    async def resolve(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(net, "_resolve_all", resolve)


def capture_html(html: str, tier: str):
    def respond(request):
        if request.url.path == "/":
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            fetcher = BoundedFetcher(client)
            if tier == "static":
                return await fetch_static(BASE, fetcher, lambda *_: None, fetched_at="test")
            return await rendered._snapshot_from_harvest(
                BASE,
                {"html": html, "shot": PNG, "final_url": BASE, "data": {}},
                fetcher,
                [],
                fetched_at="test",
            )

    return asyncio.run(run())


@pytest.mark.parametrize("tier", ["static", "rendered"])
def test_large_head_preserves_body_logo_variants_and_backgrounds(tier):
    # AWS's rendered head exceeded the old 2 MiB cap. References after it vanished.
    html = (
        '<html><head><title>Example</title><script type="application/json">"'
        + "x" * (2 * 1024 * 1024)
        + '"</script></head><body>'
        '<header><a href="/"><img src="/logo.png" alt="Example logo"></a></header>'
        '<main style="background-image:url(/background.png)"><h1>Product</h1></main>'
        '<footer><a href="/"><img src="/logo-white.png" alt="Example logo"></a></footer>'
        '</body></html>'
    )
    snapshot = capture_html(html, tier)
    assert snapshot.html == html
    assert {BASE + name for name in ("logo.png", "logo-white.png", "background.png")} <= {
        item.url for item in snapshot.downloads
    }
    assert not any(d["code"] == "LUMI0507" for d in snapshot.diagnostics)


@pytest.mark.parametrize("tier", ["static", "rendered"])
def test_oversize_capture_refuses_instead_of_returning_a_partial_snapshot(tier):
    html = "<html><head><!--" + "x" * PAGE_MAX_BYTES + "--></head><body>Lost</body></html>"
    with pytest.raises(CaptureError) as error:
        capture_html(html, tier)
    assert error.value.code == "LUMI0507"
    assert "limit" in error.value.message.lower()


@pytest.mark.parametrize("tier", ["static", "rendered"])
def test_html_limit_counts_utf8_bytes_not_characters(tier):
    html = '<html><head><script type="application/json">"' + "界" * (PAGE_MAX_BYTES // 2)
    html += '"</script></head><body>Product</body></html>'
    assert len(html) < PAGE_MAX_BYTES < len(html.encode("utf-8"))
    with pytest.raises(CaptureError):
        capture_html(html, tier)


@pytest.mark.parametrize("tier", ["static", "rendered"])
def test_complete_html_at_the_limit_is_preserved(tier):
    prefix, suffix = "<html><head><!--", "--></head><body>Product</body></html>"
    html = prefix + "x" * (PAGE_MAX_BYTES - len(prefix) - len(suffix)) + suffix
    assert capture_html(html, tier).html == html


def test_size_refusal_does_not_retry_the_same_document_in_another_browser(monkeypatch):
    async def oversized(*args, **kwargs):
        raise CaptureError("LUMI0507", "HTML exceeds capture limit")

    async def unexpected_fallback(*args, **kwargs):
        pytest.fail("A deterministic size refusal must not start another browser capture")

    monkeypatch.setenv("LUMEN_RENDER_STEALTH", "1")
    monkeypatch.setattr(rendered, "_fetch_rendered_stealth", oversized)
    monkeypatch.setattr(rendered, "_fetch_rendered_chromium", unexpected_fallback)
    with pytest.raises(CaptureError, match="capture limit"):
        asyncio.run(rendered.fetch_rendered(BASE, None, lambda *_: None, fetched_at="test"))
