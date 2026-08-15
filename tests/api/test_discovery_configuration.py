"""Provider-neutral Stage-0 discovery planning and Exa compilation contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_api.discovery_configuration import (
    DEFAULT_DISCOVERY_PLANNING_POLICY,
    DiscoveryPlanningPolicy,
    derive_discovery_configuration,
    discovery_configuration_sha256,
    parse_discovery_configuration_json,
)
from clue_api.exa_websets_acquisition import compile_exa_discovery_preflight
from clue_api.stage0_project_contracts import (
    DISCOVERY_CONFIGURATION_SCHEMA_V1,
    DiscoveryConfigurationContract,
)
from clue_core import (
    ICPCreatedFrom,
    ICPSpec,
    ICPStatus,
    PhaseContext,
    ProjectPhase,
    new_project_run_id,
)


def _spec(strategy: dict[str, object]) -> ICPSpec:
    return ICPSpec(
        workspace_id="ws-discovery-contract",
        icp_key="health-practices",
        version=1,
        status=ICPStatus.ACTIVE,
        created_from=ICPCreatedFrom.SYNTHESIS,
        discovery_strategy=strategy,  # type: ignore[arg-type]
    )


def _icp_ref() -> str:
    return "icp-spec:ws-discovery-contract:health-practices:v1"


def test_firmographic_icp_derives_complete_default_ten_without_human_gate() -> None:
    result = derive_discovery_configuration(
        spec=_spec(
            {
                "mode": "discovery",
                "firmographic": {
                    "industry": "specialty healthcare",
                    "size_band": "10-200 employees",
                    "geo": ["United States", "Canada"],
                },
                "seed_account_ids": [],
                "candidate_signal_classes": ["account.strategic_moves"],
            }
        ),
        approved_icp_ref=_icp_ref(),
    )

    assert result.requires_confirmation is False
    assert result.missing_fields == ()
    assert result.configuration is not None
    assert result.configuration.requested_account_count == 10
    assert result.configuration.must_have_criteria == (
        "Geography: United States, Canada",
        "Industry: specialty healthcare",
        "Company size: 10-200 employees",
    )
    assert result.configuration.search_intent.startswith(
        "Find companies matching the approved ICP:"
    )


def test_vague_icp_names_exact_missing_scope_and_uses_versioned_safe_default() -> None:
    result = derive_discovery_configuration(
        spec=_spec({"mode": "discovery", "firmographic": {}}),
        approved_icp_ref=_icp_ref(),
    )

    assert result.configuration is None
    assert result.missing_fields == ("must_have_criteria", "search_intent")
    assert DEFAULT_DISCOVERY_PLANNING_POLICY.default_requested_account_count == 10
    assert DEFAULT_DISCOVERY_PLANNING_POLICY.maximum_requested_account_count == 50


def test_policy_refuses_a_default_above_its_maximum() -> None:
    with pytest.raises(ValidationError, match="default discovery count"):
        DiscoveryPlanningPolicy(
            default_requested_account_count=20,
            maximum_requested_account_count=10,
        )


def test_configuration_canonicalizes_scope_text_before_hashing() -> None:
    configuration = DiscoveryConfigurationContract(
        schema_version=DISCOVERY_CONFIGURATION_SCHEMA_V1,
        approved_icp_ref=_icp_ref(),
        entity_type="company",
        requested_account_count=10,
        search_intent="  Find   matching companies.  ",
        must_have_criteria=("  Specialty   healthcare  ",),
        exclusion_criteria=(" Current   customers ",),
    )

    assert configuration.search_intent == "Find matching companies."
    assert configuration.must_have_criteria == ("Specialty healthcare",)
    assert configuration.exclusion_criteria == ("Current customers",)


def test_configuration_round_trips_from_durable_json_without_loosening_scalars() -> None:
    payload = {
        "schema_version": DISCOVERY_CONFIGURATION_SCHEMA_V1,
        "approved_icp_ref": _icp_ref(),
        "entity_type": "company",
        "requested_account_count": 10,
        "search_intent": "Find matching companies.",
        "must_have_criteria": ["Specialty healthcare"],
        "exclusion_criteria": ["Current customers"],
    }

    assert parse_discovery_configuration_json(payload).must_have_criteria == (
        "Specialty healthcare",
    )
    with pytest.raises(ValidationError):
        parse_discovery_configuration_json(
            {**payload, "requested_account_count": "10"}
        )


def test_confirmed_fifty_account_scope_compiles_to_exa_without_provider_fields_in_icp() -> None:
    configuration = DiscoveryConfigurationContract(
        schema_version=DISCOVERY_CONFIGURATION_SCHEMA_V1,
        approved_icp_ref=_icp_ref(),
        entity_type="company",
        requested_account_count=50,
        search_intent="Find specialty healthcare practices matching the approved ICP.",
        must_have_criteria=("Specialty healthcare practice", "10-200 employees"),
        exclusion_criteria=("Current customers", "Hospitals"),
    )
    ctx = PhaseContext(
        project_run_id=new_project_run_id(),
        project_id="prj-discovery-contract",
        brand_id="brand-discovery-contract",
        phase=ProjectPhase.DISCOVERY,
        workspace_id="ws-discovery-contract",
        icp_key="health-practices",
        icp_version=1,
    )
    preflight = compile_exa_discovery_preflight(
        ctx=ctx,
        spec=_spec({"mode": "discovery", "firmographic": {}}),
        configuration=configuration,
    )
    search = preflight.plan.searches[0]

    assert search.requested_count == 50
    assert search.normalized_query == configuration.search_intent
    assert tuple(item.description for item in search.criteria) == (
        "Must match: Specialty healthcare practice; Must match: 10-200 employees; "
        "Must not match: Current customers; Must not match: Hospitals",
    )
    assert discovery_configuration_sha256(configuration) == (
        discovery_configuration_sha256(configuration.model_copy())
    )
