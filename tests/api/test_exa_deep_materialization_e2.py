"""M8B E2 acceptance: immutable Exa snapshots through both account-research paths."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentExecutionStatus,
    AgentTurnOutcome,
    ArtifactRef,
    FinalizeStatus,
)
from clue_api.account_research_wiring import GovernedAccountProfiler
from clue_api.agent_runtime_wiring import CompletionGuard, ModelFinalizeRequest
from clue_api.coverage_tools import (
    ResearchAccountGapsV2Input,
    build_research_account_gaps_v2_tool,
)
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionOutcome,
    compile_exa_deep_acquisition_plan,
)
from clue_api.exa_deep_materialization import (
    ExaDeepSnapshotError,
    ExaDeepSnapshotResolverProvider,
    build_exa_deep_snapshot_resolver,
)
from clue_api.trial.account_deep_fixture import (
    DEEP_FIELD_KEYS,
    PROJECT_RUN_ID,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import (
    BRAND_ID,
    PRODUCT_ID,
    PROJECT_ID,
    WORKSPACE_ID,
)
from clue_api.verification import build_verification_phase_handler
from clue_core import (
    Completion,
    EmbeddingResult,
    EntityId,
    Message,
    PhaseContext,
    ProjectPhase,
    VerificationStatus,
    new_execution_id,
    new_operation_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, current_value
from clue_research.durable import AccountSpec, BudgetEngine, DbBudgetStore, ResearchPlan
from clue_research.icp import get_icp_version
from clue_research.identity import get_account
from clue_research.profiling import profile_account
from clue_research.resolvers.exa import exa_field_alias
from clue_research.resolvers.exa.deep_contract import ExaDeepFieldSpec
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage
from clue_toolbelt import ToolContext
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import (
    _fixture_config_store,
    _pages,
    _TaskReentrantConnectionFactory,
)
from tests.api.test_exa_deep_acquisition_e1 import _NoReplayTransport, _payload, _Transport
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_OPERATIONAL = DEEP_FIELD_KEYS[2]
_STRATEGIC = DEEP_FIELD_KEYS[3]
_CULTURE = DEEP_FIELD_KEYS[4]
_E2_FIELDS = (_OPERATIONAL, _STRATEGIC, _CULTURE)


class _CoverageGateway:
    def __init__(self, fields: Sequence[str]) -> None:
        self._fields = tuple(fields)
        self.calls = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        del messages, opts
        self.calls += 1
        assessments = [
            {
                "field_key": field,
                "meaningful_gap_remaining": True,
                "recommendation": "continue",
                "warning_codes": ["insufficient_evidence"],
                "rationale": "The engine must reach a terminal evidence outcome.",
            }
            for field in self._fields
        ]
        return Completion(
            model=model,
            text=json.dumps({"assessments": assessments, "sufficient_for_goal": False}),
            cost_cents=Decimal(0),
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        del model, inputs
        raise NotImplementedError


class _VerificationGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        del opts
        prompt = messages[-1].content
        self.calls.append(prompt)
        supported = _OPERATIONAL in prompt
        payload = (
            {
                "verdict": "supported",
                "score": 0.94,
                "rationale": "The cited span directly supports the field value.",
            }
            if supported
            else {
                "verdict": "contradicted",
                "score": 0.02,
                "rationale": "The cited span does not support the strategic conclusion.",
            }
        )
        return Completion(
            model=model,
            text=json.dumps(payload),
            cost_cents=Decimal(0),
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        del model, inputs
        raise NotImplementedError


@asynccontextmanager
async def _no_lock(_entity_id: EntityId) -> AsyncIterator[None]:
    yield


class _ToolDrivingTurnRunner:
    def __init__(self, *, tool: object, conn_factory: Any, fields: Sequence[str]) -> None:
        self._tool = tool
        self._conn_factory = conn_factory
        self._fields = tuple(fields)

    async def run(
        self,
        *,
        workspace_id: str,
        project_run_id: Any,
        account_entity_id: EntityId,
        account_run_id: Any,
        tier: str,
        plan: ResearchPlan,
        budget_cap_cents: Decimal | None,
        completion_guard: CompletionGuard,
    ) -> AgentTurnOutcome:
        del plan, budget_cap_cents
        last: Mapping[str, object] | None = None
        for round_number in range(1, 5):
            inputs = ResearchAccountGapsV2Input(
                project_run_id=str(project_run_id),
                account_entity_id=str(account_entity_id),
                tier=tier,
                round=round_number,
                gap_fields=list(self._fields),
            )
            ctx = ToolContext(
                workspace_id=workspace_id,
                actor="agent",
                conn_factory=self._conn_factory,
                operation_id=new_operation_id(),
            )
            failures = await self._tool.preconditions(inputs, ctx)  # type: ignore[attr-defined]
            assert failures == ()
            result = await self._tool.invoke(inputs, ctx)  # type: ignore[attr-defined]
            last = result.references
        assert last is not None and last["terminal"] is True
        await completion_guard(
            ModelFinalizeRequest(
                status=FinalizeStatus.COMPLETED,
                user_message="Account research reached engine-terminal coverage.",
            )
        )
        return AgentTurnOutcome(
            turn_id=uuid4(),
            execution_id=new_execution_id(),
            status=AgentExecutionStatus.COMPLETED,
            finalization_ref=ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=f"agent-finalization/{account_run_id}",
                sha256="a" * 64,
                media_type="application/json",
                byte_count=1,
            ),
        )


def test_e2_snapshot_materializes_through_mechanical_and_agent_paths_then_verifies(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
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
                field_keys=_E2_FIELDS,
            )
            directive = account_spec.research_directive
            assert directive is not None
            account = await get_account(conn, fixture.selected_account_id)
            assert account is not None
            fields = tuple(
                ExaDeepFieldSpec(field_key=field, value_schema={"type": "string"})
                for field in _E2_FIELDS
            )
            bundle = compile_exa_deep_acquisition_plan(
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                project_run_id=PROJECT_RUN_ID,
                account=account,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                research_directive=directive,
                fields=fields,
                research_intent="grounded referral workflow and strategic change evidence",
                additional_queries=("fax and referral workflow",),
                observation_window="window:exa-e2-acceptance",
                freshness_policy_ref="freshness:exa-e2-test-v1",
                freshness_seconds=3600,
                cost_cents_reserved_per_bundle=Decimal(20),
            ).bundles[0]
            payload = _payload()
            payload["costDollars"]["total"] = 0.07
            payload["output"]["content"][exa_field_alias(_CULTURE)] = None

            conn_factory = _TaskReentrantConnectionFactory(conn)
            transport = _Transport(payload)
            acquired = await ExaDeepAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=conn_factory,
            ).acquire(bundle)
            assert acquired.outcome is ExaDeepAcquisitionOutcome.READY
            assert acquired.snapshot is not None
            assert transport.calls == 1
            spent_after_acquisition = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": PROJECT_RUN_ID},
                    )
                ).scalar_one()
            )

            provider = ExaDeepSnapshotResolverProvider(
                storage=storage,
                conn_factory=conn_factory,
            )
            bindings = await provider.resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=PROJECT_RUN_ID,
                account_entity_id=fixture.selected_account_id,
                research_directive=directive,
            )
            deep_icp = await get_icp_version(
                conn,
                WORKSPACE_ID,
                fixture.deep_icp_key,
                fixture.deep_icp_version,
            )
            assert deep_icp is not None

            mechanical = await profile_account(
                account_entity_id=fixture.selected_account_id,
                spec=deep_icp.model_copy(update={"field_keys": (_STRATEGIC,)}),
                tier="high",
                run_id=new_run_id(),
                project_run_id=PROJECT_RUN_ID,
                workspace_id=WORKSPACE_ID,
                # The provider operation is already settled. Materialization must remain
                # available even when no fresh account-level spend headroom remains.
                budget_cap_cents=Decimal(0),
                session_factory=conn_factory,
                pre_spend_gate=PreSpendGateImpl(conn_factory=conn_factory),
                config_store=_fixture_config_store(),
                resolver_bindings=bindings,
            )
            assert len(mechanical.claim_refs) == 1
            assert mechanical.cost_cents == 0

            coverage_gateway = _CoverageGateway((_OPERATIONAL, _CULTURE))
            tool = build_research_account_gaps_v2_tool(
                gateway=coverage_gateway,
                conn_factory=conn_factory,
                budget=BudgetEngine(store=DbBudgetStore(conn_factory=conn_factory)),
                pre_spend_gate=PreSpendGateImpl(conn_factory=conn_factory),
                lock_factory=_no_lock,
            )
            agent_run_id = new_run_id()
            governed = GovernedAccountProfiler(
                turns=_ToolDrivingTurnRunner(
                    tool=tool,
                    conn_factory=conn_factory,
                    fields=(_OPERATIONAL, _CULTURE),
                ),
                resolver_provider=provider,
                conn_factory=conn_factory,
            )
            agent_result = await governed(
                account_entity_id=fixture.selected_account_id,
                spec=deep_icp.model_copy(update={"field_keys": (_OPERATIONAL, _CULTURE)}),
                tier="high",
                run_id=agent_run_id,
                project_run_id=PROJECT_RUN_ID,
                workspace_id=WORKSPACE_ID,
                budget_cap_cents=Decimal(0),
                research_directive=directive,
            )
            assert agent_result.coverage_terminal
            assert len(agent_result.claim_refs) == 1
            dispositions = {
                field: disposition
                for aspect in agent_result.aspects
                for field, disposition in aspect.dispositions.items()
            }
            assert dispositions == {
                _OPERATIONAL: "filled",
                _CULTURE: "unfilled_terminal",
            }
            assert coverage_gateway.calls == 4

            verification_gateway = _VerificationGateway()

            async def account_resolver(_ctx: PhaseContext) -> Sequence[AccountSpec]:
                return (
                    AccountSpec(
                        entity_id=fixture.selected_account_id,
                        tier="high",
                        workspace_id=WORKSPACE_ID,
                        field_keys=_E2_FIELDS,
                        research_directive=directive,
                    ),
                )

            verification = build_verification_phase_handler(
                gateway=verification_gateway,
                account_resolver=account_resolver,
                session_factory=conn_factory,
                govern_contacts=False,
            )
            verified = await verification.run(
                PhaseContext(
                    project_run_id=PROJECT_RUN_ID,
                    project_id=PROJECT_ID,
                    brand_id=BRAND_ID,
                    phase=ProjectPhase.VERIFICATION,
                    workspace_id=WORKSPACE_ID,
                    icp_key=fixture.deep_icp_key,
                    icp_version=fixture.deep_icp_version,
                )
            )
            assert verified.accounts_processed == 1
            assert verified.payload["accounts_failed"] == 0

            operational = await claims_for(
                conn,
                fixture.selected_account_id,
                _OPERATIONAL,
                scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
            )
            strategic = await claims_for(
                conn,
                fixture.selected_account_id,
                _STRATEGIC,
                scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
            )
            culture = await claims_for(
                conn,
                fixture.selected_account_id,
                _CULTURE,
                scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
            )
            assert len(operational) == len(strategic) == 1
            assert culture == []
            assert operational[0].verification_status is VerificationStatus.VERIFIED
            assert strategic[0].verification_status is VerificationStatus.REJECTED
            assert (
                await current_value(
                    conn,
                    fixture.selected_account_id,
                    _OPERATIONAL,
                    scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
                )
                is not None
            )
            assert (
                await current_value(
                    conn,
                    fixture.selected_account_id,
                    _STRATEGIC,
                    scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
                )
                is None
            )
            for claim in (*operational, *strategic):
                assert claim.artifact_key is not None
                assert claim.source_operation_ref == str(acquired.snapshot.operation_id)
                assert claim.source_snapshot_ref == str(acquired.snapshot.snapshot_id)
                assert claim.source_request_ref == acquired.snapshot.provider_request_id
                assert claim.cost_cents == 0

            gate_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, decision::text, effective_source_plan "
                            "FROM gate_decision WHERE run_id IN (:mechanical, :agent)"
                        ),
                        {
                            "mechanical": mechanical.run_id,
                            "agent": agent_run_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert gate_rows
            assert all(row["source_key"] != "parallel_task" for row in gate_rows)
            exa_rows = [row for row in gate_rows if row["source_key"] == "exa_deep"]
            assert len(exa_rows) == 3
            assert all(row["decision"] == "pass" for row in exa_rows)
            assert all(
                "parallel_task" not in json.dumps(row["effective_source_plan"]) for row in gate_rows
            )

            spent_after_materialization = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": PROJECT_RUN_ID},
                    )
                ).scalar_one()
            )
            assert spent_after_materialization == spent_after_acquisition

            no_replay_transport = _NoReplayTransport()
            replay = await ExaDeepAcquisitionCoordinator(
                transport=no_replay_transport,
                storage=storage,
                conn_factory=conn_factory,
            ).acquire(bundle)
            assert replay.outcome is ExaDeepAcquisitionOutcome.REPLAYED
            assert no_replay_transport.calls == 0
            replay_bindings = await provider.resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=PROJECT_RUN_ID,
                account_entity_id=fixture.selected_account_id,
                research_directive=directive,
            )
            assert replay_bindings["exa_deep"].resolve(
                account.as_entity(),
                await _field(conn, _OPERATIONAL),
            )

    run_async(scenario())


async def _field(conn: AsyncConnection, field_key: str) -> Any:
    from clue_research.claimstore import get_field

    field = await get_field(conn, field_key)
    assert field is not None
    return field


def test_e2_materializer_fails_closed_on_cross_account_or_missing_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            account = await get_account(conn, fixture.selected_account_id)
            assert account is not None
            conn_factory = conn_session_factory(conn)
            with pytest.raises(ExaDeepSnapshotError, match="at least one ready snapshot"):
                await build_exa_deep_snapshot_resolver(
                    account=account,
                    snapshots=(),
                    allowed_field_keys=_E2_FIELDS,
                    storage=storage,
                    conn_factory=conn_factory,
                )

    run_async(scenario())


def test_e2_ignores_expired_snapshots_and_newer_null_shadows_older_value(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
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
                field_keys=_E2_FIELDS,
            )
            directive = account_spec.research_directive
            assert directive is not None
            account = await get_account(conn, fixture.selected_account_id)
            assert account is not None
            conn_factory = _TaskReentrantConnectionFactory(conn)
            field_spec = (
                ExaDeepFieldSpec(field_key=_OPERATIONAL, value_schema={"type": "string"}),
            )

            def bundle(
                window: str,
                *,
                freshness_seconds: int = 3600,
                research_intent: str = "account-locked operational workflow evidence",
            ) -> Any:
                return compile_exa_deep_acquisition_plan(
                    workspace_id=WORKSPACE_ID,
                    project_id=PROJECT_ID,
                    project_run_id=PROJECT_RUN_ID,
                    account=account,
                    icp_key=fixture.deep_icp_key,
                    icp_version=fixture.deep_icp_version,
                    research_directive=directive,
                    fields=field_spec,
                    research_intent=research_intent,
                    additional_queries=(),
                    observation_window=window,
                    freshness_policy_ref="freshness:exa-e2-refresh-test-v1",
                    freshness_seconds=freshness_seconds,
                    cost_cents_reserved_per_bundle=Decimal(20),
                ).bundles[0]

            def operational_payload(*, request_id: str, value: object) -> dict[str, Any]:
                payload = _payload()
                alias = exa_field_alias(_OPERATIONAL)
                payload["requestId"] = request_id
                payload["output"]["content"] = {alias: value}
                payload["output"]["grounding"] = [
                    item
                    for item in payload["output"]["grounding"]
                    if item["field"].removeprefix("content.") == alias
                ]
                payload["costDollars"]["total"] = 0.01
                return payload

            stale = await ExaDeepAcquisitionCoordinator(
                transport=_Transport(
                    operational_payload(
                        request_id="exa-deep-expired-request",
                        value=(
                            "Referral-document indexing and patient-call routing create recurring "
                            "administrative work."
                        ),
                    )
                ),
                storage=storage,
                conn_factory=conn_factory,
                clock=lambda: datetime(2020, 1, 1, tzinfo=UTC),
            ).acquire(bundle("window:exa-e2-expired", freshness_seconds=1))
            assert stale.snapshot is not None
            provider = ExaDeepSnapshotResolverProvider(
                storage=storage,
                conn_factory=conn_factory,
            )
            with pytest.raises(ExaDeepSnapshotError, match="at least one ready snapshot"):
                await provider.resolver_bindings(
                    workspace_id=WORKSPACE_ID,
                    project_run_id=PROJECT_RUN_ID,
                    account_entity_id=fixture.selected_account_id,
                    research_directive=directive,
                )

            older = await ExaDeepAcquisitionCoordinator(
                transport=_Transport(
                    operational_payload(
                        request_id="exa-deep-older-request",
                        value=(
                            "Referral-document indexing and patient-call routing create recurring "
                            "administrative work."
                        ),
                    )
                ),
                storage=storage,
                conn_factory=conn_factory,
            ).acquire(bundle("window:exa-e2-older"))
            assert older.snapshot is not None
            newer = await ExaDeepAcquisitionCoordinator(
                transport=_Transport(
                    operational_payload(
                        request_id="exa-deep-newer-null-request",
                        value=None,
                    )
                ),
                storage=storage,
                conn_factory=conn_factory,
            ).acquire(
                bundle(
                    "window:exa-e2-newer-null",
                    research_intent="refreshed account-locked operational workflow evidence",
                )
            )
            assert newer.snapshot is not None and newer.snapshot.all_null

            bindings = await provider.resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=PROJECT_RUN_ID,
                account_entity_id=fixture.selected_account_id,
                research_directive=directive,
            )
            assert list(
                bindings["exa_deep"].resolve(
                    account.as_entity(),
                    await _field(conn, _OPERATIONAL),
                )
            ) == []
            with pytest.raises(ExaDeepSnapshotError, match="outside the exact effective directive"):
                await build_exa_deep_snapshot_resolver(
                    account=account,
                    snapshots=(older.snapshot,),
                    allowed_field_keys=(_STRATEGIC,),
                    storage=storage,
                    conn_factory=conn_factory,
                )

    run_async(scenario())
