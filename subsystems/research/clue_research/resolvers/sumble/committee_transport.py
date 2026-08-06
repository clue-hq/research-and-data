"""Single-attempt Sumble v9 transport for no-reveal committee acquisition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import JsonValue, SecretStr

from clue_research.resolvers.http import get_json
from clue_research.resolvers.sumble import (
    SUMBLE_API_BASE,
    HttpFetcher,
    SumbleContractError,
    SumbleCreditContractViolation,
    _json_payload,
)
from clue_research.resolvers.sumble.people import (
    PEOPLE_SOURCE_KEY,
    SumblePeopleResponse,
    assert_no_contact_reveals,
    parse_people_response,
    people_poll_request,
)
from clue_research.resolvers.sumble.teams import (
    TEAMS_SOURCE_KEY,
    SumbleTeamsResponse,
    assert_no_team_contact_reveals,
    parse_teams_response,
)

type SumbleRawPayload = dict[str, JsonValue]


class SumbleCommitteeTransport(Protocol):
    def search_teams(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumbleTeamsResponse, SumbleRawPayload]: ...

    def submit_people(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]: ...

    def poll_people(
        self, request_id: str, *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]: ...


class SumbleV9CommitteeClient:
    """Minimal live client; durability and retries belong to the API coordinator."""

    def __init__(self, *, api_key: SecretStr, http: HttpFetcher = get_json) -> None:
        self._api_key = api_key
        self._http = http

    def search_teams(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumbleTeamsResponse, SumbleRawPayload]:
        payload = self._request(TEAMS_SOURCE_KEY, "/teams", body)
        response = parse_teams_response(payload)
        assert_no_team_contact_reveals(response)
        self._reconcile(response.credits_used, maximum_credits, source_key=TEAMS_SOURCE_KEY)
        return response, payload

    def submit_people(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        return self._people(body, maximum_credits=maximum_credits)

    def poll_people(
        self, request_id: str, *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        return self._people(people_poll_request(request_id), maximum_credits=maximum_credits)

    def _people(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        payload = self._request(PEOPLE_SOURCE_KEY, "/people", body)
        response = parse_people_response(payload)
        assert_no_contact_reveals(response)
        self._reconcile(response.credits_used, maximum_credits, source_key=PEOPLE_SOURCE_KEY)
        return response, payload

    def _request(self, source_key: str, path: str, body: Mapping[str, Any]) -> SumbleRawPayload:
        raw = self._http(
            f"{SUMBLE_API_BASE}{path}",
            source_key=source_key,
            method="POST",
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
            json_body=dict(body),
            retries=0,
        )
        return _json_payload(raw, source_key=source_key)

    @staticmethod
    def _reconcile(actual: int, maximum: int, *, source_key: str) -> None:
        if maximum < 0:
            raise ValueError("Sumble committee maximum credits must be non-negative")
        if actual > maximum:
            raise SumbleCreditContractViolation(
                f"{source_key}: provider charged {actual} credits above authorized {maximum}"
            )


def require_matching_people_request_id(
    response: SumblePeopleResponse, expected_request_id: str | None
) -> None:
    """Prevent a poll response from being attached to a different async operation."""

    if expected_request_id is not None and response.request_id != expected_request_id:
        raise SumbleContractError(
            "sumble_people: response request_id differs from the durable operation id"
        )


__all__ = [
    "SumbleCommitteeTransport",
    "SumbleRawPayload",
    "SumbleV9CommitteeClient",
    "require_matching_people_request_id",
]
