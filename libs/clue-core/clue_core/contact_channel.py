"""Provider-neutral selected-contact channel acquisition and validation contracts (M8C C5)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType, Protocol, runtime_checkable
from uuid import UUID, uuid4

from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from clue_core.contact_research import (
    CONTACT_CHANNEL_FIELD_KEYS,
    ChannelIdentityCorroboration,
    ChannelReachability,
    ChannelUseDecision,
    ContactChannel,
    ContactChannelState,
    ContactChannelValidation,
)
from clue_core.discovery import Sha256Hex
from clue_core.enums import IdentityBinding
from clue_core.primitives import ClaimId, EntityId, ProjectRunId, UtcDatetime

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProviderUnits = Annotated[Decimal, Ge(0)]
ContactChannelOperationId = NewType("ContactChannelOperationId", UUID)


def new_contact_channel_operation_id() -> ContactChannelOperationId:
    return ContactChannelOperationId(uuid4())


class ContactChannelOperationState(StrEnum):
    PLANNED = "planned"
    SUBMITTING = "submitting"
    WAITING_EXTERNAL = "waiting_external"
    READY_TO_VALIDATE = "ready_to_validate"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    CANCELLED = "cancelled"


class ContactChannelSpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    NOT_CHARGED = "not_charged"
    CHARGED = "charged"


class ContactChannelValidationOutcome(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class ContactChannelAcquisitionRequest(BaseModel):
    """Immutable authorization for one selected contact and exactly one channel.

    The request contains no raw channel value. It pins the receipt, exact contact/account,
    acquisition and validation sources, independent budgets, retention, and strong profile URL.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    entity_research_job_id: UUID | None = None
    account_id: EntityId
    contact_id: EntityId
    selection_id: UUID
    selection_sha256: Sha256Hex
    contact_intent_sha256: Sha256Hex
    channel: ContactChannel
    field_key: NonEmptyStr
    acquisition_source_key: NonEmptyStr
    validation_source_key: NonEmptyStr
    provider_api_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    validation_contract_version: NonEmptyStr
    pricing_policy_version: NonEmptyStr
    effective_policy_sha256: Sha256Hex
    jurisdiction_policy_ref: NonEmptyStr
    jurisdiction_regime: NonEmptyStr
    use_policy_ref: NonEmptyStr
    retention_policy_ref: NonEmptyStr
    observation_window: NonEmptyStr
    freshness_seconds: int = Field(ge=1)
    retention_seconds: int = Field(ge=1)
    email_identity_promotion_allowed: bool
    canonical_profile_url: NonEmptyStr
    canonical_full_name: NonEmptyStr
    employer_name: NonEmptyStr
    employer_domain: NonEmptyStr
    acquisition_native_unit_cap: ProviderUnits
    acquisition_budget_cap_cents: Decimal = Field(ge=0)
    validation_native_unit_cap: ProviderUnits
    validation_budget_cap_cents: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _exact_channel_and_budgets(self) -> ContactChannelAcquisitionRequest:
        if self.field_key != CONTACT_CHANNEL_FIELD_KEYS[self.channel]:
            raise ValueError("channel request field does not match its exact channel")
        if self.acquisition_source_key == self.validation_source_key:
            raise ValueError("channel validation must be independent from acquisition")
        if self.acquisition_native_unit_cap <= 0:
            raise ValueError("channel acquisition requires a positive native-unit cap")
        if self.validation_native_unit_cap <= 0:
            raise ValueError("channel validation requires a positive native-unit cap")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @property
    def request_fingerprint(self) -> Sha256Hex:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @property
    def provider_external_id(self) -> str:
        return f"clue-contact-{self.channel.value}-{self.request_fingerprint[:40]}"


class ContactChannelOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: ContactChannelOperationId
    request: ContactChannelAcquisitionRequest
    request_fingerprint: Sha256Hex
    state: ContactChannelOperationState
    acquisition_spend_outcome: ContactChannelSpendOutcome
    validation_spend_outcome: ContactChannelSpendOutcome
    input_artifact_key: NonEmptyStr
    csv_artifact_key: NonEmptyStr
    provider_import_id: str | None = None
    provider_operation_id: str | None = None
    observed_claim_id: ClaimId | None = None
    observation_artifact_key: str | None = None
    validation_artifact_key: str | None = None
    receipt_artifact_key: str | None = None
    acquisition_units_charged: ProviderUnits = Decimal(0)
    acquisition_cost_cents_charged: Decimal = Field(default=Decimal(0), ge=0)
    validation_units_charged: ProviderUnits = Decimal(0)
    validation_cost_cents_charged: Decimal = Field(default=Decimal(0), ge=0)
    validation: ContactChannelValidation | None = None
    next_poll_at: UtcDatetime | None = None
    failure_code: str | None = None
    started_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> ContactChannelOperation:
        if self.request_fingerprint != self.request.request_fingerprint:
            raise ValueError("contact channel request fingerprint mismatch")
        terminal = self.state in {
            ContactChannelOperationState.SUCCEEDED,
            ContactChannelOperationState.REJECTED,
            ContactChannelOperationState.FAILED_TERMINAL,
            ContactChannelOperationState.CANCELLED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("contact channel terminal timestamp is incoherent")
        if self.acquisition_units_charged > self.request.acquisition_native_unit_cap:
            raise ValueError("channel acquisition charge exceeds reservation")
        if self.validation_units_charged > self.request.validation_native_unit_cap:
            raise ValueError("channel validation charge exceeds reservation")
        if self.acquisition_cost_cents_charged > self.request.acquisition_budget_cap_cents:
            raise ValueError("channel acquisition money charge exceeds reservation")
        if self.validation_cost_cents_charged > self.request.validation_budget_cap_cents:
            raise ValueError("channel validation money charge exceeds reservation")
        acquired = self.state in {
            ContactChannelOperationState.READY_TO_VALIDATE,
            ContactChannelOperationState.VALIDATING,
            ContactChannelOperationState.SUCCEEDED,
            ContactChannelOperationState.REJECTED,
        }
        if acquired and (
            self.acquisition_spend_outcome is not ContactChannelSpendOutcome.CHARGED
            or self.observed_claim_id is None
            or self.observation_artifact_key is None
        ):
            raise ValueError("acquired channel operation lacks charged observed evidence")
        if self.state is ContactChannelOperationState.SUCCEEDED and (
            self.validation is None
            or self.validation.state
            not in {ContactChannelState.VALIDATED, ContactChannelState.VERIFIED_IDENTITY}
            or not self.validation.delivery_eligible
            or self.validation_spend_outcome is not ContactChannelSpendOutcome.CHARGED
            or self.observed_claim_id is None
            or self.receipt_artifact_key is None
        ):
            raise ValueError("successful channel operation lacks validated durable evidence")
        if self.state is ContactChannelOperationState.REJECTED and (
            self.validation is None or self.validation.state is not ContactChannelState.REJECTED
        ):
            raise ValueError("rejected channel operation requires a rejected validation")
        return self


class ContactChannelValidatorRequest(BaseModel):
    """Value-bearing request sent only to the separately authorized validation adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: ContactChannelOperationId
    workspace_id: NonEmptyStr
    account_id: EntityId
    contact_id: EntityId
    channel: ContactChannel
    value: NonEmptyStr
    value_sha256: Sha256Hex
    canonical_full_name: NonEmptyStr
    employer_name: NonEmptyStr
    employer_domain: NonEmptyStr
    observed_claim_id: ClaimId

    @model_validator(mode="after")
    def _digest_matches(self) -> ContactChannelValidatorRequest:
        if hashlib.sha256(self.value.strip().lower().encode()).hexdigest() != self.value_sha256:
            raise ValueError("validator channel-value digest mismatch")
        return self


class ContactChannelValidatorResult(BaseModel):
    """One independent corroboration and reachability verdict with native settlement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ContactChannelValidationOutcome
    identity_binding: IdentityBinding
    corroboration: ChannelIdentityCorroboration
    reachability: ChannelReachability
    corroborating_claim_ids: tuple[ClaimId, ...] = ()
    provider_reference_ids: tuple[NonEmptyStr, ...] = ()
    evidence: dict[str, JsonValue]
    provider_units_charged: ProviderUnits
    provider_cost_cents_charged: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _has_independent_evidence(self) -> ContactChannelValidatorResult:
        if len(set(self.corroborating_claim_ids)) != len(self.corroborating_claim_ids):
            raise ValueError("validator corroborating claim ids must be unique")
        if len(set(self.provider_reference_ids)) != len(self.provider_reference_ids):
            raise ValueError("validator reference ids must be unique")
        if not self.provider_reference_ids or not self.evidence:
            raise ValueError("validator result requires durable independent evidence")
        return self

    def to_validation(
        self,
        *,
        channel: ContactChannel,
        observed_claim_id: ClaimId,
        allow_identity_promotion: bool,
        use_decision: ChannelUseDecision,
    ) -> ContactChannelValidation:
        if self.outcome is ContactChannelValidationOutcome.REJECTED:
            state = ContactChannelState.REJECTED
        elif self.outcome is ContactChannelValidationOutcome.VALIDATED:
            state = (
                ContactChannelState.VERIFIED_IDENTITY
                if channel is ContactChannel.EMAIL
                and allow_identity_promotion
                and self.identity_binding is IdentityBinding.STRONG
                else ContactChannelState.VALIDATED
            )
        else:
            state = ContactChannelState.OBSERVED
        return ContactChannelValidation(
            channel=channel,
            observed_claim_id=observed_claim_id,
            state=state,
            identity_binding=self.identity_binding,
            corroboration=self.corroboration,
            reachability=self.reachability,
            use_decision=use_decision,
            corroborating_claim_ids=self.corroborating_claim_ids,
            validation_reference_ids=self.provider_reference_ids,
        )


@runtime_checkable
class ContactChannelValidator(Protocol):
    source_key: str

    async def validate(
        self, request: ContactChannelValidatorRequest
    ) -> ContactChannelValidatorResult: ...


__all__ = [
    "ContactChannelAcquisitionRequest",
    "ContactChannelOperation",
    "ContactChannelOperationId",
    "ContactChannelOperationState",
    "ContactChannelSpendOutcome",
    "ContactChannelValidationOutcome",
    "ContactChannelValidator",
    "ContactChannelValidatorRequest",
    "ContactChannelValidatorResult",
    "new_contact_channel_operation_id",
]
