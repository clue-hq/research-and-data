"""C5.5 append-only control replay, isolation, cooldown, and envelope enforcement."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api import ExecutionRunEventWriter
from clue_config import SupervisorAutomaticAction, SupervisorPolicy
from clue_core import new_execution_id, new_operation_id, new_project_run_id
from clue_execution import (
    ControlAction,
    ControlKind,
    ControlPolicyViolation,
    DbExecutionJournal,
    DbRunControlStore,
)
from clue_research.durable import ensure_project_run
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.execution.test_executor import _factory, _runtime
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_controls_are_replay_safe_isolated_and_append_only() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, _executor, _tool, _generation = await _runtime(conn)
            factory = _factory(conn)
            store = DbRunControlStore(
                conn_factory=factory,
                journal=DbExecutionJournal(transport=ExecutionRunEventWriter()),
                policy=SupervisorPolicy(breaker_cooldown_s=0),
            )
            operation_id = new_operation_id()
            first = await store.mutate(
                workspace_id="ws-c5-executor",
                execution_id=execution_id,
                operation_id=operation_id,
                control_kind=ControlKind.SOURCE_BREAKER,
                subject_ref="provider-a",
                action=ControlAction.APPLY,
                reason_code="canary_error_rate",
                actor="agent",
            )
            replay = await store.mutate(
                workspace_id="ws-c5-executor",
                execution_id=execution_id,
                operation_id=operation_id,
                control_kind=ControlKind.SOURCE_BREAKER,
                subject_ref="provider-a",
                action=ControlAction.APPLY,
                reason_code="canary_error_rate",
                actor="agent",
            )
            assert replay.seq == first.seq
            assert not await store.source_allowed(execution_id, "provider-a")
            assert await store.source_allowed(execution_id, "provider-b")
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM run_control_event "
                        "WHERE execution_id = :execution_id AND operation_id = :operation_id"
                    ),
                    {"execution_id": execution_id, "operation_id": operation_id},
                )
            ).scalar_one()
            assert count == 1

            with pytest.raises(ControlPolicyViolation, match="different control mutation"):
                await store.mutate(
                    workspace_id="ws-c5-executor",
                    execution_id=execution_id,
                    operation_id=operation_id,
                    control_kind=ControlKind.SOURCE_BREAKER,
                    subject_ref="provider-b",
                    action=ControlAction.APPLY,
                    reason_code="changed",
                    actor="agent",
                )

            await store.mutate(
                workspace_id="ws-c5-executor",
                execution_id=execution_id,
                operation_id=new_operation_id(),
                control_kind=ControlKind.SOURCE_BREAKER,
                subject_ref="provider-a",
                action=ControlAction.RELEASE,
                reason_code="cooldown_elapsed",
                actor="agent",
            )
            assert await store.source_allowed(execution_id, "provider-a")

            with pytest.raises(DBAPIError):
                async with factory() as write_conn:
                    await write_conn.execute(
                        text(
                            "UPDATE run_control_event SET reason_code = 'tampered' WHERE seq = :seq"
                        ),
                        {"seq": first.seq},
                    )

    run_async(scenario())


def test_control_policy_uses_the_execution_icp_and_replay_checks_workspace_first() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-c5-policy", name="C5.5 control policy")
            project_run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                project_id=project.project_id,
                workspace_id=project.workspace_id,
                icp_key="icp-special",
                icp_version=1,
            )
            execution_id = new_execution_id()
            await conn.execute(
                text(
                    """
                    INSERT INTO execution (
                        id, workspace_id, project_id, project_run_id, started_by,
                        parameter_manifest_hash, pin_manifest_hash
                    ) VALUES (
                        :id, :workspace_id, :project_id, :project_run_id, 'system', :hash, :hash
                    )
                    """
                ),
                {
                    "id": execution_id,
                    "workspace_id": project.workspace_id,
                    "project_id": project.project_id,
                    "project_run_id": project_run_id,
                    "hash": "0" * 64,
                },
            )
            await conn.execute(
                text("INSERT INTO execution_cursor (execution_id, status) VALUES (:id, 'running')"),
                {"id": execution_id},
            )
            resolved: list[tuple[str, str | None]] = []

            def policy_for(workspace_id: str, icp_key: str | None) -> SupervisorPolicy:
                resolved.append((workspace_id, icp_key))
                return SupervisorPolicy(
                    permitted_automatic_actions=(SupervisorAutomaticAction.SOURCE_BREAKER,),
                )

            store = DbRunControlStore(
                conn_factory=_factory(conn),
                journal=DbExecutionJournal(transport=ExecutionRunEventWriter()),
                policy_for=policy_for,
            )
            operation_id = new_operation_id()
            await store.mutate(
                workspace_id=project.workspace_id,
                execution_id=execution_id,
                operation_id=operation_id,
                control_kind=ControlKind.SOURCE_BREAKER,
                subject_ref="provider-a",
                action=ControlAction.APPLY,
                reason_code="icp_policy_permits",
                actor="agent",
            )
            assert resolved == [(project.workspace_id, "icp-special")]

            with pytest.raises(ControlPolicyViolation, match="outside the workspace"):
                await store.mutate(
                    workspace_id="ws-other",
                    execution_id=execution_id,
                    operation_id=operation_id,
                    control_kind=ControlKind.SOURCE_BREAKER,
                    subject_ref="provider-a",
                    action=ControlAction.APPLY,
                    reason_code="cross_workspace_replay",
                    actor="agent",
                )
            assert resolved == [(project.workspace_id, "icp-special")]

    run_async(scenario())


def test_envelope_can_only_tighten_automatically_and_human_release_restores_original() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            execution_id, _executor, _tool, _generation = await _runtime(
                conn,
                max_nodes=4,
                max_depth=2,
                max_fanout=2,
            )
            store = DbRunControlStore(
                conn_factory=_factory(conn),
                journal=DbExecutionJournal(transport=ExecutionRunEventWriter()),
                policy=SupervisorPolicy(max_envelope_reduction_fraction=0.5),
            )
            original = await store.effective_envelope(execution_id)
            assert original.model_dump() == {
                "max_nodes": 4,
                "max_depth": 2,
                "max_fanout": 2,
            }
            await store.mutate(
                workspace_id="ws-c5-executor",
                execution_id=execution_id,
                operation_id=new_operation_id(),
                control_kind=ControlKind.ENVELOPE,
                subject_ref="runtime",
                action=ControlAction.APPLY,
                reason_code="reduce_fanout",
                actor="agent",
                requested_after={"limits": {"max_nodes": 2, "max_depth": 1, "max_fanout": 1}},
            )
            tightened = await store.effective_envelope(execution_id)
            assert tightened.max_fanout == 1

            with pytest.raises(ControlPolicyViolation, match="only tighten"):
                await store.mutate(
                    workspace_id="ws-c5-executor",
                    execution_id=execution_id,
                    operation_id=new_operation_id(),
                    control_kind=ControlKind.ENVELOPE,
                    subject_ref="runtime",
                    action=ControlAction.APPLY,
                    reason_code="attempt_expand",
                    actor="agent",
                    requested_after={"limits": {"max_nodes": 4, "max_depth": 2, "max_fanout": 2}},
                )

            with pytest.raises(ControlPolicyViolation, match="only a human"):
                await store.mutate(
                    workspace_id="ws-c5-executor",
                    execution_id=execution_id,
                    operation_id=new_operation_id(),
                    control_kind=ControlKind.ENVELOPE,
                    subject_ref="runtime",
                    action=ControlAction.RELEASE,
                    reason_code="agent_expand",
                    actor="agent",
                )
            await store.mutate(
                workspace_id="ws-c5-executor",
                execution_id=execution_id,
                operation_id=new_operation_id(),
                control_kind=ControlKind.ENVELOPE,
                subject_ref="runtime",
                action=ControlAction.RELEASE,
                reason_code="human_reviewed",
                actor="human",
            )
            assert await store.effective_envelope(execution_id) == original

    run_async(scenario())
