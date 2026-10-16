"""The fixed request templates equal their contracts and honour Exa's documented limits."""

from __future__ import annotations

import json
from typing import Any

from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT,
    CUSTOMER_REVIEWS_SYSTEM_PROMPT,
    EXISTING_CUSTOMERS_SYSTEM_PROMPT,
    PERSONA_EVIDENCE_SYSTEM_PROMPT,
    PRODUCT_RESEARCH_SYSTEM_PROMPT,
    company_overview_output_schema,
    company_overview_query,
    customer_reviews_output_schema,
    customer_reviews_query,
    existing_customers_output_schema,
    existing_customers_query,
    persona_evidence_output_schema,
    product_research_output_schema,
    product_research_query,
)
from tests.arv2.test_exa_client import _count_properties


def _depth(schema: Any, current: int = 0) -> int:
    """Object-nesting depth: root object = 0; an object inside an array item counts one level."""
    if not isinstance(schema, dict):
        return current
    deepest = current
    for key in ("properties", "items"):
        node = schema.get(key)
        if key == "properties" and isinstance(node, dict):
            for child in node.values():
                deepest = max(deepest, _depth(child, current + 1))
        elif key == "items" and isinstance(node, dict):
            deepest = max(deepest, _depth(node, current))
    return deepest


def test_the_overview_schema_is_the_ratified_contract_verbatim() -> None:
    """ARV2-COMPANY-OVERVIEW-CONTRACT.md §2.3 — the live-validated schema, byte for byte."""
    schema = company_overview_output_schema()
    assert schema["required"] == [
        "facts",
        "sections",
        "competitors",
        "named_customers",
        "not_found",
    ]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["facts"]["properties"]) == {
        "legal_name",
        "website",
        "founded_year",
        "headquarters",
        "employee_range",
        "funding_total_usd",
        "latest_round",
        "investors",
        "revenue_model",
        "pricing_posture",
        "industries_served",
        "geographies",
        "customer_count_claim",
        "regulatory_posture",
    }
    assert schema["properties"]["sections"]["required"] == [
        "origin_story",
        "business_model",
        "positioning",
        "market_position",
        "customer_segments",
        "leadership",
        "recent_context",
    ]
    assert schema["properties"]["competitors"]["maxItems"] == 12
    assert schema["properties"]["named_customers"]["maxItems"] == 30
    assert schema["properties"]["named_customers"]["items"]["properties"]["evidence_kind"][
        "enum"
    ] == ["case_study", "logo_wall", "press", "review", "other"]
    assert schema["properties"]["not_found"]["maxItems"] == 20
    json.dumps(schema)  # serialisable as-is


def test_the_overview_query_carries_the_nine_sections_and_the_company_name() -> None:
    query = company_overview_query("Insight Health (insighthealth.ai)")
    for heading in (
        "The Origin Story",
        "The Business Reality",
        "What They Actually Do",
        "The Market Position",
        "The Customer Reality",
        "The People",
        "The Problems",
        "The Future",
        "Recent Context",
    ):
        assert heading in query
    assert query.startswith("Research Insight Health (insighthealth.ai)")
    assert query.rstrip().endswith("company name is Insight Health (insighthealth.ai)")
    assert "[COMPANY NAME]" not in query


def test_the_system_prompts_state_the_non_negotiables() -> None:
    assert "Do not enumerate individual products" in COMPANY_OVERVIEW_SYSTEM_PROMPT
    assert "not_found" in COMPANY_OVERVIEW_SYSTEM_PROMPT
    assert (
        "never" in CUSTOMER_REVIEWS_SYSTEM_PROMPT.lower()
        and "name" in CUSTOMER_REVIEWS_SYSTEM_PROMPT
    )
    assert "only this product" in PRODUCT_RESEARCH_SYSTEM_PROMPT.lower()
    assert "verbatim" in PERSONA_EVIDENCE_SYSTEM_PROMPT


def test_the_reviews_and_product_schemas_bound_every_list_and_forbid_extras() -> None:
    reviews = customer_reviews_output_schema()
    assert reviews["properties"]["reviews"]["maxItems"] == 40
    item = reviews["properties"]["reviews"]["items"]
    assert item["required"] == ["platform", "quote", "sentiment", "source_url"]
    assert "reviewer_name" not in item["properties"]
    assert item["properties"]["sentiment"]["enum"] == ["positive", "mixed", "negative"]
    assert reviews["properties"]["case_studies"]["maxItems"] == 15

    product = product_research_output_schema()
    assert product["required"] == [
        "overview",
        "capabilities",
        "use_cases",
        "integrations",
        "pricing",
        "differentiators",
        "competitors",
        "customer_evidence",
        "not_found",
    ]
    assert product["properties"]["capabilities"]["maxItems"] == 15
    assert product["additionalProperties"] is False


def test_queries_name_their_subject_and_siblings() -> None:
    assert "insighthealth.ai" in customer_reviews_query("Insight Health", "insighthealth.ai")
    query = product_research_query(
        product_name="Aura AI Scribe",
        company_name="Insight Health",
        official_url="https://www.insighthealth.ai/ambient",
        sibling_names=["Aura Anywhere", "MagicFlow"],
    )
    assert "Aura AI Scribe" in query and "https://www.insighthealth.ai/ambient" in query
    assert "Aura Anywhere" in query and "MagicFlow" in query
    assert "not about" in query.lower()
    assert (
        "official page"
        not in product_research_query(
            product_name="X", company_name="Y", official_url=None, sibling_names=[]
        ).lower()
    )


def test_the_persona_evidence_schema_fits_the_search_limits() -> None:
    """It rides ``/search`` deep-reasoning: ≤ 10 properties, depth ≤ 2, no citation fields."""
    schema = persona_evidence_output_schema()
    assert _count_properties(schema) <= 10
    assert _depth(schema) <= 2
    assert schema["required"] == ["passages"]
    passage = schema["properties"]["passages"]["items"]
    assert passage["required"] == ["quote", "speaker_role"]
    assert not {"url", "citations", "source_url"} & set(passage["properties"])


def test_the_customers_query_names_the_seller_and_where_to_look() -> None:
    query = existing_customers_query("Alt Carbon", "altcarbon.com")
    for part in (
        "Alt Carbon",
        "altcarbon.com",
        "what buying from",
        "sitemap",
        "logo walls",
        "press releases",
        "purchase trackers or registries",
    ):
        assert part in query


def test_the_customers_prompt_states_the_non_negotiables() -> None:
    for part in (
        "investors",
        "integration partners",
        "competitors",
        "same logo wall",
        "named on a page",
        "brand domains",
        "otherwise leave it out",
    ):
        assert part in EXISTING_CUSTOMERS_SYSTEM_PROMPT


def test_the_customers_schema_bounds_lists_and_forbids_extras() -> None:
    schema = existing_customers_output_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["customers", "seller_domains"]
    customers = schema["properties"]["customers"]
    assert customers["maxItems"] == 300
    item = customers["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["name", "domains", "relationship", "evidence_kind", "quote"]
    assert item["properties"]["relationship"]["enum"] == [
        "direct",
        "through_coalition",
        "through_marketplace",
        "weak_mention",
    ]
    assert item["properties"]["evidence_kind"]["enum"] == [
        "logo_wall",
        "case_study",
        "testimonial",
        "press",
        "review",
        "tracker",
        "other",
    ]
    assert item["properties"]["domains"]["maxItems"] == 10
    assert item["properties"]["via"]["type"] == ["string", "null"]
    assert schema["properties"]["seller_domains"]["maxItems"] == 10
