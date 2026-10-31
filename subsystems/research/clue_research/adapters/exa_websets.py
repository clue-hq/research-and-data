"""Typed Exa Websets ``v0`` transport used by account discovery.

The adapter owns only the provider boundary: request/response shapes, authentication, HTTP
timeouts, safe GET retries, and a secret-safe error taxonomy.  It does not own durable replay,
budget reservation, project state, account identity, claims, or seal readiness; the API
composition root binds this transport to the provider-neutral D1 repository.

Create is deliberately attempted at most once per method call.  A timeout or transport failure
after dispatch can mean Exa accepted a paid Webset even though the caller saw no response.  Only
the durable composition layer may decide what happens next, by looking up the deterministic
``externalId`` before it considers another create.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

import httpx
from annotated_types import Ge
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from clue_obs.otel import apply_attributes, traced_step

EXA_WEBSETS_SOURCE_KEY = "exa_websets"
EXA_WEBSETS_API_VERSION = "v0"
EXA_WEBSETS_API_BASE = "https://api.exa.ai/websets/v0"
EXA_WEBSETS_CONTRACT_VERSION = "exa-websets-v0-openapi-2026-08-03"
EXA_WEBSETS_AUTH_REF = "CLUE_EXA_API_KEY"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExaWebsetEntityType(StrEnum):
    COMPANY = "company"
    PERSON = "person"
    ARTICLE = "article"
    RESEARCH_PAPER = "research_paper"
    CUSTOM = "custom"


class ExaWebsetStatus(StrEnum):
    IDLE = "idle"
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"


class ExaWebsetSearchStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELED = "canceled"


class ExaWebsetSearchBehavior(StrEnum):
    OVERRIDE = "override"
    APPEND = "append"


class ExaImportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ExaImportFormat(StrEnum):
    CSV = "csv"
    WEBSET = "webset"


class ExaWebsetEnrichmentFormat(StrEnum):
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    OPTIONS = "options"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"


class ExaWebhookEventType(StrEnum):
    WEBSET_CREATED = "webset.created"
    WEBSET_DELETED = "webset.deleted"
    WEBSET_PAUSED = "webset.paused"
    WEBSET_IDLE = "webset.idle"
    SEARCH_CREATED = "webset.search.created"
    SEARCH_CANCELED = "webset.search.canceled"
    SEARCH_COMPLETED = "webset.search.completed"
    SEARCH_UPDATED = "webset.search.updated"
    IMPORT_CREATED = "import.created"
    IMPORT_COMPLETED = "import.completed"
    ITEM_CREATED = "webset.item.created"
    ITEM_ENRICHED = "webset.item.enriched"
    MONITOR_CREATED = "monitor.created"
    MONITOR_UPDATED = "monitor.updated"
    MONITOR_DELETED = "monitor.deleted"
    MONITOR_RUN_CREATED = "monitor.run.created"
    MONITOR_RUN_COMPLETED = "monitor.run.completed"
    EXPORT_CREATED = "webset.export.created"
    EXPORT_COMPLETED = "webset.export.completed"


class ExaWebsetEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ExaWebsetEntityType
    description: str | None = Field(default=None, min_length=2, max_length=200)

    @model_validator(mode="after")
    def _custom_description_matches_type(self) -> ExaWebsetEntity:
        if self.type is ExaWebsetEntityType.CUSTOM and self.description is None:
            raise ValueError("a custom Exa entity requires a description")
        if self.type is not ExaWebsetEntityType.CUSTOM and self.description is not None:
            raise ValueError("only a custom Exa entity may carry a description")
        return self


class ExaCreateCriterion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1, max_length=1_000)


class ExaEnrichmentOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: NonEmptyStr


class ExaCreateEnrichment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1, max_length=5_000)
    format: ExaWebsetEnrichmentFormat | None = None
    options: tuple[ExaEnrichmentOption, ...] = Field(default=(), min_length=0, max_length=150)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _options_match_format(self) -> ExaCreateEnrichment:
        if self.format is ExaWebsetEnrichmentFormat.OPTIONS and not self.options:
            raise ValueError("an options enrichment requires at least one option")
        if self.format is not ExaWebsetEnrichmentFormat.OPTIONS and self.options:
            raise ValueError("enrichment options require format='options'")
        return self


class ExaCreateSearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    query: str = Field(min_length=1, max_length=5_000)
    count: int = Field(ge=1)
    entity: ExaWebsetEntity | None = None
    criteria: tuple[ExaCreateCriterion, ...] = Field(default=(), max_length=5)
    max_people_per_company: int | None = Field(
        default=None,
        ge=1,
        alias="maxPeoplePerCompany",
    )
    recall: bool | None = None


class ExaCreateImportCsvOptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: int = Field(default=0, ge=0)


class ExaCreateImportRequest(BaseModel):
    """Pinned CSV import request. The presigned upload URL exists only in the response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    size: int = Field(ge=1, le=50_000_000)
    count: int = Field(ge=1)
    format: Literal["csv"] = "csv"
    entity: ExaWebsetEntity
    title: NonEmptyStr
    csv: ExaCreateImportCsvOptions = ExaCreateImportCsvOptions()
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _supported_entity(self) -> ExaCreateImportRequest:
        if self.entity.type is ExaWebsetEntityType.CUSTOM:
            raise ValueError("targeted CSV imports do not support custom entities")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            # ``format`` is a required discriminator in Exa's live import contract.  It has a
            # single legal value and therefore a local default, but omitting model defaults from
            # the wire body removes the required field and Exa rejects the request before creating
            # an import.  Keep the complete pinned request shape here; unlike optional Webset
            # collections, these CSV defaults are provider-significant contract fields.
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class ExaCreateImportRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["import", "webset"]
    id: NonEmptyStr
    evaluate: bool | None = None


class ExaCreateWebsetRequest(BaseModel):
    """Pinned subset of the current ``CreateWebsetParameters`` schema.

    Request models reject unknown fields: provider contract changes must be explicit.  Empty
    optional collections are excluded from canonical wire bytes so the stored request is exactly
    what the transport sends.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    search: ExaCreateSearch | None = None
    imports: tuple[ExaCreateImportRef, ...] = Field(default=(), alias="import")
    title: str | None = Field(default=None, min_length=1)
    enrichments: tuple[ExaCreateEnrichment, ...] = Field(default=(), max_length=10)
    external_id: str = Field(
        min_length=1,
        max_length=300,
        alias="externalId",
    )
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_acquisition_source(self) -> ExaCreateWebsetRequest:
        if self.search is None and not self.imports:
            raise ValueError("an Exa Webset requires a search or import")
        return self

    def wire_dict(self) -> dict[str, JsonValue]:
        raw = self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_defaults=True,
        )
        return dict(raw)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.wire_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


class ExaResponseCriterion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    description: NonEmptyStr
    success_rate: float = Field(
        ge=0,
        le=100,
        alias="successRate",
    )


class ExaWebsetSourceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    source: Literal["import", "webset"]
    id: NonEmptyStr


class ExaWebsetScopeRelationship(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    definition: NonEmptyStr
    limit: int = Field(ge=1, le=10)


class ExaWebsetScopeRef(ExaWebsetSourceRef):
    relationship: ExaWebsetScopeRelationship | None = None


class ExaWebsetSearchProgress(BaseModel):
    """Current required progress shape.

    Exa documents counters as JSON ``number`` and returns integral values in production.  Decimal
    preserves a valid ``3.0`` so terminal reconciliation can require integral semantics without
    accidentally skipping the check on account of Python's runtime number type.
    """

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    found: Decimal = Field(ge=0)
    analyzed: Decimal = Field(ge=0)
    completion: Decimal = Field(ge=0, le=100)
    time_left: Decimal | None = Field(alias="timeLeft")


class ExaWebsetRecallBounds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    min: Decimal = Field(ge=0)
    max: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> ExaWebsetRecallBounds:
        if self.max < self.min:
            raise ValueError("Exa recall maximum is below its minimum")
        return self


class ExaWebsetRecallExpected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    total: Decimal = Field(ge=0)
    confidence: Literal["high", "medium", "low"]
    bounds: ExaWebsetRecallBounds


class ExaWebsetRecall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    expected: ExaWebsetRecallExpected
    reasoning: str


class ExaResponseSearch(BaseModel):
    """Typed identity-bearing portion of ``WebsetSearch``; future additive fields are retained."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["webset_search"]
    webset_id: NonEmptyStr = Field(
        alias="websetId",
    )
    status: ExaWebsetSearchStatus
    query: NonEmptyStr
    entity: ExaWebsetEntity | None
    criteria: tuple[ExaResponseCriterion, ...]
    count: Annotated[int, Ge(1)]
    max_people_per_company: int | None = Field(alias="maxPeoplePerCompany")
    behavior: ExaWebsetSearchBehavior = ExaWebsetSearchBehavior.OVERRIDE
    exclude: tuple[ExaWebsetSourceRef, ...]
    scope: tuple[ExaWebsetScopeRef, ...]
    progress: ExaWebsetSearchProgress
    recall: ExaWebsetRecall | None
    metadata: dict[str, str] = Field(default_factory=dict)
    canceled_at: datetime | None = Field(alias="canceledAt")
    canceled_reason: Literal["webset_deleted", "webset_canceled", "out_of_credits"] | None = Field(
        alias="canceledReason"
    )
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ExaResponseEnrichment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["webset_enrichment"]
    status: Literal["pending", "canceled", "completed"]
    webset_id: NonEmptyStr = Field(alias="websetId")
    title: str | None
    description: NonEmptyStr
    format: ExaWebsetEnrichmentFormat | None
    options: tuple[ExaEnrichmentOption, ...] | None
    instructions: str | None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ExaImport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["import"]
    status: ExaImportStatus
    format: ExaImportFormat
    entity: ExaWebsetEntity | None
    title: str
    count: Decimal = Field(ge=0)
    metadata: dict[str, str]
    failed_reason: (
        Literal["invalid_format", "invalid_file_content", "missing_identifier"] | None
    ) = Field(alias="failedReason")
    failed_at: datetime | None = Field(alias="failedAt")
    failed_message: str | None = Field(alias="failedMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @property
    def integral_count(self) -> int:
        if self.count != self.count.to_integral_value():
            raise ValueError("Exa import count is not integral")
        return int(self.count)


class ExaCreateImportResponse(ExaImport):
    upload_url: SecretStr = Field(alias="uploadUrl")
    upload_valid_until: datetime = Field(alias="uploadValidUntil")

    def sanitized_bytes(self) -> bytes:
        payload = self.model_dump(mode="json", by_alias=True)
        payload["uploadUrl"] = "[REDACTED_PRESIGNED_URL]"
        payload["redaction"] = "presigned_upload_url_credential"
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ExaImportExchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    status_code: int
    request_id: str | None = None
    response: ExaCreateImportResponse


class ExaWebset(BaseModel):
    """Pinned identity/lifecycle portion of Exa's ``Webset`` response.

    Provider response models allow additive properties because raw bytes are always preserved and
    later D3/D4 slices will pin their pagination/item shapes separately.  Required identifiers and
    lifecycle fields still fail loudly on drift.
    """

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["webset"]
    status: ExaWebsetStatus
    external_id: str | None = Field(alias="externalId")
    title: str | None
    searches: tuple[ExaResponseSearch, ...]
    imports: tuple[ExaImport, ...]
    enrichments: tuple[ExaResponseEnrichment, ...]
    monitors: tuple[dict[str, JsonValue], ...]
    excludes: tuple[ExaWebsetSourceRef, ...]
    metadata: dict[str, str] = Field(default_factory=dict)
    dashboard_url: str = Field(alias="dashboardUrl")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ExaWebsetExchange(BaseModel):
    """One successful HTTP response plus the exact body that must be made durable."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    status_code: int
    request_id: str | None = None
    response_body: bytes
    webset: ExaWebset


class ExaWebsetReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    title: str | None
    snippet: str | None
    url: NonEmptyStr


class ExaWebsetItemEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    criterion: NonEmptyStr
    reasoning: str
    satisfied: Literal["yes", "no", "unclear"]
    references: tuple[ExaWebsetReference, ...] = ()


class ExaWebsetEnrichmentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    object: Literal["enrichment_result"]
    status: Literal["pending", "completed", "canceled"]
    format: ExaWebsetEnrichmentFormat
    result: tuple[str, ...] | None
    reasoning: str | None
    references: tuple[ExaWebsetReference, ...]
    enrichment_id: NonEmptyStr = Field(alias="enrichmentId")

    @field_validator("result")
    @classmethod
    def _nonempty_results(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("Exa enrichment result values must be non-empty")
        return value


class ExaCompanyHeadquarters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    address: str | None
    city: str | None
    state: str | None
    postal_code: str | None = Field(alias="postalCode")
    country: str | None
    country_code: str | None = Field(alias="countryCode")


class ExaCompanyFundingRound(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str | None
    date: str | None
    amount: Decimal | None


class ExaCompanyFinancials(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    revenue_annual: Decimal | None = Field(alias="revenueAnnual")
    funding_total: Decimal | None = Field(alias="fundingTotal")
    funding_latest_round: ExaCompanyFundingRound | None = Field(alias="fundingLatestRound")


class ExaCompanyWebTraffic(BaseModel):
    """Raw provider-only field; it is intentionally absent from the platform projection."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    visits_monthly: Decimal | None = Field(alias="visitsMonthly")
    unique_visitors: Decimal | None = Field(alias="uniqueVisitors")


class ExaCompanyProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    name: NonEmptyStr
    location: str | None
    employees: int | None = Field(ge=0)
    industry: str | None
    about: str | None
    logo_url: str | None = Field(alias="logoUrl")
    # Current provider-required raw fields.  Product policy deliberately does not project them.
    founded_year: Decimal | None = Field(alias="foundedYear")
    headquarters: ExaCompanyHeadquarters | None
    financials: ExaCompanyFinancials | None
    web_traffic: ExaCompanyWebTraffic | None = Field(alias="webTraffic")


class ExaWebsetItemCompanyProperties(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: Literal["company"]
    url: NonEmptyStr
    description: str
    content: str | None
    company: ExaCompanyProfile

    def discovery_fields(self) -> dict[str, JsonValue]:
        """Return only the built-in company fields approved for account discovery.

        ``foundedYear`` and ``webTraffic`` remain in the immutable raw artifact but are excluded
        here by construction, as requested by the discovery field policy.
        """

        financials = self.company.financials
        headquarters = self.company.headquarters
        latest = financials.funding_latest_round if financials else None
        financial_values = financials.model_dump(mode="json", by_alias=True) if financials else {}
        return {
            "name": self.company.name,
            "url": self.url,
            "location": self.company.location,
            "employees": self.company.employees,
            "industry": self.company.industry,
            "about": self.company.about,
            "headquarters": (
                headquarters.model_dump(mode="json", by_alias=True) if headquarters else None
            ),
            "revenueAnnual": financial_values.get("revenueAnnual"),
            "fundingTotal": financial_values.get("fundingTotal"),
            "fundingLatestRound": latest.model_dump(mode="json") if latest else None,
        }


class ExaWebsetItemPersonProperties(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: Literal["person"]


class ExaWebsetItemArticleProperties(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: Literal["article"]


class ExaWebsetItemResearchPaperProperties(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: Literal["research_paper"]


class ExaWebsetItemCustomProperties(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: Literal["custom"]


ExaWebsetItemProperties = Annotated[
    ExaWebsetItemCompanyProperties
    | ExaWebsetItemPersonProperties
    | ExaWebsetItemArticleProperties
    | ExaWebsetItemResearchPaperProperties
    | ExaWebsetItemCustomProperties,
    Field(discriminator="type"),
]


class ExaWebsetItem(BaseModel):
    """Identity-bearing Websets item; raw bytes remain the authoritative evidence."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["webset_item"]
    source: Literal["search", "import"]
    source_id: NonEmptyStr = Field(alias="sourceId")
    source_entity_id: str | None = Field(default=None, alias="sourceEntityId")
    scope_id: str | None = Field(default=None, alias="scopeId")
    webset_id: NonEmptyStr = Field(alias="websetId")
    properties: ExaWebsetItemProperties
    evaluations: tuple[ExaWebsetItemEvaluation, ...]
    enrichments: tuple[ExaWebsetEnrichmentResult, ...] | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @property
    def enrichment_results(self) -> tuple[ExaWebsetEnrichmentResult, ...]:
        return self.enrichments or ()


class ExaDiscoveryEnrichmentObservation(BaseModel):
    """One terminal enrichment mapped from provider id to the platform's logical field key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enrichment_id: NonEmptyStr
    field_key: NonEmptyStr
    format: ExaWebsetEnrichmentFormat
    result: tuple[str, ...] | None
    reasoning: str | None
    references: tuple[ExaWebsetReference, ...]

    @property
    def is_missing(self) -> bool:
        return self.result is None


class ExaDiscoveryCompanyItem(BaseModel):
    """Pure D4 projection of an immutable Exa company item.

    The full provider object remains in the raw artifact. This projection intentionally contains
    only the approved D4 company fields; notably, founded year and web traffic have no member here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_item_id: NonEmptyStr
    provider_webset_id: NonEmptyStr
    provider_source_id: NonEmptyStr
    company_url: NonEmptyStr
    company_name: NonEmptyStr
    base_fields: dict[str, JsonValue]
    evaluations: tuple[ExaWebsetItemEvaluation, ...]
    enrichments: tuple[ExaDiscoveryEnrichmentObservation, ...]
    observed_at: datetime


def normalize_exa_discovery_company_item(
    item: ExaWebsetItem,
    enrichment_definitions: tuple[ExaResponseEnrichment, ...],
) -> ExaDiscoveryCompanyItem:
    """Normalize a D3-validated company item without provider I/O or persistence.

    Terminal D3 reconciliation already proves one result per requested enrichment. D4 repeats the
    id-to-logical-field check at its own boundary so a caller cannot materialize a raw artifact
    against the wrong definition page.
    """

    if not isinstance(item.properties, ExaWebsetItemCompanyProperties):
        raise ValueError("D4 account materialization requires an Exa company item")
    definitions_by_id = {definition.id: definition for definition in enrichment_definitions}
    if len(definitions_by_id) != len(enrichment_definitions):
        raise ValueError("Exa enrichment definitions repeat an id")
    results_by_id = {result.enrichment_id: result for result in item.enrichment_results}
    if len(results_by_id) != len(item.enrichment_results):
        raise ValueError("Exa item repeats an enrichment result id")
    if results_by_id.keys() != definitions_by_id.keys():
        raise ValueError("Exa item enrichment ids do not match its terminal definitions")

    normalized: list[ExaDiscoveryEnrichmentObservation] = []
    logical_keys: set[str] = set()
    for enrichment_id, result in results_by_id.items():
        definition = definitions_by_id[enrichment_id]
        field_key = definition.metadata.get("clueFieldKey", "").strip()
        if not field_key:
            raise ValueError(f"Exa enrichment {enrichment_id!r} has no clueFieldKey")
        if field_key in logical_keys:
            raise ValueError(f"Exa enrichment definitions repeat logical field {field_key!r}")
        logical_keys.add(field_key)
        if result.status != "completed":
            raise ValueError(f"Exa enrichment {enrichment_id!r} is not terminal completed")
        expected_result_format = {
            "core.company_email": ExaWebsetEnrichmentFormat.EMAIL,
            "core.company_phone": ExaWebsetEnrichmentFormat.PHONE,
        }.get(field_key, definition.format)
        # The create/definition contract requests email and phone logical fields as ``text``.
        # Terminal item results specialize those two values to ``email``/``phone``. Other result
        # formats must remain identical to the definition.
        if expected_result_format is None or result.format is not expected_result_format:
            raise ValueError(
                f"Exa enrichment {enrichment_id!r} result format does not match its definition"
            )
        normalized.append(
            ExaDiscoveryEnrichmentObservation(
                enrichment_id=enrichment_id,
                field_key=field_key,
                format=result.format,
                result=result.result,
                reasoning=result.reasoning,
                references=result.references,
            )
        )

    return ExaDiscoveryCompanyItem(
        provider_item_id=item.id,
        provider_webset_id=item.webset_id,
        provider_source_id=item.source_id,
        company_url=item.properties.url,
        company_name=item.properties.company.name,
        base_fields=item.properties.discovery_fields(),
        evaluations=item.evaluations,
        enrichments=tuple(normalized),
        observed_at=item.updated_at,
    )


class ExaWebsetEvent(BaseModel):
    """One Exa event as delivered by webhook or the cursor-paginated event feed."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["event"]
    type: NonEmptyStr
    data: dict[str, JsonValue]
    created_at: datetime = Field(alias="createdAt")

    @model_validator(mode="after")
    def _resource_matches_event_type(self) -> ExaWebsetEvent:
        if self.type.startswith("webset.item."):
            ExaWebsetItem.model_validate(self.data)
        elif self.type.startswith("webset.search."):
            ExaResponseSearch.model_validate(self.data)
        elif self.type in {
            "webset.created",
            "webset.deleted",
            "webset.idle",
            "webset.paused",
        }:
            ExaWebset.model_validate(self.data)
        return self

    @property
    def webset_id(self) -> str | None:
        value = self.data.get("websetId")
        if not isinstance(value, str):
            value = self.data.get("id") if self.type.startswith("webset.") else None
        return value.strip() if isinstance(value, str) and value.strip() else None


class ExaItemPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    data: tuple[ExaWebsetItem, ...]
    has_more: bool = Field(alias="hasMore")
    next_cursor: str | None = Field(alias="nextCursor")

    @model_validator(mode="after")
    def _cursor_matches_has_more(self) -> ExaItemPage:
        if self.has_more != bool(self.next_cursor):
            raise ValueError("Exa item page cursor does not match hasMore")
        return self


class ExaEventPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    data: tuple[ExaWebsetEvent, ...]
    has_more: bool = Field(alias="hasMore")
    next_cursor: str | None = Field(alias="nextCursor")

    @model_validator(mode="after")
    def _cursor_matches_has_more(self) -> ExaEventPage:
        if self.has_more != bool(self.next_cursor):
            raise ValueError("Exa event page cursor does not match hasMore")
        return self


class ExaItemPageExchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    status_code: int
    request_id: str | None = None
    response_body: bytes
    page: ExaItemPage


class ExaEventPageExchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    status_code: int
    request_id: str | None = None
    response_body: bytes
    page: ExaEventPage


class ExaCreateWebhookRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[ExaWebhookEventType, ...] = Field(min_length=1, max_length=19)
    url: NonEmptyStr
    metadata: dict[str, str] = Field(default_factory=dict)


class ExaWebhook(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["webhook"]
    status: Literal["active", "inactive"]
    events: tuple[ExaWebhookEventType, ...]
    url: NonEmptyStr
    # Exa returns this only once, on creation.  SecretStr prevents accidental repr/log exposure.
    secret: SecretStr | None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ExaWebhookPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    data: tuple[ExaWebhook, ...]
    has_more: bool = Field(alias="hasMore")
    next_cursor: str | None = Field(alias="nextCursor")

    @model_validator(mode="after")
    def _cursor_matches_has_more(self) -> ExaWebhookPage:
        if self.has_more != bool(self.next_cursor):
            raise ValueError("Exa webhook page cursor does not match hasMore")
        return self


class ExaWebhookVerificationError(ValueError):
    """A webhook signature is absent, malformed, stale, or invalid."""


def verify_exa_webhook_signature(
    *,
    raw_body: bytes,
    signature_header: str,
    secret: SecretStr,
    now: datetime | None = None,
    tolerance_seconds: int = 300,
) -> datetime:
    """Verify Exa's ``HMAC-SHA256(timestamp + '.' + raw_body)`` signature."""

    if tolerance_seconds < 1:
        raise ValueError("webhook tolerance_seconds must be positive")
    timestamp_values: list[str] = []
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, separator, value = part.strip().partition("=")
        if not separator or not value:
            continue
        if key == "t":
            timestamp_values.append(value)
        elif key == "v1":
            signatures.append(value.lower())
    if len(timestamp_values) != 1 or not signatures:
        raise ExaWebhookVerificationError("malformed Exa webhook signature header")
    try:
        timestamp_seconds = int(timestamp_values[0])
        timestamp = datetime.fromtimestamp(timestamp_seconds, tz=UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise ExaWebhookVerificationError("invalid Exa webhook timestamp") from exc
    observed_now = now or datetime.now(UTC)
    if abs((observed_now - timestamp).total_seconds()) > tolerance_seconds:
        raise ExaWebhookVerificationError("stale Exa webhook timestamp")
    signed = timestamp_values[0].encode("ascii") + b"." + raw_body
    expected = hmac.new(
        secret.get_secret_value().encode("utf-8"), signed, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise ExaWebhookVerificationError("invalid Exa webhook signature")
    return timestamp


class ExaWebsetsError(RuntimeError):
    """Base provider error whose string representation contains no response body or secret."""

    retryable = False
    dispatch_uncertain = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        error_tag: str | None = None,
        response_body: bytes | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.status_code = status_code
        self.request_id = request_id
        self.error_tag = error_tag
        self.response_body = response_body
        self.retry_after_seconds = retry_after_seconds
        safe_suffix = []
        if status_code is not None:
            safe_suffix.append(f"status={status_code}")
        if error_tag:
            safe_suffix.append(f"tag={error_tag}")
        if request_id:
            safe_suffix.append(f"request_id={request_id}")
        super().__init__(message + (f" ({', '.join(safe_suffix)})" if safe_suffix else ""))


class ExaWebsetsAuthenticationError(ExaWebsetsError):
    pass


class ExaWebsetsPaymentRequired(ExaWebsetsError):
    pass


class ExaWebsetsPermissionDenied(ExaWebsetsError):
    pass


class ExaWebsetsInvalidRequest(ExaWebsetsError):
    pass


class ExaWebsetNotFound(ExaWebsetsError):
    pass


class ExaWebsetDuplicateExternalId(ExaWebsetsError):
    """Exa rejected create because the deterministic external id already exists."""


class ExaWebsetsRateLimited(ExaWebsetsError):
    retryable = True
    dispatch_uncertain = True


class ExaWebsetsTransientError(ExaWebsetsError):
    retryable = True
    dispatch_uncertain = True


class ExaWebsetsPreDispatchError(ExaWebsetsError):
    """Connection/pool acquisition failed before any request bytes could be dispatched."""

    retryable = True


class ExaWebsetsIndeterminateDispatch(ExaWebsetsError):
    """The request may have reached Exa; automatic create retry is unsafe."""

    retryable = True
    dispatch_uncertain = True


class ExaWebsetsContractDrift(ExaWebsetsError):
    # A schema mismatch can be raised after a 201 create response.  The caller must reconcile the
    # deterministic externalId instead of assuming the paid operation did not happen.
    dispatch_uncertain = True


class ExaWebsetsTransport(Protocol):
    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange: ...

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange: ...


class ExaWebsetsImportTransport(Protocol):
    """Provider calls required by an import-only targeted enrichment operation."""

    async def create_import(self, request: ExaCreateImportRequest) -> ExaImportExchange: ...

    async def upload_import_csv(self, *, upload_url: SecretStr, content: bytes) -> None: ...

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange: ...

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange: ...

    async def poll_webset(self, webset_id: str) -> ExaWebsetExchange: ...

    async def list_items(
        self, webset_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange: ...


class ExaWebsetsLifecycleTransport(Protocol):
    """Single-attempt reads; the durable worker, not the client, owns retry timing."""

    async def poll_webset(self, webset_id: str) -> ExaWebsetExchange: ...

    async def list_items(
        self, webset_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange: ...

    async def list_events(
        self, *, cursor: str | None = None, limit: int = 200
    ) -> ExaEventPageExchange: ...


class ExaWebsetsWebhookAdminTransport(Protocol):
    async def create_webhook(self, request: ExaCreateWebhookRequest) -> ExaWebhook: ...

    async def list_webhooks(
        self, *, cursor: str | None = None, limit: int = 200
    ) -> ExaWebhookPage: ...


type AsyncSleep = Callable[[float], Awaitable[None]]


class ExaWebsetsClient:
    """Async Websets v0 client with a one-attempt create and safely retryable GET lookup."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str = EXA_WEBSETS_API_BASE,
        timeout_seconds: float = 30.0,
        lookup_attempts: int = 3,
        max_retry_after_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        sleep: AsyncSleep = asyncio.sleep,
        observe: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Exa Websets timeout_seconds must be positive")
        if lookup_attempts < 1:
            raise ValueError("Exa Websets lookup_attempts must be positive")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._lookup_attempts = lookup_attempts
        self._max_retry_after_seconds = max_retry_after_seconds
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._sleep = sleep
        # The spend layer's observer (``clue_spend.record_observed_call``, bound by the platform):
        # every answer is reported so a 402 opens a provider incident (design 2026-10-31). The
        # client keeps its own transport because its dispatch taxonomy is load-bearing.
        self._observe = observe

    async def __aenter__(self) -> ExaWebsetsClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
        """Send exactly one create attempt; never hide a possibly-paid retry."""

        with traced_step(
            "provider.exa_websets.create",
            provider=EXA_WEBSETS_SOURCE_KEY,
            provider_api_version=EXA_WEBSETS_API_VERSION,
            requested_count=request.search.count
            if request.search is not None
            else len(request.imports),
            external_id=request.external_id,
        ) as span:
            exchange = await self._request(
                method="POST",
                url=f"{self._base_url}/websets",
                body=request.canonical_bytes(),
                expected_status=201,
                create=True,
            )
            apply_attributes(
                span,
                {
                    "http.status_code": exchange.status_code,
                    "provider.request_id": exchange.request_id or "",
                    "provider.operation_id": exchange.webset.id,
                },
            )
            return exchange

    async def create_import(self, request: ExaCreateImportRequest) -> ExaImportExchange:
        """Create one uncharged upload slot; never retain its presigned credential in telemetry."""

        status, request_id, response_body = await self._raw_request(
            method="POST",
            url=f"{self._base_url}/imports",
            body=request.canonical_bytes(),
            expected_status=201,
            create=True,
        )
        try:
            response = ExaCreateImportResponse.model_validate_json(response_body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa import response does not match the pinned v0 contract",
                status_code=status,
                request_id=request_id,
                # The response may contain a live presigned credential. Never propagate it into
                # durable error handling or logs on a schema mismatch.
                response_body=None,
            ) from exc
        return ExaImportExchange(status_code=status, request_id=request_id, response=response)

    async def upload_import_csv(self, *, upload_url: SecretStr, content: bytes) -> None:
        """PUT exact CSV bytes to Exa's presigned URL without Exa auth or URL logging."""

        if not content:
            raise ValueError("Exa import CSV must be non-empty")
        try:
            response = await self._client.put(
                upload_url.get_secret_value(),
                headers={"content-type": "text/csv"},
                content=content,
            )
        except (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError) as exc:
            raise ExaWebsetsPreDispatchError(
                "Exa import upload connection failed before dispatch"
            ) from exc
        except httpx.TransportError as exc:
            # Re-PUT of the same immutable bytes is safe while the presigned URL remains valid, but
            # the caller may not possess that credential after a crash. Classify the boundary
            # honestly and let the durable E1 coordinator decide whether to start a fresh import.
            raise ExaWebsetsIndeterminateDispatch(
                "Exa import upload outcome is indeterminate"
            ) from exc
        await response.aread()
        if not 200 <= response.status_code < 300:
            raise ExaWebsetsError(
                "Exa import upload was rejected",
                status_code=response.status_code,
                request_id=response.headers.get("x-request-id"),
            )

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange:
        if not webset_id_or_external_id.strip():
            raise ValueError("Exa Webset lookup id must be non-empty")
        last_error: ExaWebsetsError | None = None
        with traced_step(
            "provider.exa_websets.lookup",
            provider=EXA_WEBSETS_SOURCE_KEY,
            provider_api_version=EXA_WEBSETS_API_VERSION,
            lookup_key=webset_id_or_external_id,
        ) as span:
            for attempt in range(1, self._lookup_attempts + 1):
                try:
                    exchange = await self._request(
                        method="GET",
                        url=f"{self._base_url}/websets/{webset_id_or_external_id}",
                        body=None,
                        expected_status=200,
                        create=False,
                        final_attempt=attempt == self._lookup_attempts,
                    )
                    apply_attributes(
                        span,
                        {
                            "http.status_code": exchange.status_code,
                            "provider.request_id": exchange.request_id or "",
                            "provider.operation_id": exchange.webset.id,
                            "retry.attempt": attempt,
                        },
                    )
                    return exchange
                except (
                    ExaWebsetsPreDispatchError,
                    ExaWebsetsRateLimited,
                    ExaWebsetsTransientError,
                ) as exc:
                    last_error = exc
                    if attempt == self._lookup_attempts:
                        raise
                    delay = exc.retry_after_seconds
                    if delay is None:
                        delay = min(float(2 ** (attempt - 1)), self._max_retry_after_seconds)
                    await self._sleep(min(delay, self._max_retry_after_seconds))
            assert last_error is not None
            raise last_error

    async def poll_webset(self, webset_id: str) -> ExaWebsetExchange:
        if not webset_id.strip():
            raise ValueError("Exa Webset id must be non-empty")
        return await self._request(
            method="GET",
            url=f"{self._base_url}/websets/{webset_id}",
            body=None,
            expected_status=200,
            create=False,
        )

    async def list_items(
        self, webset_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange:
        if not webset_id.strip():
            raise ValueError("Exa Webset id must be non-empty")
        if not 1 <= limit <= 100:
            raise ValueError("Exa item page limit must be between 1 and 100")
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        status, request_id, body = await self._raw_request(
            method="GET",
            url=f"{self._base_url}/websets/{webset_id}/items",
            body=None,
            expected_status=200,
            create=False,
            params=params,
        )
        try:
            page = ExaItemPage.model_validate_json(body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa item page does not match the pinned v0 contract",
                status_code=status,
                request_id=request_id,
                response_body=body,
            ) from exc
        return ExaItemPageExchange(
            status_code=status, request_id=request_id, response_body=body, page=page
        )

    async def list_events(
        self, *, cursor: str | None = None, limit: int = 200
    ) -> ExaEventPageExchange:
        if not 1 <= limit <= 200:
            raise ValueError("Exa event page limit must be between 1 and 200")
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        status, request_id, body = await self._raw_request(
            method="GET",
            url=f"{self._base_url}/events",
            body=None,
            expected_status=200,
            create=False,
            params=params,
        )
        try:
            page = ExaEventPage.model_validate_json(body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa event page does not match the pinned v0 contract",
                status_code=status,
                request_id=request_id,
                response_body=body,
            ) from exc
        return ExaEventPageExchange(
            status_code=status, request_id=request_id, response_body=body, page=page
        )

    async def create_webhook(self, request: ExaCreateWebhookRequest) -> ExaWebhook:
        status, request_id, body = await self._raw_request(
            method="POST",
            url=f"{self._base_url}/webhooks",
            body=request.model_dump_json(by_alias=True, exclude_defaults=True).encode(),
            expected_status=200,
            create=True,
        )
        try:
            return ExaWebhook.model_validate_json(body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa webhook response does not match the pinned v0 contract",
                status_code=status,
                request_id=request_id,
                response_body=body,
            ) from exc

    async def list_webhooks(self, *, cursor: str | None = None, limit: int = 200) -> ExaWebhookPage:
        if not 1 <= limit <= 200:
            raise ValueError("Exa webhook page limit must be between 1 and 200")
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        status, request_id, body = await self._raw_request(
            method="GET",
            url=f"{self._base_url}/webhooks",
            body=None,
            expected_status=200,
            create=False,
            params=params,
        )
        try:
            return ExaWebhookPage.model_validate_json(body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa webhook list does not match the pinned v0 contract",
                status_code=status,
                request_id=request_id,
                response_body=body,
            ) from exc

    async def _request(
        self,
        *,
        method: Literal["GET", "POST"],
        url: str,
        body: bytes | None,
        expected_status: int,
        create: bool,
        final_attempt: bool = True,
    ) -> ExaWebsetExchange:
        status_code, request_id, response_body = await self._raw_request(
            method=method,
            url=url,
            body=body,
            expected_status=expected_status,
            create=create,
            final_attempt=final_attempt,
        )
        try:
            webset = ExaWebset.model_validate_json(response_body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa Websets response does not match the pinned v0 contract",
                status_code=status_code,
                request_id=request_id,
                response_body=response_body,
            ) from exc
        return ExaWebsetExchange(
            status_code=status_code,
            request_id=request_id,
            response_body=response_body,
            webset=webset,
        )

    async def _report(
        self, method: str, url: str, status: int, body: bytes, started: float
    ) -> None:
        if self._observe is None:
            return
        path = url.removeprefix(self._base_url).split("?", 1)[0].strip("/").split("/", 1)[0]
        try:
            await self._observe(
                operation=f"research.exa_websets.{method.lower()}_{path or 'root'}",
                label=f"exa_websets:{method} {path}",
                status=status,
                body=body,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception:  # noqa: BLE001 - reporting must never break the call it observes
            return

    async def _raw_request(
        self,
        *,
        method: Literal["GET", "POST"],
        url: str,
        body: bytes | None,
        expected_status: int,
        create: bool,
        params: dict[str, str | int] | None = None,
        final_attempt: bool = True,
    ) -> tuple[int, str | None, bytes]:
        headers = {
            "accept": "application/json",
            "x-api-key": self._api_key.get_secret_value(),
        }
        if body is not None:
            headers["content-type"] = "application/json"
        started = time.monotonic()
        try:
            response = await self._client.request(
                method, url, headers=headers, content=body, params=params
            )
        except (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError) as exc:
            raise ExaWebsetsPreDispatchError(
                "Exa Websets connection failed before dispatch"
            ) from exc
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError) as exc:
            error_type = ExaWebsetsIndeterminateDispatch if create else ExaWebsetsTransientError
            raise error_type("Exa Websets transport failed after dispatch") from exc
        except httpx.TransportError as exc:
            error_type = ExaWebsetsIndeterminateDispatch if create else ExaWebsetsTransientError
            raise error_type("Exa Websets transport outcome is indeterminate") from exc

        response_body = await response.aread()
        # An attempt the lookup loop will retry (a 429 or a 5xx before its last attempt) is not
        # reported: only the answer a call ends on counts toward an incident.
        retried = not final_attempt and (
            response.status_code == 429 or response.status_code >= 500
        )
        if not retried:
            await self._report(method, url, response.status_code, response_body, started)
        request_id = response.headers.get("x-request-id")
        if response.status_code != expected_status:
            raise _provider_error(
                status_code=response.status_code,
                request_id=request_id,
                response_body=response_body,
                retry_after=response.headers.get("retry-after"),
            )
        return response.status_code, request_id, response_body


def _provider_error(
    *,
    status_code: int,
    request_id: str | None,
    response_body: bytes,
    retry_after: str | None,
) -> ExaWebsetsError:
    error_tag: str | None = None
    try:
        payload: Any = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        raw_tag = payload.get("tag")
        if isinstance(raw_tag, str) and raw_tag.strip():
            error_tag = raw_tag.strip()[:100]
        raw_request_id = payload.get("requestId")
        if request_id is None and isinstance(raw_request_id, str):
            request_id = raw_request_id[:200]
    retry_after_seconds: float | None = None
    if retry_after is not None:
        try:
            retry_after_seconds = max(0.0, float(retry_after))
        except ValueError:
            retry_after_seconds = None

    error_type: type[ExaWebsetsError]
    message: str
    if status_code == 400 or status_code == 422:
        error_type, message = ExaWebsetsInvalidRequest, "Exa Websets rejected the request"
    elif status_code == 401:
        error_type, message = ExaWebsetsAuthenticationError, "Exa Websets authentication failed"
    elif status_code == 402:
        error_type, message = ExaWebsetsPaymentRequired, "Exa Websets credits are unavailable"
    elif status_code == 403:
        error_type, message = ExaWebsetsPermissionDenied, "Exa Websets access was denied"
    elif status_code == 404:
        error_type, message = ExaWebsetNotFound, "Exa Webset was not found"
    elif status_code == 409:
        error_type, message = (
            ExaWebsetDuplicateExternalId,
            "Exa Websets external id already exists",
        )
    elif status_code in {408, 425}:
        error_type, message = ExaWebsetsTransientError, "Exa Websets request timed out"
    elif status_code == 429:
        error_type, message = ExaWebsetsRateLimited, "Exa Websets rate limit was reached"
    elif status_code >= 500:
        error_type, message = ExaWebsetsTransientError, "Exa Websets service is unavailable"
    else:
        error_type, message = ExaWebsetsError, "Exa Websets returned an unexpected status"
    return error_type(
        message,
        status_code=status_code,
        request_id=request_id,
        error_tag=error_tag,
        response_body=response_body,
        retry_after_seconds=retry_after_seconds,
    )


__all__ = [
    "EXA_WEBSETS_API_BASE",
    "EXA_WEBSETS_API_VERSION",
    "EXA_WEBSETS_AUTH_REF",
    "EXA_WEBSETS_CONTRACT_VERSION",
    "EXA_WEBSETS_SOURCE_KEY",
    "ExaCreateCriterion",
    "ExaCreateEnrichment",
    "ExaCreateImportRef",
    "ExaCreateImportRequest",
    "ExaCreateImportResponse",
    "ExaCreateSearch",
    "ExaCreateWebhookRequest",
    "ExaCreateWebsetRequest",
    "ExaDiscoveryCompanyItem",
    "ExaDiscoveryEnrichmentObservation",
    "ExaEnrichmentOption",
    "ExaEventPage",
    "ExaEventPageExchange",
    "ExaItemPage",
    "ExaItemPageExchange",
    "ExaImport",
    "ExaImportExchange",
    "ExaImportFormat",
    "ExaImportStatus",
    "ExaResponseEnrichment",
    "ExaResponseSearch",
    "ExaWebsetDuplicateExternalId",
    "ExaWebsetEnrichmentFormat",
    "ExaWebsetEntity",
    "ExaWebsetEntityType",
    "ExaWebsetEvent",
    "ExaWebsetExchange",
    "ExaWebsetItem",
    "ExaWebsetItemCompanyProperties",
    "ExaWebsetNotFound",
    "ExaWebsetSearchBehavior",
    "ExaWebsetSearchStatus",
    "ExaWebsetStatus",
    "ExaWebsetsAuthenticationError",
    "ExaWebsetsClient",
    "ExaWebsetsContractDrift",
    "ExaWebsetsError",
    "ExaWebsetsIndeterminateDispatch",
    "ExaWebsetsImportTransport",
    "ExaWebsetsInvalidRequest",
    "ExaWebsetsPaymentRequired",
    "ExaWebsetsPermissionDenied",
    "ExaWebsetsPreDispatchError",
    "ExaWebsetsRateLimited",
    "ExaWebsetsTransientError",
    "ExaWebsetsLifecycleTransport",
    "ExaWebsetsTransport",
    "ExaWebsetsWebhookAdminTransport",
    "normalize_exa_discovery_company_item",
    "ExaWebhook",
    "ExaWebhookEventType",
    "ExaWebhookPage",
    "ExaWebhookVerificationError",
    "verify_exa_webhook_signature",
]
