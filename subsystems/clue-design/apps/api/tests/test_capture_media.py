"""Real website dependencies must survive capture, including background video."""

from __future__ import annotations

import asyncio
import base64

import httpx
from lumen_ingestion.capture import capture_website
from lumen_ingestion.capture.candidates import collect_asset_candidates
from lumen_ingestion.capture.net import BoundedFetcher, FetchRequest
from lumen_ingestion.sections.mint import build_reference_harvest, captured_assets
from selectolax.parser import HTMLParser

BASE = "https://example.com/"
VIDEO = "https://www.gstatic.com/cgc/renaissance/video/MultiPath_2X_V2.webm"
MARKUP = (
    '<html><body><video autoplay muted loop poster="/poster.png">'
    f'<source src="{VIDEO}" type="video/webm"></video>'
    '<video src="/demo.mp4" controls></video>'
    '<img src="/figma/conduit-wordmark.svg?dpl=deployment" />'
    '<img src="/_next/image?url=%2Fhero%2Fbg.png&amp;w=640&amp;q=75&amp;dpl=deployment" '
    'srcset="/_next/image?url=%2Fhero%2Fbg.png&amp;w=1080&amp;q=75 1080w" />'
    "</body></html>"
)
WEBM = b"\x1a\x45\xdf\xa3" + b"test-webm-bytes"


def test_video_sources_posters_and_exact_query_renditions_are_all_candidates() -> None:
    candidates = {
        c.url: c for c in collect_asset_candidates(HTMLParser(MARKUP), BASE, []).candidates
    }
    assert candidates[VIDEO].kind == "video"
    assert candidates[BASE + "demo.mp4"].kind == "video"
    assert candidates[BASE + "poster.png"].kind == "image"
    assert BASE + "figma/conduit-wordmark.svg?dpl=deployment" in candidates
    assert BASE + "_next/image?url=%2Fhero%2Fbg.png&w=640&q=75&dpl=deployment" in candidates
    assert BASE + "_next/image?url=%2Fhero%2Fbg.png&w=1080&q=75" in candidates


def test_captured_video_and_image_bytes_resolve_every_original_html_reference() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE:
            return httpx.Response(200, text=MARKUP, headers={"content-type": "text/html"})
        if request.url.path.endswith((".webm", ".mp4")):
            return httpx.Response(200, content=WEBM, headers={"content-type": "video/webm"})
        return httpx.Response(200, content=b"image-bytes", headers={"content-type": "image/png"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await capture_website(
                BASE, reporter=lambda *_: None, render_available=False, http_client=client
            )

    outcome = asyncio.run(run())
    videos = [download for download in outcome.snapshot.downloads if download.kind == "video"]
    assert {download.url for download in videos} == {VIDEO, BASE + "demo.mp4"}
    assert all(base64.b64decode(download.bytes_b64) == WEBM for download in videos)
    refs = build_reference_harvest(
        subtree_html=MARKUP,
        page_url=BASE,
        css_blocks=[],
        captured=captured_assets(outcome.snapshot),
    )
    assert not refs.missing
    assert not refs.conflicts


def test_video_response_budget_stops_stream_and_never_keeps_partial_bytes(monkeypatch) -> None:
    from lumen_ingestion.capture import net

    monkeypatch.setitem(net._CAP_BY_KIND, "video", 12)
    chunks_read = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(20):
                chunks_read.append(i)
                yield b"01234567"

    async def run():
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, stream=Stream(), headers={"content-type": "video/webm"})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return (await BoundedFetcher(client).fetch_many([FetchRequest(VIDEO, "video")]))[0]

    result = asyncio.run(run())
    assert result.ok is False
    assert result.body is None
    assert len(chunks_read) == 2
    assert result.diagnostics[0]["code"] == "LUMI0502"


def test_video_redirect_cannot_fetch_loopback() -> None:
    visited = []

    def respond(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return (await BoundedFetcher(client).fetch_many([FetchRequest(VIDEO, "video")]))[0]

    result = asyncio.run(run())
    assert result.ok is False
    assert visited == [VIDEO]
    assert any("private/loopback" in d["message"] for d in result.diagnostics)


def test_video_response_with_html_type_is_reported_and_not_retained() -> None:
    async def run():
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200, text="<html>consent wall</html>", headers={"content-type": "text/html"}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return (await BoundedFetcher(client).fetch_many([FetchRequest(VIDEO, "video")]))[0]

    result = asyncio.run(run())
    assert not result.ok
    assert result.body is None
    assert "content type" in result.diagnostics[0]["reason"]


def test_redirected_page_uses_final_url_for_live_and_saved_fragment_references() -> None:
    from types import SimpleNamespace

    from lumen_ingestion.pipeline import _SnapshotView
    from lumen_ingestion.sections.mint import CapturedAsset
    from lumen_ingestion.sections.segment import segment_snapshot

    html = (
        '<section class="hero"><h1>Guest conversations</h1><img src="/logo.svg?dpl=123"></section>'
    )
    requested = "https://conduit.example"
    final = "https://www.conduit.example/"
    source = SimpleNamespace(html=html, requested_url=requested, final_url=final, geometry=None)
    saved = SimpleNamespace(
        html=html,
        page_url=requested,
        meta={"final_url": final},
        snapshot_id="snap_test",
        viewport_width=None,
    )
    for snapshot in (_SnapshotView(source, snapshot_id="snap_test"), saved):
        segmented = segment_snapshot(snapshot)
        assert segmented.page_url == final
        refs = build_reference_harvest(
            subtree_html=html,
            page_url=segmented.page_url,
            css_blocks=[],
            captured={
                final + "logo.svg?dpl=123": CapturedAsset(
                    url=final + "logo.svg?dpl=123",
                    data=b"original-logo",
                    content_type="image/svg+xml",
                )
            },
        )
        assert not refs.missing
        assert refs.resolved["/logo.svg?dpl=123"] == final + "logo.svg?dpl=123"
