"""Real-process C5.3 graph crash harness.

The parent test invokes this module in three fresh processes: prepare, SIGKILL immediately after a
certified tool's domain commit, then restart. The tool records both its invocation count and its
idempotent domain effect in Postgres so the parent can distinguish a replayed result from a second
provider/domain call.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_config import Settings
from clue_core import ExecutionId
from clue_db import db_lifespan, transaction
from clue_execution import (
    CallablePinResolver,
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
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
from clue_fleet import WorkId, acquire_work_lease
from clue_storage import FsStorage
from clue_toolbelt import (
    DbIdempotencyStore,
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


class _Input(ToolInput):
    value: int


class _Output(ToolOutput):
    effect_id: str


class _EffectTool(Tool):
    name = "graph_exit_effect"
    version = "1"
    input_model = _Input
    output_model = _Output
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="operation_id unique domain effect",
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("value",))

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, _Input)
        assert ctx.execution_id is not None
        async with transaction() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO graph_exit_provider_call (
                        call_id, execution_id, operation_id
                    )
                    VALUES (:call_id, :execution_id, :operation_id)
                    """
                ),
                {
                    "call_id": uuid4(),
                    "execution_id": ctx.execution_id,
                    "operation_id": ctx.operation_id,
                },
            )
        async with transaction() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO graph_exit_effect (
                        execution_id, operation_id, value
                    )
                    VALUES (:execution_id, :operation_id, :value)
                    ON CONFLICT (operation_id) DO NOTHING
                    """
                ),
                {
                    "execution_id": ctx.execution_id,
                    "operation_id": ctx.operation_id,
                    "value": inputs.value,
                },
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"effect_id": str(ctx.operation_id)},
        )


def _components() -> tuple[
    _EffectTool,
    ToolRegistry,
    CompatibilityLoader,
    FsStorage,
    StorageExecutionParameterStore,
]:
    tool = _EffectTool()
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    descriptor = tool.descriptor
    pins = PinResolverRegistry()

    async def observe(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation:
        del request, context
        return ResourceObservation(
            version=tool.version,
            digest=descriptor.input_schema_sha256,
            status="active",
        )

    pins.register(CallablePinResolver(kind="tool", loader=observe))
    storage = FsStorage(Path(os.environ["GRAPH_EXIT_STORAGE_ROOT"]))
    parameters = StorageExecutionParameterStore(StorageParameterArtifactStore(storage=storage))
    return tool, registry, CompatibilityLoader(pins), storage, parameters


async def _prepare() -> None:
    tool, registry, compatibility, _storage, parameters = _components()
    descriptor = tool.descriptor
    workspace_id = f"ws-graph-exit-{uuid4().hex[:12]}"
    async with transaction() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS graph_exit_provider_call (
                    call_id uuid PRIMARY KEY,
                    execution_id uuid NOT NULL,
                    operation_id uuid NOT NULL,
                    called_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS graph_exit_effect (
                    execution_id uuid NOT NULL,
                    operation_id uuid PRIMARY KEY,
                    value int NOT NULL,
                    committed_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        await seed_workspace(conn, workspace_id)
    requirement = PinRequest(kind="tool", key=tool.name, version=tool.version)
    definition = RecipeDefinition(
        recipe_key=f"graph-exit-{uuid4().hex}",
        scope_type=RecipeScopeType.WORKSPACE,
        workspace_id=workspace_id,
        version=1,
        executor_protocol=1,
        parameter_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        graph=RecipeGraph(
            nodes=(
                ToolNode(
                    node_key="effect",
                    ordinal=0,
                    tool_name=tool.name,
                    tool_version=tool.version,
                    input_schema_sha256=descriptor.input_schema_sha256,
                    output_schema_sha256=descriptor.output_schema_sha256,
                    bindings={"value": ParameterBinding(kind="parameter", name="value")},
                    requirements=(requirement,),
                ),
            ),
            tool_allowlist=(descriptor.address,),
        ),
        compatibility=CompatibilityManifest(nodes={"effect": (requirement,)}),
        max_nodes=1,
        max_depth=1,
        max_fanout=1,
        created_by="system",
    )
    repository = DbRecipeRepository(conn_factory=transaction)
    revision = await repository.propose(definition)
    promoted = await RecipeLifecycle(
        repository=repository,
        tool_catalog=registry,
        compatibility_loader=compatibility,
    ).promote(
        revision,
        context=CompatibilityContext(workspace_id=workspace_id),
        actor="system",
    )
    if not promoted.promoted:
        raise RuntimeError(f"exit recipe did not promote: {promoted.graph_validation.issues}")
    artifact_key, digest = await parameters.snapshot(
        workspace_id=workspace_id,
        parameters={"value": 17},
    )
    start = await DbExecutionStarter(
        conn_factory=transaction,
        recipes=DbRecipeReader(conn_factory=transaction),
        compatibility=compatibility,
        journal=DbExecutionJournal(transport=ExecutionRunEventWriter()),
    ).start(
        workspace_id=workspace_id,
        recipe_revision_id=revision.recipe_revision_id,
        parameters={"value": 17},
        parameter_artifact_key=artifact_key,
        parameter_manifest_hash=digest,
        actor="system",
    )
    print(json.dumps({"execution_id": str(start.execution_id)}), flush=True)


async def _drive(execution_id: ExecutionId, *, crash: bool) -> None:
    _tool, registry, compatibility, storage, parameters = _components()
    crashed = False
    requested_crash_point = os.environ.get(
        "GRAPH_EXIT_CRASH_POINT",
        "after_domain_commit",
    )

    async def crash_hook(
        point: str,
        *,
        context: ToolContext,
        start: object,
    ) -> None:
        nonlocal crashed
        del context, start
        if crash and point == requested_crash_point and not crashed:
            crashed = True
            os.kill(os.getpid(), signal.SIGKILL)

    async def journal_crash_hook(
        point: str,
        execution: ExecutionId,
        node_id: object,
        attempt_id: object,
    ) -> None:
        nonlocal crashed
        del execution, node_id, attempt_id
        if crash and point == requested_crash_point and not crashed:
            crashed = True
            os.kill(os.getpid(), signal.SIGKILL)

    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=DbIdempotencyStore(),
        storage=storage,
        settings=Settings(_env_file=None),
        crash_hook=crash_hook,
        journal_crash_hook=journal_crash_hook,
    )
    executor = RecipeExecutor(
        conn_factory=transaction,
        recipes=DbRecipeReader(conn_factory=transaction),
        compatibility=compatibility,
        journal=DbExecutionJournal(
            transport=ExecutionRunEventWriter(),
            crash_hook=journal_crash_hook,
        ),
        parameters=parameters,
        tool_invoker=invoker,
    )
    lease = None
    for _ in range(80):
        async with transaction() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=f"graph-exit:{os.getpid()}",
                ttl=timedelta(milliseconds=250),
            )
        if lease is not None:
            break
        await asyncio.sleep(0.05)
    if lease is None:
        raise RuntimeError("could not acquire graph-exit lease")
    result = await executor.execute(
        execution_id,
        worker_id=lease.worker_id,
        lease_generation=lease.generation,
    )
    print(json.dumps({"status": result.status.value}), flush=True)


async def _main() -> None:
    mode = sys.argv[1]
    async with db_lifespan():
        if mode == "prepare":
            await _prepare()
            return
        execution_id = ExecutionId(UUID(sys.argv[2]))
        await _drive(execution_id, crash=mode == "crash")


if __name__ == "__main__":
    asyncio.run(_main())
