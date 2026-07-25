"""C5.3 durable executor, fencing, and abandoned-attempt recovery."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import ExecutionRunEventWriter, StorageParameterArtifactStore, build_tool_invoker
from clue_api.execution_wiring import StorageExecutionParameterStore
from clue_config import Settings
from clue_core import ExecutionId
from clue_db import ConnFactory
from clue_execution import (
    BarrierNode,
    CallablePinResolver,
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    EffectiveEnvelope,
    ExecutionConflict,
    ExecutionEventType,
    ExecutionStatus,
    GateNode,
    GateResumeCondition,
    JournalCrashHook,
    LostExecutionLease,
    MapNode,
    ParameterBinding,
    PinRequest,
    PinResolverRegistry,
    RecipeDefinition,
    RecipeExecutor,
    RecipeGraph,
    RecipeLifecycle,
    RecipeScopeType,
    ResourceObservation,
    ToolNode,
)
from clue_fleet import (
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    release_work_lease,
)
from clue_toolbelt import (
    InvocationCrashHook,
    JournalParameterPolicy,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolResult,
)
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn
from tests.toolbelt.conftest import InMemoryStore

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


class _Input(ToolInput):
    value: int


class _Output(ToolOutput):
    echoed: int


class _CertifiedEcho(Tool):
    name = "executor_echo"
    version = "1"
    input_model = _Input
    output_model = _Output
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="test echo value",
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("value",))

    def __init__(self) -> None:
        self.calls = 0
        self.values: list[int] = []

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, _Input)
        self.calls += 1
        self.values.append(inputs.value)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"echoed": inputs.value},
        )


def _factory(conn: AsyncConnection) -> ConnFactory:
    lock = asyncio.Lock()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        # The production factory gives concurrent nodes independent pooled
        # connections. This rollback-scoped test intentionally shares one connection,
        # so serialize its nested savepoints while preserving executor concurrency.
        async with lock:
            nested = await conn.begin_nested()
            try:
                yield conn
            except BaseException:
                await nested.rollback()
                raise
            else:
                await nested.commit()

    return factory


async def _runtime(
    conn: AsyncConnection,
    *,
    crash_hook: InvocationCrashHook | None = None,
    journal_crash_hook: JournalCrashHook | None = None,
    executor_crash_hook: Any | None = None,
    graph: RecipeGraph | None = None,
    compatibility_manifest: CompatibilityManifest | None = None,
    parameter_schema: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    max_nodes: int = 4,
    max_depth: int = 1,
    max_fanout: int = 2,
    interaction: bool = False,
    storage: _MemoryStorage | None = None,
    controls: Any | None = None,
    pre_satisfied_nodes: dict[str, dict[str, Any]] | None = None,
) -> tuple[ExecutionId, RecipeExecutor, _CertifiedEcho, LeaseGeneration]:
    workspace_id = await seed_workspace(conn, "ws-c5-executor")
    factory = _factory(conn)
    tool = _CertifiedEcho()
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    descriptor = tool.descriptor
    tool_pin = PinRequest(kind="tool", key=tool.name, version=tool.version)
    pin_registry = PinResolverRegistry()

    async def observe(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation:
        return ResourceObservation(
            version=tool.version,
            digest=descriptor.input_schema_sha256,
            status="active",
        )

    pin_registry.register(CallablePinResolver(kind="tool", loader=observe))
    compatibility = CompatibilityLoader(pin_registry)
    if interaction:
        resolved_graph = RecipeGraph(
            nodes=(
                GateNode(
                    node_key="interactions",
                    ordinal=0,
                    authority="human",
                    resume_condition=GateResumeCondition.INPUT_AVAILABLE,
                    dynamic_tool_allowlist=(descriptor.address,),
                    max_children=2,
                    requirements=(tool_pin,),
                ),
                BarrierNode(
                    node_key="complete",
                    ordinal=1,
                    dependencies=("interactions",),
                ),
            ),
            tool_allowlist=(descriptor.address,),
            authority_allowlist=("human",),
        )
        resolved_compatibility = CompatibilityManifest(nodes={"interactions": (tool_pin,)})
        resolved_parameters = parameters if parameters is not None else {}
        resolved_schema = parameter_schema or {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    else:
        resolved_graph = graph or RecipeGraph(
            nodes=(
                ToolNode(
                    node_key="echo",
                    ordinal=0,
                    tool_name=tool.name,
                    tool_version=tool.version,
                    input_schema_sha256=descriptor.input_schema_sha256,
                    output_schema_sha256=descriptor.output_schema_sha256,
                    bindings={"value": ParameterBinding(kind="parameter", name="value")},
                    requirements=(tool_pin,),
                ),
            ),
            tool_allowlist=(descriptor.address,),
        )
        resolved_compatibility = compatibility_manifest or CompatibilityManifest(
            nodes={"echo": (tool_pin,)}
        )
        resolved_parameters = parameters if parameters is not None else {"value": 7}
        resolved_schema = parameter_schema or {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        }
    definition = RecipeDefinition(
        recipe_key="executor-test",
        scope_type=RecipeScopeType.WORKSPACE,
        workspace_id=workspace_id,
        version=1,
        executor_protocol=1,
        parameter_schema=resolved_schema,
        graph=resolved_graph,
        compatibility=resolved_compatibility,
        max_nodes=max_nodes,
        max_depth=max_depth,
        max_fanout=max_fanout,
        created_by="human",
    )
    repository = DbRecipeRepository(conn_factory=factory)
    revision = await repository.propose(definition)
    lifecycle = RecipeLifecycle(
        repository=repository,
        tool_catalog=registry,
        compatibility_loader=compatibility,
    )
    promoted = await lifecycle.promote(
        revision,
        context=CompatibilityContext(workspace_id=workspace_id),
        actor="human",
    )
    assert promoted.promoted, promoted.graph_validation.issues

    storage = storage or _MemoryStorage()
    artifact_store = StorageParameterArtifactStore(
        storage=storage,
        conn_factory=factory,
    )
    parameters = StorageExecutionParameterStore(artifact_store)
    artifact_key, digest = await parameters.snapshot(
        workspace_id=workspace_id,
        parameters=resolved_parameters,
    )
    journal = DbExecutionJournal(
        transport=ExecutionRunEventWriter(),
        **({"crash_hook": journal_crash_hook} if journal_crash_hook is not None else {}),
    )
    starter = DbExecutionStarter(
        conn_factory=factory,
        recipes=DbRecipeReader(conn_factory=factory),
        compatibility=compatibility,
        journal=journal,
    )
    start = await starter.start(
        workspace_id=workspace_id,
        recipe_revision_id=revision.recipe_revision_id,
        parameters=resolved_parameters,
        parameter_artifact_key=artifact_key,
        parameter_manifest_hash=digest,
        actor="human",
        pre_satisfied_nodes=pre_satisfied_nodes,
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=InMemoryStore(),
        storage=storage,
        settings=Settings(_env_file=None),
        conn_factory=factory,
        crash_hook=crash_hook,
        journal_crash_hook=journal_crash_hook,
    )
    executor = RecipeExecutor(
        conn_factory=factory,
        recipes=DbRecipeReader(conn_factory=factory),
        compatibility=compatibility,
        journal=journal,
        parameters=parameters,
        tool_invoker=invoker,
        controls=controls,
        **({"crash_hook": executor_crash_hook} if executor_crash_hook is not None else {}),
    )
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(start.execution_id),
        worker_id="worker",
        ttl=timedelta(seconds=60),
    )
    assert lease is not None
    return start.execution_id, executor, tool, LeaseGeneration(lease.generation)


def test_starter_materializes_pre_satisfied_nodes_as_born_complete() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                pre_satisfied_nodes={"echo": {"echoed": 7, "pre_satisfied": True}},
            )
            result = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert result.status is ExecutionStatus.COMPLETED
            assert tool.calls == 0
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT e.event_type, a.worker_id
                        FROM execution_event e
                        LEFT JOIN execution_attempt a ON a.id = e.attempt_id
                        WHERE e.execution_id = :id AND e.node_id IS NOT NULL
                        ORDER BY e.seq
                        """
                    ),
                    {"id": execution_id},
                )
            ).all()
            assert rows == [
                ("node.scheduled", None),
                ("node.started", "pre_satisfied"),
                ("node.completed", "pre_satisfied"),
            ]

    run_async(scenario())


def test_executor_completes_recipe_and_stamps_lease_generation() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(conn)
            result = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert result.status is ExecutionStatus.COMPLETED
            assert result.completed_node_keys == ("echo",)
            assert tool.calls == 1
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT status, active_node_count, lease_generation
                        FROM execution_cursor WHERE execution_id = :id
                        """
                    ),
                    {"id": execution_id},
                )
            ).one()
            assert tuple(row) == ("completed", 0, generation)

    run_async(scenario())


def test_lost_lease_generation_cannot_project_execution_state() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(conn)
            await release_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id="worker",
                generation=generation,
            )
            with pytest.raises(LostExecutionLease):
                await executor.execute(
                    execution_id,
                    worker_id="worker",
                    lease_generation=generation,
                )
            assert tool.calls == 0

    run_async(scenario())


def test_bounded_interaction_child_is_durable_replayable_and_human_closable() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                interaction=True,
            )
            opened = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert opened.status is ExecutionStatus.AWAITING_INPUT

            appended = await executor.append_interaction_tool(
                execution_id=execution_id,
                workspace_id="ws-c5-executor",
                slot_key="interactions",
                node_key="answer-001",
                tool_name=tool.name,
                tool_version=tool.version,
                inputs={"value": 17},
                actor="human",
            )
            with pytest.raises(ExecutionConflict, match="durable parameter artifact"):
                await executor.invoke_interaction_tool(
                    appended,
                    inputs={"value": 18},
                    actor="human",
                )
            with pytest.raises(ExecutionConflict, match="actor differs"):
                await executor.invoke_interaction_tool(
                    appended,
                    inputs={"value": 17},
                    actor="agent",
                )
            first = await executor.invoke_interaction_tool(
                appended,
                inputs={"value": 17},
                actor="human",
            )
            replayed_append = await executor.append_interaction_tool(
                execution_id=execution_id,
                workspace_id="ws-c5-executor",
                slot_key="interactions",
                node_key="answer-001",
                tool_name=tool.name,
                tool_version=tool.version,
                inputs={"value": 17},
                actor="human",
            )
            replayed = await executor.invoke_interaction_tool(
                replayed_append,
                inputs={"value": 17},
                actor="human",
            )
            assert first.references == replayed.references == {"echoed": 17}
            assert replayed.replayed is True
            assert tool.calls == 1
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT n.declared_by_node_id, n.parameter_artifact_key,
                                   n.parameter_sha256, n.definition_json,
                                   e.payload_json
                            FROM execution_node n
                            JOIN execution_event e ON e.node_id = n.id
                            WHERE n.execution_id = :execution_id
                              AND n.node_key = 'answer-001'
                              AND e.event_type = 'node.completed'
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["declared_by_node_id"] is not None
            assert row["parameter_artifact_key"]
            assert len(row["parameter_sha256"]) == 64
            assert row["definition_json"]["actor"] == "human"
            assert "value" not in row["definition_json"]
            assert row["payload_json"]["result"]["references"] == {"echoed": 17}

            with pytest.raises(ValueError, match="outside this workspace"):
                await executor.append_interaction_tool(
                    execution_id=execution_id,
                    workspace_id="other-workspace",
                    slot_key="interactions",
                    node_key="foreign",
                    tool_name=tool.name,
                    tool_version=tool.version,
                    inputs={"value": 99},
                    actor="human",
                )

            await executor.decide_gate(
                execution_id=execution_id,
                node_key="interactions",
                actor="human",
                decision="stage0_complete",
            )
            completed = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert completed.status is ExecutionStatus.COMPLETED
            assert completed.completed_node_keys == (
                "answer-001",
                "complete",
                "interactions",
            )
            terminal_replay = await executor.append_interaction_tool(
                execution_id=execution_id,
                workspace_id="ws-c5-executor",
                slot_key="interactions",
                node_key="answer-001",
                tool_name=tool.name,
                tool_version=tool.version,
                inputs={"value": 17},
                actor="human",
            )
            replayed_after_completion = await executor.invoke_interaction_tool(
                terminal_replay,
                inputs={"value": 17},
                actor="human",
            )
            assert replayed_after_completion.replayed is True
            assert tool.calls == 1

    run_async(scenario())


def test_interaction_child_recovers_after_domain_commit_without_duplicate_effect() -> None:
    async def scenario() -> None:
        crashed = False

        async def crash(
            point: str,
            *,
            context: ToolContext,
            start: Any,
        ) -> None:
            del context, start
            nonlocal crashed
            if point == "after_domain_commit" and not crashed:
                crashed = True
                raise asyncio.CancelledError

        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                interaction=True,
                crash_hook=crash,
            )
            opened = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert opened.status is ExecutionStatus.AWAITING_INPUT
            appended = await executor.append_interaction_tool(
                execution_id=execution_id,
                workspace_id="ws-c5-executor",
                slot_key="interactions",
                node_key="crash-answer",
                tool_name=tool.name,
                tool_version=tool.version,
                inputs={"value": 23},
                actor="human",
            )
            with pytest.raises(asyncio.CancelledError):
                await executor.invoke_interaction_tool(
                    appended,
                    inputs={"value": 23},
                    actor="human",
                )
            recovered = await executor.invoke_interaction_tool(
                appended,
                inputs={"value": 23},
                actor="human",
            )
            assert recovered.references == {"echoed": 23}
            assert tool.calls == 1
            attempts = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*) FROM execution_attempt
                            WHERE execution_id = :execution_id
                              AND node_id = :node_id
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "node_id": appended.node_id,
                        },
                    )
                ).scalar_one()
            )
            assert attempts == 2

    run_async(scenario())


def test_worker_recovers_an_appended_interaction_before_invocation() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                interaction=True,
            )
            opened = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert opened.status is ExecutionStatus.AWAITING_INPUT
            await executor.append_interaction_tool(
                execution_id=execution_id,
                workspace_id="ws-c5-executor",
                slot_key="interactions",
                node_key="worker-answer",
                tool_name=tool.name,
                tool_version=tool.version,
                inputs={"value": 29},
                actor="agent",
            )
            recovered = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert recovered.status is ExecutionStatus.AWAITING_INPUT
            assert recovered.completed_node_keys == ("worker-answer",)
            assert tool.values == [29]

    run_async(scenario())


def test_erased_interaction_body_is_a_tombstone_and_cannot_be_recovered() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            storage = _MemoryStorage()
            execution_id, executor, _tool, generation = await _runtime(
                conn,
                interaction=True,
                storage=storage,
            )
            opened = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert opened.status is ExecutionStatus.AWAITING_INPUT
            await executor.append_interaction_tool(
                execution_id=execution_id,
                workspace_id="ws-c5-executor",
                slot_key="interactions",
                node_key="private-answer",
                tool_name="executor_echo",
                tool_version="1",
                inputs={"value": 41},
                actor="human",
            )
            artifact_key = str(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT parameter_artifact_key
                            FROM execution_node
                            WHERE execution_id = :execution_id
                              AND node_key = 'private-answer'
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                ).scalar_one()
            )
            artifact_store = StorageParameterArtifactStore(
                storage=storage,
                conn_factory=_factory(conn),
            )
            assert await artifact_store.erase_parameter(
                workspace_id="ws-c5-executor",
                execution_id=execution_id,
                artifact_key=artifact_key,
            )
            with pytest.raises(ValueError, match="erased or missing"):
                await executor.execute(
                    execution_id,
                    worker_id="worker",
                    lease_generation=generation,
                )
            journal_text = str(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT jsonb_agg(payload_json)::text
                            FROM execution_event
                            WHERE execution_id = :execution_id
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                ).scalar_one()
            )
            assert '"value": 41' not in journal_text

    run_async(scenario())


def test_after_domain_commit_crash_recovers_without_duplicate_tool_effect() -> None:
    async def scenario() -> None:
        crashed = False

        async def crash(
            point: str,
            *,
            context: ToolContext,
            start: Any,
        ) -> None:
            nonlocal crashed
            if point == "after_domain_commit" and not crashed:
                crashed = True
                raise asyncio.CancelledError

        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                crash_hook=crash,
            )
            with pytest.raises(asyncio.CancelledError):
                await executor.execute(
                    execution_id,
                    worker_id="worker",
                    lease_generation=generation,
                )
            recovered = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert recovered.status is ExecutionStatus.COMPLETED
            assert tool.calls == 1
            events = [
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            """
                            SELECT event_type FROM execution_event
                            WHERE execution_id = :id ORDER BY seq
                            """
                        ),
                        {"id": execution_id},
                    )
                ).all()
            ]
            assert events.count(ExecutionEventType.NODE_ABANDONED.value) == 1
            assert events.count(ExecutionEventType.NODE_COMPLETED.value) == 1
            assert events.count(ExecutionEventType.NODE_STARTED.value) == 2

    run_async(scenario())


@pytest.mark.parametrize(
    ("crash_point", "expect_abandoned"),
    (
        ("after_attempt_start", True),
        ("before_tool", True),
        ("after_completion_event", False),
    ),
)
def test_tool_boundary_crashes_recover_truthfully(
    crash_point: str,
    expect_abandoned: bool,
) -> None:
    async def scenario() -> None:
        crashed = False

        async def crash(
            point: str,
            *,
            context: ToolContext,
            start: Any,
        ) -> None:
            del context, start
            nonlocal crashed
            if point == crash_point and not crashed:
                crashed = True
                raise asyncio.CancelledError

        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                crash_hook=crash,
            )
            with pytest.raises(asyncio.CancelledError):
                await executor.execute(
                    execution_id,
                    worker_id="worker",
                    lease_generation=generation,
                )
            recovered = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert recovered.status is ExecutionStatus.COMPLETED
            assert tool.calls == 1
            abandoned = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*) FROM execution_event
                            WHERE execution_id = :id AND event_type = 'node.abandoned'
                            """
                        ),
                        {"id": execution_id},
                    )
                ).scalar_one()
            )
            assert abandoned == int(expect_abandoned)

    run_async(scenario())


@pytest.mark.parametrize("crash_point", ("after_event_insert", "after_cursor_update"))
def test_atomic_event_cursor_crash_rolls_back_and_recovers(crash_point: str) -> None:
    class _Crash:
        armed = False
        crashed = False

        async def __call__(
            self,
            point: str,
            execution_id: ExecutionId,
            node_id: Any,
            attempt_id: Any,
        ) -> None:
            del execution_id, attempt_id
            if self.armed and node_id is not None and point == crash_point and not self.crashed:
                self.crashed = True
                raise asyncio.CancelledError

    async def scenario() -> None:
        hook = _Crash()
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                journal_crash_hook=hook,
            )
            hook.armed = True
            with pytest.raises(asyncio.CancelledError):
                await executor.execute(
                    execution_id,
                    worker_id="worker",
                    lease_generation=generation,
                )
            recovered = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert recovered.status is ExecutionStatus.COMPLETED
            assert tool.calls == 1

    run_async(scenario())


def test_human_gate_is_actor_bound_idempotent_and_resumable() -> None:
    async def scenario() -> None:
        crashed = False

        async def crash(
            point: str,
            execution_id: ExecutionId,
            node_id: Any,
        ) -> None:
            del execution_id, node_id
            nonlocal crashed
            if point == "gate_decided" and not crashed:
                crashed = True
                raise asyncio.CancelledError

        graph = RecipeGraph(
            nodes=(
                GateNode(
                    node_key="approve",
                    ordinal=0,
                    authority="human",
                    resume_condition=GateResumeCondition.HUMAN_DECISION,
                ),
            ),
            authority_allowlist=("human",),
        )
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, executor, tool, generation = await _runtime(
                conn,
                graph=graph,
                compatibility_manifest=CompatibilityManifest(),
                parameter_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                parameters={},
                executor_crash_hook=crash,
            )
            waiting = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert waiting.status is ExecutionStatus.AWAITING_INPUT
            with pytest.raises(ExecutionConflict):
                await executor.decide_gate(
                    execution_id=execution_id,
                    node_key="approve",
                    actor="agent",
                    decision="approved",
                )
            with pytest.raises(asyncio.CancelledError):
                await executor.decide_gate(
                    execution_id=execution_id,
                    node_key="approve",
                    actor="human",
                    decision="approved",
                )
            # A fresh operation expressing the same terminal decision is a no-op; a
            # contradictory decision fails loud.
            await executor.decide_gate(
                execution_id=execution_id,
                node_key="approve",
                actor="human",
                decision="approved",
            )
            with pytest.raises(ExecutionConflict):
                await executor.decide_gate(
                    execution_id=execution_id,
                    node_key="approve",
                    actor="human",
                    decision="rejected",
                )
            completed = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert completed.status is ExecutionStatus.COMPLETED
            assert tool.calls == 0

    run_async(scenario())


def test_bounded_map_expands_in_stable_source_order_and_executes_once() -> None:
    async def scenario() -> None:
        crashed = False

        async def crash(
            point: str,
            execution_id: ExecutionId,
            node_id: Any,
        ) -> None:
            del execution_id, node_id
            nonlocal crashed
            if point == "map_expanded" and not crashed:
                crashed = True
                raise asyncio.CancelledError

        async with rollback_conn(seed_pack=False) as conn:
            descriptor_tool = _CertifiedEcho()
            descriptor = descriptor_tool.descriptor
            tool_pin = PinRequest(
                kind="tool",
                key=descriptor.name,
                version=descriptor.version,
            )
            graph = RecipeGraph(
                nodes=(
                    MapNode(
                        node_key="fanout",
                        ordinal=0,
                        source=ParameterBinding(kind="parameter", name="items"),
                        item_parameter="item",
                        max_items=3,
                        template=(
                            ToolNode(
                                node_key="echo",
                                ordinal=0,
                                tool_name=descriptor.name,
                                tool_version=descriptor.version,
                                input_schema_sha256=descriptor.input_schema_sha256,
                                output_schema_sha256=descriptor.output_schema_sha256,
                                bindings={
                                    "value": ParameterBinding(
                                        kind="parameter",
                                        name="item",
                                    )
                                },
                                requirements=(tool_pin,),
                            ),
                        ),
                    ),
                ),
                tool_allowlist=(descriptor.address,),
            )
            execution_id, executor, tool, generation = await _runtime(
                conn,
                graph=graph,
                compatibility_manifest=CompatibilityManifest(nodes={"fanout": (tool_pin,)}),
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"type": "integer"},
                        }
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                },
                parameters={"items": [3, 1, 2]},
                max_nodes=4,
                max_depth=2,
                max_fanout=3,
                executor_crash_hook=crash,
            )
            with pytest.raises(asyncio.CancelledError):
                await executor.execute(
                    execution_id,
                    worker_id="worker",
                    lease_generation=generation,
                )
            completed = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert completed.status is ExecutionStatus.COMPLETED
            assert tool.calls == 3
            assert tool.values == [1, 2, 3]
            assert completed.completed_node_keys == (
                "fanout",
                "fanout.000000.echo",
                "fanout.000001.echo",
                "fanout.000002.echo",
            )

    run_async(scenario())


def test_tightened_runtime_envelope_blocks_future_map_expansion() -> None:
    class _EnvelopeControls:
        async def effective_envelope(self, execution_id: ExecutionId) -> EffectiveEnvelope:
            del execution_id
            return EffectiveEnvelope(max_nodes=2, max_depth=1, max_fanout=1)

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            descriptor = _CertifiedEcho().descriptor
            tool_pin = PinRequest(
                kind="tool",
                key=descriptor.name,
                version=descriptor.version,
            )
            graph = RecipeGraph(
                nodes=(
                    MapNode(
                        node_key="fanout",
                        ordinal=0,
                        source=ParameterBinding(kind="parameter", name="items"),
                        item_parameter="item",
                        max_items=3,
                        template=(
                            ToolNode(
                                node_key="echo",
                                ordinal=0,
                                tool_name=descriptor.name,
                                tool_version=descriptor.version,
                                input_schema_sha256=descriptor.input_schema_sha256,
                                output_schema_sha256=descriptor.output_schema_sha256,
                                bindings={
                                    "value": ParameterBinding(
                                        kind="parameter",
                                        name="item",
                                    )
                                },
                                requirements=(tool_pin,),
                            ),
                        ),
                    ),
                ),
                tool_allowlist=(descriptor.address,),
            )
            execution_id, executor, tool, generation = await _runtime(
                conn,
                graph=graph,
                compatibility_manifest=CompatibilityManifest(nodes={"fanout": (tool_pin,)}),
                parameter_schema={
                    "type": "object",
                    "properties": {"items": {"type": "array", "items": {"type": "integer"}}},
                    "required": ["items"],
                    "additionalProperties": False,
                },
                parameters={"items": [1, 2, 3]},
                max_nodes=4,
                max_depth=2,
                max_fanout=3,
                controls=_EnvelopeControls(),
            )
            result = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=generation,
            )
            assert result.status is ExecutionStatus.FAILED
            assert tool.calls == 0
            assert (
                await conn.execute(
                    text(
                        """
                        SELECT count(*) FROM execution_node
                        WHERE execution_id = :id
                          AND node_key LIKE 'fanout.%'
                        """
                    ),
                    {"id": execution_id},
                )
            ).scalar_one() == 0

    run_async(scenario())
