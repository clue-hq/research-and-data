"""C6 composition/queue/sitemap/robots tests at the API-owned provider boundary."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from clue_api.official_site_crawl_wiring import (
    DbOfficialSiteCrawlEnqueuer,
    LiveRobotsAuthorizer,
    LiveSitemapSeedDiscoverer,
    build_official_site_crawl_fleet,
    crawl_contract_config,
)
from clue_api.stage0_setup_fleet import DbStage0ReconEnqueuer
from clue_config import Secrets, Settings
from clue_core import OnboardingInputId
from clue_fleet import FleetTaskKind
from clue_research.adapters.scrapling_page import ScraplingTransportResponse
from clue_research.official_site import (
    CrawlMode,
    OfficialSiteDiscoveryPolicy,
    UrlPolicyConfig,
)
from clue_research.official_site.url_policy import ConservativeUrlPolicy
from tests.db.conftest import run_async


class _Queue:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return True


def _settings(**updates: Any) -> Settings:
    values = {
        "stage0_official_site_crawl_mode": "shadow",
        "stage0_official_site_crawl_workspace_allowlist": ("ws",),
    }
    values.update(updates)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_crawl_and_recon_enqueuers_store_only_internal_references() -> None:
    async def scenario() -> None:
        queue = _Queue()
        recon_run_id = uuid4()
        crawl = DbOfficialSiteCrawlEnqueuer(
            settings=_settings(),
            queue=queue,  # type: ignore[arg-type]
        )
        assert await crawl.enqueue(workspace_id="ws", recon_run_id=recon_run_id)
        call = queue.calls[-1]
        assert call["kind"] is FleetTaskKind.OFFICIAL_SITE_CRAWL
        assert call["priority"] == -100
        assert call["payload"] == {
            "workspace_id": "ws",
            "recon_run_id": str(recon_run_id),
        }

        recon = DbStage0ReconEnqueuer(queue=queue)  # type: ignore[arg-type]
        input_id = OnboardingInputId(uuid4())
        assert await recon.enqueue(
            workspace_id="ws",
            onboarding_input_id=input_id,
            website_digest="a" * 64,
            attempt=0,
        )
        call = queue.calls[-1]
        assert call["kind"] is FleetTaskKind.STAGE0_RECON
        assert call["priority"] == -200
        payload = call["payload"]
        assert isinstance(payload, dict)
        assert "website" not in payload
        assert "token" not in payload
        assert "email" not in payload

    run_async(scenario())


def test_off_or_non_allowlisted_workspace_originates_no_crawl() -> None:
    async def scenario() -> None:
        queue = _Queue()
        off = DbOfficialSiteCrawlEnqueuer(
            settings=Settings(_env_file=None),  # type: ignore[call-arg]
            queue=queue,  # type: ignore[arg-type]
        )
        assert not await off.enqueue(workspace_id="ws", recon_run_id=uuid4())
        restricted = DbOfficialSiteCrawlEnqueuer(
            settings=_settings(),
            queue=queue,  # type: ignore[arg-type]
        )
        assert not await restricted.enqueue(workspace_id="other", recon_run_id=uuid4())
        assert queue.calls == []

    run_async(scenario())


def test_contract_settings_are_pinned_and_authoritative_composition_refuses_without_c7() -> None:
    config = crawl_contract_config(_settings(), provider_key="fixture")
    assert config.crawl_mode is CrawlMode.SHADOW
    assert config.fast_deadline_seconds == 40
    assert config.max_graph_depth == 2

    with pytest.raises(RuntimeError, match="requires the C7 corpus materializer"):
        build_official_site_crawl_fleet(
            settings=_settings(stage0_official_site_crawl_mode="authoritative"),
            secrets=Secrets(_env_file=None),  # type: ignore[call-arg]
            storage=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(RuntimeError, match="requires its API key"):
        build_official_site_crawl_fleet(
            settings=_settings(stage0_page_fetcher="firecrawl"),
            secrets=Secrets(_env_file=None, firecrawl_api_key=None),  # type: ignore[call-arg]
            storage=object(),  # type: ignore[arg-type]
        )


class _ControlClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, url: str, *, allowed_domain: str) -> ScraplingTransportResponse:
        assert allowed_domain == "example.com"
        self.calls.append(url)
        if url.endswith("robots.txt"):
            return ScraplingTransportResponse(
                final_url=url,
                http_status=200,
                headers={"content-type": "text/plain"},
                content=(
                    b"User-agent: *\nDisallow: /private\nSitemap: https://example.com/sitemap.xml\n"
                ),
            )
        return ScraplingTransportResponse(
            final_url=url,
            http_status=200,
            headers={"content-type": "application/xml"},
            content=(
                b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                b"<url><loc>https://example.com/pricing</loc></url>"
                b"<url><loc>https://example.com/about</loc></url></urlset>"
            ),
        )


def test_live_robots_and_sitemap_composition_is_bounded_and_preserves_unknown_depth() -> None:
    async def scenario() -> None:
        client = _ControlClient()
        robots = LiveRobotsAuthorizer(
            client=client,  # type: ignore[arg-type]
            allowed_domain="example.com",
        )
        assert (await robots.authorize("https://example.com/pricing")).allowed
        assert not (await robots.authorize("https://example.com/private/report")).allowed
        assert client.calls.count("https://example.com/robots.txt") == 1

        policy = ConservativeUrlPolicy(
            UrlPolicyConfig(
                root_url="https://example.com/",
                allowed_registrable_domain="example.com",
            )
        )
        discovery = OfficialSiteDiscoveryPolicy(url_policy=policy)
        observations = await LiveSitemapSeedDiscoverer(
            client=client,  # type: ignore[arg-type]
            robots=robots,
            allowed_domain="example.com",
            max_urls=10,
        ).discover(
            root_url="https://example.com/",
            url_policy=policy,
            discovery_policy=discovery,
        )
        assert [item.fetch_key for item in observations] == [
            "https://example.com/pricing",
            "https://example.com/about",
        ]
        assert all(item.graph_depth is None for item in observations)
        assert all(item.sitemap_url == "https://example.com/sitemap.xml" for item in observations)

    run_async(scenario())
