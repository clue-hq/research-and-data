"""Deterministic, lease-fenced execution of immutable recipe DAGs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionNodeId,
    OperationId,
    ProjectRunId,
    RecipeRevisionId,
    decode_jsonb,
    new_execution_id,
    operation_id_from_key,
    serialize_value_json,
)
from clue_db import ConnFactory
from clue_execution.compatibility import (
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityReport,
)
from clue_execution.controls import DbRunControlStore, EffectiveEnvelope
from clue_execution.graph import (
    ActivityNode,
    BarrierNode,
    Binding,
    GateNode,
    GraphNode,
    LiteralBinding,
    MapNode,
    NodeReferenceBinding,
    ParameterBinding,
    RecipeGraph,
    ToolNode,
)
from clue_execution.journal import (
    DbExecutionJournal,
    ExecutionCursor,
    get_cursor,
    rebuild_cursor,
)
from clue_execution.models import (
    EdgeKind,
    ExecutionEventType,
    ExecutionStatus,
    PinRequest,
    RecipeRevisionEventType,
    ResolvedPin,
)
from clue_execution.recipes import DbRecipeReader, RecipeDefinition, RecipeRevisionView
from clue_toolbelt import ToolContext, ToolInvoker, ToolResult

SUPPORTED_EXECUTOR_PROTOCOL = 1
MAX_EXECUTION_CONCURRENCY = 32

_GRAPH_NODE: TypeAdapter[GraphNode] = TypeAdapter(GraphNode)


class ExecutionError(RuntimeError):
    pass


class IncompatibleRecipe(ExecutionError):
    def __init__(self, report: CompatibilityReport) -> None:
        super().__init__("recipe compatibility requirements are not satisfied")
        self.report = report


class PlaceholderRecipe(ExecutionError):
    pass


class ExecutionConflict(ExecutionError):
    pass


class ExecutionParameterStore(Protocol):
    async def snapshot(
        self,
        *,
        workspace_id: str,
        parameters: dict[str, JsonValue],
    ) -> tuple[str, str]: ...

    async def resolve(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        content_sha256: str,
    ) -> dict[str, JsonValue]: ...


class ActivityInvoker(Protocol):
    async def invoke(
        self,
        *,
        activity_name: str,
        activity_version: str,
        parameters: dict[str, object],
        context: ToolContext,
    ) -> dict[str, JsonValue]: ...


type CrashHook = Callable[
    [str, ExecutionId, ExecutionNodeId | None],
    Awaitable[None],
]


async def _no_crash(
    _point: str,
    _execution_id: ExecutionId,
    _node_id: ExecutionNodeId | None,
) -> None:
    return None


@dataclass(frozen=True, slots=True)
class ExecutionStart:
    execution_id: ExecutionId
    created: bool
    compatibility: CompatibilityReport


@dataclass(frozen=True, slots=True)
class ExecutionRunResult:
    execution_id: ExecutionId
    status: ExecutionStatus
    completed_node_keys: tuple[str, ...]
    replayed_node_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InteractionAppend:
    execution_id: ExecutionId
    node_id: ExecutionNodeId
    operation_id: OperationId
    node_key: str
    created: bool


@dataclass(frozen=True, slots=True)
class InteractionSlotView:
    """Read-only policy snapshot used to validate a complete dynamic plan before append."""

    execution_id: ExecutionId
    workspace_id: str
    slot_key: str
    tool_allowlist: tuple[str, ...]
    dynamic_pin_kinds: tuple[str, ...]
    requirements: tuple[PinRequest, ...]
    max_children: int
    child_count: int
    max_nodes: int
    node_count: int


@dataclass(frozen=True, slots=True)
class _Runtime:
    execution_id: ExecutionId
    parent_execution_id: ExecutionId | None
    workspace_id: str
    project_id: str | None
    project_run_id: ProjectRunId | None
    parameter_artifact_key: str
    parameter_manifest_hash: str
    revision: RecipeRevisionView
    definition: RecipeDefinition


@dataclass(frozen=True, slots=True)
class _Node:
    node_id: ExecutionNodeId
    operation_id: OperationId
    ordinal: int
    depth: int
    spec: GraphNode
    local_parameters: dict[str, JsonValue]
    compatibility_node_key: str
    actor: str
    parameter_artifact_key: str | None
    parameter_sha256: str | None
    dynamic_requirements: tuple[PinRequest, ...]


def execution_node_id(execution_id: ExecutionId, node_key: str) -> ExecutionNodeId:
    return ExecutionNodeId(uuid5(NAMESPACE_URL, f"clue-execution-node:{execution_id}:{node_key}"))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _assert_parameter_schema(
    value: Mapping[str, JsonValue],
    schema: Mapping[str, object],
    *,
    path: str = "$",
) -> None:
    """Validate the deliberately small JSON-Schema subset allowed by recipe definitions."""
    if schema.get("type") != "object":
        raise ValueError(f"{path} schema must be an object")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError(f"{path}.properties must be an object")
    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ValueError(f"{path}.required must be an array")
    missing = sorted(str(name) for name in required if name not in value)
    if missing:
        raise ValueError(f"recipe parameters are missing required keys: {missing}")
    if schema.get("additionalProperties") is False:
        extras = sorted(set(value) - {str(name) for name in properties})
        if extras:
            raise ValueError(f"recipe parameters contain unknown keys: {extras}")
    for name, item in value.items():
        item_schema = properties.get(name)
        if not isinstance(item_schema, Mapping):
            continue
        allowed = item_schema.get("type")
        types = {allowed} if isinstance(allowed, str) else set(allowed or ())
        observed = (
            "null"
            if item is None
            else "boolean"
            if isinstance(item, bool)
            else "integer"
            if isinstance(item, int)
            else "number"
            if isinstance(item, float)
            else "string"
            if isinstance(item, str)
            else "array"
            if isinstance(item, list)
            else "object"
        )
        if types and observed not in types and not (observed == "integer" and "number" in types):
            raise ValueError(f"recipe parameter {name!r} has type {observed}, expected {types}")
        enum = item_schema.get("enum")
        if isinstance(enum, list) and item not in enum:
            raise ValueError(f"recipe parameter {name!r} is outside its enum")


async def _effective_recipe_event(
    conn: AsyncConnection,
    recipe_revision_id: RecipeRevisionId,
) -> str | None:
    return cast(
        str | None,
        (
            await conn.execute(
                text(
                    """
                    SELECT event_type FROM recipe_revision_event
                    WHERE recipe_revision_id = :revision
                    ORDER BY seq DESC LIMIT 1
                    """
                ),
                {"revision": recipe_revision_id},
            )
        ).scalar_one_or_none(),
    )


class DbExecutionStarter:
    """Fail-before-task recipe loader and idempotent execution materializer."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory,
        recipes: DbRecipeReader,
        compatibility: CompatibilityLoader,
        journal: DbExecutionJournal,
    ) -> None:
        self._conn_factory = conn_factory
        self._recipes = recipes
        self._compatibility = compatibility
        self._journal = journal

    async def start(
        self,
        *,
        workspace_id: str,
        recipe_revision_id: RecipeRevisionId,
        parameters: dict[str, JsonValue],
        parameter_artifact_key: str,
        parameter_manifest_hash: str,
        actor: str,
        execution_id: ExecutionId | None = None,
        project_id: str | None = None,
        project_run_id: ProjectRunId | None = None,
        parent_execution_id: ExecutionId | None = None,
        additional_requirements: Sequence[PinRequest] = (),
        pre_satisfied_nodes: Mapping[str, Mapping[str, JsonValue]] | None = None,
    ) -> ExecutionStart:
        revision = await self._recipes.get_revision(
            recipe_revision_id=recipe_revision_id,
            workspace_id=workspace_id,
        )
        if revision is None:
            raise ValueError("recipe revision is unknown or outside this workspace")
        definition = revision.definition()
        if definition.executor_protocol != SUPPORTED_EXECUTOR_PROTOCOL:
            raise ValueError(
                f"executor protocol {definition.executor_protocol} is unsupported "
                f"(supported={SUPPORTED_EXECUTOR_PROTOCOL})"
            )
        if definition.graph.migration_state != "executable":
            raise PlaceholderRecipe(
                f"{definition.recipe_key}@{definition.version} is a migration placeholder"
            )
        _assert_parameter_schema(parameters, definition.parameter_schema)
        observed_hash = hashlib.sha256(_canonical_bytes(parameters)).hexdigest()
        if observed_hash != parameter_manifest_hash:
            raise ValueError("parameter manifest hash does not match the canonical parameters")
        context = CompatibilityContext(
            workspace_id=workspace_id,
            project_id=project_id,
        )
        static_requirements = list(definition.compatibility.execution)
        for node_key in sorted(definition.compatibility.nodes):
            static_requirements.extend(definition.compatibility.nodes[node_key])
        report = await self._compatibility.resolve_requirements(
            (*static_requirements, *additional_requirements),
            context=context,
        )
        if not report.compatible:
            raise IncompatibleRecipe(report)
        node_reports = {
            node.node_key: await self._compatibility.recheck_node(
                definition.compatibility,
                node_key=node.node_key,
                context=context,
            )
            for node in definition.graph.nodes
        }
        changed = next(
            (item for item in node_reports.values() if not item.compatible),
            None,
        )
        if changed is not None:
            raise IncompatibleRecipe(changed)
        pre_satisfied = dict(pre_satisfied_nodes or {})
        graph_by_key = {node.node_key: node for node in definition.graph.nodes}
        unknown_pre_satisfied = set(pre_satisfied) - set(graph_by_key)
        if unknown_pre_satisfied:
            raise ValueError(
                f"pre-satisfied nodes are absent from the recipe: {sorted(unknown_pre_satisfied)}"
            )
        for node_key in pre_satisfied:
            missing_dependencies = set(graph_by_key[node_key].dependencies) - set(pre_satisfied)
            if missing_dependencies:
                raise ValueError(
                    f"pre-satisfied node {node_key!r} is missing dependencies "
                    f"{sorted(missing_dependencies)}"
                )

        resolved_execution_id = execution_id or new_execution_id()
        async with self._conn_factory() as conn:
            effective = await _effective_recipe_event(conn, recipe_revision_id)
            if effective != RecipeRevisionEventType.PROMOTED.value:
                raise ValueError("only a currently promoted recipe revision may start")
            existing = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT workspace_id, project_id, project_run_id, recipe_revision_id,
                                   parameter_artifact_key, parameter_manifest_hash,
                                   pin_manifest_hash, parent_execution_id
                            FROM execution WHERE id = :execution_id
                            """
                        ),
                        {"execution_id": resolved_execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            expected = (
                workspace_id,
                project_id,
                str(project_run_id) if project_run_id is not None else None,
                str(recipe_revision_id),
                parameter_artifact_key,
                parameter_manifest_hash,
                report.report_sha256,
                str(parent_execution_id) if parent_execution_id is not None else None,
            )
            if existing is not None:
                actual = (
                    str(existing["workspace_id"]),
                    str(existing["project_id"]) if existing["project_id"] is not None else None,
                    (
                        str(existing["project_run_id"])
                        if existing["project_run_id"] is not None
                        else None
                    ),
                    str(existing["recipe_revision_id"]),
                    str(existing["parameter_artifact_key"]),
                    str(existing["parameter_manifest_hash"]),
                    str(existing["pin_manifest_hash"]),
                    (
                        str(existing["parent_execution_id"])
                        if existing["parent_execution_id"] is not None
                        else None
                    ),
                )
                if actual != expected:
                    raise ExecutionConflict(
                        "execution id was replayed with a different recipe, scope, or parameters"
                    )
                return ExecutionStart(
                    execution_id=resolved_execution_id,
                    created=False,
                    compatibility=report,
                )

            await conn.execute(
                text(
                    """
                    INSERT INTO execution (
                        id, workspace_id, project_id, project_run_id, recipe_revision_id,
                        parent_execution_id, started_by, parameter_artifact_key,
                        parameter_manifest_hash, pin_manifest_hash
                    )
                    VALUES (
                        :id, :workspace_id, :project_id, :project_run_id, :recipe_revision_id,
                        :parent_execution_id, :actor, :parameter_artifact_key,
                        :parameter_manifest_hash, :pin_manifest_hash
                    )
                    """
                ),
                {
                    "id": resolved_execution_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "project_run_id": project_run_id,
                    "recipe_revision_id": recipe_revision_id,
                    "parent_execution_id": parent_execution_id,
                    "actor": actor,
                    "parameter_artifact_key": parameter_artifact_key,
                    "parameter_manifest_hash": parameter_manifest_hash,
                    "pin_manifest_hash": report.report_sha256,
                },
            )
            await conn.execute(
                text("INSERT INTO execution_cursor (execution_id, status) VALUES (:id, 'queued')"),
                {"id": resolved_execution_id},
            )
            if definition.recipe_key == "recipe1-classic" and project_run_id is not None:
                claimed = await conn.execute(
                    text(
                        """
                        INSERT INTO project_run_execution_owner (
                            project_run_id, execution_id, workspace_id, project_id, routing_mode
                        )
                        VALUES (:run_id, :execution_id, :workspace_id, :project_id, 'recipe')
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "run_id": project_run_id,
                        "execution_id": resolved_execution_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                    },
                )
                if claimed.rowcount != 1:
                    raise ExecutionConflict("project run already has an execution owner")
            await self._insert_pins(
                conn,
                execution_id=resolved_execution_id,
                node_id=None,
                pins=report.pins,
            )
            cursor = await get_cursor(conn, resolved_execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=resolved_execution_id,
                event_type=ExecutionEventType.EXECUTION_QUEUED,
                actor=actor,
                payload={
                    "recipe_revision_id": str(recipe_revision_id),
                    "definition_sha256": revision.definition_sha256,
                    "pin_manifest_hash": report.report_sha256,
                },
                expected_state_version=cursor.state_version,
            )
            await self._materialize_graph(
                conn,
                execution_id=resolved_execution_id,
                graph=definition.graph,
                actor=actor,
            )
            for node_key, node_report in node_reports.items():
                await self._insert_pins(
                    conn,
                    execution_id=resolved_execution_id,
                    node_id=execution_node_id(resolved_execution_id, node_key),
                    pins=node_report.pins,
                )
            for node_key in sorted(
                pre_satisfied,
                key=lambda key: (graph_by_key[key].ordinal, key),
            ):
                await self._complete_pre_satisfied_node(
                    conn,
                    execution_id=resolved_execution_id,
                    node_key=node_key,
                    actor=actor,
                    references=pre_satisfied[node_key],
                )
        return ExecutionStart(
            execution_id=resolved_execution_id,
            created=True,
            compatibility=report,
        )

    async def _complete_pre_satisfied_node(
        self,
        conn: AsyncConnection,
        *,
        execution_id: ExecutionId,
        node_key: str,
        actor: str,
        references: Mapping[str, JsonValue],
    ) -> None:
        """Record a born-complete node inside the same transaction as execution creation."""
        node_id = execution_node_id(execution_id, node_key)
        attempt_id = ExecutionAttemptId(uuid4())
        await conn.execute(
            text(
                """
                INSERT INTO execution_attempt (
                    id, execution_id, node_id, attempt, worker_id
                )
                VALUES (:id, :execution_id, :node_id, 1, 'pre_satisfied')
                """
            ),
            {
                "id": attempt_id,
                "execution_id": execution_id,
                "node_id": node_id,
            },
        )
        cursor = await get_cursor(conn, execution_id, for_update=True)
        await self._journal.append_event(
            conn,
            execution_id=execution_id,
            node_id=node_id,
            attempt_id=attempt_id,
            event_type=ExecutionEventType.NODE_STARTED,
            actor=actor,
            payload={"attempt": 1, "pre_satisfied": True},
            expected_state_version=cursor.state_version,
        )
        cursor = await get_cursor(conn, execution_id, for_update=True)
        await self._journal.append_event(
            conn,
            execution_id=execution_id,
            node_id=node_id,
            attempt_id=attempt_id,
            event_type=ExecutionEventType.NODE_COMPLETED,
            actor=actor,
            payload={
                "result": {
                    "tool": "advance_project_phase",
                    "version": "1",
                    "references": dict(references),
                    "replayed": False,
                    "meta": {"pre_satisfied": True},
                }
            },
            expected_state_version=cursor.state_version,
        )

    async def _materialize_graph(
        self,
        conn: AsyncConnection,
        *,
        execution_id: ExecutionId,
        graph: RecipeGraph,
        actor: str,
    ) -> None:
        for node in sorted(graph.nodes, key=lambda item: (item.ordinal, item.node_key)):
            node_id = await _insert_node(
                conn,
                execution_id=execution_id,
                spec=node,
                depth=0,
                definition={"node": node.model_dump(mode="json"), "local_parameters": {}},
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                node_id=node_id,
                event_type=ExecutionEventType.NODE_SCHEDULED,
                actor=actor,
                payload={"ordinal": node.ordinal, "depth": 0},
                expected_state_version=cursor.state_version,
            )
        for node in graph.nodes:
            for dependency in node.dependencies:
                await _insert_edge(
                    conn,
                    execution_id=execution_id,
                    from_key=dependency,
                    to_key=node.node_key,
                    edge_kind=EdgeKind.DEPENDENCY,
                )

    @staticmethod
    async def _insert_pins(
        conn: AsyncConnection,
        *,
        execution_id: ExecutionId,
        node_id: ExecutionNodeId | None,
        pins: Sequence[ResolvedPin],
    ) -> None:
        for pin in pins:
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_pin (
                        execution_id, node_id, kind, key, version, digest,
                        resolved_status, metadata_json
                    )
                    VALUES (
                        :execution_id, :node_id, :kind, :key, :version, :digest,
                        :status, CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (execution_id, node_id, kind, key) DO NOTHING
                    """
                ),
                {
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "kind": pin.kind,
                    "key": pin.key,
                    "version": pin.version,
                    "digest": pin.digest,
                    "status": pin.status,
                    "metadata": serialize_value_json(pin.metadata),
                },
            )


def _tool_columns(spec: GraphNode) -> dict[str, object | None]:
    if isinstance(spec, ToolNode):
        return {
            "tool_name": spec.tool_name,
            "tool_version": spec.tool_version,
            "input_sha": spec.input_schema_sha256,
            "output_sha": spec.output_schema_sha256,
        }
    return {
        "tool_name": None,
        "tool_version": None,
        "input_sha": None,
        "output_sha": None,
    }


async def _insert_node(
    conn: AsyncConnection,
    *,
    execution_id: ExecutionId,
    spec: GraphNode,
    depth: int,
    definition: dict[str, object],
    declared_by_node_id: ExecutionNodeId | None = None,
    parameter_artifact_key: str | None = None,
    parameter_sha256: str | None = None,
) -> ExecutionNodeId:
    node_id = execution_node_id(execution_id, spec.node_key)
    operation_id = operation_id_from_key(str(execution_id), spec.node_key)
    tool = _tool_columns(spec)
    inserted = await conn.execute(
        text(
            """
            INSERT INTO execution_node (
                id, execution_id, node_key, kind, tool_name, tool_version, operation_id,
                input_schema_sha256, output_schema_sha256, display_params_json,
                parameter_artifact_key, parameter_sha256, declared_by_node_id,
                ordinal, depth, definition_json
            )
            VALUES (
                :id, :execution_id, :node_key, :kind, :tool_name, :tool_version, :operation_id,
                :input_sha, :output_sha, '{}'::jsonb,
                :parameter_artifact_key, :parameter_sha256, :declared_by,
                :ordinal, :depth, CAST(:definition AS jsonb)
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "id": node_id,
            "execution_id": execution_id,
            "node_key": spec.node_key,
            "kind": spec.kind.value,
            **tool,
            "operation_id": operation_id,
            "parameter_artifact_key": parameter_artifact_key,
            "parameter_sha256": parameter_sha256,
            "declared_by": declared_by_node_id,
            "ordinal": spec.ordinal,
            "depth": depth,
            "definition": serialize_value_json(definition),
        },
    )
    if inserted.rowcount != 1:
        existing = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT id, operation_id, definition_json
                        FROM execution_node
                        WHERE execution_id = :execution_id AND node_key = :node_key
                        """
                    ),
                    {"execution_id": execution_id, "node_key": spec.node_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            existing is None
            or str(existing["id"]) != str(node_id)
            or str(existing["operation_id"]) != str(operation_id)
            or decode_jsonb(existing["definition_json"]) != definition
        ):
            raise ExecutionConflict(f"node key {spec.node_key!r} was replayed differently")
    return node_id


async def _insert_edge(
    conn: AsyncConnection,
    *,
    execution_id: ExecutionId,
    from_key: str,
    to_key: str,
    edge_kind: EdgeKind,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO execution_edge (
                execution_id, from_node_id, to_node_id, edge_kind, binding_json
            )
            VALUES (
                :execution_id, :from_node_id, :to_node_id, :edge_kind, '{}'::jsonb
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "execution_id": execution_id,
            "from_node_id": execution_node_id(execution_id, from_key),
            "to_node_id": execution_node_id(execution_id, to_key),
            "edge_kind": edge_kind.value,
        },
    )


class RecipeExecutor:
    """One lease-owned deterministic DAG drive."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory,
        recipes: DbRecipeReader,
        compatibility: CompatibilityLoader,
        journal: DbExecutionJournal,
        parameters: ExecutionParameterStore,
        tool_invoker: ToolInvoker,
        controls: DbRunControlStore | None = None,
        activity_invoker: ActivityInvoker | None = None,
        crash_hook: CrashHook = _no_crash,
        max_concurrency: int = MAX_EXECUTION_CONCURRENCY,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("executor max concurrency must be positive")
        self._conn_factory = conn_factory
        self._recipes = recipes
        self._compatibility = compatibility
        self._journal = journal
        self._parameters = parameters
        self._tool_invoker = tool_invoker
        self._controls = controls
        self._activity_invoker = activity_invoker
        self._crash_hook = crash_hook
        self._max_concurrency = max_concurrency

    async def execute(
        self,
        execution_id: ExecutionId,
        *,
        worker_id: str,
        lease_generation: int,
        stop_requested: asyncio.Event | None = None,
        actor_id: str | None = None,
        action_ref: str | None = None,
    ) -> ExecutionRunResult:
        """Drive one execution to its next durable resting point.

        ``actor_id``/``action_ref`` carry the same ambient invocation identity as
        :meth:`invoke_interaction_tool` — the authenticated principal and the durable human act
        (``turn-action:<turn_id>``) this drive runs under — down to every node's
        :class:`~clue_toolbelt.ToolContext`. A drive that belongs to no turn (a scheduled fleet
        run, a recipe seeded outside a conversation) passes neither and every node sees ``None``:
        an absent receipt refuses a human gate, an invented one would forge consent.
        """

        runtime = await self._load_runtime(execution_id)
        root_parameters = await self._parameters.resolve(
            workspace_id=runtime.workspace_id,
            artifact_key=runtime.parameter_artifact_key,
            content_sha256=runtime.parameter_manifest_hash,
        )
        _assert_parameter_schema(root_parameters, runtime.definition.parameter_schema)
        stop = stop_requested or asyncio.Event()
        await self._recover(
            runtime,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        cursor = await self._cursor(execution_id)
        if cursor.status is ExecutionStatus.QUEUED:
            await self._append(
                runtime,
                event_type=ExecutionEventType.EXECUTION_STARTED,
                payload={},
                worker_id=worker_id,
                lease_generation=lease_generation,
            )

        replayed = tuple(sorted(await self._completed_keys(execution_id)))
        while True:
            cursor = await self._cursor(execution_id)
            if cursor.status in {
                ExecutionStatus.PAUSED,
                ExecutionStatus.AWAITING_INPUT,
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
            }:
                return ExecutionRunResult(
                    execution_id=execution_id,
                    status=cursor.status,
                    completed_node_keys=tuple(sorted(await self._completed_keys(execution_id))),
                    replayed_node_keys=replayed,
                )
            if stop.is_set():
                await self._append(
                    runtime,
                    event_type=ExecutionEventType.EXECUTION_PAUSED,
                    payload={"reason_code": "worker_stopping"},
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
                continue

            nodes = await self._load_nodes(execution_id)
            completed = await self._completed_keys(execution_id)
            failed = await self._failed_keys(execution_id)
            opened_gates = await self._event_node_keys(execution_id, "gate.opened")
            if failed:
                await self._append(
                    runtime,
                    event_type=ExecutionEventType.EXECUTION_FAILED,
                    payload={"reason_code": "node_failed", "node_keys": sorted(failed)},
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
                continue
            recovered = await self._event_node_keys(execution_id, "node.recovered")
            # A blocked INTERACTION child is answered, not pending: the agent called the tool
            # mid-turn, received the refusal as its answer (ruling T2-1) and moved on, and the
            # journal already holds ``node.blocked`` as that node's terminal outcome. Treating it
            # as unsettled re-dispatched it on every pass of this loop — a replay the journal
            # can only refuse — so the turn that made the call could never finish (incident
            # 2026-09-29). A blocked recipe-declared node keeps its meaning: awaiting input.
            settled = (
                completed | recovered | await self._answered_interaction_keys(execution_id, nodes)
            )
            if len(settled) == len(nodes):
                await self._append(
                    runtime,
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    payload={"node_count": len(nodes)},
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
                continue
            ready = [
                node
                for node in nodes
                if node.spec.node_key not in settled
                and set(node.spec.dependencies).issubset(completed)
                and not (isinstance(node.spec, GateNode) and node.spec.node_key in opened_gates)
            ]
            ready.sort(key=lambda item: (item.ordinal, item.spec.node_key))
            if not ready:
                waiting_gate = next(
                    (
                        node
                        for node in nodes
                        if isinstance(node.spec, GateNode)
                        and node.spec.node_key in opened_gates
                        and node.spec.node_key not in completed
                    ),
                    None,
                )
                if waiting_gate is not None:
                    waiting_spec = waiting_gate.spec
                    assert isinstance(waiting_spec, GateNode)
                    await self._append(
                        runtime,
                        event_type=ExecutionEventType.GATE_OPENED,
                        node_id=waiting_gate.node_id,
                        payload={
                            "authority": waiting_spec.authority,
                            "resume_condition": waiting_spec.resume_condition.value,
                            "reason_code": "awaiting_interaction",
                        },
                        worker_id=worker_id,
                        lease_generation=lease_generation,
                    )
                    continue
                await self._append(
                    runtime,
                    event_type=ExecutionEventType.EXECUTION_FAILED,
                    payload={"reason_code": "graph_stalled"},
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
                continue
            envelope = await self._effective_envelope(runtime)
            limit = min(envelope.max_fanout, self._max_concurrency)
            batch = ready[:limit]
            before = cursor.state_version
            await asyncio.gather(
                *(
                    self._execute_node(
                        runtime,
                        node,
                        root_parameters=root_parameters,
                        worker_id=worker_id,
                        lease_generation=lease_generation,
                        actor_id=actor_id,
                        action_ref=action_ref,
                    )
                    for node in batch
                )
            )
            # Every real dispatch writes at least one durable event (a start, a gate opening, a
            # terminal outcome). A pass that wrote none will be dispatched identically next pass,
            # forever, with nothing in any log: fail the execution loudly instead.
            if (await self._cursor(execution_id)).state_version == before:
                await self._append(
                    runtime,
                    event_type=ExecutionEventType.EXECUTION_FAILED,
                    payload={
                        "reason_code": "node_dispatch_made_no_progress",
                        "node_keys": sorted(node.spec.node_key for node in batch),
                    },
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )

    async def append_interaction_tool(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        slot_key: str,
        node_key: str,
        tool_name: str,
        tool_version: str,
        inputs: dict[str, JsonValue],
        actor: str,
        dependencies: Sequence[str] = (),
        pin_requests: Sequence[PinRequest] = (),
    ) -> InteractionAppend:
        """Append one exact tool beneath a promoted bounded interaction gate.

        The validated body is snapshotted before graph materialization and only its artifact
        key/hash enters the journal. Reusing ``node_key`` with the same immutable definition is a
        replay; changing its tool, body, actor, dependencies, or pins is a conflict.
        """
        runtime = await self._load_runtime(execution_id)
        if runtime.workspace_id != workspace_id:
            raise ValueError("execution is unknown or outside this workspace")
        by_key = {node.node_key: node for node in runtime.definition.graph.nodes}
        slot = by_key.get(slot_key)
        if not isinstance(slot, GateNode) or not slot.dynamic_tool_allowlist:
            raise ExecutionConflict("the requested node is not a dynamic interaction slot")
        address = f"{tool_name}@{tool_version}"
        if address not in slot.dynamic_tool_allowlist:
            raise ExecutionConflict(f"{address} is not allowed beneath interaction slot {slot_key}")
        if actor not in {"human", "agent"}:
            raise ValueError("interaction tool actor must be human or agent")
        envelope = await self._effective_envelope(runtime)
        descriptor = self._tool_invoker.descriptor(tool_name, tool_version)
        if not descriptor.recipe_safe:
            raise ExecutionConflict(f"{address} is not recipe-safe")
        validated = descriptor.input_model.model_validate(inputs).model_dump(mode="json")
        artifact_key, parameter_sha256 = await self._parameters.snapshot(
            workspace_id=runtime.workspace_id,
            parameters=cast(dict[str, JsonValue], validated),
        )
        static_requests = (
            *runtime.definition.compatibility.execution,
            *runtime.definition.compatibility.nodes.get(slot_key, ()),
        )
        static_kinds = {item.kind for item in static_requests}
        supplied_kinds = {item.kind for item in pin_requests}
        missing = set(descriptor.pin_requirements) - static_kinds - supplied_kinds
        if missing:
            raise ExecutionConflict(f"{address} is missing dynamic pin kinds: {sorted(missing)}")
        undeclared = supplied_kinds - set(slot.dynamic_pin_kinds)
        if undeclared:
            raise ExecutionConflict(
                f"dynamic pin kinds are absent from the promoted slot: {sorted(undeclared)}"
            )
        requirements = (*static_requests, *pin_requests)
        compatibility = await self._compatibility.resolve_requirements(
            requirements,
            context=CompatibilityContext(
                workspace_id=runtime.workspace_id,
                project_id=runtime.project_id,
            ),
        )
        if not compatibility.compatible:
            raise IncompatibleRecipe(compatibility)

        child_ordinal = slot.ordinal * 1_000_000
        definition: dict[str, object] = {
            "node": ToolNode(
                node_key=node_key,
                ordinal=child_ordinal,
                dependencies=tuple(dependencies),
                tool_name=tool_name,
                tool_version=tool_version,
                input_schema_sha256=descriptor.input_schema_sha256,
                output_schema_sha256=descriptor.output_schema_sha256,
            ).model_dump(mode="json"),
            "local_parameters": {},
            "compatibility_node_key": slot_key,
            "actor": actor,
            "dynamic_parameter": {
                "artifact_key": artifact_key,
                "content_sha256": parameter_sha256,
            },
            "dynamic_requirements": [item.model_dump(mode="json") for item in pin_requests],
        }
        node_id = execution_node_id(execution_id, node_key)
        operation_id = operation_id_from_key(str(execution_id), node_key)
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM execution WHERE id = :id FOR UPDATE"),
                {"id": execution_id},
            )
            slot_id = execution_node_id(execution_id, slot_key)
            existing = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, operation_id, parameter_artifact_key, parameter_sha256,
                                   definition_json
                            FROM execution_node
                            WHERE execution_id = :execution_id AND node_key = :node_key
                            """
                        ),
                        {"execution_id": execution_id, "node_key": node_key},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                stored_definition = decode_jsonb(existing["definition_json"])
                stored_node = stored_definition.get("node", {})
                if (
                    str(existing["id"]) != str(node_id)
                    or str(existing["operation_id"]) != str(operation_id)
                    or str(existing["parameter_artifact_key"]) != artifact_key
                    or str(existing["parameter_sha256"]) != parameter_sha256
                    or not isinstance(stored_node, Mapping)
                    or stored_node.get("node_key") != node_key
                    or stored_node.get("tool_name") != tool_name
                    or stored_node.get("tool_version") != tool_version
                    or tuple(stored_node.get("dependencies", ())) != tuple(dependencies)
                    or stored_definition.get("actor") != actor
                    or stored_definition.get("dynamic_parameter") != definition["dynamic_parameter"]
                    or stored_definition.get("dynamic_requirements")
                    != definition["dynamic_requirements"]
                ):
                    raise ExecutionConflict(
                        f"interaction node {node_key!r} was replayed with different inputs"
                    )
                return InteractionAppend(
                    execution_id=execution_id,
                    node_id=node_id,
                    operation_id=operation_id,
                    node_key=node_key,
                    created=False,
                )

            cursor = await get_cursor(conn, execution_id, for_update=True)
            if cursor.status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED}:
                raise ExecutionConflict("terminal executions cannot accept interaction children")
            slot_state = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            EXISTS (
                                SELECT 1 FROM execution_event
                                WHERE execution_id = :execution_id
                                  AND node_id = :slot_id
                                  AND event_type = 'gate.opened'
                            ) AS opened,
                            EXISTS (
                                SELECT 1 FROM execution_event
                                WHERE execution_id = :execution_id
                                  AND node_id = :slot_id
                                  AND event_type = 'node.completed'
                            ) AS completed
                        """
                    ),
                    {"execution_id": execution_id, "slot_id": slot_id},
                )
            ).one()
            if not bool(slot_state.opened) or bool(slot_state.completed):
                raise ExecutionConflict("the interaction slot is not accepting input")
            child_count = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*) FROM execution_node
                            WHERE execution_id = :execution_id
                              AND declared_by_node_id = :slot_id
                            """
                        ),
                        {"execution_id": execution_id, "slot_id": slot_id},
                    )
                ).scalar_one()
            )
            total_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM execution_node WHERE execution_id = :execution_id"
                        ),
                        {"execution_id": execution_id},
                    )
                ).scalar_one()
            )
            if child_count >= slot.max_children or total_count >= envelope.max_nodes:
                raise ExecutionConflict("the Stage-0 interaction/node ceiling is exhausted")
            known_dependencies = {
                str(row[0])
                for row in (
                    await conn.execute(
                        text(
                            """
                            SELECT node_key FROM execution_node
                            WHERE execution_id = :execution_id
                              AND node_key = ANY(CAST(:keys AS text[]))
                            """
                        ),
                        {"execution_id": execution_id, "keys": list(dependencies)},
                    )
                ).all()
            }
            if known_dependencies != set(dependencies):
                raise ExecutionConflict("interaction dependencies are missing from the execution")
            if dependencies:
                completed_dependencies = {
                    str(row[0])
                    for row in (
                        await conn.execute(
                            text(
                                """
                                SELECT n.node_key
                                FROM execution_node n
                                JOIN execution_event e ON e.node_id = n.id
                                WHERE n.execution_id = :execution_id
                                  AND n.node_key = ANY(CAST(:keys AS text[]))
                                  AND e.event_type = 'node.completed'
                                """
                            ),
                            {"execution_id": execution_id, "keys": list(dependencies)},
                        )
                    ).all()
                }
                if completed_dependencies != set(dependencies):
                    raise ExecutionConflict(
                        "interaction dependencies must already be durably completed"
                    )

            ordinal = child_ordinal + child_count + 1
            node_spec = ToolNode(
                node_key=node_key,
                ordinal=ordinal,
                dependencies=tuple(dependencies),
                tool_name=tool_name,
                tool_version=tool_version,
                input_schema_sha256=descriptor.input_schema_sha256,
                output_schema_sha256=descriptor.output_schema_sha256,
            )
            definition["node"] = node_spec.model_dump(mode="json")
            node_id = await _insert_node(
                conn,
                execution_id=execution_id,
                spec=node_spec,
                depth=1,
                definition=definition,
                declared_by_node_id=slot_id,
                parameter_artifact_key=artifact_key,
                parameter_sha256=parameter_sha256,
            )
            await _insert_edge(
                conn,
                execution_id=execution_id,
                from_key=slot_key,
                to_key=node_key,
                edge_kind=EdgeKind.PARENT,
            )
            for dependency in dependencies:
                await _insert_edge(
                    conn,
                    execution_id=execution_id,
                    from_key=dependency,
                    to_key=node_key,
                    edge_kind=EdgeKind.DEPENDENCY,
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_artifact_ref (
                        execution_id, node_id, workspace_id, artifact_key, role, content_sha256
                    )
                    VALUES (:execution_id, :node_id, :workspace_id, :artifact_key,
                            'parameter', :sha)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "workspace_id": runtime.workspace_id,
                    "artifact_key": artifact_key,
                    "sha": parameter_sha256,
                },
            )
            await DbExecutionStarter._insert_pins(
                conn,
                execution_id=execution_id,
                node_id=node_id,
                pins=compatibility.pins,
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                node_id=node_id,
                event_type=ExecutionEventType.NODE_SCHEDULED,
                actor=actor,
                payload={
                    "declared_by_node_id": str(slot_id),
                    "tool_address": address,
                    "parameter_artifact_key": artifact_key,
                    "parameter_sha256": parameter_sha256,
                    "ordinal": ordinal,
                    "depth": 1,
                },
                expected_state_version=cursor.state_version,
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            if cursor.status is ExecutionStatus.AWAITING_INPUT:
                await self._journal.append_event(
                    conn,
                    execution_id=execution_id,
                    event_type=ExecutionEventType.EXECUTION_RESUMED,
                    actor=actor,
                    payload={"reason_code": "interaction_child_appended"},
                    expected_state_version=cursor.state_version,
                )
        return InteractionAppend(
            execution_id=execution_id,
            node_id=node_id,
            operation_id=operation_id,
            node_key=node_key,
            created=True,
        )

    async def validate_interaction_repair(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        slot_key: str,
        failed_node_key: str,
        replacement_node_key: str,
        tool_address: str,
    ) -> None:
        """Validate an explicit retry before invoking the replacement tool."""
        await self._interaction_repair(
            execution_id=execution_id,
            workspace_id=workspace_id,
            slot_key=slot_key,
            failed_node_key=failed_node_key,
            replacement_node_key=replacement_node_key,
            tool_address=tool_address,
            commit=False,
        )

    async def resolve_interaction_failure(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        slot_key: str,
        failed_node_key: str,
        replacement_node_key: str,
        tool_address: str,
    ) -> None:
        """Append recovery only after the replacement has a durable successful receipt."""
        await self._interaction_repair(
            execution_id=execution_id,
            workspace_id=workspace_id,
            slot_key=slot_key,
            failed_node_key=failed_node_key,
            replacement_node_key=replacement_node_key,
            tool_address=tool_address,
            commit=True,
        )

    async def _interaction_repair(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        slot_key: str,
        failed_node_key: str,
        replacement_node_key: str,
        tool_address: str,
        commit: bool,
    ) -> None:
        runtime = await self._load_runtime(execution_id)
        if runtime.workspace_id != workspace_id:
            raise ExecutionConflict("repair is outside this workspace")
        if failed_node_key == replacement_node_key:
            raise ExecutionConflict("a repair requires a distinct replacement attempt")
        async with self._conn_factory() as conn:
            # Same lock order as interaction append; serialize competing repair declarations.
            await conn.execute(
                text("SELECT id FROM execution WHERE id=:id FOR UPDATE"), {"id": execution_id}
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            nodes = (
                (
                    await conn.execute(
                        text("""
                SELECT id, node_key, declared_by_node_id, definition_json FROM execution_node
                WHERE execution_id=:id AND node_key=ANY(CAST(:keys AS text[]))
            """),
                        {"id": execution_id, "keys": [failed_node_key, replacement_node_key]},
                    )
                )
                .mappings()
                .all()
            )
            by_key = {row["node_key"]: row for row in nodes}
            slot_id = execution_node_id(execution_id, slot_key)
            old = by_key.get(failed_node_key)
            if old is None:
                raise ExecutionConflict(
                    "retry_of must name an existing failed tool in this execution"
                )
            for key in (failed_node_key, replacement_node_key) if commit else (failed_node_key,):
                row = by_key.get(key)
                if row is None:
                    raise ExecutionConflict("replacement tool has no durable node")
                definition = row["definition_json"]
                node = definition["node"]
                address = f"{node.get('tool_name')}@{node.get('tool_version')}"
                if (
                    row["declared_by_node_id"] != slot_id
                    or address != tool_address
                    or definition.get("actor") != "agent"
                ):
                    raise ExecutionConflict("repair must remain in the same agent slot and tool")
            events = (
                (
                    await conn.execute(
                        text("""
                SELECT node_id, event_type, payload_json FROM execution_event
                WHERE execution_id=:id AND node_id=ANY(CAST(:nodes AS uuid[]))
                ORDER BY seq
            """),
                        {"id": execution_id, "nodes": [row["id"] for row in nodes]},
                    )
                )
                .mappings()
                .all()
            )
            if not any(
                e["node_id"] == old["id"] and e["event_type"] == "node.failed" for e in events
            ):
                raise ExecutionConflict("retry_of does not identify a failed attempt")
            prior = next(
                (
                    e
                    for e in events
                    if e["node_id"] == old["id"] and e["event_type"] == "node.recovered"
                ),
                None,
            )
            if prior is not None:
                if prior["payload_json"]["replacement_node_key"] != replacement_node_key:
                    raise ExecutionConflict("failed attempt already has another replacement")
                return
            # Repair is restricted to direct agent leaves. It cannot rewrite graph dependencies.
            dependents = (
                await conn.execute(
                    text("""
                SELECT 1 FROM execution_node WHERE execution_id=:id
                AND (definition_json->'node'->'dependencies') ? :key LIMIT 1
            """),
                    {"id": execution_id, "key": failed_node_key},
                )
            ).first()
            if dependents is not None:
                raise ExecutionConflict("failed node with dependents requires graph-level recovery")
            if not commit:
                return
            replacement = by_key[replacement_node_key]
            completed = any(
                e["node_id"] == replacement["id"] and e["event_type"] == "node.completed"
                for e in events
            )
            failed = any(
                e["node_id"] == replacement["id"] and e["event_type"] == "node.failed"
                for e in events
            )
            if not completed or failed:
                raise ExecutionConflict("replacement must have a successful durable tool receipt")
            if cursor.status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED}:
                raise ExecutionConflict("terminal execution cannot acquire a new repair")
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                node_id=old["id"],
                event_type=ExecutionEventType.NODE_RECOVERED,
                actor="agent",
                payload={
                    "replacement_node_key": replacement_node_key,
                    "replacement_node_id": str(replacement["id"]),
                    "tool_address": tool_address,
                },
                expected_state_version=cursor.state_version,
            )

    async def unresolved_interaction_failures(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        slot_key: str,
    ) -> tuple[str, ...]:
        runtime = await self._load_runtime(execution_id)
        if runtime.workspace_id != workspace_id:
            raise ExecutionConflict("execution is outside this workspace")
        failed = await self._failed_keys(execution_id)
        async with self._conn_factory() as conn:
            rows = (
                await conn.execute(
                    text("""
                SELECT node_key FROM execution_node WHERE execution_id=:id
                AND declared_by_node_id=:slot
            """),
                    {"id": execution_id, "slot": execution_node_id(execution_id, slot_key)},
                )
            ).all()
        return tuple(sorted(failed & {str(row[0]) for row in rows}))

    async def inspect_interaction_slot(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        slot_key: str,
    ) -> InteractionSlotView:
        """Return the exact C5 ceiling used for fail-before-effect agent plan validation."""

        runtime = await self._load_runtime(execution_id)
        if runtime.workspace_id != workspace_id:
            raise ValueError("execution is unknown or outside this workspace")
        slot = next(
            (node for node in runtime.definition.graph.nodes if node.node_key == slot_key),
            None,
        )
        if not isinstance(slot, GateNode) or not slot.dynamic_tool_allowlist:
            raise ExecutionConflict("the requested node is not a dynamic interaction slot")
        envelope = await self._effective_envelope(runtime)
        slot_id = execution_node_id(execution_id, slot_key)
        async with self._conn_factory() as conn:
            state = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            EXISTS (
                                SELECT 1 FROM execution_event
                                WHERE execution_id = :execution_id
                                  AND node_id = :slot_id
                                  AND event_type = 'gate.opened'
                            ) AS opened,
                            EXISTS (
                                SELECT 1 FROM execution_event
                                WHERE execution_id = :execution_id
                                  AND node_id = :slot_id
                                  AND event_type = 'node.completed'
                            ) AS completed,
                            (SELECT count(*) FROM execution_node
                             WHERE execution_id = :execution_id
                               AND declared_by_node_id = :slot_id) AS child_count,
                            (SELECT count(*) FROM execution_node
                             WHERE execution_id = :execution_id) AS node_count
                        """
                    ),
                    {"execution_id": execution_id, "slot_id": slot_id},
                )
            ).one()
        if not bool(state.opened) or bool(state.completed):
            raise ExecutionConflict("the interaction slot is not accepting input")
        requirements = (
            *runtime.definition.compatibility.execution,
            *runtime.definition.compatibility.nodes.get(slot_key, ()),
        )
        return InteractionSlotView(
            execution_id=execution_id,
            workspace_id=workspace_id,
            slot_key=slot_key,
            tool_allowlist=slot.dynamic_tool_allowlist,
            dynamic_pin_kinds=slot.dynamic_pin_kinds,
            requirements=tuple(requirements),
            max_children=slot.max_children,
            child_count=int(state.child_count),
            max_nodes=envelope.max_nodes,
            node_count=int(state.node_count),
        )

    async def invoke_interaction_tool(
        self,
        append: InteractionAppend,
        *,
        inputs: dict[str, JsonValue],
        actor: str,
        actor_id: str | None = None,
        action_ref: str | None = None,
    ) -> ToolResult:
        """Execute/replay one appended child through the mandatory tool journal.

        ``actor_id``/``action_ref`` are the *ambient* invocation identity (Lane D §3-P2): the
        authenticated principal this execution acts for, and the durable human act that authorized
        it (``turn-action:<turn_id>``). They are threaded as data by the caller that knows the turn
        — never read from a global — and stay ``None`` on a path that runs outside any turn, because
        a human gate must refuse rather than be handed a fabricated receipt.
        """
        runtime = await self._load_runtime(append.execution_id)
        nodes = {node.spec.node_key: node for node in await self._load_nodes(append.execution_id)}
        node = nodes.get(append.node_key)
        if node is None or not isinstance(node.spec, ToolNode):
            raise ExecutionConflict("the appended interaction tool disappeared")
        if actor != node.actor:
            raise ExecutionConflict("interaction tool actor differs from its durable declaration")
        if node.spec.node_key in await self._event_node_keys(append.execution_id, "node.recovered"):
            raise ExecutionConflict(
                "this failed attempt was recovered; use its replacement receipt"
            )
        if node.parameter_artifact_key is None or node.parameter_sha256 is None:
            raise ExecutionConflict("the appended interaction tool has no durable parameter body")
        durable_inputs = await self._parameters.resolve(
            workspace_id=runtime.workspace_id,
            artifact_key=node.parameter_artifact_key,
            content_sha256=node.parameter_sha256,
        )
        descriptor = self._tool_invoker.descriptor(node.spec.tool_name, node.spec.tool_version)
        supplied = descriptor.input_model.model_validate(inputs).model_dump(mode="json")
        durable = descriptor.input_model.model_validate(durable_inputs).model_dump(mode="json")
        if _canonical_bytes(supplied) != _canonical_bytes(durable):
            raise ExecutionConflict(
                "interaction tool inputs differ from its durable parameter artifact"
            )
        result = await self._tool_invoker.invoke(
            node.spec.tool_name,
            cast(dict[str, object], durable),
            ToolContext(
                workspace_id=runtime.workspace_id,
                project_id=runtime.project_id,
                actor="human" if node.actor == "human" else "agent",
                conn_factory=self._conn_factory,
                operation_id=node.operation_id,
                # B4 x D1 join: the *invoker* of a model-planned (agent) node is the execution
                # worker — a service principal — while the human's authority rides the ambient
                # turn-derived ``action_ref`` (resolving it yields the submitting user). A
                # human-authority node keeps the turn's human ``actor_id`` (legacy kind: the C5
                # seam carries no membership, which ``principal_kind='human'`` would require).
                principal_kind="service" if node.actor != "human" else None,
                actor_id="svc_execution_worker" if node.actor != "human" else actor_id,
                action_ref=action_ref,
                execution_id=runtime.execution_id,
                parent_execution_id=runtime.parent_execution_id,
                execution_node_id=node.node_id,
                execution_node_key=node.spec.node_key,
            ),
            version=node.spec.tool_version,
        )
        await self._return_to_interaction_slot(runtime, node)
        return result

    async def _return_to_interaction_slot(self, runtime: _Runtime, node: _Node) -> None:
        slot_key = node.compatibility_node_key
        slot = next(
            (
                candidate
                for candidate in runtime.definition.graph.nodes
                if candidate.node_key == slot_key
            ),
            None,
        )
        if not isinstance(slot, GateNode) or not slot.dynamic_tool_allowlist:
            return
        async with self._conn_factory() as conn:
            cursor = await get_cursor(conn, runtime.execution_id, for_update=True)
            if cursor.status in {
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
                ExecutionStatus.AWAITING_INPUT,
            }:
                return
            await self._journal.append_event(
                conn,
                execution_id=runtime.execution_id,
                node_id=execution_node_id(runtime.execution_id, slot_key),
                event_type=ExecutionEventType.GATE_OPENED,
                actor=node.actor,
                payload={
                    "authority": slot.authority,
                    "resume_condition": slot.resume_condition.value,
                    "reason_code": "interaction_child_completed",
                },
                expected_state_version=cursor.state_version,
            )

    async def pause(
        self,
        *,
        execution_id: ExecutionId,
        actor: str,
        reason_code: str,
    ) -> None:
        await self._load_runtime(execution_id)
        cursor = await self._cursor(execution_id)
        if cursor.status is ExecutionStatus.PAUSED:
            return
        if cursor.status not in {ExecutionStatus.RUNNING, ExecutionStatus.QUEUED}:
            raise ExecutionConflict("only queued or running executions can be paused")
        async with self._conn_factory() as conn:
            locked = await get_cursor(conn, execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                event_type=ExecutionEventType.EXECUTION_PAUSED,
                actor=actor,
                payload={"reason_code": reason_code},
                expected_state_version=locked.state_version,
            )

    async def resume(self, *, execution_id: ExecutionId, actor: str) -> None:
        resumed = await self._resume(
            execution_id=execution_id,
            actor=actor,
            required_reason_code=None,
        )
        if not resumed:
            raise ExecutionConflict(
                "only explicitly paused executions can resume; gates require a gate decision"
            )

    async def resume_if_paused_for(
        self,
        *,
        execution_id: ExecutionId,
        actor: str,
        reason_code: str,
    ) -> bool:
        """Resume only the exact system pause named by ``reason_code``.

        External provider waits use this on a fresh fleet offer. Human pauses and gates retain
        their existing explicit authority because a different or absent reason is a no-op.
        """

        return await self._resume(
            execution_id=execution_id,
            actor=actor,
            required_reason_code=reason_code,
        )

    async def _resume(
        self,
        *,
        execution_id: ExecutionId,
        actor: str,
        required_reason_code: str | None,
    ) -> bool:
        await self._load_runtime(execution_id)
        async with self._conn_factory() as conn:
            cursor = await get_cursor(conn, execution_id, for_update=True)
            if cursor.status is not ExecutionStatus.PAUSED:
                return False
            if required_reason_code is not None:
                raw_payload = (
                    await conn.execute(
                        text(
                            """
                            SELECT payload_json
                            FROM execution_event
                            WHERE execution_id = :execution_id
                              AND node_id IS NULL
                              AND event_type = 'execution.paused'
                            ORDER BY seq DESC
                            LIMIT 1
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                ).scalar_one_or_none()
                payload = decode_jsonb(raw_payload) if raw_payload is not None else {}
                if payload.get("reason_code") != required_reason_code:
                    return False
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                event_type=ExecutionEventType.EXECUTION_RESUMED,
                actor=actor,
                expected_state_version=cursor.state_version,
            )
        return True

    async def decide_gate(
        self,
        *,
        execution_id: ExecutionId,
        node_key: str,
        actor: str,
        decision: str,
    ) -> None:
        await self._load_runtime(execution_id)
        nodes = {node.spec.node_key: node for node in await self._load_nodes(execution_id)}
        node = nodes.get(node_key)
        if node is None or not isinstance(node.spec, GateNode):
            raise ValueError("gate node is unknown")
        if actor != node.spec.authority:
            raise ExecutionConflict(
                f"gate requires authority {node.spec.authority!r}, not {actor!r}"
            )
        async with self._conn_factory() as conn:
            opened = bool(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM execution_event
                                WHERE execution_id = :execution_id AND node_id = :node_id
                                  AND event_type = 'gate.opened'
                            )
                            """
                        ),
                        {"execution_id": execution_id, "node_id": node.node_id},
                    )
                ).scalar_one()
            )
            completed = (
                await conn.execute(
                    text(
                        """
                        SELECT 1 FROM execution_event
                        WHERE execution_id = :execution_id AND node_id = :node_id
                          AND event_type = 'node.completed'
                        """
                    ),
                    {"execution_id": execution_id, "node_id": node.node_id},
                )
            ).one_or_none()
            prior_decision = (
                await conn.execute(
                    text(
                        """
                        SELECT payload_json->>'decision'
                        FROM execution_event
                        WHERE execution_id = :execution_id AND node_id = :node_id
                          AND event_type = 'gate.decided'
                        ORDER BY seq DESC LIMIT 1
                        """
                    ),
                    {"execution_id": execution_id, "node_id": node.node_id},
                )
            ).scalar_one_or_none()
            if completed is not None and prior_decision == decision:
                return
            if completed is not None and prior_decision != decision:
                raise ExecutionConflict("gate already has a different terminal decision")
            if not opened:
                raise ExecutionConflict("gate is not awaiting a decision")
            attempt = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(max(attempt), 0) + 1 "
                            "FROM execution_attempt WHERE node_id = :node_id"
                        ),
                        {"node_id": node.node_id},
                    )
                ).scalar_one()
            )
            attempt_id = ExecutionAttemptId(uuid4())
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_attempt (
                        id, execution_id, node_id, attempt, worker_id
                    )
                    VALUES (:id, :execution_id, :node_id, :attempt, :worker_id)
                    """
                ),
                {
                    "id": attempt_id,
                    "execution_id": execution_id,
                    "node_id": node.node_id,
                    "attempt": attempt,
                    "worker_id": f"gate:{actor}",
                },
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                node_id=node.node_id,
                attempt_id=attempt_id,
                event_type=ExecutionEventType.NODE_STARTED,
                actor=actor,
                payload={"attempt": attempt},
                expected_state_version=cursor.state_version,
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                node_id=node.node_id,
                attempt_id=attempt_id,
                event_type=ExecutionEventType.GATE_DECIDED,
                actor=actor,
                payload={"decision": decision},
                expected_state_version=cursor.state_version,
            )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                node_id=node.node_id,
                attempt_id=attempt_id,
                event_type=ExecutionEventType.NODE_COMPLETED,
                actor=actor,
                payload={"references": {"decision": decision}},
                expected_state_version=cursor.state_version,
            )
        # The decision and gate completion commit atomically. A worker/control-process crash
        # after this boundary must therefore replay as the same terminal decision and never
        # reopen the gate.
        await self._crash_hook("gate_decided", execution_id, node.node_id)

    async def _execute_node(
        self,
        runtime: _Runtime,
        node: _Node,
        *,
        root_parameters: dict[str, JsonValue],
        worker_id: str,
        lease_generation: int,
        actor_id: str | None = None,
        action_ref: str | None = None,
    ) -> None:
        compatibility_context = CompatibilityContext(
            workspace_id=runtime.workspace_id,
            project_id=runtime.project_id,
        )
        if node.dynamic_requirements:
            report = await self._compatibility.resolve_requirements(
                (
                    *runtime.definition.compatibility.execution,
                    *runtime.definition.compatibility.nodes.get(node.compatibility_node_key, ()),
                    *node.dynamic_requirements,
                ),
                context=compatibility_context,
            )
        else:
            report = await self._compatibility.recheck_node(
                runtime.definition.compatibility,
                node_key=node.compatibility_node_key,
                context=compatibility_context,
            )
        if not report.compatible:
            await self._append(
                runtime,
                event_type=ExecutionEventType.EXECUTION_PAUSED,
                node_id=node.node_id,
                payload={
                    "reason_code": "compatibility_changed",
                    "incompatibilities": [
                        item.model_dump(mode="json") for item in report.incompatibilities
                    ],
                },
                worker_id=worker_id,
                lease_generation=lease_generation,
            )
            return
        if isinstance(node.spec, GateNode):
            await self._append(
                runtime,
                event_type=ExecutionEventType.GATE_OPENED,
                node_id=node.node_id,
                payload={
                    "authority": node.spec.authority,
                    "resume_condition": node.spec.resume_condition.value,
                },
                worker_id=worker_id,
                lease_generation=lease_generation,
            )
            return
        if isinstance(node.spec, ToolNode):
            body = await self._resolve_bindings(
                runtime,
                node,
                root_parameters=root_parameters,
            )
            try:
                await self._tool_invoker.invoke(
                    node.spec.tool_name,
                    body,
                    ToolContext(
                        workspace_id=runtime.workspace_id,
                        project_id=runtime.project_id,
                        actor="human" if node.actor == "human" else "agent",
                        conn_factory=self._conn_factory,
                        operation_id=node.operation_id,
                        # B4 x D1 join: see the comment at the interaction-tool site above —
                        # service invoker for agent nodes, human authority via ``action_ref``.
                        principal_kind="service" if node.actor != "human" else None,
                        actor_id="svc_execution_worker" if node.actor != "human" else actor_id,
                        action_ref=action_ref,
                        execution_id=runtime.execution_id,
                        parent_execution_id=runtime.parent_execution_id,
                        execution_node_id=node.node_id,
                        execution_node_key=node.spec.node_key,
                        execution_worker_id=worker_id,
                        lease_generation=lease_generation,
                    ),
                    version=node.spec.tool_version,
                )
            except Exception:
                # ToolInvoker has already journaled blocked/failed. The drive loop projects that
                # durable state instead of converting a tool fault into a fleet-shell crash.
                return
            return

        attempt_id = await self._reserve_attempt(
            runtime,
            node,
            worker_id=worker_id,
            lease_generation=lease_generation,
        )
        await self._crash_hook("attempt_started", runtime.execution_id, node.node_id)
        try:
            if isinstance(node.spec, BarrierNode):
                references: dict[str, JsonValue] = {}
            elif isinstance(node.spec, MapNode):
                references = await self._expand_map(
                    runtime,
                    node,
                    root_parameters=root_parameters,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                )
            elif isinstance(node.spec, ActivityNode):
                if self._activity_invoker is None:
                    raise ExecutionError(
                        f"no activity invoker registered for {node.spec.activity_address}"
                    )
                body = await self._resolve_bindings(
                    runtime,
                    node,
                    root_parameters=root_parameters,
                )
                references = await self._activity_invoker.invoke(
                    activity_name=node.spec.activity_name,
                    activity_version=node.spec.activity_version,
                    parameters=body,
                    context=ToolContext(
                        workspace_id=runtime.workspace_id,
                        project_id=runtime.project_id,
                        actor="human" if node.actor == "human" else "agent",
                        conn_factory=self._conn_factory,
                        operation_id=node.operation_id,
                        # B4 x D1 join: see the comment at the interaction-tool site above —
                        # service invoker for agent nodes, human authority via ``action_ref``.
                        principal_kind="service" if node.actor != "human" else None,
                        actor_id="svc_execution_worker" if node.actor != "human" else actor_id,
                        action_ref=action_ref,
                        execution_id=runtime.execution_id,
                        parent_execution_id=runtime.parent_execution_id,
                        execution_node_id=node.node_id,
                        execution_node_key=node.spec.node_key,
                        execution_worker_id=worker_id,
                        lease_generation=lease_generation,
                    ),
                )
            else:  # pragma: no cover - closed union
                raise AssertionError(f"unhandled node kind {node.spec.kind}")
        except Exception as exc:
            await self._append(
                runtime,
                event_type=ExecutionEventType.NODE_FAILED,
                node_id=node.node_id,
                attempt_id=attempt_id,
                payload={"error_code": type(exc).__name__.lower()},
                worker_id=worker_id,
                lease_generation=lease_generation,
            )
            return
        await self._append(
            runtime,
            event_type=ExecutionEventType.NODE_COMPLETED,
            node_id=node.node_id,
            attempt_id=attempt_id,
            payload={"references": references},
            worker_id=worker_id,
            lease_generation=lease_generation,
        )

    async def _reserve_attempt(
        self,
        runtime: _Runtime,
        node: _Node,
        *,
        worker_id: str,
        lease_generation: int,
    ) -> ExecutionAttemptId:
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM execution_node WHERE id = :id FOR UPDATE"),
                {"id": node.node_id},
            )
            attempt = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(max(attempt), 0) + 1 "
                            "FROM execution_attempt WHERE node_id = :node_id"
                        ),
                        {"node_id": node.node_id},
                    )
                ).scalar_one()
            )
            attempt_id = ExecutionAttemptId(uuid4())
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_attempt (
                        id, execution_id, node_id, attempt, worker_id, lease_generation
                    )
                    VALUES (:id, :execution_id, :node_id, :attempt, :worker_id, :generation)
                    """
                ),
                {
                    "id": attempt_id,
                    "execution_id": runtime.execution_id,
                    "node_id": node.node_id,
                    "attempt": attempt,
                    "worker_id": worker_id,
                    "generation": lease_generation,
                },
            )
            cursor = await get_cursor(conn, runtime.execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=runtime.execution_id,
                node_id=node.node_id,
                attempt_id=attempt_id,
                event_type=ExecutionEventType.NODE_STARTED,
                actor="system",
                payload={"attempt": attempt},
                expected_state_version=cursor.state_version,
                expected_worker_id=worker_id,
                expected_lease_generation=lease_generation,
            )
        return attempt_id

    async def _expand_map(
        self,
        runtime: _Runtime,
        node: _Node,
        *,
        root_parameters: dict[str, JsonValue],
        worker_id: str,
        lease_generation: int,
    ) -> dict[str, JsonValue]:
        assert isinstance(node.spec, MapNode)
        source = await self._resolve_binding(
            runtime,
            node.spec.source,
            root_parameters=root_parameters,
            local_parameters=node.local_parameters,
        )
        if not isinstance(source, list):
            raise ValueError("map source must resolve to an array")
        ordered = sorted(source, key=lambda item: _canonical_bytes(item))
        if len(ordered) > node.spec.max_items:
            raise ValueError("map source exceeds its declared max_items")
        envelope = await self._effective_envelope(runtime)
        if node.depth + 1 > envelope.max_depth:
            raise ValueError("map expansion exceeds the effective max_depth envelope")
        child_keys: list[str] = []
        async with self._conn_factory() as conn:
            existing_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM execution_node WHERE execution_id = :execution_id"
                        ),
                        {"execution_id": runtime.execution_id},
                    )
                ).scalar_one()
            )
            requested = len(ordered) * len(node.spec.template)
            if existing_count + requested > envelope.max_nodes:
                raise ValueError("map expansion exceeds the effective max_nodes envelope")
            for index, item in enumerate(ordered):
                translated = {
                    template.node_key: (f"{node.spec.node_key}.{index:06d}.{template.node_key}")
                    for template in node.spec.template
                }
                for template in sorted(
                    node.spec.template,
                    key=lambda spec: (spec.ordinal, spec.node_key),
                ):
                    dependencies = tuple(
                        [node.spec.node_key]
                        + [translated[dependency] for dependency in template.dependencies]
                    )
                    child_key = translated[template.node_key]
                    translated_bindings = (
                        {
                            name: (
                                binding.model_copy(
                                    update={"node_key": translated[binding.node_key]}
                                )
                                if isinstance(binding, NodeReferenceBinding)
                                and binding.node_key in translated
                                else binding
                            )
                            for name, binding in template.bindings.items()
                        }
                        if isinstance(template, ToolNode | ActivityNode)
                        else None
                    )
                    update: dict[str, object] = {
                        "node_key": child_key,
                        "dependencies": dependencies,
                        "ordinal": node.spec.ordinal * 1_000_000 + index * 1_000 + template.ordinal,
                    }
                    if translated_bindings is not None:
                        update["bindings"] = translated_bindings
                    child = template.model_copy(update=update)
                    child_id = await _insert_node(
                        conn,
                        execution_id=runtime.execution_id,
                        spec=child,
                        depth=node.depth + 1,
                        definition={
                            "node": child.model_dump(mode="json"),
                            "local_parameters": {node.spec.item_parameter: item},
                            # Dynamic child keys are execution-local. Their exact requirements
                            # were promoted and pinned under the declaring map node.
                            "compatibility_node_key": node.spec.node_key,
                        },
                        declared_by_node_id=node.node_id,
                    )
                    child_keys.append(child_key)
                    await _insert_edge(
                        conn,
                        execution_id=runtime.execution_id,
                        from_key=node.spec.node_key,
                        to_key=child_key,
                        edge_kind=EdgeKind.PARENT,
                    )
                    for dependency in dependencies[1:]:
                        await _insert_edge(
                            conn,
                            execution_id=runtime.execution_id,
                            from_key=dependency,
                            to_key=child_key,
                            edge_kind=EdgeKind.DEPENDENCY,
                        )
                    cursor = await get_cursor(conn, runtime.execution_id, for_update=True)
                    await self._journal.append_event(
                        conn,
                        execution_id=runtime.execution_id,
                        node_id=child_id,
                        event_type=ExecutionEventType.NODE_SCHEDULED,
                        actor="system",
                        payload={
                            "declared_by_node_id": str(node.node_id),
                            "ordinal": child.ordinal,
                            "depth": node.depth + 1,
                        },
                        expected_state_version=cursor.state_version,
                        expected_worker_id=worker_id,
                        expected_lease_generation=lease_generation,
                    )
            await self._crash_hook("map_expanded", runtime.execution_id, node.node_id)
        return {"child_node_keys": cast(JsonValue, child_keys)}

    async def _effective_envelope(self, runtime: _Runtime) -> EffectiveEnvelope:
        if self._controls is not None:
            return await self._controls.effective_envelope(runtime.execution_id)
        return EffectiveEnvelope(
            max_nodes=runtime.definition.max_nodes,
            max_depth=runtime.definition.max_depth,
            max_fanout=runtime.definition.max_fanout,
        )

    async def _resolve_bindings(
        self,
        runtime: _Runtime,
        node: _Node,
        *,
        root_parameters: dict[str, JsonValue],
    ) -> dict[str, object]:
        if node.parameter_artifact_key is not None:
            if node.parameter_sha256 is None:
                raise ExecutionConflict("dynamic parameter artifact is missing its digest")
            return cast(
                dict[str, object],
                await self._parameters.resolve(
                    workspace_id=runtime.workspace_id,
                    artifact_key=node.parameter_artifact_key,
                    content_sha256=node.parameter_sha256,
                ),
            )
        bindings = node.spec.bindings if isinstance(node.spec, ToolNode | ActivityNode) else {}
        return {
            name: await self._resolve_binding(
                runtime,
                binding,
                root_parameters=root_parameters,
                local_parameters=node.local_parameters,
            )
            for name, binding in bindings.items()
        }

    async def _resolve_binding(
        self,
        runtime: _Runtime,
        binding: Binding,
        *,
        root_parameters: dict[str, JsonValue],
        local_parameters: dict[str, JsonValue],
    ) -> object:
        if isinstance(binding, LiteralBinding):
            return binding.value
        if isinstance(binding, ParameterBinding):
            if binding.name in local_parameters:
                return local_parameters[binding.name]
            if binding.name not in root_parameters:
                raise ValueError(f"parameter {binding.name!r} is unavailable")
            return root_parameters[binding.name]
        assert isinstance(binding, NodeReferenceBinding)
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT payload_json FROM execution_event
                            WHERE execution_id = :execution_id
                              AND node_id = :node_id
                              AND event_type = 'node.completed'
                            ORDER BY seq DESC LIMIT 1
                            """
                        ),
                        {
                            "execution_id": runtime.execution_id,
                            "node_id": execution_node_id(
                                runtime.execution_id,
                                binding.node_key,
                            ),
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ValueError(f"reference node {binding.node_key!r} is not completed")
        payload: object = decode_jsonb(row["payload_json"])
        if isinstance(payload, Mapping) and "result" in payload:
            result = payload["result"]
            if isinstance(result, Mapping):
                payload = result.get("references", {})
        elif isinstance(payload, Mapping):
            payload = payload.get("references", {})
        for part in binding.reference_path:
            if not isinstance(payload, Mapping) or part not in payload:
                raise ValueError(
                    f"reference path {binding.reference_path!r} is absent "
                    f"from node {binding.node_key!r}"
                )
            payload = payload[part]
        return payload

    async def _recover(
        self,
        runtime: _Runtime,
        *,
        worker_id: str,
        lease_generation: int,
    ) -> None:
        async with self._conn_factory() as conn:
            await rebuild_cursor(
                conn,
                runtime.execution_id,
                expected_worker_id=worker_id,
                expected_lease_generation=lease_generation,
            )
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT a.id AS attempt_id, a.node_id
                            FROM execution_attempt a
                            WHERE a.execution_id = :execution_id
                              AND EXISTS (
                                  SELECT 1 FROM execution_event e
                                  WHERE e.attempt_id = a.id
                                    AND e.event_type = 'node.started'
                              )
                              AND NOT EXISTS (
                                  SELECT 1 FROM execution_event e
                                  WHERE e.attempt_id = a.id
                                    AND e.event_type IN (
                                        'node.completed', 'node.blocked',
                                        'node.failed', 'node.abandoned'
                                    )
                              )
                            ORDER BY a.started_at, a.id
                            """
                        ),
                        {"execution_id": runtime.execution_id},
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                cursor = await get_cursor(conn, runtime.execution_id, for_update=True)
                await self._journal.append_event(
                    conn,
                    execution_id=runtime.execution_id,
                    node_id=ExecutionNodeId(row["node_id"]),
                    attempt_id=ExecutionAttemptId(row["attempt_id"]),
                    event_type=ExecutionEventType.NODE_ABANDONED,
                    actor="system",
                    payload={"reason_code": "worker_recovery"},
                    expected_state_version=cursor.state_version,
                    expected_worker_id=worker_id,
                    expected_lease_generation=lease_generation,
                )

    async def _append(
        self,
        runtime: _Runtime,
        *,
        event_type: ExecutionEventType,
        payload: dict[str, object],
        worker_id: str,
        lease_generation: int,
        node_id: ExecutionNodeId | None = None,
        attempt_id: ExecutionAttemptId | None = None,
    ) -> None:
        async with self._conn_factory() as conn:
            cursor = await get_cursor(conn, runtime.execution_id, for_update=True)
            await self._journal.append_event(
                conn,
                execution_id=runtime.execution_id,
                node_id=node_id,
                attempt_id=attempt_id,
                event_type=event_type,
                actor="system",
                payload=payload,
                expected_state_version=cursor.state_version,
                expected_worker_id=worker_id,
                expected_lease_generation=lease_generation,
            )

    async def _load_runtime(self, execution_id: ExecutionId) -> _Runtime:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT workspace_id, project_id, project_run_id, parent_execution_id,
                                   recipe_revision_id, parameter_artifact_key,
                                   parameter_manifest_hash
                            FROM execution WHERE id = :execution_id
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or row["recipe_revision_id"] is None:
            raise ValueError("execution is unknown or is not recipe-backed")
        if row["parameter_artifact_key"] is None:
            raise ValueError("recipe execution has no parameter artifact")
        workspace_id = str(row["workspace_id"])
        revision = await self._recipes.get_revision(
            recipe_revision_id=RecipeRevisionId(row["recipe_revision_id"]),
            workspace_id=workspace_id,
        )
        if revision is None:
            raise ValueError("execution recipe revision is unavailable")
        definition = revision.definition()
        if definition.graph.migration_state != "executable":
            raise PlaceholderRecipe("placeholder recipes are not executable")
        return _Runtime(
            execution_id=execution_id,
            parent_execution_id=(
                ExecutionId(row["parent_execution_id"])
                if row["parent_execution_id"] is not None
                else None
            ),
            workspace_id=workspace_id,
            project_id=str(row["project_id"]) if row["project_id"] is not None else None,
            project_run_id=(
                ProjectRunId(row["project_run_id"]) if row["project_run_id"] is not None else None
            ),
            parameter_artifact_key=str(row["parameter_artifact_key"]),
            parameter_manifest_hash=str(row["parameter_manifest_hash"]),
            revision=revision,
            definition=definition,
        )

    async def _load_nodes(self, execution_id: ExecutionId) -> tuple[_Node, ...]:
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, operation_id, ordinal, depth, parameter_artifact_key,
                                   parameter_sha256, definition_json
                            FROM execution_node
                            WHERE execution_id = :execution_id
                            ORDER BY ordinal, node_key
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
        nodes: list[_Node] = []
        for row in rows:
            definition = decode_jsonb(row["definition_json"])
            node_raw = definition.get("node")
            local_raw = definition.get("local_parameters", {})
            compatibility_key = definition.get("compatibility_node_key")
            actor = definition.get("actor", "agent")
            dynamic_requirements_raw = definition.get("dynamic_requirements", [])
            if (
                not isinstance(node_raw, Mapping)
                or not isinstance(local_raw, Mapping)
                or (compatibility_key is not None and not isinstance(compatibility_key, str))
                or actor not in {"human", "agent", "system"}
                or not isinstance(dynamic_requirements_raw, list)
            ):
                raise ExecutionConflict("materialized node definition is malformed")
            try:
                dynamic_requirements = tuple(
                    PinRequest.model_validate(item) for item in dynamic_requirements_raw
                )
            except Exception as exc:
                raise ExecutionConflict(
                    "materialized dynamic compatibility requirements are malformed"
                ) from exc
            nodes.append(
                _Node(
                    node_id=ExecutionNodeId(row["id"]),
                    operation_id=OperationId(row["operation_id"]),
                    ordinal=int(row["ordinal"]),
                    depth=int(row["depth"]),
                    # The immutable definition crossed a JSONB boundary. Strict graph models
                    # intentionally require tuples in Python, while JSON arrays are the correct
                    # wire representation; validate in JSON mode so that distinction is honored.
                    spec=_GRAPH_NODE.validate_json(_canonical_bytes(node_raw)),
                    local_parameters=dict(local_raw),
                    compatibility_node_key=(
                        compatibility_key
                        if isinstance(compatibility_key, str)
                        else str(node_raw["node_key"])
                    ),
                    actor=str(actor),
                    parameter_artifact_key=(
                        str(row["parameter_artifact_key"])
                        if row["parameter_artifact_key"] is not None
                        else None
                    ),
                    parameter_sha256=(
                        str(row["parameter_sha256"])
                        if row["parameter_sha256"] is not None
                        else None
                    ),
                    dynamic_requirements=dynamic_requirements,
                )
            )
        return tuple(nodes)

    async def _completed_keys(self, execution_id: ExecutionId) -> set[str]:
        return await self._event_node_keys(execution_id, "node.completed")

    async def _answered_interaction_keys(
        self, execution_id: ExecutionId, nodes: Sequence[_Node]
    ) -> set[str]:
        """Interaction children (an agent's tool calls through a gate slot) that ended blocked."""
        gates = {node.spec.node_key for node in nodes if isinstance(node.spec, GateNode)}
        children = {
            node.spec.node_key
            for node in nodes
            if isinstance(node.spec, ToolNode) and node.compatibility_node_key in gates
        }
        if not children:
            return set()
        return children & await self._event_node_keys(execution_id, "node.blocked")

    async def _failed_keys(self, execution_id: ExecutionId) -> set[str]:
        failed = await self._event_node_keys(execution_id, "node.failed")
        recovered = await self._event_node_keys(execution_id, "node.recovered")
        return failed - recovered

    async def _event_node_keys(self, execution_id: ExecutionId, event_type: str) -> set[str]:
        async with self._conn_factory() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT DISTINCT n.node_key
                        FROM execution_event e
                        JOIN execution_node n ON n.id = e.node_id
                        WHERE e.execution_id = :execution_id
                          AND e.event_type = :event_type
                        """
                    ),
                    {"execution_id": execution_id, "event_type": event_type},
                )
            ).all()
        return {str(row[0]) for row in rows}

    async def _cursor(self, execution_id: ExecutionId) -> ExecutionCursor:
        async with self._conn_factory() as conn:
            return await get_cursor(conn, execution_id)


__all__ = [
    "ActivityInvoker",
    "CrashHook",
    "DbExecutionStarter",
    "ExecutionConflict",
    "ExecutionError",
    "ExecutionParameterStore",
    "ExecutionRunResult",
    "ExecutionStart",
    "IncompatibleRecipe",
    "PlaceholderRecipe",
    "RecipeExecutor",
    "SUPPORTED_EXECUTOR_PROTOCOL",
    "execution_node_id",
]
