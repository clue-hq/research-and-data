"""R5 account-agent semantic contracts layered over the frozen M8D R0/R4 kernel."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_agents.entity_research_tools import EntityResearchSemanticToolInput
from clue_core.entity_research import ResearchFinalizationOutcome

NonEmptyStr = Annotated[str, Field(min_length=1)]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountBuyingUnitScope(_FrozenModel):
    """The exact office/facility/business unit the account agent elects to map.

    At least one location discriminator and retained account-evidence reference are mandatory.
    The provider may enumerate a broader organization, but only candidates matching this scope may
    be projected as committee members; ambiguous rows become durable review, never silent admits.
    """

    scope_id: UUID
    account_entity_id: UUID
    office_label: NonEmptyStr
    facility_name: NonEmptyStr | None = None
    locality: NonEmptyStr | None = None
    region: NonEmptyStr | None = None
    country: NonEmptyStr | None = None
    business_unit: NonEmptyStr | None = None
    target_functions: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=20)
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=20)
    match_policy: Literal["same_office_strict"] = "same_office_strict"

    @model_validator(mode="after")
    def _bounded_office(self) -> Self:
        if not any((self.facility_name, self.locality, self.region, self.business_unit)):
            raise ValueError("buying-unit scope requires an office, facility, region, or unit")
        if len(self.target_functions) != len(set(self.target_functions)):
            raise ValueError("buying-unit target functions must be unique")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("buying-unit evidence references must be unique")
        return self


class DiscoverBuyingCommitteeInput(EntityResearchSemanticToolInput):
    """Committee research intent plus an account-evidence-backed office boundary."""

    buying_unit_scope: AccountBuyingUnitScope


class ReadAccountResearchStateInput(_FrozenModel):
    include_result_index: bool = True


class InspectAccountEvidenceInput(_FrozenModel):
    result_refs: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("account evidence result references must be unique")
        return self


class AssessAccountCoverageInput(_FrozenModel):
    """Model explanation is advisory; the engine derives coverage from persisted results."""

    result_refs: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=100)
    assessment_note: NonEmptyStr

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("coverage result references must be unique")
        return self


class FinalizeAccountResearchInput(_FrozenModel):
    coverage_ledger_ref: NonEmptyStr
    requested_outcome: ResearchFinalizationOutcome


class AccountResearchStateProjection(_FrozenModel):
    job_id: UUID
    account_entity_id: UUID
    current_state_sha256: NonEmptyStr
    admitted_field_keys: tuple[NonEmptyStr, ...]
    admitted_source_keys: tuple[NonEmptyStr, ...]
    committee_source_keys: tuple[NonEmptyStr, ...]
    result_refs: tuple[NonEmptyStr, ...]
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    committee_result_refs: tuple[NonEmptyStr, ...]
    committee_member_ids: tuple[UUID, ...]
    pending_operation_refs: tuple[NonEmptyStr, ...]
    spent_cents: str
    contact_research_request_count: int = Field(ge=0)


class AccountCoverageProjection(_FrozenModel):
    coverage_id: UUID
    coverage_ledger_ref: NonEmptyStr
    current_state_sha256: NonEmptyStr
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    unresolved_reasons: tuple[NonEmptyStr, ...]
    committee_result_refs: tuple[NonEmptyStr, ...]
    committee_member_ids: tuple[UUID, ...]
    committee_status: Literal["complete", "partial", "needs_review"]
    claim_refs: tuple[NonEmptyStr, ...]
    evidence_refs: tuple[NonEmptyStr, ...]
    review_flags: tuple[NonEmptyStr, ...]
    review_item_refs: tuple[NonEmptyStr, ...]
    assessment_note: NonEmptyStr

    def as_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


__all__ = [
    "AccountBuyingUnitScope",
    "AccountCoverageProjection",
    "AccountResearchStateProjection",
    "AssessAccountCoverageInput",
    "DiscoverBuyingCommitteeInput",
    "FinalizeAccountResearchInput",
    "InspectAccountEvidenceInput",
    "ReadAccountResearchStateInput",
]
