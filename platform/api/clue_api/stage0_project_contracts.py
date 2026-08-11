"""Frozen Slice-0 contracts for Stage-0/project hardening.

This module deliberately defines contracts only.  Slice 1 registers and composes the v2 tools;
Slices 2 and 3 persist and serve the ICP-confirmation gate.  Keeping the models unregistered here
lets the contract battery reject the defective authority shapes before any runtime behavior moves.

The existing ``@1`` tools remain replayable historical contracts.  Their schemas are not mutated:
the corrected authority split is expressed by ``evaluate_stage0_readiness@2`` and
``synthesize_icps@2``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from clue_toolbelt import ToolInput, ToolOutput

__all__ = [
    "EVALUATE_STAGE0_READINESS_V2",
    "ICP_CONFIRMATION_GATE_KIND",
    "ICP_GATE_DECISIONS",
    "SYNTHESIZE_ICPS_V2",
    "DraftIcpSpecRef",
    "EvaluateStage0ReadinessV2Input",
    "IcpConfirmationGateContract",
    "Stage0GateResponseContract",
    "Stage0ReadinessV2Output",
    "SynthesizeIcpsV2Input",
    "SynthesizeIcpsV2Output",
    "canonical_subject_sha256",
]

EVALUATE_STAGE0_READINESS_V2 = "evaluate_stage0_readiness@2"
SYNTHESIZE_ICPS_V2 = "synthesize_icps@2"
ICP_CONFIRMATION_GATE_KIND = "icp_confirmation"
ICP_GATE_DECISIONS = ("approved", "rejected", "revised")

type IcpGateDecision = Literal["approved", "rejected", "revised"]
type Sha256 = str

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


def canonical_subject_sha256(snapshot: dict[str, JsonValue]) -> str:
    """Digest the exact JSON snapshot a human is asked to decide about."""

    canonical = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class _FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class EvaluateStage0ReadinessV2Input(ToolInput):
    """The model chooses when and which permitted readiness gate to evaluate.

    Workspace, project, product, client, Client-KB lineage, claims, policy and every metric are
    trusted runtime inputs.  They intentionally have no model-visible field in this contract.
    """

    gate: Literal["icp_synthesis"]


class Stage0ReadinessV2Output(ToolOutput):
    """A persisted backend-computed readiness decision, returned reference-first."""

    readiness_decision_id: str = Field(pattern=_UUID_PATTERN)
    gate: Literal["icp_synthesis"]
    verdict: Literal["ready", "not_ready"]
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    verified_claims: int = Field(ge=0)
    available_field_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]
    readiness_policy_version: int = Field(gt=0)

    @field_validator("available_field_keys")
    @classmethod
    def available_fields_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("available_field_keys must be sorted and unique")
        return values

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("reason_codes must be unique")
        return values


class SynthesizeIcpsV2Input(ToolInput):
    """No model-authored authority: the runtime supplies the exact ready Stage-0 scope."""


class DraftIcpSpecRef(_FrozenContract):
    """Durable composite reference to one persisted draft ``icp_spec`` revision."""

    workspace_id: str = Field(min_length=1)
    icp_key: str = Field(min_length=1)
    icp_version: int = Field(gt=0)
    status: Literal["draft"]


class SynthesizeIcpsV2Output(ToolOutput):
    """Reference-only synthesis result; proposal bodies stay in persisted ``icp_spec`` rows."""

    readiness_decision_id: str = Field(pattern=_UUID_PATTERN)
    icp_specs: tuple[DraftIcpSpecRef, ...] = Field(min_length=1)


class IcpConfirmationGateContract(_FrozenContract):
    """The exact durable authority a future ICP decision card may render."""

    gate_id: str = Field(pattern=_UUID_PATTERN)
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    turn_id: str = Field(pattern=_UUID_PATTERN)
    kind: Literal["icp_confirmation"]
    subject_ref: DraftIcpSpecRef
    subject_revision: int = Field(gt=0)
    expected_subject_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    subject_snapshot: dict[str, JsonValue] = Field(min_length=1)
    permitted_decisions: tuple[IcpGateDecision, ...] = Field(min_length=1)
    addressee_user_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def exact_subject_and_decisions(self) -> IcpConfirmationGateContract:
        if self.subject_ref.workspace_id != self.workspace_id:
            raise ValueError("ICP gate subject must share the gate workspace")
        if self.subject_ref.icp_version != self.subject_revision:
            raise ValueError("ICP gate subject revision must equal the persisted ICP version")
        if self.permitted_decisions != ICP_GATE_DECISIONS:
            raise ValueError("ICP gate must store the exact permitted decision vocabulary")
        if canonical_subject_sha256(self.subject_snapshot) != self.expected_subject_sha256:
            raise ValueError("ICP gate digest must match the canonical subject snapshot")
        return self


class Stage0GateResponseContract(_FrozenContract):
    """Structured human answer carried through the normal turn route.

    ICP confirmation has no spend amount.  The shared route may still carry an amount for other
    gate kinds, so the echo is optional here while the subject digest remains mandatory.
    """

    gate_id: str = Field(pattern=_UUID_PATTERN)
    decision: IcpGateDecision
    expected_subject_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    expected_estimated_cost_cents: Decimal | None = Field(default=None, ge=0)
