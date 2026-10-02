"""Postgres acceptance for the M8D R6 account-research fleet and user return."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import (
    AccountResearchAdmissionState,
    AccountResearchFleetError,
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
    AccountResearchFleetState,
    AccountResearchFleetWorkHandler,
)
from clue_core import ProjectRunId
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchRunKind,
    SelectedResearchSubject,
)
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchDriverDisposition,
    EntityResearchDriverResult,
    EntityResearchExecutionFence,
    EntityResearchInvalidTransition,
    EntityResearchJobDriver,
    EntityResearchJobEnvelope,
    EntityResearchJobWorkHandler,
    EntityResearchRunEnvelope,
    FleetTaskKind,
    FleetTaskStatus,
    LeaseGeneration,
    WorkContext,
    WorkId,
    WorkResult,
    acquire_work_lease,
    begin_entity_research_job,
    claim_next_task,
    finalize_entity_research_job,
    get_task,
    list_tasks,
    release_work_lease,
    wake_entity_research_job,
)
from clue_fleet.entity_research import EntityResearchJobRow
from tests.fleet.conftest import rollback_conn, run_async
from tests.fleet.entity_research_r2_helpers import finalization_receipt, run_envelope

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_TTL = timedelta(seconds=60)


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


def _account_envelope(count: int = 3) -> EntityResearchRunEnvelope:
    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH, concurrency_limit=2)
    first = base.lifecycle.selection.subjects[0]
    subjects = (
        first,
        *(
            SelectedResearchSubject(
                subject_entity_id=uuid4(),
                basis=first.basis,
            )
            for _ in range(count - 1)
        ),
    )
    selection = base.lifecycle.selection.model_copy(update={"subjects": subjects})
    lifecycle = base.lifecycle.model_copy(update={"selection": selection})
    template = base.jobs[0]
    jobs: list[EntityResearchJobEnvelope] = []
    for priority, subject in enumerate(subjects):
        authorization = EntityResearchJobAuthorization(
            **{
                **template.authorization.model_dump(mode="python"),
                "job_id": uuid4(),
                "subject_entity_id": subject.subject_entity_id,
                "selection": selection,
                "checkpoint_thread_id": (
                    f"checkpoint:{lifecycle.run_id}:{subject.subject_entity_id}"
                ),
                "attempt_id": uuid4(),
                "lease_id": uuid4(),
            }
        )
        jobs.append(
            EntityResearchJobEnvelope(
                authorization=authorization,
                priority=priority,
                budget_envelope_ref=f"budget:job:{authorization.job_id}",
                budget_cap_cents=Decimal("3.00"),
            )
        )
    return EntityResearchRunEnvelope(
        lifecycle=lifecycle,
        jobs=tuple(jobs),
        budget_cap_cents=Decimal("10.00"),
        concurrency_limit=2,
    )


async def _claim_begin_finalize(
    conn: AsyncConnection,
    envelope: EntityResearchRunEnvelope,
    job_id: UUID,
    *,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
) -> None:
    worker_id = f"worker:{job_id}"
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        ttl=_TTL,
    )
    assert lease is not None
    fence = EntityResearchExecutionFence(
        task_id=task.task_id,
        worker_id=worker_id,
        lease_generation=lease.generation,
        task_attempt=1,
    )
    begin = await begin_entity_research_job(conn, job_id, fence=fence)
    assert begin.admitted
    job = next(item for item in envelope.jobs if item.authorization.job_id == job_id)
    receipt = finalization_receipt(
        job_id=job_id,
        subject_type=job.authorization.subject_type,
        target_entity_id=job.authorization.subject_entity_id,
        current_state_sha256=begin.job.current_state_sha256,
        outcome=outcome,
    )
    terminal = await finalize_entity_research_job(conn, job_id, fence=fence, receipt=receipt)
    assert terminal.state is ResearchJobState.TERMINAL
    await release_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        generation=LeaseGeneration(lease.generation),
    )


def test_exact_set_launch_admits_only_canary_and_replay_is_immutable() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope()
            service = AccountResearchFleetService(conn_factory=lambda: _same_connection(conn))
            policy = AccountResearchFleetPolicy(canary_size=1)
            projection = await service.launch(
                envelope,
                policy=policy,
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:1",
            )
            assert projection.fleet_state is AccountResearchFleetState.CANARY
            assert projection.selected_accounts == 3
            assert projection.queued_accounts == 3
            assert projection.contact_research_started is False
            assert projection.contact_research_request_count == 0

            canary = [job for job in projection.jobs if job.cohort.value == "canary"]
            held = [job for job in projection.jobs if job.cohort.value == "remainder"]
            assert len(canary) == 1
            assert [job.admission_state.value for job in held] == ["held", "held"]
            canary_tasks = await list_tasks(
                conn,
                project_run_id=ProjectRunId(canary[0].job_id),
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
            )
            assert len(canary_tasks) == 1
            assert canary_tasks[0].status is FleetTaskStatus.QUEUED
            for job in held:
                tasks = await list_tasks(
                    conn,
                    project_run_id=ProjectRunId(job.job_id),
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                )
                assert len(tasks) == 1
                assert tasks[0].status is FleetTaskStatus.DONE
                assert tasks[0].result_ref["outcome"] == "canary_held"

            replay = await service.launch(
                envelope,
                policy=policy,
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:1",
            )
            assert replay == projection
            assert (
                await service.read(
                    envelope.lifecycle.run_id,
                    workspace_id="foreign-workspace",
                )
                is None
            )
            with pytest.raises(AccountResearchFleetError, match="changed canary, policy"):
                await service.launch(
                    envelope,
                    policy=policy.model_copy(update={"canary_size": 2}),
                    actor="user:owner",
                    source_operation_id=envelope.lifecycle.run_id,
                    source_action_ref="agent-action:launch-account-research:1",
                )

    run_async(scenario())


def test_canary_releases_remainder_and_terminal_return_exposes_results_and_review() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope()
            service = AccountResearchFleetService(conn_factory=lambda: _same_connection(conn))
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:2",
            )
            canary_id = next(job.job_id for job in launched.jobs if job.cohort.value == "canary")
            await _claim_begin_finalize(conn, envelope, canary_id)

            opened = await service.reconcile(envelope.lifecycle.run_id)
            assert opened.fleet_state is AccountResearchFleetState.OPEN
            remainder = [job for job in opened.jobs if job.cohort.value == "remainder"]
            assert all(
                job.admission_state is AccountResearchAdmissionState.RELEASED for job in remainder
            )
            for job in remainder:
                task_rows = await list_tasks(
                    conn,
                    project_run_id=ProjectRunId(job.job_id),
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                )
                assert len(task_rows) == 1
                assert task_rows[0].status is FleetTaskStatus.QUEUED

            for job in remainder:
                await _claim_begin_finalize(conn, envelope, job.job_id)

            review_job = remainder[0]
            coverage_id = uuid4()
            review_id = uuid4()
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_coverage
                        (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                         result_refs, completed_field_keys, unresolved_field_keys,
                         unresolved_reasons, committee_result_refs, committee_member_ids,
                         committee_status, review_flags, claim_refs, evidence_refs,
                         coverage_json, coverage_sha256)
                    VALUES
                        (:coverage_id, :run_id, :job_id, :workspace_id, :account_id,
                         :result_refs, ARRAY['account.operational_pain'],
                         ARRAY['account.resonance.culture'],
                         ARRAY[]::text[], :committee_refs, :committee_ids, 'needs_review',
                         ARRAY['committee_partial'], :claim_refs, :evidence_refs,
                         '{}'::jsonb, :coverage_sha)
                    """
                ),
                {
                    "coverage_id": coverage_id,
                    "run_id": envelope.lifecycle.run_id,
                    "job_id": review_job.job_id,
                    "workspace_id": envelope.lifecycle.selection.workspace_id,
                    "account_id": review_job.account_entity_id,
                    "result_refs": [f"research-result:{uuid4()}"],
                    "committee_refs": [f"committee-result:{uuid4()}"],
                    "committee_ids": [uuid4(), uuid4()],
                    "claim_refs": [f"claim:{uuid4()}"],
                    "evidence_refs": [f"evidence:{uuid4()}"],
                    "coverage_sha": "d" * 64,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_review_item
                        (review_item_id, coverage_id, research_run_id, job_id, workspace_id,
                         account_entity_id, reason_code, details_json)
                    VALUES
                        (:review_id, :coverage_id, :run_id, :job_id, :workspace_id,
                         :account_id, 'committee_partial', '{}'::jsonb)
                    """
                ),
                {
                    "review_id": review_id,
                    "coverage_id": coverage_id,
                    "run_id": envelope.lifecycle.run_id,
                    "job_id": review_job.job_id,
                    "workspace_id": envelope.lifecycle.selection.workspace_id,
                    "account_id": review_job.account_entity_id,
                },
            )

            terminal = await service.reconcile(envelope.lifecycle.run_id)
            assert terminal.fleet_state is AccountResearchFleetState.TERMINAL
            assert terminal.terminal_accounts == 3
            assert terminal.completed_accounts == 3
            assert terminal.review_queue == (f"account-review:{review_id}",)
            projected = next(job for job in terminal.jobs if job.job_id == review_job.job_id)
            assert projected.result_refs
            assert projected.unresolved_field_keys == ("account.resonance.culture",)
            assert projected.committee_status == "needs_review"
            assert len(projected.committee_member_ids) == 2
            assert projected.review_item_refs == (f"account-review:{review_id}",)
            assert terminal.contact_research_started is False
            assert terminal.contact_research_request_count == 0

            returned = await service.latest_return(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert returned is not None
            assert returned.return_kind == "terminal"
            assert returned.projection == terminal
            assert (
                await service.latest_return(
                    envelope.lifecycle.run_id,
                    workspace_id="foreign-workspace",
                )
                is None
            )

    run_async(scenario())


def test_failed_canary_suspends_remainder_without_admitting_it() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope()
            service = AccountResearchFleetService(conn_factory=lambda: _same_connection(conn))
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:3",
            )
            canary_id = next(job.job_id for job in launched.jobs if job.cohort.value == "canary")
            await _claim_begin_finalize(
                conn,
                envelope,
                canary_id,
                outcome=ResearchFinalizationOutcome.FAILED,
            )
            suspended = await service.reconcile(envelope.lifecycle.run_id)
            assert suspended.fleet_state is AccountResearchFleetState.SUSPENDED
            assert suspended.diagnosis["reason_code"] == "canary_health_gate_failed"
            held = [job for job in suspended.jobs if job.cohort.value == "remainder"]
            assert all(job.admission_state is AccountResearchAdmissionState.PAUSED for job in held)
            for job in held:
                tasks = await list_tasks(
                    conn,
                    project_run_id=ProjectRunId(job.job_id),
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                )
                assert tasks[0].status is FleetTaskStatus.DONE
            returned = await service.latest_return(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert returned is not None and returned.return_kind == "suspended"

    run_async(scenario())


def test_pause_resume_and_reprioritize_are_scoped_and_journaled() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope()
            service = AccountResearchFleetService(conn_factory=lambda: _same_connection(conn))
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:4",
            )
            canary = next(job for job in launched.jobs if job.cohort.value == "canary")
            with pytest.raises(AccountResearchFleetError, match="cross-workspace"):
                await service.pause_job(
                    canary.job_id,
                    workspace_id="foreign-workspace",
                    actor="user:foreign",
                    reason_code="wrong_scope",
                )
            paused = await service.pause_job(
                canary.job_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
                actor="user:owner",
                reason_code="user_requested_pause",
            )
            assert paused.fleet_state is AccountResearchFleetState.SUSPENDED
            resumed = await service.resume_job(
                canary.job_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
                actor="user:owner",
            )
            assert resumed.fleet_state is AccountResearchFleetState.CANARY
            reprioritized = await service.reprioritize_job(
                canary.job_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
                actor="user:owner",
                priority=-50,
            )
            updated = next(job for job in reprioritized.jobs if job.job_id == canary.job_id)
            assert updated.effective_priority == -50
            task = (
                await list_tasks(
                    conn,
                    project_run_id=ProjectRunId(canary.job_id),
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                )
            )[0]
            assert task.status is FleetTaskStatus.QUEUED
            assert task.priority == -50
            actions = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT action FROM entity_research_account_fleet_control_event "
                            "WHERE research_run_id=:run_id ORDER BY event_seq"
                        ),
                        {"run_id": envelope.lifecycle.run_id},
                    )
                ).scalars()
            )
            assert actions == (
                "launch",
                "pause_job",
                "reconcile",
                "resume_job",
                "reconcile",
                "reprioritize_job",
            )

    run_async(scenario())


class _FailingInner(EntityResearchJobWorkHandler):
    def __init__(self) -> None:
        pass

    async def handle(self, context: WorkContext) -> WorkResult:
        del context
        raise RuntimeError("model transport failed after bounded retries")


class _FinalizingDriver(EntityResearchJobDriver):
    async def run(
        self,
        job: EntityResearchJobRow,
        *,
        fence: EntityResearchExecutionFence,
        stop_requested: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> EntityResearchDriverResult:
        del fence, stop_requested, lease_lost
        return EntityResearchDriverResult(
            disposition=EntityResearchDriverDisposition.FINALIZED,
            finalization_receipt=finalization_receipt(
                job_id=job.job_id,
                subject_type=job.subject_type,
                target_entity_id=job.subject_entity_id,
                current_state_sha256=job.current_state_sha256,
            ),
        )


class _WaitingDriver(EntityResearchJobDriver):
    async def run(
        self,
        job: EntityResearchJobRow,
        *,
        fence: EntityResearchExecutionFence,
        stop_requested: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> EntityResearchDriverResult:
        del fence, stop_requested, lease_lost
        return EntityResearchDriverResult(
            disposition=EntityResearchDriverDisposition.WAITING_EXTERNAL,
            wait_ref=f"provider-operation:{job.job_id}",
            checkpoint_ref=f"checkpoint:{job.job_id}:provider-wait",
            checkpoint_sha256="a" * 64,
            current_state_sha256="b" * 64,
        )


async def _handle_claimed_job(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    handler: AccountResearchFleetWorkHandler,
    worker_id: str,
) -> WorkResult:
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        ttl=_TTL,
    )
    assert lease is not None
    try:
        return await handler.handle(
            WorkContext(
                task_id=task.task_id,
                work_id=WorkId(job_id),
                worker_id=worker_id,
                lease_generation=LeaseGeneration(lease.generation),
                payload={"job_id": str(job_id)},
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )
        )
    finally:
        await release_work_lease(
            conn,
            work_id=WorkId(job_id),
            worker_id=worker_id,
            generation=LeaseGeneration(lease.generation),
        )


def test_composed_r2_handler_drains_canary_then_remainder_and_returns_terminal() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope(count=2)

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            service = AccountResearchFleetService(conn_factory=connection)
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:handler",
            )
            handler = AccountResearchFleetWorkHandler(
                inner=EntityResearchJobWorkHandler(
                    store=DbEntityResearchJobStore(conn_factory=connection),
                    driver=_FinalizingDriver(),
                ),
                fleets=service,
            )
            canary = next(job for job in launched.jobs if job.cohort.value == "canary")
            result = await _handle_claimed_job(
                conn,
                job_id=canary.job_id,
                handler=handler,
                worker_id="worker:canary",
            )
            assert result.outcome == "completed"
            assert result.references["account_fleet_state"] == "open"
            opened = await service.read(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert opened is not None
            remainder = next(job for job in opened.jobs if job.cohort.value == "remainder")
            assert remainder.admission_state is AccountResearchAdmissionState.RELEASED

            result = await _handle_claimed_job(
                conn,
                job_id=remainder.job_id,
                handler=handler,
                worker_id="worker:remainder",
            )
            assert result.outcome == "completed"
            assert result.references["account_fleet_state"] == "terminal"
            returned = await service.latest_return(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert returned is not None
            assert returned.projection.terminal_accounts == 2
            assert returned.projection.contact_research_started is False

    run_async(scenario())


def test_composed_wait_releases_job_into_honest_fleet_suspension() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope(count=1)

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            service = AccountResearchFleetService(conn_factory=connection)
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:wait",
            )
            handler = AccountResearchFleetWorkHandler(
                inner=EntityResearchJobWorkHandler(
                    store=DbEntityResearchJobStore(conn_factory=connection),
                    driver=_WaitingDriver(),
                ),
                fleets=service,
            )
            result = await _handle_claimed_job(
                conn,
                job_id=launched.jobs[0].job_id,
                handler=handler,
                worker_id="worker:wait",
            )
            assert result.outcome == "waiting_external"
            assert result.references["account_fleet_state"] == "waiting_external"
            projection = await service.read(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert projection is not None
            assert projection.fleet_state is AccountResearchFleetState.WAITING_EXTERNAL
            assert projection.waiting_accounts == 1
            assert projection.active_accounts == 0
            assert projection.jobs[0].current_wait_ref == (
                f"provider-operation:{launched.jobs[0].job_id}"
            )

    run_async(scenario())


def test_user_cancellation_terminalizes_waiting_and_held_jobs_without_resurrection() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope(count=2)

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            service = AccountResearchFleetService(conn_factory=connection)
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:cancel",
            )
            handler = AccountResearchFleetWorkHandler(
                inner=EntityResearchJobWorkHandler(
                    store=DbEntityResearchJobStore(conn_factory=connection),
                    driver=_WaitingDriver(),
                ),
                fleets=service,
            )
            canary = next(job for job in launched.jobs if job.cohort.value == "canary")
            await _handle_claimed_job(
                conn,
                job_id=canary.job_id,
                handler=handler,
                worker_id="worker:cancel-wait",
            )
            wait_ref = f"provider-operation:{canary.job_id}"
            terminal = await service.cancel(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
                actor="user:owner",
                reason_code="user_cancelled_account_fleet",
            )
            assert terminal.fleet_state is AccountResearchFleetState.TERMINAL
            assert terminal.terminal_accounts == 2
            assert all(
                job.finalization_outcome is ResearchFinalizationOutcome.CANCELLED
                for job in terminal.jobs
            )
            assert all(
                job.admission_state is AccountResearchAdmissionState.TERMINAL
                for job in terminal.jobs
            )
            with pytest.raises(
                EntityResearchInvalidTransition,
                match="cannot be resurrected",
            ):
                await wake_entity_research_job(
                    conn,
                    canary.job_id,
                    wait_ref=wait_ref,
                    actor="provider:late-callback",
                )
            returned = await service.latest_return(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert returned is not None and returned.return_kind == "terminal"
            actions = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT action FROM entity_research_account_fleet_control_event "
                            "WHERE research_run_id=:run_id ORDER BY event_seq"
                        ),
                        {"run_id": envelope.lifecycle.run_id},
                    )
                ).scalars()
            )
            assert "cancel_fleet" in actions

    run_async(scenario())


def test_worker_failure_becomes_honest_resumable_suspension() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = _account_envelope(count=1)
            service = AccountResearchFleetService(conn_factory=lambda: _same_connection(conn))
            launched = await service.launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:owner",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref="agent-action:launch-account-research:5",
            )
            job_id = launched.jobs[0].job_id
            worker_id = "worker:failure"
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                worker_id=worker_id,
                project_run_id=ProjectRunId(job_id),
            )
            assert task is not None
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(job_id),
                worker_id=worker_id,
                ttl=_TTL,
            )
            assert lease is not None
            fence = EntityResearchExecutionFence(
                task_id=task.task_id,
                worker_id=worker_id,
                lease_generation=lease.generation,
                task_attempt=1,
            )
            begin = await begin_entity_research_job(conn, job_id, fence=fence)
            assert begin.admitted
            handler = AccountResearchFleetWorkHandler(inner=_FailingInner(), fleets=service)
            result = await handler.handle(
                WorkContext(
                    task_id=task.task_id,
                    work_id=WorkId(job_id),
                    worker_id=worker_id,
                    lease_generation=LeaseGeneration(lease.generation),
                    payload={"job_id": str(job_id)},
                    stop_requested=asyncio.Event(),
                    lease_lost=asyncio.Event(),
                )
            )
            assert result.outcome == "supervisor_suspended"
            assert result.task_finalized
            projection = await service.read(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert projection is not None
            assert projection.fleet_state is AccountResearchFleetState.SUSPENDED
            assert projection.jobs[0].job_state is ResearchJobState.QUEUED
            assert projection.jobs[0].admission_state is AccountResearchAdmissionState.PAUSED
            job_event = (
                (
                    await conn.execute(
                        text(
                            "SELECT event_kind, from_state, to_state, actor, references_json "
                            "FROM entity_research_job_event WHERE job_id=:job_id "
                            "ORDER BY event_seq DESC LIMIT 1"
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert job_event["event_kind"] == "queued"
            assert job_event["from_state"] == "running"
            assert job_event["to_state"] == "queued"
            assert job_event["actor"] == "engine:account-fleet-supervisor"
            assert job_event["references_json"]["reason_code"] == "worker_error:RuntimeError"
            assert job_event["references_json"]["task_id"] == str(task.task_id)
            assert job_event["references_json"]["lease_generation"] == lease.generation
            task_after = await get_task(conn, task.task_id)
            assert task_after is not None
            assert task_after.status is FleetTaskStatus.DONE
            returned = await service.latest_return(
                envelope.lifecycle.run_id,
                workspace_id=envelope.lifecycle.selection.workspace_id,
            )
            assert returned is not None and returned.return_kind == "suspended"

    run_async(scenario())
