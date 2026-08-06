"""Provider-neutral proof contracts for buying-committee acquisition eligibility."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from clue_core.committee_acquisition import CommitteeAcquisitionOperationId
from clue_core.enums import UseClass
from clue_core.primitives import EntityId, ProjectRunId, UtcDatetime
from clue_core.research_directive import ResearchDirectivePin

CommitteeEligibilityDecisionId = NewType("CommitteeEligibilityDecisionId", UUID)
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def new_committee_eligibility_decision_id() -> CommitteeEligibilityDecisionId:
    return CommitteeEligibilityDecisionId(uuid4())


class CommitteeEligibilityCondition(StrEnum):
    SEALED_BATCH_MEMBERSHIP = "sealed_batch_membership"
    PASS_A_COMPLETE = "pass_a_complete"
    MUST_HAVE_CRITERIA = "must_have_criteria"
    HUMAN_APPROVED_TIER = "human_approved_tier"
    CONFIRMED_COMMITTEE_PLAN = "confirmed_committee_plan"
    GOVERNANCE_AND_BUDGET = "governance_and_budget"
    NO_FRESH_REUSABLE_SNAPSHOT = "no_fresh_reusable_snapshot"


class CommitteeEligibilityOutcome(StrEnum):
    ELIGIBLE = "eligible"
    REUSABLE = "reusable"
    INELIGIBLE = "ineligible"


class CommitteeExecutionAuthorization(BaseModel):
    """A2-owned confirmation/governance receipt consumed by the S2D gate.

    This receipt authorizes only professional-public, no-reveal role/person enumeration. It does
    not authorize a provider call by itself: S2D still proves sealed lineage, evidence, human tier,
    pre-spend identity and project budget against durable state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    account_id: EntityId
    research_direction_ref: NonEmptyStr
    research_directive: ResearchDirectivePin
    committee_plan_ref: NonEmptyStr
    confirmation_ref: NonEmptyStr
    confirmed_by_human: bool
    personal_data_allowed: bool
    jurisdiction_policy_ref: NonEmptyStr
    jurisdiction_allowed: bool
    allowed_use_classes: tuple[UseClass, ...]
    identity_policy_ref: NonEmptyStr
    identity_acquisition_allowed: bool
    budget_authorization_ref: NonEmptyStr
    contact_reveals_allowed: bool = False

    @model_validator(mode="after")
    def _bounded_no_reveal_authorization(self) -> CommitteeExecutionAuthorization:
        if len(self.allowed_use_classes) != len(set(self.allowed_use_classes)):
            raise ValueError("committee authorization use classes must be unique")
        if self.contact_reveals_allowed:
            raise ValueError("S2 committee acquisition authorization cannot allow contact reveals")
        if self.research_direction_ref != self.research_directive.directive_ref:
            raise ValueError("committee authorization directive ref and exact pin must agree")
        if self.account_id != self.research_directive.account_id:
            raise ValueError("committee authorization directive pin belongs to another account")
        return self

    @property
    def authorization_fingerprint(self) -> str:
        body = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()


class CommitteeEligibilityConditionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: CommitteeEligibilityCondition
    passed: bool
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _failed_condition_has_reason(self) -> CommitteeEligibilityConditionResult:
        if not self.passed and not self.reason_codes:
            raise ValueError("a failed committee eligibility condition requires a reason code")
        return self


class CommitteeEligibilityDecision(BaseModel):
    """Immutable seven-condition decision; `REUSABLE` is a zero-call success path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: CommitteeEligibilityDecisionId
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: ProjectRunId
    account_id: EntityId
    request_fingerprint: NonEmptyStr
    authorization_fingerprint: NonEmptyStr
    policy_version: NonEmptyStr
    outcome: CommitteeEligibilityOutcome
    conditions: tuple[CommitteeEligibilityConditionResult, ...]
    reusable_operation_id: CommitteeAcquisitionOperationId | None = None
    created_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _complete_and_coherent(self) -> CommitteeEligibilityDecision:
        observed = tuple(item.condition for item in self.conditions)
        expected = tuple(CommitteeEligibilityCondition)
        if len(observed) != len(set(observed)) or set(observed) != set(expected):
            raise ValueError(
                "committee eligibility decision must contain all seven conditions once"
            )
        if observed != expected:
            raise ValueError("committee eligibility conditions must use canonical order")
        failed = {item.condition for item in self.conditions if not item.passed}
        reuse_only = {CommitteeEligibilityCondition.NO_FRESH_REUSABLE_SNAPSHOT}
        if self.outcome is CommitteeEligibilityOutcome.ELIGIBLE and failed:
            raise ValueError("eligible committee decision cannot contain failed conditions")
        if self.outcome is CommitteeEligibilityOutcome.REUSABLE:
            if failed != reuse_only or self.reusable_operation_id is None:
                raise ValueError(
                    "reusable committee decision requires only the freshness condition"
                )
        elif self.reusable_operation_id is not None:
            raise ValueError("only reusable committee decisions carry an operation id")
        if self.outcome is CommitteeEligibilityOutcome.INELIGIBLE and not failed:
            raise ValueError("ineligible committee decision requires at least one failed condition")
        return self

    @property
    def decision_fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"decision_id", "created_at"})
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()


__all__ = [
    "CommitteeEligibilityCondition",
    "CommitteeEligibilityConditionResult",
    "CommitteeEligibilityDecision",
    "CommitteeEligibilityDecisionId",
    "CommitteeEligibilityOutcome",
    "CommitteeExecutionAuthorization",
    "new_committee_eligibility_decision_id",
]
