"""Sumble v9 People wire contract for bounded, no-reveal committee acquisition.

This module owns only provider-local request/response modeling and normalization.  It does not
dispatch HTTP, persist operations, construct contacts, or infer committee roles.  S2B supplies the
durable asynchronous submit/poll lifecycle; S2C adapts ready records to ``CommitteeSource``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_research.resolvers.sumble import SumbleContractError, SumbleSchemaDrift

PEOPLE_SOURCE_KEY: Final = "sumble_people"

# ``name`` is the only selected attribute documented as free.  Person id and Sumble URL are
# always included for free and therefore do not appear in ``select.attributes``.
PEOPLE_NO_REVEAL_ATTRIBUTES: Final[tuple[str, ...]] = (
    "name",
    "linkedin_url",
    "job_title",
    "job_function",
    "job_level",
    "location",
    "country",
    "current_employer",
)
_CONTACT_ATTRIBUTES: Final[frozenset[str]] = frozenset({"email", "phone"})
_FREE_SELECTED_ATTRIBUTES: Final[frozenset[str]] = frozenset({"name"})


class SumblePeopleStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SumbleAdvancedQuery(BaseModel):
    """An already-compiled Sumble advanced expression, never arbitrary user prompt text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expression: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def _normalized_expression(self) -> SumbleAdvancedQuery:
        if self.expression != self.expression.strip():
            raise ValueError("Sumble advanced query must be pre-normalized")
        if "\n" in self.expression or "\r" in self.expression:
            raise ValueError("Sumble advanced query must be a single line")
        return self


class SumbleCurrentEmployer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    organization_id: int = Field(ge=1)
    name: str | None = None
    start_date: str | None = None
    sumble_url: str | None = None


class SumblePersonAttributes(BaseModel):
    """Tolerant provider shape; contact fields exist only so S2 can reject their presence."""

    model_config = ConfigDict(frozen=True, extra="allow")

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    job_title: str | None = None
    job_function: str | None = None
    job_level: str | None = None
    location: str | None = None
    country: str | None = None
    current_employer: SumbleCurrentEmployer | None = None


class SumblePersonRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    person_id: int | None = Field(default=None, ge=1)
    sumble_url: str | None = None
    attributes: SumblePersonAttributes | None = None


class SumblePeopleResponse(BaseModel):
    """The v9 async response shared by kickoff and every poll."""

    model_config = ConfigDict(frozen=True, extra="allow")

    # The OpenAPI marks ``id`` required, but the async prose examples omit it on kickoff/poll.
    # ``request_id`` is the v9 operation identity; tolerate an absent envelope id.
    id: str | None = Field(default=None, min_length=1)
    credits_used: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    request_id: str = Field(min_length=1)
    status: SumblePeopleStatus
    people: tuple[SumblePersonRow, ...] | None = None
    matched_count: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    source_data_url: str | None = None

    @model_validator(mode="after")
    def _status_contract(self) -> SumblePeopleResponse:
        if self.status is not SumblePeopleStatus.SUCCEEDED:
            if self.credits_used != 0:
                raise ValueError("non-succeeded Sumble People responses must charge zero credits")
            if self.people not in (None, ()):
                raise ValueError("non-succeeded Sumble People responses cannot contain people")
            return self
        if self.people is None or self.total is None:
            raise ValueError("succeeded Sumble People response requires people and total")
        return self


class SumblePersonRecord(BaseModel):
    """One target-locked provider person; still only a candidate input, never a contact claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_person_id: int = Field(ge=1)
    source_url: str = Field(min_length=1)
    linkedin_url: str | None = None
    name: str = Field(min_length=1)
    job_title: str | None = None
    job_function: str | None = None
    job_level: str | None = None
    location: str | None = None
    country: str | None = None
    current_employer_organization_id: int = Field(ge=1)
    current_employer_name: str | None = None
    current_role_start_date: str | None = None

    @property
    def has_current_strong_key(self) -> bool:
        return bool((self.linkedin_url or "").strip())


class SumblePeopleNormalization(BaseModel):
    """Ready people plus explicit rows excluded by exact-account target locking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    people: tuple[SumblePersonRecord, ...] = ()
    target_unlocked_person_ids: tuple[int, ...] = ()


def people_search_request(
    organization_id: int,
    *,
    limit: int,
    offset: int = 0,
    advanced_query: SumbleAdvancedQuery | None = None,
) -> tuple[dict[str, Any], int]:
    """Build an exact-account, no-reveal People kickoff and its worst-case provider credits."""

    if organization_id < 1:
        raise ValueError("Sumble organization id must be positive")
    if not 1 <= limit <= 200:
        raise ValueError("Sumble People limit must be between 1 and 200")
    if not 0 <= offset <= 10_000:
        raise ValueError("Sumble People offset must be between 0 and 10000")
    if _CONTACT_ATTRIBUTES.intersection(PEOPLE_NO_REVEAL_ATTRIBUTES):
        raise AssertionError("S2 People select list must never contain contact attributes")

    filter_body: dict[str, Any] = {"organization_ids": [organization_id]}
    if advanced_query is not None:
        filter_body["query"] = {"query": advanced_query.expression}
    body = {
        "filter": filter_body,
        "select": {"attributes": list(PEOPLE_NO_REVEAL_ATTRIBUTES)},
        "limit": limit,
        "offset": offset,
        "order_by_column": "job_level",
        "order_by_direction": "DESC",
    }
    paid_attribute_count = len(set(PEOPLE_NO_REVEAL_ATTRIBUTES) - _FREE_SELECTED_ATTRIBUTES)
    maximum_credits = limit * (1 + paid_attribute_count)
    return body, maximum_credits


def people_poll_request(request_id: str) -> dict[str, str]:
    """Build the poll body; v9 requires the request id to be sent alone."""

    normalized = request_id.strip()
    if not normalized:
        raise ValueError("Sumble People request id must be non-empty")
    return {"request_id": normalized}


def parse_people_response(payload: Mapping[str, Any]) -> SumblePeopleResponse:
    try:
        return SumblePeopleResponse.model_validate(payload)
    except Exception as exc:
        raise SumbleContractError("sumble_people: invalid v9 async response shape") from exc


def assert_no_contact_reveals(response: SumblePeopleResponse) -> None:
    """Fail closed if a supposedly no-reveal operation contains contact data."""

    for row in response.people or ():
        attributes = row.attributes
        if attributes is not None and (attributes.email or attributes.phone):
            raise SumbleContractError(
                "sumble_people: S2 no-reveal response unexpectedly contained email or phone"
            )


def normalize_people(
    payload: Mapping[str, Any], *, expected_organization_id: int
) -> SumblePeopleNormalization:
    """Normalize a ready People snapshot and enforce exact-account target locking."""

    response = parse_people_response(payload)
    if response.status is not SumblePeopleStatus.SUCCEEDED:
        raise SumbleContractError("sumble_people: snapshot is not ready for materialization")
    assert_no_contact_reveals(response)

    records: list[SumblePersonRecord] = []
    target_unlocked: list[int] = []
    for row in response.people or ():
        attributes = row.attributes
        if (
            row.person_id is None
            or row.sumble_url is None
            or attributes is None
            or not attributes.name
        ):
            raise SumbleSchemaDrift(
                "sumble_people: returned row lacks person_id, sumble_url, attributes, or name"
            )
        employer = attributes.current_employer
        if employer is None or employer.organization_id != expected_organization_id:
            target_unlocked.append(row.person_id)
            continue
        records.append(
            SumblePersonRecord(
                provider_person_id=row.person_id,
                source_url=row.sumble_url,
                linkedin_url=attributes.linkedin_url,
                name=attributes.name,
                job_title=attributes.job_title,
                job_function=attributes.job_function,
                job_level=attributes.job_level,
                location=attributes.location,
                country=attributes.country,
                current_employer_organization_id=employer.organization_id,
                current_employer_name=employer.name,
                current_role_start_date=employer.start_date,
            )
        )
    return SumblePeopleNormalization(
        people=tuple(records),
        target_unlocked_person_ids=tuple(target_unlocked),
    )


__all__ = [
    "PEOPLE_NO_REVEAL_ATTRIBUTES",
    "PEOPLE_SOURCE_KEY",
    "SumbleAdvancedQuery",
    "SumbleCurrentEmployer",
    "SumblePeopleNormalization",
    "SumblePeopleResponse",
    "SumblePeopleStatus",
    "SumblePersonAttributes",
    "SumblePersonRecord",
    "SumblePersonRow",
    "assert_no_contact_reveals",
    "normalize_people",
    "parse_people_response",
    "people_poll_request",
    "people_search_request",
]
