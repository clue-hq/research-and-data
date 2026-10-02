"""DB acceptance for trusted Stage-0 readiness and durable ICP synthesis."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.stage0_project_contracts import (
    EvaluateStage0ReadinessV2Input,
    Stage0ReadinessV2Output,
    SynthesizeIcpsV2Input,
    SynthesizeIcpsV2Output,
)
from clue_api.stage0_project_tools import (
    EvaluateStage0ReadinessV2Tool,
    SynthesizeIcpsV2Tool,
)
from clue_api.trial.browser_fixture import (
    BRAND_ID,
    PRODUCT_ID,
    WORKSPACE_ID,
    seed_insight_health_browser_fixture,
    seed_insight_health_browser_onboarding_result,
)
from clue_core import ExecutionId, OnboardingInputKind, OperationId, RawArtifact
from clue_research.icp import get_icp_version
from clue_research.stage0 import get_readiness_decision, submit_onboarding_input
from clue_spine import create_project
from clue_storage import FsStorage, SnapshotSink, flush_snapshots
from clue_toolbelt import ToolContext
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _execution(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> ExecutionId:
    execution_id = ExecutionId(uuid4())
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            "parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "hash": "0" * 64,
        },
    )
    return execution_id


def test_insight_health_claims_drive_readiness_and_persist_replay_safe_draft_specs(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def conn_factory():
                yield conn

            await seed_insight_health_browser_fixture(
                conn,
                provider_subject="user_stage0_slice1_acceptance",
                display_name="Insight Health GTM Lead",
            )
            project = await create_project(
                conn,
                workspace_id=WORKSPACE_ID,
                brand_id=BRAND_ID,
                project_id="prj_stage0_slice1_acceptance",
                name="Insight Health Stage 0",
            )
            prompt = b"Start from Insight Health and co-define the Aura AI ICP."
            sink = SnapshotSink(workspace_id=WORKSPACE_ID)
            artifact_key = sink.capture(
                RawArtifact(
                    ref="fixture://stage0-slice1-prompt",
                    media_type="text/plain",
                    content=prompt,
                ),
                source_key="user_upload",
            )
            await flush_snapshots(conn, storage, sink)
            await submit_onboarding_input(
                conn,
                workspace_id=WORKSPACE_ID,
                brand_id=BRAND_ID,
                project_id=project.project_id,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=artifact_key,
                content_sha256=hashlib.sha256(prompt).hexdigest(),
                actor="human",
            )
            onboarding = await seed_insight_health_browser_onboarding_result(
                conn,
                provider_subject="user_stage0_slice1_acceptance",
                project_id=project.project_id,
                storage=storage,
            )
            assert len(onboarding.client_claim_ids) == 7
            execution_id = await _execution(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=project.project_id,
            )

            readiness_operation = OperationId(uuid4())
            readiness_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=readiness_operation,
                execution_id=execution_id,
            )
            readiness_tool = EvaluateStage0ReadinessV2Tool(conn_factory=conn_factory)
            assert not await readiness_tool.preconditions(
                EvaluateStage0ReadinessV2Input(gate="icp_synthesis"),
                readiness_ctx,
            )
            readiness_result = await readiness_tool.invoke(
                EvaluateStage0ReadinessV2Input(gate="icp_synthesis"),
                readiness_ctx,
            )
            readiness = Stage0ReadinessV2Output.model_validate(readiness_result.references)

            assert readiness.verdict == "ready"
            assert readiness.coverage_ratio == pytest.approx(7 / 9)
            assert len(readiness.available_field_keys) == 7
            # Official-site fixture claims are unverified; the backend reports that truth instead
            # of equating claim count with verification count.
            assert readiness.verified_claims == 0
            assert readiness.readiness_policy_version == 1
            decision = await get_readiness_decision(
                conn,
                readiness_operation,
                workspace_id=WORKSPACE_ID,
            )
            assert decision is not None
            assert decision.metrics["metrics_authority"] == ("backend_product_scoped_client_kb")
            assert len(decision.metrics["effective_expected_field_keys"]) == 9
            assert decision.product_id == PRODUCT_ID
            assert str(decision.client_entity_id) == onboarding.client_entity_id
            assert decision.client_kb_version == onboarding.client_kb_version

            replayed_readiness = Stage0ReadinessV2Output.model_validate(
                (
                    await readiness_tool.invoke(
                        EvaluateStage0ReadinessV2Input(gate="icp_synthesis"),
                        readiness_ctx,
                    )
                ).references
            )
            assert replayed_readiness == readiness
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM readiness_decision WHERE id = :decision_id"),
                    {"decision_id": readiness.readiness_decision_id},
                )
            ).scalar_one() == 1

            synthesis_operation = OperationId(uuid4())
            synthesis_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=synthesis_operation,
                execution_id=execution_id,
            )
            synthesis_tool = SynthesizeIcpsV2Tool(conn_factory=conn_factory)
            assert not await synthesis_tool.preconditions(SynthesizeIcpsV2Input(), synthesis_ctx)
            first = SynthesizeIcpsV2Output.model_validate(
                (await synthesis_tool.invoke(SynthesizeIcpsV2Input(), synthesis_ctx)).references
            )
            assert first.readiness_decision_id == readiness.readiness_decision_id
            assert first.icp_specs
            for ref in first.icp_specs:
                spec = await get_icp_version(
                    conn,
                    ref.workspace_id,
                    ref.icp_key,
                    ref.icp_version,
                )
                assert spec is not None
                assert spec.status.value == "draft"
                assert str(spec.client_entity_id) == onboarding.client_entity_id
                assert spec.client_kb_version == onboarding.client_kb_version
                assert spec.product_id == PRODUCT_ID

            spec_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM icp_spec WHERE workspace_id = :workspace"),
                        {"workspace": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            replay_result = await synthesis_tool.invoke(SynthesizeIcpsV2Input(), synthesis_ctx)
            replay = SynthesizeIcpsV2Output.model_validate(replay_result.references)
            assert replay == first
            assert replay_result.replayed is True
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM icp_spec WHERE workspace_id = :workspace"),
                    {"workspace": WORKSPACE_ID},
                )
            ).scalar_one() == spec_count
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM stage0_icp_synthesis WHERE operation_id = :operation"
                    ),
                    {"operation": UUID(str(synthesis_operation))},
                )
            ).scalar_one() == 1
            for mutation in (
                "UPDATE stage0_icp_synthesis SET product_id = product_id "
                "WHERE operation_id = :operation",
                "DELETE FROM stage0_icp_synthesis WHERE operation_id = :operation",
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with conn.begin_nested():
                        await conn.execute(
                            text(mutation),
                            {"operation": UUID(str(synthesis_operation))},
                        )

    run_async(scenario())


def test_empty_project_scope_is_explicitly_not_ready_instead_of_zero_over_zero_ready() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def conn_factory():
                yield conn

            await seed_insight_health_browser_fixture(
                conn,
                provider_subject="user_stage0_slice1_empty",
            )
            project = await create_project(
                conn,
                workspace_id=WORKSPACE_ID,
                brand_id=BRAND_ID,
                project_id="prj_stage0_slice1_empty",
                name="Empty Stage 0",
            )
            execution_id = await _execution(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=project.project_id,
            )
            ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=OperationId(uuid4()),
                execution_id=execution_id,
            )
            output = Stage0ReadinessV2Output.model_validate(
                (
                    await EvaluateStage0ReadinessV2Tool(conn_factory=conn_factory).invoke(
                        EvaluateStage0ReadinessV2Input(gate="icp_synthesis"),
                        ctx,
                    )
                ).references
            )
            assert output.verdict == "not_ready"
            assert output.coverage_ratio == 0.0
            assert output.available_field_keys == ()
            assert "coverage_below_floor" not in output.reason_codes
            assert "product_not_confirmed" in output.reason_codes
            assert "client_not_bound" in output.reason_codes

    run_async(scenario())
