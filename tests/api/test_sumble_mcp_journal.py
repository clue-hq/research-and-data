"""Real-PostgreSQL acceptance for the Sumble MCP account-gap journal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.sumble_account_gaps import compile_sumble_account_gap_preflight
from clue_api.sumble_mcp_journal import AccountGapSumbleMcpJournal
from clue_core import (
    AccountGapOperation,
    AccountGapOperationState,
    AccountGapSpendOutcome,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
    new_account_gap_operation_id,
)
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.tiering import TIER_FIELD
from clue_research.durable import (
    capture_discovery_artifact,
    claim_account_gap_operation,
    enumerate_discovery_subject_artifacts,
    list_account_gap_snapshots,
    reserve_account_gap_operation,
    seal_discovery_batch,
)
from clue_research.identity import stamp_reuse
from clue_research.resolvers.sumble import JOBS_SOURCE_KEY
from clue_research.resolvers.sumble.mcp_adapter import (
    GovernedSumbleMcpAdapter,
    SumbleMcpFieldBinding,
    SumbleMcpInvocationOutcome,
    SumbleMcpInvocationPlan,
    SumbleMcpSettlementMode,
    SumbleMcpSettlementRule,
)
from clue_research.resolvers.sumble.mcp_client import (
    SumbleMcpToolCatalog,
    SumbleMcpToolDescriptor,
    SumbleMcpToolExchange,
    SumbleMcpToolResult,
)
from clue_storage import FsStorage
from tests.api.test_exa_targeted_enrichment_e1 import _advance_sealed_run_to_deep
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _McpClient:
    def __init__(self) -> None:
        self.calls = 0

    async def initialize(self) -> None:
        return None

    async def call_tool(self, name: str, arguments: Any) -> SumbleMcpToolExchange:
        self.calls += 1
        assert name == "FindMatchAndEnrichJobs"
        assert arguments == {
            "reason": "Resolve one hiring signal for a selected account",
            "organization_ids": [1726684],
            "limit": 1,
        }
        payload = {
            "id": "sumble-mcp-job-request-1",
            "credits_used": 2,
            "credits_remaining": 998,
            "jobs": [{"job_id": 501, "job_function": "Software Engineer"}],
            "total": 7,
            "source_data_url": "https://sumble.com/l/org/insight-health-ai/jobs",
        }
        return SumbleMcpToolExchange(
            jsonrpc_request_id=4,
            session_id="session-db-test",
            tool_name=name,
            result=SumbleMcpToolResult(structuredContent=payload),
            payload=payload,
            raw_response={"structuredContent": payload, "isError": False},
        )


def _catalog() -> SumbleMcpToolCatalog:
    return SumbleMcpToolCatalog.from_tools(
        (
            SumbleMcpToolDescriptor(
                name="FindMatchAndEnrichJobs",
                description="Find and enrich jobs",
                inputSchema={
                    "type": "object",
                    "required": ["reason", "organization_ids", "limit"],
                    "additionalProperties": False,
                    "properties": {
                        "reason": {"type": "string", "minLength": 1},
                        "organization_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "limit": {"type": "integer"},
                    },
                },
                outputSchema={"type": "object"},
                annotations={"readOnlyHint": True, "destructiveHint": False},
            ),
        )
    )


def test_real_db_mcp_reservation_artifact_receipt_and_zero_call_replay(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = "ws-sumble-mcp-journal"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started)
            seal = await seal_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            await _advance_sealed_run_to_deep(conn, ProjectRunId(started.project_run_id))
            tier = stamp_reuse(
                account_claim(
                    entity_id=EntityId(ready.account_id),
                    field_key=TIER_FIELD,
                    value_json={
                        "tier": "high",
                        "decision_basis": "discovery_criteria",
                        "selection_policy_version": "discovery-selection-v1",
                        "decision_version": "sumble-mcp-test",
                        "cutoff_version": "sumble-mcp-test",
                        "discovery_batch_id": str(started.batch_id),
                        "discovery_seal_sha256": seal.seal_sha256,
                        "project_run_id": str(started.project_run_id),
                        "disposition": "selected",
                        "evidence_claim_ids": [],
                        "icp_key": "independent-specialty-practices",
                        "icp_version": 1,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=1,
                    run_id=RunId(started.project_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, tier)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            preflight = await compile_sumble_account_gap_preflight(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={"account.hiring_velocity_eng": Decimal(5)},
                provider_credit_cap=2,
                allow_unbounded_tech=False,
                observation_window=f"project-run:{started.project_run_id}:sumble-mcp-v1",
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            catalog = _catalog()
            request = preflight.request.model_copy(
                update={
                    "provider_api_version": "mcp-2025-06-18",
                    "provider_contract_version": f"sumble-mcp:{catalog.fingerprint}",
                    "field_policy_version": "sumble-mcp-governance-v1",
                }
            )
            input_key = await capture_discovery_artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                content=request.canonical_bytes(),
                media_type="application/json",
                source_key=JOBS_SOURCE_KEY,
                source_url="https://mcp.sumble.com/",
            )
            operation = AccountGapOperation(
                operation_id=new_account_gap_operation_id(),
                request=request,
                request_fingerprint=request.request_fingerprint,
                state=AccountGapOperationState.PLANNED,
                spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                input_artifact_key=input_key,
                provider_units_reserved=Decimal(2),
                cost_cents_reserved=Decimal(1),
            )
            operation, created = await reserve_account_gap_operation(
                conn, operation=operation, snapshots=()
            )
            assert created is True
            claimed = await claim_account_gap_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            assert claimed is not None
            plan = SumbleMcpInvocationPlan(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                source_key=JOBS_SOURCE_KEY,
                tool_name="FindMatchAndEnrichJobs",
                arguments={
                    "reason": "Resolve one hiring signal for a selected account",
                    "organization_ids": [1726684],
                    "limit": 1,
                },
                catalog_fingerprint=catalog.fingerprint,
                provider_contract_version=request.provider_contract_version,
                policy_version=request.field_policy_version,
                observation_window=request.observation_window,
                field_bindings=(
                    SumbleMcpFieldBinding(
                        field_key="account.hiring_velocity_eng",
                        value_pointer="/total",
                        source_url_pointer="/source_data_url",
                    ),
                ),
                maximum_provider_units=Decimal(2),
                expected_value_credits=Decimal(5),
                maximum_cost_cents=Decimal(1),
                settlement=SumbleMcpSettlementRule(
                    mode=SumbleMcpSettlementMode.PROVIDER_RECEIPT,
                    credits_used_pointer="/credits_used",
                    credits_remaining_pointer="/credits_remaining",
                    provider_request_id_pointer="/id",
                ),
            )
            journal = AccountGapSumbleMcpJournal(
                operation=claimed,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            authorization = await journal.authorization_for(plan)
            client = _McpClient()
            result = await GovernedSumbleMcpAdapter(
                client=client,
                journal=journal,
            ).invoke(plan=plan, authorization=authorization, catalog=catalog)

            assert result.outcome is SumbleMcpInvocationOutcome.COMPLETED
            assert result.snapshot is not None
            assert result.snapshot.provider_units_charged == Decimal(2)
            assert result.snapshot.cost_cents_charged == Decimal(1)
            assert client.calls == 1
            snapshots = await list_account_gap_snapshots(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            assert len(snapshots) == 1
            assert snapshots[0].state.value == "succeeded"
            assert snapshots[0].request_artifact_key
            assert snapshots[0].response_artifact_key
            assert snapshots[0].provider_request_id == "sumble-mcp-job-request-1"
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM account_gap_snapshot WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            ).scalar_one() == 1

            replay_client = _McpClient()
            replay_journal = AccountGapSumbleMcpJournal(
                operation=claimed,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            replay = await GovernedSumbleMcpAdapter(
                client=replay_client,
                journal=replay_journal,
            ).invoke(
                plan=plan,
                authorization=await replay_journal.authorization_for(plan),
                catalog=catalog,
            )
            assert replay.outcome is SumbleMcpInvocationOutcome.REPLAYED
            assert replay.snapshot == result.snapshot
            assert replay_client.calls == 0

            artifacts = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=EntityId(ready.account_id),
            )
            assert {
                item.reference_kind
                for item in artifacts
                if item.reference_kind.startswith("sumble_mcp")
            } == {"sumble_mcp_request", "sumble_mcp_response"}

    run_async(scenario())
