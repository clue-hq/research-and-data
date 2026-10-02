"""Provider-neutral durable contracts for one-account committee acquisition."""

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
from clue_core.primitives import ClaimId, CostCents, EntityId, ProjectRunId, UtcDatetime
from clue_core.research_directive import ResearchDirectivePin

CommitteeAcquisitionOperationId = NewType("CommitteeAcquisitionOperationId", UUID)
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProviderUnits = Annotated[Decimal, Ge(0)]


def new_committee_acquisition_operation_id() -> CommitteeAcquisitionOperationId:
    return CommitteeAcquisitionOperationId(uuid4())


class CommitteeAcquisitionState(StrEnum):
    PLANNED = "planned"
    ACQUIRING_TEAMS = "acquiring_teams"
    SUBMITTING_PEOPLE = "submitting_people"
    WAITING_EXTERNAL = "waiting_external"
    POLLING_PEOPLE = "polling_people"
    READY = "ready"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    CANCELLED = "cancelled"


class CommitteeSnapshotState(StrEnum):
    PLANNED = "planned"
    DISPATCHING = "dispatching"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class CommitteeSpendOutcome(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    UNKNOWN = "unknown"
    NOT_CHARGED = "not_charged"
    CHARGED = "charged"


class CommitteeAttemptKind(StrEnum):
    TEAMS_SEARCH = "teams_search"
    PEOPLE_SUBMIT = "people_submit"
    PEOPLE_POLL = "people_poll"


class CommitteeAttemptState(StrEnum):
    DISPATCHING = "dispatching"
    RESPONDED = "responded"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class CommitteeAcquisitionRequest(BaseModel):
    """Immutable intent for bounded Teams plus no-reveal People acquisition."""

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
    tier_claim_id: ClaimId | None = None
    committee_plan_ref: NonEmptyStr
    research_direction_ref: NonEmptyStr
    research_directive: ResearchDirectivePin
    organization_identity_ref: NonEmptyStr
    provider_organization_id: NonEmptyStr
    provider_api_version: NonEmptyStr
    provider_contract_version: NonEmptyStr
    pricing_policy_version: NonEmptyStr
    committee_policy_version: NonEmptyStr
    observation_window: NonEmptyStr
    provider_filter_expression: str | None = Field(default=None, max_length=2_000)
    team_limit: int = Field(ge=1, le=200)
    related_people_per_team: int = Field(ge=1, le=100)
    jobs_per_team: int = Field(ge=1, le=100)
    people_limit: int = Field(ge=1, le=200)
    people_offset: int = Field(default=0, ge=0, le=10_000)
    provider_credit_cap: int = Field(ge=0)
    money_budget_cap_cents: CostCents = Decimal(0)

    @model_validator(mode="after")
    def _normalized_provider_plan(self) -> CommitteeAcquisitionRequest:
        if self.research_direction_ref != self.research_directive.directive_ref:
            raise ValueError("committee request directive ref and exact pin must agree")
        if self.account_id != self.research_directive.account_id:
            raise ValueError("committee request directive pin belongs to another account")
        if self.entity_research_job_id is None and self.tier_claim_id is None:
            raise ValueError("historical committee request requires an exact tier claim")
        if self.provider_filter_expression is not None:
            if self.provider_filter_expression != self.provider_filter_expression.strip():
                raise ValueError("committee provider filter must be pre-normalized")
            if "\n" in self.provider_filter_expression or "\r" in self.provider_filter_expression:
                raise ValueError("committee provider filter must be a single line")
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


class CommitteeAcquisitionOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: CommitteeAcquisitionOperationId
    request: CommitteeAcquisitionRequest
    request_fingerprint: Sha256Hex
    state: CommitteeAcquisitionState
    spend_outcome: CommitteeSpendOutcome
    input_artifact_key: NonEmptyStr
    receipt_manifest_key: str | None = None
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
    def _coherent(self) -> CommitteeAcquisitionOperation:
        if self.request_fingerprint != self.request.request_fingerprint:
            raise ValueError("committee acquisition request fingerprint mismatch")
        terminal = self.state in {
            CommitteeAcquisitionState.READY,
            CommitteeAcquisitionState.FAILED_TERMINAL,
            CommitteeAcquisitionState.SPEND_OUTCOME_UNKNOWN,
            CommitteeAcquisitionState.CANCELLED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("committee acquisition terminal timestamp is incoherent")
        if self.state is CommitteeAcquisitionState.READY and self.receipt_manifest_key is None:
            raise ValueError("ready committee acquisition lacks its receipt manifest")
        if (self.state is CommitteeAcquisitionState.SPEND_OUTCOME_UNKNOWN) != (
            self.spend_outcome is CommitteeSpendOutcome.UNKNOWN
        ):
            raise ValueError("unknown committee acquisition requires unknown spend")
        if self.provider_units_charged > self.provider_units_reserved:
            raise ValueError("committee acquisition charge exceeds its reservation")
        if self.cost_cents_charged > self.cost_cents_reserved:
            raise ValueError("committee acquisition cost exceeds its reservation")
        if self.state is CommitteeAcquisitionState.WAITING_EXTERNAL:
            if self.next_poll_at is None:
                raise ValueError("waiting committee acquisition requires next_poll_at")
        elif self.next_poll_at is not None:
            raise ValueError("only waiting committee acquisition may carry next_poll_at")
        return self


class CommitteeAcquisitionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: CommitteeAcquisitionOperationId
    workspace_id: NonEmptyStr
    account_id: EntityId
    source_key: NonEmptyStr
    request_fingerprint: Sha256Hex
    state: CommitteeSnapshotState
    spend_outcome: CommitteeSpendOutcome
    request_artifact_key: NonEmptyStr
    response_artifact_key: str | None = None
    provider_operation_id: str | None = None
    provider_status: str | None = None
    provider_units_reserved: ProviderUnits = Decimal(0)
    provider_units_charged: ProviderUnits = Decimal(0)
    credits_remaining: int | None = Field(default=None, ge=0)
    cost_cents_charged: CostCents = Decimal(0)
    failure_code: str | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> CommitteeAcquisitionSnapshot:
        if self.state is CommitteeSnapshotState.SUCCEEDED and (
            self.response_artifact_key is None or self.provider_status != "succeeded"
        ):
            raise ValueError("succeeded committee snapshot lacks terminal provider evidence")
        if self.state is CommitteeSnapshotState.WAITING_EXTERNAL and (
            not self.provider_operation_id
            or self.provider_status not in {"pending", "running"}
            or self.response_artifact_key is None
        ):
            raise ValueError("waiting committee snapshot lacks asynchronous provider evidence")
        if (self.state is CommitteeSnapshotState.SPEND_OUTCOME_UNKNOWN) != (
            self.spend_outcome is CommitteeSpendOutcome.UNKNOWN
        ):
            raise ValueError("unknown committee snapshot requires unknown spend")
        if self.provider_units_charged > self.provider_units_reserved:
            raise ValueError("committee snapshot charge exceeds its reservation")
        return self


class CommitteeAcquisitionAttempt(BaseModel):
    """One durable dispatch boundary; terminal rows are immutable provider history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: CommitteeAcquisitionOperationId
    workspace_id: NonEmptyStr
    ordinal: int = Field(ge=0)
    source_key: NonEmptyStr
    kind: CommitteeAttemptKind
    state: CommitteeAttemptState
    request_artifact_key: NonEmptyStr
    response_artifact_key: str | None = None
    provider_operation_id: str | None = None
    provider_status: str | None = None
    provider_units_charged: ProviderUnits = Decimal(0)
    credits_remaining: int | None = Field(default=None, ge=0)
    failure_code: str | None = None
    dispatched_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _terminal_shape(self) -> CommitteeAcquisitionAttempt:
        terminal = self.state is not CommitteeAttemptState.DISPATCHING
        if terminal != (self.completed_at is not None):
            raise ValueError("committee attempt completion timestamp is incoherent")
        if self.state is CommitteeAttemptState.RESPONDED and self.response_artifact_key is None:
            raise ValueError("responded committee attempt lacks a response artifact")
        if self.state is CommitteeAttemptState.SPEND_OUTCOME_UNKNOWN and not self.failure_code:
            raise ValueError("unknown committee attempt requires a failure code")
        return self


__all__ = [
    "CommitteeAcquisitionAttempt",
    "CommitteeAcquisitionOperation",
    "CommitteeAcquisitionOperationId",
    "CommitteeAcquisitionRequest",
    "CommitteeAcquisitionSnapshot",
    "CommitteeAcquisitionState",
    "CommitteeAttemptKind",
    "CommitteeAttemptState",
    "CommitteeSnapshotState",
    "CommitteeSpendOutcome",
    "new_committee_acquisition_operation_id",
]
