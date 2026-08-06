"""M8D R8 contact-agent semantic contracts over the shared R0-R4 runtime."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core.entity_research import ContactChannel, ResearchFinalizationOutcome

NonEmptyStr = Annotated[str, Field(min_length=1)]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReadContactResearchStateInput(_FrozenModel):
    include_result_index: bool = True


class InspectContactEvidenceInput(_FrozenModel):
    result_refs: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("contact evidence result references must be unique")
        return self


class AssessContactCoverageInput(_FrozenModel):
    result_refs: tuple[NonEmptyStr, ...] = Field(max_length=100)
    assessment_note: NonEmptyStr

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("contact coverage result references must be unique")
        return self


class FinalizeContactResearchInput(_FrozenModel):
    coverage_ledger_ref: NonEmptyStr
    requested_outcome: ResearchFinalizationOutcome


class DelegateContactFacetInput(_FrozenModel):
    facet_key: NonEmptyStr
    question: NonEmptyStr


class ContactChannelToolInput(_FrozenModel):
    channel: ContactChannel


class ContactFacetProjection(_FrozenModel):
    facet_key: NonEmptyStr
    child_ordinal: int = Field(ge=1, le=2)
    state: Literal["started", "waiting_external", "completed"]
    child_turn_id: UUID
    result_refs: tuple[NonEmptyStr, ...] = ()
    claim_refs: tuple[NonEmptyStr, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    wait_ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _state_shape(self) -> Self:
        if (self.state == "waiting_external") != (self.wait_ref is not None):
            raise ValueError("waiting facet requires exactly one wait reference")
        if self.state == "started" and (self.result_refs or self.claim_refs or self.evidence_refs):
            raise ValueError("started facet cannot publish result references")
        return self


class ContactChannelProjection(_FrozenModel):
    channel: ContactChannel
    operation_ref: NonEmptyStr
    stage: Literal["acquisition", "validation"]
    state: NonEmptyStr
    acquisition_source_key: NonEmptyStr
    validation_source_key: NonEmptyStr
    observed_claim_ref: NonEmptyStr | None = None
    validation_state: NonEmptyStr | None = None
    delivery_eligible: bool = False
    artifact_refs: tuple[NonEmptyStr, ...] = ()
    provider_request_ids: tuple[NonEmptyStr, ...] = ()
    acquisition_cost_cents: str
    validation_cost_cents: str


class ContactIdentityProjection(_FrozenModel):
    contact_entity_id: UUID
    parent_account_id: UUID
    full_name: NonEmptyStr
    linkedin_url: str | None = None
    verified_email: str | None = None
    account_name: NonEmptyStr
    account_domain: str | None = None


class ContactExistingClaimProjection(_FrozenModel):
    field_key: NonEmptyStr
    claim_ref: NonEmptyStr
    value: JsonValue
    source_url: str | None = None
    source_tier: int = Field(ge=1, le=4)
    evidence_span: str | None = None
    confidence: float = Field(ge=0, le=1)
    freshness_state: Literal["fresh", "stale"]
    conflict: bool


class ContactResearchStateProjection(_FrozenModel):
    job_id: UUID
    contact_entity_id: UUID
    parent_account_id: UUID
    current_state_sha256: NonEmptyStr
    identity_lock_ref: NonEmptyStr
    identity: ContactIdentityProjection
    admitted_field_keys: tuple[NonEmptyStr, ...]
    admitted_source_keys: tuple[NonEmptyStr, ...]
    existing_claims: tuple[ContactExistingClaimProjection, ...]
    result_refs: tuple[NonEmptyStr, ...]
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    facet_projections: tuple[ContactFacetProjection, ...]
    channel_projections: tuple[ContactChannelProjection, ...]
    pending_operation_refs: tuple[NonEmptyStr, ...]
    spent_cents: str


class ContactCoverageProjection(_FrozenModel):
    coverage_id: UUID
    coverage_ledger_ref: NonEmptyStr
    current_state_sha256: NonEmptyStr
    identity_lock_ref: NonEmptyStr
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    unresolved_reasons: tuple[NonEmptyStr, ...]
    result_refs: tuple[NonEmptyStr, ...]
    facet_refs: tuple[NonEmptyStr, ...]
    channel_operation_refs: tuple[NonEmptyStr, ...]
    claim_refs: tuple[NonEmptyStr, ...]
    evidence_refs: tuple[NonEmptyStr, ...]
    review_flags: tuple[NonEmptyStr, ...]
    review_item_refs: tuple[NonEmptyStr, ...]
    assessment_note: NonEmptyStr

    def as_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


__all__ = [
    "AssessContactCoverageInput",
    "ContactChannelProjection",
    "ContactChannelToolInput",
    "ContactCoverageProjection",
    "ContactExistingClaimProjection",
    "ContactFacetProjection",
    "ContactIdentityProjection",
    "ContactResearchStateProjection",
    "DelegateContactFacetInput",
    "FinalizeContactResearchInput",
    "InspectContactEvidenceInput",
    "ReadContactResearchStateInput",
]
