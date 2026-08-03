"""D4 pure-contract tests over the current Exa company-item schema."""

from __future__ import annotations

from copy import deepcopy

import pytest

from clue_research.adapters.exa_websets import (
    ExaResponseEnrichment,
    ExaWebsetItem,
    normalize_exa_discovery_company_item,
)


def _definition(
    enrichment_id: str,
    field_key: str,
    *,
    format_: str = "text",
) -> ExaResponseEnrichment:
    return ExaResponseEnrichment.model_validate(
        {
            "id": enrichment_id,
            "object": "webset_enrichment",
            "status": "completed",
            "websetId": "ws_d4",
            "title": field_key,
            "description": f"Find {field_key}",
            "format": format_,
            "options": None,
            "instructions": None,
            "metadata": {"clueFieldKey": field_key},
            "createdAt": "2026-08-03T08:00:00Z",
            "updatedAt": "2026-08-03T08:05:00Z",
        }
    )


def _item_payload() -> dict[str, object]:
    return {
        "id": "item_d4",
        "object": "webset_item",
        "source": "search",
        "sourceId": "search_d4",
        "sourceEntityId": None,
        "scopeId": None,
        "websetId": "ws_d4",
        "properties": {
            "type": "company",
            "url": "https://www.example-neuro.com/",
            "description": "Independent neurosurgery practice",
            "content": None,
            "company": {
                "name": "Example Neuro",
                "location": "Austin, Texas, United States",
                "employees": 42,
                "industry": "Medical Practice",
                "about": "A physician-owned neurosurgery practice.",
                "logoUrl": None,
                "foundedYear": 1999,
                "headquarters": {
                    "address": "100 Main St",
                    "city": "Austin",
                    "state": "Texas",
                    "postalCode": "78701",
                    "country": "United States",
                    "countryCode": "US",
                },
                "financials": {
                    "revenueAnnual": 12_500_000,
                    "fundingTotal": 2_000_000,
                    "fundingLatestRound": {
                        "name": "Seed",
                        "date": "2025-01-02",
                        "amount": 2_000_000,
                    },
                },
                "webTraffic": {"visitsMonthly": 100_000, "uniqueVisitors": 60_000},
            },
        },
        "evaluations": [
            {
                "criterion": "Is an independent practice",
                "reasoning": "The practice describes itself as physician owned.",
                "satisfied": "yes",
                "references": [
                    {
                        "title": "About",
                        "snippet": "Physician-owned practice",
                        "url": "https://www.example-neuro.com/about",
                    }
                ],
            }
        ],
        "enrichments": [
            {
                "object": "enrichment_result",
                "status": "completed",
                "format": "url",
                "result": ["https://www.linkedin.com/company/example-neuro"],
                "reasoning": "Canonical company page.",
                "references": [
                    {
                        "title": "Example Neuro | LinkedIn",
                        "snippet": None,
                        "url": "https://www.linkedin.com/company/example-neuro",
                    }
                ],
                "enrichmentId": "enr_linkedin",
            },
            {
                "object": "enrichment_result",
                "status": "completed",
                "format": "number",
                "result": None,
                "reasoning": "No separate revenue estimate was found.",
                "references": [],
                "enrichmentId": "enr_revenue",
            },
        ],
        "createdAt": "2026-08-03T08:00:00Z",
        "updatedAt": "2026-08-03T08:10:00Z",
    }


def _definitions() -> tuple[ExaResponseEnrichment, ...]:
    return (
        _definition("enr_linkedin", "core.company_linkedin_url", format_="url"),
        _definition("enr_revenue", "core.annual_revenue_usd", format_="number"),
    )


def test_normalizer_preserves_current_company_fields_and_excludes_disallowed_fields() -> None:
    item = ExaWebsetItem.model_validate(_item_payload())
    normalized = normalize_exa_discovery_company_item(item, _definitions())

    assert normalized.provider_item_id == "item_d4"
    assert normalized.provider_webset_id == "ws_d4"
    assert normalized.provider_source_id == "search_d4"
    assert normalized.base_fields == {
        "name": "Example Neuro",
        "url": "https://www.example-neuro.com/",
        "location": "Austin, Texas, United States",
        "employees": 42,
        "industry": "Medical Practice",
        "about": "A physician-owned neurosurgery practice.",
        "headquarters": {
            "address": "100 Main St",
            "city": "Austin",
            "state": "Texas",
            "postalCode": "78701",
            "country": "United States",
            "countryCode": "US",
        },
        "revenueAnnual": "12500000",
        "fundingTotal": "2000000",
        "fundingLatestRound": {
            "name": "Seed",
            "date": "2025-01-02",
            "amount": "2000000",
        },
    }
    assert "foundedYear" not in normalized.base_fields
    assert "webTraffic" not in normalized.base_fields
    assert normalized.evaluations[0].satisfied == "yes"
    assert normalized.enrichments[0].field_key == "core.company_linkedin_url"
    assert normalized.enrichments[1].field_key == "core.annual_revenue_usd"
    assert normalized.enrichments[1].is_missing


def test_normalizer_rejects_definition_item_mismatch_and_duplicate_logical_field() -> None:
    payload = _item_payload()
    item = ExaWebsetItem.model_validate(payload)
    with pytest.raises(ValueError, match="do not match"):
        normalize_exa_discovery_company_item(item, _definitions()[:1])

    duplicate = (
        _definition("enr_linkedin", "core.company_linkedin_url", format_="url"),
        _definition("enr_revenue", "core.company_linkedin_url", format_="number"),
    )
    with pytest.raises(ValueError, match="repeat logical field"):
        normalize_exa_discovery_company_item(item, duplicate)

    wrong_format = (
        _definition("enr_linkedin", "core.company_linkedin_url", format_="text"),
        _definition("enr_revenue", "core.annual_revenue_usd", format_="number"),
    )
    with pytest.raises(ValueError, match="result format does not match"):
        normalize_exa_discovery_company_item(item, wrong_format)


def test_normalizer_rejects_non_terminal_and_non_company_items() -> None:
    payload = deepcopy(_item_payload())
    enrichments = payload["enrichments"]
    assert isinstance(enrichments, list)
    enrichments[0]["status"] = "pending"
    with pytest.raises(ValueError, match="not terminal completed"):
        normalize_exa_discovery_company_item(ExaWebsetItem.model_validate(payload), _definitions())

    person = deepcopy(_item_payload())
    properties = person["properties"]
    assert isinstance(properties, dict)
    person["properties"] = {"type": "person"}
    person["enrichments"] = []
    with pytest.raises(ValueError, match="requires an Exa company item"):
        normalize_exa_discovery_company_item(ExaWebsetItem.model_validate(person), ())


def test_normalizer_accepts_live_email_result_specialization_from_text_definition() -> None:
    payload = _item_payload()
    enrichments = payload["enrichments"]
    assert isinstance(enrichments, list)
    enrichments.append(
        {
            "object": "enrichment_result",
            "status": "completed",
            "format": "email",
            "result": ["hello@example-neuro.com"],
            "reasoning": "Public company inbox.",
            "references": [],
            "enrichmentId": "enr_email",
        }
    )
    definitions = (*_definitions(), _definition("enr_email", "core.company_email", format_="text"))
    normalized = normalize_exa_discovery_company_item(
        ExaWebsetItem.model_validate(payload), definitions
    )
    assert normalized.enrichments[-1].format.value == "email"

    enrichments[-1]["format"] = "text"
    with pytest.raises(ValueError, match="result format does not match"):
        normalize_exa_discovery_company_item(ExaWebsetItem.model_validate(payload), definitions)
