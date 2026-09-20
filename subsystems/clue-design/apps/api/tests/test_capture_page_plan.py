"""Bounded, evidence-based website library discovery and honest coverage."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from lumen_api.models import IngestWebsiteRequest
from lumen_ingestion.capture import capture_website
from pydantic import ValidationError

HOME = "https://example.com/"
HTML = (
    "<html><body><h1>Product</h1><nav>"
    '<a href="/product/agents">Agents</a><a href="/product/inbox">Inbox</a>'
    '<a href="/customers">Customers</a><a href="/privacy">Privacy</a>'
    '<a href="https://foreign.example/product/a">Other company</a>'
    '<a href="/product/agents#details">Agents again</a>'
    "</nav></body></html>"
)


def test_ingestion_exposes_bounded_explicit_pages_and_default_library_discovery() -> None:
    request = IngestWebsiteRequest(url=HOME, page_urls=[HOME + "product/agents"])
    assert request.page_urls == [HOME + "product/agents"]
    assert request.discover_pages is True
    with pytest.raises(ValidationError):
        IngestWebsiteRequest(url=HOME, page_urls=[HOME + str(i) for i in range(21)])


def test_discovery_follows_product_and_customer_evidence_and_records_failure() -> None:
    requested = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/":
            html = HTML
        elif request.url.path == "/customers":
            html = (
                '<html><body><a href="/customers/hotel">Hotel story</a>'
                '<a href="/customers/missing">Other story</a></body></html>'
            )
        elif request.url.path == "/customers/missing":
            return httpx.Response(404)
        else:
            html = "<html><body><h1>Source page</h1></body></html>"
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await capture_website(
                HOME,
                reporter=lambda *_: None,
                render_available=False,
                http_client=client,
                discover_pages=True,
            )

    outcome = asyncio.run(run())
    pages = {row["url"]: row for row in outcome.page_coverage}
    assert set(pages) == {
        HOME,
        HOME + "product/agents",
        HOME + "product/inbox",
        HOME + "customers",
        HOME + "customers/hotel",
        HOME + "customers/missing",
    }
    assert pages[HOME + "customers/missing"]["status"] == "failed"
    assert HOME + "privacy" not in requested
    assert not any("foreign.example" in url for url in requested)
    assert sum(url == HOME + "product/agents" for url in requested) == 1


def test_anchor_only_homepage_reports_missing_page_categories_without_inventing_urls() -> None:
    from lumen_ingestion.capture.page_plan import discover_reference_pages

    plan = discover_reference_pages(
        '<a href="#platform">Platform</a><a href="/privacy">Privacy</a>',
        HOME,
        existing=[{"url": HOME, "role": "homepage"}],
    )
    assert plan == []


def test_motion_inventory_distinguishes_css_video_and_unrecovered_canvas_runtime() -> None:
    from lumen_ingestion.capture.page_plan import motion_inventory
    from lumen_ingestion.capture.snapshot import SiteSnapshot, Stylesheet

    snapshot = SiteSnapshot(
        requested_url=HOME,
        final_url=HOME,
        fetched_at="2026-09-20T12:00:00Z",
        tier="static",
        html='<video src="/hero.webm"></video><canvas id="scene"></canvas>',
        stylesheets=[
            Stylesheet(
                url=HOME + "a.css",
                text="@keyframes floaty {to {opacity:1}} .a{animation:floaty 2s;}",
            )
        ],
    )
    inventory = motion_inventory(snapshot)
    assert inventory["css_keyframes"] == ["floaty"]
    assert inventory["videos"] == [HOME + "hero.webm"]
    assert inventory["canvas_count"] == 1
    assert inventory["canvas_runtime_recovered"] is False


def test_page_plan_has_a_hard_bound_even_for_direct_callers() -> None:
    from lumen_ingestion.capture import _pages_to_capture
    from lumen_ingestion.capture.net import CaptureError

    with pytest.raises(CaptureError, match="at most 20"):
        _pages_to_capture(HOME, [HOME + str(i) for i in range(20)])


def test_fragment_budget_does_not_let_homepage_starve_supporting_pages() -> None:
    from lumen_ingestion.pipeline import _allocate_fragment_budget

    assert _allocate_fragment_budget([40, 40, 40], 6, 40) == [2, 2, 2]
    assert _allocate_fragment_budget([1, 40, 40], 9, 40) == [1, 4, 4]
    assert _allocate_fragment_budget([80, 40], 240, 40) == [40, 40]


def test_capture_coverage_survives_evidence_and_public_job_projection() -> None:
    import json

    from lumen_api.dto import ingestion_job_outcome
    from lumen_ingestion.pipeline import _evidence_dump

    pages = [{"url": HOME, "role": "homepage", "status": "partial", "fidelity_verified": False}]
    evidence = json.loads(_evidence_dump({}, page_coverage=pages, missing_page_roles=["product"]))
    assert evidence["page_coverage"] == pages
    public = ingestion_job_outcome({"kind": "website", "evidence": evidence})
    assert public["pages"][0]["status"] == "partial"
    assert public["missing_page_roles"] == ["product"]
    assert public["fidelity_verified"] is False


def test_pipeline_default_capture_forwards_discovery(monkeypatch) -> None:
    from lumen_ingestion import capture, pipeline

    received = {}

    async def fake(url, **kwargs):
        received.update(kwargs)
        return "captured"

    monkeypatch.setattr(capture, "capture_website", fake)
    assert (
        asyncio.run(pipeline._default_capture(HOME, reporter=lambda *_: None, discover_pages=True))
        == "captured"
    )
    assert received["discover_pages"] is True


def test_stealth_error_page_is_refused_without_fallback(monkeypatch) -> None:
    from types import SimpleNamespace

    from lumen_ingestion.capture import rendered
    from lumen_ingestion.capture.net import CaptureError
    from scrapling.fetchers import StealthyFetcher

    async def allow(url):
        return url

    async def failed(*args, **kwargs):
        return SimpleNamespace(status=404)

    async def wrong_fallback(*args, **kwargs):
        raise AssertionError("must not recapture a 404")

    monkeypatch.setattr(rendered, "guard_url", allow)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", failed)
    monkeypatch.setattr(rendered, "_fetch_rendered_chromium", wrong_fallback)
    monkeypatch.setenv("LUMEN_RENDER_STEALTH", "1")
    with pytest.raises(CaptureError, match="HTTP 404"):
        asyncio.run(rendered.fetch_rendered(HOME, None, lambda *_: None, fetched_at="now"))
