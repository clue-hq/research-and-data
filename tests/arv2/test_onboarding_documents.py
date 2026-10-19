"""The mappers are pure: a recorded provider body in, a KnowledgeDocument out. The recorded
Insight Health run is mapper INPUT, not a provider double (R1's live-test ruling is untouched)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from clue_api.arv2.calls import CallCost
from clue_api.arv2.customer_domains import DomainCheck
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult
from clue_api.arv2.onboarding_documents import (
    KnowledgeDocument,
    company_overview_document,
    customer_reviews_document,
    demote_headings,
    existing_customers_document,
    product_catalog_document,
    product_research_document,
    render_markdown,
    slugify,
    sources_by_field,
)

FIXTURE = Path(__file__).parent / "fixtures" / "exa_agent_overview_insight_health.json"
AS_OF = date(2026, 9, 7)


def _cost(usd: str = "0.5") -> CallCost:
    return CallCost(
        cost_usd=Decimal(usd),
        credits=Decimal(0),
        media_seconds=0,
        cost_source="metered",
        provider="exa",
        operation="agent-poll",
        raw_ref="raw/1",
        ledger_row_id="row-1",
    )


def _overview_run() -> ExaAgentRun:
    body = json.loads(FIXTURE.read_text())
    return ExaAgentRun(
        run_id=body["id"],
        status=body["status"],
        stop_reason=body["stopReason"],
        output_text=body["output"]["text"],
        structured=body["output"]["structured"],
        grounding=body["output"]["grounding"],
        usage=body["usage"],
        cost_usd=Decimal(str(body["costDollars"]["total"])),
        error_code=None,
        error_message=None,
        polls=3,
        raw_refs=("raw/1",),
        ledger_row_ids=("row-1",),
        costs=(_cost(),),
        cost=_cost(),
    )


def test_render_writes_yaml_front_matter_then_the_body() -> None:
    doc = KnowledgeDocument(
        kind="company-overview",
        folder="company",
        path="company/overview.md",
        front_matter={
            "kind": "company-overview",
            "as_of": "2026-09-07",
            "facts": {"founded_year": 2023},
        },
        body="# Company overview\n\nHello.\n",
        cost=None,
    )
    text = render_markdown(doc)
    assert text.startswith("---\n")
    head, _, body = text[4:].partition("\n---\n")
    assert yaml.safe_load(head) == doc.front_matter
    assert body.lstrip("\n") == doc.body
    assert "\nkind: company-overview\n" in "\n" + head  # insertion order kept, not sorted


def test_demote_headings_pushes_every_heading_down_one_level() -> None:
    assert demote_headings("## Leadership\n\ntext\n### Sub\n#notaheading") == (
        "### Leadership\n\ntext\n#### Sub\n#notaheading"
    )


def test_sources_by_field_keeps_confidence_and_citations_per_field() -> None:
    grounding = [
        {
            "field": "structured.facts",
            "citations": [{"url": "https://a", "title": "A"}],
            "confidence": "high",
        },
        {"field": "structured.sections.leadership", "citations": [], "confidence": "medium"},
        "garbage",
    ]
    sources = sources_by_field(grounding)
    assert sources["structured.facts"] == {
        "citations": [{"url": "https://a", "title": "A"}],
        "confidence": "high",
    }
    assert sources["structured.sections.leadership"]["confidence"] == "medium"
    assert len(sources) == 2


def test_the_overview_mapper_builds_the_contracts_front_matter_and_fixed_headings() -> None:
    doc = company_overview_document(_overview_run(), company_domain="insighthealth.ai", as_of=AS_OF)
    assert (doc.kind, doc.folder, doc.path) == (
        "company-overview",
        "company",
        "company/overview.md",
    )
    fm = doc.front_matter
    assert fm["kind"] == "company-overview"
    assert fm["as_of"] == "2026-09-07" and fm["company_domain"] == "insighthealth.ai"
    assert fm["provider_run_id"] == "agent_run_11b83e1af2bd44f399badec0d8c77ebd"
    assert fm["facts"]["legal_name"] == "Insight Health AI, Inc."
    assert fm["facts"]["founded_year"] == 2023
    assert [c["name"] for c in fm["competitors"]][:2] == ["Tennr", "HealOS"]
    assert len(fm["named_customers"]) == 8
    assert len(fm["not_found"]) == 7
    assert fm["sources"]["structured.sections.market_position"]["confidence"] == "medium"
    assert fm["cost_usd"] == "0.5" and fm["searches"] == 60
    assert doc.cost is not None and doc.cost.cost_usd == Decimal("0.5")

    headings = [line for line in doc.body.splitlines() if line.startswith("#")]
    assert headings[0] == "# Company overview"
    assert [h for h in headings if h.startswith("## ")] == [
        "## Origin story",
        "## Business model",
        "## Positioning",
        "## Market position",
        "## Competitors",
        "## Customer segments",
        "## Named customers",
        "## Leadership",
        "## Recent context",
        "## Not established",
        "## Sources",
    ]
    # The model's own "## Leadership and organization" is demoted, so ours stay the only H2s.
    assert "### Leadership and organization" in doc.body
    assert "- **Founded:** 2023" in doc.body
    assert "| Tennr |" in doc.body and "| The Oregon Clinic |" in doc.body
    assert "Audited financial statements" in doc.body  # not_found is rendered, never hidden
    assert "[Business Wire]" in doc.body  # inline labels are left as text


def test_the_overview_mapper_on_a_failed_run_yields_an_honest_empty_document() -> None:
    failed = ExaAgentRun(
        run_id="agent_run_x",
        status="failed",
        stop_reason=None,
        output_text=None,
        structured=None,
        grounding=[],
        usage={},
        cost_usd=None,
        error_code="schema_unsatisfiable",
        error_message="could not satisfy schema",
        polls=1,
        raw_refs=(),
        ledger_row_ids=("row-1",),
        costs=(_cost("0"),),
        cost=_cost("0"),
    )
    doc = company_overview_document(failed, company_domain="x.io", as_of=AS_OF)
    assert doc.front_matter["status"] == "failed"
    assert doc.front_matter["error"] == {
        "code": "schema_unsatisfiable",
        "message": "could not satisfy schema",
    }
    assert doc.front_matter["facts"] == {} and doc.front_matter["not_found"] == []
    assert "## Not established" in doc.body and "schema_unsatisfiable" in doc.body


def test_the_reviews_mapper_never_carries_a_reviewer_name_field() -> None:
    run = ExaAgentRun(
        run_id="agent_run_r",
        status="completed",
        stop_reason="schema_satisfied",
        output_text="ok",
        structured={
            "summary": "Thin corpus.",
            "themes_positive": ["fast setup"],
            "themes_negative": ["fax OCR misses"],
            "reviews": [
                {
                    "platform": "G2",
                    "source_url": "https://g2.com/x",
                    "quote": "Setup took a day.",
                    "sentiment": "positive",
                    "rating": 4.5,
                    "date": "2026-05",
                    "reviewer_role": "Practice manager",
                    "reviewer_org_type": "GI practice, 12 clinicians",
                    "product_mentioned": "Aura",
                }
            ],
            "case_studies": [
                {
                    "customer": "Headland Family Medicine",
                    "source_url": "https://insighthealth.ai/c/1",
                    "outcome_claim": "38% fewer no-shows",
                    "named_person": None,
                }
            ],
            "not_found": ["Trustpilot page"],
        },
        grounding=[],
        usage={"searches": 9},
        cost_usd=Decimal("0.1"),
        error_code=None,
        error_message=None,
        polls=2,
        raw_refs=(),
        ledger_row_ids=("row-1",),
        costs=(_cost("0.1"),),
        cost=_cost("0.1"),
    )
    doc = customer_reviews_document(run, company_domain="insighthealth.ai", as_of=AS_OF)
    assert doc.path == "proof/customer-reviews.md" and doc.kind == "customer-reviews"
    assert "reviewer_name" not in json.dumps(doc.front_matter)
    assert "## What customers praise" in doc.body and "## What customers complain about" in doc.body
    assert "> Setup took a day." in doc.body and "Practice manager" in doc.body
    assert "## Case studies" in doc.body and "38% fewer no-shows" in doc.body


def test_the_product_mapper_names_the_product_and_slugs_its_path() -> None:
    run = ExaAgentRun(
        run_id="agent_run_p",
        status="completed",
        stop_reason="schema_satisfied",
        output_text="ok",
        structured={
            "overview": "Ambient scribe.",
            "capabilities": ["Drafts SOAP notes"],
            "use_cases": ["GI visits"],
            "integrations": ["athenahealth"],
            "pricing": "$39.99/month Pro",
            "differentiators": ["Specialty templates"],
            "competitors": [{"name": "Abridge", "website": None, "how_they_compare": None}],
            "customer_evidence": [],
            "who_it_is_for": "Clinicians in outpatient practices",
            "not_found": [],
        },
        grounding=[],
        usage={},
        cost_usd=Decimal("0.1"),
        error_code=None,
        error_message=None,
        polls=1,
        raw_refs=(),
        ledger_row_ids=("row-1",),
        costs=(_cost("0.1"),),
        cost=_cost("0.1"),
    )
    doc = product_research_document(
        run,
        product_id="prd_aura",
        product_name="Aura AI Scribe",
        product_slug=slugify("Aura AI Scribe"),
        as_of=AS_OF,
    )
    assert doc.path == "product/aura-ai-scribe.md" and doc.kind == "product-research"
    assert doc.front_matter["product_id"] == "prd_aura"
    assert doc.body.startswith("# Aura AI Scribe\n")
    assert "## Who it is for" in doc.body and "## Pricing" in doc.body
    assert slugify("MagicDocs AI Referral Coordinator") == "magicdocs-ai-referral-coordinator"
    assert slugify("  Pré-Visit / Intake (Lumi)  ") == "pre-visit-intake-lumi"


def test_the_catalog_mapper_attaches_grounding_per_product_and_drops_nameless_entries() -> None:
    deep = ExaDeepResult(
        output_text="{}",
        output_object={
            "coverage_note": "Own domain + open web.",
            "products": [
                {
                    "name": "Aura AI Scribe",
                    "short_description": "Ambient documentation.",
                    "offering_kind": "product",
                    "family": "Aura",
                    "lifecycle": "active",
                    "official_url": "https://www.insighthealth.ai/ambient",
                },
                {"name": "", "short_description": "orphan", "offering_kind": "product"},
                {
                    "name": "EHR Partnership",
                    "short_description": "Embed Aura in an EHR.",
                    "offering_kind": "partner_program",
                },
            ],
        },
        report_text=None,
        grounding=[
            {
                "field": "products[0].official_url",
                "citations": [{"url": "https://www.insighthealth.ai/ambient", "title": "Aura"}],
                "confidence": "high",
            },
            {
                "field": "products[0].short_description",
                "citations": [{"url": "https://www.insighthealth.ai/", "title": "Home"}],
                "confidence": "medium",
            },
            {
                "field": "products[2].name",
                "citations": [
                    {"url": "https://www.insighthealth.ai/ehr-partnership", "title": "EHR"}
                ],
                "confidence": "high",
            },
        ],
        results=(),
        status=200,
        cost_usd=Decimal("0.015"),
        request_id="req",
        raw_ref="raw/2",
        ledger_row_id="row-2",
        cost=_cost("0.015"),
        retried=False,
    )
    doc = product_catalog_document(deep, company_domain="insighthealth.ai", as_of=AS_OF)
    assert (doc.kind, doc.path) == ("product-catalog", "product/catalog.md")
    fm = doc.front_matter
    assert fm["kind"] == "product-catalog" and fm["coverage_note"] == "Own domain + open web."
    assert [p["name"] for p in fm["products"]] == ["Aura AI Scribe", "EHR Partnership"]
    aura = fm["products"][0]
    assert aura["aliases"] == [] and aura["grounding_confidence"] == "medium"
    assert {s["url"] for s in aura["sources"]} == {
        "https://www.insighthealth.ai/ambient",
        "https://www.insighthealth.ai/",
    }
    assert fm["products"][1]["sources"][0]["url"].endswith("/ehr-partnership")
    assert fm["dropped"] == [{"index": 1, "reason": "missing name or short_description"}]
    assert "## Dropped by the mapper" in doc.body and "orphan" in doc.body


def _customers_run(*, status: str = "completed") -> ExaAgentRun:
    structured = {
        "customers": [
            {
                "name": "Wynwood House",
                "domains": ["wynwoodhouse.us"],
                "relationship": "direct",
                "via": None,
                "evidence_kind": "case_study",
                "quote": (
                    "Wynwood House made the decision to move its guest communication to Conduit."
                ),
            },
            {
                "name": "Stripe",
                "domains": ["stripe.com"],
                "relationship": "through_coalition",
                "via": "Frontier",
                "evidence_kind": "press",
                "quote": "The participating buyers are Stripe, Shopify, Google and Watershed.",
            },
        ],
        "seller_domains": ["altcarbon.com", "alt-carbon.com"],
    }
    grounding = [
        {
            "field": "structured.customers[0].quote",
            "citations": [{"url": "https://www.conduit.ai/customers/wynwood-house"}],
            "confidence": "high",
        },
        {
            "field": "structured.customers[1].quote",
            "citations": [{"url": "https://altcarbon.com/press-releases/frontier"}],
            "confidence": "high",
        },
    ]
    completed = status == "completed"
    return ExaAgentRun(
        run_id="agent_run_customers",
        status=status,
        stop_reason="schema_satisfied" if completed else None,
        output_text=None,
        structured=structured if completed else None,
        grounding=grounding if completed else [],
        usage={"searches": 120},
        cost_usd=Decimal("1"),
        error_code=None if completed else "timeout",
        error_message=None,
        polls=4,
        raw_refs=("raw/1",),
        ledger_row_ids=("row-1",),
        costs=(_cost("1"),),
        cost=_cost("1"),
    )


_CHECKS = {
    "wynwoodhouse.us": DomainCheck("unconfirmed", "Personal Care Communities | State College"),
    "stripe.com": DomainCheck("confirmed", "Stripe | Financial Infrastructure"),
}


def test_the_customers_list_lives_in_the_body_only() -> None:
    doc = existing_customers_document(
        _customers_run(), company_domain="altcarbon.com", as_of=AS_OF, checks=_CHECKS
    )
    assert (doc.kind, doc.folder, doc.path) == (
        "existing-customers",
        "proof",
        "proof/customers.md",
    )
    assert doc.front_matter["kind"] == "existing-customers"
    assert "customers" not in doc.front_matter
    assert "seller_domains" not in doc.front_matter
    assert "sources" in doc.front_matter


def test_the_table_shows_domains_with_their_check_how_they_buy_and_the_quote() -> None:
    body = existing_customers_document(
        _customers_run(), company_domain="altcarbon.com", as_of=AS_OF, checks=_CHECKS
    ).body
    assert "# Existing customers" in body
    assert (
        "| Customer | Domains | Domain check | How they buy | Evidence | Quote | Source |" in body
    )
    # The Domains cell holds only domains, so the Head of ABM can copy it into `exclude` as it is;
    # the check's result has its own column (review finding, 2026-10-16).
    assert "| Wynwood House | wynwoodhouse.us | wynwoodhouse.us: unconfirmed" in body
    assert "Personal Care Communities \\| State College" in body
    # Every answered page keeps its title, confirmed ones too (a same-name company shows there).
    assert (
        "| Stripe | stripe.com | stripe.com: confirmed (Stripe \\| Financial Infrastructure) |"
        in body
    )
    assert "through_coalition via Frontier" in body
    assert "move its guest communication to Conduit." in body
    assert "https://www.conduit.ai/customers/wynwood-house" in body
    # Sorted by name: Stripe before Wynwood House, each keeping its own source.
    assert body.index("| Stripe |") < body.index("| Wynwood House |")


def test_the_sellers_own_domains_have_their_own_line() -> None:
    body = existing_customers_document(
        _customers_run(), company_domain="altcarbon.com", as_of=AS_OF, checks=_CHECKS
    ).body
    assert "Seller's own domains: altcarbon.com, alt-carbon.com" in body


def test_a_failed_customers_run_still_renders_with_its_failure_note() -> None:
    body = existing_customers_document(
        _customers_run(status="failed"), company_domain="altcarbon.com", as_of=AS_OF, checks={}
    ).body
    assert "_Not established._" in body
    assert "Research run did not complete: `timeout`" in body


def test_the_check_column_says_when_a_domain_was_not_checked_or_none_was_given() -> None:
    run = _customers_run()
    customers = run.structured["customers"]  # type: ignore[index]
    customers.append(
        {
            "name": "Beachside",
            "domains": [],
            "relationship": "direct",
            "via": None,
            "evidence_kind": "logo_wall",
            "quote": "Operators who run on Conduit",
        }
    )
    checks = {**_CHECKS, "stripe.com": DomainCheck("unchecked", None)}
    body = existing_customers_document(
        run, company_domain="conduit.ai", as_of=AS_OF, checks=checks
    ).body
    assert "| Beachside |  | no domain given |" in body
    assert "| Stripe | stripe.com | stripe.com: not checked (the site did not answer) |" in body
