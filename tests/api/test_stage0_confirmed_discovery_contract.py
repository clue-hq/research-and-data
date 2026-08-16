"""Checkpoint-1 prevention gates for the confirmed Stage-0 discovery transition."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_api.stage0_project_contracts import (
    DISCOVERY_CONFIGURATION_SCHEMA_V1,
    PRODUCT_CONTEXT_RECEIPT_INPUT_KINDS,
    PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1,
    DiscoveryConfigurationContract,
    DiscoverySpendBoundaryContract,
    DraftIcpSpecRef,
    IcpSynthesisPresentation,
    ProductContextReceiptContract,
    ProductContextReceiptInputRef,
    StartConfirmedProjectRunV2Input,
    StartConfirmedProjectRunV2Output,
    SynthesizeIcpsV3Output,
    product_context_receipt_manifest_sha256,
)

_WORKSPACE_ID = "ws_contract"
_PROJECT_ID = "prj_contract"
_CLIENT_ENTITY_ID = "123e4567-e89b-42d3-a456-426614174000"
_PRODUCT_ID = "prd_contract"
_DECISION_ID = "123e4567-e89b-42d3-a456-426614174001"


def _receipt_inputs() -> tuple[ProductContextReceiptInputRef, ...]:
    return tuple(
        ProductContextReceiptInputRef(
            kind=kind,
            subject_ref=f"{kind}:contract",
            revision={
                "client_kb": "2",
                "selected_product": "answer:product-selection",
                "product_profile": "profile-sha-revision",
                "product_kb": "1",
                "approved_icp": "independent-practices@1",
            }[kind],
            subject_sha256=f"{index + 1:064x}",
        )
        for index, kind in enumerate(PRODUCT_CONTEXT_RECEIPT_INPUT_KINDS)
    )


def _receipt(
    inputs: tuple[ProductContextReceiptInputRef, ...] | None = None,
) -> ProductContextReceiptContract:
    exact_inputs = inputs or _receipt_inputs()
    return ProductContextReceiptContract(
        receipt_schema_version=PRODUCT_CONTEXT_RECEIPT_SCHEMA_V1,
        workspace_id=_WORKSPACE_ID,
        project_id=_PROJECT_ID,
        client_entity_id=_CLIENT_ENTITY_ID,
        product_id=_PRODUCT_ID,
        inputs=exact_inputs,
        manifest_sha256=product_context_receipt_manifest_sha256(
            workspace_id=_WORKSPACE_ID,
            project_id=_PROJECT_ID,
            client_entity_id=_CLIENT_ENTITY_ID,
            product_id=_PRODUCT_ID,
            inputs=exact_inputs,
        ),
    )


def test_receipt_binds_the_exact_existing_stage0_inputs_without_knowledge_bodies() -> None:
    receipt = _receipt()

    assert tuple(item.kind for item in receipt.inputs) == PRODUCT_CONTEXT_RECEIPT_INPUT_KINDS
    assert set(ProductContextReceiptContract.model_fields) == {
        "receipt_schema_version",
        "workspace_id",
        "project_id",
        "client_entity_id",
        "product_id",
        "inputs",
        "manifest_sha256",
    }
    assert set(ProductContextReceiptInputRef.model_fields) == {
        "kind",
        "subject_ref",
        "revision",
        "subject_sha256",
    }


def test_receipt_refuses_missing_duplicate_reordered_or_digest_drifted_inputs() -> None:
    inputs = _receipt_inputs()
    invalid_inputs = (
        inputs[:-1],
        (*inputs[:-1], inputs[0]),
        (inputs[1], inputs[0], *inputs[2:]),
    )
    for candidate in invalid_inputs:
        with pytest.raises(ValidationError):
            _receipt(candidate)

    valid = _receipt()
    with pytest.raises(ValidationError, match="digest must match"):
        ProductContextReceiptContract(
            **{
                **valid.model_dump(mode="python"),
                "manifest_sha256": "f" * 64,
            }
        )


def test_confirmed_run_v2_has_no_model_or_frontend_authored_authority_fields() -> None:
    assert StartConfirmedProjectRunV2Input.model_fields == {}
    assert StartConfirmedProjectRunV2Input.model_validate({}).model_dump() == {}

    forbidden = {
        "workspace_id",
        "project_id",
        "client_entity_id",
        "client_kb_version",
        "product_id",
        "product_kb_version",
        "product_context_version_id",
        "readiness_decision_id",
        "icp_key",
        "icp_version",
        "budget_cap_cents",
    }
    for field in forbidden:
        with pytest.raises(ValidationError):
            StartConfirmedProjectRunV2Input.model_validate({field: "model-authored"})


def test_confirmed_run_v2_does_not_expose_internal_receipt_or_readiness_ids() -> None:
    assert set(StartConfirmedProjectRunV2Output.model_fields) == {"project_run_id", "phase"}


def test_icp_presentation_is_bounded_business_copy_and_matches_its_exact_draft() -> None:
    ref = DraftIcpSpecRef(
        workspace_id=_WORKSPACE_ID,
        icp_key="independent-neurosurgery-practices",
        icp_version=2,
        status="draft",
    )
    presentation = IcpSynthesisPresentation(
        icp_key=ref.icp_key,
        icp_version=ref.icp_version,
        name="Independent neurosurgery practices",
        rationale="Prioritize practices where call handling constrains patient access.",
        target_criteria=("Industry: Neurosurgery", "Geography: United States"),
        buying_signals=("Call Volume Growth",),
        discovery_motion="discovery",
        content_truncated=False,
    )
    output = SynthesizeIcpsV3Output(
        readiness_decision_id=_DECISION_ID,
        icp_specs=(ref,),
        presentations=(presentation,),
    )

    assert output.presentations == (presentation,)
    assert set(IcpSynthesisPresentation.model_fields) == {
        "icp_key",
        "icp_version",
        "name",
        "rationale",
        "target_criteria",
        "buying_signals",
        "discovery_motion",
        "content_truncated",
    }
    with pytest.raises(ValidationError, match="match the exact ordered draft"):
        SynthesizeIcpsV3Output(
            readiness_decision_id=_DECISION_ID,
            icp_specs=(ref,),
            presentations=(presentation.model_copy(update={"icp_version": 3}),),
        )
    with pytest.raises(ValidationError, match="at most 500 characters"):
        IcpSynthesisPresentation.model_validate(
            {
                **presentation.model_dump(),
                "target_criteria": ("x" * 501,),
                "content_truncated": True,
            }
        )


def test_budget_controls_off_is_internal_record_only_allow_without_a_human_gate() -> None:
    boundary = DiscoverySpendBoundaryContract(
        evaluated_by="backend",
        readiness_decision_id=_DECISION_ID,
        budget_controls_enabled=False,
        enforcement_mode="record_only",
        execution_allowed=True,
        human_gate_required=False,
    )

    assert boundary.execution_allowed is True
    assert boundary.human_gate_required is False


@pytest.mark.parametrize(
    ("enforcement_mode", "execution_allowed", "human_gate_required"),
    [
        ("enforced", True, False),
        ("record_only", False, False),
        ("record_only", True, True),
    ],
)
def test_budget_controls_off_refuses_any_enforcement_block_or_user_interruption(
    enforcement_mode: str,
    execution_allowed: bool,
    human_gate_required: bool,
) -> None:
    with pytest.raises(ValidationError, match="open no gate"):
        DiscoverySpendBoundaryContract.model_validate(
            {
                "evaluated_by": "backend",
                "readiness_decision_id": _DECISION_ID,
                "budget_controls_enabled": False,
                "enforcement_mode": enforcement_mode,
                "execution_allowed": execution_allowed,
                "human_gate_required": human_gate_required,
            }
        )


def test_discovery_configuration_is_separate_from_context_and_budget_authority() -> None:
    configuration = DiscoveryConfigurationContract(
        schema_version=DISCOVERY_CONFIGURATION_SCHEMA_V1,
        approved_icp_ref="independent-practices@1",
        entity_type="company",
        requested_account_count=10,
        search_intent="Find independent US neurosurgery and spine practices.",
        must_have_criteria=("Independent practice", "United States"),
        exclusion_criteria=("Hospitals",),
    )

    assert configuration.requested_account_count == 10
    forbidden = {
        "product_context_version_id",
        "readiness_decision_id",
        "budget_cap_cents",
        "estimated_cost_cents",
        "max_spend_cents",
    }
    assert forbidden.isdisjoint(DiscoveryConfigurationContract.model_fields)
    assert {
        "requested_account_count",
        "search_intent",
        "must_have_criteria",
        "exclusion_criteria",
    }.isdisjoint(ProductContextReceiptContract.model_fields)

    with pytest.raises(ValidationError):
        DiscoveryConfigurationContract(
            **{
                **configuration.model_dump(mode="python"),
                "requested_account_count": 51,
            }
        )
