"""Provider-neutral contracts for post-discovery targeted enrichment.

Unlike discovery, targeted enrichment is allowed only after a durable account set has been sealed
and a human has selected the exact accounts worth additional spend.  These contracts deliberately
carry that seal and tier-decision lineage.  Provider adapters translate them into their own wire
formats; no provider vocabulary appears in the durable repository.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType
from uuid import UUID, uuid4

from annotated_types import Ge
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from clue_core.discovery import DiscoveryBatchId, DiscoveryEnrichmentFormat, Sha256Hex
from clue_core.field import FieldKey
from clue_core.primitives import ClaimId, CostCents, EntityId, ProjectRunId, UtcDatetime

TargetedEnrichmentOperationId = NewType("TargetedEnrichmentOperationId", UUID)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProviderUnits = Annotated[Decimal, Ge(0)]


def new_targeted_enrichment_operation_id() -> TargetedEnrichmentOperationId:
    return TargetedEnrichmentOperationId(uuid4())


class TargetedEnrichmentState(StrEnum):
    PLANNED = "planned"
    SUBMITTING = "submitting"
    PROVIDER_RUNNING = "provider_running"
    RECONCILING = "reconciling"
    MATERIALIZING = "materializing"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    CANCELLED = "cancelled"


class TargetedEnrichmentSpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    NOT_CHARGED = "not_charged"
    CHARGED = "charged"


class TargetedEnrichmentFieldState(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CONFIRMED_MISSING = "confirmed_missing"
    IMPORT_UNRESOLVED = "import_unresolved"
    FAILED_TERMINAL = "failed_terminal"


class TargetedEnrichmentFieldPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    description: NonEmptyStr
    format: DiscoveryEnrichmentFormat
    options: tuple[NonEmptyStr, ...] = Field(default=(), max_length=150)

    @model_validator(mode="after")
    def _options_match_format(self) -> TargetedEnrichmentFieldPlan:
        if self.format is DiscoveryEnrichmentFormat.OPTIONS and not self.options:
            raise ValueError("an options targeted enrichment requires options")
        if self.format is not DiscoveryEnrichmentFormat.OPTIONS and self.options:
            raise ValueError("targeted enrichment options require format='options'")
        if len(self.options) != len(set(self.options)):
            raise ValueError("targeted enrichment options must be unique")
        return self


class TargetedEnrichmentTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: EntityId
    identifier_url: NonEmptyStr
    tier_claim_id: ClaimId

    @field_validator("identifier_url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("targeted enrichment identifier must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("targeted enrichment identifier must not contain credentials/query")
        return value


class TargetedEnrichmentRequest(BaseModel):
    """Immutable, fingerprinted intent for one bounded post-seal operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    discovery_batch_id: DiscoveryBatchId
    discovery_seal_sha256: Sha256Hex
    source_key: NonEmptyStr
    provider_api_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    pricing_policy_version: NonEmptyStr
    field_policy_version: NonEmptyStr
    observation_window: NonEmptyStr
    targets: tuple[TargetedEnrichmentTarget, ...] = Field(min_length=1, max_length=100)
    fields: tuple[TargetedEnrichmentFieldPlan, ...] = Field(min_length=1, max_length=10)
    provider_credit_cap: int = Field(ge=0)
    money_budget_cap_cents: CostCents = Decimal(0)

    @model_validator(mode="after")
    def _canonical_members(self) -> TargetedEnrichmentRequest:
        account_ids = tuple(target.account_id for target in self.targets)
        urls = tuple(target.identifier_url for target in self.targets)
        field_keys = tuple(field.field_key for field in self.fields)
        if len(account_ids) != len(set(account_ids)):
            raise ValueError("targeted enrichment accounts must be unique")
        if len(urls) != len(set(urls)):
            raise ValueError("targeted enrichment identifiers must be unique")
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("targeted enrichment fields must be unique")
        if account_ids != tuple(sorted(account_ids, key=str)):
            raise ValueError("targeted enrichment targets must be sorted by account id")
        if field_keys != tuple(sorted(field_keys, key=str)):
            raise ValueError("targeted enrichment fields must be sorted by field key")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def request_fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class TargetedEnrichmentOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: TargetedEnrichmentOperationId
    request: TargetedEnrichmentRequest
    request_fingerprint: Sha256Hex
    provider_external_id: NonEmptyStr
    state: TargetedEnrichmentState
    spend_outcome: TargetedEnrichmentSpendOutcome
    import_id: str | None = None
    provider_operation_id: str | None = None
    input_artifact_key: str
    csv_artifact_key: str
    submitted_receipt_ref: str | None = None
    final_receipt_ref: str | None = None
    raw_response_manifest_key: str | None = None
    provider_units_reserved: ProviderUnits = Decimal(0)
    provider_units_charged: ProviderUnits = Decimal(0)
    cost_cents_reserved: CostCents = Decimal(0)
    cost_cents_charged: CostCents = Decimal(0)
    next_poll_at: UtcDatetime | None = None
    failure_code: str | None = None
    started_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> TargetedEnrichmentOperation:
        if self.request_fingerprint != self.request.request_fingerprint:
            raise ValueError("targeted enrichment request fingerprint mismatch")
        terminal = self.state in {
            TargetedEnrichmentState.SUCCEEDED,
            TargetedEnrichmentState.FAILED_TERMINAL,
            TargetedEnrichmentState.CANCELLED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("targeted enrichment terminal timestamp is incoherent")
        if self.state is TargetedEnrichmentState.SUCCEEDED and (
            self.provider_operation_id is None
            or self.final_receipt_ref is None
            or self.raw_response_manifest_key is None
            or self.spend_outcome is not TargetedEnrichmentSpendOutcome.CHARGED
        ):
            raise ValueError("successful targeted enrichment lacks terminal provider evidence")
        if (self.state is TargetedEnrichmentState.SPEND_OUTCOME_UNKNOWN) != (
            self.spend_outcome is TargetedEnrichmentSpendOutcome.UNKNOWN
        ):
            raise ValueError("unknown targeted enrichment state requires unknown spend")
        if self.provider_units_charged > self.provider_units_reserved:
            raise ValueError("targeted enrichment provider charge exceeds its reservation")
        if self.cost_cents_charged > self.cost_cents_reserved:
            raise ValueError("targeted enrichment monetary charge exceeds its reservation")
        return self


class TargetedEnrichmentFieldResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: TargetedEnrichmentOperationId
    account_id: EntityId
    field_key: FieldKey
    state: TargetedEnrichmentFieldState
    provider_item_id: str | None = None
    item_artifact_key: str | None = None
    claim_id: ClaimId | None = None
    reason_code: str | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _terminal_shape(self) -> TargetedEnrichmentFieldResult:
        if self.state is TargetedEnrichmentFieldState.RESOLVED:
            if (
                self.provider_item_id is None
                or self.item_artifact_key is None
                or self.claim_id is None
            ):
                raise ValueError("resolved targeted enrichment field lacks provider/claim evidence")
        elif self.claim_id is not None:
            raise ValueError("a non-resolved targeted enrichment field cannot carry a claim")
        return self


__all__ = [
    "TargetedEnrichmentFieldPlan",
    "TargetedEnrichmentFieldResult",
    "TargetedEnrichmentFieldState",
    "TargetedEnrichmentOperation",
    "TargetedEnrichmentOperationId",
    "TargetedEnrichmentRequest",
    "TargetedEnrichmentSpendOutcome",
    "TargetedEnrichmentState",
    "TargetedEnrichmentTarget",
    "new_targeted_enrichment_operation_id",
]
