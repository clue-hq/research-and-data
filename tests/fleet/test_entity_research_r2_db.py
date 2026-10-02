"""Postgres acceptance for the M8D R2 subject-neutral entity-research fleet."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.fleet.conftest import rollback_conn, run_async
from tests.fleet.entity_research_r2_helpers import finalization_receipt, run_envelope

from clue_core import ProjectRunId
from clue_core.entity_research import (
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchRunKind,
)
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    EntityResearchInvalidTransition,
    EntityResearchLeaseLost,
    EntityResearchRunConflict,
    EntityResearchRunEnvelope,
    EntityResearchRunState,
    EntityResearchWaitState,
    FleetTaskKind,
    FleetTaskStatus,
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    begin_entity_research_job,
    cancel_entity_research_run,
    cancel_work_tasks,
    checkpoint_entity_research_job,
    claim_next_task,
    finalize_entity_research_job,
    get_task,
    get_work_lease,
    launch_entity_research_run,
    list_tasks,
    release_work_lease,
    requeue_task,
    wait_entity_research_job,
    wake_entity_research_job,
)

pytestmark = pytest.mark.usefixtures("require_fleet_db")

_TTL = timedelta(seconds=60)


async def _claim_and_lease(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    worker_id: str,
) -> tuple[EntityResearchExecutionFence, UUID]:
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
    return (
        EntityResearchExecutionFence(
            task_id=task.task_id,
            worker_id=worker_id,
            lease_generation=lease.generation,
            task_attempt=1,
        ),
        task.task_id,
    )


async def _release(
    conn: AsyncConnection,
    job_id: UUID,
    fence: EntityResearchExecutionFence,
) -> None:
    await release_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=fence.worker_id,
        generation=LeaseGeneration(fence.lease_generation),
    )


def test_account_and_contact_launch_separately_into_one_shared_queue() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            account = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
            contact = run_envelope(ResearchRunKind.CONTACT_RESEARCH)
            account_row = await launch_entity_research_run(conn, account)
            contact_row = await launch_entity_research_run(conn, contact)

            assert account_row.run_kind is ResearchRunKind.ACCOUNT_RESEARCH
            assert contact_row.run_kind is ResearchRunKind.CONTACT_RESEARCH
            assert account_row.research_run_id != contact_row.research_run_id
            assert account_row.budget_cap_cents == Decimal("10.00")
            assert contact_row.budget_cap_cents == Decimal("10.00")
            assert account_row.concurrency_limit == 1
            assert contact_row.concurrency_limit == 2

            all_job_ids = [job.authorization.job_id for job in account.jobs + contact.jobs]
            for job_id in all_job_ids:
                tasks = await list_tasks(
                    conn,
                    project_run_id=ProjectRunId(job_id),
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                )
                assert len(tasks) == 1
                assert tasks[0].project_run_id == job_id
                assert tasks[0].payload["job_id"] == str(job_id)

            # Exact launch replay creates neither another job nor another queue/event row.
            await launch_entity_research_run(conn, account)
            await launch_entity_research_run(conn, contact)
            counts = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT
                          (SELECT count(*) FROM entity_research_run
                           WHERE research_run_id IN (:account_run, :contact_run)) AS runs,
                          (SELECT count(*) FROM entity_research_job
                           WHERE research_run_id IN (:account_run, :contact_run)) AS jobs,
                          (SELECT count(*) FROM entity_research_job_event
                           WHERE research_run_id IN (:account_run, :contact_run)) AS events,
                          (SELECT count(*) FROM fleet_task
                           WHERE kind = 'entity_research_job'
                             AND work_id = ANY(CAST(:job_ids AS uuid[]))) AS tasks
                        """
                        ),
                        {
                            "account_run": account.lifecycle.run_id,
                            "contact_run": contact.lifecycle.run_id,
                            "job_ids": all_job_ids,
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert counts == {
                "runs": 2,
                "jobs": len(all_job_ids),
                "events": len(all_job_ids),
                "tasks": len(all_job_ids),
            }

            widened_payload = account.model_dump(mode="python")
            widened_payload["budget_cap_cents"] = Decimal("11.00")
            widened = EntityResearchRunEnvelope.model_validate(widened_payload)
            with pytest.raises(EntityResearchRunConflict, match="different immutable authority"):
                await launch_entity_research_run(conn, widened)

    run_async(scenario())


def test_wait_releases_task_and_exact_wake_resumes_same_checkpoint_then_finalizes() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
            job_id = envelope.jobs[0].authorization.job_id
            await launch_entity_research_run(conn, envelope)
            fence, task_id = await _claim_and_lease(conn, job_id, worker_id="worker-a")

            begin = await begin_entity_research_job(conn, job_id, fence=fence)
            assert begin.admitted and begin.job.state is ResearchJobState.RUNNING
            initial_state_sha256 = begin.job.current_state_sha256
            waiting = await wait_entity_research_job(
                conn,
                job_id,
                fence=fence,
                wait_ref="provider-operation:exa:1",
                checkpoint_ref="checkpoint:account:1",
                checkpoint_sha256="a" * 64,
                current_state_sha256="b" * 64,
            )
            assert waiting.state is ResearchJobState.WAITING_EXTERNAL
            assert waiting.active_worker_id is None
            task = await get_task(conn, task_id)
            assert task is not None and task.status is FleetTaskStatus.DONE
            await _release(conn, job_id, fence)

            woken = await wake_entity_research_job(
                conn,
                job_id,
                wait_ref="provider-operation:exa:1",
                actor="provider-callback:exa",
            )
            assert woken.state is ResearchJobState.QUEUED
            assert woken.checkpoint_ref == "checkpoint:account:1"
            # Duplicate delivery is an exact no-op, not a second offer.
            duplicate = await wake_entity_research_job(
                conn,
                job_id,
                wait_ref="provider-operation:exa:1",
                actor="provider-callback:exa",
            )
            assert duplicate.state is ResearchJobState.QUEUED

            second_fence, second_task_id = await _claim_and_lease(
                conn, job_id, worker_id="worker-b"
            )
            assert second_task_id == task_id
            resumed = await begin_entity_research_job(conn, job_id, fence=second_fence)
            assert resumed.admitted
            assert resumed.job.checkpoint_ref == "checkpoint:account:1"
            stale_receipt = finalization_receipt(
                job_id=job_id,
                subject_type=resumed.job.subject_type,
                target_entity_id=resumed.job.subject_entity_id,
                current_state_sha256=initial_state_sha256,
            )
            with pytest.raises(EntityResearchInvalidTransition, match="stale job state"):
                await finalize_entity_research_job(
                    conn,
                    job_id,
                    fence=second_fence,
                    receipt=stale_receipt,
                )
            receipt = finalization_receipt(
                job_id=job_id,
                subject_type=resumed.job.subject_type,
                target_entity_id=resumed.job.subject_entity_id,
                current_state_sha256=resumed.job.current_state_sha256,
            )
            terminal = await finalize_entity_research_job(
                conn,
                job_id,
                fence=second_fence,
                receipt=receipt,
            )
            assert terminal.state is ResearchJobState.TERMINAL
            assert terminal.finalization_outcome is ResearchFinalizationOutcome.COMPLETED
            await _release(conn, job_id, second_fence)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            store = DbEntityResearchJobStore(conn_factory=same_connection)
            events = await store.list_events(job_id)
            assert [event.event_kind.value for event in events] == [
                "queued",
                "leased",
                "started",
                "waiting_external",
                "woken",
                "leased",
                "started",
                "finalized",
            ]
            run = await store.get_run(envelope.lifecycle.run_id)
            assert run is not None and run.state is EntityResearchRunState.TERMINAL

            for statement in (
                "UPDATE entity_research_job_finalization SET engine_actor='mutated' "
                "WHERE job_id=:job_id",
                "DELETE FROM entity_research_job_event WHERE job_id=:job_id",
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with conn.begin_nested():
                        await conn.execute(text(statement), {"job_id": job_id})

            with pytest.raises(DBAPIError, match="authority is immutable"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE entity_research_job SET initial_state_sha256=:sha "
                            "WHERE job_id=:job_id"
                        ),
                        {"job_id": job_id, "sha": "f" * 64},
                    )

    run_async(scenario())


def test_contact_run_cancellation_is_all_or_none_and_cannot_resurrect_waits() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = run_envelope(ResearchRunKind.CONTACT_RESEARCH)
            await launch_entity_research_run(conn, envelope)
            queued_id = envelope.jobs[0].authorization.job_id
            waiting_id = envelope.jobs[1].authorization.job_id
            running_fence, _ = await _claim_and_lease(
                conn, queued_id, worker_id="worker-running-contact"
            )
            assert (await begin_entity_research_job(conn, queued_id, fence=running_fence)).admitted
            fence, _ = await _claim_and_lease(conn, waiting_id, worker_id="worker-contact")
            assert (await begin_entity_research_job(conn, waiting_id, fence=fence)).admitted
            waiting = await wait_entity_research_job(
                conn,
                waiting_id,
                fence=fence,
                wait_ref="provider-operation:sumble:people:1",
                checkpoint_ref="checkpoint:contact:1",
                checkpoint_sha256="c" * 64,
                current_state_sha256="d" * 64,
            )
            await _release(conn, waiting_id, fence)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            store = DbEntityResearchJobStore(conn_factory=same_connection)
            queued = await store.get_job(queued_id)
            assert queued is not None
            queued_receipt = finalization_receipt(
                job_id=queued_id,
                subject_type=queued.subject_type,
                target_entity_id=queued.subject_entity_id,
                current_state_sha256=queued.current_state_sha256,
                outcome=ResearchFinalizationOutcome.CANCELLED,
            )
            waiting_receipt = finalization_receipt(
                job_id=waiting_id,
                subject_type=waiting.subject_type,
                target_entity_id=waiting.subject_entity_id,
                current_state_sha256=waiting.current_state_sha256,
                outcome=ResearchFinalizationOutcome.CANCELLED,
            )

            with pytest.raises(EntityResearchInvalidTransition, match="exactly one"):
                await cancel_entity_research_run(
                    conn,
                    envelope.lifecycle.run_id,
                    receipts=((queued_id, queued_receipt),),
                    actor="user:owner",
                )
            still_running = await store.get_job(queued_id)
            still_waiting = await store.get_job(waiting_id)
            assert still_running is not None and still_running.state is ResearchJobState.RUNNING
            assert (
                still_waiting is not None
                and still_waiting.state is ResearchJobState.WAITING_EXTERNAL
            )

            cancelled_run = await cancel_entity_research_run(
                conn,
                envelope.lifecycle.run_id,
                receipts=(
                    (queued_id, queued_receipt),
                    (waiting_id, waiting_receipt),
                ),
                actor="user:owner",
            )
            assert cancelled_run.state is EntityResearchRunState.TERMINAL
            assert await get_work_lease(conn, WorkId(queued_id)) is None
            for job_id in (queued_id, waiting_id):
                job = await store.get_job(job_id)
                assert job is not None
                assert job.state is ResearchJobState.TERMINAL
                assert job.finalization_outcome is ResearchFinalizationOutcome.CANCELLED
                tasks = await list_tasks(
                    conn,
                    project_run_id=ProjectRunId(job_id),
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                )
                assert tasks[0].status is FleetTaskStatus.DONE
                assert tasks[0].result_ref["outcome"] == "cancelled"

            wait_state = (
                await conn.execute(
                    text(
                        "SELECT state FROM entity_research_job_wait "
                        "WHERE job_id = :job_id AND wait_ref = :wait_ref"
                    ),
                    {"job_id": waiting_id, "wait_ref": "provider-operation:sumble:people:1"},
                )
            ).scalar_one()
            assert wait_state == EntityResearchWaitState.CANCELLED.value
            with pytest.raises(EntityResearchInvalidTransition, match="cannot be resurrected"):
                await wake_entity_research_job(
                    conn,
                    waiting_id,
                    wait_ref="provider-operation:sumble:people:1",
                    actor="late-provider-callback",
                )

    run_async(scenario())


def test_per_run_concurrency_is_independent_and_requeue_does_not_lose_scope() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = run_envelope(
                ResearchRunKind.CONTACT_RESEARCH,
                concurrency_limit=1,
            )
            await launch_entity_research_run(conn, envelope)
            first_id = envelope.jobs[0].authorization.job_id
            second_id = envelope.jobs[1].authorization.job_id
            first_fence, _ = await _claim_and_lease(conn, first_id, worker_id="worker-first")
            second_fence, second_task_id = await _claim_and_lease(
                conn, second_id, worker_id="worker-second"
            )
            assert (await begin_entity_research_job(conn, first_id, fence=first_fence)).admitted
            denied = await begin_entity_research_job(conn, second_id, fence=second_fence)
            assert not denied.admitted and denied.reason == "concurrency_limit"
            assert denied.job.state is ResearchJobState.QUEUED
            assert await requeue_task(
                conn,
                task_id=second_task_id,
                worker_id=second_fence.worker_id,
            )
            await _release(conn, second_id, second_fence)

            first_job = (await begin_entity_research_job(conn, first_id, fence=first_fence)).job
            first_receipt = finalization_receipt(
                job_id=first_id,
                subject_type=first_job.subject_type,
                target_entity_id=first_job.subject_entity_id,
                current_state_sha256=first_job.current_state_sha256,
            )
            await finalize_entity_research_job(
                conn, first_id, fence=first_fence, receipt=first_receipt
            )
            await _release(conn, first_id, first_fence)

            admitted_fence, _ = await _claim_and_lease(conn, second_id, worker_id="worker-third")
            admitted = await begin_entity_research_job(conn, second_id, fence=admitted_fence)
            assert admitted.admitted
            assert (
                admitted.job.subject_entity_id == envelope.jobs[1].authorization.subject_entity_id
            )

    run_async(scenario())


def test_domain_writes_require_the_exact_live_generic_task_and_lease_fence() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            envelope = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
            job_id = envelope.jobs[0].authorization.job_id
            await launch_entity_research_run(conn, envelope)
            fence, _ = await _claim_and_lease(conn, job_id, worker_id="worker-fenced")
            wrong = fence.model_copy(update={"task_id": uuid4()})
            with pytest.raises(EntityResearchLeaseLost, match="task and live lease"):
                await begin_entity_research_job(conn, job_id, fence=wrong)

            begun = await begin_entity_research_job(conn, job_id, fence=fence)
            assert begun.admitted
            await cancel_work_tasks(
                conn,
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                work_id=WorkId(job_id),
                result_ref={"outcome": "fence-test"},
            )
            with pytest.raises(EntityResearchLeaseLost, match="task and live lease"):
                await checkpoint_entity_research_job(
                    conn,
                    job_id,
                    fence=fence,
                    checkpoint_ref="checkpoint:stale",
                    checkpoint_sha256="e" * 64,
                    current_state_sha256="f" * 64,
                )

    run_async(scenario())
