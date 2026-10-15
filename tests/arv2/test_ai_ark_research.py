"""Research-facing AI Ark data excludes prose without changing enrichment or audit data."""

import asyncio
import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from clue_api.arv2 import quality_acquisition, research_operations
from clue_api.arv2.account_research_claims import ai_ark_company_claims, ai_ark_person_claims
from clue_api.arv2.ai_ark_client import company_from_record, person_from_record
from clue_api.arv2.ai_ark_research import enrichment_only
from clue_api.arv2.committee_discovery import page_result
from tests.arv2.test_account_research_claims import CATALOG, SCOPE


def company():
    return {
        "id": "company-1",
        "summary": {
            "name": "Acme",
            "description": "PROVIDER_PROMO",
            "industry": "Software",
            "staff": {"total": 120, "range": "101-200"},
            "founded": 2015,
        },
        "link": {"domain": "acme.test", "linkedin": "https://linkedin.com/company/acme"},
        "financial": {
            "revenue": {"annual": {"amount": "10000000-25000000"}},
            "funding": {"total_amount": 1000000, "rounds": [], "description": "PROVIDER_PROMO"},
        },
        "location": {"headquarter": {"city": "London"}},
        "technologies": [
            {"name": "Salesforce", "category": "CRM", "description": "PROVIDER_PROMO"}
        ],
    }


def person():
    return {
        "id": "person-1",
        "profile": {
            "full_name": "Dana Test",
            "title": "VP Marketing",
            "headline": "PROVIDER_PROMO",
        },
        "bio": "PROVIDER_PROMO",
        "link": {"linkedin": "https://linkedin.com/in/dana-test"},
        "company": company(),
        "position_groups": [
            {
                "company": {"id": "company-1", "name": "Acme", "domain": "acme.test"},
                "profile": {"title": "VP Marketing", "description": "PROVIDER_PROMO"},
                "date": {"start": {"year": 2024}},
            }
        ],
        "email": {"output": [{"address": "dana@acme.test", "status": "valid"}]},
    }


def test_nested_projection_preserves_typed_data_and_original_record():
    original = {"content": [person()], "totalElements": 1, "trackId": "track-1"}
    before = copy.deepcopy(original)
    result = enrichment_only(original)
    assert "PROVIDER_PROMO" not in json.dumps(result)
    assert original == before
    assert result["totalElements"] == 1 and result["trackId"] == "track-1"
    record = result["content"][0]
    assert record["id"] == "person-1"
    assert record["profile"]["title"] == "VP Marketing"
    assert record["position_groups"][0]["date"]["start"]["year"] == 2024
    assert record["email"] == original["content"][0]["email"]
    assert record["company"]["summary"]["staff"]["total"] == 120
    assert enrichment_only(result) == result


def test_typed_claim_mappers_keep_identical_values_and_provenance_paths():
    for raw, parse, mapper in (
        (
            company(),
            company_from_record,
            lambda r: ai_ark_company_claims(r, SCOPE, catalog=CATALOG),
        ),
        (person(), person_from_record, lambda r: ai_ark_person_claims(r, SCOPE)),
    ):
        before = mapper(parse(raw))
        after = mapper(parse(enrichment_only(raw)))
        assert before and before == after
        assert "core.company_about" not in {d.field_key for d in after}
        assert "contact.headline" not in {d.field_key for d in after}


@pytest.mark.parametrize("full", [False, True])
def test_discovery_result_keeps_candidate_identity_without_prose(full):
    op = SimpleNamespace(operation_id=uuid4(), request_data={}, state="succeeded")
    result = page_result(op, {"content": [person()], "totalElements": 1}, SCOPE, full=full)
    assert "PROVIDER_PROMO" not in json.dumps(result)
    assert result["people"][0]["candidate_ref"] == f"{op.operation_id}:person-1"
    assert result["people"][0]["title"] == "VP Marketing"
    if full:
        assert result["people"][0]["profile"]["id"] == "person-1"


@pytest.mark.parametrize("provider", ["ai_ark", "exa"])
def test_acquisition_projects_research_evidence_only_and_preserves_audit(monkeypatch, provider):
    original = {"content": [company()], "requestId": "request-1"}
    envelope = json.dumps({"body_utf8": json.dumps(original)}).encode()
    reader = AsyncMock(return_value=(None, envelope))
    save = AsyncMock(return_value=["source"])
    monkeypatch.setattr(quality_acquisition, "read_verified_artifact", reader)
    monkeypatch.setattr(quality_acquisition, "prepare_sources", save)
    row = quality_acquisition.AcquisitionReceipt(
        uuid4(), provider, "lookup", datetime.now(UTC), 200, None, "audit-key", uuid4()
    )
    asyncio.run(
        quality_acquisition._index_receipts(None, None, SimpleNamespace(workspace_id="ws"), (row,))
    )
    (saved_spec,) = save.call_args.args[3]
    saved = vars(saved_spec)
    assert saved["body"] == (enrichment_only(original) if provider == "ai_ark" else original)
    assert saved["original_key"] == "audit-key"
    assert saved["ledger_id"] == row.ledger_id
    assert saved["operation_id"] == row.operation_id
    assert json.loads(json.loads(envelope)["body_utf8"]) == original
    if provider == "ai_ark":
        assert saved["normalizer_version"] == "ai_ark:enrichment-v2"


@pytest.mark.parametrize("provider", ["ai_ark", "exa"])
def test_reused_operation_projects_only_ai_ark(monkeypatch, provider):
    original = {"content": [person()]}
    envelope = {"body_utf8": json.dumps(original), "record": {"provider": provider}}
    op = research_operations.Operation(
        uuid4(), "people_roles", "succeeded", "audit-key", None, None, uuid4()
    )
    monkeypatch.setattr(research_operations, "get", AsyncMock(return_value=op))
    monkeypatch.setattr(research_operations, "job_available", AsyncMock(return_value=True))
    reader = AsyncMock(return_value=(None, json.dumps(envelope).encode()))
    monkeypatch.setattr(research_operations, "read_verified_artifact", reader)
    _, body = asyncio.run(
        research_operations.body(None, None, SimpleNamespace(workspace_id="ws"), op.operation_id)
    )
    assert body == (enrichment_only(original) if provider == "ai_ark" else original)
