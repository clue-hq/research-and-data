"""Workspace-scoped execution graph and activity read models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text

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
from clue_execution.models import EdgeKind, ExecutionEventType, ExecutionNodeKind, ExecutionStatus


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


class DbExecutionRunViewReader:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

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
                            SELECT id, node_key, kind, tool_name, tool_version, operation_id,
                                   parameter_artifact_key, parameter_sha256, input_schema_sha256,
                                   output_schema_sha256, display_params_json,
                                   declared_by_node_id, created_at
                            FROM execution_node
                            WHERE execution_id = :execution_id
                            ORDER BY created_at, node_key
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
]
