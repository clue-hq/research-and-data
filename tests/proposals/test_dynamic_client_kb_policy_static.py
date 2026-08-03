"""Pure contract tests for the dynamic Client-KB autonomous authority floor."""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_config.proposals import ClientFieldPromotionMode, ProposalPolicy
from clue_core import FieldDef, PassKind, ReuseScope, VolunteeredStatementId
from clue_research.claimstore import (
    ValueSchemaError,
    WorkspaceFieldDefinitionError,
    validate_value_against_schema,
    validate_workspace_field_schema,
)
from clue_research.proposals import ClientKbFieldSpec, FieldProposalPayload
from clue_research.proposals.service import (
    client_field_semantic_contract_hash,
    evaluate_safe_client_field,
)


def _payload(**detail_updates: object) -> FieldProposalPayload:
    statement_id = VolunteeredStatementId(uuid4())
    details = ClientKbFieldSpec(
        candidate_value=True,
        source_statement_id=statement_id,
        intended_use="Supplemental product context.",
        non_expiring_rationale="The client owns this stable policy statement.",
    ).model_copy(update=detail_updates)
    return FieldProposalPayload(
        field_def=FieldDef(
            field_key="client.hipaa_compliant",
            value_type="bool",
            pass_kind=PassKind.DEEP,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema={"type": "boolean"},
        description="Whether the client's product is HIPAA compliant.",
        pack="client",
        rationale="The statement is material and has no effective registered field.",
        evidence_refs=(f"volunteered_statement:{statement_id}",),
        client_kb=details,
    )


def _policy(payload: FieldProposalPayload) -> ProposalPolicy:
    return ProposalPolicy(
        client_field_mode=ClientFieldPromotionMode.SAFE_AUTO_PROMOTE,
        safe_auto_client_field_contract_hashes=frozenset(
            {client_field_semantic_contract_hash(payload)}
        ),
    )


def test_safe_auto_accepts_only_an_ordinary_supplemental_field() -> None:
    payload = _payload()
    eligible, reasons = evaluate_safe_client_field(payload, _policy(payload))

    assert eligible
    assert reasons == ()


@pytest.mark.parametrize(
    ("payload", "reason"),
    (
        (_payload(readiness_requested=True), "readiness_authority"),
        (_payload(scoring_authoritative=True), "scoring_authority"),
        (_payload(qualification_authoritative=True), "qualification_authority"),
        (_payload(outreach_authoritative=True), "outreach_authority"),
        (_payload(compliance_authoritative=True), "compliance_authority"),
        (_payload(contains_personal_data=True), "personal_data"),
        (_payload(introduces_new_source=True), "new_source"),
        (_payload(elevates_source_trust=True), "trust_elevation"),
        (
            _payload().model_copy(update={"sensitive": True}),
            "sensitive",
        ),
        (
            _payload().model_copy(
                update={
                    "field_def": _payload().field_def.model_copy(
                        update={"pass_kind": PassKind.SCORING}
                    )
                }
            ),
            "scoring_pass",
        ),
        (
            _payload().model_copy(
                update={
                    "field_def": _payload().field_def.model_copy(
                        update={"gate": "outreach-disabled"}
                    )
                }
            ),
            "use_gate",
        ),
        (
            _payload().model_copy(
                update={
                    "field_def": _payload().field_def.model_copy(
                        update={"tier_plan": ("official_web",)}
                    )
                }
            ),
            "source_plan_requires_human",
        ),
        (
            _payload().model_copy(update={"value_schema": {"type": "string"}}),
            "invalid_schema",
        ),
        (
            _payload().model_copy(update={"value_schema": {"type": "string", "maxLength": 32}}),
            "candidate_schema_mismatch",
        ),
    ),
)
def test_unsafe_or_unbounded_proposals_are_human_blocked(
    payload: FieldProposalPayload, reason: str
) -> None:
    eligible, reasons = evaluate_safe_client_field(payload, _policy(payload))

    assert not eligible
    assert reason in reasons


def test_safe_auto_cannot_trust_model_authored_safety_self_attestation() -> None:
    payload = _payload(
        intended_use="Use the founder's private home address for tailored outreach.",
        contains_personal_data=False,
        outreach_authoritative=False,
    ).model_copy(
        update={
            "field_def": _payload().field_def.model_copy(
                update={"field_key": "client.founder_home_address"}
            ),
            "description": "The founder's private home address.",
        }
    )
    policy = ProposalPolicy(client_field_mode=ClientFieldPromotionMode.SAFE_AUTO_PROMOTE)

    eligible, reasons = evaluate_safe_client_field(payload, policy)

    assert not eligible
    assert reasons == ("semantic_contract_not_policy_approved",)


def test_workspace_schema_subset_is_bounded_and_validates_values() -> None:
    schema = {
        "type": "array",
        "maxItems": 4,
        "items": {"type": "string", "maxLength": 24},
    }
    validate_workspace_field_schema(schema)
    validate_value_against_schema(["SOAP", "APSO", "H&P"], schema)

    with pytest.raises(ValueSchemaError, match="more than 4"):
        validate_value_against_schema(["a", "b", "c", "d", "e"], schema)
    with pytest.raises(WorkspaceFieldDefinitionError, match="maxItems"):
        validate_workspace_field_schema({"type": "array", "items": {"type": "boolean"}})


def test_workspace_schema_enforces_numeric_bounds_instead_of_silently_ignoring_them() -> None:
    schema = {"type": "integer", "minimum": 0, "maximum": 3650}

    validate_workspace_field_schema(schema)
    validate_value_against_schema(0, schema)
    validate_value_against_schema(3650, schema)

    with pytest.raises(ValueSchemaError, match="at least 0"):
        validate_value_against_schema(-1, schema)
    with pytest.raises(ValueSchemaError, match="at most 3650"):
        validate_value_against_schema(3651, schema)


@pytest.mark.parametrize(
    "schema",
    (
        {"type": "number", "minimum": 2, "maximum": 1},
        {"type": "number", "minimum": "zero"},
        {"type": "number", "minimum": None},
        {"type": "number", "enum": None},
        {"type": "integer", "exclusiveMinimum": 0},
        {"type": "string", "maxLength": 12, "pattern": "^[a-z]+$"},
        {"type": "string", "maxLength": None, "enum": ["bounded"]},
    ),
)
def test_workspace_schema_rejects_invalid_or_unenforced_constraints(
    schema: dict[str, object],
) -> None:
    with pytest.raises(WorkspaceFieldDefinitionError):
        validate_workspace_field_schema(schema)


def test_safe_auto_rejects_a_policy_approved_numeric_contract_with_out_of_range_value() -> None:
    payload = _payload().model_copy(
        update={
            "field_def": _payload().field_def.model_copy(
                update={"field_key": "client.retention_days", "value_type": "int"}
            ),
            "value_schema": {"type": "integer", "minimum": 0, "maximum": 3650},
            "description": "The client's configured data-retention period in days.",
            "client_kb": _payload().client_kb.model_copy(update={"candidate_value": -1}),
        }
    )

    eligible, reasons = evaluate_safe_client_field(payload, _policy(payload))

    assert not eligible
    assert "candidate_schema_mismatch" in reasons
