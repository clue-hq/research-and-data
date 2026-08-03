"""M06A S2A Sumble Teams/People wire, cost, privacy, and normalization contract."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from clue_research.resolvers.sumble import SumbleContractError, SumbleSchemaDrift
from clue_research.resolvers.sumble.committee_transport import (
    SumbleV9CommitteeClient,
    require_matching_people_request_id,
)
from clue_research.resolvers.sumble.people import (
    PEOPLE_NO_REVEAL_ATTRIBUTES,
    SumbleAdvancedQuery,
    SumblePeopleStatus,
    normalize_people,
    parse_people_response,
    people_poll_request,
    people_search_request,
)
from clue_research.resolvers.sumble.teams import (
    TEAM_ATTRIBUTES,
    TEAM_JOB_COMPONENTS,
    TEAM_RELATED_PERSON_ATTRIBUTES,
    SumbleRelationshipBasis,
    normalize_teams,
    teams_search_request,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "sumble" / "v9"
_ORGANIZATION_ID = 1_726_684


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((_FIXTURES / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_people_search_is_exact_account_bounded_and_no_reveal() -> None:
    query = SumbleAdvancedQuery(
        expression="job_function EQ 'Operations' AND job_level_min EQ 'Manager'"
    )
    body, maximum = people_search_request(
        _ORGANIZATION_ID,
        limit=5,
        offset=10,
        advanced_query=query,
    )

    assert body == {
        "filter": {
            "organization_ids": [_ORGANIZATION_ID],
            "query": {"query": query.expression},
        },
        "select": {"attributes": list(PEOPLE_NO_REVEAL_ATTRIBUTES)},
        "limit": 5,
        "offset": 10,
        "order_by_column": "job_level",
        "order_by_direction": "DESC",
    }
    assert maximum == 40  # five people × (one base + seven paid attributes)
    serialized = json.dumps(body)
    assert '"email"' not in serialized
    assert '"phone"' not in serialized
    assert '"all"' not in serialized
    assert "related_people" not in serialized


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (201, 0), (1, -1), (1, 10_001)],
)
def test_people_request_rejects_unbounded_pagination(limit: int, offset: int) -> None:
    with pytest.raises(ValueError):
        people_search_request(_ORGANIZATION_ID, limit=limit, offset=offset)


def test_advanced_query_must_be_prevalidated_and_single_line() -> None:
    with pytest.raises(ValueError, match="pre-normalized"):
        SumbleAdvancedQuery(expression=" job_function EQ 'Operations' ")
    with pytest.raises(ValueError, match="single line"):
        SumbleAdvancedQuery(expression="job_function EQ 'Operations'\nOR true")


def test_people_poll_body_contains_request_id_alone() -> None:
    assert people_poll_request(" request-123 ") == {"request_id": "request-123"}
    with pytest.raises(ValueError, match="non-empty"):
        people_poll_request("   ")


def test_committee_transport_is_single_attempt_and_request_id_locked() -> None:
    calls: list[dict[str, Any]] = []

    def http(url: str, **kwargs: Any) -> object:
        calls.append({"url": url, **kwargs})
        return _fixture("people_pending.json")

    client = SumbleV9CommitteeClient(api_key=SecretStr("fixture-secret"), http=http)
    response, _payload = client.submit_people({"filter": {}}, maximum_credits=16)
    assert response.status is SumblePeopleStatus.PENDING
    assert calls[0]["retries"] == 0
    assert calls[0]["headers"] == {"Authorization": "Bearer fixture-secret"}
    require_matching_people_request_id(response, response.request_id)
    with pytest.raises(SumbleContractError, match="request_id differs"):
        require_matching_people_request_id(response, "different-operation")


def test_committee_transport_rejects_unrequested_contact_before_returning_payload() -> None:
    payload = _fixture("teams_succeeded.json")
    payload["teams"][0]["related_people"][0]["attributes"]["email"] = "hidden@example.test"

    def http(_url: str, **_kwargs: Any) -> object:
        return payload

    client = SumbleV9CommitteeClient(api_key=SecretStr("fixture-secret"), http=http)
    with pytest.raises(SumbleContractError, match="no-reveal"):
        client.search_teams({"filter": {}}, maximum_credits=12)


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    [
        ("people_pending.json", SumblePeopleStatus.PENDING),
        ("people_running.json", SumblePeopleStatus.RUNNING),
        ("people_failed.json", SumblePeopleStatus.FAILED),
    ],
)
def test_nonterminal_or_failed_people_statuses_charge_zero(
    fixture_name: str, expected_status: SumblePeopleStatus
) -> None:
    response = parse_people_response(_fixture(fixture_name))
    assert response.status is expected_status
    assert response.credits_used == 0
    assert response.people is None


def test_non_succeeded_people_response_with_charge_fails_contract() -> None:
    payload = _fixture("people_running.json")
    payload["credits_used"] = 1
    with pytest.raises(SumbleContractError, match="invalid v9 async response"):
        parse_people_response(payload)


def test_succeeded_people_normalize_and_target_lock() -> None:
    payload = _fixture("people_succeeded.json")
    response = parse_people_response(payload)
    assert response.status is SumblePeopleStatus.SUCCEEDED
    assert response.credits_used == 16

    normalized = normalize_people(payload, expected_organization_id=_ORGANIZATION_ID)
    assert len(normalized.people) == 1
    person = normalized.people[0]
    assert person.provider_person_id == 1001
    assert person.name == "Alex Morgan"
    assert person.job_title == "VP of Operations"
    assert person.current_employer_organization_id == _ORGANIZATION_ID
    assert person.has_current_strong_key is True
    assert normalized.target_unlocked_person_ids == (1002,)

    # The same terminal result may be observed on a later free poll; durable settlement belongs to
    # S2B and keys the first non-zero succeeded receipt, not every materialization.
    repeated = copy.deepcopy(payload)
    repeated["credits_used"] = 0
    assert parse_people_response(repeated).credits_used == 0


def test_people_contact_reveal_fails_closed() -> None:
    payload = _fixture("people_succeeded.json")
    payload["people"][0]["attributes"]["email"] = "alex@example.test"
    with pytest.raises(SumbleContractError, match="no-reveal"):
        normalize_people(payload, expected_organization_id=_ORGANIZATION_ID)


def test_people_charged_row_without_provider_identity_fails_loudly() -> None:
    payload = _fixture("people_succeeded.json")
    payload["people"][0]["person_id"] = None
    with pytest.raises(SumbleSchemaDrift, match="lacks person_id"):
        normalize_people(payload, expected_organization_id=_ORGANIZATION_ID)


def test_sumble_person_id_is_provenance_not_current_strong_admission_key() -> None:
    payload = _fixture("people_succeeded.json")
    payload["people"][0]["attributes"]["linkedin_url"] = None
    normalized = normalize_people(payload, expected_organization_id=_ORGANIZATION_ID)
    assert normalized.people[0].provider_person_id == 1001
    assert normalized.people[0].has_current_strong_key is False


def test_teams_search_is_bounded_explicit_and_no_reveal() -> None:
    body, maximum = teams_search_request(
        _ORGANIZATION_ID,
        limit=2,
        max_people_per_team=3,
        max_jobs_per_team=2,
        since=date(2026, 1, 1),
        advanced_query=SumbleAdvancedQuery(expression="job_function EQ 'Operations'"),
    )

    assert body == {
        "filter": {
            "organization_ids": [_ORGANIZATION_ID],
            "query": {"query": "job_function EQ 'Operations'"},
            "since": "2026-01-01",
        },
        "select": {
            "attributes": list(TEAM_ATTRIBUTES),
            "related_people": {
                "attributes": list(TEAM_RELATED_PERSON_ATTRIBUTES),
                "max_per_team": 3,
            },
            "job_posts": {
                "components": list(TEAM_JOB_COMPONENTS),
                "max_per_team": 2,
                "since": "2026-01-01",
            },
        },
        "limit": 2,
        "offset": 0,
        "order_by_column": "jobs_count",
        "order_by_direction": "DESC",
    }
    assert maximum == 26  # two teams × (base + seven attrs + three people + two jobs)
    serialized = json.dumps(body)
    assert '"email"' not in serialized
    assert '"phone"' not in serialized
    assert '"all"' not in serialized


@pytest.mark.parametrize(
    ("limit", "people_cap", "jobs_cap"),
    [(0, 1, 1), (201, 1, 1), (1, 0, 1), (1, 101, 1), (1, 1, 0), (1, 1, 101)],
)
def test_teams_request_rejects_unbounded_axes(limit: int, people_cap: int, jobs_cap: int) -> None:
    with pytest.raises(ValueError):
        teams_search_request(
            _ORGANIZATION_ID,
            limit=limit,
            max_people_per_team=people_cap,
            max_jobs_per_team=jobs_cap,
        )


def test_teams_normalize_org_map_with_inferred_relationship_label() -> None:
    normalized = normalize_teams(
        _fixture("teams_succeeded.json"),
        expected_organization_id=_ORGANIZATION_ID,
        max_people_per_team=3,
        max_jobs_per_team=2,
    )

    assert normalized.target_unlocked_team_ids == ()
    assert normalized.target_unlocked_person_ids == ()
    assert len(normalized.teams) == 1
    team = normalized.teams[0]
    assert team.provider_team_id == 501
    assert [crumb.name for crumb in team.breadcrumbs] == ["Operations"]
    assert [technology.name for technology in team.technologies] == ["Epic"]
    assert team.provider_job_ids == (7001,)
    member = team.related_people[0]
    assert member.provider_person_id == 1001
    assert member.relationship_basis is SumbleRelationshipBasis.PROVIDER_INFERRED_TEAM_MEMBERSHIP
    assert member.relationship_confidence == pytest.approx(0.92)


def test_teams_contact_reveal_and_returned_cap_drift_fail_closed() -> None:
    contact_payload = _fixture("teams_succeeded.json")
    contact_payload["teams"][0]["related_people"][0]["attributes"]["phone"] = "+15555550100"
    with pytest.raises(SumbleContractError, match="no-reveal"):
        normalize_teams(
            contact_payload,
            expected_organization_id=_ORGANIZATION_ID,
            max_people_per_team=3,
            max_jobs_per_team=2,
        )

    cap_payload = _fixture("teams_succeeded.json")
    cap_payload["teams"][0]["related_people"].append(
        copy.deepcopy(cap_payload["teams"][0]["related_people"][0])
    )
    with pytest.raises(SumbleSchemaDrift, match="exceeded the requested cap"):
        normalize_teams(
            cap_payload,
            expected_organization_id=_ORGANIZATION_ID,
            max_people_per_team=1,
            max_jobs_per_team=2,
        )


def test_teams_target_mismatch_is_explicit_not_silently_admitted() -> None:
    payload = _fixture("teams_succeeded.json")
    payload["teams"][0]["attributes"]["organization"]["organization_id"] = 9_999_999
    normalized = normalize_teams(
        payload,
        expected_organization_id=_ORGANIZATION_ID,
        max_people_per_team=3,
        max_jobs_per_team=2,
    )
    assert normalized.teams == ()
    assert normalized.target_unlocked_team_ids == (501,)


def test_team_person_target_mismatch_is_explicit_without_dropping_team() -> None:
    payload = _fixture("teams_succeeded.json")
    employer = payload["teams"][0]["related_people"][0]["attributes"]["current_employer"]
    employer["organization_id"] = 9_999_999
    normalized = normalize_teams(
        payload,
        expected_organization_id=_ORGANIZATION_ID,
        max_people_per_team=3,
        max_jobs_per_team=2,
    )
    assert len(normalized.teams) == 1
    assert normalized.teams[0].related_people == ()
    assert normalized.target_unlocked_person_ids == (1001,)


def test_charged_team_row_without_provider_identity_fails_loudly() -> None:
    payload = _fixture("teams_succeeded.json")
    payload["teams"][0]["team_id"] = None
    with pytest.raises(SumbleSchemaDrift, match="lacks team_id"):
        normalize_teams(
            payload,
            expected_organization_id=_ORGANIZATION_ID,
            max_people_per_team=3,
            max_jobs_per_team=2,
        )
