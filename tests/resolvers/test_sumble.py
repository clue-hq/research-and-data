"""Sumble v9 contract, credit-safety, normalization, and snapshot-resolver tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from clue_core import (
    Entity,
    EntityType,
    ExtractionMethod,
    FieldDef,
    PassKind,
    RetryableResolverError,
    new_entity_id,
)
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_BASE,
    TECH_STACK_SOURCE_KEY,
    MappingSumbleSnapshotLookup,
    SumbleClient,
    SumbleContractError,
    SumbleCreditBudget,
    SumbleCreditContractViolation,
    SumbleCreditLimitExceeded,
    SumbleSchemaDrift,
    SumbleSnapshot,
    SumbleSpendOutcomeUnknown,
    SumbleUnboundedCreditRisk,
    build_sumble_resolvers,
    matched_organization_id,
    normalize_jobs,
    normalize_organization,
    normalize_tech_stack,
    organization_request,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "clue_trial" / "sumble"


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((_FIXTURES / name).read_text())
    assert isinstance(payload, dict)
    return payload


def _field(field_key: str, value_type: str = "str") -> FieldDef:
    return FieldDef(
        field_key=field_key,
        value_type=value_type,
        pass_kind=PassKind.SCORING,
    )


def _account() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


class RecordingHttp:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        return self.payload


def test_organization_request_is_fixed_and_credit_bounded() -> None:
    http = RecordingHttp(_fixture("organizations_match.json"))
    budget = SumbleCreditBudget(maximum=2)
    snapshot = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=budget,
        http=http,
        cents_per_credit=Decimal("0.5"),
    ).resolve_organization("acme.example")

    assert budget.spent == 2
    assert snapshot.credits_used == 2
    assert snapshot.cost_cents == Decimal(1)
    assert snapshot.estimated_max_credits == 2
    assert http.calls == [
        {
            "url": f"{SUMBLE_API_BASE}/organizations",
            "source_key": ORGANIZATIONS_SOURCE_KEY,
            "method": "POST",
            "headers": {"Authorization": "Bearer fixture"},
            "json_body": {
                "organizations": [{"url": "acme.example"}],
                # Every attribute the normalization keys on is selected: v9 returns only what the
                # select list names. id/name/url/sumble_url are documented free, so the bound
                # stays 1 base + 1 paid (employee_count) = 2 credits.
                "select": {
                    "attributes": [
                        "id",
                        "name",
                        "url",
                        "sumble_url",
                        "employee_count",
                    ]
                },
            },
            "retries": 0,
        }
    ]


def test_s1_organization_request_selects_only_planned_paid_fields() -> None:
    body, maximum = organization_request(
        "acme.example",
        field_keys=("core.hq_location", "core.industry", "core.primary_domain"),
    )

    assert maximum == 3
    assert body == {
        "organizations": [{"url": "acme.example"}],
        "select": {
            "attributes": [
                "id",
                "name",
                "url",
                "sumble_url",
                "headquarters_country",
                "industry",
            ]
        },
    }

    with pytest.raises(ValueError, match="unsupported Sumble organization fields"):
        organization_request("acme.example", field_keys=("core.annual_revenue",))


def test_jobs_request_wraps_the_advanced_query_in_the_v9_query_object() -> None:
    """``filter.query`` is a ``Query`` object, never the bare advanced-query string.

    The bare string is the live 2026-08-01 drift: v9 answered HTTP 422
    (``model_attributes_type`` at ``body.filter.query``), so the hiring-velocity field was never
    resolved at all. ``JobsFilter`` forbids additional properties, so the wrapper is the contract.
    """

    http = RecordingHttp(_fixture("jobs_engineering.json"))
    budget = SumbleCreditBudget(maximum=1)
    snapshot = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=budget,
        http=http,
        cents_per_credit=Decimal("0.5"),
    ).engineering_jobs(1726684)

    assert budget.spent == 1
    assert snapshot.estimated_max_credits == 1
    assert http.calls == [
        {
            "url": f"{SUMBLE_API_BASE}/jobs",
            "source_key": JOBS_SOURCE_KEY,
            "method": "POST",
            "headers": {"Authorization": "Bearer fixture"},
            "json_body": {
                "filter": {
                    "organization_ids": [1726684],
                    "query": {"query": "job_function EQ 'Software Engineer'"},
                },
                "select": {"attributes": []},
                "limit": 1,
            },
            "retries": 0,
        }
    ]


def test_bounded_request_is_rejected_before_transport_when_cap_is_too_small() -> None:
    http = RecordingHttp(_fixture("organizations_match.json"))
    client = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=SumbleCreditBudget(maximum=1),
        http=http,
    )

    with pytest.raises(SumbleCreditLimitExceeded):
        client.resolve_organization("acme.example")
    assert http.calls == []


def test_provider_cannot_report_more_than_authorized_bound() -> None:
    payload: dict[str, Any] = _fixture("organizations_match.json")
    payload["credits_used"] = 3
    client = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=SumbleCreditBudget(maximum=3),
        http=RecordingHttp(payload),
    )

    with pytest.raises(SumbleCreditContractViolation):
        client.resolve_organization("acme.example")


def test_tech_stack_requires_explicit_unbounded_call_approval() -> None:
    http = RecordingHttp(_fixture("tech_stack_confirmed.json"))
    client = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=SumbleCreditBudget(maximum=10),
        http=http,
    )

    with pytest.raises(SumbleUnboundedCreditRisk):
        client.tech_stack(1726684)
    assert http.calls == []

    snapshot = client.tech_stack(1726684, allow_unbounded=True)
    assert snapshot.unbounded_call_approved is True
    assert snapshot.estimated_max_credits is None
    assert snapshot.credits_used == 3


def test_paid_transport_failure_is_not_automatically_retried() -> None:
    def fail(*args: Any, **kwargs: Any) -> object:
        del args, kwargs
        raise RetryableResolverError("transport lost")

    client = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=SumbleCreditBudget(maximum=2),
        http=fail,
    )
    with pytest.raises(SumbleSpendOutcomeUnknown):
        client.resolve_organization("acme.example")


def test_non_object_and_schema_drift_fail_closed() -> None:
    payloads: tuple[object, ...] = ([], {"id": "missing-credit-fields"})
    for payload in payloads:
        client = SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=2),
            http=RecordingHttp(payload),
        )
        with pytest.raises(SumbleContractError):
            client.resolve_organization("acme.example")


def test_organization_identity_mismatch_fails_closed_after_one_paid_response() -> None:
    payload = _fixture("organizations_match.json")
    payload["organizations"][0]["attributes"]["url"] = "wrong.example"
    http = RecordingHttp(payload)
    client = SumbleClient(
        api_key=SecretStr("fixture"),
        budget=SumbleCreditBudget(maximum=2),
        http=http,
    )

    with pytest.raises(SumbleSchemaDrift, match="domain does not match"):
        client.resolve_organization("acme.example")
    assert len(http.calls) == 1


def test_organization_normalization_produces_direct_fields_and_hard_miss() -> None:
    payload = _fixture("organizations_match.json")
    headcount = normalize_organization(payload, _field("core.employee_count", "int"))
    domain = normalize_organization(payload, _field("core.primary_domain"))

    assert [item.value for item in headcount] == [120]
    assert [item.value for item in domain] == ["acme.example"]
    assert headcount[0].source_url == "https://sumble.com/l/org/acme"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert headcount[0].evidence_span in canonical
    assert domain[0].evidence_span in canonical
    assert (
        normalize_organization(
            _fixture("organizations_unmatched.json"),
            _field("core.employee_count", "int"),
        )
        == []
    )


def test_s1_organization_normalizes_documented_industry_and_headquarters() -> None:
    payload = _fixture("organizations_match.json")
    payload["organizations"][0]["attributes"].update(
        {"industry": "Healthcare", "headquarters_country": "US"}
    )

    industry = normalize_organization(payload, _field("core.industry"))
    headquarters = normalize_organization(payload, _field("core.hq_location", "object"))

    assert [item.value for item in industry] == ["Healthcare"]
    assert [item.value for item in headquarters] == [
        {"raw": "US", "country": "US", "country_code": "US"}
    ]


def test_matched_organization_id_is_recovered_for_the_jobs_call() -> None:
    assert matched_organization_id(_fixture("organizations_match.json")) == 1726684
    assert matched_organization_id(_fixture("organizations_unmatched.json")) is None


def test_paid_matched_row_missing_identity_attributes_fails_loudly() -> None:
    """A matched-and-charged row the normalizer cannot key on is drift, never a silent miss.

    This is the live 2026-08-01 payload shape: Sumble returned only the selected
    ``employee_count``, so the identity-gated normalization accepted zero rows and the run
    lost a paid organization match without a single error.
    """

    payload = _fixture("organizations_attributes_only.json")
    assert payload["matched_count"] == 1

    with pytest.raises(SumbleSchemaDrift) as normalization:
        normalize_organization(payload, _field("core.employee_count", "int"))
    assert "matched_count" in str(normalization.value)

    with pytest.raises(SumbleSchemaDrift):
        matched_organization_id(payload)


def test_schema_drift_is_a_sumble_contract_error() -> None:
    assert issubclass(SumbleSchemaDrift, SumbleContractError)


def test_bound_resolver_raises_rather_than_emitting_zero_claims_on_drift() -> None:
    """The seam the run actually uses must fail, not return an empty claim list."""

    account = _account()
    snapshot = SumbleSnapshot(
        source_key=ORGANIZATIONS_SOURCE_KEY,
        request_id="org-attrs-drift",
        credits_used=2,
        credits_remaining=998,
        payload=_fixture("organizations_attributes_only.json"),
        estimated_max_credits=2,
        artifact_key="workspace/provider-response",
    )
    lookup = MappingSumbleSnapshotLookup({(account.entity_id, ORGANIZATIONS_SOURCE_KEY): snapshot})
    resolver = build_sumble_resolvers(lookup)[ORGANIZATIONS_SOURCE_KEY]

    with pytest.raises(SumbleSchemaDrift):
        resolver.resolve(account, _field("core.employee_count", "int"))


def test_a_true_no_match_stays_a_successful_empty_result() -> None:
    """Drift detection must not convert a legitimate unmatched domain into an error."""

    payload = _fixture("organizations_unmatched.json")
    assert payload["matched_count"] == 0
    assert normalize_organization(payload, _field("core.employee_count", "int")) == []
    assert matched_organization_id(payload) is None


def test_jobs_normalization_is_an_explicit_engineering_activity_proxy() -> None:
    payload = _fixture("jobs_engineering.json")
    resolved = normalize_jobs(
        payload,
        _field("account.hiring_velocity_eng", "number"),
    )

    assert [item.value for item in resolved] == [4]
    assert resolved[0].evidence_span == '"total":4'
    assert resolved[0].evidence_span in json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )


def test_tech_normalization_uses_only_confirmed_primary_technologies() -> None:
    payload = _fixture("tech_stack_confirmed.json")
    resolved = normalize_tech_stack(
        payload,
        _field("core.primary_tech_stack", "list[str]"),
    )

    assert [item.value for item in resolved] == [
        ["Amazon Web Services", "Kubernetes", "Salesforce"]
    ]
    assert '"business_functions":' in resolved[0].evidence_span
    assert resolved[0].evidence_span in json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )
    assert (
        normalize_tech_stack(
            _fixture("tech_stack_empty.json"),
            _field("core.primary_tech_stack", "list[str]"),
        )
        == []
    )


def test_snapshot_resolvers_emit_tier1_api_claims_without_network() -> None:
    account = _account()
    snapshot = SumbleSnapshot(
        source_key=ORGANIZATIONS_SOURCE_KEY,
        request_id="fixture-org-match",
        credits_used=2,
        credits_remaining=998,
        payload=_fixture("organizations_match.json"),
        cost_cents=Decimal(1),
        estimated_max_credits=2,
        artifact_key="workspace/provider-response",
    )
    lookup = MappingSumbleSnapshotLookup({(account.entity_id, ORGANIZATIONS_SOURCE_KEY): snapshot})
    resolver = build_sumble_resolvers(lookup)[ORGANIZATIONS_SOURCE_KEY]

    headcount = resolver.resolve(account, _field("core.employee_count", "int"))
    domain = resolver.resolve(account, _field("core.primary_domain"))
    assert headcount[0].source_tier == 1
    assert headcount[0].extraction_method is ExtractionMethod.API
    assert headcount[0].cost_cents == Decimal(1)
    assert headcount[0].artifact_key == "workspace/provider-response"
    assert domain[0].cost_cents == Decimal(0)

    contact = Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)
    assert resolver.resolve(contact, _field("core.employee_count", "int")) == []


def test_all_three_snapshot_resolvers_are_built_at_tier_one() -> None:
    resolvers = build_sumble_resolvers(MappingSumbleSnapshotLookup({}))
    assert set(resolvers) == {
        ORGANIZATIONS_SOURCE_KEY,
        JOBS_SOURCE_KEY,
        TECH_STACK_SOURCE_KEY,
    }
    assert {resolver.tier for resolver in resolvers.values()} == {1}
