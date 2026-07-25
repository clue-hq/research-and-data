"""C5.3 execution control tools composed at the API root."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text

from clue_api.execution_wiring import StorageExecutionParameterStore
from clue_api.tool_outputs import (
    ProjectPhaseAdvanceOutput,
    RecipeExecutionStartOutput,
    RecipeExecutionStatusOutput,
    RecipeGateDecisionOutput,
    RecipeProposalOutput,
    RunControlOutput,
)
from clue_core import (
    ExecutionId,
    ProjectPhase,
    ProjectRunId,
    RecipeRevisionId,
)
from clue_db import ConnFactory
from clue_execution import (
    Binding,
    CompatibilityManifest,
    ControlAction,
    ControlKind,
    DbExecutionStarter,
    DbRecipeRepository,
    DbRunControlStore,
    ExecutionStatus,
    ParameterBinding,
    PinRequest,
    RecipeDefinition,
    RecipeExecutor,
    RecipeGraph,
    RecipeScopeType,
    ToolNode,
    get_cursor,
)
from clue_fleet import RunDriver, WorkQueue, reoffer_governed_partial_task
from clue_research.durable import ProjectRunRow, ProjectRunStatus, get_project_run
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolAwaitingInput,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolRegistry,
    ToolResult,
)


class StartRecipeExecutionInput(ToolInput):
    recipe_revision_id: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    project_id: str | None = None
    project_run_id: str | None = None


class PauseRecipeExecutionInput(ToolInput):
    execution_id: str
    reason_code: str = "user_pause"


class ResumeRecipeExecutionInput(ToolInput):
    execution_id: str


class DecideRecipeGateInput(ToolInput):
    execution_id: str
    node_key: str
    decision: str


class PinNodeSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node_key: str
    parameter_fields: tuple[str, ...] = Field(min_length=1)


class PinExecutionAsRecipeInput(ToolInput):
    execution_id: str
    recipe_key: str
    version: int = Field(ge=1)
    nodes: tuple[PinNodeSelection, ...] = Field(min_length=1)
    max_nodes: int = Field(default=128, ge=1)
    max_depth: int = Field(default=3, ge=1)
    max_fanout: int = Field(default=32, ge=1)


class AdvanceProjectPhaseInput(ToolInput):
    project_run_id: str
    expected_phase: ProjectPhase


class ApplyRunControlInput(ToolInput):
    execution_id: str
    control_kind: ControlKind
    subject_ref: str
    reason_code: str
    observation_id: str | None = None
    diagnosis_id: str | None = None
    limits: dict[str, int] | None = None


class ReleaseRunControlInput(ToolInput):
    execution_id: str
    control_kind: ControlKind
    subject_ref: str
    reason_code: str
    observation_id: str | None = None
    diagnosis_id: str | None = None


class AcknowledgeRunEscalationInput(ToolInput):
    execution_id: str
    reason_code: str
    observation_id: str | None = None
    diagnosis_id: str | None = None


def _uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (ValueError, TypeError, AttributeError):
        return None


def _failure(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


@dataclass(frozen=True, slots=True)
class ExecutionControlServices:
    starter: DbExecutionStarter
    executor: RecipeExecutor
    parameters: StorageExecutionParameterStore
    recipes: DbRecipeRepository
    run_machine: RunDriver
    queue: WorkQueue
    conn_factory: ConnFactory
    registry: ToolRegistry
    controls: DbRunControlStore | None = None


class _ExecutionTool(Tool):
    def __init__(self, services: ExecutionControlServices) -> None:
        self._services = services

    async def _execution_snapshot(
        self,
        execution_id: str,
        ctx: ToolContext,
    ) -> dict[str, object]:
        parsed = _uuid(execution_id)
        if parsed is None:
            return {"execution_id": execution_id, "exists": False}
        async with ctx.conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT e.workspace_id, c.status, c.state_version
                            FROM execution e
                            JOIN execution_cursor c ON c.execution_id = e.id
                            WHERE e.id = :execution_id
                            """
                        ),
                        {"execution_id": parsed},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or str(row["workspace_id"]) != ctx.workspace_id:
            return {"execution_id": execution_id, "exists": False}
        return {
            "execution_id": execution_id,
            "exists": True,
            "status": str(row["status"]),
            "state_version": int(row["state_version"]),
        }

    async def _owned_execution(
        self,
        execution_id: str,
        ctx: ToolContext,
    ) -> ExecutionId | None:
        parsed = _uuid(execution_id)
        if parsed is None:
            return None
        async with ctx.conn_factory() as conn:
            workspace = (
                await conn.execute(
                    text("SELECT workspace_id FROM execution WHERE id = :id"),
                    {"id": parsed},
                )
            ).scalar_one_or_none()
        return (
            ExecutionId(parsed)
            if workspace is not None and str(workspace) == ctx.workspace_id
            else None
        )


class StartRecipeExecutionTool(_ExecutionTool):
    name = "start_recipe_execution"
    input_model = StartRecipeExecutionInput
    output_model = RecipeExecutionStartOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="execution id derived from ToolContext.operation_id",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("recipe_revision_id", "project_id", "project_run_id")
    )
    pin_requirements = ("recipe_revision",)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, StartRecipeExecutionInput)
        revision = _uuid(inputs.recipe_revision_id)
        if revision is None:
            raise ValueError("recipe_revision_id is not a UUID")
        run = _uuid(inputs.project_run_id) if inputs.project_run_id is not None else None
        if inputs.project_run_id is not None and run is None:
            raise ValueError("project_run_id is not a UUID")
        project_id = inputs.project_id
        if run is not None:
            async with ctx.conn_factory() as conn:
                run_row = await get_project_run(conn, ProjectRunId(run))
            if run_row is None or run_row.workspace_id != ctx.workspace_id:
                raise ValueError("project run is unknown or outside this workspace")
            if project_id is not None and project_id != run_row.project_id:
                raise ValueError("project_id does not match the project run")
            project_id = run_row.project_id
        artifact_key, digest = await self._services.parameters.snapshot(
            workspace_id=ctx.workspace_id,
            parameters=inputs.parameters,
        )
        execution_id = ExecutionId(
            uuid5(NAMESPACE_URL, f"clue-recipe-execution:{ctx.operation_id}")
        )
        await self._services.starter.start(
            workspace_id=ctx.workspace_id,
            recipe_revision_id=RecipeRevisionId(revision),
            parameters=inputs.parameters,
            parameter_artifact_key=artifact_key,
            parameter_manifest_hash=digest,
            actor=ctx.actor,
            execution_id=execution_id,
            project_id=project_id,
            project_run_id=ProjectRunId(run) if run is not None else None,
            parent_execution_id=ctx.execution_id,
        )
        from clue_execution import enqueue_recipe_execution

        enqueued = await enqueue_recipe_execution(self._services.queue, execution_id)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "execution_id": str(execution_id),
                "status": ExecutionStatus.QUEUED.value,
                "enqueued": enqueued,
            },
        )


class PauseRecipeExecutionTool(_ExecutionTool):
    name = "pause_recipe_execution"
    input_model = PauseRecipeExecutionInput
    output_model = RecipeExecutionStatusOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="execution desired status paused",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("execution_id", "reason_code"))
    pin_requirements = ("execution",)

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, object]:
        assert isinstance(inputs, PauseRecipeExecutionInput)
        return await self._execution_snapshot(inputs.execution_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, PauseRecipeExecutionInput)
        execution_id = await self._owned_execution(inputs.execution_id, ctx)
        if execution_id is None:
            return _failure("execution_not_found", "no such execution")
        async with ctx.conn_factory() as conn:
            cursor = await get_cursor(conn, execution_id)
        if cursor.status not in {
            ExecutionStatus.QUEUED,
            ExecutionStatus.RUNNING,
            ExecutionStatus.PAUSED,
        }:
            return _failure(
                "execution_not_running",
                "only queued, running, or already-paused execution can pause",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, PauseRecipeExecutionInput)
        execution_id = ExecutionId(UUID(inputs.execution_id))
        await self._services.executor.pause(
            execution_id=execution_id,
            actor=ctx.actor,
            reason_code=inputs.reason_code,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "execution_id": inputs.execution_id,
                "status": ExecutionStatus.PAUSED.value,
                "enqueued": False,
            },
        )


class ResumeRecipeExecutionTool(_ExecutionTool):
    name = "resume_recipe_execution"
    input_model = ResumeRecipeExecutionInput
    output_model = RecipeExecutionStatusOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="execution desired status running + queue dedup",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("execution_id",))
    pin_requirements = ("execution",)

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, object]:
        assert isinstance(inputs, ResumeRecipeExecutionInput)
        return await self._execution_snapshot(inputs.execution_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResumeRecipeExecutionInput)
        execution_id = await self._owned_execution(inputs.execution_id, ctx)
        if execution_id is None:
            return _failure("execution_not_found", "no such execution")
        async with ctx.conn_factory() as conn:
            cursor = await get_cursor(conn, execution_id)
        if cursor.status not in {ExecutionStatus.PAUSED, ExecutionStatus.RUNNING}:
            return _failure("execution_not_paused", "only paused execution can resume")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ResumeRecipeExecutionInput)
        execution_id = ExecutionId(UUID(inputs.execution_id))
        async with ctx.conn_factory() as conn:
            cursor = await get_cursor(conn, execution_id)
        if cursor.status is ExecutionStatus.PAUSED:
            await self._services.executor.resume(execution_id=execution_id, actor=ctx.actor)
        from clue_execution import enqueue_recipe_execution

        enqueued = await enqueue_recipe_execution(self._services.queue, execution_id)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "execution_id": inputs.execution_id,
                "status": ExecutionStatus.RUNNING.value,
                "enqueued": enqueued,
            },
        )


class DecideRecipeGateTool(_ExecutionTool):
    name = "decide_recipe_gate"
    input_model = DecideRecipeGateInput
    output_model = RecipeGateDecisionOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="execution + gate node terminal decision",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("execution_id", "node_key", "decision")
    )
    pin_requirements = ("execution",)

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, object]:
        assert isinstance(inputs, DecideRecipeGateInput)
        snapshot = await self._execution_snapshot(inputs.execution_id, ctx)
        execution = _uuid(inputs.execution_id)
        if execution is None or not snapshot.get("exists"):
            return snapshot
        async with ctx.conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                EXISTS (
                                    SELECT 1 FROM execution_event e
                                    JOIN execution_node n ON n.id = e.node_id
                                    WHERE e.execution_id = :execution_id
                                      AND n.node_key = :node_key
                                      AND e.event_type = 'gate.opened'
                                ) AS opened,
                                (
                                    SELECT e.payload_json->>'decision'
                                    FROM execution_event e
                                    JOIN execution_node n ON n.id = e.node_id
                                    WHERE e.execution_id = :execution_id
                                      AND n.node_key = :node_key
                                      AND e.event_type = 'gate.decided'
                                    ORDER BY e.seq DESC LIMIT 1
                                ) AS decision
                            """
                        ),
                        {
                            "execution_id": execution,
                            "node_key": inputs.node_key,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return {
            **snapshot,
            "gate_node_key": inputs.node_key,
            "gate_opened": bool(row["opened"]),
            "gate_decision": (str(row["decision"]) if row["decision"] is not None else None),
        }

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DecideRecipeGateInput)
        execution_id = await self._owned_execution(inputs.execution_id, ctx)
        if execution_id is None:
            return _failure("execution_not_found", "no such execution")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DecideRecipeGateInput)
        execution_id = ExecutionId(UUID(inputs.execution_id))
        await self._services.executor.decide_gate(
            execution_id=execution_id,
            node_key=inputs.node_key,
            actor=ctx.actor,
            decision=inputs.decision,
        )
        from clue_execution import enqueue_recipe_execution

        enqueued = await enqueue_recipe_execution(self._services.queue, execution_id)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "execution_id": inputs.execution_id,
                "node_key": inputs.node_key,
                "decision": inputs.decision,
                "enqueued": enqueued,
            },
        )


def _parameter_name(node_key: str, field_name: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9_]", "_", node_key)
    return f"{prefix}__{field_name}"


class PinExecutionAsRecipeTool(_ExecutionTool):
    name = "pin_execution_as_recipe"
    input_model = PinExecutionAsRecipeInput
    output_model = RecipeProposalOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace recipe key + immutable version",
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("execution_id", "recipe_key", "version")
    )
    pin_requirements = ("execution",)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, PinExecutionAsRecipeInput)
        execution_id = await self._owned_execution(inputs.execution_id, ctx)
        if execution_id is None:
            return _failure("execution_not_found", "no such execution")
        async with ctx.conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT e.recipe_revision_id, c.status
                            FROM execution e
                            JOIN execution_cursor c ON c.execution_id = e.id
                            WHERE e.id = :execution_id
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one()
            )
        if row["recipe_revision_id"] is not None:
            return _failure(
                "execution_not_ad_hoc",
                "only a completed ad-hoc execution can be pinned as a recipe",
            )
        if str(row["status"]) != ExecutionStatus.COMPLETED.value:
            return _failure(
                "execution_not_completed",
                "execution must be completed before pinning",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, PinExecutionAsRecipeInput)
        execution_id = ExecutionId(UUID(inputs.execution_id))
        selected = {item.node_key: item for item in inputs.nodes}
        if len(selected) != len(inputs.nodes):
            raise ValueError("pin selections contain duplicate node keys")
        async with ctx.conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT n.node_key, n.tool_name, n.tool_version,
                                   n.input_schema_sha256, n.output_schema_sha256,
                                   r.artifact_key, r.content_sha256
                            FROM execution_node n
                            JOIN execution_artifact_ref r
                              ON r.execution_id = n.execution_id
                             AND r.node_id = n.id
                             AND r.role = 'parameter'
                            WHERE n.execution_id = :execution_id
                              AND n.node_key = ANY(CAST(:node_keys AS text[]))
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "node_keys": list(selected),
                        },
                    )
                )
                .mappings()
                .all()
            )
            edge_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT f.node_key AS from_key, t.node_key AS to_key
                            FROM execution_edge e
                            JOIN execution_node f ON f.id = e.from_node_id
                            JOIN execution_node t ON t.id = e.to_node_id
                            WHERE e.execution_id = :execution_id
                              AND e.edge_kind = 'dependency'
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
        by_key = {str(row["node_key"]): row for row in rows}
        if set(by_key) != set(selected):
            raise ValueError("one or more selected nodes are missing or are not tool invocations")
        dependencies = {
            key: tuple(
                sorted(
                    str(edge["from_key"])
                    for edge in edge_rows
                    if str(edge["to_key"]) == key and str(edge["from_key"]) in selected
                )
            )
            for key in selected
        }
        parameter_properties: dict[str, JsonValue] = {}
        graph_nodes: list[ToolNode] = []
        compatibility_nodes: dict[str, tuple[PinRequest, ...]] = {}
        for ordinal, selection in enumerate(inputs.nodes):
            row = by_key[selection.node_key]
            descriptor = self._services.registry.descriptor(
                str(row["tool_name"]),
                str(row["tool_version"]),
            )
            body = await self._services.parameters.resolve(
                workspace_id=ctx.workspace_id,
                artifact_key=str(row["artifact_key"]),
                content_sha256=str(row["content_sha256"]),
            )
            fields = tuple(selection.parameter_fields)
            if len(fields) != len(set(fields)):
                raise ValueError(f"{selection.node_key} repeats a parameter field")
            if set(fields) != set(body):
                raise ValueError(
                    f"{selection.node_key} must explicitly parameterize every input field; "
                    "C5 never copies unselected body content into a recipe"
                )
            unsafe = sorted(set(fields) - set(descriptor.parameter_policy.safe_display_fields))
            if unsafe:
                raise ValueError(
                    f"{selection.node_key} fields are not declared display-safe: {unsafe}"
                )
            schema = descriptor.input_model.model_json_schema()
            properties = schema.get("properties", {})
            if not isinstance(properties, Mapping):
                raise ValueError("tool input schema has no properties")
            bindings: dict[str, Binding] = {}
            for field_name in fields:
                field_schema = properties.get(field_name)
                if not isinstance(field_schema, Mapping):
                    raise ValueError(f"tool schema has no field {field_name!r}")
                parameter_name = _parameter_name(selection.node_key, field_name)
                parameter_properties[parameter_name] = dict(field_schema)
                bindings[field_name] = ParameterBinding(
                    kind="parameter",
                    name=parameter_name,
                )
            requirement = PinRequest(
                kind="tool",
                key=descriptor.name,
                version=descriptor.version,
            )
            compatibility_nodes[selection.node_key] = (requirement,)
            graph_nodes.append(
                ToolNode(
                    node_key=selection.node_key,
                    ordinal=ordinal,
                    dependencies=dependencies[selection.node_key],
                    tool_name=descriptor.name,
                    tool_version=descriptor.version,
                    input_schema_sha256=descriptor.input_schema_sha256,
                    output_schema_sha256=descriptor.output_schema_sha256,
                    bindings=bindings,
                    requirements=(requirement,),
                )
            )
        parameter_names = sorted(parameter_properties)
        definition = RecipeDefinition(
            recipe_key=inputs.recipe_key,
            scope_type=RecipeScopeType.WORKSPACE,
            workspace_id=ctx.workspace_id,
            version=inputs.version,
            executor_protocol=1,
            parameter_schema={
                "type": "object",
                "properties": parameter_properties,
                "required": list(parameter_names),
                "additionalProperties": False,
            },
            graph=RecipeGraph(
                nodes=tuple(graph_nodes),
                tool_allowlist=tuple(sorted(node.tool_address for node in graph_nodes)),
                authority_allowlist=(),
                activity_allowlist=(),
            ),
            compatibility=CompatibilityManifest(nodes=compatibility_nodes),
            max_nodes=inputs.max_nodes,
            max_depth=inputs.max_depth,
            max_fanout=inputs.max_fanout,
            source_execution_id=execution_id,
            created_by=ctx.actor,
        )
        revision = await self._services.recipes.propose(definition)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "recipe_revision_id": str(revision.recipe_revision_id),
                "recipe_key": revision.recipe_key,
                "version": revision.version,
                "status": "proposed",
            },
        )


class AdvanceProjectPhaseTool(_ExecutionTool):
    name = "advance_project_phase"
    input_model = AdvanceProjectPhaseInput
    output_model = ProjectPhaseAdvanceOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project run + expected phase + phase ledger",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_run_id", "expected_phase")
    )
    pin_requirements = ("project_run",)

    async def _run(
        self, inputs: AdvanceProjectPhaseInput, ctx: ToolContext
    ) -> tuple[ProjectRunId, ProjectRunRow | None]:
        parsed = _uuid(inputs.project_run_id)
        if parsed is None:
            return ProjectRunId(UUID(int=0)), None
        run_id = ProjectRunId(parsed)
        async with ctx.conn_factory() as conn:
            run = await get_project_run(conn, run_id)
            owner = (
                await conn.execute(
                    text(
                        """
                            SELECT execution_id FROM project_run_execution_owner
                            WHERE project_run_id = :run_id
                            """
                    ),
                    {"run_id": run_id},
                )
            ).scalar_one_or_none()
        if (
            run is None
            or run.workspace_id != ctx.workspace_id
            or ctx.execution_id is None
            or owner is None
            or str(owner) != str(ctx.execution_id)
        ):
            return run_id, None
        return run_id, run

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, AdvanceProjectPhaseInput)
        _run_id, run_raw = await self._run(inputs, ctx)
        if run_raw is None:
            return _failure(
                "run_not_recipe_owned",
                "run is missing, cross-workspace, or not owned by this execution",
            )
        run = run_raw
        phases = list(ProjectPhase)
        expected_index = phases.index(inputs.expected_phase)
        current_index = phases.index(run.phase)
        if current_index not in {expected_index, expected_index + 1}:
            return _failure(
                "unexpected_project_phase",
                f"expected {inputs.expected_phase.value} or its immediate successor",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, AdvanceProjectPhaseInput)
        run_id, run_raw = await self._run(inputs, ctx)
        assert run_raw is not None
        run = run_raw
        if run.phase is inputs.expected_phase:
            run = await self._services.run_machine.advance(run_id)
        if run.status is ProjectRunStatus.FAILED:
            raise RuntimeError(f"project phase {inputs.expected_phase.value} failed")
        if run.phase is inputs.expected_phase and run.status is ProjectRunStatus.PAUSED:
            raise ToolAwaitingInput(f"project_phase_{inputs.expected_phase.value}_awaiting_input")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": str(run.id),
                "phase": run.phase.value,
                "status": run.status.value,
            },
        )


class _RunControlTool(_ExecutionTool):
    effect_class = ToolEffectClass.STEERING
    output_model = RunControlOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="execution + stable operation id in append-only run_control_event",
        operation_id_required=True,
    )
    pin_requirements = ("execution", "supervisor_policy")

    @property
    def _controls(self) -> DbRunControlStore:
        if self._services.controls is None:
            raise RuntimeError("run-control tools require DbRunControlStore")
        return self._services.controls

    async def _snapshot(
        self,
        *,
        execution_id: str,
        kind: ControlKind,
        subject_ref: str,
        ctx: ToolContext,
    ) -> Mapping[str, object]:
        owned = await self._owned_execution(execution_id, ctx)
        if owned is None:
            return {
                "execution_id": execution_id,
                "control_kind": kind.value,
                "subject_ref": subject_ref,
                "exists": False,
            }
        current = await self._controls.latest(owned, kind, subject_ref)
        return {
            "execution_id": execution_id,
            "control_kind": kind.value,
            "subject_ref": subject_ref,
            "exists": True,
            "active": bool(current.after.get("active")) if current is not None else False,
            "last_action": current.action.value if current is not None else None,
            "reason_code": current.reason_code if current is not None else None,
        }

    async def _preconditions(
        self,
        *,
        execution_id: str,
        kind: ControlKind,
    ) -> Sequence[PreconditionFailure]:
        if kind not in set(ControlKind):
            return _failure("invalid_control_kind", "control kind is not supported")
        if _uuid(execution_id) is None:
            return _failure("execution_not_found", "execution id is not a UUID")
        return ()

    async def _mutate(
        self,
        *,
        execution_id: str,
        kind: ControlKind,
        subject_ref: str,
        action: ControlAction,
        reason_code: str,
        observation_id: str | None,
        diagnosis_id: str | None,
        limits: dict[str, int] | None,
        ctx: ToolContext,
    ) -> ToolResult:
        target = await self._owned_execution(execution_id, ctx)
        if target is None:
            raise ValueError("execution is unknown or outside this workspace")
        observation = _uuid(observation_id) if observation_id is not None else None
        diagnosis = _uuid(diagnosis_id) if diagnosis_id is not None else None
        if observation_id is not None and observation is None:
            raise ValueError("observation_id is not a UUID")
        if diagnosis_id is not None and diagnosis is None:
            raise ValueError("diagnosis_id is not a UUID")
        requested_after: dict[str, JsonValue] = {}
        if limits is not None:
            requested_after["limits"] = cast(JsonValue, limits)
        event = await self._controls.mutate(
            workspace_id=ctx.workspace_id,
            execution_id=target,
            operation_id=ctx.operation_id,
            control_kind=kind,
            subject_ref=subject_ref,
            action=action,
            reason_code=reason_code,
            actor=ctx.actor,
            requested_after=requested_after,
            observation_id=observation,
            diagnosis_id=diagnosis,
        )
        reoffered = False
        if kind is ControlKind.ACCOUNT_QUARANTINE and action is ControlAction.RELEASE:
            async with ctx.conn_factory() as conn:
                project_run_id = (
                    await conn.execute(
                        text("SELECT project_run_id FROM execution WHERE id = :id"),
                        {"id": target},
                    )
                ).scalar_one_or_none()
                if project_run_id is not None:
                    reoffered = await reoffer_governed_partial_task(
                        conn,
                        project_run_id=ProjectRunId(project_run_id),
                        dedup_key=subject_ref,
                    )
        if kind is ControlKind.ESCALATION and action is ControlAction.APPLY:
            await self._services.executor.pause(
                execution_id=target,
                actor=ctx.actor,
                reason_code=reason_code,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "execution_id": execution_id,
                "control_kind": kind.value,
                "subject_ref": subject_ref,
                "action": action.value,
                "active": bool(event.after.get("active")),
                "reoffered": reoffered,
            },
        )


class ApplyRunControlTool(_RunControlTool):
    name = "apply_run_control"
    input_model = ApplyRunControlInput
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "execution_id",
            "control_kind",
            "subject_ref",
            "reason_code",
            "observation_id",
            "diagnosis_id",
            "limits",
        )
    )

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, object]:
        assert isinstance(inputs, ApplyRunControlInput)
        return await self._snapshot(
            execution_id=inputs.execution_id,
            kind=inputs.control_kind,
            subject_ref=inputs.subject_ref,
            ctx=ctx,
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ApplyRunControlInput)
        failures = await self._preconditions(
            execution_id=inputs.execution_id,
            kind=inputs.control_kind,
        )
        if failures:
            return failures
        if await self._owned_execution(inputs.execution_id, ctx) is None:
            return _failure("execution_not_found", "no such execution")
        if inputs.control_kind is ControlKind.ENVELOPE and inputs.limits is None:
            return _failure("envelope_limits_required", "envelope apply requires limits")
        if inputs.control_kind is not ControlKind.ENVELOPE and inputs.limits is not None:
            return _failure("unexpected_envelope_limits", "limits apply only to envelope controls")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ApplyRunControlInput)
        return await self._mutate(
            execution_id=inputs.execution_id,
            kind=inputs.control_kind,
            subject_ref=inputs.subject_ref,
            action=ControlAction.APPLY,
            reason_code=inputs.reason_code,
            observation_id=inputs.observation_id,
            diagnosis_id=inputs.diagnosis_id,
            limits=inputs.limits,
            ctx=ctx,
        )


class ReleaseRunControlTool(_RunControlTool):
    name = "release_run_control"
    input_model = ReleaseRunControlInput
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "execution_id",
            "control_kind",
            "subject_ref",
            "reason_code",
            "observation_id",
            "diagnosis_id",
        )
    )

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, object]:
        assert isinstance(inputs, ReleaseRunControlInput)
        return await self._snapshot(
            execution_id=inputs.execution_id,
            kind=inputs.control_kind,
            subject_ref=inputs.subject_ref,
            ctx=ctx,
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ReleaseRunControlInput)
        if inputs.control_kind is ControlKind.ESCALATION:
            return _failure(
                "escalation_requires_acknowledge",
                "use acknowledge_run_escalation for escalations",
            )
        if await self._owned_execution(inputs.execution_id, ctx) is None:
            return _failure("execution_not_found", "no such execution")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReleaseRunControlInput)
        return await self._mutate(
            execution_id=inputs.execution_id,
            kind=inputs.control_kind,
            subject_ref=inputs.subject_ref,
            action=ControlAction.RELEASE,
            reason_code=inputs.reason_code,
            observation_id=inputs.observation_id,
            diagnosis_id=inputs.diagnosis_id,
            limits=None,
            ctx=ctx,
        )


class AcknowledgeRunEscalationTool(_RunControlTool):
    name = "acknowledge_run_escalation"
    input_model = AcknowledgeRunEscalationInput
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "execution_id",
            "reason_code",
            "observation_id",
            "diagnosis_id",
        )
    )

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, object]:
        assert isinstance(inputs, AcknowledgeRunEscalationInput)
        return await self._snapshot(
            execution_id=inputs.execution_id,
            kind=ControlKind.ESCALATION,
            subject_ref="deep_gate",
            ctx=ctx,
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, AcknowledgeRunEscalationInput)
        if await self._owned_execution(inputs.execution_id, ctx) is None:
            return _failure("execution_not_found", "no such execution")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, AcknowledgeRunEscalationInput)
        return await self._mutate(
            execution_id=inputs.execution_id,
            kind=ControlKind.ESCALATION,
            subject_ref="deep_gate",
            action=ControlAction.ACKNOWLEDGE,
            reason_code=inputs.reason_code,
            observation_id=inputs.observation_id,
            diagnosis_id=inputs.diagnosis_id,
            limits=None,
            ctx=ctx,
        )


def execution_control_tools(
    services: ExecutionControlServices,
) -> tuple[Tool, ...]:
    tools: tuple[Tool, ...] = (
        StartRecipeExecutionTool(services),
        PauseRecipeExecutionTool(services),
        ResumeRecipeExecutionTool(services),
        DecideRecipeGateTool(services),
        PinExecutionAsRecipeTool(services),
        AdvanceProjectPhaseTool(services),
    )
    if services.controls is not None:
        tools = (
            *tools,
            ApplyRunControlTool(services),
            ReleaseRunControlTool(services),
            AcknowledgeRunEscalationTool(services),
        )
    return tools


def register_execution_control_tools(services: ExecutionControlServices) -> None:
    for tool in execution_control_tools(services):
        services.registry.register(tool, make_default=True)


__all__ = [
    "AdvanceProjectPhaseInput",
    "AdvanceProjectPhaseTool",
    "AcknowledgeRunEscalationInput",
    "ApplyRunControlInput",
    "ExecutionControlServices",
    "PinExecutionAsRecipeInput",
    "ReleaseRunControlInput",
    "register_execution_control_tools",
]
