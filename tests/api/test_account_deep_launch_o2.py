"""M8B O2 acceptance for the exact-set account-deep launch authority."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.account_research_wiring import AccountResolverBindingAvailability
from clue_api.deep import DbAccountRunIO, build_high_tier_resolver, deep_account_run_id
from clue_api.exa_deep_acquisition import ExaDeepAcquisitionCoordinator
from clue_api.exa_deep_preparation import ExaDeepAccountResolverProvider
from clue_api.sumble_account_gaps import SumbleAccountGapCoordinator, SumbleAccountGapStarter
from clue_api.sumble_committee_inputs import DurableSumbleCommitteeInputResolver
from clue_api.toolbelt_wiring import (
    SubmitTierCheckpointInput,
    SubmitTierCheckpointTool,
    build_toolbelt,
)
from clue_api.trial.account_deep_fixture import (
    ACCOUNT_NAME,
    DEEP_FIELD_KEYS,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import BRAND_ID, PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import Settings
from clue_core import (
    DiscoveryGapOperationState,
    PhaseContext,
    ProjectPhase,
    ResearchQuestion,
    new_operation_id,
)
from clue_research.durable import (
    AccountDeepLaunchConflict,
    account_deep_launch_account_pins,
    create_account_deep_launch,
    get_account_deep_launch,
    get_account_run,
    get_project_run,
    list_account_gap_snapshots,
    preview_account_deep_launch,
)
from clue_research.icp import get_icp_version
from clue_research.resolvers.exa import ExaDeepSearchRequest, exa_field_alias
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage
from clue_toolbelt import ToolContext, invoke_tool
from clue_toolbelt.errors import PreconditionFailed
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages, _TaskReentrantConnectionFactory
from tests.api.test_fleet_wiring import _RecordingQueue
from tests.api.test_sumble_account_gaps_s1 import _SumbleHttp
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_EXA_RESPONSE = (
    Path(__file__).parents[1] / "fixtures" / "providers" / "exa" / "search" / "deep_response.json"
)


class _ExaTransport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload
        self.calls: list[object] = []

    def search(self, request: object) -> Mapping[str, Any]:
        self.calls.append(request)
        return self._payload


def test_launch_is_immutable_exactly_replayable_and_drives_the_effective_budget(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(DEEP_FIELD_KEYS[0], *DEEP_FIELD_KEYS[2:]),
            )
            pin = account_spec.research_directive
            assert pin is not None
            operation_id = new_operation_id()
            same_connection = conn_session_factory(conn)
            queue = _RecordingQueue()
            registry = build_toolbelt(
                storage=storage,
                gateway=None,
                conn_factory=same_connection,
                queue=queue,  # type: ignore[arg-type]
                account_deep_full_unit_available=True,
            )
            # The durable project machine's checkpoint transition is covered independently. Here
            # we isolate the O2 wiring contract: a successful transition to DEEP must not enqueue
            # the fleet; only the distinct exact-set launch below may do so.
            deep_run = await get_project_run(conn, fixture.project_run_id)
            assert deep_run is not None and deep_run.phase is ProjectPhase.DEEP

            class _ApprovedTierRun:
                async def submit_checkpoint(self, *_args: object, **_kwargs: object):
                    return deep_run

            submit = object.__new__(SubmitTierCheckpointTool)
            submit._run = _ApprovedTierRun()  # type: ignore[assignment]
            submit._queue = queue
            submit._project_execution_router = None
            approved = await submit.invoke(
                SubmitTierCheckpointInput(
                    project_run_id=str(fixture.project_run_id),
                    decision={"action": "approve"},
                ),
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="human",
                    principal_kind="human",
                    actor_id="human:o2-tier-approval",
                    membership_id="wsm_o2_tier_approval",
                    action_ref="turn:o2-tier-approved",
                    conn_factory=same_connection,
                    operation_id=new_operation_id(),
                ),
            )
            assert approved.references["phase"] == "deep"
            assert queue.calls == []

            # M8D R10: a *new* account-deep launch through the tool surface is quarantined —
            # exact-replay-only. The refusal is loud, enqueues nothing, and writes no launch row.
            with pytest.raises(PreconditionFailed) as quarantined:
                await invoke_tool(
                    registry,
                    "launch_account_deep",
                    {
                        "project_run_id": str(fixture.project_run_id),
                        "research_directive_id": str(pin.directive_id),
                        "account_entity_ids": [str(fixture.selected_account_id)],
                        "approved_budget_cap_cents": "300",
                        "expected_estimated_cost_cents": "300",
                    },
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="human",
                        principal_kind="human",
                        actor_id="human:o2-acceptance",
                        membership_id="wsm_o2_acceptance",
                        action_ref="turn:o2-launch-confirmed",
                        conn_factory=same_connection,
                        operation_id=operation_id,
                    ),
                    idempotency_ttl_s=60,
                )
            assert quarantined.value.reason_codes == ("entity_research_agent_not_composed",)
            assert queue.calls == []
            assert (
                await get_account_deep_launch(
                    conn,
                    fixture.project_run_id,
                    workspace_id=WORKSPACE_ID,
                )
                is None
            )

            # The durable launch substrate itself is preserved for historical exact replay; the
            # immutability/replay/budget contract below is unchanged and is exercised directly.
            created = await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                created_by="human:o2-acceptance",
                source_operation_id=operation_id,
                source_action_ref="turn:o2-launch-confirmed",
            )
            assert created.replayed is False
            stored = created.launch
            assert await account_deep_launch_account_pins(conn, stored) == (pin,)

            account_run_id = deep_account_run_id(
                fixture.project_run_id,
                fixture.selected_account_id,
            )
            await DbAccountRunIO(session_factory=conn_session_factory(conn)).ensure(
                account_run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
                research_directive=pin,
                budget_cap_cents=Decimal("300"),
            )
            account_run = await get_account_run(conn, account_run_id)
            assert account_run is not None
            assert account_run.budget_cap_cents == Decimal("300")

            # Mutable directive lifecycle state cannot invalidate an already-authorized crash
            # replay after the account run pinned the confirmed version. The receipt retains the
            # exact digest and account pin.
            await conn.execute(
                text(
                    "UPDATE account_research_directive SET status='superseded' "
                    "WHERE directive_id=:directive_id"
                ),
                {"directive_id": pin.directive_id},
            )
            replay_preview = await preview_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300.0"),
                expected_estimated_cost_cents=Decimal("3.00E+2"),
            )
            assert replay_preview.request_sha256 == stored.request_sha256
            replay = await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300.0"),
                expected_estimated_cost_cents=Decimal("3.00E+2"),
                created_by="human:o2-acceptance",
                source_operation_id=operation_id,
                source_action_ref="turn:o2-launch-confirmed",
            )
            assert replay.replayed is True
            assert replay.launch == stored
            with pytest.raises(AccountDeepLaunchConflict):
                await preview_account_deep_launch(
                    conn,
                    workspace_id=WORKSPACE_ID,
                    project_run_id=fixture.project_run_id,
                    directive_id=pin.directive_id,
                    account_entity_ids=(fixture.selected_account_id,),
                    approved_budget_cap_cents=Decimal("301"),
                    expected_estimated_cost_cents=Decimal("300"),
                )

            spec = await get_icp_version(
                conn,
                WORKSPACE_ID,
                fixture.deep_icp_key,
                fixture.deep_icp_version,
            )
            assert spec is not None
            resolved = await build_high_tier_resolver(
                spec=spec,
                session_factory=conn_session_factory(conn),
            )(
                PhaseContext(
                    project_run_id=fixture.project_run_id,
                    project_id=PROJECT_ID,
                    brand_id=BRAND_ID,
                    phase=ProjectPhase.DEEP,
                    workspace_id=WORKSPACE_ID,
                    icp_key=fixture.deep_icp_key,
                    icp_version=fixture.deep_icp_version,
                    budget_cap_cents=Decimal("1000"),
                    params={},
                )
            )
            assert len(resolved) == 1
            assert resolved[0].entity_id == fixture.selected_account_id
            assert resolved[0].research_directive == pin
            assert resolved[0].budget_cap_cents == Decimal("300")
            assert resolved[0].contact_profiling_allowed is False

            with pytest.raises(DBAPIError, match="immutable"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE account_deep_launch SET approved_budget_cap_cents=999 "
                            "WHERE id=:launch_id"
                        ),
                        {"launch_id": stored.id},
                    )

    run_async(scenario())


def test_durable_sumble_inputs_are_derived_from_the_launch_and_s1_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(DEEP_FIELD_KEYS[0], *DEEP_FIELD_KEYS[2:]),
            )
            pin = account_spec.research_directive
            assert pin is not None
            launch = await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                created_by="human:o2-sumble",
                source_operation_id=new_operation_id(),
                source_action_ref="turn:o2-sumble-launch",
            )
            account_run_id = deep_account_run_id(
                fixture.project_run_id,
                fixture.selected_account_id,
            )
            same_connection = conn_session_factory(conn)
            await DbAccountRunIO(session_factory=same_connection).ensure(
                account_run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
                research_directive=pin,
                budget_cap_cents=Decimal("300"),
            )

            http = _SumbleHttp("cascade-gastro.example")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            coordinator = SumbleAccountGapCoordinator(
                api_key=SecretStr("fixture"),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                client_factory=client_factory,
            )
            starter = SumbleAccountGapStarter(
                coordinator=coordinator,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            gap_result = await starter.start(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_id=fixture.selected_account_id,
                field_expected_value_credits={DEEP_FIELD_KEYS[0]: Decimal("5")},
                provider_credit_cap=5,
                allow_unbounded_tech=False,
            )

            resolver = DurableSumbleCommitteeInputResolver(
                settings=Settings(_env_file=None, sumble_cents_per_credit=Decimal("0.5")),
                storage=storage,
                conn_factory=same_connection,
            )
            inputs = await resolver.resolve(
                account_entity_id=fixture.selected_account_id,
                account_run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                workspace_id=WORKSPACE_ID,
                tier="high",
            )
            request = inputs.preflight.request
            assert request.research_directive == pin
            assert request.research_direction_ref == pin.directive_ref
            assert request.provider_organization_id == "1726684"
            # No advanced query is compiled: Sumble documents no multi-value operator and
            # `/v9/teams` has no job-level dimension; plan selectors gate admission locally
            # (docs/specs/M8D-R10-sumble-contract-decision.md).
            assert request.provider_filter_expression is None
            assert request.people_limit == 4
            assert request.team_limit == 1
            assert request.money_budget_cap_cents == Decimal("300")
            assert inputs.authorization.confirmed_by_human is True
            assert inputs.authorization.contact_reveals_allowed is False
            assert inputs.authorization.budget_authorization_ref == (
                f"account-deep-launch:{launch.launch.id}"
            )

            # Required-field discovery owns the first paid Organizations lookup in the normal
            # product flow. Verify committee preparation can reuse that exact sealed-batch
            # response when no later account-gap snapshot exists.
            account_gap_snapshots = await list_account_gap_snapshots(
                conn,
                workspace_id=WORKSPACE_ID,
                operation_id=gap_result.operation.operation_id,
            )
            organization_snapshot = next(
                item
                for item in account_gap_snapshots
                if item.source_key == ORGANIZATIONS_SOURCE_KEY
            )
            assert organization_snapshot.response_artifact_key is not None

            async def no_account_gap_snapshot(*_args: object, **_kwargs: object) -> None:
                return None

            async def discovery_gap_operations(
                *_args: object, **_kwargs: object
            ) -> tuple[SimpleNamespace, ...]:
                return (
                    SimpleNamespace(
                        request=SimpleNamespace(
                            project_run_id=fixture.project_run_id,
                            account_id=fixture.selected_account_id,
                            source_key=ORGANIZATIONS_SOURCE_KEY,
                        ),
                        state=DiscoveryGapOperationState.SUCCEEDED,
                        response_artifact_key=organization_snapshot.response_artifact_key,
                        updated_at=organization_snapshot.updated_at,
                        operation_id=gap_result.operation.operation_id,
                    ),
                )

            monkeypatch.setattr(
                "clue_api.sumble_committee_inputs.latest_succeeded_account_gap_snapshot",
                no_account_gap_snapshot,
            )
            monkeypatch.setattr(
                "clue_api.sumble_committee_inputs.list_discovery_gap_operations",
                discovery_gap_operations,
            )
            discovery_inputs = await resolver.resolve(
                account_entity_id=fixture.selected_account_id,
                account_run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                workspace_id=WORKSPACE_ID,
                tier="high",
            )
            assert discovery_inputs.preflight.request.provider_organization_id == "1726684"
            assert discovery_inputs.preflight.request.organization_identity_ref == (
                f"discovery-gap-operation:{gap_result.operation.operation_id}:"
                f"{ORGANIZATIONS_SOURCE_KEY}"
            )
            assert [call["url"].rsplit("/", 1)[-1] for call in http.calls] == [
                "organizations",
                "jobs",
            ]

    run_async(scenario())


def test_production_exa_preparation_acquires_once_then_replays_from_the_snapshot(
    tmp_path: Path,
) -> None:
    contact_fields = (
        "contact.current_title",
        "contact.facet.stated_interests",
    )

    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
                deep_field_keys=(*DEEP_FIELD_KEYS, *contact_fields),
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(DEEP_FIELD_KEYS[0], *DEEP_FIELD_KEYS[2:], *contact_fields),
                questions=(
                    ResearchQuestion(
                        question_id="account-workflow",
                        text="Find exact-account workflow friction.",
                        target_field_key=DEEP_FIELD_KEYS[0],
                    ),
                    ResearchQuestion(
                        question_id="contact-interests",
                        text="Find selected-contact public interests only.",
                        target_field_key=contact_fields[1],
                    ),
                ),
                contact_profiling_allowed=True,
            )
            pin = account_spec.research_directive
            assert pin is not None
            await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                created_by="human:o2-exa",
                source_operation_id=new_operation_id(),
                source_action_ref="turn:o2-exa-launch",
            )

            payload = json.loads(_EXA_RESPONSE.read_text(encoding="utf-8"))
            payload["costDollars"]["total"] = 0.07
            # The confirmed field boundary has one additional admitted fallback beyond the
            # recorded two-field E1 response. The explicit null preserves the closed output
            # contract and proves that unsupported output remains empty rather than being invented.
            # ``DEEP_FIELD_KEYS[0]`` (``account.hiring_velocity_eng``) is deliberately no longer
            # among them: comprehensive-research contract §3.1 gives that row to Sumble Jobs alone,
            # and the ``exa_deep`` source manifest stopped claiming the whole ``account`` class, so
            # Exa is no longer asked — and no longer paid — for a field it does not own.
            payload["output"]["content"][exa_field_alias(DEEP_FIELD_KEYS[4])] = None
            transport = _ExaTransport(payload)
            conn_factory = _TaskReentrantConnectionFactory(conn)
            provider = ExaDeepAccountResolverProvider(
                settings=Settings(
                    _env_file=None,
                    exa_account_deep_acquisition_enabled=True,
                ),
                storage=storage,
                pre_spend_gate=PreSpendGateImpl(conn_factory=conn_factory),
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    conn_factory=conn_factory,
                ),
                conn_factory=conn_factory,
            )

            acquired = await provider.resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_entity_id=fixture.selected_account_id,
                research_directive=pin,
            )
            assert acquired.availability is AccountResolverBindingAvailability.READY
            assert set(acquired.bindings) == {"exa_deep"}
            assert len(acquired.snapshot_refs) == 1
            assert len(acquired.audit_refs) == 1
            assert len(transport.calls) == 1
            request = transport.calls[0]
            assert isinstance(request, ExaDeepSearchRequest)
            properties = request.output_schema["properties"]
            # §3.1 ownership decides the bundle: the Sumble-owned hiring row stays out even though
            # the human confirmed it as a directive field (its question still rides along below).
            assert set(properties) == {
                exa_field_alias(field_key) for field_key in DEEP_FIELD_KEYS[2:]
            }
            assert all(exa_field_alias(field_key) not in properties for field_key in contact_fields)
            assert request.additional_queries == (
                f"{ACCOUNT_NAME} Find exact-account workflow friction.",
            )

            replayed = await provider.resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_entity_id=fixture.selected_account_id,
                research_directive=pin,
            )
            assert replayed.availability is AccountResolverBindingAvailability.READY
            assert replayed.snapshot_refs == acquired.snapshot_refs
            assert replayed.audit_refs == acquired.audit_refs
            assert len(transport.calls) == 1

    run_async(scenario())
