"""C2 provider-free URL, sitemap, robots, graph-planning, and safety acceptance matrix."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clue_research.official_site import (
    ConservativeUrlPolicy,
    CrawlEligibility,
    CrawlSafetyPolicy,
    DiscoveredVia,
    LinkObservation,
    LinkRelation,
    OfficialSiteDiscoveryPolicy,
    PolicyOutcome,
    RedirectHop,
    RobotsParsePolicy,
    RobotsPolicyError,
    SitemapEntry,
    SitemapParsePolicy,
    SitemapPayload,
    SitemapPolicyError,
    StaticAddressResolver,
    UrlObservation,
    UrlPolicyConfig,
    apply_safety_decision,
    build_sitemap_inventory,
    classify_page,
    extract_html_links,
    make_pinned_resolver,
    parse_robots,
    parse_sitemap,
    preflight_target,
    validate_redirects,
    validate_response_content,
)

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "official_site" / "c2_url_policy_matrix.json"


def _url_policy(
    *,
    root: str = "https://example.com/",
    domain: str = "example.com",
    allow_subdomains: bool = False,
) -> ConservativeUrlPolicy:
    return ConservativeUrlPolicy(
        UrlPolicyConfig(
            root_url=root,
            allowed_registrable_domain=domain,
            allow_subdomains=allow_subdomains,
        )
    )


def test_c2_policy_modules_are_provider_database_and_http_client_free() -> None:
    package = (
        Path(__file__).parents[2] / "subsystems" / "research" / "clue_research" / "official_site"
    )
    forbidden = {
        "aiohttp",
        "asyncpg",
        "firecrawl",
        "httpx",
        "requests",
        "scrapling",
        "sqlalchemy",
    }
    found: set[tuple[str, str]] = set()
    for name in ("url_policy.py", "discovery.py", "safety.py", "robots.py", "sitemap.py"):
        tree = ast.parse((package / name).read_text())
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.append(node.module.split(".", 1)[0])
            found.update((name, root) for root in roots if root in forbidden)
    assert not found


def test_every_c2_policy_rejects_unknown_versions_and_incoherent_bounds() -> None:
    with pytest.raises(ValueError, match="unsupported URL policy"):
        ConservativeUrlPolicy(
            UrlPolicyConfig(
                root_url="https://example.com/",
                allowed_registrable_domain="example.com",
                version="future",
            )
        )
    with pytest.raises(ValueError, match="unsupported discovery policy"):
        OfficialSiteDiscoveryPolicy(url_policy=_url_policy(), version="future")
    with pytest.raises(ValueError, match="unsupported safety policy"):
        CrawlSafetyPolicy(version="future")
    with pytest.raises(ValueError, match="frozen observation bound"):
        CrawlSafetyPolicy(max_link_text_chars=501)
    with pytest.raises(ValueError, match="unsupported robots policy"):
        RobotsParsePolicy(version="future")
    with pytest.raises(ValueError, match="unsupported sitemap policy"):
        SitemapParsePolicy(version="future")


def test_full_versioned_url_policy_fixture_matrix() -> None:
    cases = json.loads(_FIXTURE.read_text())
    assert len(cases) >= 30
    for case in cases:
        policy = _url_policy(
            root=case.get("root", "https://example.com/"),
            domain=case.get("domain", "example.com"),
        )
        decision = policy.decide(case["url"], base_url=case.get("base"))
        if "fetch_key" in case:
            assert decision.admitted, case["name"]
            assert decision.fetch_key == case["fetch_key"], case["name"]
            assert decision.fetch_key_hash is not None and len(decision.fetch_key_hash) == 64
            assert list(decision.removed_tracking_parameters) == case.get("removed", [])
            assert decision.stripped_fragment == case.get("stripped")
            assert decision.routing_fragment == case.get("routing")
        else:
            assert not decision.admitted, case["name"]
            assert decision.reason == case["reason"], case["name"]
            assert decision.fetch_key is None and decision.fetch_key_hash is None


def test_conservative_equivalence_and_non_equivalence_are_explicit() -> None:
    policy = _url_policy()
    keys = {
        value: policy.decide(value).fetch_key
        for value in (
            "https://example.com/pricing",
            "https://example.com/pricing/",
            "https://example.com/",
            "https://example.com/index.html",
            "https://example.com/search?a=1&b=2",
            "https://example.com/search?b=2&a=1",
            "https://example.com/search?a=1&a=2",
        )
    }
    assert len(set(keys.values())) == len(keys)
    assert (
        policy.decide("https://example.com/pricing?utm_source=nav#plans").fetch_key
        == "https://example.com/pricing"
    )
    assert (
        policy.decide("https://example.com/pricing#/in-app").fetch_key
        == "https://example.com/pricing#/in-app"
    )


def test_subdomain_policy_is_explicit_and_auth_surfaces_stay_denied() -> None:
    policy = _url_policy(allow_subdomains=True)
    assert policy.decide("https://docs.example.com/guide").admitted
    assert policy.decide("https://auth.example.com/guide").reason == "denied_auth_host"
    assert policy.decide("https://example.com/sign-in/sso").reason == "denied_auth_path"
    assert policy.decide("https://notexample.com/").reason == "external_domain"


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",
        "10.0.0.1",
        "100.64.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "172.16.0.1",
        "192.0.2.1",
        "192.168.1.1",
        "224.0.0.1",
        "255.255.255.255",
        "::",
        "::1",
        "::ffff:127.0.0.1",
        "2001:db8::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
    ],
)
def test_ssrf_preflight_refuses_every_non_public_address_class(address: str) -> None:
    async def run() -> None:
        decision = await preflight_target(
            "https://example.com/",
            url_policy=_url_policy(),
            resolver=StaticAddressResolver({"example.com": (address,)}),
            safety=CrawlSafetyPolicy(),
        )
        assert not decision.allowed
        assert decision.reason == "non_public_network_target"

    asyncio.run(run())


def test_ssrf_preflight_accepts_only_all_public_bounded_dns_answers() -> None:
    async def run() -> None:
        policy = _url_policy()
        accepted = await preflight_target(
            "https://example.com/",
            url_policy=policy,
            resolver=StaticAddressResolver(
                {"example.com": ("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")}
            ),
            safety=CrawlSafetyPolicy(),
        )
        assert accepted.allowed
        mixed = await preflight_target(
            "https://example.com/",
            url_policy=policy,
            resolver=StaticAddressResolver({"example.com": ("93.184.216.34", "127.0.0.1")}),
            safety=CrawlSafetyPolicy(),
        )
        assert not mixed.allowed
        ceiling = await preflight_target(
            "https://example.com/",
            url_policy=policy,
            resolver=StaticAddressResolver({"example.com": ("1.1.1.1", "8.8.8.8")}),
            safety=CrawlSafetyPolicy(max_dns_answers=1),
        )
        assert not ceiling.allowed and ceiling.reason == "dns_answer_ceiling_exceeded"

        timeout = await preflight_target(
            "https://example.com/",
            url_policy=policy,
            resolver=StaticAddressResolver({"example.com": TimeoutError("dns_timeout")}),
            safety=CrawlSafetyPolicy(),
        )
        assert not timeout.allowed and timeout.reason == "dns_timeout"

    asyncio.run(run())


def test_ip_literal_and_dns_private_targets_become_explicit_refused_observations() -> None:
    async def run() -> None:
        literal_policy = _url_policy(root="http://127.0.0.1/", domain="127.0.0.1")
        literal = await preflight_target(
            "http://127.0.0.1/public",
            url_policy=literal_policy,
            resolver=StaticAddressResolver({}),
            safety=CrawlSafetyPolicy(),
        )
        assert not literal.allowed and literal.reason == "non_public_network_target"

        discovery = OfficialSiteDiscoveryPolicy(url_policy=_url_policy())
        provisional = discovery.root("https://example.com/")
        private_dns = await preflight_target(
            "https://example.com/",
            url_policy=_url_policy(),
            resolver=StaticAddressResolver({"example.com": ("10.0.0.8",)}),
            safety=CrawlSafetyPolicy(),
        )
        refused = apply_safety_decision(provisional, private_dns)
        assert refused.policy_outcome is PolicyOutcome.REFUSED
        assert refused.fetch_key is None and refused.fetch_key_hash is None
        assert refused.policy_reason == "non_public_network_target"

    asyncio.run(run())


def test_redirect_policy_revalidates_chain_final_domain_private_ips_loops_and_ceiling() -> None:
    async def run() -> None:
        policy = _url_policy()
        public = StaticAddressResolver({"example.com": ("93.184.216.34",)})
        safety = CrawlSafetyPolicy(max_redirects=2)
        valid_chain = (
            RedirectHop(
                from_url="https://example.com/old",
                to_url="https://example.com/pricing",
                http_status=301,
            ),
        )
        assert (
            await validate_redirects(
                requested_url="https://example.com/old",
                final_url="https://example.com/pricing",
                redirect_chain=valid_chain,
                url_policy=policy,
                resolver=public,
                safety=safety,
            )
        ).allowed
        external = await validate_redirects(
            requested_url="https://example.com/old",
            final_url="https://evil.test/",
            redirect_chain=(
                RedirectHop(
                    from_url="https://example.com/old",
                    to_url="https://evil.test/",
                    http_status=302,
                ),
            ),
            url_policy=policy,
            resolver=public,
            safety=safety,
        )
        assert not external.allowed and external.reason == "redirect_external_domain"
        private = await validate_redirects(
            requested_url="https://example.com/old",
            final_url="https://example.com/private",
            redirect_chain=(
                RedirectHop(
                    from_url="https://example.com/old",
                    to_url="https://example.com/private",
                    http_status=302,
                ),
            ),
            url_policy=policy,
            resolver=StaticAddressResolver({"example.com": ("169.254.169.254",)}),
            safety=safety,
        )
        assert not private.allowed and private.reason == "redirect_non_public_network_target"
        loop = await validate_redirects(
            requested_url="https://example.com/a",
            final_url="https://example.com/a",
            redirect_chain=(
                RedirectHop(
                    from_url="https://example.com/a",
                    to_url="https://example.com/b",
                    http_status=302,
                ),
                RedirectHop(
                    from_url="https://example.com/b",
                    to_url="https://example.com/a",
                    http_status=302,
                ),
            ),
            url_policy=policy,
            resolver=public,
            safety=safety,
        )
        assert not loop.allowed and loop.reason == "redirect_loop"
        overflow = await validate_redirects(
            requested_url="https://example.com/a",
            final_url="https://example.com/c",
            redirect_chain=valid_chain * 3,
            url_policy=policy,
            resolver=public,
            safety=safety,
        )
        assert not overflow.allowed and overflow.reason == "redirect_ceiling_exceeded"

    asyncio.run(run())


def test_content_mime_decompressed_size_and_link_ceilings_fail_closed() -> None:
    safety = CrawlSafetyPolicy(max_response_bytes=5, max_outgoing_links=2, max_link_text_chars=4)
    assert validate_response_content(
        media_type="text/html; charset=utf-8", content=b"12345", safety=safety
    ).allowed
    assert (
        validate_response_content(media_type="image/png", content=b"1", safety=safety).reason
        == "unsupported_media_type"
    )
    assert (
        validate_response_content(media_type="text/html", content=b"123456", safety=safety).reason
        == "decompressed_response_too_large"
    )
    discovery = OfficialSiteDiscoveryPolicy(url_policy=_url_policy(), safety=safety)
    planned, dropped = discovery.plan_links(
        (
            LinkObservation(discovered_url="/a", link_text="abcdefgh"),
            LinkObservation(discovered_url="/b", link_text="second"),
            LinkObservation(discovered_url="/c", link_text="third"),
        ),
        source_page_id=uuid4(),
        source_url="https://example.com/",
        source_graph_depth=0,
    )
    assert len(planned) == 2 and dropped == 1
    assert planned[0].link_text == "abcd"


def test_local_transport_rebinding_seam_passes_only_prevalidated_addresses() -> None:
    async def run() -> None:
        received: list[tuple[str, tuple[str, ...]]] = []

        async def connector(url: str, addresses: tuple[str, ...]) -> object:
            received.append((url, addresses))
            return "connected"

        connect = make_pinned_resolver(
            StaticAddressResolver({"example.com": ("93.184.216.34",)}),
            connector,
            safety=CrawlSafetyPolicy(),
        )
        assert await connect("https://example.com/") == "connected"
        assert received == [("https://example.com/", ("93.184.216.34",))]
        refused = make_pinned_resolver(
            StaticAddressResolver({"example.com": ("127.0.0.1",)}),
            connector,
            safety=CrawlSafetyPolicy(),
        )
        with pytest.raises(ValueError, match="non_public_network_target"):
            await refused("https://example.com/")

    asyncio.run(run())


def test_robots_longest_match_user_agent_status_and_sitemap_rules() -> None:
    body = b"""
User-agent: *
Disallow: /private
Allow: /private/public
Sitemap: /sitemap.xml

User-agent: cluebot
Disallow: /bot-only
Allow: /bot-only/ok$
"""
    document = parse_robots(
        body,
        robots_url="https://example.com/robots.txt",
        media_type="text/plain; charset=utf-8",
    )
    assert document.sitemap_urls == ("https://example.com/sitemap.xml",)
    assert not document.decide(
        user_agent="otherbot", target_url="https://example.com/private/a"
    ).allowed
    assert document.decide(
        user_agent="otherbot", target_url="https://example.com/private/public/a"
    ).allowed
    assert not document.decide(
        user_agent="ClueBot/1.0", target_url="https://example.com/bot-only/no"
    ).allowed
    assert document.decide(
        user_agent="ClueBot/1.0", target_url="https://example.com/bot-only/ok"
    ).allowed
    assert not document.decide(user_agent="ClueBot/1.0", target_url="https://evil.test/").allowed
    missing = parse_robots(
        b"", robots_url="https://example.com/robots.txt", media_type=None, http_status=404
    )
    refused = parse_robots(
        b"", robots_url="https://example.com/robots.txt", media_type=None, http_status=403
    )
    unavailable = parse_robots(
        b"", robots_url="https://example.com/robots.txt", media_type=None, http_status=503
    )
    assert missing.decide(user_agent="clue", target_url="https://example.com/a").allowed
    assert not refused.decide(user_agent="clue", target_url="https://example.com/a").allowed
    assert not unavailable.decide(user_agent="clue", target_url="https://example.com/a").allowed


def test_robots_parser_enforces_every_bound() -> None:
    with pytest.raises(RobotsPolicyError, match="size"):
        parse_robots(
            b"x" * 5,
            robots_url="https://example.com/robots.txt",
            media_type="text/plain",
            policy=RobotsParsePolicy(max_bytes=4),
        )
    with pytest.raises(RobotsPolicyError, match="media"):
        parse_robots(
            b"User-agent: *",
            robots_url="https://example.com/robots.txt",
            media_type="text/html",
        )
    with pytest.raises(RobotsPolicyError, match="line_ceiling"):
        parse_robots(
            b"a\nb\nc",
            robots_url="https://example.com/robots.txt",
            media_type="text/plain",
            policy=RobotsParsePolicy(max_lines=2),
        )
    with pytest.raises(RobotsPolicyError, match="rule_ceiling"):
        parse_robots(
            b"User-agent: *\nDisallow: /a\nDisallow: /b",
            robots_url="https://example.com/robots.txt",
            media_type="text/plain",
            policy=RobotsParsePolicy(max_rules=1),
        )
    with pytest.raises(RobotsPolicyError, match="sitemap_ceiling"):
        parse_robots(
            b"Sitemap: /a.xml\nSitemap: /b.xml",
            robots_url="https://example.com/robots.txt",
            media_type="text/plain",
            policy=RobotsParsePolicy(max_sitemaps=1),
        )


def test_sitemap_urlset_and_bounded_index_inventory_keep_depth_out_of_inventory() -> None:
    urlset = SitemapPayload(
        body=b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/pricing</loc></url>
  <url><loc>/about</loc></url>
</urlset>""",
        media_type="application/xml",
    )
    parsed = parse_sitemap(urlset, sitemap_url="https://example.com/pages.xml")
    assert parsed.page_urls == ("https://example.com/pricing", "https://example.com/about")
    index = SitemapPayload(
        body=b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/pages.xml</loc></sitemap>
  <sitemap><loc>https://evil.test/external.xml</loc></sitemap>
</sitemapindex>""",
        media_type="text/xml",
    )
    inventory = build_sitemap_inventory(
        root_sitemap_urls=("https://example.com/sitemap.xml",),
        captured_documents={
            "https://example.com/sitemap.xml": index,
            "https://example.com/pages.xml": urlset,
        },
        url_policy=_url_policy(),
    )
    assert [entry.discovered_url for entry in inventory.entries] == [
        "https://example.com/pricing",
        "https://example.com/about",
    ]
    assert inventory.documents_visited == (
        "https://example.com/sitemap.xml",
        "https://example.com/pages.xml",
    )
    assert inventory.refused_documents == (("https://evil.test/external.xml", "external_domain"),)
    discovery = OfficialSiteDiscoveryPolicy(url_policy=_url_policy())
    observations = tuple(discovery.sitemap(entry) for entry in inventory.entries)
    assert all(item.graph_depth is None for item in observations)
    assert all(item.discovered_via is DiscoveredVia.SITEMAP for item in observations)
    assert all(item.sitemap_url == "https://example.com/pages.xml" for item in observations)


def test_url_observation_origin_provenance_fails_closed() -> None:
    common = {
        "discovered_url": "https://example.com/pricing",
        "fetch_key": "https://example.com/pricing",
        "fetch_key_hash": "a" * 64,
        "eligibility": CrawlEligibility.BOTH,
        "policy_outcome": PolicyOutcome.ADMITTED,
    }
    with pytest.raises(ValidationError, match="requires source_page_id"):
        UrlObservation(**common, discovered_via=DiscoveredVia.LINK, graph_depth=1)
    with pytest.raises(ValidationError, match="cannot carry source_page_id"):
        UrlObservation(
            **common,
            discovered_via=DiscoveredVia.SITEMAP,
            source_page_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="depth zero"):
        UrlObservation(**common, discovered_via=DiscoveredVia.ROOT, graph_depth=1)
    with pytest.raises(ValidationError, match="alias discovery cannot assign"):
        UrlObservation(
            **common,
            discovered_via=DiscoveredVia.CANONICAL,
            source_page_id=uuid4(),
            graph_depth=1,
        )


def test_sitemap_parser_rejects_bombs_entities_mime_depth_and_loops() -> None:
    with pytest.raises(SitemapPolicyError, match="size"):
        parse_sitemap(
            SitemapPayload(b"<urlset/>", "application/xml"),
            sitemap_url="https://example.com/s.xml",
            policy=SitemapParsePolicy(max_bytes=5),
        )
    with pytest.raises(SitemapPolicyError, match="media"):
        parse_sitemap(
            SitemapPayload(b"<urlset/>", "application/zip"),
            sitemap_url="https://example.com/s.xml",
        )
    with pytest.raises(SitemapPolicyError, match="dtd_or_entity"):
        parse_sitemap(
            SitemapPayload(
                b"<!DOCTYPE x [<!ENTITY boom 'x'>]><urlset><url><loc>&boom;</loc></url></urlset>",
                "application/xml",
            ),
            sitemap_url="https://example.com/s.xml",
        )
    with pytest.raises(SitemapPolicyError, match="url_ceiling"):
        parse_sitemap(
            SitemapPayload(
                b"<urlset><url><loc>/a</loc></url><url><loc>/b</loc></url></urlset>",
                "application/xml",
            ),
            sitemap_url="https://example.com/s.xml",
            policy=SitemapParsePolicy(max_urls=1),
        )
    loop_index = SitemapPayload(
        b"<sitemapindex><sitemap><loc>/s.xml</loc></sitemap></sitemapindex>",
        "application/xml",
    )
    inventory = build_sitemap_inventory(
        root_sitemap_urls=("https://example.com/s.xml",),
        captured_documents={"https://example.com/s.xml": loop_index},
        url_policy=_url_policy(),
    )
    assert inventory.refused_documents == (
        ("https://example.com/s.xml", "sitemap_loop_or_duplicate"),
    )
    depth_inventory = build_sitemap_inventory(
        root_sitemap_urls=("https://example.com/s.xml",),
        captured_documents={"https://example.com/s.xml": loop_index},
        url_policy=_url_policy(),
        policy=SitemapParsePolicy(max_index_depth=0),
    )
    assert depth_inventory.refused_documents == (
        ("https://example.com/s.xml", "sitemap_index_depth_ceiling_exceeded"),
    )


def test_discovery_categories_depth_aliases_and_active_content_are_deterministic() -> None:
    assert classify_page("https://example.com/pricing") == "pricing"
    assert classify_page("https://example.com/case-studies/acme") == "customer_proof"
    assert classify_page("https://example.com/team") == "company"
    extracted = extract_html_links(
        b"""
        <html><head><link rel="canonical" href="https://example.com/home"></head><body>
        <a href="/pricing"><span>See</span> pricing</a>
        <script><a href="https://evil.test/injected">ignore</a></script>
        <template><a href="/also-ignore">ignore</a></template>
        </body></html>
        """
    )
    assert extracted.links == (LinkObservation(discovered_url="/pricing", link_text="See pricing"),)
    assert extracted.canonical_hints == (
        LinkObservation(
            discovered_url="https://example.com/home",
            relation=LinkRelation.CANONICAL_HINT,
        ),
    )
    jointly_bounded = extract_html_links(
        b'<a href="/one">one</a><a href="/two">two</a><link rel="canonical" href="/canonical">',
        safety=CrawlSafetyPolicy(max_outgoing_links=2),
    )
    assert len(jointly_bounded.links) + len(jointly_bounded.canonical_hints) == 2
    assert jointly_bounded.dropped_links == 1
    discovery = OfficialSiteDiscoveryPolicy(url_policy=_url_policy())
    source_id = uuid4()
    depth_two = discovery.link(
        LinkObservation(discovered_url="/too-deep"),
        source_page_id=source_id,
        source_url="https://example.com/product",
        source_graph_depth=2,
    )
    unknown = discovery.link(
        LinkObservation(discovered_url="/saved-until-shorter-path"),
        source_page_id=source_id,
        source_url="https://example.com/product",
        source_graph_depth=None,
    )
    same_canonical = discovery.link(
        LinkObservation(discovered_url="/home", relation=LinkRelation.CANONICAL_HINT),
        source_page_id=source_id,
        source_url="https://example.com/product",
        source_graph_depth=1,
    )
    external_canonical = discovery.link(
        LinkObservation(discovered_url="https://evil.test/", relation=LinkRelation.CANONICAL_HINT),
        source_page_id=source_id,
        source_url="https://example.com/product",
        source_graph_depth=1,
    )
    assert depth_two.policy_outcome is PolicyOutcome.REFUSED
    assert depth_two.policy_reason == "graph_depth_ceiling_exceeded"
    assert unknown.policy_outcome is PolicyOutcome.ADMITTED and unknown.graph_depth is None
    assert same_canonical.policy_outcome is PolicyOutcome.REFUSED
    assert same_canonical.fetch_key == "https://example.com/home"
    assert "no_identity_merge" in (same_canonical.policy_reason or "")
    assert external_canonical.fetch_key is None
    assert external_canonical.policy_reason == "canonical_external_domain_refused"


def test_sitemap_only_constructor_cannot_be_given_false_link_depth() -> None:
    observation = OfficialSiteDiscoveryPolicy(url_policy=_url_policy()).sitemap(
        SitemapEntry("https://example.com/pricing", "https://example.com/sitemap.xml")
    )
    assert observation.graph_depth is None
    assert observation.sitemap_url == "https://example.com/sitemap.xml"
    assert observation.policy_outcome is PolicyOutcome.ADMITTED
