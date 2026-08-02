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
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
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
    model_validator,
)

from clue_obs.otel import apply_attributes, traced_step

EXA_WEBSETS_SOURCE_KEY = "exa_websets"
EXA_WEBSETS_API_VERSION = "v0"
EXA_WEBSETS_API_BASE = "https://api.exa.ai/websets/v0"
EXA_WEBSETS_CONTRACT_VERSION = "exa-websets-v0-openapi-2026-05-22"
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


class ExaWebsetEnrichmentFormat(StrEnum):
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    OPTIONS = "options"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"


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


class ExaCreateWebsetRequest(BaseModel):
    """Pinned subset of the current ``CreateWebsetParameters`` schema.

    Request models reject unknown fields: provider contract changes must be explicit.  Empty
    optional collections are excluded from canonical wire bytes so the stored request is exactly
    what the transport sends.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    search: ExaCreateSearch
    title: str | None = Field(default=None, min_length=1)
    enrichments: tuple[ExaCreateEnrichment, ...] = Field(default=(), max_length=10)
    external_id: str = Field(
        min_length=1,
        max_length=300,
        alias="externalId",
    )
    metadata: dict[str, str] = Field(default_factory=dict)

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
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ExaResponseEnrichment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    id: NonEmptyStr
    object: Literal["webset_enrichment"]
    status: Literal["pending", "canceled", "completed"]
    webset_id: NonEmptyStr = Field(alias="websetId")
    description: NonEmptyStr
    format: ExaWebsetEnrichmentFormat | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


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
    imports: tuple[dict[str, JsonValue], ...]
    enrichments: tuple[ExaResponseEnrichment, ...]
    monitors: tuple[dict[str, JsonValue], ...]
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
            requested_count=request.search.count,
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

    async def _request(
        self,
        *,
        method: Literal["GET", "POST"],
        url: str,
        body: bytes | None,
        expected_status: int,
        create: bool,
    ) -> ExaWebsetExchange:
        headers = {
            "accept": "application/json",
            "x-api-key": self._api_key.get_secret_value(),
        }
        if body is not None:
            headers["content-type"] = "application/json"
        try:
            response = await self._client.request(method, url, headers=headers, content=body)
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
        request_id = response.headers.get("x-request-id")
        if response.status_code != expected_status:
            raise _provider_error(
                status_code=response.status_code,
                request_id=request_id,
                response_body=response_body,
                retry_after=response.headers.get("retry-after"),
            )
        try:
            webset = ExaWebset.model_validate_json(response_body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa Websets response does not match the pinned v0 contract",
                status_code=response.status_code,
                request_id=request_id,
                response_body=response_body,
            ) from exc
        return ExaWebsetExchange(
            status_code=response.status_code,
            request_id=request_id,
            response_body=response_body,
            webset=webset,
        )


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
    "ExaCreateSearch",
    "ExaCreateWebsetRequest",
    "ExaEnrichmentOption",
    "ExaResponseEnrichment",
    "ExaResponseSearch",
    "ExaWebsetDuplicateExternalId",
    "ExaWebsetEnrichmentFormat",
    "ExaWebsetEntity",
    "ExaWebsetEntityType",
    "ExaWebsetExchange",
    "ExaWebsetNotFound",
    "ExaWebsetSearchBehavior",
    "ExaWebsetSearchStatus",
    "ExaWebsetStatus",
    "ExaWebsetsAuthenticationError",
    "ExaWebsetsClient",
    "ExaWebsetsContractDrift",
    "ExaWebsetsError",
    "ExaWebsetsIndeterminateDispatch",
    "ExaWebsetsInvalidRequest",
    "ExaWebsetsPaymentRequired",
    "ExaWebsetsPermissionDenied",
    "ExaWebsetsPreDispatchError",
    "ExaWebsetsRateLimited",
    "ExaWebsetsTransientError",
    "ExaWebsetsTransport",
]
