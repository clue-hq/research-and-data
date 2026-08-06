"""Provider-neutral contracts for required-field work before a discovery batch is sealed."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType
from uuid import UUID, uuid4

from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from clue_core.discovery import (
    DiscoveryBatchId,
    DiscoveryItemSnapshotId,
    Sha256Hex,
)
from clue_core.field import FieldKey
from clue_core.primitives import ClaimId, CostCents, EntityId, ProjectRunId, UtcDatetime

DiscoveryGapOperationId = NewType("DiscoveryGapOperationId", UUID)
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProviderUnits = Annotated[Decimal, Ge(0)]


def new_discovery_gap_operation_id() -> DiscoveryGapOperationId:
    return DiscoveryGapOperationId(uuid4())


class DiscoveryGapOperationState(StrEnum):
    PLANNED = "planned"
    DISPATCHING = "dispatching"
    MATERIALIZING = "materializing"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    CANCELLED = "cancelled"


class DiscoveryGapSpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    NOT_CHARGED = "not_charged"
    CHARGED = "charged"


class DiscoveryGapFieldState(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CONFIRMED_MISSING = "confirmed_missing"
    CORROBORATED = "corroborated"
    CONFLICT = "conflict"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    FAILED_TERMINAL = "failed_terminal"


class DiscoveryGapFieldPlan(BaseModel):
    """One exact logical discovery field and its canonical provider-backed storage field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_field_key: FieldKey
    field_key: FieldKey
    source_key: NonEmptyStr
    expected_value_credits: ProviderUnits
    basis_claim_ids: tuple[ClaimId, ...] = ()
    source_item_ids: tuple[DiscoveryItemSnapshotId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _canonical_evidence(self) -> DiscoveryGapFieldPlan:
        if self.expected_value_credits <= 0:
            raise ValueError("discovery-gap fields require positive expected value")
        if len(self.basis_claim_ids) != len(set(self.basis_claim_ids)):
            raise ValueError("discovery-gap basis claims must be unique")
        if len(self.source_item_ids) != len(set(self.source_item_ids)):
            raise ValueError("discovery-gap source items must be unique")
        return self


class DiscoveryGapRequest(BaseModel):
    """Immutable pre-seal acquisition intent for one account and one provider request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    discovery_batch_id: DiscoveryBatchId
    account_id: EntityId
    primary_domain: NonEmptyStr
    source_key: NonEmptyStr
    provider_api_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    pricing_policy_version: NonEmptyStr
    field_policy_version: NonEmptyStr
    observation_window: NonEmptyStr
    required_criteria: tuple[NonEmptyStr, ...] = Field(min_length=1)
    eligibility_claim_ids: tuple[ClaimId, ...] = Field(min_length=1)
    fields: tuple[DiscoveryGapFieldPlan, ...] = Field(min_length=1, max_length=8)
    provider_credit_cap: int = Field(ge=0)
    expected_value_credits: ProviderUnits
    money_budget_cap_cents: CostCents = Decimal(0)

    @model_validator(mode="after")
    def _canonical_plan(self) -> DiscoveryGapRequest:
        logical_keys = tuple(str(item.logical_field_key) for item in self.fields)
        if logical_keys != tuple(sorted(logical_keys)) or len(logical_keys) != len(
            set(logical_keys)
        ):
            raise ValueError("discovery-gap logical fields must be unique and sorted")
        if any(item.source_key != self.source_key for item in self.fields):
            raise ValueError("one discovery-gap request may target only one source")
        if len(self.required_criteria) != len(set(self.required_criteria)):
            raise ValueError("discovery-gap required criteria must be unique")
        if len(self.eligibility_claim_ids) != len(set(self.eligibility_claim_ids)):
            raise ValueError("discovery-gap eligibility claims must be unique")
        expected = sum((item.expected_value_credits for item in self.fields), Decimal(0))
        if expected != self.expected_value_credits:
            raise ValueError("discovery-gap expected value must equal the field-plan total")
        if self.expected_value_credits < Decimal(self.provider_credit_cap):
            raise ValueError("discovery-gap expected value does not justify its provider cap")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()

    @property
    def request_fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class DiscoveryGapOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: DiscoveryGapOperationId
    request: DiscoveryGapRequest
    request_fingerprint: Sha256Hex
    state: DiscoveryGapOperationState
    spend_outcome: DiscoveryGapSpendOutcome
    request_artifact_key: NonEmptyStr
    response_artifact_key: str | None = None
    receipt_artifact_key: str | None = None
    provider_request_id: str | None = None
    provider_units_reserved: ProviderUnits = Decimal(0)
    provider_units_charged: ProviderUnits = Decimal(0)
    credits_remaining: int | None = Field(default=None, ge=0)
    cost_cents_reserved: CostCents = Decimal(0)
    cost_cents_charged: CostCents = Decimal(0)
    failure_code: str | None = None
    started_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> DiscoveryGapOperation:
        if self.request_fingerprint != self.request.request_fingerprint:
            raise ValueError("discovery-gap request fingerprint mismatch")
        terminal = self.state in {
            DiscoveryGapOperationState.SUCCEEDED,
            DiscoveryGapOperationState.FAILED_TERMINAL,
            DiscoveryGapOperationState.SPEND_OUTCOME_UNKNOWN,
            DiscoveryGapOperationState.CANCELLED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("discovery-gap terminal timestamp is incoherent")
        if self.state is DiscoveryGapOperationState.SUCCEEDED and (
            self.response_artifact_key is None
            or self.receipt_artifact_key is None
            or self.provider_request_id is None
            or self.spend_outcome is not DiscoveryGapSpendOutcome.CHARGED
        ):
            raise ValueError("successful discovery-gap operation lacks provider evidence")
        if (self.state is DiscoveryGapOperationState.SPEND_OUTCOME_UNKNOWN) != (
            self.spend_outcome is DiscoveryGapSpendOutcome.UNKNOWN
        ):
            raise ValueError("unknown discovery-gap state requires unknown spend")
        if self.provider_units_charged > self.provider_units_reserved:
            raise ValueError("discovery-gap charge exceeds its reservation")
        return self


class DiscoveryGapFieldResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: DiscoveryGapOperationId
    account_id: EntityId
    logical_field_key: FieldKey
    field_key: FieldKey
    source_key: NonEmptyStr
    state: DiscoveryGapFieldState
    provider_claim_id: ClaimId | None = None
    current_claim_id: ClaimId | None = None
    conflicting_claim_ids: tuple[ClaimId, ...] = ()
    reason_code: NonEmptyStr
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _terminal_shape(self) -> DiscoveryGapFieldResult:
        if (
            self.state
            in {
                DiscoveryGapFieldState.RESOLVED,
                DiscoveryGapFieldState.CORROBORATED,
            }
            and self.provider_claim_id is None
        ):
            raise ValueError("resolved discovery-gap field lacks its provider claim")
        if self.state is DiscoveryGapFieldState.CONFLICT and (
            self.provider_claim_id is None or not self.conflicting_claim_ids
        ):
            raise ValueError("conflicting discovery-gap field lacks contender claims")
        if (
            self.state
            in {
                DiscoveryGapFieldState.PENDING,
                DiscoveryGapFieldState.CONFIRMED_MISSING,
                DiscoveryGapFieldState.BLOCKED_BY_POLICY,
                DiscoveryGapFieldState.FAILED_TERMINAL,
            }
            and self.provider_claim_id is not None
        ):
            raise ValueError("non-resolved discovery-gap field cannot carry a provider claim")
        return self


__all__ = [
    "DiscoveryGapFieldPlan",
    "DiscoveryGapFieldResult",
    "DiscoveryGapFieldState",
    "DiscoveryGapOperation",
    "DiscoveryGapOperationId",
    "DiscoveryGapOperationState",
    "DiscoveryGapRequest",
    "DiscoveryGapSpendOutcome",
    "new_discovery_gap_operation_id",
]
