"""Sumble v9 core-data acquisition and snapshot-backed resolver bindings.

Sumble charges in provider credits whose realized value is returned by each response. That does
not fit the ordinary field-at-a-time live resolver lifecycle: resolving two organization fields
must not make two paid organization calls, and a process crash after a paid response must not
silently spend again.

This module therefore keeps two explicit halves:

* :class:`SumbleClient` performs one bounded provider request and returns an immutable
  :class:`SumbleSnapshot` carrying the exact credit receipt.
* :class:`SumbleSnapshotResolver` reads a previously persisted/loaded snapshot and emits ordinary
  provider-neutral tier-1 claims through the shared resolver seam. It never makes a network call.

The API composition root owns durable snapshot/receipt persistence and supplies a
:class:`SumbleSnapshotLookup`. Downstream research knows only the registered ``source_key``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, TypeAdapter

from clue_core import (
    Claim,
    CostCents,
    Entity,
    EntityId,
    EntityType,
    FieldDef,
    ResolverError,
    RetryableResolverError,
    revalidate_with,
    to_value_json,
)
from clue_research.resolvers.base import ResolvedField, build_claim, resolved_field
from clue_research.resolvers.http import get_json
from clue_research.sources import bind_resolver

SUMBLE_API_VERSION: Final = "v9"
SUMBLE_API_BASE: Final = f"https://api.sumble.com/{SUMBLE_API_VERSION}"
AUTH_REF: Final = "CLUE_SUMBLE_API_KEY"

ORGANIZATIONS_SOURCE_KEY: Final = "sumble_organizations"
JOBS_SOURCE_KEY: Final = "sumble_jobs"
TECH_STACK_SOURCE_KEY: Final = "sumble_tech_stack"
SUMBLE_SOURCE_KEYS: Final[frozenset[str]] = frozenset(
    {ORGANIZATIONS_SOURCE_KEY, JOBS_SOURCE_KEY, TECH_STACK_SOURCE_KEY}
)

_EMPLOYEE_COUNT_FIELD = "core.employee_count"
_PRIMARY_DOMAIN_FIELD = "core.primary_domain"
_INDUSTRY_FIELD = "core.industry"
_HQ_LOCATION_FIELD = "core.hq_location"
_HIRING_VELOCITY_FIELD = "account.hiring_velocity_eng"
_TECH_STACK_FIELD = "core.primary_tech_stack"
_ENGINEERING_QUERY = "job_function EQ 'Software Engineer'"

# Sumble v9 charges 1 base credit + 1 credit per *paid* attribute per matched organization. The
# identity attributes below are documented as costing nothing, so selecting them keeps the request
# at its two-credit bound while making the response normalizable.
_ORGANIZATION_FREE_ATTRIBUTES: Final[tuple[str, ...]] = ("id", "name", "url", "sumble_url")
_ORGANIZATION_FIELD_ATTRIBUTES: Final[dict[str, str]] = {
    _EMPLOYEE_COUNT_FIELD: "employee_count",
    _INDUSTRY_FIELD: "industry",
    _HQ_LOCATION_FIELD: "headquarters_country",
}
_ORGANIZATION_PAID_ATTRIBUTES: Final[tuple[str, ...]] = tuple(
    _ORGANIZATION_FIELD_ATTRIBUTES.values()
)

#: The exact field keys each pinned v9 action can *request*. Ownership (which §3.1 row a Sumble
#: source is allowed to answer) and requestability (which of them the shipped action can put on
#: the wire) are different facts: ``organization_request`` raises ``ValueError`` on any other key,
#: so every consumer must intersect its planned field set with these before dispatch. A field a
#: source owns but cannot request is an honest gap for the next source, never a fabricated value.
ORGANIZATION_SUPPORTED_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {*_ORGANIZATION_FIELD_ATTRIBUTES, _PRIMARY_DOMAIN_FIELD}
)
JOBS_SUPPORTED_FIELD_KEYS: Final[frozenset[str]] = frozenset({_HIRING_VELOCITY_FIELD})
TECH_STACK_SUPPORTED_FIELD_KEYS: Final[frozenset[str]] = frozenset({_TECH_STACK_FIELD})
SUMBLE_SUPPORTED_FIELD_KEYS_BY_SOURCE: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        ORGANIZATIONS_SOURCE_KEY: ORGANIZATION_SUPPORTED_FIELD_KEYS,
        JOBS_SOURCE_KEY: JOBS_SUPPORTED_FIELD_KEYS,
        TECH_STACK_SOURCE_KEY: TECH_STACK_SUPPORTED_FIELD_KEYS,
    }
)


def sumble_action_supports_field(field_key: str, source_key: str) -> bool:
    """Whether the pinned v9 action behind ``source_key`` can request ``field_key`` at all."""

    return field_key in SUMBLE_SUPPORTED_FIELD_KEYS_BY_SOURCE.get(source_key, frozenset())


type SumbleSourceKey = Literal["sumble_organizations", "sumble_jobs", "sumble_tech_stack"]
type HttpFetcher = Callable[..., Any]


def _json_member_span(key: str, value: object) -> str:
    """Return an exact excerpt of the canonical immutable Sumble response artifact."""

    return (
        json.dumps(key, ensure_ascii=False)
        + ":"
        + json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


class SumbleContractError(ResolverError):
    """A Sumble response or request violates the pinned v9 trial contract."""


class SumbleSchemaDrift(SumbleContractError):
    """A charged Sumble row is well-formed JSON the pinned normalization cannot key on.

    A legitimate no-match is a successful empty result (plan §5 rule 11). Silently discarding a
    row the provider *charged us for* is not: it turns a paid, matched organization into an empty
    account with no error, which is exactly how the ``select``-list drift of 2026-08-01 went
    unnoticed. Loud failure is the only honest disposition.
    """


class SumbleCreditLimitExceeded(ResolverError):
    """A request's documented maximum would exceed the trial's provider-credit cap."""


class SumbleUnboundedCreditRisk(ResolverError):
    """The endpoint has no caller-controlled maximum and needs explicit one-call approval."""


class SumbleSpendOutcomeUnknown(RetryableResolverError):
    """Transport failed after dispatching a paid call, so automatic retry could double-spend."""


class SumbleCreditContractViolation(ResolverError):
    """The provider reported more credits than the maximum authorized for a bounded request."""


class SumbleOrganizationInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str | None = None
    url: str | None = None


class SumbleOrganizationAttributes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    id: int | None = None
    slug: str | None = None
    name: str | None = None
    url: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    industry: str | None = None
    headquarters_country: str | None = None
    status: str | None = None
    status_reason: str | None = None
    sumble_url: str | None = None


class SumbleOrganizationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    input: SumbleOrganizationInput | None = None
    attributes: SumbleOrganizationAttributes = Field(default_factory=SumbleOrganizationAttributes)
    entities: tuple[dict[str, JsonValue], ...] = ()


class SumbleOrganizationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    id: str
    credits_used: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    organizations: tuple[SumbleOrganizationRow, ...]
    matched_count: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)


class SumbleJobRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    job_id: int
    sumble_url: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class SumbleJobsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    id: str
    credits_used: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    jobs: tuple[SumbleJobRow, ...]
    total: int = Field(ge=0)
    source_data_url: str | None = None


class SumbleTechStackTechnology(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    job_post_used_count: int = Field(ge=0)
    domain: str | None = None


class SumbleTechStackEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    job_post_used_count: int = Field(ge=0)


class SumbleTechStackCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    category_slug: str
    category_name: str
    category_name_full: str
    technologies: tuple[SumbleTechStackTechnology, ...]
    evidence: tuple[SumbleTechStackEvidence, ...]


class SumbleTechStackBusinessFunction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    business_function: str
    categories: tuple[SumbleTechStackCategory, ...]


class SumbleTechStackResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    id: str
    credits_used: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    organization_id: int
    organization_slug: str
    business_functions: tuple[SumbleTechStackBusinessFunction, ...]


class SumbleSnapshot(BaseModel):
    """One immutable provider response receipt loaded by a snapshot-backed resolver."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: SumbleSourceKey
    request_id: str
    credits_used: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    payload: dict[str, JsonValue]
    # Optional monetary conversion owned by the trial's billing configuration. Zero is truthful
    # when no plan-specific cents-per-credit conversion has been configured.
    cost_cents: CostCents = Decimal(0)
    estimated_max_credits: int | None = Field(default=None, ge=0)
    unbounded_call_approved: bool = False
    # Set only after the raw response is durable in clue-storage. Snapshot-backed claims copy this
    # reference so evidence remains inspectable if Sumble later changes or removes the live record.
    artifact_key: str | None = Field(default=None, min_length=1)


class SumbleSnapshotLookup(Protocol):
    """Load a durable Sumble response snapshot for one account/source pair."""

    def snapshot_for(
        self, entity_id: EntityId, source_key: SumbleSourceKey
    ) -> SumbleSnapshot | None: ...


class MappingSumbleSnapshotLookup:
    """Immutable in-memory view over snapshots already loaded by the composition root."""

    def __init__(
        self, snapshots: Mapping[tuple[EntityId, SumbleSourceKey], SumbleSnapshot]
    ) -> None:
        self._snapshots = dict(snapshots)

    def snapshot_for(
        self, entity_id: EntityId, source_key: SumbleSourceKey
    ) -> SumbleSnapshot | None:
        return self._snapshots.get((entity_id, source_key))


class MutableSumbleSnapshotLookup:
    """Process-local read-through cache populated only from durable Sumble receipts.

    The resolver protocol is synchronous, so it cannot read the async artifact store itself.
    Composition loads each receipt before driving a phase and places it here. A lock keeps multiple
    local trial requests from observing a partially-updated mapping; authoritative data remains the
    receipt artifact, not this cache.
    """

    def __init__(self) -> None:
        self._snapshots: dict[tuple[EntityId, SumbleSourceKey], SumbleSnapshot] = {}
        self._lock = RLock()

    def put(self, entity_id: EntityId, snapshot: SumbleSnapshot) -> None:
        if snapshot.artifact_key is None:
            raise ValueError("only durable Sumble snapshots may be bound to resolvers")
        with self._lock:
            self._snapshots[(entity_id, snapshot.source_key)] = snapshot

    def snapshot_for(
        self, entity_id: EntityId, source_key: SumbleSourceKey
    ) -> SumbleSnapshot | None:
        with self._lock:
            return self._snapshots.get((entity_id, source_key))


@dataclass
class SumbleCreditBudget:
    """One trial's provider-unit budget.

    Bounded endpoints are authorized against their documented worst case before dispatch and
    reconciled against the response. The confirmed-tech endpoint has no caller-side result limit,
    so it can run only when ``allow_unbounded`` is explicit.
    """

    maximum: int
    spent: int = 0

    def __post_init__(self) -> None:
        if self.maximum < 0 or self.spent < 0:
            raise ValueError("Sumble credit budget values must be non-negative")

    @property
    def remaining(self) -> int:
        return max(0, self.maximum - self.spent)

    def authorize(self, estimated_max: int | None, *, allow_unbounded: bool = False) -> None:
        if estimated_max is None:
            if not allow_unbounded:
                raise SumbleUnboundedCreditRisk(
                    "Sumble tech-stack cost is one credit per returned technology and the endpoint "
                    "has no caller-side limit; explicit unbounded-call approval is required"
                )
            return
        if estimated_max > self.remaining:
            raise SumbleCreditLimitExceeded(
                f"Sumble request could use {estimated_max} credits with only "
                f"{self.remaining} remaining under the trial cap"
            )

    def reconcile(self, actual: int, *, estimated_max: int | None) -> None:
        if actual < 0:
            raise ValueError("actual Sumble credits must be non-negative")
        if estimated_max is not None and actual > estimated_max:
            raise SumbleCreditContractViolation(
                f"Sumble reported {actual} credits after a bounded maximum of {estimated_max}"
            )
        self.spent += actual


def _json_payload(payload: object, *, source_key: str) -> dict[str, JsonValue]:
    if not isinstance(payload, Mapping):
        raise SumbleContractError(f"{source_key}: response must be a JSON object")
    try:
        return TypeAdapter(dict[str, JsonValue]).validate_python(payload)
    except Exception as exc:
        raise SumbleContractError(f"{source_key}: response must contain JSON values") from exc


def organization_request(domain: str, *, field_keys: tuple[str, ...]) -> tuple[dict[str, Any], int]:
    """Build the exact coalesced v9 organization wire body and documented maximum."""

    unknown = sorted(set(field_keys) - {*_ORGANIZATION_FIELD_ATTRIBUTES, _PRIMARY_DOMAIN_FIELD})
    if unknown:
        raise ValueError(f"unsupported Sumble organization fields: {unknown!r}")
    paid = sorted(
        {
            _ORGANIZATION_FIELD_ATTRIBUTES[field_key]
            for field_key in field_keys
            if field_key in _ORGANIZATION_FIELD_ATTRIBUTES
        }
    )
    return (
        {
            "organizations": [{"url": domain}],
            "select": {"attributes": [*_ORGANIZATION_FREE_ATTRIBUTES, *paid]},
        },
        1 + len(paid),
    )


def engineering_jobs_request(organization_id: int, *, limit: int = 1) -> tuple[dict[str, Any], int]:
    """Build the bounded v9 engineering-jobs body; returned rows are the charged unit."""

    if not 1 <= limit <= 200:
        raise ValueError("Sumble jobs limit must be between 1 and 200")
    return (
        {
            "filter": {
                "organization_ids": [organization_id],
                "query": {"query": _ENGINEERING_QUERY},
            },
            "select": {"attributes": []},
            "limit": limit,
        },
        limit,
    )


class SumbleClient:
    """Minimal typed v9 client for the three first-wave core-data surfaces."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        budget: SumbleCreditBudget,
        http: HttpFetcher = get_json,
        cents_per_credit: Decimal = Decimal(0),
    ) -> None:
        if cents_per_credit < 0:
            raise ValueError("cents_per_credit must be non-negative")
        self._api_key = api_key
        self._budget = budget
        self._http = http
        self._cents_per_credit = cents_per_credit

    def resolve_organization(
        self,
        domain: str,
        *,
        field_keys: tuple[str, ...] = (_EMPLOYEE_COUNT_FIELD,),
    ) -> SumbleSnapshot:
        # ``select`` is exhaustive, not additive: v9 returns *only* the attributes named here.
        # The identity attributes are documented as free ("1 credit per paid attribute requested
        # (`id`, `name`, `slug`, `url`, and `sumble_url` are free)"), but "free" governs price, not
        # delivery — an unrequested free attribute is still absent, which is what silently voided
        # the 2026-08-01 live match. Request every attribute the normalization keys on.
        #
        # Cost is therefore unchanged: 1 base credit + 1 paid attribute (``employee_count``) = 2.
        body, estimated_max = organization_request(domain, field_keys=field_keys)
        snapshot = self._request(
            source_key=ORGANIZATIONS_SOURCE_KEY,
            method="POST",
            path="/organizations",
            json_body=body,
            response_model=SumbleOrganizationsResponse,
            estimated_max=estimated_max,
        )
        _validate_requested_organization(snapshot.payload, requested_domain=domain)
        return snapshot

    def engineering_jobs(self, organization_id: int, *, limit: int = 1) -> SumbleSnapshot:
        if not 1 <= limit <= 200:
            raise ValueError("Sumble jobs limit must be between 1 and 200")
        # No paid attributes: each returned row costs only its one base credit. ``total`` carries
        # the count matched by the engineering-function filter while ``limit`` bounds paid rows.
        #
        # ``filter.query`` is v9's ``Query`` object (``{"query": "<advanced query>"}``), not the
        # bare string: ``JobsFilter.query`` is ``$ref: Query`` and ``JobsFilter`` forbids additional
        # properties, so a bare string is rejected HTTP 422 before any job is ever matched.
        body, estimated_max = engineering_jobs_request(organization_id, limit=limit)
        return self._request(
            source_key=JOBS_SOURCE_KEY,
            method="POST",
            path="/jobs",
            json_body=body,
            response_model=SumbleJobsResponse,
            estimated_max=estimated_max,
        )

    def tech_stack(self, organization_id: int, *, allow_unbounded: bool = False) -> SumbleSnapshot:
        return self._request(
            source_key=TECH_STACK_SOURCE_KEY,
            method="GET",
            path=f"/organizations/{organization_id}/techs",
            json_body=None,
            response_model=SumbleTechStackResponse,
            estimated_max=None,
            allow_unbounded=allow_unbounded,
        )

    def _request(
        self,
        *,
        source_key: SumbleSourceKey,
        method: str,
        path: str,
        json_body: dict[str, Any] | None,
        response_model: type[
            SumbleOrganizationsResponse | SumbleJobsResponse | SumbleTechStackResponse
        ],
        estimated_max: int | None,
        allow_unbounded: bool = False,
    ) -> SumbleSnapshot:
        self._budget.authorize(estimated_max, allow_unbounded=allow_unbounded)
        url = f"{SUMBLE_API_BASE}{path}"
        try:
            # Paid provider calls are deliberately single-attempt. A transport loss after dispatch
            # has an indeterminate spend outcome; the durable caller reconciles it rather than
            # allowing the generic HTTP helper to repeat the charge.
            raw = self._http(
                url,
                source_key=source_key,
                method=method,
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                json_body=json_body,
                retries=0,
            )
        except RetryableResolverError as exc:
            raise SumbleSpendOutcomeUnknown(
                f"{source_key}: paid request outcome is unknown; reconcile before retry"
            ) from exc
        payload = _json_payload(raw, source_key=source_key)
        try:
            response = response_model.model_validate(payload)
        # Pydantic's exact error stays chained and is not exposed as provider data.
        except Exception as exc:
            raise SumbleContractError(f"{source_key}: invalid v9 response shape") from exc
        self._budget.reconcile(response.credits_used, estimated_max=estimated_max)
        return SumbleSnapshot(
            source_key=source_key,
            request_id=response.id,
            credits_used=response.credits_used,
            credits_remaining=response.credits_remaining,
            payload=payload,
            cost_cents=Decimal(response.credits_used) * self._cents_per_credit,
            estimated_max_credits=estimated_max,
            unbounded_call_approved=allow_unbounded,
        )


def _identified_rows(
    response: SumbleOrganizationsResponse,
) -> tuple[SumbleOrganizationRow, ...]:
    """Return the rows carrying the identity attributes every Sumble binding keys on.

    Accepting zero rows while the provider reports at least one *charged* match means the pinned
    ``select`` list and the live response have drifted apart. That is raised, never absorbed: a
    paid match must not be able to disappear into an empty result.
    """

    identified = tuple(
        row
        for row in response.organizations
        if row.attributes.id is not None and row.attributes.url
    )
    matched_count = response.matched_count
    if not identified and matched_count is not None and matched_count >= 1:
        returned_attributes = sorted(
            {
                str(name)
                for row in response.organizations
                for name in row.attributes.model_dump(exclude_none=True)
            }
        )
        raise SumbleSchemaDrift(
            f"{ORGANIZATIONS_SOURCE_KEY}: response reports matched_count={matched_count} but no "
            "returned organization carries the required 'id' and 'url' attributes "
            f"(attributes present: {returned_attributes or ['<none>']}); the pinned select list "
            f"{[*_ORGANIZATION_FREE_ATTRIBUTES, *_ORGANIZATION_PAID_ATTRIBUTES]!r} and the live "
            "v9 contract have drifted"
        )
    if len(identified) > 1:
        raise SumbleSchemaDrift(
            f"{ORGANIZATIONS_SOURCE_KEY}: one requested organization returned "
            f"{len(identified)} identified matches"
        )
    for row in identified:
        if row.input is not None and row.input.url:
            requested = _canonical_domain(row.input.url)
            returned_domain = _canonical_domain(row.attributes.url or "")
            if not requested or not returned_domain or requested != returned_domain:
                raise SumbleSchemaDrift(
                    f"{ORGANIZATIONS_SOURCE_KEY}: returned organization domain does not match "
                    "the echoed request domain"
                )
    return identified


def _canonical_domain(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _validate_requested_organization(payload: Mapping[str, Any], *, requested_domain: str) -> None:
    response = SumbleOrganizationsResponse.model_validate(payload)
    identified = _identified_rows(response)
    if not identified:
        return
    returned = _canonical_domain(identified[0].attributes.url or "")
    requested = _canonical_domain(requested_domain)
    if not requested or returned != requested:
        raise SumbleSchemaDrift(
            f"{ORGANIZATIONS_SOURCE_KEY}: returned organization domain does not match the request"
        )


def normalize_organization(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    response = SumbleOrganizationsResponse.model_validate(payload)
    matched = _identified_rows(response)
    if len(matched) != 1:
        return []
    row = matched[0]
    source_url = row.attributes.sumble_url or "https://sumble.com"
    if field.field_key == _EMPLOYEE_COUNT_FIELD and row.attributes.employee_count is not None:
        return [
            resolved_field(
                str(field.field_key),
                row.attributes.employee_count,
                source_url=source_url,
                confidence=0.9,
            ).model_copy(
                update={
                    "evidence_span": _json_member_span(
                        "employee_count", row.attributes.employee_count
                    )
                }
            )
        ]
    if field.field_key == _PRIMARY_DOMAIN_FIELD and row.attributes.url:
        return [
            resolved_field(
                str(field.field_key),
                row.attributes.url,
                source_url=source_url,
                confidence=0.98,
            ).model_copy(update={"evidence_span": _json_member_span("url", row.attributes.url)})
        ]
    if field.field_key == _INDUSTRY_FIELD and row.attributes.industry:
        return [
            resolved_field(
                str(field.field_key),
                row.attributes.industry,
                source_url=source_url,
                confidence=0.9,
            ).model_copy(
                update={"evidence_span": _json_member_span("industry", row.attributes.industry)}
            )
        ]
    if field.field_key == _HQ_LOCATION_FIELD and row.attributes.headquarters_country:
        country = row.attributes.headquarters_country
        return [
            resolved_field(
                str(field.field_key),
                {"raw": country, "country": country, "country_code": country},
                source_url=source_url,
                confidence=0.88,
            ).model_copy(
                update={"evidence_span": _json_member_span("headquarters_country", country)}
            )
        ]
    return []


def matched_organization_id(payload: Mapping[str, Any]) -> int | None:
    """Return the sole matched Sumble organization id, or ``None`` for no/ambiguous match.

    Raises :class:`SumbleSchemaDrift` when the provider charged for a match this binding cannot
    identify; the dependent jobs/tech-stack calls key on this id, so a silent ``None`` would
    quietly degrade the whole account into "no data" (plan §5 rule 11 covers only a *true*
    no-match).
    """

    response = SumbleOrganizationsResponse.model_validate(payload)
    matched = _identified_rows(response)
    if len(matched) != 1:
        return None
    return matched[0].attributes.id


def normalize_jobs(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    if field.field_key != _HIRING_VELOCITY_FIELD:
        return []
    response = SumbleJobsResponse.model_validate(payload)
    source_url = response.source_data_url or "https://sumble.com"
    return [
        ResolvedField(
            field_key=field.field_key,
            value=response.total,
            source_url=source_url,
            evidence_span=_json_member_span("total", response.total),
            confidence=0.85,
        )
    ]


def normalize_tech_stack(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    if field.field_key != _TECH_STACK_FIELD:
        return []
    response = SumbleTechStackResponse.model_validate(payload)
    technologies = sorted(
        {
            tech.name
            for business_function in response.business_functions
            for category in business_function.categories
            for tech in category.technologies
        },
        key=str.casefold,
    )
    if not technologies:
        return []
    return [
        ResolvedField(
            field_key=field.field_key,
            value=to_value_json(technologies),
            source_url=(f"{SUMBLE_API_BASE}/organizations/{response.organization_id}/techs"),
            evidence_span=_json_member_span(
                "business_functions", payload.get("business_functions", [])
            ),
            confidence=0.92,
        )
    ]


type Normalizer = Callable[[Mapping[str, Any], FieldDef], list[ResolvedField]]


class SumbleSnapshotResolver:
    """A tier-1 resolver over one durable Sumble snapshot kind; never performs acquisition."""

    tier = 1

    def __init__(
        self,
        *,
        source_key: SumbleSourceKey,
        snapshots: SumbleSnapshotLookup,
        normalize: Normalizer,
        charge_field: str,
    ) -> None:
        self._source_key = source_key
        self._snapshots = snapshots
        self._normalize = normalize
        self._charge_field = charge_field

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if entity.entity_type is not EntityType.ACCOUNT:
            return []
        snapshot = self._snapshots.snapshot_for(entity.entity_id, self._source_key)
        if snapshot is None:
            return []
        resolved = self._normalize(snapshot.payload, field)
        cost = snapshot.cost_cents if field.field_key == self._charge_field else Decimal(0)
        claims = [
            build_claim(
                entity,
                item,
                cost_cents=cost if index == 0 else Decimal(0),
            )
            for index, item in enumerate(resolved)
        ]
        if snapshot.artifact_key is None:
            return claims
        return [revalidate_with(claim, artifact_key=snapshot.artifact_key) for claim in claims]


def build_sumble_resolvers(
    snapshots: SumbleSnapshotLookup,
) -> dict[SumbleSourceKey, SumbleSnapshotResolver]:
    """Build all first-wave Sumble resolvers over one loaded snapshot view."""

    return {
        ORGANIZATIONS_SOURCE_KEY: SumbleSnapshotResolver(
            source_key=ORGANIZATIONS_SOURCE_KEY,
            snapshots=snapshots,
            normalize=normalize_organization,
            # Attribute the shared organization response cost once, to the paid employee field.
            charge_field=_EMPLOYEE_COUNT_FIELD,
        ),
        JOBS_SOURCE_KEY: SumbleSnapshotResolver(
            source_key=JOBS_SOURCE_KEY,
            snapshots=snapshots,
            normalize=normalize_jobs,
            charge_field=_HIRING_VELOCITY_FIELD,
        ),
        TECH_STACK_SOURCE_KEY: SumbleSnapshotResolver(
            source_key=TECH_STACK_SOURCE_KEY,
            snapshots=snapshots,
            normalize=normalize_tech_stack,
            charge_field=_TECH_STACK_FIELD,
        ),
    }


def register_sumble_resolvers(snapshots: SumbleSnapshotLookup) -> None:
    """Bind first-wave Sumble snapshot resolvers behind their source keys."""

    for source_key, resolver in build_sumble_resolvers(snapshots).items():
        bind_resolver(source_key, resolver)


__all__ = [
    "AUTH_REF",
    "JOBS_SOURCE_KEY",
    "JOBS_SUPPORTED_FIELD_KEYS",
    "ORGANIZATION_SUPPORTED_FIELD_KEYS",
    "MappingSumbleSnapshotLookup",
    "MutableSumbleSnapshotLookup",
    "ORGANIZATIONS_SOURCE_KEY",
    "SUMBLE_API_BASE",
    "SUMBLE_API_VERSION",
    "SUMBLE_SOURCE_KEYS",
    "SUMBLE_SUPPORTED_FIELD_KEYS_BY_SOURCE",
    "SumbleClient",
    "SumbleContractError",
    "SumbleCreditBudget",
    "SumbleCreditContractViolation",
    "SumbleCreditLimitExceeded",
    "SumbleJobsResponse",
    "SumbleOrganizationRow",
    "SumbleOrganizationsResponse",
    "SumbleSchemaDrift",
    "SumbleSnapshot",
    "SumbleSnapshotLookup",
    "SumbleSnapshotResolver",
    "SumbleSourceKey",
    "SumbleSpendOutcomeUnknown",
    "SumbleTechStackResponse",
    "SumbleUnboundedCreditRisk",
    "TECH_STACK_SOURCE_KEY",
    "TECH_STACK_SUPPORTED_FIELD_KEYS",
    "build_sumble_resolvers",
    "engineering_jobs_request",
    "matched_organization_id",
    "normalize_jobs",
    "normalize_organization",
    "normalize_tech_stack",
    "organization_request",
    "register_sumble_resolvers",
    "sumble_action_supports_field",
]
