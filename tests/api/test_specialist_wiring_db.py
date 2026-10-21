from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text

from clue_agents import (
    AgentExecutionAdapter,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentProfile,
    AgentRole,
    AgentTurnRequest,
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
    ArtifactRef,
    AssembledAgentContext,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    DelegatedFileGrant,
    DelegationRequest,
    DelegationResult,
    HistoryMessageRef,
    ResolvedAgentProfile,
    ScriptedAgentChatModel,
    SpecialistTaskEnvelope,
    ValidatedPlan,
    WorkspaceRootPolicy,
)
from clue_agents.ports import ExecutionProgress
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.specialist_wiring import FreshWakeSpecialistRunner, SpecialistRuntimeBindings
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ExecutionId, new_execution_id
from clue_storage.protocol import ArtifactNotFound
from tests._workspace import seed_project
from tests.agents.conftest import NOW, constitution
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    rollback_conn,
)


@pytest.fixture
def require_c66_db(request: pytest.FixtureRequest) -> None:
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


class _Models:
    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        return ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {
                                "file_path": "outputs/review-verdict.md",
                                "content": "# Verdict\n\nrevise: missing evidence",
                            },
                            "id": "write-review-c66",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_turn",
                            "args": {
                                "status": "completed",
                                "user_message": "The durable review verdict is ready.",
                            },
                            "id": "finalize-review-c66",
                            "type": "tool_call",
                        }
                    ],
                ),
            )
        )


class _Contexts:
    def __init__(self) -> None:
        self.histories: list[tuple[object, ...]] = []

    async def assemble(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> AssembledAgentContext:
        del profile
        self.histories.append(tuple(history))
        layers = tuple(
            ContextLayerManifest(
                layer=layer,
                token_count=0 if layer is ContextLayer.L6_CONVERSATION else 1,
            )
            for layer in ContextLayer
        )
        return AssembledAgentContext(
            manifest=ContextBundleManifest(
                context_bundle_id=UUID("00000000-0000-0000-0000-000000000699"),
                execution_id=request.constitution.execution_id,
                schema_version="1",
                layers=layers,
                aggregate_sha256="9" * 64,
                assembled_at=NOW,
            ),
            messages=(HumanMessage(content="Use only the exact delegated task artifact."),),
        )


class _Workspaces:
    def __init__(self, factory: AgentWorkspaceFactory) -> None:
        self.factory = factory
        self.leases: list[AgentWorkspaceLease] = []
        self._last: dict[str, Any] = {}

    async def acquire_restored(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        execution_id: ExecutionId,
        resolved_profile: ResolvedAgentProfile,
    ) -> AgentWorkspaceLease:
        self._last = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "thread_id": thread_id,
            "execution_id": execution_id,
            "policy": resolved_profile.profile.workspace,
        }
        lease = self.factory.create(**self._last)
        self.leases.append(lease)
        return lease

    async def release_saved(self, lease: AgentWorkspaceLease) -> None:
        await self.factory.release_saved(lease)

    def reopen(self) -> AgentWorkspaceLease:
        """Take a fresh lease over the child thread, after the run released its own."""

        return self.factory.acquire(**self._last)


class _Spend:
    async def spend_millicents(self, **kwargs: Any) -> int:
        del kwargs
        return 125


class _ChildExecution(AgentExecutionAdapter):
    def __init__(
        self,
        execution_id: ExecutionId,
        *,
        turn_id: UUID,
        workspace_id: str,
    ) -> None:
        self.execution_id = execution_id
        self.turn_id = turn_id
        self.workspace_id = workspace_id
        self.authority: Any = None
        self.recovered: dict[str, object] = {}

    def bind_finalization_authority(self, authority: object) -> None:
        self.authority = authority

    async def validate_plan(self, *, plan: AgentPlan, constitution: object) -> ValidatedPlan:
        del plan, constitution
        raise AssertionError("reviewer fixture does not invoke platform tools")

    def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        del plan
        raise AssertionError("reviewer fixture does not execute a plan")

    async def delegate(self, *, request: DelegationRequest) -> DelegationResult:
        del request
        raise AssertionError("specialists cannot delegate")

    async def finalize(self, *, envelope: AgentFinalizeEnvelope) -> ArtifactRef:
        ref = await self.authority.finalize(
            turn_id=self.turn_id,
            workspace_id=self.workspace_id,
            envelope=envelope,
        )
        self.recovered = {
            "finalization_status": envelope.status.value,
            "finalization_ref": ref,
        }
        return ref

    def checkpointer(
        self,
        *,
        execution_id: ExecutionId,
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]:
        assert execution_id == self.execution_id

        @asynccontextmanager
        async def opened() -> AsyncIterator[BaseCheckpointSaver[str]]:
            yield InMemorySaver()

        return opened()

    async def recover(self, *, execution_id: ExecutionId) -> Mapping[str, object]:
        assert execution_id == self.execution_id
        return self.recovered


@pytest.mark.parametrize("authorized_rounds", [None, 200])
def test_fresh_wake_reviewer_has_no_history_and_returns_only_durable_refs(
    tmp_path: Path,
    require_c66_db: None,
    monkeypatch: pytest.MonkeyPatch,
    authorized_rounds: int | None,
) -> None:
    del require_c66_db
    from clue_api import specialist_wiring

    real_runtime = specialist_wiring.DeepAgentTurnRuntime
    observed_rounds: list[int] = []

    def capture_runtime(**kwargs: Any):
        observed_rounds.append(kwargs["max_rounds"])
        return real_runtime(**kwargs)

    monkeypatch.setattr(specialist_wiring, "DeepAgentTurnRuntime", capture_runtime)

    async def bindings(*args: Any) -> SpecialistRuntimeBindings:
        return SpecialistRuntimeBindings(max_model_rounds=authorized_rounds)

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-c66-reviewer", name="C6.6 reviewer")
            parent_execution_id = new_execution_id()
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) VALUES "
                    "(:id, :workspace, :project, 'agent', :sha, :sha)"
                ),
                {
                    "id": parent_execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "sha": "1" * 64,
                },
            )
            conn_factory = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=_Storage(),
                conn_factory=conn_factory,
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            head = registry.resolve(AgentRole.HEAD_OF_ABM)
            reviewer = registry.resolve_delegation(
                parent=head,
                child_role=AgentRole.REVIEWER,
                current_depth=0,
            )

            async def put(
                body: str,
                media_type: str = "application/json",
            ) -> ArtifactRef:
                return await artifacts.persist_body(
                    workspace_id=project.workspace_id,
                    data=body.encode(),
                    media_type=media_type,
                )

            card = await put('{"card_kind":"stage0_project","project":{}}')
            parent_budget = await put('{"limit_millicents":5000}')
            parent_manifest = await put(head.resource_manifest.model_dump_json())
            user = await put('{"message":"review the exemplar"}')
            exemplar = await put(
                "# Exemplar\n\nExact canonical copy.",
                "text/markdown",
            )
            task_value = SpecialistTaskEnvelope(
                role=AgentRole.REVIEWER,
                goal="Review one exemplar.",
                instructions="Check evidence and slot fit without editing.",
                file_grants=(
                    DelegatedFileGrant(
                        source_path="outputs/content-exemplar.md",
                        materialized_path="context/delegated/00-content-exemplar.md",
                        artifact_ref=exemplar,
                    ),
                ),
                required_output_path="outputs/review-verdict.md",
            )
            task = await put(
                task_value.model_dump_json(exclude_none=False),
                "application/vnd.clue.specialist-task+json",
            )
            child_budget = await put('{"limit_millicents":1000}')
            child_manifest = await put(reviewer.resource_manifest.model_dump_json())
            parent_request = AgentTurnRequest(
                turn_id=UUID("00000000-0000-0000-0000-000000000697"),
                thread_id="thread-c66-parent",
                constitution=constitution(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    execution_id=parent_execution_id,
                    brand_id=project.brand_id,
                    product_id=None,
                    profile_ref=head.profile_ref,
                    project_card_ref=card,
                    budget_envelope_ref=parent_budget,
                    resource_manifest_ref=parent_manifest,
                    resource_manifest_sha256=head.resource_manifest.aggregate_sha256,
                    focus_refs=(),
                ),
                user_message_artifact_ref=user,
                requested_at=NOW,
            )
            child_execution_id = new_execution_id()
            delegation = DelegationRequest(
                delegation_id=UUID("00000000-0000-0000-0000-000000000696"),
                parent_execution_id=parent_execution_id,
                parent_role=AgentRole.HEAD_OF_ABM,
                subagent_role=AgentRole.REVIEWER,
                task_artifact_ref=task,
                granted_paths=("context/delegated/00-content-exemplar.md",),
                domain_refs=(),
                child_budget_envelope_ref=child_budget,
                resource_manifest_ref=child_manifest,
                resource_manifest_sha256=reviewer.resource_manifest.aggregate_sha256,
                depth=1,
            )
            source = tmp_path / "source"
            home = tmp_path / "home"
            source.mkdir(mode=0o700)
            home.mkdir(mode=0o700)
            prepared = WorkspaceRootPolicy(
                configured_root=tmp_path / "runtime",
                source_root=source,
                home_root=home,
            ).prepare()
            workspace_factory = AgentWorkspaceFactory(
                prepared_root=prepared,
                artifact_sink=artifacts,
            )
            workspaces = _Workspaces(workspace_factory)
            contexts = _Contexts()
            child_executions: list[_ChildExecution] = []

            def build_child_execution(
                *,
                request: AgentTurnRequest,
                resolved_profile: ResolvedAgentProfile,
                budget_limit_millicents: int,
            ) -> _ChildExecution:
                del resolved_profile, budget_limit_millicents
                child = _ChildExecution(
                    child_execution_id,
                    turn_id=request.turn_id,
                    workspace_id=project.workspace_id,
                )
                child_executions.append(child)
                return child

            runner = FreshWakeSpecialistRunner(
                parent_request=parent_request,
                profiles=registry,
                models=_Models(),
                turns=DbAgentTurnJournal(conn_factory=conn_factory),
                artifacts=artifacts,
                tools=build_toolbelt(storage=None, gateway=None),
                contexts=contexts,
                workspaces=workspaces,
                execution_factory=build_child_execution,
                spend=_Spend(),
                bindings=bindings,
                conn_factory=conn_factory,
            )

            result = await runner.run(
                request=delegation,
                child_execution_id=child_execution_id,
                resolved_profile=reviewer,
            )

            assert contexts.histories == [()]
            assert observed_rounds == [authorized_rounds or reviewer.profile.max_model_rounds]
            assert result.status == "completed"
            assert len(child_executions) == 1
            assert result.spend_millicents == 125
            assert len(result.output_refs) == 1
            assert await artifacts.read(result.output_refs[0]) == (
                b"# Verdict\n\nrevise: missing evidence"
            )
            assert (
                await workspaces.reopen().backend.read_text(
                    "context/delegated/00-content-exemplar.md"
                )
                == "# Exemplar\n\nExact canonical copy."
            )
            assert result.domain_refs == ()
            assert (
                await conn.execute(
                    text("SELECT parent_execution_id FROM execution WHERE id=:id"),
                    {"id": child_execution_id},
                )
            ).scalar_one() == parent_execution_id
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_thread_message WHERE thread_id=:thread"),
                    {"thread": f"delegation-{delegation.delegation_id}"},
                )
            ).scalar_one() == 0
            workspace_factory.close()

    run_async(scenario())
