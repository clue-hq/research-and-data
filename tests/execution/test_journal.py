"""C5.1 durable invocation journal integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import (
    ExecutionRunEventWriter,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.auth_tool_context import tool_context_for_principal, tool_context_for_service
from clue_auth import (
    RequestPrincipal,
    ServicePrincipal,
    create_platform_user,
)
from clue_auth.store import create_workspace_membership
from clue_config import Settings
from clue_core import ExecutionId, new_execution_id, new_operation_id
from clue_execution import (
    DbExecutionJournal,
    DbExecutionRunViewReader,
    ExecutionEventType,
    OperationConflict,
    ParameterArtifactState,
    StaleCursor,
    ToolAuthorityStateChanged,
    get_cursor,
    list_run_events,
    rebuild_cursor,
    resolve_parameter_body,
)
from clue_toolbelt import (
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolInvoker,
    ToolOutput,
    ToolRegistry,
    ToolResult,
)
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.toolbelt.conftest import EchoInput, EchoTool, InMemoryStore

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _MemoryStorage:
    def __init__(self, *, fail_put: bool = False) -> None:
        self.blobs: dict[str, bytes] = {}
        self.fail_put = fail_put

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        if self.fail_put:
            raise RuntimeError("parameter storage unavailable")
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


class _JournalEcho(EchoTool):
    parameter_policy = JournalParameterPolicy(safe_display_fields=("value",))


class _FlakyEcho(_JournalEcho):
    name = "flaky_echo"

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EchoInput)
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("secret provider body must never be journaled")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"echoed": inputs.value},
        )


class _BlockedEcho(_JournalEcho):
    name = "blocked_echo"

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        return (
            PreconditionFailure(
                reason_code="approval_required",
                message="a human approval is required",
            ),
        )


class _SteeringInput(ToolInput):
    value: int


class _SteeringOutput(ToolOutput):
    value: int


class _SteeringTool(_JournalEcho):
    name = "steer"
    input_model = _SteeringInput
    output_model = _SteeringOutput
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("value",))

    def __init__(self) -> None:
        super().__init__()
        self.state = 0

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        return {"value": self.state}

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, _SteeringInput)
        self.state = inputs.value
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"value": self.state},
        )


def _savepoint_factory(conn: AsyncConnection):
    """Give each repository call real commit/rollback semantics inside the test transaction."""

    @asynccontextmanager
    async def _factory():
        nested = await conn.begin_nested()
        try:
            yield conn
        except BaseException:
            await nested.rollback()
            raise
        else:
            await nested.commit()

    return _factory


def _invoker(
    conn: AsyncConnection,
    *,
    tool,
    storage: _MemoryStorage | None = None,
) -> tuple[ToolInvoker, _MemoryStorage]:
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    resolved_storage = storage or _MemoryStorage()
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=InMemoryStore(),
        storage=resolved_storage,
        settings=Settings(_env_file=None),
        conn_factory=_savepoint_factory(conn),
    )
    return invoker, resolved_storage


def _ctx(conn: AsyncConnection, workspace_id: str, operation_id=None) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=operation_id or new_operation_id(),
    )


def test_success_replay_parameter_erasure_views_and_sse_replay() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-success")
            tool = _JournalEcho()
            invoker, storage = _invoker(conn, tool=tool)
            context = _ctx(conn, workspace_id)

            first = await invoker.invoke(
                tool.name,
                {"value": 7, "note": "private parameter text"},
                context,
            )
            replay = await invoker.invoke(
                tool.name,
                {"note": "private parameter text", "value": 7},
                context,
            )

            assert first.references == {"echoed": 7}
            assert first.replayed is False
            assert replay.replayed is True
            assert tool.invocations == [7]

            execution_id = ExecutionId(context.operation_id)
            reader = DbExecutionRunViewReader(conn_factory=conn_session_factory(conn))
            view = await reader.read_execution(
                workspace_id=workspace_id,
                execution_id=execution_id,
            )
            assert view is not None
            assert view.summary.status.value == "completed"
            assert view.summary.active_node_count == 0
            assert len(view.nodes) == 1
            assert view.nodes[0].display_params == {"value": 7}
            assert len(view.attempts) == 1
            event_types = [event.event_type for event in view.events]
            assert event_types == [
                ExecutionEventType.EXECUTION_QUEUED,
                ExecutionEventType.EXECUTION_STARTED,
                ExecutionEventType.NODE_SCHEDULED,
                ExecutionEventType.NODE_STARTED,
                ExecutionEventType.NODE_COMPLETED,
                ExecutionEventType.EXECUTION_COMPLETED,
            ]
            assert "private parameter text" not in view.model_dump_json()

            parameter_ref = view.artifact_refs[0]
            artifact_store = StorageParameterArtifactStore(
                storage=storage,
                conn_factory=_savepoint_factory(conn),
            )
            body = await resolve_parameter_body(
                store=artifact_store,
                workspace_id=workspace_id,
                artifact_key=parameter_ref.artifact_key,
                content_sha256=parameter_ref.content_sha256,
            )
            assert body.state is ParameterArtifactState.LIVE
            assert body.body == {"note": "private parameter text", "value": 7}

            async with conn_session_factory(conn)() as read_conn:
                all_events = await list_run_events(
                    read_conn,
                    workspace_id=workspace_id,
                    execution_id=execution_id,
                )
                replayed_events = await list_run_events(
                    read_conn,
                    workspace_id=workspace_id,
                    execution_id=execution_id,
                    after_seq=all_events[2].seq,
                )
            assert [event.seq for event in replayed_events] == [
                event.seq for event in all_events[3:]
            ]
            assert all(event.execution_id == execution_id for event in all_events)

            assert (
                await reader.read_execution(
                    workspace_id="ws-other",
                    execution_id=execution_id,
                )
                is None
            )
            # Review of F3 Phase 2: erasing one parameter body purges that one key and does no
            # fleet work. ``purge_erased_artifacts`` opens with an unfiltered
            # ``UPDATE artifact … WHERE expires_at <= now()`` and a sequential scan — the
            # keyless maintenance sweep's job, not this seam's to do on another owner's rows.
            expiring = f"{workspace_id}/{'e' * 64}"
            await storage.put(expiring, b"another owner's bytes", media_type="text/plain")
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, "
                    "media_type, size_bytes, expires_at) VALUES (:key, :ws, :sha, "
                    "'text/plain', 21, now() - interval '1 second')"
                ),
                {"key": expiring, "ws": workspace_id, "sha": "e" * 64},
            )

            erased = await artifact_store.erase_parameter(
                workspace_id=workspace_id,
                execution_id=execution_id,
                artifact_key=parameter_ref.artifact_key,
            )
            assert erased is True
            untouched = (
                await conn.execute(
                    text(
                        "SELECT erased_at, purged_at, privacy_erased FROM artifact "
                        "WHERE storage_key = :key"
                    ),
                    {"key": expiring},
                )
            ).one()
            assert tuple(untouched) == (None, None, False)
            assert await storage.exists(expiring)
            tombstone = await resolve_parameter_body(
                store=artifact_store,
                workspace_id=workspace_id,
                artifact_key=parameter_ref.artifact_key,
                content_sha256=parameter_ref.content_sha256,
            )
            assert tombstone.state is ParameterArtifactState.ERASED
            assert tombstone.body is None
            assert "private parameter text" not in tombstone.model_dump_json()

    run_async(scenario())


def test_authenticated_authority_is_durable_and_cannot_change_on_replay() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-b4-authority")
            user = await create_platform_user(conn, display_name="Authenticated human")
            membership = await create_workspace_membership(
                conn,
                workspace_id=workspace_id,
                user_id=user.user_id,
                role_key="operator",
            )
            principal = RequestPrincipal(
                user_id=user.user_id,
                membership_id=membership.membership_id,
                workspace_id=workspace_id,
                role_key="operator",
                permissions=frozenset({"thread.write"}),
                authenticated_at=datetime.now(UTC),
            )
            operation_id = new_operation_id()
            context = tool_context_for_principal(
                principal,
                conn_factory=conn_session_factory(conn),
                operation_id=operation_id,
                action_ref="turn-action:turn-b4-authority",
            )
            tool = _JournalEcho()
            invoker, _ = _invoker(conn, tool=tool)

            await invoker.invoke(tool.name, {"value": 8}, context)
            view = await DbExecutionRunViewReader(
                conn_factory=conn_session_factory(conn)
            ).read_execution(
                workspace_id=workspace_id,
                execution_id=ExecutionId(operation_id),
            )
            assert view is not None
            node = view.nodes[0]
            assert node.invocation_actor == "human"
            assert node.principal_kind == "human"
            assert node.authority_workspace_id == workspace_id
            assert node.actor_id == user.user_id
            assert node.membership_id == membership.membership_id
            assert node.action_ref == "turn-action:turn-b4-authority"

            other_user = await create_platform_user(conn, display_name="Different human")
            other_membership = await create_workspace_membership(
                conn,
                workspace_id=workspace_id,
                user_id=other_user.user_id,
                role_key="operator",
            )
            other_principal = principal.model_copy(
                update={
                    "user_id": other_user.user_id,
                    "membership_id": other_membership.membership_id,
                }
            )
            with pytest.raises(OperationConflict, match="authority"):
                await invoker.invoke(
                    tool.name,
                    {"value": 8},
                    tool_context_for_principal(
                        other_principal,
                        conn_factory=conn_session_factory(conn),
                        operation_id=operation_id,
                        action_ref="turn-action:turn-b4-authority",
                    ),
                )

            malformed_operation_id = new_operation_id()
            malformed_principal = principal.model_copy(
                update={"membership_id": other_membership.membership_id}
            )
            with pytest.raises(ToolAuthorityStateChanged):
                await invoker.invoke(
                    tool.name,
                    {"value": 10},
                    tool_context_for_principal(
                        malformed_principal,
                        conn_factory=conn_session_factory(conn),
                        operation_id=malformed_operation_id,
                        action_ref="turn-action:turn-b4-malformed",
                    ),
                )
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM execution WHERE id = :id"),
                    {"id": ExecutionId(malformed_operation_id)},
                )
            ).scalar_one() == 0

            service_operation_id = new_operation_id()
            service_context = tool_context_for_service(
                ServicePrincipal(
                    service_id="svc_agent_turn_worker",
                    workspace_id=workspace_id,
                    permissions=frozenset({"thread.write"}),
                    authenticated_at=datetime.now(UTC),
                ),
                conn_factory=conn_session_factory(conn),
                operation_id=service_operation_id,
                action_ref="turn-action:turn-b4-authority",
            )
            await invoker.invoke(tool.name, {"value": 9}, service_context)
            service_view = await DbExecutionRunViewReader(
                conn_factory=conn_session_factory(conn)
            ).read_execution(
                workspace_id=workspace_id,
                execution_id=ExecutionId(service_operation_id),
            )
            assert service_view is not None
            service_node = service_view.nodes[0]
            assert service_node.invocation_actor == "agent"
            assert service_node.principal_kind == "service"
            assert service_node.authority_workspace_id == workspace_id
            assert service_node.actor_id == "svc_agent_turn_worker"
            assert service_node.membership_id is None
            assert service_node.action_ref == "turn-action:turn-b4-authority"

    run_async(scenario())


def test_failed_attempt_retries_and_failure_payload_is_redacted() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-retry")
            tool = _FlakyEcho()
            invoker, _ = _invoker(conn, tool=tool)
            context = _ctx(conn, workspace_id)

            with pytest.raises(RuntimeError, match="secret provider"):
                await invoker.invoke(tool.name, {"value": 3}, context)
            result = await invoker.invoke(tool.name, {"value": 3}, context)
            assert result.references == {"echoed": 3}

            view = await DbExecutionRunViewReader(
                conn_factory=conn_session_factory(conn)
            ).read_execution(
                workspace_id=workspace_id,
                execution_id=ExecutionId(context.operation_id),
            )
            assert view is not None
            assert [attempt.attempt for attempt in view.attempts] == [1, 2]
            assert [event.event_type for event in view.events].count(
                ExecutionEventType.NODE_FAILED
            ) == 1
            assert [event.event_type for event in view.events].count(
                ExecutionEventType.NODE_COMPLETED
            ) == 1
            failed = next(
                event for event in view.events if event.event_type is ExecutionEventType.NODE_FAILED
            )
            assert failed.payload == {
                "error_code": "runtime_error",
                "summary": "tool invocation failed",
            }
            assert "secret provider" not in view.model_dump_json()
            assert view.summary.status.value == "completed"

    run_async(scenario())


def test_blocked_operation_is_permanent_and_steering_is_attributed() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-blocked")
            blocked = _BlockedEcho()
            invoker, _ = _invoker(conn, tool=blocked)
            context = _ctx(conn, workspace_id)
            for _ in range(2):
                with pytest.raises(PreconditionFailed) as raised:
                    await invoker.invoke(blocked.name, {"value": 2}, context)
                assert raised.value.reason_codes == ("approval_required",)
            blocked_view = await DbExecutionRunViewReader(
                conn_factory=conn_session_factory(conn)
            ).read_execution(
                workspace_id=workspace_id,
                execution_id=ExecutionId(context.operation_id),
            )
            assert blocked_view is not None
            assert len(blocked_view.attempts) == 1
            assert blocked_view.summary.status.value == "awaiting_input"
            assert [event.event_type for event in blocked_view.events].count(
                ExecutionEventType.NODE_BLOCKED
            ) == 1

            steering = _SteeringTool()
            steering_invoker, _ = _invoker(conn, tool=steering)
            steering_context = _ctx(conn, workspace_id)
            await steering_invoker.invoke(steering.name, {"value": 9}, steering_context)
            steering_view = await DbExecutionRunViewReader(
                conn_factory=conn_session_factory(conn)
            ).read_execution(
                workspace_id=workspace_id,
                execution_id=ExecutionId(steering_context.operation_id),
            )
            assert steering_view is not None
            snapshots = [
                event
                for event in steering_view.events
                if event.event_type
                in {
                    ExecutionEventType.STEERING_BEFORE,
                    ExecutionEventType.STEERING_AFTER,
                }
            ]
            assert [event.payload for event in snapshots] == [
                {"state": {"value": 0}},
                {"state": {"value": 9}},
            ]
            assert {event.actor for event in snapshots} == {"agent"}

    run_async(scenario())


def test_operation_conflict_and_snapshot_failure_create_no_orphan_invocation() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-orphans")
            tool = _JournalEcho()
            invoker, _ = _invoker(conn, tool=tool)
            context = _ctx(conn, workspace_id)
            await invoker.invoke(tool.name, {"value": 1}, context)
            with pytest.raises(OperationConflict):
                await invoker.invoke(tool.name, {"value": 2}, context)

            execution_id = ExecutionId(context.operation_id)
            node_attempt_counts = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM execution_node WHERE execution_id = :id),
                            (SELECT count(*) FROM execution_attempt WHERE execution_id = :id)
                        """
                    ),
                    {"id": execution_id},
                )
            ).one()
            assert node_attempt_counts == (1, 1)

            failing_storage = _MemoryStorage(fail_put=True)
            failing_invoker, _ = _invoker(
                conn,
                tool=_JournalEcho(),
                storage=failing_storage,
            )
            failed_context = _ctx(conn, workspace_id)
            with pytest.raises(RuntimeError, match="storage unavailable"):
                await failing_invoker.invoke(
                    tool.name,
                    {"value": 99, "note": "must not reach a journal"},
                    failed_context,
                )
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM execution WHERE id = :id"),
                    {"id": ExecutionId(failed_context.operation_id)},
                )
            ).scalar_one() == 0

            unknown_execution = new_execution_id()
            with pytest.raises(OperationConflict, match="unknown"):
                await invoker.invoke(
                    tool.name,
                    {"value": 5},
                    ToolContext(
                        workspace_id=workspace_id,
                        actor="agent",
                        conn_factory=conn_session_factory(conn),
                        operation_id=new_operation_id(),
                        execution_id=unknown_execution,
                    ),
                )
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM execution WHERE id = :id"),
                    {"id": unknown_execution},
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM execution_node n
                        LEFT JOIN execution e ON e.id = n.execution_id
                        WHERE e.id IS NULL
                        """
                    )
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_pre_b4_node_without_authority_remains_replayable() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-pre-b4-replay")
            tool = _JournalEcho()
            invoker, _ = _invoker(conn, tool=tool)
            context = _ctx(conn, workspace_id)
            first = await invoker.invoke(tool.name, {"value": 7}, context)
            execution_id = ExecutionId(context.operation_id)

            # Reproduce a node that predates the B4 authority table: the completed operation and
            # attempt exist, but the additive authority row does not.
            await conn.execute(
                text(
                    "ALTER TABLE execution_node_authority "
                    "DISABLE TRIGGER execution_node_authority_append_only"
                )
            )
            try:
                await conn.execute(
                    text("DELETE FROM execution_node_authority WHERE execution_id = :execution_id"),
                    {"execution_id": execution_id},
                )
            finally:
                await conn.execute(
                    text(
                        "ALTER TABLE execution_node_authority "
                        "ENABLE TRIGGER execution_node_authority_append_only"
                    )
                )
            replay = await invoker.invoke(tool.name, {"value": 7}, context)

            assert first.replayed is False
            assert replay.replayed is True
            assert tool.invocations == [7]

    run_async(scenario())


def test_cursor_rebuild_cas_rollback_and_append_only_guards() -> None:
    class _FailingTransport:
        async def append(self, conn, **kwargs) -> None:
            raise RuntimeError("transport unavailable")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-cursor")
            invoker, _ = _invoker(conn, tool=_JournalEcho())
            context = _ctx(conn, workspace_id)
            await invoker.invoke("echo", {"value": 4}, context)
            execution_id = ExecutionId(context.operation_id)

            expected = await get_cursor(conn, execution_id)
            before_events = (
                await conn.execute(
                    text("SELECT count(*) FROM execution_event WHERE execution_id = :id"),
                    {"id": execution_id},
                )
            ).scalar_one()
            before_transport = (
                await conn.execute(
                    text("SELECT count(*) FROM run_event WHERE execution_id = :id"),
                    {"id": execution_id},
                )
            ).scalar_one()
            failing = DbExecutionJournal(transport=_FailingTransport())
            with pytest.raises(RuntimeError, match="transport unavailable"):
                async with _savepoint_factory(conn)() as tx:
                    await failing.append_event(
                        tx,
                        execution_id=execution_id,
                        event_type=ExecutionEventType.SUPERVISOR_OBSERVED,
                        actor="system",
                        expected_state_version=expected.state_version,
                    )
            assert await get_cursor(conn, execution_id) == expected
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM execution_event WHERE execution_id = :id"),
                    {"id": execution_id},
                )
            ).scalar_one() == before_events
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM run_event WHERE execution_id = :id"),
                    {"id": execution_id},
                )
            ).scalar_one() == before_transport

            repository = DbExecutionJournal(transport=ExecutionRunEventWriter())
            with pytest.raises(StaleCursor):
                async with _savepoint_factory(conn)() as tx:
                    await repository.append_event(
                        tx,
                        execution_id=execution_id,
                        event_type=ExecutionEventType.SUPERVISOR_OBSERVED,
                        actor="system",
                        expected_state_version=expected.state_version - 1,
                    )

            await conn.execute(
                text("DELETE FROM execution_cursor WHERE execution_id = :id"),
                {"id": execution_id},
            )
            rebuilt = await rebuild_cursor(conn, execution_id)
            assert rebuilt == expected

            node_id = (
                await conn.execute(
                    text("SELECT id FROM execution_node WHERE execution_id = :id"),
                    {"id": execution_id},
                )
            ).scalar_one()
            with pytest.raises(DBAPIError, match="append-only"):
                async with conn.begin_nested():
                    await conn.execute(
                        text("UPDATE execution_node SET node_key = 'mutated' WHERE id = :id"),
                        {"id": UUID(str(node_id))},
                    )

    run_async(scenario())


def test_c5_1_schema_is_complete_and_has_one_mutable_execution_table() -> None:
    async def scenario() -> None:
        expected_tables = {
            "recipe",
            "recipe_revision",
            "recipe_revision_event",
            "execution",
            "execution_cursor",
            "execution_node",
            "execution_edge",
            "execution_pin",
            "execution_attempt",
            "execution_event",
            "execution_artifact_ref",
            "project_run_execution_owner",
            "supervisor_observation",
            "supervisor_diagnosis",
            "run_control_event",
        }
        append_only = expected_tables - {"execution_cursor"}
        async with rollback_conn(seed_pack=False) as conn:
            present = set(
                (
                    await conn.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = 'public' AND tablename = ANY(:names)"
                        ),
                        {"names": list(expected_tables)},
                    )
                )
                .scalars()
                .all()
            )
            assert present == expected_tables
            guarded = set(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT event_object_table
                            FROM information_schema.triggers
                            WHERE trigger_schema = 'public'
                              AND trigger_name LIKE '%_append_only'
                            """
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert append_only <= guarded
            run_event_columns = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = 'run_event'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "execution_id" in run_event_columns

    run_async(scenario())
