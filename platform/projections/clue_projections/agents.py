"""Body-free C6 agent registry-adjacent, turn, progress, telemetry, and routing projections."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import ConnFactory, transaction

__all__ = [
    "AgentArtifactView",
    "AgentProgressView",
    "AgentRouteView",
    "AgentTelemetryView",
    "AgentTurnSummary",
    "AgentTurnView",
    "agent_progress",
    "agent_route",
    "agent_telemetry",
    "agent_turn",
    "agent_turns_for_project",
]


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentArtifactView(_View):
    role: str
    artifact_key: str
    sha256: str


class AgentTurnSummary(_View):
    turn_id: UUID
    execution_id: UUID
    parent_execution_id: UUID | None
    project_id: str
    thread_id: str
    role: str
    status: str
    failure_code: str | None
    profile_address: str
    requested_at: AwareDatetime


class AgentTurnView(AgentTurnSummary):
    workspace_root_id: str
    resource_manifest_sha256: str
    context_bundle_id: UUID | None
    context_sha256: str | None
    finalization_id: UUID | None
    finalization_status: str | None
    artifacts: tuple[AgentArtifactView, ...]
    delegation_ids: tuple[UUID, ...]


class AgentProgressView(_View):
    turn_id: UUID
    status: str
    plan_count: int = Field(ge=0)
    operation_count: int = Field(ge=0)
    tool_result_count: int = Field(ge=0)
    delegation_count: int = Field(ge=0)
    completed_delegation_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    failed_model_call_count: int = Field(ge=0)
    context_layer_count: int = Field(ge=0)
    finalization_status: str | None
    cleanup_recorded: bool


class AgentTelemetryView(_View):
    turn_id: UUID
    input_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_ratio: float = Field(ge=0, le=1)
    model_cost_millicredits: int = Field(ge=0)
    model_latency_ms: float = Field(ge=0)
    tool_results: int = Field(ge=0)
    tool_reference_yield: int = Field(ge=0)
    context_tokens: int = Field(ge=0)
    context_excluded_refs: int = Field(ge=0)
    workspace_files: int | None = Field(default=None, ge=0)
    workspace_bytes: int | None = Field(default=None, ge=0)
    workspace_file_utilization: float | None = Field(default=None, ge=0, le=1)
    workspace_byte_utilization: float | None = Field(default=None, ge=0, le=1)
    child_spend_millicents: int = Field(ge=0)
    finalize_failure_events: int = Field(ge=0)


class AgentRouteView(_View):
    route_id: UUID
    surface: str
    subject_id: str
    owner: str
    selection_source: str
    cohort_bucket: int | None
    configured_percent: int
    config_sha256: str
    decided_at: AwareDatetime


async def _turn_row(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> RowMapping | None:
    result = await conn.execute(
        text(
            "SELECT t.*, latest.status, latest.reason_code AS failure_code, "
            "b.id AS context_bundle_id, b.aggregate_sha256 AS context_sha256, "
            "f.id AS finalization_id, f.status AS finalization_status "
            "FROM agent_turn t "
            "JOIN LATERAL (SELECT status, reason_code FROM agent_turn_event "
            " WHERE turn_id=t.id ORDER BY seq DESC LIMIT 1) latest ON true "
            "LEFT JOIN agent_context_bundle b ON b.turn_id=t.id "
            "LEFT JOIN agent_finalization f ON f.turn_id=t.id "
            "WHERE t.workspace_id=:workspace AND t.id=:turn"
        ),
        {"workspace": workspace_id, "turn": turn_id},
    )
    return result.mappings().first()


def _summary(item: RowMapping) -> AgentTurnSummary:
    return AgentTurnSummary(
        turn_id=item["id"],
        execution_id=item["execution_id"],
        parent_execution_id=item["parent_execution_id"],
        project_id=item["project_id"],
        thread_id=item["thread_id"],
        role=item["role"],
        status=item["status"],
        failure_code=item["failure_code"],
        profile_address=f"profile:{item['profile_name']}@{item['profile_version']}",
        requested_at=item["requested_at"],
    )


async def agent_turn(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> AgentTurnView | None:
    async with conn_factory() as conn:
        row = await _turn_row(conn, workspace_id=workspace_id, turn_id=turn_id)
        if row is None:
            return None
        artifact_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT ref_role, artifact_key, artifact_sha256 "
                        "FROM agent_artifact_ref WHERE workspace_id=:workspace AND turn_id=:turn "
                        "ORDER BY owner_kind, owner_id, ref_role, ordinal"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            )
            .mappings()
            .all()
        )
        delegation_ids = tuple(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM agent_delegation "
                        "WHERE workspace_id=:workspace AND turn_id=:turn ORDER BY created_at, id"
                    ),
                    {"workspace": workspace_id, "turn": turn_id},
                )
            ).scalars()
        )
    summary = _summary(row)
    return AgentTurnView(
        **summary.model_dump(),
        workspace_root_id=row["workspace_root_id"],
        resource_manifest_sha256=row["resource_manifest_sha256"],
        context_bundle_id=row["context_bundle_id"],
        context_sha256=row["context_sha256"],
        finalization_id=row["finalization_id"],
        finalization_status=row["finalization_status"],
        artifacts=tuple(
            AgentArtifactView(
                role=item["ref_role"],
                artifact_key=item["artifact_key"],
                sha256=item["artifact_sha256"],
            )
            for item in artifact_rows
        ),
        delegation_ids=delegation_ids,
    )


async def agent_turns_for_project(
    *,
    workspace_id: str,
    project_id: str,
    conn_factory: ConnFactory = transaction,
) -> tuple[AgentTurnSummary, ...]:
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT t.*, latest.status, latest.reason_code AS failure_code "
                        "FROM agent_turn t "
                        "JOIN LATERAL (SELECT status, reason_code FROM agent_turn_event "
                        " WHERE turn_id=t.id ORDER BY seq DESC LIMIT 1) latest ON true "
                        "WHERE t.workspace_id=:workspace AND t.project_id=:project "
                        "ORDER BY t.requested_at, t.id"
                    ),
                    {"workspace": workspace_id, "project": project_id},
                )
            )
            .mappings()
            .all()
        )
    return tuple(_summary(row) for row in rows)


async def agent_progress(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> AgentProgressView | None:
    async with conn_factory() as conn:
        row = await _turn_row(conn, workspace_id=workspace_id, turn_id=turn_id)
        if row is None:
            return None
        counts = (
            (
                await conn.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM agent_plan p WHERE p.turn_id=:turn) plans, "
                        "(SELECT count(*) FROM agent_plan_operation o JOIN agent_plan p "
                        " ON p.id=o.plan_id WHERE p.turn_id=:turn) operations, "
                        "(SELECT count(*) FROM agent_tool_result r JOIN agent_plan p "
                        " ON p.id=r.plan_id WHERE p.turn_id=:turn) tool_results, "
                        "(SELECT count(*) FROM agent_delegation d WHERE d.turn_id=:turn) "
                        "delegations, "
                        "(SELECT count(*) FROM agent_delegation_result r "
                        " JOIN agent_delegation d "
                        " ON d.id=r.delegation_id WHERE d.turn_id=:turn) completed_delegations, "
                        "(SELECT count(*) FROM agent_model_call m WHERE m.turn_id=:turn) "
                        "model_calls, "
                        "(SELECT count(*) FROM agent_model_call m WHERE m.turn_id=:turn "
                        " AND m.status='failed') failed_model_calls, "
                        "(SELECT count(*) FROM agent_context_layer l JOIN agent_context_bundle b "
                        " ON b.id=l.context_bundle_id WHERE b.turn_id=:turn) context_layers, "
                        "EXISTS(SELECT 1 FROM agent_workspace_cleanup_event c "
                        " WHERE c.turn_id=:turn) cleanup_recorded"
                    ),
                    {"turn": turn_id},
                )
            )
            .mappings()
            .one()
        )
    return AgentProgressView(
        turn_id=turn_id,
        status=row["status"],
        plan_count=int(counts["plans"]),
        operation_count=int(counts["operations"]),
        tool_result_count=int(counts["tool_results"]),
        delegation_count=int(counts["delegations"]),
        completed_delegation_count=int(counts["completed_delegations"]),
        model_call_count=int(counts["model_calls"]),
        failed_model_call_count=int(counts["failed_model_calls"]),
        context_layer_count=int(counts["context_layers"]),
        finalization_status=row["finalization_status"],
        cleanup_recorded=bool(counts["cleanup_recorded"]),
    )


async def agent_telemetry(
    *,
    workspace_id: str,
    turn_id: UUID,
    conn_factory: ConnFactory = transaction,
) -> AgentTelemetryView | None:
    async with conn_factory() as conn:
        exists = await conn.execute(
            text("SELECT 1 FROM agent_turn WHERE id=:turn AND workspace_id=:workspace"),
            {"turn": turn_id, "workspace": workspace_id},
        )
        if exists.first() is None:
            return None
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT "
                        "COALESCE((SELECT sum(input_tokens) FROM agent_model_call "
                        " WHERE turn_id=:turn),0) input_tokens, "
                        "COALESCE((SELECT sum(cache_read_input_tokens) FROM agent_model_call "
                        " WHERE turn_id=:turn),0) cache_read, "
                        "COALESCE((SELECT sum(cache_creation_input_tokens) FROM agent_model_call "
                        " WHERE turn_id=:turn),0) cache_creation, "
                        "COALESCE((SELECT sum(output_tokens) FROM agent_model_call "
                        " WHERE turn_id=:turn),0) output_tokens, "
                        "COALESCE((SELECT sum(cost_millicredits) FROM agent_model_call "
                        " WHERE turn_id=:turn),0) model_cost, "
                        "COALESCE((SELECT sum(latency_ms) FROM agent_model_call "
                        " WHERE turn_id=:turn),0) model_latency, "
                        "COALESCE((SELECT count(*) FROM agent_tool_result r JOIN agent_plan p "
                        " ON p.id=r.plan_id WHERE p.turn_id=:turn),0) tool_results, "
                        "COALESCE((SELECT sum(reference_count) FROM agent_tool_result r "
                        " JOIN agent_plan p ON p.id=r.plan_id "
                        " WHERE p.turn_id=:turn),0) tool_yield, "
                        "COALESCE((SELECT sum(token_count) FROM agent_context_layer l "
                        " JOIN agent_context_bundle b ON b.id=l.context_bundle_id "
                        " WHERE b.turn_id=:turn),0) context_tokens, "
                        "COALESCE((SELECT sum(excluded_count) FROM agent_context_layer l "
                        " JOIN agent_context_bundle b ON b.id=l.context_bundle_id "
                        " WHERE b.turn_id=:turn),0) context_excluded, "
                        "COALESCE((SELECT sum(spend_millicents) FROM agent_delegation_result r "
                        " JOIN agent_delegation d ON d.id=r.delegation_id "
                        " WHERE d.turn_id=:turn),0) child_spend, "
                        "COALESCE((SELECT count(*) FROM agent_turn_event e "
                        " WHERE e.turn_id=:turn AND e.status IN ('failed','abandoned')),0) "
                        "finalize_failures"
                    ),
                    {"turn": turn_id},
                )
            )
            .mappings()
            .one()
        )
        usage = (
            (
                await conn.execute(
                    text(
                        "SELECT file_count, total_bytes, max_file_count, max_total_bytes "
                        "FROM agent_workspace_usage WHERE turn_id=:turn "
                        "AND workspace_id=:workspace"
                    ),
                    {"turn": turn_id, "workspace": workspace_id},
                )
            )
            .mappings()
            .first()
        )
    input_tokens = int(row["input_tokens"])
    cache_read = int(row["cache_read"])
    return AgentTelemetryView(
        turn_id=turn_id,
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=int(row["cache_creation"]),
        output_tokens=int(row["output_tokens"]),
        cache_read_ratio=(cache_read / input_tokens if input_tokens else 0),
        model_cost_millicredits=int(row["model_cost"]),
        model_latency_ms=float(row["model_latency"]),
        tool_results=int(row["tool_results"]),
        tool_reference_yield=int(row["tool_yield"]),
        context_tokens=int(row["context_tokens"]),
        context_excluded_refs=int(row["context_excluded"]),
        workspace_files=(int(usage["file_count"]) if usage is not None else None),
        workspace_bytes=(int(usage["total_bytes"]) if usage is not None else None),
        workspace_file_utilization=(
            int(usage["file_count"]) / int(usage["max_file_count"]) if usage is not None else None
        ),
        workspace_byte_utilization=(
            int(usage["total_bytes"]) / int(usage["max_total_bytes"]) if usage is not None else None
        ),
        child_spend_millicents=int(row["child_spend"]),
        finalize_failure_events=int(row["finalize_failures"]),
    )


async def agent_route(
    *,
    workspace_id: str,
    surface: str,
    subject_id: str,
    conn_factory: ConnFactory = transaction,
) -> AgentRouteView | None:
    async with conn_factory() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT id, surface, subject_id, owner, selection_source, cohort_bucket, "
                        "configured_percent, config_sha256, decided_at "
                        "FROM agent_runtime_route WHERE workspace_id=:workspace "
                        "AND surface=:surface AND subject_id=:subject"
                    ),
                    {
                        "workspace": workspace_id,
                        "surface": surface,
                        "subject": subject_id,
                    },
                )
            )
            .mappings()
            .first()
        )
    return (
        AgentRouteView(
            route_id=row["id"],
            surface=row["surface"],
            subject_id=row["subject_id"],
            owner=row["owner"],
            selection_source=row["selection_source"],
            cohort_bucket=row["cohort_bucket"],
            configured_percent=int(row["configured_percent"]),
            config_sha256=row["config_sha256"],
            decided_at=row["decided_at"],
        )
        if row is not None
        else None
    )
