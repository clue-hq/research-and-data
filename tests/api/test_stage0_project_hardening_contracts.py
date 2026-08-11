"""Slice 0 — executable contract freeze for Stage-0/project hardening."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from clue_api.stage0_project_contracts import (
    ICP_GATE_DECISIONS,
    DraftIcpSpecRef,
    EvaluateStage0ReadinessV2Input,
    IcpConfirmationGateContract,
    Stage0GateResponseContract,
    Stage0ReadinessV2Output,
    SynthesizeIcpsV2Input,
    SynthesizeIcpsV2Output,
    canonical_subject_sha256,
)

_DECISION_ID = "00000000-0000-4000-8000-000000000701"
_GATE_ID = "00000000-0000-4000-8000-000000000702"
_TURN_ID = "00000000-0000-4000-8000-000000000703"


def _schema_sha256(model: type[BaseModel]) -> str:
    canonical = json.dumps(
        model.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _subject_snapshot() -> dict[str, Any]:
    return {
        "icp_key": "independent-neurosurgery-practices",
        "label": "Independent neurosurgery practices",
        "status": "draft",
        "version": 1,
    }


def _gate_payload() -> dict[str, Any]:
    snapshot = _subject_snapshot()
    return {
        "gate_id": _GATE_ID,
        "workspace_id": "ws-insight-health",
        "project_id": "project-aura-ai",
        "thread_id": "thread-stage0",
        "turn_id": _TURN_ID,
        "kind": "icp_confirmation",
        "subject_ref": {
            "workspace_id": "ws-insight-health",
            "icp_key": "independent-neurosurgery-practices",
            "icp_version": 1,
            "status": "draft",
        },
        "subject_revision": 1,
        "expected_subject_sha256": canonical_subject_sha256(snapshot),
        "subject_snapshot": snapshot,
        "permitted_decisions": ICP_GATE_DECISIONS,
        "addressee_user_id": "user-insight-health",
    }


def test_readiness_v2_accepts_only_the_agent_owned_gate_choice() -> None:
    value = EvaluateStage0ReadinessV2Input(gate="icp_synthesis")

    assert value.model_dump(mode="json") == {"gate": "icp_synthesis"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EvaluateStage0ReadinessV2Input.model_validate(
            {
                "gate": "icp_synthesis",
                "metrics": {"coverage_ratio": 1.0},
                "workspace_id": "model-authored-workspace",
            }
        )


def test_readiness_v2_returns_backend_metrics_and_never_calls_policy_an_icp_version() -> None:
    value = Stage0ReadinessV2Output(
        readiness_decision_id=_DECISION_ID,
        gate="icp_synthesis",
        verdict="ready",
        coverage_ratio=0.78,
        verified_claims=7,
        available_field_keys=(
            "client.differentiator",
            "client.product",
            "client.value_prop",
        ),
        reason_codes=(),
        readiness_policy_version=1,
    )

    assert value.verified_claims == 7
    assert "readiness_policy_version" in value.model_dump(mode="json")
    assert Stage0ReadinessV2Output.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Stage0ReadinessV2Output.model_validate({**value.model_dump(mode="json"), "spec_version": 1})


def test_synthesis_v2_has_no_model_authored_scope_and_returns_durable_draft_refs() -> None:
    assert SynthesizeIcpsV2Input().model_dump() == {}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SynthesizeIcpsV2Input.model_validate({"client_entity_id": "model-authored-client"})

    result = SynthesizeIcpsV2Output(
        readiness_decision_id=_DECISION_ID,
        icp_specs=(
            DraftIcpSpecRef(
                workspace_id="ws-insight-health",
                icp_key="independent-neurosurgery-practices",
                icp_version=1,
                status="draft",
            ),
        ),
    )
    assert result.icp_specs[0].status == "draft"
    assert SynthesizeIcpsV2Output.model_validate_json(result.model_dump_json()) == result


def test_icp_gate_requires_a_durable_exact_subject_digest_and_stored_decisions() -> None:
    gate = IcpConfirmationGateContract.model_validate(_gate_payload())

    assert gate.subject_ref.icp_version == gate.subject_revision
    assert gate.permitted_decisions == ICP_GATE_DECISIONS

    malformed = _gate_payload()
    malformed["subject_ref"] = "human_only"
    with pytest.raises(ValidationError):
        IcpConfirmationGateContract.model_validate(malformed)

    stale = _gate_payload()
    stale["expected_subject_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="digest must match"):
        IcpConfirmationGateContract.model_validate(stale)

    unsupported = _gate_payload()
    unsupported["permitted_decisions"] = ("approved",)
    with pytest.raises(ValidationError, match="exact permitted decision"):
        IcpConfirmationGateContract.model_validate(unsupported)


@pytest.mark.parametrize("decision", ICP_GATE_DECISIONS)
def test_each_icp_decision_uses_the_structured_digest_bound_answer(decision: str) -> None:
    payload = _gate_payload()
    response = Stage0GateResponseContract(
        gate_id=_GATE_ID,
        decision=decision,  # type: ignore[arg-type]
        expected_subject_sha256=payload["expected_subject_sha256"],
        revision_request=("Focus on independent practices." if decision == "revised" else None),
    )

    assert response.expected_estimated_cost_cents is None


def test_icp_revision_requires_the_requested_changes_and_only_revision_accepts_them() -> None:
    digest = _gate_payload()["expected_subject_sha256"]
    with pytest.raises(ValidationError, match="revision_request"):
        Stage0GateResponseContract(
            gate_id=_GATE_ID,
            decision="revised",
            expected_subject_sha256=digest,
        )
    with pytest.raises(ValidationError, match="only valid"):
        Stage0GateResponseContract(
            gate_id=_GATE_ID,
            decision="approved",
            expected_subject_sha256=digest,
            revision_request="Change it",
        )


@pytest.mark.parametrize(
    ("model", "expected_sha256"),
    (
        (
            EvaluateStage0ReadinessV2Input,
            "5946e16aa77e32627adb4c965430bec3685d40d914d723f6cfd6f93339b61fac",
        ),
        (
            Stage0ReadinessV2Output,
            "ea352b21dea5627ce2a4c67b42a0e0df0450f0f0d3aead0262437142f671a195",
        ),
        (
            SynthesizeIcpsV2Input,
            "9dd9f7d7dc66b9b4c4c19aed3d4ff0c5f903b5a082e50dbbe5940925c10f66a3",
        ),
        (
            DraftIcpSpecRef,
            "d528d336ea14c658ec06522516f59cdeee22cd78e5764cad237812c6bbee39f6",
        ),
        (
            SynthesizeIcpsV2Output,
            "0b2b661c6128ee50b0e2573109107fa1a2ccf1c34fb53d53920e2671e74085d0",
        ),
        (
            IcpConfirmationGateContract,
            "236547fb15a9b2e7cde586704abde1e19169b66ffd367e28db034e1938fb9d87",
        ),
        (
            Stage0GateResponseContract,
            "53fa90216942fba805e345fa8cc73e282630fbc797f6e9992383613db53774f3",
        ),
    ),
)
def test_stage0_hardening_contract_schema_is_frozen(
    model: type[BaseModel], expected_sha256: str
) -> None:
    assert _schema_sha256(model) == expected_sha256
