"""Sumble v9 Teams wire contract and organization-map normalization for S2A."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from clue_research.resolvers.sumble import SumbleContractError, SumbleSchemaDrift
from clue_research.resolvers.sumble.people import (
    SumbleAdvancedQuery,
    SumblePersonAttributes,
)

TEAMS_SOURCE_KEY: Final = "sumble_teams"
TEAM_ATTRIBUTES: Final[tuple[str, ...]] = (
    "organization",
    "breadcrumbs",
    "jobs_count",
    "technology_list",
    "job_function_list",
    "location_list",
    "last_activity",
)
TEAM_RELATED_PERSON_ATTRIBUTES: Final[tuple[str, ...]] = (
    "name",
    "linkedin_url",
    "job_title",
    "job_function",
    "job_level",
    "location",
    "country",
    "current_employer",
    "confidence",
)
TEAM_JOB_COMPONENTS: Final[tuple[str, ...]] = (
    "job_details",
    "technologies",
    "job_functions",
    "job_level",
)
_CONTACT_ATTRIBUTES: Final[frozenset[str]] = frozenset({"email", "phone"})


class SumbleRelationshipBasis(StrEnum):
    PROVIDER_INFERRED_TEAM_MEMBERSHIP = "provider_inferred_team_membership"


class SumbleTeamOrganization(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    organization_id: int = Field(ge=1)
    name: str | None = None
    sumble_url: str | None = None


class SumbleTeamBreadcrumb(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    team_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1)
    slug: str | None = None
    sumble_url: str | None = None


class SumbleTeamTechnology(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    used: bool = False
    jobs_count: int | None = Field(default=None, ge=0)


class SumbleTeamJobFunction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    jobs_count: int | None = Field(default=None, ge=0)


class SumbleTeamLocation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    jobs_count: int | None = Field(default=None, ge=0)


class SumbleTeamMembershipFeature(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    match_type: str = Field(min_length=1)
    name: str | None = None
    slug: str | None = None
    is_parent: bool = False
    score: float


class SumbleTeamMembershipConfidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    score: float = Field(ge=0.0, le=1.0)
    matched_features: tuple[SumbleTeamMembershipFeature, ...] = ()


class SumbleTeamRelatedPersonRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    person_id: int = Field(ge=1)
    sumble_url: str = Field(min_length=1)
    confidence: SumbleTeamMembershipConfidence | None = None
    attributes: SumblePersonAttributes | None = None


class SumbleTeamJobPostRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    job_id: int = Field(ge=1)
    sumble_url: str | None = None
    attributes: dict[str, Any] | None = None


class SumbleTeamAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    organization: SumbleTeamOrganization | None = None
    breadcrumbs: tuple[SumbleTeamBreadcrumb, ...] | None = None
    jobs_count: int | None = Field(default=None, ge=0)
    technology_list: tuple[SumbleTeamTechnology, ...] | None = None
    job_function_list: tuple[SumbleTeamJobFunction, ...] | None = None
    location_list: tuple[SumbleTeamLocation, ...] | None = None
    last_activity: str | None = None


class SumbleTeamRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    team_id: int | None = Field(default=None, ge=1)
    name: str | None = None
    sumble_url: str | None = None
    attributes: SumbleTeamAttributes | None = None
    related_people: tuple[SumbleTeamRelatedPersonRow, ...] | None = None
    job_posts: tuple[SumbleTeamJobPostRow, ...] | None = None


class SumbleTeamsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    id: str = Field(min_length=1)
    credits_used: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    teams: tuple[SumbleTeamRow, ...]
    matched_count: int | None = Field(default=None, ge=0)
    total: int = Field(ge=0)
    source_data_url: str | None = None


class SumbleTeamMemberRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_person_id: int = Field(ge=1)
    source_url: str = Field(min_length=1)
    linkedin_url: str | None = None
    name: str | None = None
    job_title: str | None = None
    job_function: str | None = None
    job_level: str | None = None
    location: str | None = None
    country: str | None = None
    current_employer_organization_id: int = Field(ge=1)
    current_employer_name: str | None = None
    current_role_start_date: str | None = None
    relationship_basis: SumbleRelationshipBasis = (
        SumbleRelationshipBasis.PROVIDER_INFERRED_TEAM_MEMBERSHIP
    )
    relationship_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    relationship_features: tuple[SumbleTeamMembershipFeature, ...] = ()


class SumbleTeamRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_team_id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    breadcrumbs: tuple[SumbleTeamBreadcrumb, ...] = ()
    jobs_count: int | None = Field(default=None, ge=0)
    technologies: tuple[SumbleTeamTechnology, ...] = ()
    job_functions: tuple[SumbleTeamJobFunction, ...] = ()
    locations: tuple[SumbleTeamLocation, ...] = ()
    last_activity: str | None = None
    related_people: tuple[SumbleTeamMemberRecord, ...] = ()
    provider_job_ids: tuple[int, ...] = ()


class SumbleTeamsNormalization(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    teams: tuple[SumbleTeamRecord, ...] = ()
    target_unlocked_team_ids: tuple[int, ...] = ()
    target_unlocked_person_ids: tuple[int, ...] = ()


# Documented `/v9/teams` queryable dimensions ("technologies, technology categories, job
# functions, hiring period"). Job level is deliberately absent: it is not a Teams dimension and
# querying it produced a live deterministic HTTP 400 (contract-decision note).
TEAMS_QUERY_DIMENSIONS: Final[frozenset[str]] = frozenset(
    {"technology", "technology_category", "job_function", "hiring_period"}
)


def teams_search_request(
    organization_id: int,
    *,
    limit: int,
    max_people_per_team: int,
    max_jobs_per_team: int,
    offset: int = 0,
    since: date | None = None,
    advanced_query: SumbleAdvancedQuery | None = None,
) -> tuple[dict[str, Any], int]:
    """Build a bounded exact-account Teams request and its deterministic worst-case credits."""

    if organization_id < 1:
        raise ValueError("Sumble organization id must be positive")
    if not 1 <= limit <= 200:
        raise ValueError("Sumble Teams limit must be between 1 and 200")
    if not 1 <= max_people_per_team <= 100:
        raise ValueError("Sumble related people cap must be between 1 and 100")
    if not 1 <= max_jobs_per_team <= 100:
        raise ValueError("Sumble team jobs cap must be between 1 and 100")
    if not 0 <= offset <= 10_000:
        raise ValueError("Sumble Teams offset must be between 0 and 10000")
    if _CONTACT_ATTRIBUTES.intersection(TEAM_RELATED_PERSON_ATTRIBUTES):
        raise AssertionError("S2 Teams select list must never contain contact attributes")

    filter_body: dict[str, Any] = {"organization_ids": [organization_id]}
    if advanced_query is not None:
        advanced_query.require_dimensions(TEAMS_QUERY_DIMENSIONS, endpoint="Teams")
        filter_body["query"] = {"query": advanced_query.expression}
    if since is not None:
        filter_body["since"] = since.isoformat()
    body = {
        "filter": filter_body,
        "select": {
            "attributes": list(TEAM_ATTRIBUTES),
            "related_people": {
                "attributes": list(TEAM_RELATED_PERSON_ATTRIBUTES),
                "max_per_team": max_people_per_team,
            },
            "job_posts": {
                "components": list(TEAM_JOB_COMPONENTS),
                "max_per_team": max_jobs_per_team,
                **({"since": since.isoformat()} if since is not None else {}),
            },
        },
        "limit": limit,
        "offset": offset,
        "order_by_column": "jobs_count",
        "order_by_direction": "DESC",
    }
    maximum_credits = limit * (1 + len(TEAM_ATTRIBUTES) + max_people_per_team + max_jobs_per_team)
    return body, maximum_credits


def parse_teams_response(payload: Mapping[str, Any]) -> SumbleTeamsResponse:
    try:
        return SumbleTeamsResponse.model_validate(payload)
    except Exception as exc:
        raise SumbleContractError("sumble_teams: invalid v9 response shape") from exc


def assert_no_team_contact_reveals(response: SumbleTeamsResponse) -> None:
    """Reject unexpected contact values before the raw response enters durable storage."""

    for team in response.teams:
        for person in team.related_people or ():
            attributes = person.attributes
            if attributes is not None and (attributes.email or attributes.phone):
                raise SumbleContractError(
                    "sumble_teams: S2 no-reveal response unexpectedly contained email or phone"
                )


def normalize_teams(
    payload: Mapping[str, Any],
    *,
    expected_organization_id: int,
    max_people_per_team: int,
    max_jobs_per_team: int,
) -> SumbleTeamsNormalization:
    """Normalize bounded Teams rows with explicit target-lock and relationship semantics."""

    response = parse_teams_response(payload)
    records: list[SumbleTeamRecord] = []
    unlocked_teams: list[int] = []
    unlocked_people: list[int] = []
    for row in response.teams:
        if (
            row.team_id is None
            or row.name is None
            or row.sumble_url is None
            or row.attributes is None
        ):
            raise SumbleSchemaDrift(
                "sumble_teams: returned row lacks team_id, name, sumble_url, or attributes"
            )
        organization = row.attributes.organization
        if organization is None or organization.organization_id != expected_organization_id:
            unlocked_teams.append(row.team_id)
            continue
        related_rows = row.related_people or ()
        job_rows = row.job_posts or ()
        if len(related_rows) > max_people_per_team:
            raise SumbleSchemaDrift("sumble_teams: related people exceeded the requested cap")
        if len(job_rows) > max_jobs_per_team:
            raise SumbleSchemaDrift("sumble_teams: job posts exceeded the requested cap")

        members: list[SumbleTeamMemberRecord] = []
        for person in related_rows:
            attributes = person.attributes
            if attributes is None:
                unlocked_people.append(person.person_id)
                continue
            if attributes.email or attributes.phone:
                raise SumbleContractError(
                    "sumble_teams: S2 no-reveal response unexpectedly contained email or phone"
                )
            employer = attributes.current_employer
            if employer is None or employer.organization_id != expected_organization_id:
                unlocked_people.append(person.person_id)
                continue
            confidence = person.confidence
            members.append(
                SumbleTeamMemberRecord(
                    provider_person_id=person.person_id,
                    source_url=person.sumble_url,
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
                    relationship_confidence=confidence.score if confidence is not None else None,
                    relationship_features=(
                        confidence.matched_features if confidence is not None else ()
                    ),
                )
            )
        records.append(
            SumbleTeamRecord(
                provider_team_id=row.team_id,
                organization_id=organization.organization_id,
                name=row.name,
                source_url=row.sumble_url,
                breadcrumbs=row.attributes.breadcrumbs or (),
                jobs_count=row.attributes.jobs_count,
                technologies=row.attributes.technology_list or (),
                job_functions=row.attributes.job_function_list or (),
                locations=row.attributes.location_list or (),
                last_activity=row.attributes.last_activity,
                related_people=tuple(members),
                provider_job_ids=tuple(job.job_id for job in job_rows),
            )
        )
    return SumbleTeamsNormalization(
        teams=tuple(records),
        target_unlocked_team_ids=tuple(unlocked_teams),
        target_unlocked_person_ids=tuple(unlocked_people),
    )


__all__ = [
    "TEAMS_SOURCE_KEY",
    "TEAM_ATTRIBUTES",
    "TEAM_JOB_COMPONENTS",
    "TEAM_RELATED_PERSON_ATTRIBUTES",
    "SumbleRelationshipBasis",
    "SumbleTeamMemberRecord",
    "SumbleTeamRecord",
    "SumbleTeamsNormalization",
    "SumbleTeamsResponse",
    "assert_no_team_contact_reveals",
    "normalize_teams",
    "parse_teams_response",
    "teams_search_request",
]
