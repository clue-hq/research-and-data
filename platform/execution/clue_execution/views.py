"""Workspace-scoped execution graph and activity read models."""

from __future__ import annotations

import json
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from clue_core import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionNodeId,
    OperationId,
    ProjectRunId,
    RecipeRevisionId,
    UtcDatetime,
    decode_jsonb,
)
from clue_db import ConnFactory
from clue_execution.compatibility import CompatibilityContext, CompatibilityLoader
from clue_execution.models import EdgeKind, ExecutionEventType, ExecutionNodeKind, ExecutionStatus
from clue_execution.recipes import RecipeDefinition


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionSummary(_View):
    execution_id: ExecutionId
    workspace_id: str
    project_id: str | None
    project_run_id: ProjectRunId | None
    recipe_revision_id: RecipeRevisionId | None
    parent_execution_id: ExecutionId | None
    started_by: str
    started_at: UtcDatetime
    status: ExecutionStatus
    state_version: int
    active_node_count: int
    last_event_seq: int | None


class ExecutionNodeView(_View):
    node_id: ExecutionNodeId
    node_key: str
    kind: ExecutionNodeKind
    tool_name: str | None
    tool_version: str | None
    operation_id: OperationId
    parameter_artifact_key: str | None
    parameter_sha256: str | None
    input_schema_sha256: str | None
    output_schema_sha256: str | None
    invocation_actor: str | None
    principal_kind: str | None
    authority_workspace_id: str | None
    actor_id: str | None
    membership_id: str | None
    action_ref: str | None
    display_params: dict[str, JsonValue]
    declared_by_node_id: ExecutionNodeId | None
    created_at: UtcDatetime


class ExecutionEdgeView(_View):
    from_node_id: ExecutionNodeId
    to_node_id: ExecutionNodeId
    edge_kind: EdgeKind
    binding: dict[str, JsonValue]


class ExecutionPinView(_View):
    pin_id: str
    node_id: ExecutionNodeId | None
    kind: str
    key: str
    version: str | None
    digest: str
    resolved_status: str
    metadata: dict[str, JsonValue]


class ExecutionAttemptView(_View):
    attempt_id: ExecutionAttemptId
    node_id: ExecutionNodeId
    attempt: int
    worker_id: str | None
    lease_generation: int | None
    started_at: UtcDatetime


class ExecutionEventView(_View):
    seq: int
    node_id: ExecutionNodeId | None
    attempt_id: ExecutionAttemptId | None
    event_type: ExecutionEventType
    actor: str
    payload: dict[str, JsonValue]
    created_at: UtcDatetime


class ExecutionArtifactRefView(_View):
    node_id: ExecutionNodeId
    artifact_key: str
    role: str
    content_sha256: str
    artifact_state: str


class ExecutionRunView(_View):
    summary: ExecutionSummary
    nodes: tuple[ExecutionNodeView, ...]
    edges: tuple[ExecutionEdgeView, ...]
    pins: tuple[ExecutionPinView, ...]
    attempts: tuple[ExecutionAttemptView, ...]
    events: tuple[ExecutionEventView, ...]
    artifact_refs: tuple[ExecutionArtifactRefView, ...]


class RecipeLibraryRevisionView(_View):
    recipe_revision_id: RecipeRevisionId
    recipe_key: str
    scope_type: str
    workspace_id: str | None
    version: int
    lifecycle_status: str
    migration_state: str
    definition_sha256: str
    compatibility_status: str
    created_at: UtcDatetime


class SupervisorObservationView(_View):
    observation_id: str
    project_run_id: ProjectRunId | None
    policy_version: str
    aggregate_snapshot: dict[str, JsonValue]
    trigger_codes: tuple[str, ...]
    created_at: UtcDatetime


class SupervisorDiagnosisView(_View):
    diagnosis_id: str
    observation_id: str
    requested_model: str
    answering_model: str
    prompt_version: str
    diagnosis_codes: tuple[str, ...]
    affected_refs: tuple[str, ...]
    confidence: float
    created_at: UtcDatetime


class SupervisorControlView(_View):
    seq: int
    control_kind: str
    subject_ref: str
    action: str
    before: dict[str, JsonValue]
    after: dict[str, JsonValue]
    reason_code: str
    observation_id: str | None
    diagnosis_id: str | None
    actor: str
    created_at: UtcDatetime


class ExecutionSupervisionView(_View):
    observations: tuple[SupervisorObservationView, ...]
    diagnoses: tuple[SupervisorDiagnosisView, ...]
    controls: tuple[SupervisorControlView, ...]
    effective_controls: tuple[SupervisorControlView, ...]


class DbExecutionRunViewReader:
    def __init__(
        self,
        *,
        conn_factory: ConnFactory,
        compatibility: CompatibilityLoader | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._compatibility = compatibility

    async def read_project_run(
        self, *, workspace_id: str, project_run_id: ProjectRunId
    ) -> ExecutionRunView | None:
        async with self._conn_factory() as conn:
            execution_id = (
                await conn.execute(
                    text(
                        """
                        SELECT execution_id FROM project_run_execution_owner
                        WHERE project_run_id = :run_id AND workspace_id = :workspace_id
                        """
                    ),
                    {"run_id": project_run_id, "workspace_id": workspace_id},
                )
            ).scalar_one_or_none()
        return (
            None
            if execution_id is None
            else await self.read_execution(
                workspace_id=workspace_id,
                execution_id=ExecutionId(execution_id),
            )
        )

    async def list_recipe_library(
        self,
        *,
        workspace_id: str,
        project_id: str | None = None,
    ) -> tuple[RecipeLibraryRevisionView, ...]:
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT rr.id, r.recipe_key, r.scope_type, r.workspace_id, rr.version,
                                   rr.graph_json, rr.parameter_schema_json, rr.compatibility_json,
                                   rr.requested_memory_types, rr.executor_protocol, rr.max_nodes,
                                   rr.max_depth, rr.max_fanout, rr.source_execution_id,
                                   rr.definition_sha256, rr.created_by, rr.created_at,
                                   (
                                       SELECT event_type FROM recipe_revision_event e
                                       WHERE e.recipe_revision_id = rr.id
                                       ORDER BY seq DESC LIMIT 1
                                   ) AS lifecycle_status
                            FROM recipe_revision rr
                            JOIN recipe r ON r.id = rr.recipe_id
                            WHERE r.scope_type = 'system' OR r.workspace_id = :workspace_id
                            ORDER BY r.recipe_key, rr.version
                            """
                        ),
                        {"workspace_id": workspace_id},
                    )
                )
                .mappings()
                .all()
            )
        result: list[RecipeLibraryRevisionView] = []
        for row in rows:
            graph = decode_jsonb(row["graph_json"])
            status = "not_evaluated"
            if self._compatibility is not None:
                definition = RecipeDefinition.model_validate_json(
                    json.dumps(
                        {
                            "recipe_key": row["recipe_key"],
                            "scope_type": row["scope_type"],
                            "workspace_id": row["workspace_id"],
                            "version": row["version"],
                            "executor_protocol": row["executor_protocol"],
                            "parameter_schema": decode_jsonb(row["parameter_schema_json"]),
                            "graph": graph,
                            "compatibility": decode_jsonb(row["compatibility_json"]),
                            "requested_memory_types": decode_jsonb(row["requested_memory_types"]),
                            "max_nodes": row["max_nodes"],
                            "max_depth": row["max_depth"],
                            "max_fanout": row["max_fanout"],
                            "source_execution_id": row["source_execution_id"],
                            "created_by": row["created_by"],
                        },
                        default=str,
                    )
                )
                report = await self._compatibility.load(
                    definition.compatibility,
                    context=CompatibilityContext(
                        workspace_id=workspace_id,
                        project_id=project_id,
                    ),
                )
                status = "compatible" if report.compatible else "incompatible"
            result.append(
                RecipeLibraryRevisionView(
                    recipe_revision_id=row["id"],
                    recipe_key=str(row["recipe_key"]),
                    scope_type=str(row["scope_type"]),
                    workspace_id=(
                        str(row["workspace_id"]) if row["workspace_id"] is not None else None
                    ),
                    version=int(row["version"]),
                    lifecycle_status=str(row["lifecycle_status"]),
                    migration_state=str(graph["migration_state"]),
                    definition_sha256=str(row["definition_sha256"]),
                    compatibility_status=status,
                    created_at=row["created_at"],
                )
            )
        return tuple(result)

    async def read_supervision(
        self, *, workspace_id: str, execution_id: ExecutionId
    ) -> ExecutionSupervisionView | None:
        async with self._conn_factory() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM execution WHERE id = :id AND workspace_id = :workspace_id"),
                    {"id": execution_id, "workspace_id": workspace_id},
                )
            ).scalar_one_or_none()
            if exists is None:
                return None
            observations = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, project_run_id, policy_version, aggregate_snapshot_json,
                                   trigger_codes_json, created_at
                            FROM supervisor_observation
                            WHERE execution_id = :id AND workspace_id = :workspace_id
                            ORDER BY created_at, id
                            """
                        ),
                        {"id": execution_id, "workspace_id": workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            diagnoses = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT d.id, d.observation_id, d.requested_model, d.answering_model,
                                   d.prompt_version, d.diagnosis_codes_json,
                                   d.affected_refs_json, d.confidence, d.created_at
                            FROM supervisor_diagnosis d
                            JOIN supervisor_observation o ON o.id = d.observation_id
                            WHERE o.execution_id = :id AND o.workspace_id = :workspace_id
                            ORDER BY d.created_at, d.id
                            """
                        ),
                        {"id": execution_id, "workspace_id": workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            controls = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT seq, control_kind, subject_ref, action, before_json, after_json,
                                   reason_code, observation_id, diagnosis_id, actor, created_at
                            FROM run_control_event
                            WHERE execution_id = :id AND workspace_id = :workspace_id
                            ORDER BY seq
                            """
                        ),
                        {"id": execution_id, "workspace_id": workspace_id},
                    )
                )
                .mappings()
                .all()
            )

        def control(values: RowMapping) -> SupervisorControlView:
            return SupervisorControlView(
                seq=cast(int, values["seq"]),
                control_kind=str(values["control_kind"]),
                subject_ref=str(values["subject_ref"]),
                action=str(values["action"]),
                before=decode_jsonb(values["before_json"]),
                after=decode_jsonb(values["after_json"]),
                reason_code=str(values["reason_code"]),
                observation_id=(
                    str(values["observation_id"]) if values["observation_id"] is not None else None
                ),
                diagnosis_id=(
                    str(values["diagnosis_id"]) if values["diagnosis_id"] is not None else None
                ),
                actor=str(values["actor"]),
                created_at=cast(UtcDatetime, values["created_at"]),
            )

        control_views = tuple(control(row) for row in controls)
        latest: dict[tuple[str, str], SupervisorControlView] = {}
        for item in control_views:
            latest[(item.control_kind, item.subject_ref)] = item
        effective = tuple(
            latest[key] for key in sorted(latest) if latest[key].after.get("active") is True
        )
        return ExecutionSupervisionView(
            observations=tuple(
                SupervisorObservationView(
                    observation_id=str(row["id"]),
                    project_run_id=row["project_run_id"],
                    policy_version=str(row["policy_version"]),
                    aggregate_snapshot=decode_jsonb(row["aggregate_snapshot_json"]),
                    trigger_codes=tuple(decode_jsonb(row["trigger_codes_json"])),
                    created_at=row["created_at"],
                )
                for row in observations
            ),
            diagnoses=tuple(
                SupervisorDiagnosisView(
                    diagnosis_id=str(row["id"]),
                    observation_id=str(row["observation_id"]),
                    requested_model=str(row["requested_model"]),
                    answering_model=str(row["answering_model"]),
                    prompt_version=str(row["prompt_version"]),
                    diagnosis_codes=tuple(decode_jsonb(row["diagnosis_codes_json"])),
                    affected_refs=tuple(decode_jsonb(row["affected_refs_json"])),
                    confidence=float(row["confidence"]),
                    created_at=row["created_at"],
                )
                for row in diagnoses
            ),
            controls=control_views,
            effective_controls=effective,
        )

    async def read_execution(
        self, *, workspace_id: str, execution_id: ExecutionId
    ) -> ExecutionRunView | None:
        async with self._conn_factory() as conn:
            summary_row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT e.id, e.workspace_id, e.project_id, e.project_run_id,
                                   e.recipe_revision_id, e.parent_execution_id, e.started_by,
                                   e.started_at, c.status, c.state_version, c.active_node_count,
                                   c.last_event_seq
                            FROM execution e
                            JOIN execution_cursor c ON c.execution_id = e.id
                            WHERE e.id = :execution_id AND e.workspace_id = :workspace_id
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "workspace_id": workspace_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if summary_row is None:
                return None
            nodes = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT n.id, n.node_key, n.kind, n.tool_name, n.tool_version,
                                   n.operation_id, n.parameter_artifact_key, n.parameter_sha256,
                                   n.input_schema_sha256, n.output_schema_sha256,
                                   a.invocation_actor, a.principal_kind,
                                   a.authority_workspace_id, a.actor_id, a.membership_id,
                                   a.action_ref, n.display_params_json, n.declared_by_node_id,
                                   n.created_at
                            FROM execution_node n
                            LEFT JOIN execution_node_authority a ON a.node_id = n.id
                            WHERE n.execution_id = :execution_id
                            ORDER BY n.created_at, n.node_key
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            edges = (
                (
                    await conn.execute(
                        text(
                            "SELECT from_node_id, to_node_id, edge_kind, binding_json "
                            "FROM execution_edge WHERE execution_id = :execution_id "
                            "ORDER BY from_node_id, to_node_id, edge_kind"
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            pins = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, node_id, kind, key, version, digest, resolved_status, "
                            "metadata_json FROM execution_pin WHERE execution_id = :execution_id "
                            "ORDER BY kind, key, node_id NULLS FIRST"
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            attempts = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, node_id, attempt, worker_id, lease_generation, started_at "
                            "FROM execution_attempt WHERE execution_id = :execution_id "
                            "ORDER BY node_id, attempt"
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            events = (
                (
                    await conn.execute(
                        text(
                            "SELECT seq, node_id, attempt_id, event_type, actor, payload_json, "
                            "created_at FROM execution_event WHERE execution_id = :execution_id "
                            "ORDER BY seq"
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            artifacts = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT r.node_id, r.artifact_key, r.role, r.content_sha256,
                                   CASE
                                       WHEN a.erased_at IS NOT NULL THEN 'erased'
                                       WHEN a.storage_key IS NULL THEN 'missing'
                                       ELSE 'live'
                                   END AS artifact_state
                            FROM execution_artifact_ref r
                            LEFT JOIN artifact a ON a.storage_key = r.artifact_key
                            WHERE r.execution_id = :execution_id
                              AND r.workspace_id = :workspace_id
                            ORDER BY r.created_at, r.artifact_key
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "workspace_id": workspace_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
        summary_data = dict(summary_row)
        summary_data["execution_id"] = summary_data.pop("id")
        summary = ExecutionSummary.model_validate(summary_data)
        return ExecutionRunView(
            summary=summary,
            nodes=tuple(
                ExecutionNodeView.model_validate(
                    {
                        "node_id": row["id"],
                        "node_key": row["node_key"],
                        "kind": row["kind"],
                        "tool_name": row["tool_name"],
                        "tool_version": row["tool_version"],
                        "operation_id": row["operation_id"],
                        "parameter_artifact_key": row["parameter_artifact_key"],
                        "parameter_sha256": row["parameter_sha256"],
                        "input_schema_sha256": row["input_schema_sha256"],
                        "output_schema_sha256": row["output_schema_sha256"],
                        "invocation_actor": row["invocation_actor"],
                        "principal_kind": row["principal_kind"],
                        "authority_workspace_id": row["authority_workspace_id"],
                        "actor_id": row["actor_id"],
                        "membership_id": row["membership_id"],
                        "action_ref": row["action_ref"],
                        "display_params": decode_jsonb(row["display_params_json"]),
                        "declared_by_node_id": row["declared_by_node_id"],
                        "created_at": row["created_at"],
                    }
                )
                for row in nodes
            ),
            edges=tuple(
                ExecutionEdgeView.model_validate(
                    {
                        "from_node_id": row["from_node_id"],
                        "to_node_id": row["to_node_id"],
                        "edge_kind": row["edge_kind"],
                        "binding": decode_jsonb(row["binding_json"]),
                    }
                )
                for row in edges
            ),
            pins=tuple(
                ExecutionPinView.model_validate(
                    {
                        "pin_id": str(row["id"]),
                        "node_id": row["node_id"],
                        "kind": row["kind"],
                        "key": row["key"],
                        "version": row["version"],
                        "digest": row["digest"],
                        "resolved_status": row["resolved_status"],
                        "metadata": decode_jsonb(row["metadata_json"]),
                    }
                )
                for row in pins
            ),
            attempts=tuple(
                ExecutionAttemptView.model_validate(
                    {
                        "attempt_id": row["id"],
                        "node_id": row["node_id"],
                        "attempt": row["attempt"],
                        "worker_id": row["worker_id"],
                        "lease_generation": row["lease_generation"],
                        "started_at": row["started_at"],
                    }
                )
                for row in attempts
            ),
            events=tuple(
                ExecutionEventView.model_validate(
                    {
                        "seq": row["seq"],
                        "node_id": row["node_id"],
                        "attempt_id": row["attempt_id"],
                        "event_type": row["event_type"],
                        "actor": row["actor"],
                        "payload": decode_jsonb(row["payload_json"]),
                        "created_at": row["created_at"],
                    }
                )
                for row in events
            ),
            artifact_refs=tuple(
                ExecutionArtifactRefView.model_validate(
                    {
                        "node_id": row["node_id"],
                        "artifact_key": row["artifact_key"],
                        "role": row["role"],
                        "content_sha256": row["content_sha256"],
                        "artifact_state": row["artifact_state"],
                    }
                )
                for row in artifacts
            ),
        )


__all__ = [
    "DbExecutionRunViewReader",
    "ExecutionArtifactRefView",
    "ExecutionAttemptView",
    "ExecutionEdgeView",
    "ExecutionEventView",
    "ExecutionNodeView",
    "ExecutionPinView",
    "ExecutionRunView",
    "ExecutionSummary",
    "ExecutionSupervisionView",
    "RecipeLibraryRevisionView",
    "SupervisorControlView",
    "SupervisorDiagnosisView",
    "SupervisorObservationView",
]
