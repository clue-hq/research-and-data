"""Append-only execution journal and the toolbelt InvocationJournal implementation."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionNodeId,
    decode_jsonb,
    serialize_value_json,
)
from clue_db import ConnFactory
from clue_execution.models import ExecutionEventType, ExecutionStatus
from clue_toolbelt import (
    InvocationJournal,
    JournalDisposition,
    JournalStart,
    ParameterSnapshot,
    ToolContext,
    ToolDescriptor,
    ToolResult,
)

EMPTY_MANIFEST_SHA256 = hashlib.sha256(b"{}").hexdigest()


class StaleCursor(RuntimeError):
    def __init__(self, execution_id: ExecutionId, expected: int) -> None:
        super().__init__(
            f"execution {execution_id} cursor no longer has expected state version {expected}"
        )
        self.execution_id = execution_id
        self.expected = expected


class OperationConflict(RuntimeError):
    pass


class LostExecutionLease(RuntimeError):
    pass


class _LeaseKwargs(TypedDict):
    expected_worker_id: str | None
    expected_lease_generation: int | None


class ExecutionTransportWriter(Protocol):
    async def append(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        run_id: UUID,
        execution_id: ExecutionId,
        topic: str,
        payload: dict[str, JsonValue],
    ) -> None: ...


type JournalCrashHook = Callable[
    [str, ExecutionId, ExecutionNodeId | None, ExecutionAttemptId | None],
    Awaitable[None],
]


async def _no_journal_crash(
    _point: str,
    _execution_id: ExecutionId,
    _node_id: ExecutionNodeId | None,
    _attempt_id: ExecutionAttemptId | None,
) -> None:
    return None


@dataclass(frozen=True, slots=True)
class ExecutionCursor:
    execution_id: ExecutionId
    status: ExecutionStatus
    state_version: int
    active_node_count: int
    last_event_seq: int | None
    lease_generation: int | None = None


def _node_id(execution_id: ExecutionId, operation_id: UUID) -> ExecutionNodeId:
    return ExecutionNodeId(
        uuid5(NAMESPACE_URL, f"clue-execution-node:{execution_id}:{operation_id}")
    )


def _cursor_from_row(row: dict[str, object]) -> ExecutionCursor:
    return ExecutionCursor(
        execution_id=ExecutionId(row["execution_id"]),  # type: ignore[arg-type]
        status=ExecutionStatus(str(row["status"])),
        state_version=int(cast(int, row["state_version"])),
        active_node_count=int(cast(int, row["active_node_count"])),
        last_event_seq=(
            int(cast(int, row["last_event_seq"])) if row["last_event_seq"] is not None else None
        ),
        lease_generation=(
            int(cast(int, row["lease_generation"]))
            if row.get("lease_generation") is not None
            else None
        ),
    )


async def get_cursor(
    conn: AsyncConnection, execution_id: ExecutionId, *, for_update: bool = False
) -> ExecutionCursor:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    "SELECT execution_id, status, state_version, active_node_count, "
                    "last_event_seq, lease_generation "
                    f"FROM execution_cursor WHERE execution_id = :id{suffix}"
                ),
                {"id": execution_id},
            )
        )
        .mappings()
        .one()
    )
    return _cursor_from_row(dict(row))


def _project_event(
    cursor: ExecutionCursor, event_type: ExecutionEventType
) -> tuple[ExecutionStatus, int]:
    status = cursor.status
    active = cursor.active_node_count
    if event_type is ExecutionEventType.EXECUTION_QUEUED:
        status = ExecutionStatus.QUEUED
    elif event_type in (
        ExecutionEventType.EXECUTION_STARTED,
        ExecutionEventType.EXECUTION_RESUMED,
        ExecutionEventType.GATE_DECIDED,
    ):
        status = ExecutionStatus.RUNNING
    elif event_type is ExecutionEventType.EXECUTION_PAUSED:
        status = ExecutionStatus.PAUSED
    elif event_type in (
        ExecutionEventType.GATE_OPENED,
        ExecutionEventType.NODE_BLOCKED,
    ):
        status = ExecutionStatus.AWAITING_INPUT
    elif event_type is ExecutionEventType.EXECUTION_COMPLETED:
        status = ExecutionStatus.COMPLETED
    elif event_type is ExecutionEventType.EXECUTION_FAILED:
        status = ExecutionStatus.FAILED

    if event_type is ExecutionEventType.NODE_STARTED:
        active += 1
    elif event_type in (
        ExecutionEventType.NODE_BLOCKED,
        ExecutionEventType.NODE_COMPLETED,
        ExecutionEventType.NODE_FAILED,
        ExecutionEventType.NODE_ABANDONED,
    ):
        active -= 1
        if active < 0:
            raise ValueError("execution event history would make active_node_count negative")
    return status, active


class DbExecutionJournal:
    """Raw-SQL journal repository; all event/cursor/outbox writes share one transaction."""

    def __init__(
        self,
        *,
        transport: ExecutionTransportWriter,
        crash_hook: JournalCrashHook = _no_journal_crash,
    ) -> None:
        self._transport = transport
        self._crash_hook = crash_hook

    async def append_event(
        self,
        conn: AsyncConnection,
        *,
        execution_id: ExecutionId,
        event_type: ExecutionEventType,
        actor: str,
        payload: dict[str, object] | None = None,
        node_id: ExecutionNodeId | None = None,
        attempt_id: ExecutionAttemptId | None = None,
        expected_state_version: int,
        expected_worker_id: str | None = None,
        expected_lease_generation: int | None = None,
    ) -> int:
        if (expected_worker_id is None) != (expected_lease_generation is None):
            raise ValueError("lease worker and generation must be supplied together")
        if expected_worker_id is not None:
            lease = (
                await conn.execute(
                    text(
                        """
                        SELECT 1 FROM work_lease
                        WHERE work_id = :execution_id
                          AND worker_id = :worker_id
                          AND generation = :generation
                          AND expires_at > now()
                        FOR UPDATE
                        """
                    ),
                    {
                        "execution_id": execution_id,
                        "worker_id": expected_worker_id,
                        "generation": expected_lease_generation,
                    },
                )
            ).one_or_none()
            if lease is None:
                raise LostExecutionLease(
                    f"execution {execution_id} lease generation "
                    f"{expected_lease_generation} is no longer owned by {expected_worker_id}"
                )
        cursor = await get_cursor(conn, execution_id, for_update=True)
        if cursor.state_version != expected_state_version:
            raise StaleCursor(execution_id, expected_state_version)
        status, active = _project_event(cursor, event_type)
        safe_payload = payload or {}
        row = (
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO execution_event
                            (execution_id, node_id, attempt_id, event_type, actor, payload_json)
                        VALUES
                            (:execution_id, :node_id, :attempt_id, :event_type, :actor,
                             CAST(:payload AS jsonb))
                        RETURNING seq
                        """
                    ),
                    {
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "attempt_id": attempt_id,
                        "event_type": event_type.value,
                        "actor": actor,
                        "payload": serialize_value_json(safe_payload),
                    },
                )
            )
            .mappings()
            .one()
        )
        seq = int(row["seq"])
        await self._crash_hook(
            "after_event_insert",
            execution_id,
            node_id,
            attempt_id,
        )
        execution = (
            (
                await conn.execute(
                    text("SELECT workspace_id, project_run_id FROM execution WHERE id = :id"),
                    {"id": execution_id},
                )
            )
            .mappings()
            .one()
        )
        transport_payload: dict[str, JsonValue] = {
            "execution_id": str(execution_id),
            "execution_event_seq": seq,
            "node_id": str(node_id) if node_id is not None else None,
            "attempt_id": str(attempt_id) if attempt_id is not None else None,
            "payload": safe_payload,  # type: ignore[dict-item]
        }
        await self._transport.append(
            conn,
            workspace_id=str(execution["workspace_id"]),
            run_id=(
                UUID(str(execution["project_run_id"]))
                if execution["project_run_id"] is not None
                else UUID(str(execution_id))
            ),
            execution_id=execution_id,
            topic=event_type.value,
            payload=transport_payload,
        )
        updated = await conn.execute(
            text(
                """
                UPDATE execution_cursor
                SET status = :status,
                    state_version = state_version + 1,
                    active_node_count = :active,
                    last_event_seq = :seq,
                    lease_generation = COALESCE(:lease_generation, lease_generation),
                    updated_at = now()
                WHERE execution_id = :execution_id AND state_version = :expected
                  AND (
                    CAST(:lease_generation AS bigint) IS NULL
                    OR EXISTS (
                        SELECT 1 FROM work_lease
                        WHERE work_id = :execution_id
                          AND worker_id = :worker_id
                          AND generation = :lease_generation
                          AND expires_at > now()
                    )
                  )
                """
            ),
            {
                "status": status.value,
                "active": active,
                "seq": seq,
                "execution_id": execution_id,
                "expected": expected_state_version,
                "worker_id": expected_worker_id,
                "lease_generation": expected_lease_generation,
            },
        )
        if updated.rowcount != 1:
            if expected_lease_generation is not None:
                raise LostExecutionLease(
                    f"execution {execution_id} lost lease generation "
                    f"{expected_lease_generation} during cursor projection"
                )
            raise StaleCursor(execution_id, expected_state_version)
        await self._crash_hook(
            "after_cursor_update",
            execution_id,
            node_id,
            attempt_id,
        )
        return seq


async def rebuild_cursor(
    conn: AsyncConnection,
    execution_id: ExecutionId,
    *,
    expected_worker_id: str | None = None,
    expected_lease_generation: int | None = None,
) -> ExecutionCursor:
    """Rebuild the mutable cursor only from authoritative append-only events."""
    if (expected_worker_id is None) != (expected_lease_generation is None):
        raise ValueError("lease worker and generation must be supplied together")
    if expected_worker_id is not None:
        lease = (
            await conn.execute(
                text(
                    """
                    SELECT 1 FROM work_lease
                    WHERE work_id = :execution_id
                      AND worker_id = :worker_id
                      AND generation = :generation
                      AND expires_at > now()
                    FOR UPDATE
                    """
                ),
                {
                    "execution_id": execution_id,
                    "worker_id": expected_worker_id,
                    "generation": expected_lease_generation,
                },
            )
        ).one_or_none()
        if lease is None:
            raise LostExecutionLease("cannot rebuild cursor after losing the execution lease")
    exists = await conn.execute(
        text("SELECT 1 FROM execution WHERE id = :id"), {"id": execution_id}
    )
    if exists.one_or_none() is None:
        raise ValueError("cannot rebuild cursor for an unknown execution")
    cursor = ExecutionCursor(
        execution_id=execution_id,
        status=ExecutionStatus.QUEUED,
        state_version=0,
        active_node_count=0,
        last_event_seq=None,
        lease_generation=expected_lease_generation,
    )
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT seq, event_type FROM execution_event "
                    "WHERE execution_id = :id ORDER BY seq"
                ),
                {"id": execution_id},
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        status, active = _project_event(cursor, ExecutionEventType(str(row["event_type"])))
        cursor = ExecutionCursor(
            execution_id=execution_id,
            status=status,
            state_version=cursor.state_version + 1,
            active_node_count=active,
            last_event_seq=int(row["seq"]),
            lease_generation=expected_lease_generation,
        )
    await conn.execute(
        text(
            """
            INSERT INTO execution_cursor
                (execution_id, status, state_version, active_node_count, last_event_seq,
                 lease_generation)
            VALUES (:id, :status, :version, :active, :last_seq, :lease_generation)
            ON CONFLICT (execution_id) DO UPDATE SET
                status = EXCLUDED.status,
                state_version = EXCLUDED.state_version,
                active_node_count = EXCLUDED.active_node_count,
                last_event_seq = EXCLUDED.last_event_seq,
                lease_generation = EXCLUDED.lease_generation,
                updated_at = now()
            """
        ),
        {
            "id": execution_id,
            "status": cursor.status.value,
            "version": cursor.state_version,
            "active": cursor.active_node_count,
            "last_seq": cursor.last_event_seq,
            "lease_generation": expected_lease_generation,
        },
    )
    return cursor


class DbInvocationJournal(InvocationJournal):
    def __init__(
        self,
        *,
        conn_factory: ConnFactory,
        repository: DbExecutionJournal,
    ) -> None:
        self._conn_factory = conn_factory
        self._repository = repository

    @staticmethod
    def _lease_kwargs(context: ToolContext) -> _LeaseKwargs:
        return {
            "expected_worker_id": context.execution_worker_id,
            "expected_lease_generation": context.lease_generation,
        }

    async def begin(
        self,
        *,
        descriptor: ToolDescriptor,
        context: ToolContext,
        snapshot: ParameterSnapshot,
    ) -> JournalStart:
        owns_execution = context.execution_id is None
        execution_id = context.execution_id or ExecutionId(context.operation_id)
        node_id = context.execution_node_id or _node_id(execution_id, context.operation_id)
        node_key = context.execution_node_key or (f"{descriptor.address}:{context.operation_id}")
        async with self._conn_factory() as conn:
            execution_created = False
            if owns_execution:
                inserted = await conn.execute(
                    text(
                        """
                        INSERT INTO execution
                            (id, workspace_id, parent_execution_id, started_by,
                             parameter_manifest_hash, pin_manifest_hash)
                        VALUES
                            (:id, :workspace_id, :parent, :actor, :parameters, :pins)
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": execution_id,
                        "workspace_id": context.workspace_id,
                        "parent": context.parent_execution_id,
                        "actor": context.actor,
                        "parameters": snapshot.content_sha256,
                        "pins": EMPTY_MANIFEST_SHA256,
                    },
                )
                execution_created = inserted.rowcount == 1
            execution = (
                (
                    await conn.execute(
                        text(
                            "SELECT workspace_id, parent_execution_id FROM execution WHERE id = :id"
                        ),
                        {"id": execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if execution is None or str(execution["workspace_id"]) != context.workspace_id:
                raise OperationConflict(
                    "explicit execution id is unknown or belongs to another workspace"
                )
            stored_parent = (
                str(execution["parent_execution_id"])
                if execution["parent_execution_id"] is not None
                else None
            )
            requested_parent = (
                str(context.parent_execution_id)
                if context.parent_execution_id is not None
                else None
            )
            if stored_parent != requested_parent:
                raise OperationConflict("execution id was replayed with a different parent")
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_cursor (execution_id, status)
                    VALUES (:id, 'queued')
                    ON CONFLICT (execution_id) DO NOTHING
                    """
                ),
                {"id": execution_id},
            )
            if execution_created:
                cursor = await get_cursor(conn, execution_id)
                await self._repository.append_event(
                    conn,
                    execution_id=execution_id,
                    event_type=ExecutionEventType.EXECUTION_QUEUED,
                    actor=context.actor,
                    expected_state_version=cursor.state_version,
                    **self._lease_kwargs(context),
                )
                cursor = await get_cursor(conn, execution_id)
                await self._repository.append_event(
                    conn,
                    execution_id=execution_id,
                    event_type=ExecutionEventType.EXECUTION_STARTED,
                    actor=context.actor,
                    expected_state_version=cursor.state_version,
                    **self._lease_kwargs(context),
                )

            node_insert = await conn.execute(
                text(
                    """
                    INSERT INTO execution_node
                        (id, execution_id, node_key, kind, tool_name, tool_version, operation_id,
                         parameter_artifact_key, parameter_sha256, input_schema_sha256,
                         output_schema_sha256, display_params_json)
                    VALUES
                        (:id, :execution_id, :node_key, 'tool', :tool_name, :tool_version,
                         :operation_id, :artifact_key, :parameter_sha, :input_sha, :output_sha,
                         CAST(:display AS jsonb))
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "id": node_id,
                    "execution_id": execution_id,
                    "node_key": node_key,
                    "tool_name": descriptor.name,
                    "tool_version": descriptor.version,
                    "operation_id": context.operation_id,
                    "artifact_key": snapshot.artifact_key,
                    "parameter_sha": snapshot.content_sha256,
                    "input_sha": descriptor.input_schema_sha256,
                    "output_sha": descriptor.output_schema_sha256,
                    "display": serialize_value_json(snapshot.display_params),
                },
            )
            node_created = node_insert.rowcount == 1
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_node_authority
                        (node_id, execution_id, authority_workspace_id, invocation_actor,
                         principal_kind, actor_id, membership_id, action_ref)
                    SELECT :node_id, :execution_id, :authority_workspace_id, :invocation_actor,
                           :principal_kind, :actor_id, :membership_id, :action_ref
                    WHERE NOT EXISTS (
                        SELECT 1 FROM execution_attempt a WHERE a.node_id = :node_id
                    )
                    ON CONFLICT (node_id) DO NOTHING
                    """
                ),
                {
                    "node_id": node_id,
                    "execution_id": execution_id,
                    "authority_workspace_id": (
                        context.workspace_id if context.principal_kind is not None else None
                    ),
                    "invocation_actor": context.actor,
                    "principal_kind": context.principal_kind,
                    "actor_id": context.actor_id,
                    "membership_id": context.membership_id,
                    "action_ref": context.action_ref,
                },
            )
            node = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT n.id, n.node_key, n.tool_name, n.tool_version,
                                   n.parameter_artifact_key, n.parameter_sha256,
                                   n.input_schema_sha256, n.output_schema_sha256,
                                   a.invocation_actor, a.principal_kind,
                                   a.authority_workspace_id, a.actor_id, a.membership_id,
                                   a.action_ref
                            FROM execution_node n
                            LEFT JOIN execution_node_authority a ON a.node_id = n.id
                            WHERE n.execution_id = :execution_id
                              AND n.operation_id = :operation_id
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "operation_id": context.operation_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            expected_node = (
                node_key,
                descriptor.name,
                descriptor.version,
                descriptor.input_schema_sha256,
                descriptor.output_schema_sha256,
                context.actor,
                context.principal_kind,
                context.workspace_id if context.principal_kind is not None else None,
                context.actor_id,
                context.membership_id,
                context.action_ref,
            )
            actual_node = (
                (
                    str(node["node_key"]),
                    str(node["tool_name"]),
                    str(node["tool_version"]),
                    str(node["input_schema_sha256"]),
                    str(node["output_schema_sha256"]),
                    str(node["invocation_actor"]),
                    (str(node["principal_kind"]) if node["principal_kind"] is not None else None),
                    (
                        str(node["authority_workspace_id"])
                        if node["authority_workspace_id"] is not None
                        else None
                    ),
                    str(node["actor_id"]) if node["actor_id"] is not None else None,
                    (str(node["membership_id"]) if node["membership_id"] is not None else None),
                    str(node["action_ref"]) if node["action_ref"] is not None else None,
                )
                if node is not None
                else None
            )
            if actual_node != expected_node or (
                node is not None and str(node["id"]) != str(node_id)
            ):
                raise OperationConflict(
                    "operation id or node key was replayed with different "
                    "tool/body/schema/authority"
                )
            existing_parameter = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT artifact_key, content_sha256
                            FROM execution_artifact_ref
                            WHERE execution_id = :execution_id
                              AND node_id = :node_id
                              AND role = 'parameter'
                            """
                        ),
                        {"execution_id": execution_id, "node_id": node_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing_parameter is not None and (
                str(existing_parameter["artifact_key"]) != snapshot.artifact_key
                or str(existing_parameter["content_sha256"]) != snapshot.content_sha256
            ):
                raise OperationConflict(
                    "operation id was replayed with a different parameter artifact"
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_artifact_ref
                        (execution_id, node_id, workspace_id, artifact_key, role, content_sha256)
                    VALUES (:execution_id, :node_id, :workspace_id, :artifact_key,
                            'parameter', :sha)
                    ON CONFLICT (execution_id, node_id, artifact_key, role) DO NOTHING
                    """
                ),
                {
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "workspace_id": context.workspace_id,
                    "artifact_key": snapshot.artifact_key,
                    "sha": snapshot.content_sha256,
                },
            )

            terminal = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT event_type, payload_json
                            FROM execution_event
                            WHERE node_id = :node_id
                              AND event_type IN ('node.completed', 'node.blocked')
                            ORDER BY seq DESC LIMIT 1
                            """
                        ),
                        {"node_id": node_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if terminal is not None:
                payload = decode_jsonb(terminal["payload_json"])
                if terminal["event_type"] == ExecutionEventType.NODE_COMPLETED.value:
                    return JournalStart(
                        execution_id=execution_id,
                        node_id=node_id,
                        attempt_id=None,
                        disposition=JournalDisposition.COMPLETED,
                        owns_execution=owns_execution,
                        result=ToolResult.model_validate(payload["result"]),
                    )
                return JournalStart(
                    execution_id=execution_id,
                    node_id=node_id,
                    attempt_id=None,
                    disposition=JournalDisposition.BLOCKED,
                    owns_execution=owns_execution,
                    blocked_reason_codes=tuple(payload["reason_codes"]),
                )

            attempt_number = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(max(attempt), 0) + 1 "
                            "FROM execution_attempt WHERE node_id = :node_id"
                        ),
                        {"node_id": node_id},
                    )
                ).scalar_one()
            )
            attempt_id = ExecutionAttemptId(uuid4())
            await conn.execute(
                text(
                    """
                    INSERT INTO execution_attempt
                        (id, execution_id, node_id, attempt, worker_id, lease_generation)
                    VALUES (:id, :execution_id, :node_id, :attempt, :worker_id, :generation)
                    """
                ),
                {
                    "id": attempt_id,
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "attempt": attempt_number,
                    "worker_id": context.execution_worker_id,
                    "generation": context.lease_generation,
                },
            )
            if node_created:
                cursor = await get_cursor(conn, execution_id, for_update=True)
                await self._repository.append_event(
                    conn,
                    execution_id=execution_id,
                    node_id=node_id,
                    event_type=ExecutionEventType.NODE_SCHEDULED,
                    actor=context.actor,
                    payload={
                        "tool_address": descriptor.address,
                        "parameter_artifact_key": snapshot.artifact_key,
                        "parameter_sha256": snapshot.content_sha256,
                        "input_schema_sha256": descriptor.input_schema_sha256,
                        "output_schema_sha256": descriptor.output_schema_sha256,
                    },
                    expected_state_version=cursor.state_version,
                    **self._lease_kwargs(context),
                )
            cursor = await get_cursor(conn, execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=execution_id,
                node_id=node_id,
                attempt_id=attempt_id,
                event_type=ExecutionEventType.NODE_STARTED,
                actor=context.actor,
                payload={"attempt": attempt_number},
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )
            return JournalStart(
                execution_id=execution_id,
                node_id=node_id,
                attempt_id=attempt_id,
                disposition=JournalDisposition.STARTED,
                owns_execution=owns_execution,
            )

    async def steering_snapshot(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        phase: str,
        state: dict[str, object],
    ) -> None:
        if phase not in {"before", "after"}:
            raise ValueError("steering snapshot phase must be before or after")
        assert start.attempt_id is not None
        async with self._conn_factory() as conn:
            cursor = await get_cursor(conn, start.execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=start.execution_id,
                node_id=start.node_id,
                attempt_id=start.attempt_id,
                event_type=(
                    ExecutionEventType.STEERING_BEFORE
                    if phase == "before"
                    else ExecutionEventType.STEERING_AFTER
                ),
                actor=context.actor,
                payload={"state": state},
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )

    async def blocked(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        reason_codes: tuple[str, ...],
    ) -> None:
        assert start.attempt_id is not None
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM execution_node WHERE id = :id FOR UPDATE"),
                {"id": start.node_id},
            )
            if await self._has_terminal(conn, start.node_id):
                return
            cursor = await get_cursor(conn, start.execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=start.execution_id,
                node_id=start.node_id,
                attempt_id=start.attempt_id,
                event_type=ExecutionEventType.NODE_BLOCKED,
                actor=context.actor,
                payload={"reason_codes": list(reason_codes), "summary": "precondition blocked"},
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )

    async def awaiting_input(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        reason_code: str,
    ) -> None:
        """End this attempt without terminally resolving its node, then pause the execution."""
        assert start.attempt_id is not None
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM execution_node WHERE id = :id FOR UPDATE"),
                {"id": start.node_id},
            )
            if await self._has_terminal(conn, start.node_id):
                return
            cursor = await get_cursor(conn, start.execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=start.execution_id,
                node_id=start.node_id,
                attempt_id=start.attempt_id,
                event_type=ExecutionEventType.NODE_ABANDONED,
                actor=context.actor,
                payload={"reason_code": reason_code},
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )
            cursor = await get_cursor(conn, start.execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=start.execution_id,
                event_type=ExecutionEventType.EXECUTION_PAUSED,
                actor=context.actor,
                payload={"reason_code": reason_code, "node_id": str(start.node_id)},
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )

    async def failed(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        error_code: str,
    ) -> None:
        assert start.attempt_id is not None
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM execution_node WHERE id = :id FOR UPDATE"),
                {"id": start.node_id},
            )
            if await self._has_terminal(conn, start.node_id):
                return
            cursor = await get_cursor(conn, start.execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=start.execution_id,
                node_id=start.node_id,
                attempt_id=start.attempt_id,
                event_type=ExecutionEventType.NODE_FAILED,
                actor=context.actor,
                payload={
                    "error_code": error_code,
                    "summary": "tool invocation failed",
                },
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )

    async def completed(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        result: ToolResult,
    ) -> ToolResult:
        assert start.attempt_id is not None
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM execution_node WHERE id = :id FOR UPDATE"),
                {"id": start.node_id},
            )
            existing = await self._terminal(conn, start.node_id)
            if existing is not None:
                event_type, payload = existing
                if event_type != ExecutionEventType.NODE_COMPLETED.value:
                    raise OperationConflict("a blocked operation cannot later complete")
                return ToolResult.model_validate(payload["result"]).model_copy(
                    update={"replayed": True}
                )
            cursor = await get_cursor(conn, start.execution_id, for_update=True)
            await self._repository.append_event(
                conn,
                execution_id=start.execution_id,
                node_id=start.node_id,
                attempt_id=start.attempt_id,
                event_type=ExecutionEventType.NODE_COMPLETED,
                actor=context.actor,
                payload={"result": result.model_dump(mode="json")},
                expected_state_version=cursor.state_version,
                **self._lease_kwargs(context),
            )
            if start.owns_execution:
                cursor = await get_cursor(conn, start.execution_id, for_update=True)
                await self._repository.append_event(
                    conn,
                    execution_id=start.execution_id,
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    actor=context.actor,
                    payload={"node_id": str(start.node_id)},
                    expected_state_version=cursor.state_version,
                    **self._lease_kwargs(context),
                )
        return result

    @staticmethod
    async def _terminal(
        conn: AsyncConnection, node_id: ExecutionNodeId
    ) -> tuple[str, dict[str, object]] | None:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT event_type, payload_json
                        FROM execution_event
                        WHERE node_id = :node_id
                          AND event_type IN ('node.completed', 'node.blocked')
                        ORDER BY seq DESC LIMIT 1
                        """
                    ),
                    {"node_id": node_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return str(row["event_type"]), decode_jsonb(row["payload_json"])

    @classmethod
    async def _has_terminal(cls, conn: AsyncConnection, node_id: ExecutionNodeId) -> bool:
        return await cls._terminal(conn, node_id) is not None


__all__ = [
    "DbExecutionJournal",
    "DbInvocationJournal",
    "EMPTY_MANIFEST_SHA256",
    "ExecutionCursor",
    "ExecutionTransportWriter",
    "LostExecutionLease",
    "JournalCrashHook",
    "OperationConflict",
    "StaleCursor",
    "get_cursor",
    "rebuild_cursor",
]
