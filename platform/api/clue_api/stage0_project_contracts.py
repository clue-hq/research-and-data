"""Frozen Slice-0 contracts for Stage-0/project hardening.

This module deliberately defines contracts only.  Slice 1 registers and composes the v2 tools;
Slices 2 and 3 persist and serve the ICP-confirmation gate.  Keeping the models unregistered here
lets the contract battery reject the defective authority shapes before any runtime behavior moves.

The existing ``@1`` tools remain replayable historical contracts.  Their schemas are not mutated:
the corrected authority split is expressed by ``evaluate_stage0_readiness@2`` and
``synthesize_icps@2``.

The 2026-08-16 discovery-run amendment follows the same rule. It introduced
``start_confirmed_project_run@2`` with no model-authored lineage, an immutable receipt over the
substantive Stage-0 inputs that already exist, and the budget-controls-off boundary. The
historical ``@1`` tool remains unchanged for replay while ``@2`` is the active registered version.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from clue_toolbelt import ToolInput, ToolOutput

__all__ = [
    "DISCOVERY_CONFIGURATION_SCHEMA_V1",
    "EVALUATE_STAGE0_READINESS_V2",
    "ICP_CONFIRMATION_GATE_KIND",
    "ICP_GATE_DECISIONS",
    "PRODUCT_CONTEXT_RECEIPT_INPUT_KINDS",
    "PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1",
    "START_CONFIRMED_PROJECT_RUN_V2",
    "SYNTHESIZE_ICPS_V2",
    "DiscoveryConfigurationContract",
    "DiscoverySpendBoundaryContract",
    "DraftIcpSpecRef",
    "EvaluateStage0ReadinessV2Input",
    "IcpConfirmationGateContract",
    "ProductContextReceiptContract",
    "ProductContextReceiptInputRef",
    "StartConfirmedProjectRunV2Input",
    "StartConfirmedProjectRunV2Output",
    "Stage0GateResponseContract",
    "Stage0ReadinessV2Output",
    "SynthesizeIcpsV2Input",
    "SynthesizeIcpsV2Output",
    "TrustedStage0ProjectScopeInput",
    "canonical_subject_sha256",
    "product_context_receipt_manifest_sha256",
]

EVALUATE_STAGE0_READINESS_V2 = "evaluate_stage0_readiness@2"
SYNTHESIZE_ICPS_V2 = "synthesize_icps@2"
START_CONFIRMED_PROJECT_RUN_V2 = "start_confirmed_project_run@2"
ICP_CONFIRMATION_GATE_KIND = "icp_confirmation"
PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1: Literal["stage0-existing-inputs@1"] = "stage0-existing-inputs@1"
DISCOVERY_CONFIGURATION_SCHEMA_V1: Literal["stage0-discovery-configuration@1"] = (
    "stage0-discovery-configuration@1"
)

type IcpGateDecision = Literal["approved", "rejected", "revised"]
type ProductContextReceiptInputKind = Literal[
    "client_kb",
    "selected_product",
    "product_profile",
    "product_kb",
    "approved_icp",
]
type Sha256 = str

ICP_GATE_DECISIONS: tuple[IcpGateDecision, ...] = ("approved", "rejected", "revised")
PRODUCT_CONTEXT_RECEIPT_INPUT_KINDS: tuple[ProductContextReceiptInputKind, ...] = (
    "client_kb",
    "selected_product",
    "product_profile",
    "product_kb",
    "approved_icp",
)

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


class TrustedStage0ProjectScopeInput(ToolInput):
    """Marker for tools whose compatibility pins come from the execution-bound project.

    The marker is deliberately on the input contract rather than a list of tool names in the pin
    provider.  A new Stage-0 capability therefore opts into the same trusted scope boundary once;
    the provider then derives the exact project/product/Client-KB pins from the live descriptor's
    declared ``pin_requirements``.
    """

    requires_trusted_stage0_project_scope: ClassVar[bool] = True


class ProductContextReceiptInputRef(_FrozenContract):
    """One exact existing Stage-0 input, represented by reference rather than copied knowledge.

    ``revision`` uses the resource's native durable revision coordinate.  For example, Client-KB
    and Product-KB use their positive version while a selected-product decision may use its
    immutable answer receipt.  ``subject_sha256`` binds the canonical bytes at that coordinate.
    """

    kind: ProductContextReceiptInputKind
    subject_ref: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    subject_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")


def product_context_receipt_manifest_sha256(
    *,
    workspace_id: str,
    project_id: str,
    client_entity_id: str,
    product_id: str,
    inputs: tuple[ProductContextReceiptInputRef, ...],
) -> str:
    """Digest one canonical receipt payload; the backend is the only intended caller."""

    payload = {
        "receipt_schema_version": PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "client_entity_id": client_entity_id,
        "product_id": product_id,
        "inputs": [item.model_dump(mode="json") for item in inputs],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ProductContextReceiptContract(_FrozenContract):
    """Immutable replay/audit receipt over substantive context that already exists.

    This contract never carries prose, generated claims, discovery configuration, or a model-
    supplied identifier.  The backend derives the references and digest and inserts-or-reuses the
    matching durable row.
    """

    receipt_schema_version: Literal["stage0-existing-inputs@1"]
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    client_entity_id: str = Field(pattern=_UUID_PATTERN)
    product_id: str = Field(min_length=1)
    inputs: tuple[ProductContextReceiptInputRef, ...] = Field(min_length=5, max_length=5)
    manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_existing_inputs_and_digest(self) -> ProductContextReceiptContract:
        if tuple(item.kind for item in self.inputs) != PRODUCT_CONTEXT_RECEIPT_INPUT_KINDS:
            raise ValueError("product-context receipt must contain each exact Stage-0 input once")
        expected = product_context_receipt_manifest_sha256(
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            client_entity_id=self.client_entity_id,
            product_id=self.product_id,
            inputs=self.inputs,
        )
        if self.manifest_sha256 != expected:
            raise ValueError("product-context receipt digest must match its canonical inputs")
        return self


class DiscoverySpendBoundaryContract(_FrozenContract):
    """Internal discovery boundary; disabled budget controls can neither block nor interrupt."""

    evaluated_by: Literal["backend"]
    readiness_decision_id: str = Field(pattern=_UUID_PATTERN)
    budget_controls_enabled: bool
    enforcement_mode: Literal["enforced", "record_only"]
    execution_allowed: bool
    human_gate_required: bool

    @model_validator(mode="after")
    def disabled_budget_controls_are_non_interactive(
        self,
    ) -> DiscoverySpendBoundaryContract:
        if not self.budget_controls_enabled and (
            self.enforcement_mode != "record_only"
            or not self.execution_allowed
            or self.human_gate_required
        ):
            raise ValueError(
                "disabled budget controls must record internally, allow execution, and open no gate"
            )
        if self.budget_controls_enabled and self.enforcement_mode != "enforced":
            raise ValueError("enabled budget controls must use the enforced boundary")
        return self


class DiscoveryConfigurationContract(_FrozenContract):
    """Provider-neutral discovery scope, intentionally separate from context and spend authority."""

    schema_version: Literal["stage0-discovery-configuration@1"]
    approved_icp_ref: str = Field(min_length=1)
    entity_type: Literal["company"]
    requested_account_count: int = Field(gt=0)
    search_intent: str = Field(min_length=1, max_length=4_000)
    must_have_criteria: tuple[str, ...] = Field(min_length=1)
    exclusion_criteria: tuple[str, ...] = ()

    @field_validator("must_have_criteria", "exclusion_criteria")
    @classmethod
    def criteria_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 50:
            raise ValueError("discovery criteria are limited to 50 entries")
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("discovery criteria must be non-blank and at most 500 characters")
        if len(set(values)) != len(values):
            raise ValueError("discovery criteria must be unique")
        return values


class StartConfirmedProjectRunV2Input(TrustedStage0ProjectScopeInput):
    """No model-authored lineage, receipt id, readiness id, ICP id, or budget value.

    The execution-bound project and immutable turn scope identify the confirmed Stage-0 inputs.
    The backend derives/reuses the receipt and evaluates the discovery boundary.
    """


class StartConfirmedProjectRunV2Output(ToolOutput):
    """Minimal result of the backend-owned confirmed-run transition.

    Receipt and readiness identifiers remain on the durable ``project_run`` lineage.  They are
    intentionally absent here: neither the model nor the frontend needs an opaque internal id in
    order to continue the project.
    """

    project_run_id: str = Field(pattern=_UUID_PATTERN)
    phase: Literal["discovery"]


class EvaluateStage0ReadinessV2Input(TrustedStage0ProjectScopeInput):
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


class SynthesizeIcpsV2Input(TrustedStage0ProjectScopeInput):
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
    revision_request: str | None = Field(default=None, min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def revision_has_one_explicit_request(self) -> Stage0GateResponseContract:
        if self.decision == "revised":
            if self.revision_request is None or not self.revision_request.strip():
                raise ValueError("an ICP revision requires a non-blank revision_request")
        elif self.revision_request is not None:
            raise ValueError("revision_request is only valid for a revised decision")
        return self
