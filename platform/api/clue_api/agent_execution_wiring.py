"""C6.4 composition: whole-plan C5 compilation and governed tool execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import (
    AsyncIterator,
    Callable,
    Mapping,
)
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from types import MappingProxyType
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, JsonValue
from sqlalchemy import text

from clue_agents import (
    AgentConstitution,
    AgentExecutionAdapter,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentPlanIssue,
    AgentPlanPolicy,
    AgentPlanRejected,
    AgentProfileRegistry,
    AgentRole,
    ArtifactRef,
    DelegationRequest,
    DelegationResult,
    DomainObjectRef,
    GovernedOperationReceipt,
    ResolvedAgentProfile,
    ValidatedOperation,
    ValidatedPlan,
    authority_sha256,
    operation_id_for_plan_node,
    review_agent_plan,
)
from clue_agents.contracts import (
    MODEL_FORBIDDEN_AUTHORITY_KEYS,
    PlanDelegationStep,
    PlanToolStep,
)
from clue_agents.execution import SPILL_THRESHOLD_BYTES, spill_stub
from clue_agents.ports import ExecutionProgress, OperationFailure, SpillSink
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_tool_context import tool_context_for_internal_service
from clue_api.client_context_authority import (
    client_kb_version_for_input_model,
    trusted_client_kb_version_fields,
)
from clue_api.client_knowledge_privacy import client_knowledge_result_subject_bindings
from clue_api.context_observability import record_context_tool_outcome
from clue_api.product_context_authority import (
    product_scope_for_input_model,
    trusted_product_scope_fields,
)
from clue_api.product_knowledge_privacy import product_knowledge_result_subject_bindings
from clue_api.stage0_recipe import RecipeStep, StepPinProvider
from clue_api.turn_action import derive_turn_action_ref
from clue_api.turn_binding import (
    CapturedTurn,
    CapturedTurnSource,
    CapturedTurnUnavailable,
    trusted_turn_fields,
)
from clue_core import ExecutionId, OperationId
from clue_db import ConnFactory, database_url, transaction
from clue_execution import (
    BarrierNode,
    Binding,
    GraphIssue,
    InteractionSlotView,
    ParameterBinding,
    PinRequest,
    RecipeExecutor,
    RecipeGraph,
    ToolNode,
    validate_graph,
)
from clue_obs import get_logger
from clue_toolbelt import (
    PreconditionFailed,
    ToolInvoker,
    ToolRegistry,
    ToolResult,
)
from clue_toolbelt.runner import validate_tool_result

__all__ = [
    "AgentExecutionCrashHook",
    "C5AgentExecutionAdapter",
    "CheckpointerFactory",
    "DbAgentDelegationRuntime",
    "DbAgentPlanJournal",
    "FreshWakeChildRunner",
    "postgres_agent_checkpointer",
]

_PLAN_EVENT_NAMESPACE = UUID("30b976d6-032a-56a4-933a-e02db79f01cb")
_DELEGATION_EVENT_NAMESPACE = UUID("d273c199-9435-5dc5-b5d2-5b28d41051d7")
_CHILD_EXECUTION_NAMESPACE = UUID("ce926286-e065-5c98-9d57-c8af598bb87e")
log = get_logger("clue_api.agent_execution")


class AgentExecutionCrashHook(Protocol):
    async def __call__(
        self,
        point: str,
        *,
        execution_id: ExecutionId,
        node_key: str | None,
    ) -> None: ...


async def _no_crash(
    _point: str,
    *,
    execution_id: ExecutionId,
    node_key: str | None,
) -> None:
    del execution_id, node_key


_DEFAULT_CRASH_HOOK = cast(AgentExecutionCrashHook, _no_crash)

# A refusal sentence is model feedback, not a log dump: enough to name what was wrong, bounded so a
# pathological traceback-in-a-message cannot dominate the next model call's context.
_FAILURE_MESSAGE_LIMIT = 600


def _failure_message(error: BaseException) -> str:
    if isinstance(error, PreconditionFailed):
        # A precondition refusal states its codes in ``str()`` and *what to do about it* only in
        # the per-failure messages, which is the half a model can act on.
        text_value = "; ".join(
            f"{failure.reason_code}: {failure.message}" for failure in error.failures
        ) or str(error)
    else:
        text_value = str(error) or type(error).__name__
    collapsed = " ".join(text_value.split())
    if len(collapsed) <= _FAILURE_MESSAGE_LIMIT:
        return collapsed
    return f"{collapsed[:_FAILURE_MESSAGE_LIMIT]}…"


def _operation_failure(
    operation: ValidatedOperation,
    error: BaseException,
) -> OperationFailure:
    return OperationFailure(
        node_key=operation.node_key,
        address=operation.address,
        error_type=type(error).__name__,
        message=_failure_message(error),
    )


class FreshWakeChildRunner(Protocol):
    """C6.6 supplies the specialist mind; C6.4 owns authority and durable lifecycle."""

    async def run(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        resolved_profile: ResolvedAgentProfile,
    ) -> DelegationResult: ...


CheckpointerFactory = Callable[
    [ExecutionId],
    AbstractAsyncContextManager[BaseCheckpointSaver[str]],
]


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://",
        "postgresql://",
    )


@asynccontextmanager
async def postgres_agent_checkpointer(
    _execution_id: ExecutionId,
) -> AsyncIterator[BaseCheckpointSaver[str]]:
    """Yield the production async-Postgres checkpointer used by the agent loop.

    LangGraph owns its checkpoint tables and installs them idempotently.  The
    execution id is carried in the graph configuration as ``thread_id``; it is
    accepted here so this function satisfies the execution-scoped factory seam.
    """

    async with AsyncPostgresSaver.from_conn_string(_psycopg_dsn(database_url())) as saver:
        await ensure_checkpoint_tables(saver)
        yield saver


async def ensure_checkpoint_tables(saver: AsyncPostgresSaver) -> None:
    """Run LangGraph's ``setup()`` only when the database is behind the installed library.

    The tables are created by an Alembic migration as the owner (``4a94970221e9``). Production
    opens this saver as ``clue_worker``, which has no CREATE on schema public, and ``setup()``
    always issues ``CREATE TABLE IF NOT EXISTS`` — PostgreSQL checks the schema privilege before
    existence — so calling it unconditionally failed every turn (2026-10-03). A database the
    migration has not reached, or one behind a newer LangGraph, still gets ``setup()``.
    """

    latest = len(saver.MIGRATIONS) - 1
    try:
        # LangGraph's own read in setup(); its connections return dict rows.
        query = "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
        if isinstance(saver.conn, AsyncConnectionPool):
            async with saver.conn.connection() as pooled:
                row = await (await pooled.execute(query)).fetchone()
        else:
            row = await (await saver.conn.execute(query)).fetchone()
        recorded = row["v"] if row is not None else None
    except psycopg.errors.UndefinedTable:
        recorded = None
    if recorded is None or recorded < latest:
        await saver.setup()


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _rewrite_refs(value: object, prefix: str) -> object:
    if isinstance(value, dict):
        rewritten: dict[str, object] = {}
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str) and child.startswith("#/$defs/"):
                rewritten[key] = f"#/$defs/{prefix}_{child.removeprefix('#/$defs/')}"
            else:
                rewritten[key] = _rewrite_refs(child, prefix)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_refs(item, prefix) for item in value]
    return value


def _trusted_authority(constitution: AgentConstitution) -> dict[str, JsonValue]:
    """The authority values a tool body may receive, sourced only from the constitution.

    A ``None`` here is *not* a value: ``_trusted_tool_arguments`` skips it, so a tool that requires
    the field is refused by its own validator instead of being served a fabricated scope.
    """

    return {
        "actor_id": constitution.actor_id,
        "brand_id": constitution.brand_id,
        "client_entity_id": constitution.client_entity_id,
        "execution_id": str(constitution.execution_id),
        "project_id": constitution.project_id,
        "workspace_id": constitution.workspace_id,
    }


def _trusted_tool_arguments(
    *,
    arguments: Mapping[str, JsonValue],
    input_model: type[BaseModel],
    constitution: AgentConstitution,
    captured_turn: CapturedTurn | None = None,
) -> dict[str, JsonValue]:
    """Merge trusted authority into the model-proposed arguments of one tool step.

    A tool input model may declare an authority field (the Stage-0 tools declare ``project_id``),
    but the model neither sees it (the governed wrapper hides it from the model-visible schema)
    nor may propose it (``PlanToolStep.arguments`` rejects the key). The value therefore comes
    from exactly one place: the trusted :class:`AgentConstitution` this adapter is bound to.

    Authority the constitution does not carry (``operation_id``, ``parent_execution_id``) is
    deliberately not synthesized — such a field stays absent and its own model decides whether
    that is valid.

    Per-turn authority (PC-C8 §6) merges the same way from a different trusted source: a field
    marked :data:`~clue_api.turn_binding.TRUSTED_TURN_FIELD` is served from ``captured_turn``, the
    binding compiled from this turn's own artifact and capture record. A tool that declares such a
    field and reaches an execution with no binding is refused here rather than executed against
    whatever the model happened to send — which is the point: a forged or foreign
    ``onboarding_input_id`` has no path into the call.
    """

    merged = dict(arguments)
    supplied = MODEL_FORBIDDEN_AUTHORITY_KEYS & set(merged)
    if supplied:
        # Defence in depth: PlanToolStep already refuses these keys.
        raise ValueError(f"plan arguments carry trusted authority: {sorted(supplied)}")
    turn_fields = trusted_turn_fields(input_model)
    client_kb_version_fields = trusted_client_kb_version_fields(input_model)
    product_scope_fields = trusted_product_scope_fields(input_model)
    proposed_turn = set(turn_fields) & set(merged)
    if proposed_turn:
        raise ValueError(f"plan arguments carry trusted turn authority: {sorted(proposed_turn)}")
    proposed_client_kb_version = set(client_kb_version_fields) & set(merged)
    if proposed_client_kb_version:
        raise ValueError(
            "plan arguments carry trusted Client-KB authority: "
            f"{sorted(proposed_client_kb_version)}"
        )
    proposed_product_scope = set(product_scope_fields) & set(merged)
    if proposed_product_scope:
        raise ValueError(
            f"plan arguments carry trusted Product-KB authority: {sorted(proposed_product_scope)}"
        )
    authority = _trusted_authority(constitution)
    for key in MODEL_FORBIDDEN_AUTHORITY_KEYS & set(input_model.model_fields):
        value = authority.get(key)
        if value is not None:
            merged[key] = value
    for key in turn_fields:
        if captured_turn is None:
            raise CapturedTurnUnavailable(
                f"{key!r} is served from this turn's captured input, which is unavailable",
                reason_code="no_binding",
            )
        merged[key] = captured_turn.value_for(key)
    client_kb_version = client_kb_version_for_input_model(constitution, input_model)
    if client_kb_version is not None:
        for key in client_kb_version_fields:
            merged[key] = client_kb_version
    product_scope = product_scope_for_input_model(constitution, input_model)
    if product_scope is not None:
        product_id, product_kb_version = product_scope
        for key in product_scope_fields:
            if key == "product_id":
                merged[key] = product_id
            elif key == "product_kb_version":
                merged[key] = product_kb_version
    return merged


def _plan_graph_and_parameters(
    *,
    plan: AgentPlan,
    tools: ToolRegistry,
    slot: InteractionSlotView,
    arguments: Mapping[str, Mapping[str, JsonValue]],
    pin_requests: Mapping[str, tuple[PinRequest, ...]] = MappingProxyType({}),
) -> tuple[RecipeGraph, dict[str, JsonValue], dict[str, object]]:
    """Translate the full proposal into C5's closed graph/binding language.

    ``pin_requests`` carries the per-step artifact-level pins already resolved for this plan, and
    they are attached to each ``ToolNode.requirements`` — the same field a recipe's own step pins
    land on. ``validate_graph`` reads exactly that field when it checks a descriptor's
    ``pin_requirements``, so a tool whose per-turn pins are dynamic (Stage-0's
    ``record_interview_answer`` needs an ``artifact_input`` derived from its own arguments) is
    reviewed against the pins it will actually execute with, not against an empty set.
    """

    nodes: list[ToolNode | BarrierNode] = []
    parameters: dict[str, JsonValue] = {}
    properties: dict[str, object] = {}
    definitions: dict[str, object] = {}
    for ordinal, step in enumerate(plan.steps):
        if isinstance(step, PlanDelegationStep):
            nodes.append(
                BarrierNode(
                    node_key=step.node_key,
                    ordinal=ordinal,
                    dependencies=step.depends_on,
                )
            )
            continue
        descriptor = tools.descriptor(step.tool.name, step.tool.version)
        step_arguments = arguments[step.node_key]
        validated = descriptor.input_model.model_validate(step_arguments).model_dump(mode="json")
        input_schema = descriptor.input_model.model_json_schema()
        input_properties = input_schema.get("properties", {})
        if not isinstance(input_properties, Mapping):
            raise ValueError(f"{descriptor.address} input schema has no object properties")
        prefix = f"n{ordinal}"
        defs = input_schema.get("$defs", {})
        if isinstance(defs, Mapping):
            for name, definition in defs.items():
                definitions[f"{prefix}_{name}"] = _rewrite_refs(definition, prefix)
        bindings: dict[str, Binding] = {}
        for input_name, input_value in validated.items():
            parameter_name = f"p_{ordinal}_{input_name}"
            source_schema = input_properties.get(input_name)
            if not isinstance(source_schema, Mapping):
                raise ValueError(f"{descriptor.address} validated undeclared input {input_name!r}")
            properties[parameter_name] = _rewrite_refs(dict(source_schema), prefix)
            parameters[parameter_name] = cast(JsonValue, input_value)
            bindings[input_name] = ParameterBinding(
                kind="parameter",
                name=parameter_name,
            )
        nodes.append(
            ToolNode(
                node_key=step.node_key,
                ordinal=ordinal,
                dependencies=step.depends_on,
                tool_name=step.tool.name,
                tool_version=step.tool.version,
                input_schema_sha256=step.tool.input_schema_sha256,
                output_schema_sha256=step.tool.output_schema_sha256,
                bindings=bindings,
                requirements=tuple(pin_requests.get(step.node_key, ())),
            )
        )
    parameter_schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
    }
    if definitions:
        parameter_schema["$defs"] = definitions
    graph = RecipeGraph(
        nodes=tuple(nodes),
        tool_allowlist=tuple(sorted(set(slot.tool_allowlist))),
    )
    return graph, parameters, parameter_schema


class DbAgentPlanJournal:
    """Append-only plan/operation/result journal; bodies remain artifact-backed."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def record_validated(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        role: AgentRole,
        plan: ValidatedPlan,
        proposal_ref: ArtifactRef,
    ) -> None:
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO agent_plan (
                        id, turn_id, execution_id, workspace_id, role,
                        proposal_artifact_key, proposal_sha256,
                        validated_artifact_key, validated_sha256,
                        resource_manifest_sha256, max_parallelism,
                        estimated_cost_millicents, budget_limit_millicents,
                        budget_mode, validated_at
                    )
                    VALUES (
                        :id, :turn, :execution, :workspace, :role,
                        :proposal_key, :proposal_sha, :validated_key, :validated_sha,
                        :manifest_sha, :parallelism, :estimated, :budget,
                        :budget_mode, :validated_at
                    )
                    ON CONFLICT (id) DO NOTHING RETURNING id
                    """
                ),
                {
                    "id": plan.plan_id,
                    "turn": turn_id,
                    "execution": plan.execution_id,
                    "workspace": workspace_id,
                    "role": role.value,
                    "proposal_key": proposal_ref.artifact_key,
                    "proposal_sha": proposal_ref.sha256,
                    "validated_key": plan.validated_plan_artifact_ref.artifact_key,
                    "validated_sha": plan.validated_plan_artifact_ref.sha256,
                    "manifest_sha": plan.resource_manifest_sha256,
                    "parallelism": plan.max_parallelism,
                    "estimated": plan.estimated_cost_millicents,
                    "budget": plan.budget_limit_millicents,
                    "budget_mode": plan.budget_mode,
                    "validated_at": plan.validated_at,
                },
            )
            if inserted.first() is None:
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT turn_id, execution_id, workspace_id, role, "
                                "proposal_artifact_key, proposal_sha256, validated_artifact_key, "
                                "validated_sha256, resource_manifest_sha256, max_parallelism, "
                                "estimated_cost_millicents, budget_limit_millicents, "
                                "budget_mode, validated_at "
                                "FROM agent_plan WHERE id=:id"
                            ),
                            {"id": plan.plan_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                expected = (
                    turn_id,
                    plan.execution_id,
                    workspace_id,
                    role.value,
                    proposal_ref.artifact_key,
                    proposal_ref.sha256,
                    plan.validated_plan_artifact_ref.artifact_key,
                    plan.validated_plan_artifact_ref.sha256,
                    plan.resource_manifest_sha256,
                    plan.max_parallelism,
                    plan.estimated_cost_millicents,
                    plan.budget_limit_millicents,
                    plan.budget_mode,
                    plan.validated_at,
                )
                actual = (
                    row["turn_id"],
                    row["execution_id"],
                    row["workspace_id"],
                    row["role"],
                    row["proposal_artifact_key"],
                    row["proposal_sha256"],
                    row["validated_artifact_key"],
                    row["validated_sha256"],
                    row["resource_manifest_sha256"],
                    int(row["max_parallelism"]),
                    int(row["estimated_cost_millicents"]),
                    int(row["budget_limit_millicents"]),
                    row["budget_mode"],
                    row["validated_at"],
                )
                if actual != expected:
                    raise ValueError("plan id already has different immutable validation")
                return
            for ordinal, operation in enumerate(plan.operations):
                await conn.execute(
                    text(
                        """
                        INSERT INTO agent_plan_operation (
                            plan_id, workspace_id, ordinal, node_key, operation_id, kind,
                            address, parameter_artifact_key, parameter_sha256,
                            estimated_cost_millicents, authority_sha256
                        )
                        VALUES (
                            :plan, :workspace, :ordinal, :node, :operation, :kind, :address,
                            :parameter_key, :parameter_sha, :estimated, :authority
                        )
                        """
                    ),
                    {
                        "plan": plan.plan_id,
                        "workspace": workspace_id,
                        "ordinal": ordinal,
                        "node": operation.node_key,
                        "operation": operation.operation_id,
                        "kind": operation.kind,
                        "address": operation.address,
                        "parameter_key": operation.parameter_artifact_ref.artifact_key,
                        "parameter_sha": operation.parameter_sha256,
                        "estimated": operation.estimated_cost_millicents,
                        "authority": operation.authority_sha256,
                    },
                )
                for dependency_ordinal, dependency in enumerate(operation.depends_on):
                    await conn.execute(
                        text(
                            """
                            INSERT INTO agent_plan_dependency (
                                plan_id, workspace_id, node_key, dependency_node_key, ordinal
                            )
                            VALUES (:plan, :workspace, :node, :dependency, :ordinal)
                            """
                        ),
                        {
                            "plan": plan.plan_id,
                            "workspace": workspace_id,
                            "node": operation.node_key,
                            "dependency": dependency,
                            "ordinal": dependency_ordinal,
                        },
                    )
            await self._event(
                conn,
                plan_id=plan.plan_id,
                workspace_id=workspace_id,
                status="validated",
            )

    async def event(
        self,
        *,
        plan_id: UUID,
        workspace_id: str,
        status: str,
        reason_code: str | None = None,
    ) -> None:
        async with self._conn_factory() as conn:
            await self._event(
                conn,
                plan_id=plan_id,
                workspace_id=workspace_id,
                status=status,
                reason_code=reason_code,
            )

    @staticmethod
    async def _event(
        conn: object,
        *,
        plan_id: UUID,
        workspace_id: str,
        status: str,
        reason_code: str | None = None,
    ) -> None:
        await conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO agent_plan_event "
                "(event_id, plan_id, workspace_id, status, reason_code) "
                "VALUES (:id, :plan, :workspace, :status, :reason) "
                "ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "id": uuid5(_PLAN_EVENT_NAMESPACE, f"{plan_id}:{status}"),
                "plan": plan_id,
                "workspace": workspace_id,
                "status": status,
                "reason": reason_code,
            },
        )

    async def record_tool_result(
        self,
        *,
        plan_id: UUID,
        workspace_id: str,
        operation: ValidatedOperation,
        result: ToolResult,
        result_ref: ArtifactRef,
    ) -> None:
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO agent_tool_result (
                        operation_id, plan_id, node_key, workspace_id, tool_address,
                        result_artifact_key, result_sha256, replayed, reference_count
                    )
                    VALUES (
                        :operation, :plan, :node, :workspace, :tool,
                        :artifact, :sha, :replayed, :count
                    )
                    ON CONFLICT (operation_id) DO NOTHING RETURNING operation_id
                    """
                ),
                {
                    "operation": operation.operation_id,
                    "plan": plan_id,
                    "node": operation.node_key,
                    "workspace": workspace_id,
                    "tool": operation.address,
                    "artifact": result_ref.artifact_key,
                    "sha": result_ref.sha256,
                    "replayed": result.replayed,
                    "count": len(result.references),
                },
            )
            if inserted.first() is None:
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT plan_id, node_key, workspace_id, tool_address, "
                                "result_artifact_key, result_sha256 "
                                "FROM agent_tool_result WHERE operation_id=:operation"
                            ),
                            {"operation": operation.operation_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    row["plan_id"] != plan_id
                    or row["node_key"] != operation.node_key
                    or row["workspace_id"] != workspace_id
                    or row["tool_address"] != operation.address
                    or row["result_artifact_key"] != result_ref.artifact_key
                    or row["result_sha256"] != result_ref.sha256
                ):
                    raise ValueError("operation result already has a different durable target")

    async def load_receipts(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
    ) -> tuple[GovernedOperationReceipt, ...]:
        async with self._conn_factory() as conn:
            tool_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT p.validated_at, o.ordinal, o.node_key, o.operation_id,
                                   o.kind, o.address,
                                   r.result_artifact_key, r.result_sha256, a.media_type,
                                   a.size_bytes, r.replayed
                            FROM agent_plan_operation o
                            JOIN agent_plan p ON p.id=o.plan_id
                            LEFT JOIN agent_tool_result r ON r.operation_id=o.operation_id
                            LEFT JOIN artifact a ON a.storage_key=r.result_artifact_key
                            WHERE p.execution_id=:execution AND p.workspace_id=:workspace
                              AND r.operation_id IS NOT NULL
                            ORDER BY p.validated_at, o.ordinal
                            """
                        ),
                        {"execution": execution_id, "workspace": workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            delegation_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT p.validated_at, o.ordinal, o.node_key, o.operation_id,
                                   o.kind, o.address, d.id AS delegation_id,
                                   r.status, r.finalization_artifact_key,
                                   r.finalization_sha256, a.media_type, a.size_bytes
                            FROM agent_plan_operation o
                            JOIN agent_plan p ON p.id=o.plan_id
                            JOIN agent_delegation d
                              ON d.plan_id=o.plan_id AND d.node_key=o.node_key
                            JOIN agent_delegation_result r ON r.delegation_id=d.id
                            JOIN artifact a ON a.storage_key=r.finalization_artifact_key
                            WHERE p.execution_id=:execution AND p.workspace_id=:workspace
                            ORDER BY p.validated_at, o.ordinal
                            """
                        ),
                        {"execution": execution_id, "workspace": workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            recovered: list[tuple[datetime, int, GovernedOperationReceipt]] = [
                (
                    row["validated_at"],
                    int(row["ordinal"]),
                    GovernedOperationReceipt(
                        node_key=row["node_key"],
                        operation_id=row["operation_id"],
                        kind=row["kind"],
                        address=row["address"],
                        status=AgentExecutionStatus.COMPLETED,
                        replayed=bool(row["replayed"]),
                        artifact_refs=(
                            ArtifactRef(
                                workspace_id=workspace_id,
                                artifact_key=row["result_artifact_key"],
                                sha256=row["result_sha256"],
                                media_type=row["media_type"],
                                byte_count=int(row["size_bytes"]),
                            ),
                        ),
                    ),
                )
                for row in tool_rows
            ]
            for row in delegation_rows:
                output_rows = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT o.artifact_key, o.artifact_sha256,
                                       a.media_type, a.size_bytes
                                FROM agent_delegation_output_ref o
                                JOIN artifact a ON a.storage_key=o.artifact_key
                                WHERE o.delegation_id=:id ORDER BY o.ordinal
                                """
                            ),
                            {"id": row["delegation_id"]},
                        )
                    )
                    .mappings()
                    .all()
                )
                domain_rows = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT object_type, object_id, object_version
                                FROM agent_delegation_domain_ref
                                WHERE delegation_id=:id AND ref_role='result'
                                ORDER BY ordinal
                                """
                            ),
                            {"id": row["delegation_id"]},
                        )
                    )
                    .mappings()
                    .all()
                )
                recovered.append(
                    (
                        row["validated_at"],
                        int(row["ordinal"]),
                        GovernedOperationReceipt(
                            node_key=row["node_key"],
                            operation_id=row["operation_id"],
                            kind="delegation",
                            address=row["address"],
                            status=AgentExecutionStatus(row["status"]),
                            artifact_refs=(
                                *(
                                    ArtifactRef(
                                        workspace_id=workspace_id,
                                        artifact_key=item["artifact_key"],
                                        sha256=item["artifact_sha256"],
                                        media_type=item["media_type"],
                                        byte_count=int(item["size_bytes"]),
                                    )
                                    for item in output_rows
                                ),
                                ArtifactRef(
                                    workspace_id=workspace_id,
                                    artifact_key=row["finalization_artifact_key"],
                                    sha256=row["finalization_sha256"],
                                    media_type=row["media_type"],
                                    byte_count=int(row["size_bytes"]),
                                ),
                            ),
                            domain_refs=tuple(
                                DomainObjectRef(
                                    workspace_id=workspace_id,
                                    object_type=item["object_type"],
                                    object_id=item["object_id"],
                                    version=item["object_version"],
                                )
                                for item in domain_rows
                            ),
                        ),
                    )
                )
        return tuple(
            item[2]
            for item in sorted(
                recovered,
                key=lambda item: (item[0], item[1]),
            )
        )


class DbAgentDelegationRuntime:
    """Persist parent authority before a fresh child wake and accept reference-only results."""

    def __init__(
        self,
        *,
        registry: AgentProfileRegistry,
        child_runner: FreshWakeChildRunner,
        conn_factory: ConnFactory = transaction,
        crash_hook: AgentExecutionCrashHook = _DEFAULT_CRASH_HOOK,
    ) -> None:
        self._registry = registry
        self._child_runner = child_runner
        self._conn_factory = conn_factory
        self._crash_hook = crash_hook

    def resolve_child(
        self,
        *,
        parent: ResolvedAgentProfile,
        child_role: AgentRole,
        current_depth: int,
    ) -> ResolvedAgentProfile:
        return self._registry.resolve_delegation(
            parent=parent,
            child_role=child_role,
            current_depth=current_depth,
        )

    async def run(
        self,
        *,
        plan_id: UUID,
        node_key: str,
        operation_id: UUID,
        turn_id: UUID,
        request: DelegationRequest,
        parent_profile: ResolvedAgentProfile,
    ) -> DelegationResult:
        child_profile = self.resolve_child(
            parent=parent_profile,
            child_role=request.subagent_role,
            current_depth=request.depth - 1,
        )
        child_execution_id = ExecutionId(
            uuid5(_CHILD_EXECUTION_NAMESPACE, str(request.delegation_id))
        )
        if any(
            not any(
                path == prefix or path.startswith(f"{prefix}/")
                for prefix in child_profile.profile.workspace.readable_prefixes
            )
            for path in request.granted_paths
        ):
            raise ValueError("delegation path grant exceeds the resolved child authority")
        await self._record_request(
            plan_id=plan_id,
            node_key=node_key,
            operation_id=operation_id,
            turn_id=turn_id,
            child_execution_id=child_execution_id,
            request=request,
        )
        existing = await self._existing_result(request)
        if existing is not None:
            return existing
        await self._crash_hook(
            "child_start",
            execution_id=request.parent_execution_id,
            node_key=node_key,
        )
        await self._event(request, "child_started")
        try:
            result = await self._child_runner.run(
                request=request,
                child_execution_id=child_execution_id,
                resolved_profile=child_profile,
            )
        except BaseException:
            await self._event(request, "failed", reason_code="child_failed")
            raise
        if (
            result.delegation_id != request.delegation_id
            or result.parent_execution_id != request.parent_execution_id
            or result.child_execution_id != child_execution_id
        ):
            raise ValueError("child returned a result for a different delegation identity")
        await self._record_result(request=request, result=result)
        await self._event(
            request,
            result.status,
            spend_millicents=result.spend_millicents,
        )
        await self._crash_hook(
            "child_complete",
            execution_id=request.parent_execution_id,
            node_key=node_key,
        )
        return result

    async def _existing_result(
        self,
        request: DelegationRequest,
    ) -> DelegationResult | None:
        """Recover a completed child without waking it a second time."""

        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT r.child_execution_id, r.status, r.spend_millicents,
                                   r.completed_at, r.finalization_artifact_key,
                                   r.finalization_sha256, a.media_type, a.size_bytes
                            FROM agent_delegation_result r
                            JOIN artifact a
                              ON a.storage_key=r.finalization_artifact_key
                            WHERE r.delegation_id=:id AND r.workspace_id=:workspace
                            """
                        ),
                        {
                            "id": request.delegation_id,
                            "workspace": request.task_artifact_ref.workspace_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            output_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT o.artifact_key, o.artifact_sha256,
                                   a.media_type, a.size_bytes
                            FROM agent_delegation_output_ref o
                            JOIN artifact a ON a.storage_key=o.artifact_key
                            WHERE o.delegation_id=:id
                            ORDER BY o.ordinal
                            """
                        ),
                        {"id": request.delegation_id},
                    )
                )
                .mappings()
                .all()
            )
            domain_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT object_type, object_id, object_version
                            FROM agent_delegation_domain_ref
                            WHERE delegation_id=:id AND ref_role='result'
                            ORDER BY ordinal
                            """
                        ),
                        {"id": request.delegation_id},
                    )
                )
                .mappings()
                .all()
            )
        workspace_id = request.task_artifact_ref.workspace_id
        return DelegationResult(
            delegation_id=request.delegation_id,
            parent_execution_id=request.parent_execution_id,
            child_execution_id=ExecutionId(row["child_execution_id"]),
            status=row["status"],
            output_refs=tuple(
                ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=item["artifact_key"],
                    sha256=item["artifact_sha256"],
                    media_type=item["media_type"],
                    byte_count=int(item["size_bytes"]),
                )
                for item in output_rows
            ),
            domain_refs=tuple(
                DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type=item["object_type"],
                    object_id=item["object_id"],
                    version=item["object_version"],
                )
                for item in domain_rows
            ),
            finalization_ref=ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=row["finalization_artifact_key"],
                sha256=row["finalization_sha256"],
                media_type=row["media_type"],
                byte_count=int(row["size_bytes"]),
            ),
            spend_millicents=int(row["spend_millicents"]),
            completed_at=row["completed_at"],
        )

    async def _record_request(
        self,
        *,
        plan_id: UUID,
        node_key: str,
        operation_id: UUID,
        turn_id: UUID,
        child_execution_id: ExecutionId,
        request: DelegationRequest,
    ) -> None:
        workspace_id = request.task_artifact_ref.workspace_id
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO agent_delegation (
                        id, plan_id, node_key, operation_id, turn_id, workspace_id,
                        parent_execution_id, child_execution_id, parent_role, child_role,
                        task_artifact_key, task_sha256,
                        child_budget_artifact_key, child_budget_sha256,
                        resource_manifest_key, resource_manifest_artifact_sha256,
                        resource_manifest_sha256, depth
                    )
                    VALUES (
                        :id, :plan, :node, :operation, :turn, :workspace,
                        :parent_execution, :child_execution, :parent_role, :child_role,
                        :task_key, :task_sha, :budget_key, :budget_sha,
                        :manifest_key, :manifest_artifact_sha, :manifest_sha, :depth
                    )
                    ON CONFLICT (id) DO NOTHING RETURNING id
                    """
                ),
                {
                    "id": request.delegation_id,
                    "plan": plan_id,
                    "node": node_key,
                    "operation": operation_id,
                    "turn": turn_id,
                    "workspace": workspace_id,
                    "parent_execution": request.parent_execution_id,
                    "child_execution": child_execution_id,
                    "parent_role": request.parent_role.value,
                    "child_role": request.subagent_role.value,
                    "task_key": request.task_artifact_ref.artifact_key,
                    "task_sha": request.task_artifact_ref.sha256,
                    "budget_key": request.child_budget_envelope_ref.artifact_key,
                    "budget_sha": request.child_budget_envelope_ref.sha256,
                    "manifest_key": request.resource_manifest_ref.artifact_key,
                    "manifest_artifact_sha": request.resource_manifest_ref.sha256,
                    "manifest_sha": request.resource_manifest_sha256,
                    "depth": request.depth,
                },
            )
            if inserted.first() is not None:
                for ordinal, path in enumerate(request.granted_paths):
                    await conn.execute(
                        text(
                            "INSERT INTO agent_delegation_path_grant "
                            "(delegation_id, workspace_id, ordinal, path) "
                            "VALUES (:id, :workspace, :ordinal, :path)"
                        ),
                        {
                            "id": request.delegation_id,
                            "workspace": workspace_id,
                            "ordinal": ordinal,
                            "path": path,
                        },
                    )
                for ordinal, ref in enumerate(request.domain_refs):
                    await conn.execute(
                        text(
                            "INSERT INTO agent_delegation_domain_ref "
                            "(delegation_id, workspace_id, ref_role, ordinal, object_type, "
                            " object_id, object_version) "
                            "VALUES (:id, :workspace, 'grant', :ordinal, :type, :object, :version)"
                        ),
                        {
                            "id": request.delegation_id,
                            "workspace": workspace_id,
                            "ordinal": ordinal,
                            "type": ref.object_type,
                            "object": ref.object_id,
                            "version": ref.version,
                        },
                    )
                await self._event_conn(conn, request, "requested")

    async def _record_result(
        self,
        *,
        request: DelegationRequest,
        result: DelegationResult,
    ) -> None:
        workspace_id = request.task_artifact_ref.workspace_id
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO agent_delegation_result (
                        delegation_id, workspace_id, child_execution_id, status,
                        finalization_artifact_key, finalization_sha256,
                        spend_millicents, completed_at
                    )
                    VALUES (
                        :id, :workspace, :child, :status, :finalization, :sha, :spend, :at
                    )
                    ON CONFLICT (delegation_id) DO NOTHING RETURNING delegation_id
                    """
                ),
                {
                    "id": result.delegation_id,
                    "workspace": workspace_id,
                    "child": result.child_execution_id,
                    "status": result.status,
                    "finalization": result.finalization_ref.artifact_key,
                    "sha": result.finalization_ref.sha256,
                    "spend": result.spend_millicents,
                    "at": result.completed_at,
                },
            )
            if inserted.first() is not None:
                for ordinal, ref in enumerate(result.output_refs):
                    await conn.execute(
                        text(
                            "INSERT INTO agent_delegation_output_ref "
                            "(delegation_id, workspace_id, ordinal, artifact_key, artifact_sha256) "
                            "VALUES (:id, :workspace, :ordinal, :key, :sha)"
                        ),
                        {
                            "id": result.delegation_id,
                            "workspace": workspace_id,
                            "ordinal": ordinal,
                            "key": ref.artifact_key,
                            "sha": ref.sha256,
                        },
                    )
                for ordinal, domain_ref in enumerate(result.domain_refs):
                    await conn.execute(
                        text(
                            "INSERT INTO agent_delegation_domain_ref "
                            "(delegation_id, workspace_id, ref_role, ordinal, object_type, "
                            " object_id, object_version) "
                            "VALUES (:id, :workspace, 'result', :ordinal, :type, :object, :version)"
                        ),
                        {
                            "id": result.delegation_id,
                            "workspace": workspace_id,
                            "ordinal": ordinal,
                            "type": domain_ref.object_type,
                            "object": domain_ref.object_id,
                            "version": domain_ref.version,
                        },
                    )

    async def _event(
        self,
        request: DelegationRequest,
        status: str,
        *,
        spend_millicents: int = 0,
        reason_code: str | None = None,
    ) -> None:
        async with self._conn_factory() as conn:
            await self._event_conn(
                conn,
                request,
                status,
                spend_millicents=spend_millicents,
                reason_code=reason_code,
            )

    @staticmethod
    async def _event_conn(
        conn: object,
        request: DelegationRequest,
        status: str,
        *,
        spend_millicents: int = 0,
        reason_code: str | None = None,
    ) -> None:
        await conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO agent_delegation_event "
                "(event_id, delegation_id, workspace_id, status, spend_millicents, reason_code) "
                "VALUES (:event, :id, :workspace, :status, :spend, :reason) "
                "ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "event": uuid5(
                    _DELEGATION_EVENT_NAMESPACE,
                    f"{request.delegation_id}:{status}",
                ),
                "id": request.delegation_id,
                "workspace": request.task_artifact_ref.workspace_id,
                "status": status,
                "spend": spend_millicents,
                "reason": reason_code,
            },
        )


class C5AgentExecutionAdapter(AgentExecutionAdapter):
    """Trusted C6 adapter: proposal -> C5 graph -> dynamic nodes -> ToolInvoker."""

    def __init__(
        self,
        *,
        turn_id: UUID,
        constitution: AgentConstitution,
        resolved_profile: ResolvedAgentProfile,
        policy: AgentPlanPolicy,
        slot_key: str,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        executor: RecipeExecutor,
        artifacts: DurableAgentArtifactStore,
        journal: DbAgentPlanJournal,
        checkpointer_factory: CheckpointerFactory,
        pin_provider: StepPinProvider | None = None,
        delegation: DbAgentDelegationRuntime | None = None,
        captured_turn: CapturedTurnSource | None = None,
        spill_sink: SpillSink | None = None,
        crash_hook: AgentExecutionCrashHook = _DEFAULT_CRASH_HOOK,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._turn_id = turn_id
        # The canonical receipt for the human act this turn *is* — derived once, from the turn id
        # the adapter was constructed with, and stamped as the ambient ``action_ref`` on every
        # ToolContext this adapter builds. Derived, never passed: the same PC-C8 security model as
        # the captured-turn binding, so no caller and no model authors which action approved an
        # effect. Its server-side verification lives in ``clue_api.turn_action``.
        self._action_ref = derive_turn_action_ref(turn_id)
        self._constitution = constitution
        self._resolved_profile = resolved_profile
        self._policy = policy
        self._slot_key = slot_key
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._executor = executor
        self._artifacts = artifacts
        self._journal = journal
        self._checkpointer_factory = checkpointer_factory
        self._pin_provider = pin_provider
        self._delegation = delegation
        self._captured_turn = captured_turn
        # Where an oversized tool result goes instead of into its receipt. A composition root that
        # holds the turn's workspace lease passes the lease's backend; one that does not passes
        # nothing, and an oversized result keeps today's behaviour — refused at the receipt bound.
        self._spill_sink = spill_sink
        self._crash_hook = crash_hook
        self._conn_factory = conn_factory
        self._validated: dict[UUID, ValidatedPlan] = {}
        self._proposals: dict[UUID, AgentPlan] = {}
        self._pin_requests: dict[UUID, dict[str, tuple[PinRequest, ...]]] = {}

    async def _resolve_captured_turn(self) -> CapturedTurn:
        """Serve this turn's binding, or refuse loudly enough for the model to see it.

        The refusal is a ``ValueError`` on purpose: the caller turns it into a
        ``turn_binding_unavailable`` plan issue, so a step needing turn authority on an execution
        that has none is rejected with visible feedback instead of running unbound.
        """

        if self._captured_turn is None:
            raise CapturedTurnUnavailable(
                "this execution carries no captured-turn binding, so the platform cannot supply "
                "the turn's captured input, artifact, or body",
                reason_code="no_binding",
            )
        return await self._captured_turn.captured_turn()

    async def validate_plan(
        self,
        *,
        plan: AgentPlan,
        constitution: AgentConstitution,
    ) -> ValidatedPlan:
        if constitution != self._constitution:
            raise ValueError("execution adapter is bound to a different constitution")
        review = review_agent_plan(
            plan=plan,
            constitution=constitution,
            profile=self._resolved_profile.profile,
            policy=self._policy,
        )
        issues = list(review.issues)
        slot = await self._executor.inspect_interaction_slot(
            execution_id=constitution.execution_id,
            workspace_id=constitution.workspace_id,
            slot_key=self._slot_key,
        )
        proposed_tool_count = sum(isinstance(step, PlanToolStep) for step in plan.steps)
        if slot.child_count + proposed_tool_count > slot.max_children:
            issues.append(
                _agent_issue(
                    GraphIssue(
                        "dynamic_child_ceiling",
                        "plan.steps",
                        "accepted plan would exceed the C5 interaction child ceiling",
                    )
                )
            )
        if slot.node_count + proposed_tool_count > slot.max_nodes:
            issues.append(
                _agent_issue(
                    GraphIssue(
                        "execution_node_ceiling",
                        "plan.steps",
                        "accepted plan would exceed the C5 execution node ceiling",
                    )
                )
            )
        effective = {pin.address for pin in self._resolved_profile.profile.tools}
        # Model-proposed arguments carry model-controlled fields only; the authority a tool body
        # declares is merged in here, from the bound constitution, before anything validates or
        # executes. Every later use of a step's inputs reads this one merged mapping.
        trusted_arguments: dict[str, dict[str, JsonValue]] = {}
        for ordinal, step in enumerate(plan.steps):
            if not isinstance(step, PlanToolStep):
                continue
            if step.tool.address not in slot.tool_allowlist:
                issues.append(
                    _agent_issue(
                        GraphIssue(
                            "c5_tool_not_allowed",
                            f"plan.steps[{ordinal}].tool",
                            f"{step.tool.address} is absent from the active C5 slot",
                        )
                    )
                )
            if step.tool.address not in effective:
                # Skipping without an issue would retain the step while leaving it out of
                # ``trusted_arguments``, and the later unguarded lookups (graph compilation, cost
                # estimation) key straight off ``plan.steps``. ``review_agent_plan`` happens to
                # refuse this same shape upstream, but that is a second, independently-editable
                # authority: this loop states its own precondition so the invariant "every
                # retained tool step has trusted arguments" holds here, not by inheritance.
                issues.append(
                    _agent_issue(
                        GraphIssue(
                            "tool_not_effective",
                            f"plan.steps[{ordinal}].tool",
                            f"{step.tool.address} is not an effective tool of the bound profile",
                        )
                    )
                )
                continue
            descriptor = self._tools.descriptor(step.tool.name, step.tool.version)
            if (
                descriptor.input_schema_sha256 != step.tool.input_schema_sha256
                or descriptor.output_schema_sha256 != step.tool.output_schema_sha256
            ):
                issues.append(
                    _agent_issue(
                        GraphIssue(
                            "tool_schema_mismatch",
                            f"plan.steps[{ordinal}].tool",
                            f"{step.tool.address} differs from the live exact descriptor",
                        )
                    )
                )
                continue
            try:
                merged = _trusted_tool_arguments(
                    arguments=step.arguments,
                    input_model=descriptor.input_model,
                    constitution=constitution,
                    captured_turn=(
                        await self._resolve_captured_turn()
                        if trusted_turn_fields(descriptor.input_model)
                        else None
                    ),
                )
                descriptor.input_model.model_validate(merged)
            except CapturedTurnUnavailable as exc:
                # Attribution matters: this step is unrunnable because the *platform* cannot bind
                # the turn, not because the model's arguments are wrong. Reporting it as
                # ``tool_input_invalid`` on ``.arguments`` sends the model into a repair loop over
                # arguments it did not get wrong and cannot fix. Same fail-closed outcome, honest
                # cause — and the location names the step, not the model's proposal.
                issues.append(
                    _agent_issue(
                        GraphIssue(
                            "turn_binding_unavailable",
                            f"plan.steps[{ordinal}]",
                            str(exc),
                        )
                    )
                )
            except Exception as exc:
                issues.append(
                    _agent_issue(
                        GraphIssue(
                            "tool_input_invalid",
                            f"plan.steps[{ordinal}].arguments",
                            str(exc),
                        )
                    )
                )
            else:
                trusted_arguments[step.node_key] = merged
        if issues:
            from clue_agents import AgentPlanReview

            raise AgentPlanRejected(review.model_copy(update={"issues": tuple(issues)}))

        # Pins are resolved *before* the graph is compiled, because ``validate_graph`` enforces
        # "every pin kind the descriptor requires is on the node (or execution-wide)" — and for a
        # governed Stage-0 tool the per-turn kinds (an ``artifact_input`` derived from the step's
        # own arguments) exist nowhere else. Resolving them afterwards made every such tool
        # unreachable through the agent path with ``missing_tool_requirement``.
        resolved_pin_requests: dict[str, tuple[PinRequest, ...]] = {}
        if self._pin_provider is not None:
            for step in plan.steps:
                if not isinstance(step, PlanToolStep):
                    continue
                operation_id = operation_id_for_plan_node(
                    constitution.execution_id,
                    step.node_key,
                )
                try:
                    pins = await self._pin_provider.pins_for(
                        RecipeStep(
                            step_id=step.node_key,
                            tool_name=step.tool.name,
                            tool_version=step.tool.version,
                            # The merged mapping, never ``step.arguments``: pin derivation reads
                            # authority-injected keys (``project_id``) that the model neither sees
                            # nor may propose, so the raw proposal silently under-pins.
                            input_refs=dict(trusted_arguments[step.node_key]),
                            depends_on=step.depends_on,
                        ),
                        # B4 ⇄ D1 join. Pin resolution is the *execution service's* own read while
                        # it validates a proposed plan — nobody's human effect — so it runs under
                        # the service principal, never under the turn's user (a service credential
                        # that could mint a human actor id is exactly Lane B ruling 8's
                        # impersonation). The turn's ``action_ref`` still rides along: an approval
                        # receipt is *evidence* a service may carry, and a pin derived for a gated
                        # step needs to see it.
                        ctx=tool_context_for_internal_service(
                            service_id="svc_agent_execution",
                            workspace_id=constitution.workspace_id,
                            conn_factory=self._conn_factory,
                            operation_id=operation_id,
                            action_ref=self._action_ref,
                            execution_id=constitution.execution_id,
                            execution_node_key=step.node_key,
                        ),
                    )
                except Exception as exc:
                    from clue_agents import AgentPlanIssue, AgentPlanReview

                    raise AgentPlanRejected(
                        AgentPlanReview(
                            proposal_sha256=review.proposal_sha256,
                            issues=(
                                AgentPlanIssue(
                                    code="pin_resolution_failed",
                                    location=f"plan.steps.{step.node_key}",
                                    message=str(exc),
                                ),
                            ),
                            dependency_depth=review.dependency_depth,
                            maximum_fanout=review.maximum_fanout,
                        )
                    ) from exc
                invalid_kinds = sorted({pin.kind for pin in pins} - set(slot.dynamic_pin_kinds))
                if invalid_kinds:
                    from clue_agents import AgentPlanIssue, AgentPlanReview

                    raise AgentPlanRejected(
                        AgentPlanReview(
                            proposal_sha256=review.proposal_sha256,
                            issues=(
                                AgentPlanIssue(
                                    code="c5_pin_kind_not_allowed",
                                    location=f"plan.steps.{step.node_key}",
                                    message=(
                                        "resolved pins exceed the active interaction slot: "
                                        f"{invalid_kinds}"
                                    ),
                                ),
                            ),
                            dependency_depth=review.dependency_depth,
                            maximum_fanout=review.maximum_fanout,
                        )
                    )
                resolved_pin_requests[step.node_key] = pins

        graph, _, parameter_schema = _plan_graph_and_parameters(
            plan=plan,
            tools=self._tools,
            slot=slot,
            arguments=trusted_arguments,
            pin_requests=resolved_pin_requests,
        )
        graph_review = validate_graph(
            graph,
            parameter_schema=parameter_schema,
            tool_catalog=self._tools,
            max_nodes=self._policy.max_nodes,
            max_depth=self._policy.max_dependency_depth,
            max_fanout=self._policy.max_fanout,
            execution_requirements=slot.requirements,
        )
        if not graph_review.valid:
            from clue_agents import AgentPlanReview

            raise AgentPlanRejected(
                AgentPlanReview(
                    proposal_sha256=review.proposal_sha256,
                    issues=tuple(_agent_issue(item) for item in graph_review.issues),
                    dependency_depth=review.dependency_depth,
                    maximum_fanout=review.maximum_fanout,
                )
            )

        proposal_ref = await self._artifacts.persist_body(
            workspace_id=constitution.workspace_id,
            data=_canonical_bytes(plan),
            media_type="application/vnd.clue.agent-plan-proposal+json",
        )
        costs: dict[str, int] = {}
        parameter_refs: dict[str, ArtifactRef] = {}
        delegation_count = max(
            1,
            sum(isinstance(step, PlanDelegationStep) for step in plan.steps),
        )
        for step in plan.steps:
            if isinstance(step, PlanToolStep):
                tool = self._tools.get(step.tool.name, step.tool.version)
                # The executed body is materialized from this artifact, so it must be the
                # authority-merged arguments, never the raw model proposal.
                inputs = tool.input_model.model_validate(trusted_arguments[step.node_key])
                estimate = tool.estimate(inputs)
                costs[step.node_key] = int(
                    (Decimal(estimate.cost_cents) * 1000).to_integral_value(rounding=ROUND_CEILING)
                )
                payload: object = inputs.model_dump(mode="json")
            else:
                costs[step.node_key] = 0
                payload = {
                    "role": step.role.value,
                    "task_artifact_ref": step.task_artifact_ref.model_dump(mode="json"),
                    "granted_paths": list(step.granted_paths),
                    "domain_refs": [item.model_dump(mode="json") for item in step.domain_refs],
                    "child_budget_limit_millicents": (
                        self._policy.budget_limit_millicents // delegation_count
                    ),
                }
            parameter_refs[step.node_key] = await self._artifacts.persist_body(
                workspace_id=constitution.workspace_id,
                data=_canonical_bytes(payload),
                media_type="application/vnd.clue.agent-operation-parameters+json",
            )
        estimated = sum(costs.values())
        if (
            self._policy.budget_mode == "enforced"
            and estimated > self._policy.budget_limit_millicents
        ):
            from clue_agents import AgentPlanIssue, AgentPlanReview

            raise AgentPlanRejected(
                AgentPlanReview(
                    proposal_sha256=review.proposal_sha256,
                    issues=(
                        AgentPlanIssue(
                            code="budget_ceiling",
                            location="plan.steps",
                            message=(
                                f"estimated {estimated} millicents exceeds "
                                f"{self._policy.budget_limit_millicents}"
                            ),
                        ),
                    ),
                    dependency_depth=review.dependency_depth,
                    maximum_fanout=review.maximum_fanout,
                )
            )

        operations = tuple(
            ValidatedOperation(
                node_key=step.node_key,
                operation_id=operation_id_for_plan_node(constitution.execution_id, step.node_key),
                kind="tool" if isinstance(step, PlanToolStep) else "delegation",
                address=(step.tool.address if isinstance(step, PlanToolStep) else step.role.value),
                depends_on=step.depends_on,
                parameter_artifact_ref=parameter_refs[step.node_key],
                parameter_sha256=parameter_refs[step.node_key].sha256,
                estimated_cost_millicents=costs[step.node_key],
                authority_sha256=authority_sha256(
                    constitution=constitution,
                    profile=self._resolved_profile.profile,
                    node_key=step.node_key,
                    address=(
                        step.tool.address if isinstance(step, PlanToolStep) else step.role.value
                    ),
                ),
            )
            for step in plan.steps
        )
        # The proposal timestamp is part of the immutable model proposal and therefore makes a
        # crash-retry compile byte-identical. The durable row creation time still records when
        # trusted validation actually committed.
        validated_at = plan.proposed_at
        provisional = {
            "plan_id": str(plan.plan_id),
            "execution_id": str(plan.execution_id),
            "proposal_sha256": review.proposal_sha256,
            "resource_manifest_sha256": constitution.resource_manifest_sha256,
            "operations": [item.model_dump(mode="json") for item in operations],
            "max_parallelism": min(self._policy.max_parallelism, self._policy.max_fanout),
            "estimated_cost_millicents": estimated,
            "budget_limit_millicents": self._policy.budget_limit_millicents,
            "budget_mode": self._policy.budget_mode,
            "validated_at": validated_at.isoformat(),
        }
        validated_ref = await self._artifacts.persist_body(
            workspace_id=constitution.workspace_id,
            data=_canonical_bytes(provisional),
            media_type="application/vnd.clue.validated-agent-plan+json",
        )
        validated = ValidatedPlan(
            plan_id=plan.plan_id,
            execution_id=plan.execution_id,
            validated_plan_artifact_ref=validated_ref,
            proposal_sha256=review.proposal_sha256,
            resource_manifest_sha256=constitution.resource_manifest_sha256,
            operations=operations,
            max_parallelism=min(self._policy.max_parallelism, self._policy.max_fanout),
            estimated_cost_millicents=estimated,
            budget_limit_millicents=self._policy.budget_limit_millicents,
            budget_mode=self._policy.budget_mode,
            validated_at=validated_at,
        )
        await self._journal.record_validated(
            turn_id=self._turn_id,
            workspace_id=constitution.workspace_id,
            role=constitution.role,
            plan=validated,
            proposal_ref=proposal_ref,
        )
        self._validated[plan.plan_id] = validated
        self._proposals[plan.plan_id] = plan
        self._pin_requests[plan.plan_id] = resolved_pin_requests
        return validated

    async def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        if self._validated.get(plan.plan_id) != plan:
            raise ValueError("adapter can execute only a plan it validated exactly")
        proposal = self._proposals[plan.plan_id]
        steps = {step.node_key: step for step in proposal.steps}
        by_key = {operation.node_key: operation for operation in plan.operations}
        completed: set[str] = set()
        failed: set[str] = set()
        failures: list[OperationFailure] = []
        await self._journal.event(
            plan_id=plan.plan_id,
            workspace_id=self._constitution.workspace_id,
            status="running",
        )
        while len(completed) + len(failed) < len(plan.operations):
            ready = [
                operation
                for operation in plan.operations
                if operation.node_key not in completed | failed
                and set(operation.depends_on) <= completed
            ]
            if not ready:
                failed.update(set(by_key) - completed)
                break
            batch = ready[: plan.max_parallelism]
            results = await asyncio.gather(
                *(
                    self._execute_operation(
                        plan=plan,
                        operation=operation,
                        step=steps[operation.node_key],
                        completed=completed,
                        operation_by_key=by_key,
                    )
                    for operation in batch
                ),
                return_exceptions=True,
            )
            for operation, result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    failed.add(operation.node_key)
                    failures.append(_operation_failure(operation, result))
                    if operation.kind == "tool":
                        log.warning(
                            "agent_turn.context_tool_outcome",
                            turn_id=str(self._turn_id),
                            workspace_id=self._constitution.workspace_id,
                            project_id=self._constitution.project_id,
                            tool_address=operation.address,
                            outcome="failed",
                            replayed=False,
                            error_code=type(result).__name__,
                        )
                        record_context_tool_outcome(
                            tool_address=operation.address,
                            outcome="failed",
                            replayed=False,
                        )
                else:
                    completed.add(operation.node_key)
                    if operation.kind == "tool":
                        replayed = bool(result.replayed)
                        log.info(
                            "agent_turn.context_tool_outcome",
                            turn_id=str(self._turn_id),
                            workspace_id=self._constitution.workspace_id,
                            project_id=self._constitution.project_id,
                            tool_address=operation.address,
                            outcome="completed",
                            replayed=replayed,
                            reference_count=len(result.reference_values),
                        )
                        record_context_tool_outcome(
                            tool_address=operation.address,
                            outcome="completed",
                            replayed=replayed,
                        )
            yield ExecutionProgress(
                execution_id=plan.execution_id,
                status="failed" if failed else "running",
                completed_node_keys=tuple(sorted(completed)),
                failed_node_keys=tuple(sorted(failed)),
                failures=tuple(failures),
            )
            if failed:
                break
        if failed:
            await self._journal.event(
                plan_id=plan.plan_id,
                workspace_id=self._constitution.workspace_id,
                status="failed",
                reason_code="operation_failed",
            )
        else:
            await self._journal.event(
                plan_id=plan.plan_id,
                workspace_id=self._constitution.workspace_id,
                status="completed",
            )
            yield ExecutionProgress(
                execution_id=plan.execution_id,
                status="completed",
                completed_node_keys=tuple(sorted(completed)),
            )

    async def _execute_operation(
        self,
        *,
        plan: ValidatedPlan,
        operation: ValidatedOperation,
        step: PlanToolStep | PlanDelegationStep,
        completed: set[str],
        operation_by_key: Mapping[str, ValidatedOperation],
    ) -> GovernedOperationReceipt:
        if isinstance(step, PlanDelegationStep):
            return await self._execute_delegation(
                plan=plan,
                operation=operation,
                step=step,
            )
        for failed_key in step.retry_of:
            await self._executor.validate_interaction_repair(
                execution_id=plan.execution_id,
                workspace_id=self._constitution.workspace_id,
                slot_key=self._slot_key,
                failed_node_key=failed_key,
                replacement_node_key=operation.node_key,
                tool_address=operation.address,
            )
        parameter_bytes = await self._artifacts.read(operation.parameter_artifact_ref)
        inputs_value = json.loads(parameter_bytes)
        if not isinstance(inputs_value, dict):
            raise ValueError("validated tool parameters are not an object")
        tool_dependencies = tuple(
            dependency
            for dependency in operation.depends_on
            if operation_by_key[dependency].kind == "tool" and dependency in completed
        )
        await self._crash_hook(
            "plan_append",
            execution_id=plan.execution_id,
            node_key=operation.node_key,
        )
        append = await self._executor.append_interaction_tool(
            execution_id=plan.execution_id,
            workspace_id=self._constitution.workspace_id,
            slot_key=self._slot_key,
            node_key=operation.node_key,
            tool_name=step.tool.name,
            tool_version=step.tool.version,
            inputs=cast(dict[str, JsonValue], inputs_value),
            actor="agent",
            dependencies=tool_dependencies,
            pin_requests=self._pin_requests.get(plan.plan_id, {}).get(
                operation.node_key,
                (),
            ),
        )
        result = await self._executor.invoke_interaction_tool(
            append,
            inputs=cast(dict[str, JsonValue], inputs_value),
            actor="agent",
            # Ambient identity (Lane D §3-P2), threaded as data from the turn this adapter is bound
            # to: the constitution's authenticated principal, and the canonical receipt for the
            # user act that woke the agent. A human gate reads exactly these two values; nothing a
            # model or a caller writes can reach them.
            actor_id=self._constitution.actor_id,
            action_ref=self._action_ref,
        )
        # The ToolInvoker result crosses a durable JSON boundary before it reaches this adapter.
        # Reuse the toolbelt's canonical validator: strict UUID/datetime/Decimal and tuple output
        # contracts must be decoded in JSON mode, not incorrectly reinterpreted as Python-native
        # inputs. This also keeps the production C5 path and direct/idempotent tool replay on one
        # validation rule.
        canonical_result = validate_tool_result(
            self._tools.get(step.tool.name, step.tool.version),
            result,
        )
        subject_bindings = tuple(
            {
                *client_knowledge_result_subject_bindings(
                    address=operation.address,
                    references=canonical_result.references,
                ),
                *product_knowledge_result_subject_bindings(
                    address=operation.address,
                    references=canonical_result.references,
                ),
            }
        )
        result_ref = await self._artifacts.persist_body(
            workspace_id=self._constitution.workspace_id,
            data=_canonical_bytes(canonical_result),
            media_type="application/vnd.clue.agent-tool-result+json",
            subject_bindings=subject_bindings,
        )
        await self._journal.record_tool_result(
            plan_id=plan.plan_id,
            workspace_id=self._constitution.workspace_id,
            operation=operation,
            result=canonical_result,
            result_ref=result_ref,
        )
        for failed_key in step.retry_of:
            await self._executor.resolve_interaction_failure(
                execution_id=plan.execution_id,
                workspace_id=self._constitution.workspace_id,
                slot_key=self._slot_key,
                failed_node_key=failed_key,
                replacement_node_key=operation.node_key,
                tool_address=operation.address,
            )
            log.info(
                "agent.tool_recovered",
                execution_id=str(plan.execution_id),
                failed_node_key=failed_key,
                replacement_node_key=operation.node_key,
                tool_address=operation.address,
            )
        await self._crash_hook(
            "post_tool_complete",
            execution_id=plan.execution_id,
            node_key=operation.node_key,
        )
        return GovernedOperationReceipt(
            node_key=operation.node_key,
            operation_id=operation.operation_id,
            kind="tool",
            address=operation.address,
            status=AgentExecutionStatus.COMPLETED,
            replayed=canonical_result.replayed,
            artifact_refs=(result_ref,),
            reference_values=self._receipt_reference_values(
                address=operation.address,
                operation_id=operation.operation_id,
                references=cast(dict[str, JsonValue], canonical_result.references),
            ),
        )

    def _receipt_reference_values(
        self,
        *,
        address: str,
        operation_id: OperationId,
        references: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        """These references, or a pointer to them when they are too big to carry in a receipt.

        The receipt's bound is a *refusal*, and it lands after the tool has already run and spent:
        on 2026-09-13 a 72-claim account read became "the agent cannot read this account" that
        way. So nothing is allowed to reach it. Past the spill threshold the same canonical bytes
        are written into the thread's ``reads/`` folder and the receipt carries a stub naming the
        file, which the model opens with ``read_file``.

        Both ways a receipt is built call this and nothing else: the live one in ``_execute_tool``
        and the rebuilt one in ``_hydrate_tool_reference_values``. They must not drift, because the
        rebuilt receipt is the one the model is actually handed — ``execute`` drops the live
        receipt, and ``GovernedAgentToolFactory`` reads the result of ``recover``. A threshold
        applied in only one of the two is a threshold the model never sees.

        The result the receipt no longer quotes is not lost: it is the ``result_ref`` artifact,
        persisted and journaled before any of this. Only the inline copy shrinks.
        """

        if self._spill_sink is None:
            return references
        spilled = _canonical_bytes(references)
        if len(spilled) <= SPILL_THRESHOLD_BYTES:
            return references
        # Idempotent by construction: the name is the operation's, and a re-spill of the same
        # operation replaces its own file. Hydration re-running this is a rewrite, not a conflict.
        path = self._spill_sink.write_spill(str(operation_id), spilled)
        return spill_stub(address=address, path=path, references=references)

    async def _execute_delegation(
        self,
        *,
        plan: ValidatedPlan,
        operation: ValidatedOperation,
        step: PlanDelegationStep,
    ) -> GovernedOperationReceipt:
        if self._delegation is None:
            raise ValueError("delegation runtime is not composed")
        child_profile = self._resolved_profile
        # Resolve once here to build exact pinned artifacts; the runtime resolves again before wake.
        # This double check makes catalog drift between plan validation and child start fail closed.
        child_resolved = self._delegation.resolve_child(
            parent=child_profile,
            child_role=step.role,
            current_depth=0,
        )
        per_plan_limit = self._policy.budget_limit_millicents // max(
            1,
            sum(item.kind == "delegation" for item in plan.operations),
        )
        async with self._conn_factory() as conn:
            already_spent = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT COALESCE(SUM(r.spend_millicents), 0)
                            FROM agent_delegation d
                            JOIN agent_delegation_result r ON r.delegation_id=d.id
                            WHERE d.parent_execution_id=:execution
                              AND d.workspace_id=:workspace
                            """
                        ),
                        {
                            "execution": plan.execution_id,
                            "workspace": self._constitution.workspace_id,
                        },
                    )
                ).scalar_one()
            )
        budget_limit = min(
            per_plan_limit,
            max(self._policy.budget_limit_millicents - already_spent, 0),
        )
        budget_ref = await self._artifacts.persist_body(
            workspace_id=self._constitution.workspace_id,
            data=_canonical_bytes(
                {
                    "schema_version": "1",
                    "limit_millicents": budget_limit,
                    "mode": self._policy.budget_mode,
                    "parent_execution_id": str(plan.execution_id),
                    "plan_id": str(plan.plan_id),
                    "node_key": operation.node_key,
                }
            ),
            media_type="application/vnd.clue.agent-budget-envelope+json",
        )
        manifest_ref = await self._artifacts.persist_body(
            workspace_id=self._constitution.workspace_id,
            data=_canonical_bytes(child_resolved.resource_manifest),
            media_type="application/vnd.clue.agent-resource-manifest+json",
        )
        delegation_id = uuid5(
            NAMESPACE_URL,
            f"clue-agent-delegation:{plan.execution_id}:{operation.node_key}",
        )
        request = DelegationRequest(
            delegation_id=delegation_id,
            parent_execution_id=plan.execution_id,
            parent_role=self._constitution.role,
            subagent_role=step.role,
            task_artifact_ref=step.task_artifact_ref,
            granted_paths=step.granted_paths,
            domain_refs=step.domain_refs,
            child_budget_envelope_ref=budget_ref,
            resource_manifest_ref=manifest_ref,
            resource_manifest_sha256=child_resolved.resource_manifest.aggregate_sha256,
            depth=1,
        )
        result = await self._delegation.run(
            plan_id=plan.plan_id,
            node_key=operation.node_key,
            operation_id=operation.operation_id,
            turn_id=self._turn_id,
            request=request,
            parent_profile=self._resolved_profile,
        )
        return GovernedOperationReceipt(
            node_key=operation.node_key,
            operation_id=operation.operation_id,
            kind="delegation",
            address=operation.address,
            status=AgentExecutionStatus(result.status),
            artifact_refs=(*result.output_refs, result.finalization_ref),
            domain_refs=result.domain_refs,
        )

    async def delegate(self, *, request: DelegationRequest) -> DelegationResult:
        raise ValueError("delegation must execute as a validated plan operation")

    async def finalize(self, *, envelope: AgentFinalizeEnvelope) -> ArtifactRef:
        # The honest finalization authority is composed in agent_runtime_wiring and injected here
        # after construction to keep this adapter focused on plan/tool execution.
        authority = getattr(self, "_finalization_authority", None)
        if authority is None:
            raise RuntimeError("finalization authority is not composed")
        if envelope.status.value == "completed":
            unresolved = await self._executor.unresolved_interaction_failures(
                execution_id=self._constitution.execution_id,
                workspace_id=self._constitution.workspace_id,
                slot_key=self._slot_key,
            )
            if unresolved:
                raise ValueError(
                    "Unresolved failed tool attempts remain: "
                    + ", ".join(unresolved)
                    + ". Correct using retry_of, or finalize with an honest blocked status."
                )
        return await authority.finalize(  # type: ignore[no-any-return]
            turn_id=self._turn_id,
            workspace_id=self._constitution.workspace_id,
            envelope=envelope,
        )

    def bind_finalization_authority(self, authority: object) -> None:
        if hasattr(self, "_finalization_authority"):
            raise RuntimeError("finalization authority is already bound")
        self._finalization_authority = authority

    def bind_delegation_runtime(self, delegation: DbAgentDelegationRuntime) -> None:
        """Bind C6.6 after the parent lease/request exist, before any plan is validated."""

        if self._delegation is not None:
            raise RuntimeError("delegation runtime is already bound")
        if self._validated:
            raise RuntimeError("delegation runtime must be bound before plan validation")
        self._delegation = delegation

    def checkpointer(
        self,
        *,
        execution_id: ExecutionId,
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]:
        if execution_id != self._constitution.execution_id:
            raise ValueError("checkpointer request crosses the bound execution")
        return self._checkpointer_factory(execution_id)

    async def recover(self, *, execution_id: ExecutionId) -> Mapping[str, object]:
        if execution_id != self._constitution.execution_id:
            raise ValueError("recovery request crosses the bound execution")
        stored_receipts = await self._journal.load_receipts(
            execution_id=execution_id,
            workspace_id=self._constitution.workspace_id,
        )
        receipts = tuple(
            [await self._hydrate_tool_reference_values(receipt) for receipt in stored_receipts]
        )
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT f.status, c.envelope_artifact_key, c.envelope_sha256,
                                   a.media_type, a.size_bytes
                            FROM agent_finalization_commit c
                            JOIN agent_finalization f ON f.id=c.finalization_id
                            JOIN artifact a ON a.storage_key=c.envelope_artifact_key
                            WHERE c.execution_id=:execution AND c.workspace_id=:workspace
                            """
                        ),
                        {
                            "execution": execution_id,
                            "workspace": self._constitution.workspace_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return {"operation_receipts": receipts}
        return {
            "operation_receipts": receipts,
            "finalization_status": row["status"],
            "finalization_ref": ArtifactRef(
                workspace_id=self._constitution.workspace_id,
                artifact_key=row["envelope_artifact_key"],
                sha256=row["envelope_sha256"],
                media_type=row["media_type"],
                byte_count=int(row["size_bytes"]),
            ),
        }

    async def _hydrate_tool_reference_values(
        self,
        receipt: GovernedOperationReceipt,
    ) -> GovernedOperationReceipt:
        """Recover the small typed projection a live tool returned, never its domain blobs.

        ``_execute_tool`` returns this projection on the in-process receipt, but crash/recovery
        rebuilds receipts from ``agent_tool_result``. That table intentionally stores only the
        immutable result-artifact ref, so the journal-level reconstruction cannot populate
        ``reference_values`` by itself. The governed model nevertheless needs those IDs, flags,
        counts, and next-round cursors to continue. Read the exact verified ToolResult artifact and
        restore only its already-schema-validated ``references`` mapping.

        This is the receipt the model actually reads — ``execute`` drops the live one — so the
        restoration runs through the same ``_receipt_reference_values`` rule the live path uses. An
        oversized result therefore comes back here as the spill stub too, not as the payload the
        threshold exists to keep out of the model's context.
        """

        if receipt.kind != "tool":
            return receipt
        if len(receipt.artifact_refs) != 1:
            raise ValueError("completed tool receipt requires one exact result artifact")
        result_ref = receipt.artifact_refs[0]
        if result_ref.media_type != "application/vnd.clue.agent-tool-result+json":
            raise ValueError("tool receipt artifact has the wrong media type")
        result = ToolResult.model_validate_json(await self._artifacts.read(result_ref))
        if f"{result.tool}@{result.version}" != receipt.address:
            raise ValueError("tool receipt artifact belongs to a different tool address")
        references = cast(dict[str, JsonValue], result.references)
        projection = self._receipt_reference_values(
            address=receipt.address,
            operation_id=receipt.operation_id,
            references=references,
        )
        # Compare like with like. A stored projection is honest if it is either form this adapter
        # could legitimately have written: the references themselves, or the spill stub standing in
        # for them. Insisting on the raw references alone would call a correctly spilled receipt a
        # mismatch; insisting on the stub alone would do the same to one written before a sink
        # existed. Anything that is neither did not come from this artifact.
        if receipt.reference_values and receipt.reference_values not in (references, projection):
            raise ValueError("tool receipt reference projection differs from its artifact")
        # model_copy skips validators; otherwise an oversized recovered result survives
        # until AgentTurnOutcome validation, failing a job after its writes committed.
        return GovernedOperationReceipt.model_validate(
            {**receipt.model_dump(mode="python"), "reference_values": projection}
        )


def _agent_issue(issue: GraphIssue) -> AgentPlanIssue:
    return AgentPlanIssue(
        code=issue.code,
        location=issue.location,
        message=issue.message,
    )
