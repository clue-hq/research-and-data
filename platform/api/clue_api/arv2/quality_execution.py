"""Job-wide execution authority shared by the parent and its in-slot specialists.

Counters count dispatch attempts, including failures. Recovery cannot reset a child's allowance.
Model spending stays in agent_model_call; acquisition spending stays in provider_call_ledger.
This mapping joins those existing owners without copying or estimating charges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain.agents.middleware.types import AgentMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.research_operations import OperationScope, job_available
from clue_db import ConnFactory
from clue_obs import get_logger

log = get_logger("arv2.quality.execution")


class ResearchAllowanceExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class Allowance:
    model_calls: int
    tool_calls: int
    delegations: int
    runtime_ms: int = 1800000


async def bind_execution(
    conn: AsyncConnection,
    scope: OperationScope,
    *,
    execution_id: UUID,
    context_id: UUID,
    role: str,
    limits: Allowance,
    parent_execution_id: UUID | None = None,
) -> None:
    if (
        limits.model_calls < 1
        or limits.tool_calls < 1
        or limits.delegations < 0
        or limits.runtime_ms < 0
    ):
        raise ValueError("research allowance limits are invalid")
    row = (
        (
            await conn.execute(
                text("""
      SELECT r.context_id, e.parent_execution_id FROM arv2_research_job j
      JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
      JOIN execution e ON e.id=:execution AND e.workspace_id=j.workspace_id
        AND e.project_id=r.project_id
      WHERE j.job_id=:job AND j.run_id=:run AND j.workspace_id=:ws
        AND j.account_entity_id=:account
    """),
                {
                    "execution": execution_id,
                    "job": scope.job_id,
                    "run": scope.run_id,
                    "ws": scope.workspace_id,
                    "account": scope.account_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or row["context_id"] != context_id
        or row["parent_execution_id"] != parent_execution_id
    ):
        raise ValueError("execution does not match the pinned research job")
    if not await job_available(conn, scope, "quality_execution"):
        raise ValueError("research authority is unavailable")
    await conn.execute(
        text("""
      INSERT INTO arv2_quality_allowance(job_id,workspace_id,run_id,account_id,
        max_model_calls,max_tool_calls,max_delegations,max_runtime_ms)
      VALUES (:job,:ws,:run,:account,:model,:tool,:delegation,:runtime) ON CONFLICT DO NOTHING
    """),
        {
            "job": scope.job_id,
            "ws": scope.workspace_id,
            "run": scope.run_id,
            "account": scope.account_id,
            "model": limits.model_calls,
            "tool": limits.tool_calls,
            "delegation": limits.delegations,
            "runtime": limits.runtime_ms,
        },
    )
    saved = (
        await conn.execute(
            text("""
      SELECT max_model_calls,max_tool_calls,max_delegations,max_runtime_ms
      FROM arv2_quality_allowance
      WHERE job_id=:job AND workspace_id=:ws FOR UPDATE
    """),
            {"job": scope.job_id, "ws": scope.workspace_id},
        )
    ).one()
    granted = (
        await conn.execute(
            text("""
      SELECT COALESCE(sum(top_up_model_calls),0), COALESCE(sum(top_up_tool_calls),0),
        COALESCE(sum(top_up_delegations),0), COALESCE(sum(top_up_runtime_ms),0)
      FROM arv2_research_job_resume WHERE job_id=:job AND workspace_id=:ws
    """),
            {"job": scope.job_id, "ws": scope.workspace_id},
        )
    ).one()
    # An admin's recorded top-up (spec 2026-10-14 §3.5) is the only way the limits grow.
    if tuple(saved) != (
        limits.model_calls + granted[0],
        limits.tool_calls + granted[1],
        limits.delegations + granted[2],
        limits.runtime_ms + granted[3],
    ):
        raise ValueError("research recovery cannot reset the shared allowance")
    await conn.execute(
        text("""
      INSERT INTO arv2_quality_execution(
        execution_id,workspace_id,job_id,context_id,role,parent_execution_id)
      VALUES (:execution,:ws,:job,:context,:role,:parent) ON CONFLICT DO NOTHING
    """),
        {
            "execution": execution_id,
            "ws": scope.workspace_id,
            "job": scope.job_id,
            "context": context_id,
            "role": role,
            "parent": parent_execution_id,
        },
    )
    bound = (
        await conn.execute(
            text("""
      SELECT workspace_id,job_id,context_id,role,parent_execution_id
      FROM arv2_quality_execution WHERE execution_id=:execution
    """),
            {"execution": execution_id},
        )
    ).one()
    if tuple(bound) != (scope.workspace_id, scope.job_id, context_id, role, parent_execution_id):
        raise ValueError("execution already belongs to different research authority")


async def reserve(
    conn: AsyncConnection,
    scope: OperationScope,
    *,
    execution_id: UUID,
    kind: Literal["model", "tool", "delegation"],
    activity_id: UUID,
) -> None:
    if not await job_available(conn, scope, "quality_execution"):
        raise ValueError("research authority was withdrawn")
    await runtime_remaining(conn, scope)
    column = {"model": "model_calls", "tool": "tool_calls", "delegation": "delegations"}[kind]
    # Lock one shared job row before checking replay or consuming an allowance. Parent/child
    # concurrency and process restart cannot overspend the logical execution bounds.
    row = (
        await conn.execute(
            text(f"""
      SELECT a.{column},a.max_{column} FROM arv2_quality_allowance a
      JOIN arv2_quality_execution e ON e.job_id=a.job_id AND e.workspace_id=a.workspace_id
      WHERE e.execution_id=:execution AND a.job_id=:job AND a.workspace_id=:ws
        AND a.run_id=:run AND a.account_id=:account FOR UPDATE OF a
    """),
            {
                "execution": execution_id,
                "job": scope.job_id,
                "ws": scope.workspace_id,
                "run": scope.run_id,
                "account": scope.account_id,
            },
        )
    ).one_or_none()
    if row is None:
        raise ValueError("execution has no research allowance")
    prior = (
        await conn.execute(
            text("""
      SELECT workspace_id,job_id,execution_id,kind FROM arv2_quality_activity WHERE activity_id=:id
    """),
            {"id": activity_id},
        )
    ).one_or_none()
    if prior is not None:
        if tuple(prior) != (scope.workspace_id, scope.job_id, execution_id, kind):
            raise ValueError("activity replay differs from its original authority")
        return
    if row[0] >= row[1]:
        log.warning(
            "arv2.quality.allowance_exhausted",
            job_id=str(scope.job_id),
            execution_id=str(execution_id),
            kind=kind,
            used=row[0],
            limit=row[1],
        )
        raise ResearchAllowanceExhausted(f"shared research {kind} allowance exhausted")
    await conn.execute(
        text(f"UPDATE arv2_quality_allowance SET {column}={column}+1 WHERE job_id=:job"),
        {"job": scope.job_id},
    )
    await conn.execute(
        text("""
      INSERT INTO arv2_quality_activity(activity_id,workspace_id,job_id,execution_id,kind)
      VALUES (:id,:ws,:job,:execution,:kind)
    """),
        {
            "id": activity_id,
            "ws": scope.workspace_id,
            "job": scope.job_id,
            "execution": execution_id,
            "kind": kind,
        },
    )
    log.info(
        "arv2.quality.activity_reserved",
        job_id=str(scope.job_id),
        execution_id=str(execution_id),
        activity_id=str(activity_id),
        kind=kind,
    )


class SharedResearchAllowance(AgentMiddleware[Any, Any, Any]):
    """Reserve before every model dispatch, including bounded finalization repair calls."""

    def __init__(
        self,
        connections: ConnFactory,
        scope: OperationScope,
        execution_id: UUID,
        *,
        domain_tools: frozenset[str] = frozenset(),
    ):
        self._connections = connections
        self._scope = scope
        self._execution_id = execution_id
        self._domain_tools = domain_tools

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        async with self._connections() as conn:
            await reserve(
                conn,
                self._scope,
                execution_id=self._execution_id,
                kind="model",
                activity_id=uuid4(),
            )
        return await handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        # Domain tools reserve their persisted C5 operation once. Framework filesystem,
        # delegation and finalization tools also consume the shared tool allowance.
        if request.tool_call.get("name") not in self._domain_tools:
            call_id = request.tool_call.get("id")
            if not call_id:
                raise ValueError("research tool dispatch requires a stable call identity")
            async with self._connections() as conn:
                await reserve(
                    conn,
                    self._scope,
                    execution_id=self._execution_id,
                    kind="tool",
                    activity_id=uuid5(
                        NAMESPACE_URL, f"research-native-tool:{self._execution_id}:{call_id}"
                    ),
                )
        return await handler(request)


async def runtime_remaining(
    conn: AsyncConnection, scope: OperationScope, *, owner: UUID | None = None
) -> float:
    row = (
        await conn.execute(
            text("""SELECT runtime_owner_token,max_runtime_ms,
        (max_runtime_ms-runtime_used_ms)/1000.0 - CASE WHEN runtime_started_at IS NULL THEN 0
          ELSE EXTRACT(epoch FROM clock_timestamp()-runtime_started_at) END AS remaining
        FROM arv2_quality_allowance WHERE job_id=:job AND workspace_id=:ws"""),
            {"job": scope.job_id, "ws": scope.workspace_id},
        )
    ).one_or_none()
    if row is None or (owner is not None and row.runtime_owner_token != owner):
        raise ResearchAllowanceExhausted("research runtime authority is unavailable")
    if row.max_runtime_ms == 0:
        return float("inf")
    if row.remaining <= 0:
        raise ResearchAllowanceExhausted("shared research runtime allowance exhausted")
    return float(row.remaining)


async def begin_runtime(conn: AsyncConnection, scope: OperationScope, *, owner: UUID) -> float:
    await conn.execute(
        text(
            "SELECT job_id FROM arv2_quality_allowance "
            "WHERE job_id=:job AND workspace_id=:ws FOR UPDATE"
        ),
        {"job": scope.job_id, "ws": scope.workspace_id},
    )
    # An unfinished attempt's elapsed time stays charged after a crash. A fresh worker never
    # resets it, and only the existing fleet lease owner may enter this composition.
    await conn.execute(
        text("""UPDATE arv2_quality_allowance SET
        runtime_used_ms=LEAST(NULLIF(max_runtime_ms,0),runtime_used_ms+
            CASE WHEN runtime_started_at IS NULL THEN 0
            ELSE GREATEST(0,CEIL(EXTRACT(epoch FROM
                clock_timestamp()-runtime_started_at)*1000)::bigint) END),
        runtime_started_at=clock_timestamp(),runtime_owner_token=:owner
        WHERE job_id=:job AND workspace_id=:ws"""),
        {"job": scope.job_id, "ws": scope.workspace_id, "owner": owner},
    )
    remaining = await runtime_remaining(conn, scope, owner=owner)
    log.info("arv2.quality.runtime_started", job_id=str(scope.job_id), remaining_s=remaining)
    return remaining


async def finish_runtime(conn: AsyncConnection, scope: OperationScope, *, owner: UUID) -> None:
    result = await conn.execute(
        text("""UPDATE arv2_quality_allowance SET
        runtime_used_ms=LEAST(NULLIF(max_runtime_ms,0),runtime_used_ms+
            GREATEST(0,CEIL(EXTRACT(epoch FROM
                clock_timestamp()-runtime_started_at)*1000)::bigint)),
        runtime_started_at=NULL,runtime_owner_token=NULL
        WHERE job_id=:job AND workspace_id=:ws AND runtime_owner_token=:owner
        RETURNING runtime_used_ms,max_runtime_ms"""),
        {"job": scope.job_id, "ws": scope.workspace_id, "owner": owner},
    )
    row = result.one_or_none()
    if row:
        log.info(
            "arv2.quality.runtime_settled",
            job_id=str(scope.job_id),
            used_ms=row.runtime_used_ms,
            limit_ms=row.max_runtime_ms,
        )
