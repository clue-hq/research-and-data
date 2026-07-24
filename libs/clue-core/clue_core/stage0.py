"""Shared Phase-C Stage-0 identity, readiness, and reference contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from clue_core.coverage import ResearchGapRef

OnboardingInputId = NewType("OnboardingInputId", UUID)
ReconRunId = NewType("ReconRunId", UUID)
VolunteeredStatementId = NewType("VolunteeredStatementId", UUID)
ProductContextVersionId = NewType("ProductContextVersionId", UUID)
ReadinessDecisionId = NewType("ReadinessDecisionId", UUID)
ReadinessOverrideId = NewType("ReadinessOverrideId", UUID)


def new_onboarding_input_id() -> OnboardingInputId:
    return OnboardingInputId(uuid4())


def new_recon_run_id() -> ReconRunId:
    return ReconRunId(uuid4())


def new_volunteered_statement_id() -> VolunteeredStatementId:
    return VolunteeredStatementId(uuid4())


def new_product_context_version_id() -> ProductContextVersionId:
    return ProductContextVersionId(uuid4())


def new_readiness_decision_id() -> ReadinessDecisionId:
    return ReadinessDecisionId(uuid4())


def new_readiness_override_id() -> ReadinessOverrideId:
    return ReadinessOverrideId(uuid4())


class OnboardingInputKind(StrEnum):
    WEBSITE = "website"
    USER_TURN = "user_turn"
    UPLOAD = "upload"
    PASTED_TEXT = "pasted_text"
    CRM_REFERENCE = "crm_reference"


class ReadinessGate(StrEnum):
    ICP_SYNTHESIS = "icp_synthesis"
    DISCOVERY_SPEND = "discovery_spend"
    DEEP_SPEND = "deep_spend"


class ReadinessVerdict(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"
    OVERRIDDEN = "overridden"


class OnboardingInputRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    onboarding_input_id: OnboardingInputId
    artifact_key: str
    kind: OnboardingInputKind


class ProductContextRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    brand_id: str
    product_id: str
    version_id: ProductContextVersionId


class ReadinessSnapshotRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    readiness_decision_id: ReadinessDecisionId
    gate: ReadinessGate
    verdict: ReadinessVerdict
    spec_version: int
    gap_refs: tuple[ResearchGapRef, ...] = ()


__all__ = [
    "OnboardingInputId",
    "ReconRunId",
    "VolunteeredStatementId",
    "ProductContextVersionId",
    "ReadinessDecisionId",
    "ReadinessOverrideId",
    "OnboardingInputKind",
    "ReadinessGate",
    "ReadinessVerdict",
    "OnboardingInputRef",
    "ProductContextRef",
    "ReadinessSnapshotRef",
    "new_onboarding_input_id",
    "new_recon_run_id",
    "new_volunteered_statement_id",
    "new_product_context_version_id",
    "new_readiness_decision_id",
    "new_readiness_override_id",
]
