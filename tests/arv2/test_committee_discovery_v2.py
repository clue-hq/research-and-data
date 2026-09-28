"""Offline contract fixtures for the approved v2 discovery/enrichment design (not live proof)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from clue_api.arv2.account_research_catalog import (
    arv2_account_profile_sha256,
    load_account_resources,
    load_person_resources,
)
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.ai_ark_client import (
    AiArkClient,
    AiArkResponseError,
    function_values,
    phone_from_record,
    role_search_body,
)
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.committee_discovery import (
    EnrichContactArgs,
    channel_identity,
    enrich_channel,
    person_tools,
)
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport


def person(subject="p1", name="Dana Test", domain="probook.ai", linkedin=True):
    return {
        "id": subject,
        "profile": {"full_name": name, "title": "VP Marketing", "birth_date": "1980-01-01"},
        "company": {"summary": {"name": "Probook"}, "link": {"domain": domain}},
        "link": {"linkedin": f"https://linkedin.com/in/{subject}"} if linkedin else {},
        "position_groups": [
            {
                "company": {"id": "company-1", "name": "Probook", "domain": domain},
                "profile": {"title": "VP Marketing"},
            }
        ],
    }


def client_with(*responses):
    wire = ScriptedTransport(
        [HttpResponse(status=status, body=json.dumps(body).encode()) for status, body in responses]
    )
    ledger, raw = MemoryLedger(), MemoryRawSink()
    client = AiArkClient(
        ProviderCaller(transport=wire, ledger=ledger, raw_sink=raw, now=lambda: datetime.now(UTC)),
        SecretStr("offline-v2"),
        min_gap_s=0,
    )
    return client, wire, ledger, raw


@pytest.mark.parametrize("channels", [["phone"], ["email", "phone"]])
def test_phone_enrichment_is_unavailable_before_provider_dispatch(channels):
    runtime = SimpleNamespace(operate=AsyncMock(), person_seed=None)
    tool = person_tools(runtime)[0]
    result = json.loads(asyncio.run(tool.ainvoke({"channels": channels})))
    assert result["code"] == "invalid_arguments"
    # Protect callers that bypass the agent tool's schema, including stale internal calls.
    with pytest.raises(RefusalError, match="Only work-email"):
        asyncio.run(enrich_channel(runtime, "phone"))
    runtime.operate.assert_not_awaited()
    assert EnrichContactArgs().channels == ["email"]


def test_smart_exact_company_shape_and_equivalent_title_fingerprints():
    first = role_search_body([" VP Marketing ", "Head of Growth", "VP Marketing"], company_id="c1")
    assert first == role_search_body(["head of growth", "vp marketing"], company_id="c1")
    assert first["contact"]["company"] == {"latest": {"any": {"include": ["c1"]}}}
    assert first["contact"]["experience"]["latest"]["title"]["any"]["include"] == {
        "mode": "SMART",
        "content": ["head of growth", "vp marketing"],
    }
    assert "seniority" not in first["contact"] and "account" not in first
    assert len(function_values()) > 500


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"domain": "x", "company_id": "c"},
        {"domain": "x", "page": -1},
        {"domain": "x", "size": 101},
        {"domain": "x", "page": 1.2},
        {"domain": "x", "seniority": ["made_up"]},
        {"domain": "x", "functions": ["made_up"]},
    ],
)
def test_invalid_roles_refused_without_wire(kwargs):
    client, wire, _, _ = client_with()
    with pytest.raises(ValueError):
        client.people_by_roles(["CEO"], **kwargs)
    assert not wire.requests


def test_role_page_metadata_empty_page_and_sensitive_scrub():
    client, wire, ledger, raw = client_with(
        (200, {"content": [person()], "totalElements": 2, "totalPages": 2, "last": False}),
        (404, {"message": "No records found"}),
    )
    result = client.people_by_roles(["Marketing"], company_id="company-1", size=1)
    assert result.people[0].ark_id == "p1" and result.has_more is True
    assert "birth_date" not in result.people[0].raw["profile"]
    result = client.people_by_roles(["Marketing"], company_id="company-1", size=1, page=1)
    assert result.people == () and result.has_more is False
    assert json.loads(wire.requests[-1].body)["page"] == 1
    assert ledger.rows[-1].outcome == "ok"
    assert "failure" not in ledger.rows[-1].extras


def test_email_id_and_phone_request_empty_accounting():
    client, wire, ledger, _ = client_with(
        (404, {"message": "No email found"}), (404, {"message": "No phone found"})
    )
    assert not client.export_email(person_id="p1").found
    assert json.loads(wire.requests[0].body) == {"id": "p1"}
    assert client.find_phone(domain="probook.ai", name="Dana Test").numbers == ()
    assert json.loads(wire.requests[1].body) == {"domain": "probook.ai", "name": "Dana Test"}
    assert all(
        r.credits == Decimal(0) and r.outcome == "ok" for r in ledger.rows if r.phase == "result"
    )


def test_malformed_success_is_not_empty_and_other_404_is_error():
    client, *_ = client_with((200, {"error": "bad"}), (404, {"message": "wrong route"}))
    with pytest.raises(AiArkResponseError):
        client.people_by_roles(["CEO"], domain="probook.ai")
    with pytest.raises(AiArkResponseError):
        client.companies_exact("probook.ai")


def test_phone_order_dedup_and_identity_is_explicit():
    phone = phone_from_record(
        {"id": "p1", "data": [["+14155550101", "junk", "+14155550101"], ["+442012345678"]]}
    )
    assert phone.numbers == ("+14155550101", "+442012345678")
    seed = {"profile": person()}
    assert channel_identity({"id": "p1"}, seed, phone=True)
    assert not channel_identity({"data": [["+14155550101"]]}, seed, phone=True)
    assert not channel_identity({"id": "p2"}, seed, phone=True)
    assert not channel_identity(
        {"id": "p1", "linkedin": "https://linkedin.com/in/other"}, seed, phone=True
    )


def test_v2_bundles_pin_all_resources_and_do_not_mutate_v1():
    account = load_account_resources(version="v2")
    assert arv2_account_profile_sha256(version="v2") == account.manifest_sha256()
    assert load_person_resources(version="v2").profile.ref == "agent-profile:arv2-person:v2"
    assert arv2_account_profile_sha256() == load_account_resources().profile.sha256


def test_channel_prices_are_inferred_not_falsely_metered():
    client, _, ledger, _ = client_with((200, {"id": "p1", "data": [["+14155550101"]]}))
    result = client.find_phone(domain="probook.ai", name="Dana Test")
    assert result.cost.credits == Decimal(5)
    assert result.cost.cost_source == "estimate"
    assert ledger.rows[-1].extras["credit_basis"] == "documented_result_arithmetic"


@pytest.mark.parametrize("operation", ["phone", "email"])
def test_success_with_wrong_channel_shape_is_not_a_not_found(operation):
    client, *_ = client_with((200, {"error": "unexpected response"}))
    with pytest.raises(AiArkResponseError):
        if operation == "phone":
            client.find_phone(domain="probook.ai", name="Dana Test")
        else:
            client.export_email(person_id="p1")


def test_phone_field_exception_requires_provider_evidence_and_preserves_prose_floor():
    from dataclasses import replace

    from clue_api.arv2.person_compliance import apply_person_floor
    from clue_core import ExtractionMethod
    from tests.arv2.test_person_compliance import _draft

    channel = _draft(
        field_key="core.direct_phone",
        value="+14155550101",
        extraction_method=ExtractionMethod.API,
        source_key="ai_ark:phone",
        artifact_key="ws/provider-response",
        markers={"provider_subject_id": "p1", "operation_id": "op1"},
    )
    assert apply_person_floor([channel], purge_unevidenced=False)[0] == [channel]
    for invalid in (
        replace(channel, artifact_key=None),
        replace(channel, markers={}),
        replace(channel, extraction_method=ExtractionMethod.LLM_SYNTHESIS),
        replace(channel, field_key="contact.facet.self_summary"),
    ):
        assert apply_person_floor([invalid], purge_unevidenced=False)[0] == []


def test_unusable_phone_data_keeps_unknown_cost_and_metered_header_wins():
    from clue_api.arv2.ai_ark_client import phone_cost_reader

    client, _, ledger, _ = client_with((200, {"id": "p1", "data": [["invalid"]]}))
    with pytest.raises(AiArkResponseError, match="unusable_phone"):
        client.find_phone(domain="probook.ai", name="Dana Test")
    assert ledger.rows[-1].credits == Decimal(5)
    assert ledger.rows[-1].extras["credit_basis"] == "unknown"
    metered = phone_cost_reader(
        HttpResponse(
            status=200,
            headers={"X-Credit": "3"},
            body=b'{"error":"malformed"}',
        )
    )
    assert metered.credits == Decimal(3) and not metered.inferred
