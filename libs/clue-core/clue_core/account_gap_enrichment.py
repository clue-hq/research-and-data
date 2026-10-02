"""Provider-neutral contracts for post-selection account-gap enrichment."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType
from uuid import UUID, uuid4

from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from clue_core.discovery import DiscoveryBatchId, Sha256Hex
from clue_core.field import FieldKey
from clue_core.primitives import ClaimId, CostCents, EntityId, ProjectRunId, UtcDatetime

AccountGapOperationId = NewType("AccountGapOperationId", UUID)
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProviderUnits = Annotated[Decimal, Ge(0)]


def new_account_gap_operation_id() -> AccountGapOperationId:
    return AccountGapOperationId(uuid4())


class AccountGapReason(StrEnum):
    """Why a field is a *gap* worth paying a structured provider to answer (FI-2 §6.3).

    Carried in the durable gap request payload (JSON — there is no ``account_gap_reason`` DB enum),
    so adding a member needs no migration.
    """

    MISSING = "missing"
    LOW_CONFIDENCE = "low_confidence"
    CONFLICT = "conflict"
    STALE = "stale"  # confidently resolved, conflict-free, but past the field's freshness TTL
    # Confidently resolved, conflict-free and fresh, but the winning claim carries no evidence
    # span — so no consumer may treat the field as answered (``CurrentValue.evidence_backed``).
    # Distinct from MISSING: something *is* on file, and it is the basis of the re-buy.
    NO_EVIDENCE = "no_evidence"


class AccountGapOperationState(StrEnum):
    PLANNED = "planned"
    ACQUIRING = "acquiring"
    MATERIALIZING = "materializing"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    CANCELLED = "cancelled"


class AccountGapSnapshotState(StrEnum):
    PLANNED = "planned"
    DISPATCHING = "dispatching"
    SUCCEEDED = "succeeded"
    NOT_APPLICABLE = "not_applicable"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class AccountGapSpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    NOT_CHARGED = "not_charged"
    CHARGED = "charged"


class AccountGapFieldState(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CONFIRMED_MISSING = "confirmed_missing"
    CORROBORATED = "corroborated"
    CONFLICT = "conflict"
    FAILED_TERMINAL = "failed_terminal"


class AccountGapFieldPlan(BaseModel):
    """One field selected by the governed plan, including its durable selection basis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    source_key: NonEmptyStr
    reason: AccountGapReason
    expected_value_credits: ProviderUnits
    basis_claim_ids: tuple[ClaimId, ...] = ()


class AccountGapRequest(BaseModel):
    """Immutable intent for one selected account and one coalesced provider bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    entity_research_job_id: UUID | None = None
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    discovery_batch_id: DiscoveryBatchId
    discovery_seal_sha256: Sha256Hex
    account_id: EntityId
    primary_domain: NonEmptyStr
    tier_claim_id: ClaimId | None = None
    provider_api_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    pricing_policy_version: NonEmptyStr
    field_policy_version: NonEmptyStr
    observation_window: NonEmptyStr
    fields: tuple[AccountGapFieldPlan, ...] = Field(min_length=1, max_length=12)
    provider_credit_cap: int = Field(ge=0)
    expected_value_credits: ProviderUnits
    money_budget_cap_cents: CostCents = Decimal(0)
    allow_unbounded_tech: bool = False

    @model_validator(mode="after")
    def _canonical_fields_and_value(self) -> AccountGapRequest:
        if self.entity_research_job_id is None and self.tier_claim_id is None:
            raise ValueError("historical account-gap request requires an exact tier claim")
        keys = tuple(str(item.field_key) for item in self.fields)
        if len(keys) != len(set(keys)):
            raise ValueError("account-gap fields must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("account-gap fields must be sorted by field key")
        planned_value = sum((item.expected_value_credits for item in self.fields), Decimal(0))
        if planned_value != self.expected_value_credits:
            raise ValueError("account-gap expected value must equal the sum of field-plan values")
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


class AccountGapOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: AccountGapOperationId
    request: AccountGapRequest
    request_fingerprint: Sha256Hex
    state: AccountGapOperationState
    spend_outcome: AccountGapSpendOutcome
    input_artifact_key: NonEmptyStr
    receipt_manifest_key: str | None = None
    provider_units_reserved: ProviderUnits = Decimal(0)
    provider_units_charged: ProviderUnits = Decimal(0)
    cost_cents_reserved: CostCents = Decimal(0)
    cost_cents_charged: CostCents = Decimal(0)
    unbounded_call_approved: bool = False
    failure_code: str | None = None
    started_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> AccountGapOperation:
        if self.request_fingerprint != self.request.request_fingerprint:
            raise ValueError("account-gap request fingerprint mismatch")
        if self.unbounded_call_approved != self.request.allow_unbounded_tech:
            raise ValueError("account-gap unbounded approval differs from its request")
        terminal = self.state in {
            AccountGapOperationState.SUCCEEDED,
            AccountGapOperationState.FAILED_TERMINAL,
            AccountGapOperationState.SPEND_OUTCOME_UNKNOWN,
            AccountGapOperationState.CANCELLED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("account-gap terminal timestamp is incoherent")
        if self.state is AccountGapOperationState.SUCCEEDED and (
            self.receipt_manifest_key is None
            or self.spend_outcome is not AccountGapSpendOutcome.CHARGED
        ):
            raise ValueError("successful account-gap operation lacks terminal receipts")
        if (self.state is AccountGapOperationState.SPEND_OUTCOME_UNKNOWN) != (
            self.spend_outcome is AccountGapSpendOutcome.UNKNOWN
        ):
            raise ValueError("unknown account-gap state requires unknown spend")
        if (
            not self.request.allow_unbounded_tech
            and self.provider_units_charged > self.provider_units_reserved
        ):
            raise ValueError("bounded account-gap charge exceeds its reservation")
        return self


class AccountGapSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: AccountGapOperationId
    workspace_id: NonEmptyStr
    account_id: EntityId
    source_key: NonEmptyStr
    request_fingerprint: Sha256Hex
    state: AccountGapSnapshotState
    spend_outcome: AccountGapSpendOutcome
    request_artifact_key: NonEmptyStr
    response_artifact_key: str | None = None
    provider_request_id: str | None = None
    provider_units_reserved: ProviderUnits = Decimal(0)
    provider_units_charged: ProviderUnits = Decimal(0)
    credits_remaining: int | None = Field(default=None, ge=0)
    cost_cents_charged: CostCents = Decimal(0)
    unbounded_call_approved: bool = False
    failure_code: str | None = None
    started_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> AccountGapSnapshot:
        terminal = self.state in {
            AccountGapSnapshotState.SUCCEEDED,
            AccountGapSnapshotState.NOT_APPLICABLE,
            AccountGapSnapshotState.FAILED_TERMINAL,
            AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("account-gap snapshot terminal timestamp is incoherent")
        if self.state is AccountGapSnapshotState.SUCCEEDED and (
            self.response_artifact_key is None
            or self.provider_request_id is None
            or self.spend_outcome is not AccountGapSpendOutcome.CHARGED
        ):
            raise ValueError("successful account-gap snapshot lacks provider evidence")
        if self.state is AccountGapSnapshotState.NOT_APPLICABLE and (
            self.spend_outcome is not AccountGapSpendOutcome.NOT_CHARGED
        ):
            raise ValueError("not-applicable account-gap snapshot must be uncharged")
        if (self.state is AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN) != (
            self.spend_outcome is AccountGapSpendOutcome.UNKNOWN
        ):
            raise ValueError("unknown account-gap snapshot requires unknown spend")
        if not self.unbounded_call_approved and (
            self.provider_units_charged > self.provider_units_reserved
        ):
            raise ValueError("bounded account-gap snapshot charge exceeds its reservation")
        return self


class AccountGapFieldResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: AccountGapOperationId
    account_id: EntityId
    field_key: FieldKey
    source_key: NonEmptyStr
    state: AccountGapFieldState
    sumble_claim_id: ClaimId | None = None
    current_claim_id: ClaimId | None = None
    conflicting_claim_ids: tuple[ClaimId, ...] = ()
    reason_code: str | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _terminal_shape(self) -> AccountGapFieldResult:
        if (
            self.state
            in {
                AccountGapFieldState.RESOLVED,
                AccountGapFieldState.CORROBORATED,
            }
            and self.sumble_claim_id is None
        ):
            raise ValueError("resolved account-gap field lacks its Sumble claim")
        if self.state is AccountGapFieldState.CONFLICT and (
            self.sumble_claim_id is None or not self.conflicting_claim_ids
        ):
            raise ValueError("conflicting account-gap field lacks contender claims")
        if (
            self.state
            in {
                AccountGapFieldState.PENDING,
                AccountGapFieldState.CONFIRMED_MISSING,
                AccountGapFieldState.FAILED_TERMINAL,
            }
            and self.sumble_claim_id is not None
        ):
            raise ValueError("non-resolved account-gap field cannot carry a Sumble claim")
        return self


__all__ = [
    "AccountGapFieldPlan",
    "AccountGapFieldResult",
    "AccountGapFieldState",
    "AccountGapOperation",
    "AccountGapOperationId",
    "AccountGapOperationState",
    "AccountGapReason",
    "AccountGapRequest",
    "AccountGapSnapshot",
    "AccountGapSnapshotState",
    "AccountGapSpendOutcome",
    "new_account_gap_operation_id",
]
