from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from sqlalchemy import text

from clue_agents import (
    AgentFinalizeEnvelope,
    AgentProfileRegistry,
    AgentRole,
    AgentTurnRequest,
    DelegationRequest,
    DelegationResult,
    FinalizeStatus,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
    ValidatedOperation,
    ValidatedPlan,
    operation_id_for_plan_node,
)
from clue_api.agent_execution_wiring import (
    DbAgentDelegationRuntime,
    DbAgentPlanJournal,
)
from clue_api.agent_registry_wiring import (
    C6_ACTIVE_PROFILE_VERSIONS,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    DurableAgentModelCallHandler,
)
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ExecutionId, new_execution_id
from clue_storage.protocol import ArtifactNotFound
from tests._workspace import seed_project
from tests.agents.conftest import NOW, constitution
from tests.agents.workspace_helpers import make_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_c64_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.objects[key] = (data, media_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise ArtifactNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return key

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", NOW


class _CrashOnce:
    def __init__(self, point: str) -> None:
        self._point = point
        self._raised = False

    async def __call__(self, point: str, **kwargs: Any) -> None:
        del kwargs
        if point == self._point and not self._raised:
            self._raised = True
            raise RuntimeError(f"crash:{point}")


async def _no_crash(point: str, **kwargs: Any) -> None:
    del point, kwargs


def _c64_delegating_registry() -> AgentProfileRegistry:
    """Resolve current pinned authority for the C6.4 delegation durability regression."""

    toolbelt = build_toolbelt(storage=None, gateway=None)
    root = Path(__file__).resolve().parents[2] / "platform" / "agents" / "catalog"
    return AgentProfileRegistry(
        prompts=FolderPromptCatalog((root / "prompts").resolve(strict=True)),
        skills=FolderSkillCatalog((root / "skills").resolve(strict=True)),
        profiles=FolderProfileCatalog((root / "profiles").resolve(strict=True)),
        tools=ToolRegistryAgentCatalog(toolbelt),
        engine_tool_ceiling=frozenset(
            toolbelt.descriptor(name).address for name in toolbelt.names()
        ),
        selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
    )


@pytest.mark.parametrize(
    ("crash_point", "committed_before_retry", "status_before_retry"),
    [
        ("artifact_store", 0, "requested"),
        ("finalize_event", 0, "requested"),
        ("cursor_update", 1, "completed"),
    ],
)
def test_honest_finalize_recovers_each_storage_and_commit_boundary_without_false_success(
    tmp_path: Path,
    require_c64_db: None,
    crash_point: str,
    committed_before_retry: int,
    status_before_retry: str,
) -> None:
    del require_c64_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-c64-finalize", name="C6.4 finalize")
            execution_id = new_execution_id()
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'agent', :hash, :hash)"
                ),
                {
                    "id": execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "hash": "0" * 64,
                },
            )
            factory = conn_session_factory(conn)
            storage = _Storage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            resolved = registry.resolve(AgentRole.HEAD_OF_ABM)

            async def put(body: str, media_type: str = "application/json"):
                return await artifacts.persist_body(
                    workspace_id=project.workspace_id,
                    data=body.encode(),
                    media_type=media_type,
                )

            card = await put('{"card_kind":"stage0_project","project":{}}')
            budget = await put('{"limit_millicents":10000}')
            manifest = await put('{"resources":[]}')
            user = await put("Please finalize", "text/plain")
            final_message = await put("Durable answer", "text/markdown")
            harness = make_workspace(
                tmp_path,
                execution_id=execution_id,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                active_policy=resolved.profile.workspace,
                sink=cast(Any, artifacts),
            )
            harness.lease.backend.write_text_sync(
                "outputs/report.md",
                "durable report",
            )
            request = AgentTurnRequest(
                turn_id=UUID("00000000-0000-0000-0000-000000000647"),
                thread_id="thread-c64-finalize",
                constitution=constitution(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    execution_id=execution_id,
                    workspace_root_id=harness.lease.identity.workspace_root_id,
                    brand_id=project.brand_id,
                    product_id=None,
                    profile_ref=resolved.profile_ref,
                    project_card_ref=card,
                    budget_envelope_ref=budget,
                    resource_manifest_ref=manifest,
                    resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                    focus_refs=(),
                ),
                user_message_artifact_ref=user,
                requested_at=NOW,
            )
            turns = DbAgentTurnJournal(conn_factory=factory)
            await turns.create(request=request, profile=resolved.profile)
            model_calls = DurableAgentModelCallHandler(
                request=request,
                requested_model=resolved.profile.model.model_id,
                initial_sequence=await turns.next_model_call_sequence(turn_id=request.turn_id),
                artifacts=artifacts,
                turns=turns,
            )
            model_call_id = UUID("00000000-0000-0000-0000-000000000652")
            await model_calls.on_chat_model_start(
                {},
                [[HumanMessage(content="Please finalize")]],
                run_id=model_call_id,
            )
            await model_calls.on_llm_end(
                LLMResult(
                    generations=[
                        [
                            ChatGeneration(
                                message=AIMessage(
                                    content="Durable answer",
                                    usage_metadata={
                                        "input_tokens": 12,
                                        "input_token_details": {
                                            "cache_read": 8,
                                            "cache_creation": 2,
                                        },
                                        "output_tokens": 4,
                                        "total_tokens": 16,
                                    },
                                )
                            )
                        ]
                    ],
                    llm_output={"model_name": "answering/model"},
                ),
                run_id=model_call_id,
            )
            call_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT sequence, requested_model, answering_model, status, "
                            "input_tokens, cache_read_input_tokens, "
                            "cache_creation_input_tokens, output_tokens "
                            "FROM agent_model_call WHERE id=:id"
                        ),
                        {"id": model_call_id},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(call_row) == {
                "sequence": 1,
                "requested_model": resolved.profile.model.model_id,
                "answering_model": "answering/model",
                "status": "completed",
                "input_tokens": 12,
                "cache_read_input_tokens": 8,
                "cache_creation_input_tokens": 2,
                "output_tokens": 4,
            }
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_artifact_ref "
                        "WHERE owner_kind='model_call' AND owner_id=:id"
                    ),
                    {"id": model_call_id},
                )
            ).scalar_one() == 2
            outputs = tuple(await harness.lease.backend.snapshot_outputs())
            envelope = AgentFinalizeEnvelope(
                finalization_id=UUID("00000000-0000-0000-0000-000000000648"),
                execution_id=execution_id,
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=final_message,
                output_refs=outputs,
                finalized_at=NOW,
            )
            crashing = AgentFinalizationAuthority(
                lease=harness.lease,
                artifacts=artifacts,
                turns=turns,
                crash_hook=_CrashOnce(crash_point),
                conn_factory=factory,
            )
            with pytest.raises(RuntimeError, match=f"crash:{crash_point}"):
                await crashing.finalize(
                    turn_id=request.turn_id,
                    workspace_id=project.workspace_id,
                    envelope=envelope,
                )
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM agent_finalization_commit WHERE turn_id=:turn"
                            ),
                            {"turn": request.turn_id},
                        )
                    ).scalar_one()
                )
                == committed_before_retry
            )
            current = (
                await conn.execute(
                    text(
                        "SELECT status FROM agent_turn_event "
                        "WHERE turn_id=:turn ORDER BY seq DESC LIMIT 1"
                    ),
                    {"turn": request.turn_id},
                )
            ).scalar_one()
            assert current == status_before_retry

            recovered = AgentFinalizationAuthority(
                lease=harness.lease,
                artifacts=artifacts,
                turns=turns,
                crash_hook=_no_crash,
                conn_factory=factory,
            )
            ref = await recovered.finalize(
                turn_id=request.turn_id,
                workspace_id=project.workspace_id,
                envelope=envelope,
            )
            assert (
                await recovered.finalize(
                    turn_id=request.turn_id,
                    workspace_id=project.workspace_id,
                    envelope=envelope,
                )
                == ref
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT status FROM agent_turn_event "
                        "WHERE turn_id=:turn ORDER BY seq DESC LIMIT 1"
                    ),
                    {"turn": request.turn_id},
                )
            ).scalar_one() == "completed"
            harness.close()

    run_async(scenario())


def test_delegation_is_durable_before_fresh_child_wake_and_rolls_up_reference_result(
    tmp_path: Path,
    require_c64_db: None,
) -> None:
    del tmp_path, require_c64_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-c64-delegate", name="C6.4 delegation")
            parent_execution_id = new_execution_id()
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'agent', :hash, :hash)"
                ),
                {
                    "id": parent_execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "hash": "1" * 64,
                },
            )
            factory = conn_session_factory(conn)
            storage = _Storage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)
            registry = _c64_delegating_registry()
            parent_profile = registry.resolve(AgentRole.HEAD_OF_ABM)
            child_profile = registry.resolve_delegation(
                parent=parent_profile,
                child_role=AgentRole.RESEARCH,
                current_depth=0,
            )

            async def put(body: str):
                return await artifacts.persist_body(
                    workspace_id=project.workspace_id,
                    data=body.encode(),
                    media_type="application/json",
                )

            card = await put('{"card_kind":"account_research","plan":{}}')
            budget = await put('{"limit_millicents":10000}')
            manifest = await put('{"resources":[]}')
            user = await put('{"message":"delegate"}')
            task = await put('{"task":"research account"}')
            child_budget = await put('{"limit_millicents":2000}')
            child_manifest = await put(child_profile.resource_manifest.model_dump_json())
            request = AgentTurnRequest(
                turn_id=UUID("00000000-0000-0000-0000-000000000649"),
                thread_id="thread-c64-delegate",
                constitution=constitution(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    execution_id=parent_execution_id,
                    brand_id=project.brand_id,
                    product_id=None,
                    profile_ref=parent_profile.profile_ref,
                    project_card_ref=card,
                    budget_envelope_ref=budget,
                    resource_manifest_ref=manifest,
                    resource_manifest_sha256=parent_profile.resource_manifest.aggregate_sha256,
                    focus_refs=(),
                ),
                user_message_artifact_ref=user,
                requested_at=NOW,
            )
            turns = DbAgentTurnJournal(conn_factory=factory)
            await turns.create(request=request, profile=parent_profile.profile)

            plan_id = UUID("00000000-0000-0000-0000-000000000650")
            parameter_ref = await put('{"delegation":true}')
            proposal_ref = await put('{"proposal":"delegate"}')
            validated_ref = await put('{"validated":"delegate"}')
            operation_id = operation_id_for_plan_node(
                parent_execution_id,
                "delegate_research",
            )
            plan = ValidatedPlan(
                plan_id=plan_id,
                execution_id=parent_execution_id,
                validated_plan_artifact_ref=validated_ref,
                proposal_sha256=proposal_ref.sha256,
                resource_manifest_sha256=parent_profile.resource_manifest.aggregate_sha256,
                operations=(
                    ValidatedOperation(
                        node_key="delegate_research",
                        operation_id=operation_id,
                        kind="delegation",
                        address=AgentRole.RESEARCH.value,
                        depends_on=(),
                        parameter_artifact_ref=parameter_ref,
                        parameter_sha256=parameter_ref.sha256,
                        estimated_cost_millicents=0,
                        authority_sha256="2" * 64,
                    ),
                ),
                max_parallelism=1,
                estimated_cost_millicents=0,
                budget_limit_millicents=2_000,
                validated_at=NOW,
            )
            plans = DbAgentPlanJournal(conn_factory=factory)
            await plans.record_validated(
                turn_id=request.turn_id,
                workspace_id=project.workspace_id,
                role=AgentRole.HEAD_OF_ABM,
                plan=plan,
                proposal_ref=proposal_ref,
            )

            child_calls = 0

            class _Child:
                async def run(
                    self,
                    *,
                    request: DelegationRequest,
                    child_execution_id: ExecutionId,
                    resolved_profile: object,
                ) -> DelegationResult:
                    nonlocal child_calls
                    child_calls += 1
                    assert resolved_profile == child_profile
                    recorded = (
                        await conn.execute(
                            text("SELECT count(*) FROM agent_delegation WHERE id=:id"),
                            {"id": request.delegation_id},
                        )
                    ).scalar_one()
                    started = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM agent_delegation_event "
                                "WHERE delegation_id=:id AND status='child_started'"
                            ),
                            {"id": request.delegation_id},
                        )
                    ).scalar_one()
                    assert recorded == 1
                    assert started == 1
                    await conn.execute(
                        text(
                            "INSERT INTO execution "
                            "(id, workspace_id, project_id, parent_execution_id, started_by, "
                            " parameter_manifest_hash, pin_manifest_hash) "
                            "VALUES (:id, :workspace, :project, :parent, 'agent', :hash, :hash)"
                        ),
                        {
                            "id": child_execution_id,
                            "workspace": project.workspace_id,
                            "project": project.project_id,
                            "parent": parent_execution_id,
                            "hash": "3" * 64,
                        },
                    )
                    output_ref = await put('{"claim_refs":["claim-1"]}')
                    finalization_ref = await put('{"status":"completed"}')
                    return DelegationResult(
                        delegation_id=request.delegation_id,
                        parent_execution_id=request.parent_execution_id,
                        child_execution_id=child_execution_id,
                        status="completed",
                        output_refs=(output_ref,),
                        finalization_ref=finalization_ref,
                        spend_millicents=875,
                        completed_at=NOW,
                    )

            start_crash = DbAgentDelegationRuntime(
                registry=registry,
                child_runner=_Child(),
                conn_factory=factory,
                crash_hook=_CrashOnce("child_start"),
            )
            delegation_request = DelegationRequest(
                delegation_id=UUID("00000000-0000-0000-0000-000000000651"),
                parent_execution_id=parent_execution_id,
                parent_role=AgentRole.HEAD_OF_ABM,
                subagent_role=AgentRole.RESEARCH,
                task_artifact_ref=task,
                granted_paths=("context", "work"),
                domain_refs=(),
                child_budget_envelope_ref=child_budget,
                resource_manifest_ref=child_manifest,
                resource_manifest_sha256=child_profile.resource_manifest.aggregate_sha256,
                depth=1,
            )
            with pytest.raises(RuntimeError, match="crash:child_start"):
                await start_crash.run(
                    plan_id=plan_id,
                    node_key="delegate_research",
                    operation_id=operation_id,
                    turn_id=request.turn_id,
                    request=delegation_request,
                    parent_profile=parent_profile,
                )
            assert child_calls == 0

            complete_crash = DbAgentDelegationRuntime(
                registry=registry,
                child_runner=_Child(),
                conn_factory=factory,
                crash_hook=_CrashOnce("child_complete"),
            )
            with pytest.raises(RuntimeError, match="crash:child_complete"):
                await complete_crash.run(
                    plan_id=plan_id,
                    node_key="delegate_research",
                    operation_id=operation_id,
                    turn_id=request.turn_id,
                    request=delegation_request,
                    parent_profile=parent_profile,
                )
            assert child_calls == 1

            recovered = DbAgentDelegationRuntime(
                registry=registry,
                child_runner=_Child(),
                conn_factory=factory,
            )
            result = await recovered.run(
                plan_id=plan_id,
                node_key="delegate_research",
                operation_id=operation_id,
                turn_id=request.turn_id,
                request=delegation_request,
                parent_profile=parent_profile,
            )
            assert result.status == "completed"
            assert child_calls == 1
            assert result.spend_millicents == 875
            parent_receipts = await plans.load_receipts(
                execution_id=parent_execution_id,
                workspace_id=project.workspace_id,
            )
            assert len(parent_receipts) == 1
            assert parent_receipts[0].kind == "delegation"
            assert parent_receipts[0].artifact_refs == (
                *result.output_refs,
                result.finalization_ref,
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT spend_millicents FROM agent_delegation_event "
                        "WHERE delegation_id=:id AND status='completed'"
                    ),
                    {"id": delegation_request.delegation_id},
                )
            ).scalar_one() == 875

    run_async(scenario())
