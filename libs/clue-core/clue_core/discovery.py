"""Provider-neutral contracts for durable asynchronous account discovery.

These types are the D0 contract freeze for the Exa Websets discovery integration.  They live in
``clue_core`` because discovery, durable execution, projections, and the API composition root must
share the exact same lifecycle vocabulary without importing one another.  Provider request/response
models remain behind provider adapters; this module contains only the platform-owned plan, durable
references, field-resolution state, fingerprint identity, and seal barrier.

The central invariant is that a discovery batch is not complete merely because a provider reports
``idle``.  It is complete only after all fourteen platform-owned seal conditions are true and an
immutable :class:`DiscoveryBatchSeal` can be committed transactionally.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType, Protocol, cast, runtime_checkable
from uuid import UUID, uuid4

from annotated_types import Ge
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from clue_core.field import FieldKey
from clue_core.primitives import ClaimId, CostCents, EntityId, ProjectRunId, UtcDatetime

DiscoveryPlanId = NewType("DiscoveryPlanId", UUID)
DiscoveryBatchId = NewType("DiscoveryBatchId", UUID)
DiscoveryOperationId = NewType("DiscoveryOperationId", UUID)
DiscoveryItemSnapshotId = NewType("DiscoveryItemSnapshotId", UUID)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ProviderUnits = Annotated[Decimal, Ge(0)]

FIRST_PAGE_CURSOR = "__first_page__"


def new_discovery_plan_id() -> DiscoveryPlanId:
    return DiscoveryPlanId(uuid4())


def new_discovery_batch_id() -> DiscoveryBatchId:
    return DiscoveryBatchId(uuid4())


def new_discovery_operation_id() -> DiscoveryOperationId:
    return DiscoveryOperationId(uuid4())


def new_discovery_item_snapshot_id() -> DiscoveryItemSnapshotId:
    return DiscoveryItemSnapshotId(uuid4())


class DiscoveryEntityKind(StrEnum):
    COMPANY = "company"
    PERSON = "person"
    ARTICLE = "article"
    RESEARCH_PAPER = "research_paper"
    CUSTOM = "custom"


class DiscoverySearchBehaviour(StrEnum):
    """Search semantics included in the paid-operation fingerprint.

    D0 intentionally exposes only the behavior currently used by the integration.  A provider
    contract adding another behavior is a contract change, not an untyped string flowing through.
    """

    OVERRIDE = "override"


class DiscoveryEnrichmentFormat(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    URL = "url"
    EMAIL = "email"
    PHONE = "phone"
    OPTIONS = "options"


class DiscoveryEvaluationState(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


class DiscoveryFieldRequirement(StrEnum):
    HARD_IDENTITY = "hard_identity"
    REQUIRED_ATTEMPT = "required_attempt"
    OPTIONAL_ATTEMPT = "optional_attempt"


class DiscoveryFieldResolutionState(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CONFIRMED_MISSING = "confirmed_missing"
    CONFLICT = "conflict"
    REVIEW_REQUIRED = "review_required"
    ACCEPTED_MISSING = "accepted_missing"
    ACCOUNT_EXCLUDED = "account_excluded"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


SEAL_TERMINAL_FIELD_STATES: frozenset[DiscoveryFieldResolutionState] = frozenset(
    {
        DiscoveryFieldResolutionState.RESOLVED,
        DiscoveryFieldResolutionState.CONFIRMED_MISSING,
        DiscoveryFieldResolutionState.CONFLICT,
        DiscoveryFieldResolutionState.ACCEPTED_MISSING,
        DiscoveryFieldResolutionState.ACCOUNT_EXCLUDED,
        DiscoveryFieldResolutionState.BLOCKED_BY_POLICY,
    }
)


class DiscoveryBatchState(StrEnum):
    PLANNED = "planned"
    SUBMITTING = "submitting"
    PROVIDER_RUNNING = "provider_running"
    INGESTING_EVENTS_AND_PAGES = "ingesting_events_and_pages"
    RECONCILING = "reconciling"
    IDENTITY_RESOLUTION = "identity_resolution"
    FIELD_MATERIALIZATION = "field_materialization"
    SEAL_PENDING = "seal_pending"
    SEALED = "sealed"
    WAITING_EXTERNAL = "waiting_external"
    PAUSED_BY_USER = "paused_by_user"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED_UNSEALED = "cancelled_unsealed"


class DiscoveryOperationState(StrEnum):
    PLANNED = "planned"
    SUBMITTING = "submitting"
    PROVIDER_RUNNING = "provider_running"
    INGESTING = "ingesting"
    RECONCILING = "reconciling"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    ACCEPTED_TERMINAL_FAILURE = "accepted_terminal_failure"
    PAUSED_BY_USER = "paused_by_user"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"


SEAL_TERMINAL_OPERATION_STATES: frozenset[DiscoveryOperationState] = frozenset(
    {
        DiscoveryOperationState.SUCCEEDED,
        DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE,
    }
)


class DiscoverySpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    NOT_CHARGED = "not_charged"
    CHARGED = "charged"


class DiscoveryEventDisposition(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    SUPERSEDED = "superseded"
    DUPLICATE = "duplicate"
    LATE_AFTER_SEAL = "late_after_seal"


class DiscoveryPageResource(StrEnum):
    WEBSETS = "websets"
    SEARCHES = "searches"
    ENRICHMENTS = "enrichments"
    ITEMS = "items"
    EVENTS = "events"


class DiscoveryNormalizationState(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class DiscoveryCandidateAdmissionState(StrEnum):
    """Terminal identity disposition for one provider item.

    ``ADMITTED`` means the source item resolved directly to its surviving workspace-local account;
    ``MERGED`` means it first resolved to another candidate that was collapsed into the survivor.
    ``EXCLUDED`` is an honest terminal non-admission.  Only ``PENDING`` blocks the batch seal.
    """

    PENDING = "pending"
    ADMITTED = "admitted"
    MERGED = "merged"
    EXCLUDED = "excluded"


class DiscoveryWakeReason(StrEnum):
    SCHEDULED_POLL = "scheduled_poll"
    PROVIDER_EVENT = "provider_event"
    MANUAL_RECONCILE = "manual_reconcile"
    CRASH_RECOVERY = "crash_recovery"


class DiscoveryErrorCode(StrEnum):
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    RETRYABLE_TRANSPORT = "retryable_transport"
    INDETERMINATE_DISPATCH = "indeterminate_dispatch"
    PROVIDER_CONTRACT_DRIFT = "provider_contract_drift"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    POLICY_BLOCKED = "policy_blocked"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class DiscoverySealBlocker(StrEnum):
    PLAN_LINEAGE = "plan_lineage"
    OPERATION_TERMINALITY = "operation_terminality"
    DISPATCH_RECEIPTS = "dispatch_receipts"
    PROVIDER_EVENTS = "provider_events"
    FINAL_RECONCILIATION = "final_reconciliation"
    PAGINATION_EXHAUSTION = "pagination_exhaustion"
    ITEM_MATERIALIZATION = "item_materialization"
    CANDIDATE_IDENTITY = "candidate_identity"
    HARD_IDENTITIES = "hard_identities"
    REQUIRED_FIELDS = "required_fields"
    CLAIM_OR_DISPOSITION = "claim_or_disposition"
    SURVIVOR_LINKS = "survivor_links"
    SPEND_RECONCILIATION = "spend_reconciliation"
    FINAL_MANIFESTS = "final_manifests"


def _normalize_semantic_text(value: str) -> str:
    """Canonicalize user/provider-plan text before it can influence paid-operation identity."""

    return " ".join(unicodedata.normalize("NFKC", value).split())


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")


class DiscoveryCriterionPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: NonEmptyStr

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        return _normalize_semantic_text(value)


class DiscoveryEnrichmentOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: NonEmptyStr

    @field_validator("label")
    @classmethod
    def _normalize_label(cls, value: str) -> str:
        return _normalize_semantic_text(value)


class DiscoveryEnrichmentPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    description: NonEmptyStr
    format: DiscoveryEnrichmentFormat
    options: tuple[DiscoveryEnrichmentOption, ...] = Field(default=(), max_length=20)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        return _normalize_semantic_text(value)

    @model_validator(mode="after")
    def _options_match_format(self) -> DiscoveryEnrichmentPlan:
        if self.format is DiscoveryEnrichmentFormat.OPTIONS and not self.options:
            raise ValueError("an options enrichment requires at least one option")
        if self.format is not DiscoveryEnrichmentFormat.OPTIONS and self.options:
            raise ValueError("enrichment options are allowed only when format='options'")
        _require_unique(tuple(option.label for option in self.options), "enrichment option labels")
        return self


class DiscoverySearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    search_key: NonEmptyStr
    channel_key: NonEmptyStr
    normalized_query: NonEmptyStr
    entity_type: DiscoveryEntityKind
    custom_entity_description: NonEmptyStr | None = None
    requested_count: int = Field(ge=1)
    criteria: tuple[DiscoveryCriterionPlan, ...] = Field(default=(), max_length=5)
    enrichments: tuple[DiscoveryEnrichmentPlan, ...] = Field(default=(), max_length=10)
    behaviour: DiscoverySearchBehaviour = DiscoverySearchBehaviour.OVERRIDE
    max_people_per_company: int | None = Field(default=None, ge=1)

    @field_validator("normalized_query", "custom_entity_description")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        return _normalize_semantic_text(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_shape(self) -> DiscoverySearchPlan:
        if (
            self.entity_type is DiscoveryEntityKind.CUSTOM
            and self.custom_entity_description is None
        ):
            raise ValueError("a custom discovery entity requires custom_entity_description")
        if self.entity_type is not DiscoveryEntityKind.CUSTOM and self.custom_entity_description:
            raise ValueError("custom_entity_description is valid only for a custom entity")
        if self.entity_type is not DiscoveryEntityKind.PERSON and self.max_people_per_company:
            raise ValueError("max_people_per_company is valid only for person searches")
        _require_unique(
            tuple(criterion.description for criterion in self.criteria), "criterion descriptions"
        )
        _require_unique(
            tuple(str(enrichment.field_key) for enrichment in self.enrichments),
            "enrichment field keys",
        )
        return self


class DiscoveryPlan(BaseModel):
    """One immutable, versioned compilation of a confirmed ICP into discovery work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_plan_id: DiscoveryPlanId
    plan_version: int = Field(ge=1)
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    provider_policy_version: NonEmptyStr
    field_policy_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    channels: tuple[NonEmptyStr, ...] = Field(min_length=1)
    searches: tuple[DiscoverySearchPlan, ...] = Field(min_length=1)
    required_account_fields: tuple[FieldKey, ...] = Field(min_length=1)
    optional_account_fields: tuple[FieldKey, ...] = ()
    provider_credit_cap: int = Field(ge=0)
    money_budget_cap_cents: CostCents
    stopping_policy: dict[str, JsonValue]
    snapshot_reuse_policy: NonEmptyStr

    @model_validator(mode="after")
    def _validate_plan(self) -> DiscoveryPlan:
        _require_unique(self.channels, "channels")
        _require_unique(tuple(search.search_key for search in self.searches), "search keys")
        _require_unique(self.required_account_fields, "required account fields")
        _require_unique(self.optional_account_fields, "optional account fields")
        overlap = set(self.required_account_fields) & set(self.optional_account_fields)
        if overlap:
            raise ValueError(f"required and optional account fields overlap: {sorted(overlap)}")
        unknown_channels = {search.channel_key for search in self.searches} - set(self.channels)
        if unknown_channels:
            raise ValueError(f"searches reference undeclared channels: {sorted(unknown_channels)}")
        return self


class DiscoveryRequestFingerprintInput(BaseModel):
    """The complete semantic identity of one potentially paid provider operation.

    Secrets, random ids, transport headers, and wall-clock timestamps are deliberately absent.
    Criteria/enrichments remain ordered because provider behavior and spend can depend on order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    source_key: NonEmptyStr
    provider_api_version: NonEmptyStr
    entity_type: DiscoveryEntityKind
    custom_entity_description: NonEmptyStr | None = None
    normalized_query: NonEmptyStr
    criteria: tuple[DiscoveryCriterionPlan, ...] = Field(default=(), max_length=5)
    requested_count: int = Field(ge=1)
    search_behaviour: DiscoverySearchBehaviour
    enrichments: tuple[DiscoveryEnrichmentPlan, ...] = Field(default=(), max_length=10)
    max_people_per_company: int | None = Field(default=None, ge=1)
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    discovery_plan_version: int = Field(ge=1)
    field_policy_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    observation_window: NonEmptyStr

    @field_validator("normalized_query", "custom_entity_description")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        return _normalize_semantic_text(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_entity_shape(self) -> DiscoveryRequestFingerprintInput:
        if (
            self.entity_type is DiscoveryEntityKind.CUSTOM
            and self.custom_entity_description is None
        ):
            raise ValueError("a custom discovery entity requires custom_entity_description")
        if self.entity_type is not DiscoveryEntityKind.CUSTOM and self.custom_entity_description:
            raise ValueError("custom_entity_description is valid only for a custom entity")
        if self.entity_type is not DiscoveryEntityKind.PERSON and self.max_people_per_company:
            raise ValueError("max_people_per_company is valid only for person searches")
        return self

    def canonical_bytes(self) -> bytes:
        payload = cast(JsonValue, self.model_dump(mode="json", exclude_none=False))
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def discovery_request_fingerprint(value: DiscoveryRequestFingerprintInput) -> str:
    return value.sha256()


def discovery_plan_sha256(plan: DiscoveryPlan) -> str:
    """Stable content identity for an immutable discovery plan.

    The plan id is included deliberately: a separately-approved plan is a distinct durable object
    even when every execution knob happens to be equal.
    """

    payload = cast(JsonValue, plan.model_dump(mode="json", exclude_none=False))
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def discovery_provider_external_id(fingerprint: str) -> str:
    """Derive the deterministic Exa-compatible external id from a validated fingerprint."""

    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise ValueError("discovery request fingerprint must be 64 lowercase hex characters")
    return f"clue-{fingerprint[:48]}"


class DiscoveryOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: DiscoveryOperationId
    batch_id: DiscoveryBatchId
    workspace_id: NonEmptyStr
    source_key: NonEmptyStr
    provider_api_version: NonEmptyStr
    request_fingerprint: Sha256Hex
    observation_window: NonEmptyStr
    provider_external_id: NonEmptyStr
    provider_operation_id: str | None = None
    state: DiscoveryOperationState
    spend_outcome: DiscoverySpendOutcome
    next_poll_at: UtcDatetime | None = None
    submitted_receipt_ref: str | None = None
    final_receipt_ref: str | None = None
    raw_request_artifact_key: str | None = None
    raw_response_manifest_key: str | None = None
    provider_units_reserved: ProviderUnits = Decimal(0)
    provider_units_charged: ProviderUnits = Decimal(0)
    cost_cents_charged: CostCents = Decimal(0)
    started_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validate_lifecycle_and_spend(self) -> DiscoveryOperation:
        terminal_states = {
            DiscoveryOperationState.SUCCEEDED,
            DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE,
            DiscoveryOperationState.FAILED_TERMINAL,
            DiscoveryOperationState.CANCELLED,
        }
        if self.state in terminal_states and self.terminal_at is None:
            raise ValueError("a terminal discovery operation requires terminal_at")
        if self.state is DiscoveryOperationState.SPEND_OUTCOME_UNKNOWN:
            if self.spend_outcome is not DiscoverySpendOutcome.UNKNOWN:
                raise ValueError("spend_outcome_unknown state requires unknown spend outcome")
        elif self.spend_outcome is DiscoverySpendOutcome.UNKNOWN:
            raise ValueError("unknown spend outcome requires spend_outcome_unknown state")
        if self.spend_outcome is DiscoverySpendOutcome.NOT_CHARGED and (
            self.provider_units_charged != 0 or self.cost_cents_charged != 0
        ):
            raise ValueError("not_charged operation cannot record charged units or money")
        if self.state in SEAL_TERMINAL_OPERATION_STATES:
            if self.spend_outcome is DiscoverySpendOutcome.NOT_DISPATCHED:
                raise ValueError("a seal-terminal operation must have been dispatched")
            required_refs = {
                "submitted_receipt_ref": self.submitted_receipt_ref,
                "final_receipt_ref": self.final_receipt_ref,
                "raw_request_artifact_key": self.raw_request_artifact_key,
            }
            missing = sorted(name for name, value in required_refs.items() if not value)
            if missing:
                raise ValueError(f"a seal-terminal operation is missing references: {missing}")
        if self.state is DiscoveryOperationState.SUCCEEDED and not self.raw_response_manifest_key:
            raise ValueError("a succeeded operation requires raw_response_manifest_key")
        if self.state is DiscoveryOperationState.SUCCEEDED and not self.provider_operation_id:
            raise ValueError("a succeeded operation requires provider_operation_id")
        return self


class DiscoveryProviderEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: DiscoveryOperationId
    provider_event_id: NonEmptyStr
    event_type: NonEmptyStr
    signature_verified: bool
    payload_artifact_key: NonEmptyStr
    provider_created_at: UtcDatetime
    received_at: UtcDatetime
    processed_at: UtcDatetime | None = None
    processing_disposition: DiscoveryEventDisposition = DiscoveryEventDisposition.PENDING


class DiscoveryExternalWait(BaseModel):
    """Reference-only phase payload while discovery waits on provider-owned time.

    This is deliberately not a human pause.  The project run remains active in ``discovery`` and
    either a scheduled poll or a verified webhook enqueues the same phase operation again.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_batch_id: DiscoveryBatchId
    pending_operation_ids: tuple[DiscoveryOperationId, ...] = Field(min_length=1)
    next_poll_at: UtcDatetime
    wake_reason: DiscoveryWakeReason

    @model_validator(mode="after")
    def _operation_ids_are_unique(self) -> DiscoveryExternalWait:
        if len(self.pending_operation_ids) != len(set(self.pending_operation_ids)):
            raise ValueError("pending discovery operation ids must be unique")
        return self


class DiscoveryWakeRequest(BaseModel):
    """Provider-neutral request handed to a scheduler/outbox implementation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_run_id: ProjectRunId
    discovery_batch_id: DiscoveryBatchId
    operation_id: DiscoveryOperationId | None = None
    reason: DiscoveryWakeReason
    available_at: UtcDatetime
    dedupe_key: NonEmptyStr


@runtime_checkable
class DiscoveryWakeScheduler(Protocol):
    async def schedule(self, request: DiscoveryWakeRequest) -> str:
        """Durably enqueue ``request`` and return its stable wake reference."""
        ...


class DiscoveryPageReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: DiscoveryOperationId
    resource_kind: DiscoveryPageResource
    request_cursor: NonEmptyStr = FIRST_PAGE_CURSOR
    next_cursor: str | None = None
    has_more: bool
    payload_artifact_key: NonEmptyStr
    payload_sha256: Sha256Hex
    item_count: int = Field(ge=0)
    fetched_at: UtcDatetime

    @model_validator(mode="after")
    def _cursor_matches_has_more(self) -> DiscoveryPageReceipt:
        if self.has_more and not self.next_cursor:
            raise ValueError("a page with has_more=true requires next_cursor")
        if not self.has_more and self.next_cursor is not None:
            raise ValueError("a terminal page must have next_cursor=null")
        return self


class DiscoveryItemSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_snapshot_id: DiscoveryItemSnapshotId
    operation_id: DiscoveryOperationId
    provider_item_id: NonEmptyStr
    source_kind: NonEmptyStr
    source_id: NonEmptyStr
    raw_artifact_key: NonEmptyStr
    item_sha256: Sha256Hex
    observed_at: UtcDatetime
    normalization_state: DiscoveryNormalizationState = DiscoveryNormalizationState.RAW
    normalized_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _normalized_timestamp_matches_state(self) -> DiscoveryItemSnapshot:
        if self.normalization_state is DiscoveryNormalizationState.NORMALIZED:
            if self.normalized_at is None:
                raise ValueError("a normalized item requires normalized_at")
        elif self.normalized_at is not None:
            raise ValueError("normalized_at is valid only for a normalized item")
        return self


class DiscoveryFieldResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: DiscoveryBatchId
    account_entity_id: EntityId
    logical_field_key: FieldKey
    state: DiscoveryFieldResolutionState
    claim_ids: tuple[ClaimId, ...] = ()
    winning_claim_id: ClaimId | None = None
    source_item_ids: tuple[DiscoveryItemSnapshotId, ...] = ()
    reason_code: str | None = None
    review_disposition_ref: str | None = None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_resolution(self) -> DiscoveryFieldResolution:
        if self.state is DiscoveryFieldResolutionState.RESOLVED:
            if not self.claim_ids or self.winning_claim_id is None:
                raise ValueError("a resolved field requires claim_ids and winning_claim_id")
            if self.winning_claim_id not in self.claim_ids:
                raise ValueError("winning_claim_id must be present in claim_ids")
        elif self.winning_claim_id is not None:
            raise ValueError("winning_claim_id is valid only for a resolved field")
        if (
            self.state
            not in {
                DiscoveryFieldResolutionState.PENDING,
                DiscoveryFieldResolutionState.RESOLVED,
            }
            and not self.reason_code
        ):
            raise ValueError("a non-resolved terminal/review field requires reason_code")
        return self

    @property
    def is_seal_terminal(self) -> bool:
        return self.state in SEAL_TERMINAL_FIELD_STATES


class DiscoveryEnvelopeField(BaseModel):
    """One logical account-envelope requirement and its ordered canonical storage fallbacks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_field_key: FieldKey
    label: NonEmptyStr
    requirement: DiscoveryFieldRequirement
    canonical_storage: NonEmptyStr
    field_attempt_order: tuple[FieldKey, ...] = ()
    allow_terminal_disposition: bool

    @model_validator(mode="after")
    def _validate_storage(self) -> DiscoveryEnvelopeField:
        _require_unique(self.field_attempt_order, "field attempt order")
        expected_disposition = self.requirement is not DiscoveryFieldRequirement.HARD_IDENTITY
        if self.allow_terminal_disposition is not expected_disposition:
            raise ValueError(
                "hard identities must forbid missing dispositions; attempted fields must allow "
                "honest terminal dispositions"
            )
        if not self.field_attempt_order and not self.canonical_storage.startswith(
            "account_entity."
        ):
            raise ValueError(
                "an envelope field without registered field attempts must use "
                "account_entity storage"
            )
        return self


class DiscoveryEnvelopePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: NonEmptyStr
    fields: tuple[DiscoveryEnvelopeField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_logical_fields(self) -> DiscoveryEnvelopePolicy:
        _require_unique(
            tuple(str(field.logical_field_key) for field in self.fields), "logical envelope fields"
        )
        return self

    @property
    def required_fields(self) -> tuple[FieldKey, ...]:
        return tuple(
            field.logical_field_key
            for field in self.fields
            if field.requirement is not DiscoveryFieldRequirement.OPTIONAL_ATTEMPT
        )

    @property
    def optional_fields(self) -> tuple[FieldKey, ...]:
        return tuple(
            field.logical_field_key
            for field in self.fields
            if field.requirement is DiscoveryFieldRequirement.OPTIONAL_ATTEMPT
        )


def validate_discovery_plan_policy(plan: DiscoveryPlan, policy: DiscoveryEnvelopePolicy) -> None:
    """Fail closed when a plan claims a policy version but carries a different field envelope."""

    if plan.field_policy_version != policy.version:
        raise ValueError(
            f"plan field_policy_version {plan.field_policy_version!r} does not match "
            f"policy {policy.version!r}"
        )
    if plan.required_account_fields != policy.required_fields:
        raise ValueError("plan required_account_fields do not match the versioned field policy")
    if plan.optional_account_fields != policy.optional_fields:
        raise ValueError("plan optional_account_fields do not match the versioned field policy")


class DiscoverySealReadiness(BaseModel):
    """Transaction-snapshot truth values for the fourteen-condition completion barrier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_lineage_matches: bool
    operations_terminal: bool
    dispatch_receipts_complete: bool
    provider_events_accounted: bool
    final_reconciliation_complete: bool
    pagination_exhausted: bool
    items_materialized: bool
    candidate_identities_terminal: bool
    hard_identities_complete: bool
    required_fields_terminal: bool
    claims_or_dispositions_complete: bool
    survivor_links_complete: bool
    spend_reconciled: bool
    final_manifests_exist: bool


_SEAL_CONDITIONS: tuple[tuple[str, DiscoverySealBlocker], ...] = (
    ("plan_lineage_matches", DiscoverySealBlocker.PLAN_LINEAGE),
    ("operations_terminal", DiscoverySealBlocker.OPERATION_TERMINALITY),
    ("dispatch_receipts_complete", DiscoverySealBlocker.DISPATCH_RECEIPTS),
    ("provider_events_accounted", DiscoverySealBlocker.PROVIDER_EVENTS),
    ("final_reconciliation_complete", DiscoverySealBlocker.FINAL_RECONCILIATION),
    ("pagination_exhausted", DiscoverySealBlocker.PAGINATION_EXHAUSTION),
    ("items_materialized", DiscoverySealBlocker.ITEM_MATERIALIZATION),
    ("candidate_identities_terminal", DiscoverySealBlocker.CANDIDATE_IDENTITY),
    ("hard_identities_complete", DiscoverySealBlocker.HARD_IDENTITIES),
    ("required_fields_terminal", DiscoverySealBlocker.REQUIRED_FIELDS),
    ("claims_or_dispositions_complete", DiscoverySealBlocker.CLAIM_OR_DISPOSITION),
    ("survivor_links_complete", DiscoverySealBlocker.SURVIVOR_LINKS),
    ("spend_reconciled", DiscoverySealBlocker.SPEND_RECONCILIATION),
    ("final_manifests_exist", DiscoverySealBlocker.FINAL_MANIFESTS),
)


class DiscoverySealDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sealable: bool
    blockers: tuple[DiscoverySealBlocker, ...]


def evaluate_discovery_seal(readiness: DiscoverySealReadiness) -> DiscoverySealDecision:
    blockers = tuple(
        blocker for attribute, blocker in _SEAL_CONDITIONS if not getattr(readiness, attribute)
    )
    return DiscoverySealDecision(sealable=not blockers, blockers=blockers)


class DiscoveryBatchSeal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: DiscoveryBatchId
    project_run_id: ProjectRunId
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    discovery_plan_id: DiscoveryPlanId
    plan_sha256: Sha256Hex
    sealed_at: UtcDatetime
    account_count: int = Field(ge=0)
    account_manifest_artifact_key: NonEmptyStr
    account_manifest_sha256: Sha256Hex
    excluded_candidate_count: int = Field(ge=0)
    field_resolution_summary: dict[str, int]
    provider_operation_ids: tuple[DiscoveryOperationId, ...]
    request_fingerprints: tuple[Sha256Hex, ...]
    raw_artifact_manifest_key: NonEmptyStr
    claim_id_manifest_key: NonEmptyStr
    provider_units_charged: ProviderUnits
    cost_cents_charged: CostCents
    coverage_report_ref: NonEmptyStr
    seal_sha256: Sha256Hex

    @field_validator("field_resolution_summary")
    @classmethod
    def _nonnegative_summary(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("field resolution summary counts must be non-negative")
        return value

    @model_validator(mode="after")
    def _operation_manifest_is_one_to_one(self) -> DiscoveryBatchSeal:
        if len(self.provider_operation_ids) != len(self.request_fingerprints):
            raise ValueError("provider operation ids and request fingerprints must be one-to-one")
        if len(self.provider_operation_ids) != len(set(self.provider_operation_ids)):
            raise ValueError("provider operation ids must be unique in a seal")
        if len(self.request_fingerprints) != len(set(self.request_fingerprints)):
            raise ValueError("request fingerprints must be unique in a seal")
        return self


class DiscoveryFailure(BaseModel):
    """Secret-safe typed failure persisted by D1 and produced by provider adapters in D2+."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: DiscoveryErrorCode
    message: NonEmptyStr
    retryable: bool
    spend_outcome: DiscoverySpendOutcome
    provider_status_code: int | None = Field(default=None, ge=100, le=599)
    receipt_ref: str | None = None

    @model_validator(mode="after")
    def _indeterminate_spend_is_unknown(self) -> DiscoveryFailure:
        if (
            self.code is DiscoveryErrorCode.INDETERMINATE_DISPATCH
            and self.spend_outcome is not DiscoverySpendOutcome.UNKNOWN
        ):
            raise ValueError("indeterminate dispatch requires spend_outcome='unknown'")
        return self


__all__ = [
    "FIRST_PAGE_CURSOR",
    "SEAL_TERMINAL_FIELD_STATES",
    "SEAL_TERMINAL_OPERATION_STATES",
    "DiscoveryBatchId",
    "DiscoveryBatchSeal",
    "DiscoveryBatchState",
    "DiscoveryCandidateAdmissionState",
    "DiscoveryCriterionPlan",
    "DiscoveryEnrichmentFormat",
    "DiscoveryEnrichmentOption",
    "DiscoveryEnrichmentPlan",
    "DiscoveryEntityKind",
    "DiscoveryEnvelopeField",
    "DiscoveryEnvelopePolicy",
    "DiscoveryErrorCode",
    "DiscoveryEvaluationState",
    "DiscoveryEventDisposition",
    "DiscoveryFailure",
    "DiscoveryExternalWait",
    "DiscoveryFieldRequirement",
    "DiscoveryFieldResolution",
    "DiscoveryFieldResolutionState",
    "DiscoveryItemSnapshot",
    "DiscoveryItemSnapshotId",
    "DiscoveryNormalizationState",
    "DiscoveryOperation",
    "DiscoveryOperationId",
    "DiscoveryOperationState",
    "DiscoveryPageReceipt",
    "DiscoveryPageResource",
    "DiscoveryPlan",
    "DiscoveryPlanId",
    "DiscoveryProviderEvent",
    "DiscoveryRequestFingerprintInput",
    "DiscoverySearchBehaviour",
    "DiscoverySearchPlan",
    "DiscoverySealBlocker",
    "DiscoverySealDecision",
    "DiscoverySealReadiness",
    "DiscoverySpendOutcome",
    "DiscoveryWakeReason",
    "DiscoveryWakeRequest",
    "DiscoveryWakeScheduler",
    "ProviderUnits",
    "Sha256Hex",
    "discovery_provider_external_id",
    "discovery_plan_sha256",
    "discovery_request_fingerprint",
    "evaluate_discovery_seal",
    "new_discovery_batch_id",
    "new_discovery_item_snapshot_id",
    "new_discovery_operation_id",
    "new_discovery_plan_id",
    "validate_discovery_plan_policy",
]
