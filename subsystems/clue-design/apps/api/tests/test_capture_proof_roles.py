"""Do not count product marketing and story collections as individual proof."""

from __future__ import annotations

import pytest
from lumen_ingestion.capture.page_plan import discover_reference_pages, page_role


@pytest.mark.parametrize(
    ("path", "label", "expected"),
    [
        ("/products/support/customer/", "Customer experience platform", "product"),
        ("/platform/customer/overview", "Customer workspace", "product"),
        ("/features/customer/reviews", "Review management", "product"),
        ("/product/security", "Security", "product"),
        ("/products/tool/customer-stories/hotel", "Hotel story", "case-study"),
        ("/products/tool/case-studies/hotel", "Hotel story", "case-study"),
        ("/customers", "Customers", "customers"),
        ("/customer/hotel", "Hotel", "case-study"),
        ("/solutions/case-studies/collection/", "View more stories", "customers"),
        ("/solutions/case-studies/collection/", "Browse all customer stories", "customers"),
        ("/solutions/case-studies/collection/", "See all case studies", "customers"),
        ("/solutions/case-studies/hotel", "Hotel success story", "case-study"),
        ("/solutions/case-studies/hotel", "Hotel helps teams view more stories", "case-study"),
        ("/solutions/case-studies/hotel", "View the story", "case-study"),
        ("/products/stories", "View more stories", "product"),
        ("/blog/case-studies/", "View more stories", "reference"),
    ],
)
def test_observed_path_and_link_label_distinguish_collection_product_and_story(
    path: str, label: str, expected: str
) -> None:
    assert page_role("https://example.com" + path, label) == expected


def test_product_with_customer_slug_does_not_consume_proof_budget() -> None:
    home = "https://example.com/"
    html = """<nav>
      <a href="/products/agents">Agents</a>
      <a href="/products/connect/customer/?source=nav">Customer support product</a>
      <a href="/products/">Product catalog</a>
      <a href="/solutions/case-studies/collection/?source=home">View more stories</a>
      <a href="/solutions/case-studies/collection/company-a">Company A. View the story</a>
      <a href="/solutions/case-studies/collection/company-b">Company B. View the story</a>
      <a href="/solutions/case-studies/collection/company-c">Company C. View the story</a>
    </nav>"""
    rows = discover_reference_pages(html, home, existing=[{"url": home, "role": "homepage"}])
    assert [(row["url"].removeprefix(home), row["role"]) for row in rows] == [
        ("products/agents", "product"),
        ("products/connect/customer/?source=nav", "product"),
        ("solutions/case-studies/collection/?source=home", "customers"),
        ("solutions/case-studies/collection/company-a", "case-study"),
        ("solutions/case-studies/collection/company-b", "case-study"),
    ]


def test_one_malformed_observed_link_does_not_discard_valid_page_candidates() -> None:
    rows = discover_reference_pages(
        '<a href="https://[bad-host/product/x">Broken</a>'
        '<a href="/product/good">Good product</a>'
        '<a href="/customers">Customers</a>',
        "https://example.com/",
        existing=[{"url": "https://example.com/", "role": "homepage"}],
    )
    assert [(row["url"], row["role"]) for row in rows] == [
        ("https://example.com/product/good", "product"),
        ("https://example.com/customers", "customers"),
    ]
