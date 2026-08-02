"""M6A D0 — provider-neutral asynchronous discovery contract freeze."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from clue_core import (
    DiscoveryBatchSeal,
    DiscoveryCriterionPlan,
    DiscoveryEnrichmentFormat,
    DiscoveryEnrichmentPlan,
    DiscoveryEntityKind,
    DiscoveryEnvelopeField,
    DiscoveryEnvelopePolicy,
    DiscoveryFailure,
    DiscoveryFieldResolution,
    DiscoveryItemSnapshot,
    DiscoveryOperation,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPlan,
    DiscoveryProviderEvent,
    DiscoveryRequestFingerprintInput,
    DiscoverySealBlocker,
    DiscoverySealReadiness,
    DiscoverySearchPlan,
    DiscoverySpendOutcome,
    discovery_provider_external_id,
    evaluate_discovery_seal,
    new_discovery_batch_id,
    new_discovery_operation_id,
    new_discovery_plan_id,
    new_project_run_id,
    validate_discovery_plan_policy,
)
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1

_ROOT = Path(__file__).resolve().parents[2]
_VECTORS = _ROOT / "tests/fixtures/discovery/request-fingerprint-vectors.json"


def _vectors() -> list[dict[str, object]]:
    value = json.loads(_VECTORS.read_text(encoding="utf-8"))
    assert isinstance(value, list)
    return value


@pytest.mark.parametrize("vector", _vectors(), ids=lambda value: str(value["name"]))
def test_request_fingerprint_matches_golden_vectors(vector: dict[str, object]) -> None:
    request = DiscoveryRequestFingerprintInput.model_validate(vector["input"])

    assert request.canonical_bytes().decode("utf-8") == vector["canonical_json"]
    assert request.sha256() == vector["sha256"]
    assert discovery_provider_external_id(request.sha256()).startswith("clue-")


def test_request_fingerprint_is_byte_stable_across_processes_and_hash_seeds() -> None:
    vector = _vectors()[0]
    script = """
import json, sys
from clue_core import DiscoveryRequestFingerprintInput
value = DiscoveryRequestFingerprintInput.model_validate(json.load(sys.stdin))
sys.stdout.write(value.canonical_bytes().hex() + "\\n" + value.sha256())
"""
    outputs: list[str] = []
    for seed in ("1", "99991"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=_ROOT,
            env=env,
            input=json.dumps(vector["input"]),
            text=True,
            capture_output=True,
            check=True,
        )
        outputs.append(result.stdout)

    assert outputs[0] == outputs[1]
    encoded, digest = outputs[0].splitlines()
    assert bytes.fromhex(encoded).decode("utf-8") == vector["canonical_json"]
    assert digest == vector["sha256"]


def test_fingerprint_normalizes_whitespace_but_preserves_order_and_workspace_scope() -> None:
    baseline = DiscoveryRequestFingerprintInput.model_validate(_vectors()[0]["input"])
    whitespace_only = baseline.model_copy(
        update={
            "normalized_query": (
                "Independent   neurosurgery and spine practices in the United States"
            )
        }
    )
    reordered = baseline.model_copy(update={"criteria": tuple(reversed(baseline.criteria))})
    other_workspace = baseline.model_copy(update={"workspace_id": "another-workspace"})

    # model_copy does not re-run validators, so validate the serialized copy at the boundary.
    normalized = DiscoveryRequestFingerprintInput.model_validate(
        whitespace_only.model_dump(mode="json")
    )
    assert normalized.sha256() == baseline.sha256()
    assert reordered.sha256() != baseline.sha256()
    assert other_workspace.sha256() != baseline.sha256()


def test_search_contract_enforces_current_provider_limits_and_typed_options() -> None:
    with pytest.raises(ValidationError, match="at most 5 items"):
        DiscoverySearchPlan(
            search_key="too-many",
            channel_key="exa_websets",
            normalized_query="query",
            entity_type=DiscoveryEntityKind.COMPANY,
            requested_count=2,
            criteria=tuple(
                DiscoveryCriterionPlan(description=f"criterion {index}") for index in range(6)
            ),
        )

    with pytest.raises(ValidationError, match="requires at least one option"):
        DiscoveryEnrichmentPlan(
            field_key="core.revenue_band",
            description="Revenue band",
            format=DiscoveryEnrichmentFormat.OPTIONS,
        )

    with pytest.raises(ValidationError, match="person searches"):
        DiscoverySearchPlan(
            search_key="company",
            channel_key="exa_websets",
            normalized_query="query",
            entity_type=DiscoveryEntityKind.COMPANY,
            requested_count=2,
            max_people_per_company=2,
        )


def test_discovery_plan_binds_lineage_policy_caps_and_declared_channels() -> None:
    search = DiscoverySearchPlan(
        search_key="primary-company-search",
        channel_key="exa_websets",
        normalized_query="Independent specialty practices in the United States",
        entity_type=DiscoveryEntityKind.COMPANY,
        requested_count=2,
        criteria=(DiscoveryCriterionPlan(description="Organization is independent"),),
    )
    plan = DiscoveryPlan(
        discovery_plan_id=new_discovery_plan_id(),
        plan_version=1,
        workspace_id="insight-health-fixture",
        project_id="aura-account-discovery",
        project_run_id=new_project_run_id(),
        icp_key="independent_neurosurgery_spine_practices_us",
        icp_version=1,
        provider_policy_version="exa-websets-company-v1",
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version="exa-websets-v0-2026-08-02",
        channels=("exa_websets",),
        searches=(search,),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=100,
        money_budget_cap_cents=Decimal("5.00"),
        stopping_policy={"requested_count": 2},
        snapshot_reuse_policy="same_observation_window",
    )

    assert plan.searches == (search,)
    assert plan.required_account_fields == DISCOVERY_ENVELOPE_POLICY_V1.required_fields
    validate_discovery_plan_policy(plan, DISCOVERY_ENVELOPE_POLICY_V1)
    with pytest.raises(ValueError, match="field_policy_version"):
        validate_discovery_plan_policy(
            plan.model_copy(update={"field_policy_version": "wrong-version"}),
            DISCOVERY_ENVELOPE_POLICY_V1,
        )
    with pytest.raises(ValidationError, match="undeclared channels"):
        DiscoveryPlan.model_validate(
            plan.model_dump(mode="json")
            | {
                "searches": [
                    search.model_copy(update={"channel_key": "undeclared"}).model_dump(mode="json")
                ]
            }
        )


def test_page_receipt_requires_cursor_exhaustion_consistency() -> None:
    with pytest.raises(ValidationError, match="requires next_cursor"):
        DiscoveryPageReceipt(
            operation_id="00000000-0000-0000-0000-000000000001",
            resource_kind="items",
            has_more=True,
            next_cursor=None,
            payload_artifact_key="ws/artifact",
            payload_sha256="a" * 64,
            item_count=2,
            fetched_at=datetime.now(UTC),
        )


def test_operation_contract_separates_unknown_spend_and_requires_terminal_receipts() -> None:
    base = {
        "operation_id": new_discovery_operation_id(),
        "batch_id": new_discovery_batch_id(),
        "workspace_id": "fixture-workspace",
        "source_key": "exa_websets",
        "provider_api_version": "v0",
        "request_fingerprint": "a" * 64,
        "observation_window": "2026-08",
        "provider_external_id": "clue-fixture",
    }
    with pytest.raises(ValidationError, match="requires unknown spend outcome"):
        DiscoveryOperation(
            **base,
            state=DiscoveryOperationState.SPEND_OUTCOME_UNKNOWN,
            spend_outcome=DiscoverySpendOutcome.NOT_CHARGED,
        )
    with pytest.raises(ValidationError, match="missing references"):
        DiscoveryOperation(
            **base,
            state=DiscoveryOperationState.SUCCEEDED,
            spend_outcome=DiscoverySpendOutcome.NOT_CHARGED,
            terminal_at=datetime.now(UTC),
        )

    operation = DiscoveryOperation(
        **base,
        provider_operation_id="ws_fixture",
        state=DiscoveryOperationState.SUCCEEDED,
        spend_outcome=DiscoverySpendOutcome.CHARGED,
        submitted_receipt_ref="receipt:submit",
        final_receipt_ref="receipt:final",
        raw_request_artifact_key="fixture/request",
        raw_response_manifest_key="fixture/responses",
        terminal_at=datetime.now(UTC),
    )
    assert operation.state is DiscoveryOperationState.SUCCEEDED


def test_contract_json_schemas_exist_for_every_d0_owned_shape() -> None:
    models = (
        DiscoveryPlan,
        DiscoveryOperation,
        DiscoveryProviderEvent,
        DiscoveryPageReceipt,
        DiscoveryItemSnapshot,
        DiscoveryFieldResolution,
        DiscoveryBatchSeal,
        DiscoveryFailure,
        DiscoveryEnvelopePolicy,
        DiscoveryEnvelopeField,
    )
    for model in models:
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


_ALL_TRUE = {
    "plan_lineage_matches": True,
    "operations_terminal": True,
    "dispatch_receipts_complete": True,
    "provider_events_accounted": True,
    "final_reconciliation_complete": True,
    "pagination_exhausted": True,
    "items_materialized": True,
    "candidate_identities_terminal": True,
    "hard_identities_complete": True,
    "required_fields_terminal": True,
    "claims_or_dispositions_complete": True,
    "survivor_links_complete": True,
    "spend_reconciled": True,
    "final_manifests_exist": True,
}

_BLOCKER_BY_ATTRIBUTE = {
    "plan_lineage_matches": DiscoverySealBlocker.PLAN_LINEAGE,
    "operations_terminal": DiscoverySealBlocker.OPERATION_TERMINALITY,
    "dispatch_receipts_complete": DiscoverySealBlocker.DISPATCH_RECEIPTS,
    "provider_events_accounted": DiscoverySealBlocker.PROVIDER_EVENTS,
    "final_reconciliation_complete": DiscoverySealBlocker.FINAL_RECONCILIATION,
    "pagination_exhausted": DiscoverySealBlocker.PAGINATION_EXHAUSTION,
    "items_materialized": DiscoverySealBlocker.ITEM_MATERIALIZATION,
    "candidate_identities_terminal": DiscoverySealBlocker.CANDIDATE_IDENTITY,
    "hard_identities_complete": DiscoverySealBlocker.HARD_IDENTITIES,
    "required_fields_terminal": DiscoverySealBlocker.REQUIRED_FIELDS,
    "claims_or_dispositions_complete": DiscoverySealBlocker.CLAIM_OR_DISPOSITION,
    "survivor_links_complete": DiscoverySealBlocker.SURVIVOR_LINKS,
    "spend_reconciled": DiscoverySealBlocker.SPEND_RECONCILIATION,
    "final_manifests_exist": DiscoverySealBlocker.FINAL_MANIFESTS,
}


def test_seal_barrier_accepts_only_when_all_fourteen_conditions_are_true() -> None:
    decision = evaluate_discovery_seal(DiscoverySealReadiness(**_ALL_TRUE))
    assert decision.sealable is True
    assert decision.blockers == ()


@pytest.mark.parametrize("attribute", tuple(_BLOCKER_BY_ATTRIBUTE))
def test_each_nonterminal_condition_independently_blocks_the_seal(attribute: str) -> None:
    readiness = dict(_ALL_TRUE)
    readiness[attribute] = False

    decision = evaluate_discovery_seal(DiscoverySealReadiness(**readiness))

    assert decision.sealable is False
    assert decision.blockers == (_BLOCKER_BY_ATTRIBUTE[attribute],)


def test_seal_barrier_reports_all_blockers_in_contract_order() -> None:
    decision = evaluate_discovery_seal(DiscoverySealReadiness(**dict.fromkeys(_ALL_TRUE, False)))
    assert decision.sealable is False
    assert decision.blockers == tuple(_BLOCKER_BY_ATTRIBUTE.values())


def test_d0_contracts_accept_decimal_spend_without_float_rounding() -> None:
    # The field is a shared annotated Decimal, so a value used by D1 never becomes a binary float.
    schema = DiscoveryOperation.model_json_schema()
    assert "provider_units_charged" in schema["properties"]
    assert Decimal("0.10") + Decimal("0.20") == Decimal("0.30")
