"""DB acceptance for the exact-draft ICP confirmation lifecycle.

The tests use the real Insight Health onboarding substitute and Stage-0 tools.  The gate is not a
hand-authored fixture: readiness derives the Client-KB metrics, synthesis persists the draft, and
the governed opener binds that exact draft to one project turn and one human.  The HTTP assertions
then prove that Approve, Reject and Revise create one immutable receipt with the expected domain
effect, while tampered or stale decisions remain side-effect free.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_gate import get_gate
from clue_api.agent_turn_submission import thread_work_id
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.discovery_configuration import get_discovery_configuration_receipt
from clue_api.execution_wiring import build_tool_invoker
from clue_api.product_knowledge_privacy import product_context_subject_bindings
from clue_api.projections_app import create_projections_app
from clue_api.stage0_icp_gate_tools import (
    OpenIcpConfirmationGateInput,
    OpenIcpConfirmationGateOutput,
    OpenIcpConfirmationGateTool,
)
from clue_api.stage0_project_contracts import (
    EvaluateStage0ReadinessV2Input,
    Stage0ReadinessV2Output,
    StartConfirmedProjectRunV2Input,
    StartConfirmedProjectRunV2Output,
    StartConfirmedProjectRunV3Input,
    StartConfirmedProjectRunV3Output,
    SynthesizeIcpsV2Input,
    SynthesizeIcpsV2Output,
)
from clue_api.stage0_project_tools import (
    EvaluateStage0ReadinessV2Tool,
    OpenDiscoveryConfigurationGateInput,
    OpenDiscoveryConfigurationGateOutput,
    OpenDiscoveryConfigurationGateTool,
    StartConfirmedProjectRunV2Tool,
    StartConfirmedProjectRunV3Tool,
    SynthesizeIcpsV2Tool,
)
from clue_api.thread_wiring import register_thread_tools
from clue_api.trial.browser_fixture import (
    BRAND_ID,
    WORKSPACE_ID,
    seed_insight_health_browser_fixture,
    seed_insight_health_browser_onboarding_result,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_config import Settings, load_settings
from clue_core import (
    ExecutionId,
    ICPStatus,
    OnboardingInputKind,
    OperationId,
    ProjectPhase,
    ProjectRunId,
    RawArtifact,
    RunId,
    decode_jsonb,
)
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
    PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
    PRODUCT_PROFILE_CARD_MEDIA_TYPE,
    STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE,
)
from clue_research.claimstore import record_run_lineage
from clue_research.durable import ProjectRunStatus, get_project_run
from clue_research.durable.project_run import set_phase
from clue_research.icp import activate_icp_version, create_icp_spec, get_icp_version
from clue_research.stage0 import (
    current_kb_version,
    finalize_client_kb_version,
    submit_onboarding_input,
)
from clue_spine import create_project
from clue_storage import FsStorage, SnapshotSink, flush_snapshots
from clue_toolbelt import DbIdempotencyStore, ToolContext, ToolRegistry
from tests._identity import seed_principal
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

_AUTHENTICATED_AT = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


class _RecordingProjectExecutionRouter:
    def __init__(self) -> None:
        self.attached: list[ProjectRunId] = []

    async def attach_if_eligible(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId | None:
        del actor, parent_execution_id
        self.attached.append(project_run_id)
        return None

    async def attach_confirmed_discovery(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId:
        del actor, parent_execution_id
        self.attached.append(project_run_id)
        return ExecutionId(uuid5(NAMESPACE_URL, f"confirmed-discovery:{project_run_id}"))

    async def pause_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        reason_code: str,
    ) -> bool:
        del project_run_id, actor, reason_code
        return False

    async def resume_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
    ) -> bool:
        del project_run_id, actor
        return False


@dataclass(frozen=True, slots=True)
class _Scenario:
    workspace_id: str
    project_id: str
    thread_id: str
    user_id: str
    membership_id: str
    execution_id: ExecutionId
    presenting_turn_id: UUID
    icp_key: str
    icp_version: int
    gate_id: UUID
    storage: FsStorage


def _settings() -> Settings:
    return load_settings(_env_file=None, chat_enabled=True)


def _principal(scenario: _Scenario, *, user_id: str | None = None) -> Any:
    resolved_user_id = user_id or scenario.user_id
    membership_id = (
        scenario.membership_id
        if resolved_user_id == scenario.user_id
        else f"wsm_stage0_slice2_{resolved_user_id}"
    )

    def resolve(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            user_id=resolved_user_id,
            membership_id=membership_id,
            workspace_id=workspace_id,
            role_key="owner",
            permissions=CHAT_PERMISSIONS,
            authenticated_at=_AUTHENTICATED_AT,
        )

    return resolve


def _app(conn: Any, scenario: _Scenario, *, user_id: str | None = None) -> Any:
    conn_factory = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=conn_factory)
    settings = _settings()
    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=conn_factory,
        ),
        settings=settings,
        conn_factory=conn_factory,
        manage_db_lifespan=False,
        ingestion_storage=scenario.storage,
        chat_principal_resolver=_principal(scenario, user_id=user_id),
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _execution(
    conn: AsyncConnection,
    *,
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
            "workspace": WORKSPACE_ID,
            "project": project_id,
            "hash": "0" * 64,
        },
    )
    return execution_id


async def _seed_scenario(
    conn: AsyncConnection,
    tmp_path: Path,
    *,
    label: str,
) -> _Scenario:
    """Materialize the production path through onboarding, synthesis, turn and gate."""

    provider_subject = f"user_stage0_slice2_{label}"
    fixture = await seed_insight_health_browser_fixture(
        conn,
        provider_subject=provider_subject,
        display_name=f"Insight Health {label}",
    )
    project = await create_project(
        conn,
        workspace_id=WORKSPACE_ID,
        brand_id=BRAND_ID,
        project_id=f"prj_stage0_slice2_{label}",
        name=f"Insight Health ICP {label}",
    )
    storage = FsStorage(tmp_path / f"stage0-slice2-{label}")
    prompt = f"Co-define the Insight Health Aura AI ICP for {label}.".encode()
    sink = SnapshotSink(workspace_id=WORKSPACE_ID)
    artifact_key = sink.capture(
        RawArtifact(
            ref=f"fixture://stage0-slice2/{label}/prompt",
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
    await seed_insight_health_browser_onboarding_result(
        conn,
        provider_subject=provider_subject,
        project_id=project.project_id,
        storage=storage,
    )
    execution_id = await _execution(conn, project_id=project.project_id)

    @asynccontextmanager
    async def conn_factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    readiness_ctx = ToolContext(
        workspace_id=WORKSPACE_ID,
        actor="agent",
        conn_factory=conn_factory,
        operation_id=OperationId(uuid4()),
        execution_id=execution_id,
    )
    readiness = Stage0ReadinessV2Output.model_validate(
        (
            await EvaluateStage0ReadinessV2Tool(conn_factory=conn_factory).invoke(
                EvaluateStage0ReadinessV2Input(gate="icp_synthesis"),
                readiness_ctx,
            )
        ).references
    )
    assert readiness.verdict == "ready"
    synthesis_ctx = ToolContext(
        workspace_id=WORKSPACE_ID,
        actor="agent",
        conn_factory=conn_factory,
        operation_id=OperationId(uuid4()),
        execution_id=execution_id,
    )
    synthesis = SynthesizeIcpsV2Output.model_validate(
        (
            await SynthesizeIcpsV2Tool(conn_factory=conn_factory).invoke(
                SynthesizeIcpsV2Input(), synthesis_ctx
            )
        ).references
    )
    proposal = synthesis.icp_specs[0]

    thread_id = f"thr_stage0_slice2_{label}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user)"
        ),
        {
            "id": thread_id,
            "workspace": WORKSPACE_ID,
            "project": project.project_id,
            "user": fixture.user_id,
        },
    )
    artifacts = DurableAgentArtifactStore(
        storage=storage,
        conn_factory=conn_session_factory(conn),
    )
    manifest = await artifacts.persist_body(
        workspace_id=WORKSPACE_ID,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    presenting_turn_id = uuid5(NAMESPACE_URL, f"stage0-slice2:{label}:presenting-turn")
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at, "
            " submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor, 'head_of_abm', "
            " :root, 'head-of-abm', 'v25', :profile_sha, :manifest_key, :manifest_sha, "
            " :manifest_sha, 'test', :requested_at, :user, :membership)"
        ),
        {
            "id": presenting_turn_id,
            "execution": execution_id,
            "workspace": WORKSPACE_ID,
            "project": project.project_id,
            "thread": thread_id,
            "actor": fixture.user_id,
            "root": f"root-{label}",
            "profile_sha": "0" * 64,
            "manifest_key": manifest.artifact_key,
            "manifest_sha": manifest.sha256,
            "requested_at": _AUTHENTICATED_AT,
            "user": fixture.user_id,
            "membership": fixture.membership_id,
        },
    )

    gate_ctx = ToolContext(
        workspace_id=WORKSPACE_ID,
        actor="agent",
        conn_factory=conn_factory,
        operation_id=OperationId(uuid4()),
        execution_id=execution_id,
    )
    gate_tool = OpenIcpConfirmationGateTool(conn_factory=conn_factory)
    gate_input = OpenIcpConfirmationGateInput(
        icp_key=proposal.icp_key,
        icp_version=proposal.icp_version,
        source_turn_ref=derive_turn_action_ref(presenting_turn_id),
    )
    assert not await gate_tool.preconditions(gate_input, gate_ctx)
    gate_output = OpenIcpConfirmationGateOutput.model_validate(
        (await gate_tool.invoke(gate_input, gate_ctx)).references
    )
    assert gate_output.created is True

    return _Scenario(
        workspace_id=WORKSPACE_ID,
        project_id=project.project_id,
        thread_id=thread_id,
        user_id=fixture.user_id,
        membership_id=fixture.membership_id,
        execution_id=execution_id,
        presenting_turn_id=presenting_turn_id,
        icp_key=proposal.icp_key,
        icp_version=proposal.icp_version,
        gate_id=UUID(gate_output.gate_id),
        storage=storage,
    )


async def _answer(
    client: httpx.AsyncClient,
    scenario: _Scenario,
    *,
    decision: str,
    key: str,
    digest: str,
    revision_request: str | None = None,
    amount: str | None = None,
) -> httpx.Response:
    gate_response: dict[str, Any] = {
        "gate_id": str(scenario.gate_id),
        "decision": decision,
        "expected_subject_sha256": digest,
    }
    if revision_request is not None:
        gate_response["revision_request"] = revision_request
    if amount is not None:
        gate_response["expected_estimated_cost_cents"] = amount
    return await client.post(
        f"/api/v1/projects/{scenario.project_id}/threads/{scenario.thread_id}/turns",
        json={"gate_response": gate_response},
        headers={"X-Workspace-Id": scenario.workspace_id, "Idempotency-Key": key},
    )


async def _answer_count(conn: AsyncConnection, scenario: _Scenario) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM agent_gate_answer WHERE gate_id = :gate_id"),
                {"gate_id": scenario.gate_id},
            )
        ).scalar_one()
    )


async def _seed_confirmed_run_turn(
    conn: AsyncConnection,
    scenario: _Scenario,
    *,
    foreign_product_profile: bool = False,
) -> ExecutionId:
    """Materialize one post-approval governed turn with its exact existing context cards."""

    project = (
        (
            await conn.execute(
                text(
                    "SELECT project_id, name, status, brand_id, product_id "
                    "FROM project WHERE project_id=:project_id AND workspace_id=:workspace_id"
                ),
                {"project_id": scenario.project_id, "workspace_id": scenario.workspace_id},
            )
        )
        .mappings()
        .one()
    )
    client_entity_id = (
        await conn.execute(
            text(
                "SELECT client_entity_id FROM onboarding_input "
                "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                "AND client_entity_id IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"workspace_id": scenario.workspace_id, "project_id": scenario.project_id},
        )
    ).scalar_one()
    company_version = await current_kb_version(
        conn,
        client_entity_id,
        workspace_id=scenario.workspace_id,
        product_id=None,
    )
    product_version = await current_kb_version(
        conn,
        client_entity_id,
        workspace_id=scenario.workspace_id,
        product_id=str(project["product_id"]),
    )
    if product_version is None:
        product_run_id = RunId(uuid4())
        await record_run_lineage(
            conn,
            run_id=product_run_id,
            workspace_id=scenario.workspace_id,
            kind="stage0",
        )
        product_version = await finalize_client_kb_version(
            conn,
            client_entity_id=client_entity_id,
            workspace_id=scenario.workspace_id,
            run_id=product_run_id,
            filled_fields=set(),
            attempted_fields=set(),
            product_id=str(project["product_id"]),
        )
    assert company_version is not None

    artifacts = DurableAgentArtifactStore(
        storage=scenario.storage,
        conn_factory=conn_session_factory(conn),
    )
    manifest = await artifacts.persist_body(
        workspace_id=scenario.workspace_id,
        data=b'{"confirmed-run-resources":[]}',
        media_type="application/json",
    )
    context_refs = []
    for index, media_type in enumerate(
        (
            CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
            STAGE0_PROJECT_STATE_CARD_MEDIA_TYPE,
            PRODUCT_PROFILE_CARD_MEDIA_TYPE,
            PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
        )
    ):
        product_scoped = media_type in {
            PRODUCT_PROFILE_CARD_MEDIA_TYPE,
            PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
        }
        context_refs.append(
            await artifacts.persist_body(
                workspace_id=scenario.workspace_id,
                data=f"existing-stage0-context-{index}".encode(),
                media_type=media_type,
                subject_bindings=(
                    product_context_subject_bindings(
                        client_entity_id=UUID(str(client_entity_id)),
                        product_id=(
                            "prd_foreign"
                            if foreign_product_profile
                            and media_type == PRODUCT_PROFILE_CARD_MEDIA_TYPE
                            else str(project["product_id"])
                        ),
                    )
                    if product_scoped
                    else ((UUID(str(client_entity_id)), "context"),)
                ),
                project_bindings=((scenario.project_id, "project_conversation_context"),),
            )
        )

    execution_id = await _execution(conn, project_id=scenario.project_id)
    turn_id = (
        await conn.execute(
            text(
                "SELECT turn_id FROM agent_turn_submission "
                "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                "AND thread_id=:thread_id ORDER BY requested_at DESC, turn_id DESC LIMIT 1"
            ),
            {
                "workspace_id": scenario.workspace_id,
                "project_id": scenario.project_id,
                "thread_id": scenario.thread_id,
            },
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :workspace, :project, :thread, 'agent', 'head_of_abm', "
            " :root, 'head-of-abm', 'v30', :profile_sha, :manifest_key, :manifest_sha, "
            " :manifest_sha, 'test', :requested_at)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": scenario.workspace_id,
            "project": scenario.project_id,
            "thread": scenario.thread_id,
            "root": f"root-confirmed-run-{turn_id}",
            "profile_sha": "0" * 64,
            "manifest_key": manifest.artifact_key,
            "manifest_sha": manifest.sha256,
            "requested_at": _AUTHENTICATED_AT,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn_scope_pin "
            "(turn_id, workspace_id, project_id, project_name, project_status, brand_id, "
            " product_id, client_entity_id, client_kb_version, product_kb_version, "
            " knowledge_scope_policy_version) "
            "VALUES (:turn_id, :workspace_id, :project_id, :project_name, :project_status, "
            " :brand_id, :product_id, :client_entity_id, :client_kb_version, "
            " :product_kb_version, 'company-and-selected-product-v2')"
        ),
        {
            "turn_id": turn_id,
            "workspace_id": scenario.workspace_id,
            "project_id": scenario.project_id,
            "project_name": project["name"],
            "project_status": project["status"],
            "brand_id": project["brand_id"],
            "product_id": project["product_id"],
            "client_entity_id": client_entity_id,
            "client_kb_version": company_version,
            "product_kb_version": product_version,
        },
    )
    for ordinal, ref in enumerate(context_refs):
        await conn.execute(
            text(
                "INSERT INTO agent_artifact_ref "
                "(id, turn_id, workspace_id, owner_kind, owner_id, ref_role, ordinal, "
                " artifact_key, artifact_sha256, retention_class) "
                "VALUES (:id, :turn_id, :workspace_id, 'context', :turn_id, "
                " 'context_materialization', :ordinal, :artifact_key, :sha256, 'test')"
            ),
            {
                "id": uuid4(),
                "turn_id": turn_id,
                "workspace_id": scenario.workspace_id,
                "ordinal": ordinal,
                "artifact_key": ref.artifact_key,
                "sha256": ref.sha256,
            },
        )
    return execution_id


def test_confirmed_run_v2_reuses_existing_context_and_creates_one_run_across_retries(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label="confirmed-run-v2")
            gate = await get_gate(
                conn,
                workspace_id=seeded.workspace_id,
                gate_id=seeded.gate_id,
            )
            assert gate is not None
            app = _app(conn, seeded)
            async with _client(app) as client:
                approved = await _answer(
                    client,
                    seeded,
                    decision="approved",
                    key="confirmed-run-v2-approval",
                    digest=gate.gate.expected_subject_sha256,
                )
            assert approved.status_code == 202, approved.text

            execution_id = await _seed_confirmed_run_turn(conn, seeded)
            before_claims = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE workspace_id=:workspace_id"),
                        {"workspace_id": seeded.workspace_id},
                    )
                ).scalar_one()
            )
            before_human_gates = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM agent_gate WHERE workspace_id=:workspace_id"),
                        {"workspace_id": seeded.workspace_id},
                    )
                ).scalar_one()
            )

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            unrouted_ctx = ToolContext(
                workspace_id=seeded.workspace_id,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=OperationId(uuid4()),
                execution_id=execution_id,
            )
            unrouted_tool = StartConfirmedProjectRunV2Tool(
                conn_factory=conn_factory,
                project_execution_router=None,
                budget_controls_enabled=False,
            )
            assert [
                failure.reason_code
                for failure in await unrouted_tool.preconditions(
                    StartConfirmedProjectRunV2Input(), unrouted_ctx
                )
            ] == ["confirmed_discovery_router_unavailable"]
            with pytest.raises(RuntimeError, match="execution router is unavailable"):
                await unrouted_tool.invoke(StartConfirmedProjectRunV2Input(), unrouted_ctx)

            router = _RecordingProjectExecutionRouter()
            tool = StartConfirmedProjectRunV2Tool(
                conn_factory=conn_factory,
                project_execution_router=router,
                budget_controls_enabled=False,
            )

            async def invoke(
                tool_to_invoke: StartConfirmedProjectRunV2Tool,
            ) -> StartConfirmedProjectRunV2Output:
                ctx = ToolContext(
                    workspace_id=seeded.workspace_id,
                    actor="agent",
                    conn_factory=conn_factory,
                    operation_id=OperationId(uuid4()),
                    execution_id=execution_id,
                )
                assert not await tool_to_invoke.preconditions(
                    StartConfirmedProjectRunV2Input(), ctx
                )
                return StartConfirmedProjectRunV2Output.model_validate(
                    (await tool_to_invoke.invoke(StartConfirmedProjectRunV2Input(), ctx)).references
                )

            outputs = [await invoke(tool)]
            first_run_id = ProjectRunId(UUID(outputs[0].project_run_id))
            await set_phase(
                conn,
                first_run_id,
                phase=ProjectPhase.SCORING,
                status=ProjectRunStatus.ACTIVE,
            )
            outputs.append(await invoke(tool))

            assert outputs[0] == outputs[1]
            assert outputs[0].phase == "discovery"
            assert len(router.attached) == 2
            run = await get_project_run(conn, first_run_id)
            assert run is not None
            assert run.phase is ProjectPhase.SCORING
            assert run.project_id == seeded.project_id
            assert run.icp_key == seeded.icp_key
            assert run.icp_version == seeded.icp_version
            assert run.product_context_version_id is not None
            assert run.readiness_decision_id is not None

            context = (
                (
                    await conn.execute(
                        text(
                            "SELECT artifact_refs, freshness_snapshot, compiler_version "
                            "FROM product_context_version WHERE id=:id"
                        ),
                        {"id": run.product_context_version_id},
                    )
                )
                .mappings()
                .one()
            )
            freshness = decode_jsonb(context["freshness_snapshot"])
            assert context["compiler_version"] == "product-context@2-existing-stage0-receipt"
            assert len(decode_jsonb(context["artifact_refs"])) == 4
            assert [item["kind"] for item in freshness["inputs"]] == [
                "client_kb",
                "selected_product",
                "product_profile",
                "product_kb",
                "approved_icp",
            ]
            assert freshness["manifest_sha256"]

            readiness = (
                (
                    await conn.execute(
                        text("SELECT gate, verdict, metrics FROM readiness_decision WHERE id=:id"),
                        {"id": run.readiness_decision_id},
                    )
                )
                .mappings()
                .one()
            )
            metrics = decode_jsonb(readiness["metrics"])
            assert (readiness["gate"], readiness["verdict"]) == (
                "discovery_spend",
                "ready",
            )
            assert metrics["budget_controls_enabled"] is False
            assert metrics["budget_enforcement_mode"] == "record_only"
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM product_context_version "
                                "WHERE workspace_id=:workspace_id"
                            ),
                            {"workspace_id": seeded.workspace_id},
                        )
                    ).scalar_one()
                )
                == 1
            )
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM readiness_decision "
                                "WHERE workspace_id=:workspace_id AND gate='discovery_spend'"
                            ),
                            {"workspace_id": seeded.workspace_id},
                        )
                    ).scalar_one()
                )
                == 1
            )
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM project_run "
                                "WHERE workspace_id=:workspace_id AND project_id=:project_id"
                            ),
                            {
                                "workspace_id": seeded.workspace_id,
                                "project_id": seeded.project_id,
                            },
                        )
                    ).scalar_one()
                )
                == 1
            )
            assert (
                int(
                    (
                        await conn.execute(
                            text("SELECT count(*) FROM claim WHERE workspace_id=:workspace_id"),
                            {"workspace_id": seeded.workspace_id},
                        )
                    ).scalar_one()
                )
                == before_claims
            )
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM agent_gate WHERE workspace_id=:workspace_id"
                            ),
                            {"workspace_id": seeded.workspace_id},
                        )
                    ).scalar_one()
                )
                == before_human_gates
            )

            # A deployment-mode change cannot reinterpret the stored record-only authority as an
            # enforced decision on the same immutable run. The new mode derives a distinct
            # readiness identity, and the run-lineage guard refuses to replace the original.
            enforced_tool = StartConfirmedProjectRunV2Tool(
                conn_factory=conn_factory,
                project_execution_router=router,
                budget_controls_enabled=True,
            )
            with pytest.raises(ValueError, match="different immutable lineage"):
                async with conn.begin_nested():
                    await invoke(enforced_tool)
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM readiness_decision "
                                "WHERE workspace_id=:workspace_id AND gate='discovery_spend'"
                            ),
                            {"workspace_id": seeded.workspace_id},
                        )
                    ).scalar_one()
                )
                == 1
            )

    run_async(scenario())


def test_confirmed_run_v2_refuses_a_context_card_bound_to_another_product(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label="confirmed-run-foreign-product")
            gate = await get_gate(
                conn,
                workspace_id=seeded.workspace_id,
                gate_id=seeded.gate_id,
            )
            assert gate is not None
            app = _app(conn, seeded)
            async with _client(app) as client:
                approved = await _answer(
                    client,
                    seeded,
                    decision="approved",
                    key="confirmed-run-foreign-product-approval",
                    digest=gate.gate.expected_subject_sha256,
                )
            assert approved.status_code == 202, approved.text
            execution_id = await _seed_confirmed_run_turn(
                conn,
                seeded,
                foreign_product_profile=True,
            )

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            tool = StartConfirmedProjectRunV2Tool(
                conn_factory=conn_factory,
                project_execution_router=_RecordingProjectExecutionRouter(),
                budget_controls_enabled=False,
            )
            ctx = ToolContext(
                workspace_id=seeded.workspace_id,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=OperationId(uuid4()),
                execution_id=execution_id,
            )
            failures = await tool.preconditions(StartConfirmedProjectRunV2Input(), ctx)
            assert [failure.reason_code for failure in failures] == [
                "stage0_context_materialization_missing"
            ]

    run_async(scenario())


def test_confirmed_run_v3_pins_one_human_confirmed_provider_neutral_scope(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label="confirmed-run-v3")
            gate = await get_gate(
                conn,
                workspace_id=seeded.workspace_id,
                gate_id=seeded.gate_id,
            )
            assert gate is not None
            app = _app(conn, seeded)
            async with _client(app) as client:
                approved = await _answer(
                    client,
                    seeded,
                    decision="approved",
                    key="confirmed-run-v3-approval",
                    digest=gate.gate.expected_subject_sha256,
                )
            assert approved.status_code == 202, approved.text
            approval_turn_id = UUID(approved.json()["data"]["turn_id"])
            execution_id = await _seed_confirmed_run_turn(conn, seeded)

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            router = _RecordingProjectExecutionRouter()
            tool = StartConfirmedProjectRunV3Tool(
                conn_factory=conn_factory,
                project_execution_router=router,
                budget_controls_enabled=False,
            )

            initial_ctx = ToolContext(
                workspace_id=seeded.workspace_id,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=OperationId(uuid4()),
                execution_id=execution_id,
            )
            initial = await tool.preconditions(StartConfirmedProjectRunV3Input(), initial_ctx)
            assert [failure.reason_code for failure in initial] == [
                "discovery_configuration_confirmation_required"
            ]

            scope_tool = OpenDiscoveryConfigurationGateTool(conn_factory=conn_factory)
            scope_input = OpenDiscoveryConfigurationGateInput(
                requested_account_count=50,
                search_intent="Find independent specialty healthcare practices in the US.",
                must_have_criteria=(
                    "Independent specialty healthcare practice",
                    "United States",
                ),
                exclusion_criteria=("Current customers", "Hospitals"),
                source_turn_ref=derive_turn_action_ref(approval_turn_id),
            )
            scope_ctx = ToolContext(
                workspace_id=seeded.workspace_id,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=OperationId(uuid4()),
                execution_id=execution_id,
            )
            assert not await scope_tool.preconditions(scope_input, scope_ctx)
            scope_gate = OpenDiscoveryConfigurationGateOutput.model_validate(
                (await scope_tool.invoke(scope_input, scope_ctx)).references
            )
            async with _client(app) as client:
                scope_approved = await client.post(
                    f"/api/v1/projects/{seeded.project_id}/threads/"
                    f"{seeded.thread_id}/turns",
                    json={
                        "gate_response": {
                            "gate_id": scope_gate.gate_id,
                            "decision": "approved",
                            "expected_subject_sha256": scope_gate.expected_subject_sha256,
                        }
                    },
                    headers={
                        "X-Workspace-Id": seeded.workspace_id,
                        "Idempotency-Key": "confirmed-run-v3-scope-approval",
                    },
                )
            assert scope_approved.status_code == 202, scope_approved.text

            async def invoke() -> StartConfirmedProjectRunV3Output:
                ctx = ToolContext(
                    workspace_id=seeded.workspace_id,
                    actor="agent",
                    conn_factory=conn_factory,
                    operation_id=OperationId(uuid4()),
                    execution_id=execution_id,
                )
                inputs = StartConfirmedProjectRunV3Input()
                assert not await tool.preconditions(inputs, ctx)
                return StartConfirmedProjectRunV3Output.model_validate(
                    (await tool.invoke(inputs, ctx)).references
                )

            first = await invoke()
            replay = await invoke()
            assert replay == first
            assert len(router.attached) == 2

            run_id = ProjectRunId(UUID(first.project_run_id))
            receipt = await get_discovery_configuration_receipt(
                conn,
                project_run_id=run_id,
                workspace_id=seeded.workspace_id,
            )
            assert receipt is not None
            assert receipt.project_id == seeded.project_id
            assert (receipt.icp_key, receipt.icp_version) == (
                seeded.icp_key,
                seeded.icp_version,
            )
            assert receipt.configuration.requested_account_count == 50
            assert receipt.configuration.entity_type == "company"
            assert receipt.configuration.must_have_criteria == (
                "Independent specialty healthcare practice",
                "United States",
            )
            assert receipt.configuration.exclusion_criteria == (
                "Current customers",
                "Hospitals",
            )
            assert receipt.source_gate_id == UUID(scope_gate.gate_id)
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM project_run_discovery_configuration "
                                "WHERE project_run_id=:project_run_id"
                            ),
                            {"project_run_id": run_id},
                        )
                    ).scalar_one()
                )
                == 1
            )

    run_async(scenario())


def test_gate_tool_persists_the_exact_supported_draft_and_replays(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label="open")
            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=seeded.gate_id)
            assert view is not None and view.is_open
            assert view.gate.kind == "icp_confirmation"
            assert view.gate.project_id == seeded.project_id
            assert view.gate.thread_id == seeded.thread_id
            assert view.gate.turn_id == seeded.presenting_turn_id
            assert view.gate.subject_revision == seeded.icp_version
            assert view.gate.subject_snapshot["icp_key"] == seeded.icp_key
            assert view.gate.subject_snapshot["version"] == seeded.icp_version
            assert view.gate.subject_snapshot["status"] == "draft"
            assert view.gate.permitted_decisions == ("approved", "rejected", "revised")
            assert view.gate.max_spend_cents is None
            assert view.gate.currency is None
            assert view.gate.addressee_user_id == seeded.user_id

            # A future caller bypassing the helper still cannot create a second authority object
            # over the same exact project-scoped draft. This closes the two-gates/two-decisions
            # race at the database boundary, not just in today's tool implementation.
            with pytest.raises(DBAPIError, match="agent_gate_one_icp_subject"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO agent_gate "
                            "(gate_id, workspace_id, project_id, thread_id, turn_id, kind, "
                            " subject_ref, subject_revision, expected_subject_sha256, "
                            " subject_snapshot, permitted_decisions, max_spend_cents, currency, "
                            " addressee_user_id) "
                            "SELECT :new_gate_id, workspace_id, project_id, thread_id, turn_id, "
                            " kind, subject_ref, subject_revision, expected_subject_sha256, "
                            " subject_snapshot, permitted_decisions, max_spend_cents, currency, "
                            " addressee_user_id FROM agent_gate WHERE gate_id = :gate_id"
                        ),
                        {"new_gate_id": uuid4(), "gate_id": seeded.gate_id},
                    )

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            replay_ctx = ToolContext(
                workspace_id=seeded.workspace_id,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=OperationId(uuid4()),
                execution_id=seeded.execution_id,
            )
            replay = OpenIcpConfirmationGateOutput.model_validate(
                (
                    await OpenIcpConfirmationGateTool(conn_factory=conn_factory).invoke(
                        OpenIcpConfirmationGateInput(
                            icp_key=seeded.icp_key,
                            icp_version=seeded.icp_version,
                            source_turn_ref=derive_turn_action_ref(seeded.presenting_turn_id),
                        ),
                        replay_ctx,
                    )
                ).references
            )
            assert UUID(replay.gate_id) == seeded.gate_id
            assert replay.created is False
            assert replay.expected_subject_sha256 == view.gate.expected_subject_sha256
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_gate WHERE gate_id = :gate_id"),
                    {"gate_id": seeded.gate_id},
                )
            ).scalar_one() == 1

            # Merely sharing the workspace/product/client lineage is insufficient. A model cannot
            # name some other durable draft and make this project's conversation authoritative
            # over it; the project synthesis ledger is the binding seam.
            spec = await get_icp_version(
                conn,
                seeded.workspace_id,
                seeded.icp_key,
                seeded.icp_version,
            )
            assert spec is not None
            unrelated = await create_icp_spec(
                conn,
                workspace_id=seeded.workspace_id,
                icp_key="unrelated-project-proposal",
                created_from=spec.created_from,
                field_keys=spec.field_keys,
                enabled_packs=spec.enabled_packs,
                discovery_strategy=spec.discovery_strategy,
                source_profile_ref=spec.source_profile_ref,
                scoring_rubric=spec.scoring_rubric,
                created_by="agent",
                label="Unrelated proposal",
                activate=False,
                client_entity_id=spec.client_entity_id,
                client_kb_version=spec.client_kb_version,
                product_id=spec.product_id,
            )
            failures = await OpenIcpConfirmationGateTool(conn_factory=conn_factory).preconditions(
                OpenIcpConfirmationGateInput(
                    icp_key=unrelated.icp_key,
                    icp_version=unrelated.version,
                    source_turn_ref=derive_turn_action_ref(seeded.presenting_turn_id),
                ),
                replay_ctx,
            )
            assert [failure.reason_code for failure in failures] == [
                "icp_spec_not_project_proposal"
            ]

            app = _app(conn, seeded)
            async with _client(app) as client:
                response = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            assert response.status_code == 200, response.text
            wire = response.json()["data"][0]
            assert wire["gate_id"] == str(seeded.gate_id)
            assert wire["permitted_decisions"] == ["approved", "rejected", "revised"]
            assert wire["max_spend_cents"] is None
            assert wire["currency"] is None

    run_async(scenario())


@pytest.mark.parametrize(
    ("decision", "revision_request", "expected_status"),
    [
        ("approved", None, ICPStatus.ACTIVE),
        ("rejected", None, ICPStatus.DRAFT),
        ("revised", "Focus the ICP on multi-site neurosurgery groups.", ICPStatus.DRAFT),
    ],
)
def test_structured_decisions_persist_one_receipt_and_apply_only_the_exact_effect(
    tmp_path: Path,
    decision: str,
    revision_request: str | None,
    expected_status: ICPStatus,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label=decision)
            before = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=seeded.gate_id)
            assert before is not None
            original_snapshot = before.gate.subject_snapshot
            app = _app(conn, seeded)
            async with _client(app) as client:
                first = await _answer(
                    client,
                    seeded,
                    decision=decision,
                    key=f"slice2-{decision}",
                    digest=before.gate.expected_subject_sha256,
                    revision_request=revision_request,
                )
                replay = await _answer(
                    client,
                    seeded,
                    decision=decision,
                    key=f"slice2-{decision}",
                    digest=before.gate.expected_subject_sha256,
                    revision_request=revision_request,
                )
                second_turn = await _answer(
                    client,
                    seeded,
                    decision="rejected" if decision == "approved" else "approved",
                    key=f"slice2-{decision}-second-turn",
                    digest=before.gate.expected_subject_sha256,
                )
            assert first.status_code == 202, first.text
            assert replay.status_code == 202, replay.text
            assert first.json()["data"]["replayed"] is False
            assert replay.json()["data"]["replayed"] is True
            assert replay.json()["data"]["turn_id"] == first.json()["data"]["turn_id"]
            assert second_turn.status_code == 409, second_turn.text
            assert second_turn.json()["error"]["code"] == "GATE_ALREADY_ANSWERED"

            spec = await get_icp_version(
                conn,
                seeded.workspace_id,
                seeded.icp_key,
                seeded.icp_version,
            )
            assert spec is not None and spec.status is expected_status
            final = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=seeded.gate_id)
            assert final is not None and not final.is_open and final.answer is not None
            assert final.answer.decision == decision
            assert final.answer.expected_subject_sha256 == before.gate.expected_subject_sha256
            assert final.answer.decision_payload == (
                {"revision_request": revision_request} if revision_request is not None else {}
            )
            assert final.answer.answered_by_user_id == seeded.user_id
            assert final.gate.subject_snapshot == original_snapshot
            assert await _answer_count(conn, seeded) == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM fleet_task WHERE kind = 'agent_turn' "
                        "AND work_id = :work_id"
                    ),
                    {
                        "work_id": thread_work_id(
                            workspace_id=seeded.workspace_id,
                            thread_id=seeded.thread_id,
                        )
                    },
                )
            ).scalar_one() == 1

            for mutation in (
                "UPDATE agent_gate_answer SET decision = decision WHERE gate_id = :gate_id",
                "DELETE FROM agent_gate_answer WHERE gate_id = :gate_id",
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with conn.begin_nested():
                        await conn.execute(text(mutation), {"gate_id": seeded.gate_id})

    run_async(scenario())


def test_tampered_unauthorized_and_stale_answers_fail_before_any_receipt(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label="refusals")
            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=seeded.gate_id)
            assert view is not None
            app = _app(conn, seeded)
            async with _client(app) as client:
                cases = (
                    (
                        await _answer(
                            client,
                            seeded,
                            decision="approved",
                            key="bad-digest",
                            digest="f" * 64,
                        ),
                        409,
                        "GATE_SUBJECT_STALE",
                    ),
                    (
                        await _answer(
                            client,
                            seeded,
                            decision="revised",
                            key="missing-revision",
                            digest=view.gate.expected_subject_sha256,
                        ),
                        422,
                        "GATE_REVISION_REQUEST_REQUIRED",
                    ),
                    (
                        await _answer(
                            client,
                            seeded,
                            decision="approved",
                            key="unexpected-revision",
                            digest=view.gate.expected_subject_sha256,
                            revision_request="Smuggled text",
                        ),
                        422,
                        "GATE_REVISION_REQUEST_UNEXPECTED",
                    ),
                    (
                        await _answer(
                            client,
                            seeded,
                            decision="approved",
                            key="unexpected-amount",
                            digest=view.gate.expected_subject_sha256,
                            amount="0",
                        ),
                        422,
                        "GATE_AMOUNT_UNEXPECTED",
                    ),
                )
            for response, status, code in cases:
                assert response.status_code == status, response.text
                assert response.json()["error"]["code"] == code
            assert await _answer_count(conn, seeded) == 0

            other_user = "usr_stage0_slice2_other"
            await seed_principal(
                conn,
                workspace_id=seeded.workspace_id,
                user_id=other_user,
                membership_id=f"wsm_stage0_slice2_{other_user}",
            )
            other_app = _app(conn, seeded, user_id=other_user)
            async with _client(other_app) as client:
                forbidden = await _answer(
                    client,
                    seeded,
                    decision="rejected",
                    key="wrong-human",
                    digest=view.gate.expected_subject_sha256,
                )
            assert forbidden.status_code == 403, forbidden.text
            assert forbidden.json()["error"]["code"] == "GATE_FORBIDDEN"
            assert await _answer_count(conn, seeded) == 0

            # A subject-state change that happens after presentation invalidates the gate even
            # when the client echoes the original digest perfectly.
            await activate_icp_version(
                conn,
                seeded.workspace_id,
                seeded.icp_key,
                seeded.icp_version,
            )
            async with _client(app) as client:
                stale = await _answer(
                    client,
                    seeded,
                    decision="approved",
                    key="stale-draft",
                    digest=view.gate.expected_subject_sha256,
                )
            assert stale.status_code == 409, stale.text
            assert stale.json()["error"]["code"] == "GATE_SUBJECT_STALE"
            assert await _answer_count(conn, seeded) == 0

    run_async(scenario())


@pytest.mark.parametrize(
    ("decision", "digest", "actor", "payload", "message"),
    [
        ("approved", "e" * 64, None, {}, "digest does not match"),
        ("approved", None, "usr_not_the_addressee", {}, "only the gate addressee"),
        ("nonsense", None, None, {}, "decision is not permitted"),
        ("revised", None, None, {}, "requires one trimmed"),
        ("approved", None, None, {}, "answering turn does not exist"),
    ],
)
def test_database_trigger_enforces_gate_authority_for_every_caller(
    tmp_path: Path,
    decision: str,
    digest: str | None,
    actor: str | None,
    payload: dict[str, Any],
    message: str,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed_scenario(conn, tmp_path, label=f"db-{decision}-{message[:3]}")
            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=seeded.gate_id)
            assert view is not None
            with pytest.raises(DBAPIError, match=message):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO agent_gate_answer "
                            "(gate_id, workspace_id, turn_id, action_ref, decision, "
                            " expected_subject_sha256, decision_payload, answered_by_user_id) "
                            "VALUES (:gate_id, :workspace_id, :turn_id, :action_ref, :decision, "
                            " :digest, CAST(:payload AS jsonb), :actor)"
                        ),
                        {
                            "gate_id": seeded.gate_id,
                            "workspace_id": seeded.workspace_id,
                            "turn_id": seeded.presenting_turn_id,
                            "action_ref": derive_turn_action_ref(seeded.presenting_turn_id),
                            "decision": decision,
                            "digest": digest or view.gate.expected_subject_sha256,
                            "payload": json.dumps(payload),
                            "actor": actor or seeded.user_id,
                        },
                    )
            assert await _answer_count(conn, seeded) == 0

    run_async(scenario())
