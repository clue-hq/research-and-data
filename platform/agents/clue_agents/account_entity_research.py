"""R5 account-agent semantic contracts layered over the frozen M8D R0/R4 kernel."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_agents.entity_research_tools import EntityResearchSemanticToolInput
from clue_core import Persona
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

    field_keys: tuple[NonEmptyStr, ...] = Field(
        default=(),
        max_length=0,
        description="Always empty: committee discovery enumerates people, not account fields.",
    )
    source_keys: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="Exact admitted committee-enumeration source keys only.",
    )
    questions: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="Verbatim confirmed committee question; never synthesize or paraphrase it.",
    )
    parent_operation_ref: None = Field(
        default=None,
        description="Always null: committee enumeration is not a field follow-up.",
    )
    parent_observation_ref: None = Field(
        default=None,
        description="Always null: cite account evidence in buying_unit_scope.evidence_refs.",
    )
    follow_up_reason: None = Field(
        default=None,
        description="Always null: committee enumeration is not a field follow-up.",
    )
    buying_unit_scope: AccountBuyingUnitScope = Field(
        description="Exact account/office boundary grounded by retained account evidence refs."
    )

    @model_validator(mode="after")
    def _enumeration_is_not_field_research_or_follow_up(self) -> Self:
        if self.field_keys:
            raise ValueError("committee discovery enumerates people and must not request fields")
        if any(
            value is not None
            for value in (
                self.parent_operation_ref,
                self.parent_observation_ref,
                self.follow_up_reason,
            )
        ):
            raise ValueError("committee discovery is not an additive field follow-up")
        return self


class ReadAccountResearchStateInput(_FrozenModel):
    include_result_index: bool = True


class CommitteeRoleInference(_FrozenModel):
    """One evidence-cited committee judgment authored by the responsible account agent."""

    contact_entity_id: UUID
    role: Persona
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2_000)
    evidence_claim_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)


class RecordCommitteeRoleInferencesInput(_FrozenModel):
    """A bounded batch of role judgments; omitted discovered members remain roleless."""

    inferences: tuple[CommitteeRoleInference, ...] = Field(min_length=1, max_length=64)


class InspectAccountEvidenceInput(_FrozenModel):
    result_refs: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("account evidence result references must be unique")
        return self


class AssessAccountCoverageInput(_FrozenModel):
    """Model explanation is advisory; the engine derives coverage from persisted results.

    ``result_refs`` may be **empty** (FI-2 §6.1): an account whose every admitted field was already
    known — fresh, evidence-backed, conflict-free and ``project_neutral`` — is researched by
    spending nothing, so there is no result to cite. The set is still authority-checked, just not
    by a length: the engine requires it to equal the job's persisted result set exactly (so a job
    that *did* research cannot zero-close), and it re-derives every completed field's evidence from
    durable rows regardless of what the model says here.
    """

    result_refs: tuple[NonEmptyStr, ...] = Field(max_length=100)
    assessment_note: NonEmptyStr

    @model_validator(mode="after")
    def _unique_refs(self) -> Self:
        if len(self.result_refs) != len(set(self.result_refs)):
            raise ValueError("coverage result references must be unique")
        return self


class FinalizeAccountResearchInput(_FrozenModel):
    coverage_ledger_ref: NonEmptyStr
    requested_outcome: ResearchFinalizationOutcome


class AccountCommitteePlanProjection(_FrozenModel):
    """The confirmed committee authority of the job's pinned directive, projected read-only.

    The agent may narrow this plan for one office, but it may never widen or invent a target
    function: the engine validates every committee call's ``target_functions`` against it.
    """

    directive_ref: NonEmptyStr
    functions: tuple[NonEmptyStr, ...] = ()
    levels: tuple[NonEmptyStr, ...] = ()
    teams: tuple[NonEmptyStr, ...] = ()
    personas: tuple[NonEmptyStr, ...] = ()
    candidate_cap: int = Field(ge=1)
    questions: tuple[NonEmptyStr, ...] = ()


class AccountExistingClaimProjection(_FrozenModel):
    """One admitted field's *already known* current truth, read before this job spends (FI-2 §6.1).

    Mirrors ``ContactExistingClaimProjection`` and adds ``research_scope`` — the field's species,
    which the account economics need: a ``project_neutral`` fact is the world's answer and any
    project may reuse it while it is fresh, evidence-backed and conflict-free (born-complete);
    a ``project_relative`` value is *this* project's answer, so another project's fresh claim is
    never a substitute for researching it here.
    """

    field_key: NonEmptyStr
    claim_ref: NonEmptyStr
    value: JsonValue
    source_url: str | None = None
    source_tier: int = Field(ge=1, le=4)
    evidence_span: str | None = None
    confidence: float = Field(ge=0, le=1)
    freshness_state: Literal["fresh", "stale"]
    conflict: bool
    research_scope: Literal["project_neutral", "project_relative"]

    @property
    def born_complete(self) -> bool:
        """Whether this existing claim answers the field without spending anything (FI-2 §6.1)."""

        return (
            self.research_scope == "project_neutral"
            and self.freshness_state == "fresh"
            and bool(self.evidence_span)
            and not self.conflict
        )


class AccountResearchStateProjection(_FrozenModel):
    job_id: UUID
    account_entity_id: UUID
    current_state_sha256: NonEmptyStr
    admitted_field_keys: tuple[NonEmptyStr, ...]
    admitted_source_keys: tuple[NonEmptyStr, ...]
    committee_source_keys: tuple[NonEmptyStr, ...]
    existing_claims: tuple[AccountExistingClaimProjection, ...] = ()
    result_refs: tuple[NonEmptyStr, ...]
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    committee_result_refs: tuple[NonEmptyStr, ...]
    committee_member_ids: tuple[UUID, ...]
    pending_operation_refs: tuple[NonEmptyStr, ...]
    spent_cents: str
    contact_research_request_count: int = Field(ge=0)
    committee_plan: AccountCommitteePlanProjection | None = None


class AccountCoverageProjection(_FrozenModel):
    coverage_id: UUID
    coverage_ledger_ref: NonEmptyStr
    current_state_sha256: NonEmptyStr
    completed_field_keys: tuple[NonEmptyStr, ...]
    unresolved_field_keys: tuple[NonEmptyStr, ...]
    unresolved_reasons: tuple[NonEmptyStr, ...]
    #: Why a completed field cost nothing — ``"<field_key>:existing_claim_fresh"`` per field the
    #: job never researched because a fresh, evidence-backed, conflict-free ``project_neutral``
    #: claim already answered it (FI-2 §6.1). It rides ``coverage_json`` rather than a column
    #: (there is none, and this is a ledger *explanation*, not authority — the authority is
    #: ``claim_refs``, which cites the exact claims that stood in for the spend).
    skipped_field_reasons: tuple[NonEmptyStr, ...] = ()
    committee_result_refs: tuple[NonEmptyStr, ...]
    committee_member_ids: tuple[UUID, ...]
    committee_status: Literal["complete", "partial", "needs_review"]
    committee_needs_review: int = Field(default=0, ge=0)
    claim_refs: tuple[NonEmptyStr, ...]
    evidence_refs: tuple[NonEmptyStr, ...]
    review_flags: tuple[NonEmptyStr, ...]
    review_item_refs: tuple[NonEmptyStr, ...]
    assessment_note: NonEmptyStr

    def as_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


__all__ = [
    "AccountBuyingUnitScope",
    "AccountCommitteePlanProjection",
    "AccountCoverageProjection",
    "AccountExistingClaimProjection",
    "AccountResearchStateProjection",
    "AssessAccountCoverageInput",
    "CommitteeRoleInference",
    "DiscoverBuyingCommitteeInput",
    "FinalizeAccountResearchInput",
    "InspectAccountEvidenceInput",
    "ReadAccountResearchStateInput",
    "RecordCommitteeRoleInferencesInput",
]
