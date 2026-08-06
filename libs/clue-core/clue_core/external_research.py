"""Provider-neutral external-research acquisition, preparation and DEEP wait contracts.

External acquisition happens before a short claim-materialization transaction. Request contracts
pin admitted immutable lineage; ready/preparation/wait contracts carry only durable references and
scheduling metadata. Response bodies remain artifact-backed and provider lifecycle state remains in
the durable adapter rather than leaking into orchestrator checkpoints.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from clue_core.primitives import EntityId, ProjectRunId, RunId, UtcDatetime
from clue_core.research_directive import ResearchDirectivePin

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

ExternalResearchOperationId = NewType("ExternalResearchOperationId", UUID)
ExternalResearchSnapshotId = NewType("ExternalResearchSnapshotId", UUID)


def new_external_research_operation_id() -> ExternalResearchOperationId:
    return ExternalResearchOperationId(uuid4())


def new_external_research_snapshot_id() -> ExternalResearchSnapshotId:
    return ExternalResearchSnapshotId(uuid4())


class ExternalResearchSubjectKind(StrEnum):
    ACCOUNT = "account"
    CONTACT = "contact"


class ExternalResearchOperationState(StrEnum):
    PLANNED = "planned"
    DISPATCHING = "dispatching"
    READY = "ready"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    CANCELLED = "cancelled"


class ExternalResearchAttemptState(StrEnum):
    DISPATCHING = "dispatching"
    RESPONDED = "responded"
    FAILED_PRE_DISPATCH = "failed_pre_dispatch"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class ExternalResearchSpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    NOT_CHARGED = "not_charged"
    PROVIDER_REPORTED = "provider_reported"
    UNKNOWN = "unknown"


class ExternalResearchReconciliationState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING_PROVIDER_BILLING = "pending_provider_billing"
    RECONCILED = "reconciled"


class ExternalResearchCostDisposition(StrEnum):
    """Authoritative provider-billing disposition recorded after an initial estimate/ambiguity."""

    CHARGED = "charged"
    NOT_CHARGED = "not_charged"


class ExternalResearchAcquisitionRequest(BaseModel):
    """Provider-neutral immutable input for one bounded external-research operation.

    The provider wire body is already compiled and policy-admitted.  This contract intentionally
    does not know how the provider is called or how its response becomes claims.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    entity_research_job_id: UUID | None = None
    subject_kind: ExternalResearchSubjectKind = ExternalResearchSubjectKind.ACCOUNT
    account_id: EntityId
    contact_id: EntityId | None = None
    icp_key: NonEmptyStr
    icp_version: int = Field(ge=1)
    research_directive: ResearchDirectivePin
    source_key: NonEmptyStr
    observation_window: NonEmptyStr
    freshness_policy_ref: NonEmptyStr
    freshness_seconds: int = Field(ge=1)
    # Stable across project runs and observation-window labels for the same immutable provider
    # request.  It is the serialization/reuse identity; ``request_fingerprint`` remains the exact
    # consumer-operation identity and therefore includes its run/window lineage.
    reuse_fingerprint: Sha256Hex
    request_fingerprint: Sha256Hex
    wire_request_sha256: Sha256Hex
    request_payload: dict[str, JsonValue]
    cost_cents_reserved: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _subject_and_directive_are_exact(self) -> ExternalResearchAcquisitionRequest:
        if self.research_directive.account_id != self.account_id:
            raise ValueError("external research directive pin belongs to another account")
        if self.subject_kind is ExternalResearchSubjectKind.ACCOUNT and self.contact_id is not None:
            raise ValueError("account research cannot carry a contact id")
        if self.subject_kind is ExternalResearchSubjectKind.CONTACT and self.contact_id is None:
            raise ValueError("contact research requires a contact id")
        if not self.request_payload:
            raise ValueError("external research request payload must be non-empty")
        return self


class ExternalResearchSnapshotRef(BaseModel):
    """Reference-only output consumed by later materialization slices."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: ExternalResearchSnapshotId
    operation_id: ExternalResearchOperationId
    workspace_id: NonEmptyStr
    subject_kind: ExternalResearchSubjectKind
    account_id: EntityId
    contact_id: EntityId | None = None
    source_key: NonEmptyStr
    request_fingerprint: Sha256Hex
    request_artifact_key: NonEmptyStr
    response_artifact_key: NonEmptyStr
    normalization_artifact_key: NonEmptyStr
    provider_request_id: NonEmptyStr
    provider_reported_cost_cents: Decimal = Field(ge=0)
    all_null: bool
    fresh_until: UtcDatetime

    @model_validator(mode="after")
    def _subject_is_exact(self) -> ExternalResearchSnapshotRef:
        if self.subject_kind is ExternalResearchSubjectKind.ACCOUNT and self.contact_id is not None:
            raise ValueError("account snapshot cannot carry a contact id")
        if self.subject_kind is ExternalResearchSubjectKind.CONTACT and self.contact_id is None:
            raise ValueError("contact snapshot requires a contact id")
        return self


class ExternalResearchPreparationOutcome(StrEnum):
    READY = "ready"
    WAITING_EXTERNAL = "waiting_external"
    INELIGIBLE = "ineligible"
    FAILED = "failed"


class ExternalResearchPreparation(BaseModel):
    """One provider-neutral acquisition result, containing references rather than payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExternalResearchPreparationOutcome
    operation_ref: NonEmptyStr | None = None
    snapshot_refs: tuple[NonEmptyStr, ...] = ()
    retry_after: UtcDatetime | None = None
    cost_receipt_ref: NonEmptyStr | None = None
    audit_refs: tuple[NonEmptyStr, ...] = ()
    reason_code: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _coherent(self) -> ExternalResearchPreparation:
        if len(self.snapshot_refs) != len(set(self.snapshot_refs)):
            raise ValueError("external-research snapshot references must be unique")
        if len(self.audit_refs) != len(set(self.audit_refs)):
            raise ValueError("external-research audit references must be unique")
        if self.outcome is ExternalResearchPreparationOutcome.WAITING_EXTERNAL:
            if self.operation_ref is None or self.retry_after is None:
                raise ValueError("an external wait requires an operation reference and retry time")
        elif self.retry_after is not None:
            raise ValueError("only an external wait may carry a retry time")
        if (
            self.outcome
            in {
                ExternalResearchPreparationOutcome.INELIGIBLE,
                ExternalResearchPreparationOutcome.FAILED,
            }
            and self.reason_code is None
        ):
            raise ValueError("an ineligible or failed preparation requires a reason code")
        return self


class DeepAccountExternalWait(BaseModel):
    """The pending external operation for one resumable account-deep run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    account_run_id: RunId
    preparation: ExternalResearchPreparation

    @model_validator(mode="after")
    def _is_waiting(self) -> DeepAccountExternalWait:
        if self.preparation.outcome is not ExternalResearchPreparationOutcome.WAITING_EXTERNAL:
            raise ValueError("a deep external wait must carry a waiting preparation")
        return self


class DeepExternalWakeReason(StrEnum):
    SCHEDULED_POLL = "scheduled_poll"
    PROVIDER_EVENT = "provider_event"
    MANUAL_RECONCILE = "manual_reconcile"
    CRASH_RECOVERY = "crash_recovery"


class DeepExternalWait(BaseModel):
    """Reference-only DEEP phase checkpoint while account operations wait externally."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_accounts: tuple[DeepAccountExternalWait, ...]
    next_poll_at: UtcDatetime
    wake_reason: DeepExternalWakeReason = DeepExternalWakeReason.SCHEDULED_POLL

    @model_validator(mode="after")
    def _bounded_and_consistent(self) -> DeepExternalWait:
        if not self.pending_accounts:
            raise ValueError("a deep external wait requires at least one pending account")
        account_ids = tuple(item.account_entity_id for item in self.pending_accounts)
        run_ids = tuple(item.account_run_id for item in self.pending_accounts)
        if len(account_ids) != len(set(account_ids)) or len(run_ids) != len(set(run_ids)):
            raise ValueError("deep external wait accounts and account runs must be unique")
        retry_times = tuple(item.preparation.retry_after for item in self.pending_accounts)
        if any(value is None for value in retry_times):  # defended by the nested model
            raise ValueError("every pending account requires a retry time")
        if self.next_poll_at != min(value for value in retry_times if value is not None):
            raise ValueError("deep next_poll_at must be the earliest pending retry")
        return self


__all__ = [
    "DeepAccountExternalWait",
    "DeepExternalWait",
    "DeepExternalWakeReason",
    "ExternalResearchPreparation",
    "ExternalResearchPreparationOutcome",
    "ExternalResearchAcquisitionRequest",
    "ExternalResearchAttemptState",
    "ExternalResearchCostDisposition",
    "ExternalResearchOperationId",
    "ExternalResearchOperationState",
    "ExternalResearchReconciliationState",
    "ExternalResearchSnapshotId",
    "ExternalResearchSnapshotRef",
    "ExternalResearchSpendOutcome",
    "ExternalResearchSubjectKind",
    "new_external_research_operation_id",
    "new_external_research_snapshot_id",
]
