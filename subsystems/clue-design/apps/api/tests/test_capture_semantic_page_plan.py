"""Discover observed product links from local navigation semantics, without guessing routes."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from lumen_ingestion.capture import capture_website, net
from lumen_ingestion.capture.page_plan import discover_reference_pages, page_role

HOME = "https://example.com/"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("page-plan tests must not use the network")

    async def public_dns(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "getaddrinfo", refused)
    monkeypatch.setattr(net, "_resolve_all", public_dns)


def plan(html, *, existing=None):
    return discover_reference_pages(
        html, HOME, existing=existing or [{"url": HOME, "role": "homepage"}]
    )


@pytest.mark.parametrize("label", ["Product", "Products", "Platform", "Features", "Services"])
@pytest.mark.parametrize("landmark", ["nav", "footer", 'div role="navigation"'])
def test_direct_group_heading_discovers_unfamiliar_paths_without_rewriting_them(label, landmark):
    tag = landmark.split()[0]
    html = (
        '<main><a href="/queue">Learn more</a></main>'
        f"<{landmark}><div><h3>  {label.upper()} </h3><ul>"
        '<li><a href="/queue">Queue</a></li><li><a href="/dispatch">Dispatch</a></li>'
        '<li><a href="/later">Later</a></li></ul></div>'
        '<div><h3>Company</h3><ul><li><a href="/about">About</a></li></ul></div>'
        f"</{tag}>"
    )
    assert plan(html) == [
        {"url": HOME + "queue", "role": "product", "discovered_from": HOME},
        {"url": HOME + "dispatch", "role": "product", "discovered_from": HOME},
    ]


@pytest.mark.parametrize(
    "group",
    [
        '<ul aria-label="Product"><li><a href="/queue">Queue</a></li></ul>',
        (
            '<h3 id="p">Features</h3><div><ul aria-labelledby="p">'
            '<li><a href="/queue">Queue</a></li></ul></div>'
        ),
        '<div aria-label="Services"><ul><li><a href="/queue">Queue</a></li></ul></div>',
        (
            '<h3 id="p">Platform</h3><div aria-labelledby="p">'
            '<ul><li><a href="/queue">Queue</a></li></ul></div>'
        ),
        (
            '<div role="list" aria-label="Products">'
            '<div role="listitem"><a href="/queue">Queue</a></div></div>'
        ),
    ],
)
def test_unambiguous_aria_group_labels_are_source_evidence(group):
    assert [row["url"] for row in plan(f"<footer>{group}</footer>")] == [HOME + "queue"]


@pytest.mark.parametrize(
    "html",
    [
        '<main><h3>Product</h3><ul><li><a href="/queue">Queue</a></li></ul></main>',
        '<h1>Product</h1><nav><ul><li><a href="/queue">Queue</a></li></ul></nav>',
        '<h1>Product</h1><ul role="navigation"><li><a href="/queue">Queue</a></li></ul>',
        '<footer><h3>Product</h3><div><ul><li><a href="/queue">Queue</a></li></ul></div></footer>',
        (
            '<footer><h3>Product</h3><ul><li><a href="/about">About</a>'
            '</li></ul><ul><li><a href="/queue">Queue</a></li></ul></footer>'
        ),
        (
            "<footer><h3>Product</h3><h3>Company</h3><ul>"
            '<li><a href="/queue">Queue</a></li></ul></footer>'
        ),
        (
            "<footer><div><h3>Product news</h3><ul><li>"
            '<a href="/queue">Queue</a></li></ul></div></footer>'
        ),
        (
            '<h3 id="p">Product</h3><footer><ul aria-labelledby="p">'
            '<li><a href="/queue">Queue</a></li></ul></footer>'
        ),
        (
            '<footer><h3 id="p">Product</h3><h3 id="p">Company</h3>'
            '<ul aria-labelledby="p"><li><a href="/queue">Queue</a></li></ul></footer>'
        ),
        (
            '<footer><ul aria-labelledby="missing" aria-label="Product">'
            '<li><a href="/queue">Queue</a></li></ul></footer>'
        ),
        (
            '<footer><h3>Product</h3><ul aria-label="Company">'
            '<li><a href="/queue">Queue</a></li></ul></footer>'
        ),
    ],
)
def test_ambiguous_or_nonlocal_product_mentions_do_not_supply_a_role(html):
    assert plan(html) == []


def test_nested_list_owns_its_label_instead_of_inheriting_parent_product_role():
    html = (
        '<nav><ul aria-label="Product"><li><a href="/queue">Queue</a></li>'
        '<li><div><h3>Company</h3><ul aria-label="Company">'
        '<li><a href="/about">About</a></li><li><a href="/culture">Culture</a></li>'
        "</ul></div></li></ul></nav>"
    )
    assert [row["url"] for row in plan(html)] == [HOME + "queue"]


def test_context_does_not_override_proof_roles_or_promote_utility_pages():
    hrefs = [
        "/pricing",
        "/security",
        "/changelog",
        "/docs",
        "/signup",
        "/contact/sales",
        "/privacy",
        "/blog/queue",
        "/jobs",
        "/customers",
        "/customers/shop",
    ]
    links = "".join(f'<li><a href="{href}">Details</a></li>' for href in hrefs)
    html = (
        "<footer><h3>Product</h3><ul>"
        + links
        + '<li><a href="/utility">Contact sales</a></li>'
        + '<li><a href="/story">Customer story</a></li>'
        + '<li><a href="/queue">Queue</a></li></ul></footer>'
        + '<a href="/product/security">Product security</a>'
    )
    result = plan(html)
    assert [(row["url"], row["role"]) for row in result] == [
        (HOME + "queue", "product"),
        (HOME + "product/security", "product"),
        (HOME + "customers", "customers"),
        (HOME + "customers/shop", "case-study"),
        (HOME + "story", "case-study"),
    ]
    assert page_role(HOME + "product/security") == "product"
    assert page_role(HOME + "queue") == "reference"


def test_semantic_candidates_keep_origin_query_fragment_and_duplicate_rules():
    hrefs = [
        "#product",
        "/",
        "https://foreign.example/queue",
        "https://sub.example.com/queue",
        "http://example.com/queue",
        "https://user:pass@example.com/queue",
        "mailto:a@example.com",
        "/queue?mode=one#details",
        "/queue?mode=one#again",
        "/queue?mode=two",
        "/third",
    ]
    html = (
        '<nav><ul aria-label="Product">'
        + "".join(f'<li><a href="{href}">Queue</a></li>' for href in hrefs)
        + "</ul></nav>"
    )
    assert [row["url"] for row in plan(html)] == [HOME + "queue?mode=one", HOME + "queue?mode=two"]
    existing = [
        {"url": HOME, "role": "homepage"},
        {"url": HOME + "queue?mode=one", "role": "product"},
    ]
    assert [row["url"] for row in plan(html, existing=existing)] == [HOME + "queue?mode=two"]


def test_semantic_discovery_respects_existing_category_and_total_page_budgets():
    html = (
        "<footer><h3>Product</h3><ul>"
        + "".join(f'<li><a href="/flow-{i}">Flow {i}</a></li>' for i in range(30))
        + "</ul></footer>"
    )
    existing = [{"url": HOME, "role": "homepage"}] + [
        {"url": HOME + f"reference-{i}", "role": "reference"} for i in range(18)
    ]
    assert [row["url"] for row in plan(html, existing=existing)] == [HOME + "flow-0"]
    existing.append({"url": HOME + "another", "role": "reference"})
    assert plan(html, existing=existing) == []
    assert (
        plan(
            html,
            existing=[
                {"url": HOME, "role": "homepage"},
                {"url": HOME + "first", "role": "product"},
                {"url": HOME + "second", "role": "product"},
            ],
        )
        == []
    )


@pytest.mark.parametrize("product_status", [200, 404])
def test_capture_only_clears_missing_product_after_successful_observed_fetch(product_status):
    requested = []

    def respond(request):
        if request.url.path == "/favicon.ico":
            return httpx.Response(404)  # Existing asset probe, not a discovered page.
        requested.append(str(request.url))
        if request.url.path == "/":
            html = (
                "<html><body><h1>Site</h1><footer><h3>Product</h3><ul><li>"
                '<a href="/queue">Queue</a></li></ul></footer></body></html>'
            )
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        assert request.url.path == "/queue", "capture must not invent a route"
        return httpx.Response(
            product_status,
            text="<html><body><h1>Queue</h1></body></html>",
            headers={"content-type": "text/html"},
        )

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
    assert requested == [HOME, HOME + "queue"]
    product = next(row for row in outcome.page_coverage if row["role"] == "product")
    assert (product["status"] == "failed") is (product_status == 404)
    assert ("product" in outcome.missing_page_roles) is (product_status == 404)
    assert len(outcome.snapshots) == (1 if product_status == 404 else 2)
