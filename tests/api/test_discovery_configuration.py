"""Provider-neutral Stage-0 discovery planning and Exa compilation contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

import clue_api.stage0_project_tools as stage0_project_tools
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
from clue_api.stage0_project_scope import Stage0ProjectScope
from clue_api.stage0_project_tools import (
    OpenDiscoveryConfigurationGateInput,
    OpenDiscoveryConfigurationGateTool,
    StartConfirmedProjectRunV3Tool,
)
from clue_api.turn_action import TurnIdentity, derive_turn_action_ref
from clue_core import (
    EntityId,
    ExecutionId,
    ICPCreatedFrom,
    ICPSpec,
    ICPStatus,
    OperationId,
    PhaseContext,
    ProjectPhase,
    new_project_run_id,
)
from clue_toolbelt import ToolContext
from tests.db.conftest import run_async


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


def test_explicit_human_scope_can_override_a_complete_derived_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        turn_id = uuid4()
        execution_id = ExecutionId(uuid4())
        scope = Stage0ProjectScope(
            workspace_id="ws-discovery-contract",
            execution_id=execution_id,
            project_id="prj-discovery-contract",
            brand_id="brand-discovery-contract",
            product_id="product-discovery-contract",
            client_entity_id=EntityId(uuid4()),
            client_kb_version=2,
            turn_id=turn_id,
            product_kb_version=1,
        )
        approved_icp = stage0_project_tools._ApprovedIcp(
            icp_key="health-practices",
            version=1,
            subject_ref=_icp_ref(),
            expected_subject_sha256="0" * 64,
        )
        spec = _spec(
            {
                "mode": "discovery",
                "firmographic": {
                    "industry": "specialty healthcare",
                    "geo": ["United States"],
                },
            }
        )
        turn = TurnIdentity(
            turn_id=turn_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            thread_id="thr-discovery-contract",
            submitted_by_user_id="usr-discovery-contract",
            submitted_via_membership_id="wsm-discovery-contract",
        )

        async def resolved_scope(_conn: object, _ctx: object) -> Stage0ProjectScope:
            return scope

        async def resolved_icp(
            _conn: object,
            *,
            scope: Stage0ProjectScope,
        ) -> stage0_project_tools._ApprovedIcp:
            del scope
            return approved_icp

        async def resolved_spec(*_args: object, **_kwargs: object) -> object:
            return spec

        async def resolved_turn(*_args: object, **_kwargs: object) -> TurnIdentity:
            return turn

        @asynccontextmanager
        async def conn_factory() -> AsyncIterator[AsyncConnection]:
            yield cast(AsyncConnection, object())

        monkeypatch.setattr(stage0_project_tools, "_scope", resolved_scope)
        monkeypatch.setattr(stage0_project_tools, "_approved_icp", resolved_icp)
        monkeypatch.setattr(stage0_project_tools, "get_icp_version", resolved_spec)
        monkeypatch.setattr(stage0_project_tools, "load_turn_identity", resolved_turn)

        proposal = OpenDiscoveryConfigurationGateInput(
            requested_account_count=5,
            search_intent="Find independent neurosurgery and spine practices in WA and OR.",
            must_have_criteria=(
                "Independent multi-provider neurosurgery or spine practice",
                "Washington or Oregon",
            ),
            exclusion_criteria=(
                "Insight Health",
                "Academic, hospital-owned, or large health systems",
            ),
            source_turn_ref=derive_turn_action_ref(turn_id),
        )
        ctx = ToolContext(
            workspace_id=scope.workspace_id,
            actor="agent",
            conn_factory=conn_factory,
            operation_id=OperationId(uuid4()),
            execution_id=execution_id,
        )
        gate_tool = OpenDiscoveryConfigurationGateTool(conn_factory=conn_factory)
        _, _, configuration, missing_fields, _ = await gate_tool._resolve(
            cast(AsyncConnection, object()),
            proposal,
            ctx,
        )
        assert missing_fields == ()
        assert configuration.requested_account_count == 5

        gate_id = uuid4()

        async def approved_override(*_args: object, **_kwargs: object) -> object:
            return configuration, gate_id

        monkeypatch.setattr(
            stage0_project_tools,
            "_approved_discovery_configuration_gate",
            approved_override,
        )
        selected = await StartConfirmedProjectRunV3Tool(conn_factory=conn_factory)._configuration(
            cast(AsyncConnection, object()),
            scope=scope,
            approved_icp=approved_icp,
        )
        assert selected == (configuration, gate_id)

    run_async(scenario())


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
        parse_discovery_configuration_json({**payload, "requested_account_count": "10"})


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
