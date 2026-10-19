"""DB-gated tests for the PB-B1 fleet tables — ``run_lease`` + ``fleet_task``.

Need a reachable, migrated Postgres and ``pytest.skip`` without one. Cover: the two enum
parities, the lease's atomic acquire/expiry-takeover/holder-guarded renew+release, and the
queue's idempotent enqueue, priority claim order, holder guards, stale reclaim, and the explicit
FAILED requeue gate. Repo calls run inside a rolled-back transaction, so no committed rows leak.

Postgres ``now()`` is frozen inside one transaction, so expiry/staleness are exercised with
**zero** TTLs/windows (``expires_at <= now()`` / ``claimed_at <= now() - 0`` hold immediately)
rather than sleeps — deterministic, no timing flakes."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.fleet.conftest import rollback_conn, run_async

from clue_core import new_project_run_id
from clue_db import db_lifespan
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    LeaseGeneration,
    WorkId,
    acquire_run_lease,
    claim_next_task,
    enqueue_task,
    finish_task,
    get_run_lease,
    get_task,
    list_tasks,
    release_run_lease,
    renew_run_lease,
    renew_work_lease,
    requeue_failed_tasks,
    requeue_task,
)

pytestmark = pytest.mark.usefixtures("require_fleet_db")

_TTL = timedelta(seconds=60)
_EXPIRED = timedelta(0)
_FRESH = timedelta(seconds=60)
_STALE_NOW = timedelta(0)


def test_concurrent_claimers_each_receive_one_distinct_task() -> None:
    async def case():
        async with db_lifespan() as engine:
            run = new_project_run_id()
            async with engine.begin() as conn:
                for i in range(90):
                    await enqueue_task(
                        conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run, dedup_key=str(i)
                    )

            async def claim(index):
                async with engine.begin() as conn:
                    return await claim_next_task(
                        conn,
                        kind=FleetTaskKind.DRIVE_RUN,
                        project_run_id=run,
                        worker_id=f"claimant-{index}",
                        stale_after=_FRESH,
                    )

            try:
                rows = []
                for _ in range(3):
                    rows.extend(await asyncio.gather(*(claim(i) for i in range(30))))
                assert all(row is not None for row in rows)
                assert len({row.task_id for row in rows}) == 90
                assert all(row.attempts == 1 for row in rows)
            finally:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("DELETE FROM fleet_task WHERE work_id=:run"), {"run": run}
                    )

    run_async(case())


async def _enum_labels(conn: AsyncConnection, typname: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = :t ORDER BY e.enumsortorder"
        ),
        {"t": typname},
    )
    return [r[0] for r in rows.all()]


def test_fleet_task_kind_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = await _enum_labels(conn, "fleet_task_kind")
        assert labels == [k.value for k in FleetTaskKind]

    run_async(_run())


def test_fleet_task_status_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = await _enum_labels(conn, "fleet_task_status")
        assert labels == [s.value for s in FleetTaskStatus]

    run_async(_run())


# --- run_lease ---------------------------------------------------------------


def test_lease_acquire_blocks_second_worker_while_live() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            assert await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )
            # The exit-gate property, first half: a second worker may NOT drive a leased run.
            assert not await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and lease.worker_id == "worker-a" and lease.live

    run_async(_run())


def test_lease_reacquire_by_holder_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            assert await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )
            assert await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )

    run_async(_run())


def test_lease_takeover_after_expiry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            # ttl=0 → born expired (kill -9: the holder stops renewing and the TTL lapses).
            assert await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-a", ttl=_EXPIRED
            )
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and not lease.live
            # The exit-gate property, second half: takeover happens only after expiry.
            assert await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and lease.worker_id == "worker-b" and lease.live

    run_async(_run())


def test_lease_renew_is_holder_guarded_and_a_lapsed_unclaimed_lease_is_taken_back() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await acquire_run_lease(conn, project_run_id=run_id, worker_id="worker-a", ttl=_TTL)
            assert await renew_run_lease(
                conn, project_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )
            # Not the holder → no renewal.
            assert not await renew_run_lease(
                conn, project_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            # A stale generation → no renewal, even by the named worker.
            held = await get_run_lease(conn, run_id)
            assert held is not None
            assert not await renew_work_lease(
                conn,
                work_id=WorkId(run_id),
                worker_id="worker-a",
                generation=LeaseGeneration(held.generation - 1),
                ttl=_TTL,
            )
            # Lapsed but nobody claimed it → the holder's renew lands, at the same generation.
            other = new_project_run_id()
            await acquire_run_lease(conn, project_run_id=other, worker_id="worker-a", ttl=_EXPIRED)
            lapsed = await get_run_lease(conn, other)
            assert lapsed is not None and not lapsed.live
            assert await renew_run_lease(conn, project_run_id=other, worker_id="worker-a", ttl=_TTL)
            back = await get_run_lease(conn, other)
            assert back is not None and back.live and back.worker_id == "worker-a"
            assert back.generation == lapsed.generation
            # Once another worker has acquired a lapsed lease, the old holder's renew fails (the
            # driver must treat this as lease-lost and abort).
            taken = new_project_run_id()
            await acquire_run_lease(conn, project_run_id=taken, worker_id="worker-a", ttl=_EXPIRED)
            assert await acquire_run_lease(
                conn, project_run_id=taken, worker_id="worker-b", ttl=_TTL
            )
            assert not await renew_run_lease(
                conn, project_run_id=taken, worker_id="worker-a", ttl=_TTL
            )
            stolen = await get_run_lease(conn, taken)
            assert stolen is not None and stolen.worker_id == "worker-b"
            assert stolen.generation == lapsed.generation + 1

    run_async(_run())


def test_lease_release_is_holder_guarded_and_ends_the_lease() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await acquire_run_lease(conn, project_run_id=run_id, worker_id="worker-a", ttl=_TTL)
            # A fenced-out zombie's release is a no-op.
            await release_run_lease(conn, project_run_id=run_id, worker_id="worker-b")
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and lease.worker_id == "worker-a" and lease.live
            # The holder's release ends the lease (the row is kept, so generations never repeat).
            await release_run_lease(conn, project_run_id=run_id, worker_id="worker-a")
            ended = await get_run_lease(conn, run_id)
            assert ended is not None and not ended.live
            assert ended.generation == lease.generation
            # The run is free: the next acquire — by anyone — is the next generation.
            assert await acquire_run_lease(
                conn, project_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            after = await get_run_lease(conn, run_id)
            assert after is not None and after.live and after.worker_id == "worker-b"
            assert after.generation == lease.generation + 1

    run_async(_run())


# --- fleet_task --------------------------------------------------------------


def test_enqueue_is_idempotent_on_dedup_key() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            assert await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                project_run_id=run_id,
                dedup_key=str(run_id),
            )
            assert not await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                project_run_id=run_id,
                dedup_key=str(run_id),
            )
            rows = await list_tasks(conn, project_run_id=run_id, kind=FleetTaskKind.DRIVE_RUN)
            assert len(rows) == 1

    run_async(_run())


def test_enqueue_reopen_terminal_reopens_finished_drive_tasks_only() -> None:
    """The resume path: a paused run's DONE drive task must not block the post-resume re-drive
    (``enqueue_drive`` re-opens it), while the default account-job enqueue never resurrects a
    done row (it is the run's exactly-once completion marker)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_id, dedup_key=str(run_id)
            )
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="w",
                project_run_id=run_id,
                stale_after=_FRESH,
            )
            assert task is not None
            await finish_task(
                conn,
                task_id=task.task_id,
                worker_id="w",
                status=FleetTaskStatus.DONE,
                result_ref={"outcome": "paused"},
            )
            # Plain enqueue: still a no-op against the finished row.
            assert not await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_id, dedup_key=str(run_id)
            )
            # A queued/claimed row is a no-op even with reopen (the work is already offered).
            # A terminal row is re-opened — same task id, clean slate, claimable again.
            assert await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                project_run_id=run_id,
                dedup_key=str(run_id),
                reopen_terminal=True,
            )
            reopened = await get_task(conn, task.task_id)
            assert reopened is not None and reopened.status is FleetTaskStatus.QUEUED
            assert reopened.claimed_by is None and reopened.result_ref == {}
            assert not await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                project_run_id=run_id,
                dedup_key=str(run_id),
                reopen_terminal=True,
            )

    run_async(_run())


def test_claim_order_is_priority_then_fifo() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            for key, priority in (("low-first", 3), ("top", 0), ("high", 1), ("low-second", 3)):
                await enqueue_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    project_run_id=run_id,
                    dedup_key=key,
                    priority=priority,
                )
            claimed = []
            while True:
                task = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    worker_id="w",
                    project_run_id=run_id,
                    stale_after=_FRESH,
                )
                if task is None:
                    break
                claimed.append(task.dedup_key)
            assert claimed == ["top", "high", "low-first", "low-second"]

    run_async(_run())


def test_same_transaction_enqueues_claim_in_insertion_order() -> None:
    """Total-FIFO regression (audit finding #3): same-priority rows enqueued inside ONE
    transaction all share the frozen ``now()`` as ``enqueued_at``, so ``(priority, enqueued_at)``
    alone leaves ties with no final key and claim order is plan/physical-order-sensitive
    (nondeterministic). The monotonic ``enqueue_seq`` identity column is the total order that makes
    claim order exactly the insertion order regardless of timestamp collisions."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            order = [f"seq-{i}" for i in range(6)]
            for key in order:  # all same priority, all one frozen-now() transaction
                await enqueue_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    project_run_id=run_id,
                    dedup_key=key,
                    priority=5,
                )
            claimed = []
            seqs = []
            while True:
                task = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    worker_id="w",
                    project_run_id=run_id,
                    stale_after=_FRESH,
                )
                if task is None:
                    break
                claimed.append(task.dedup_key)
                seqs.append(task.enqueue_seq)
            assert claimed == order, claimed
            # The total order is the monotonic insertion sequence, not the frozen timestamp.
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), seqs

    run_async(_run())


def test_claimed_task_is_not_reclaimable_until_stale() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_id, dedup_key=str(run_id)
            )
            first = await claim_next_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, worker_id="worker-a", stale_after=_FRESH
            )
            assert first is not None and first.attempts == 1
            # A live claim is honoured…
            assert (
                await claim_next_task(
                    conn,
                    kind=FleetTaskKind.DRIVE_RUN,
                    worker_id="worker-b",
                    project_run_id=run_id,
                    stale_after=_FRESH,
                )
                is None
            )
            # …a stale one (killed holder) is re-owned, attempts counted.
            reclaimed = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-b",
                project_run_id=run_id,
                stale_after=_STALE_NOW,
            )
            assert reclaimed is not None
            assert reclaimed.claimed_by == "worker-b" and reclaimed.attempts == 2

    run_async(_run())


def test_touch_restamps_a_live_claim_holder_guarded() -> None:
    """The claim heartbeat: a live holder's touch keeps its task out of the staleness window; a
    non-holder's touch is a no-op."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_id, dedup_key=str(run_id)
            )
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-a",
                project_run_id=run_id,
                stale_after=_FRESH,
            )
            assert task is not None
            from clue_fleet import touch_task

            assert await touch_task(conn, task_id=task.task_id, worker_id="worker-a")
            assert not await touch_task(conn, task_id=task.task_id, worker_id="worker-b")

    run_async(_run())


def test_finish_and_requeue_are_holder_guarded() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_id, dedup_key=str(run_id)
            )
            task = await claim_next_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, worker_id="worker-a", stale_after=_FRESH
            )
            assert task is not None
            # A fenced-out zombie can neither finish nor requeue.
            assert not await finish_task(
                conn, task_id=task.task_id, worker_id="worker-b", status=FleetTaskStatus.DONE
            )
            assert not await requeue_task(conn, task_id=task.task_id, worker_id="worker-b")
            # The holder finishes with a result ref; terminal states reject further writes.
            assert await finish_task(
                conn,
                task_id=task.task_id,
                worker_id="worker-a",
                status=FleetTaskStatus.DONE,
                result_ref={"outcome": "completed"},
            )
            row = await get_task(conn, task.task_id)
            assert row is not None and row.status is FleetTaskStatus.DONE
            assert row.result_ref == {"outcome": "completed"}
            assert not await finish_task(
                conn, task_id=task.task_id, worker_id="worker-a", status=FleetTaskStatus.DONE
            )

    run_async(_run())


def test_delayed_requeue_uses_db_time_and_does_not_starve_ready_work() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                project_run_id=run_id,
                dedup_key="delayed-high-priority",
                priority=-10,
            )
            await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                project_run_id=run_id,
                dedup_key="ready-lower-priority",
                priority=0,
            )
            delayed = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-a",
                project_run_id=run_id,
                stale_after=_FRESH,
            )
            assert delayed is not None and delayed.dedup_key == "delayed-high-priority"
            assert await requeue_task(
                conn,
                task_id=delayed.task_id,
                worker_id="worker-a",
                delay=timedelta(seconds=60),
            )

            stored = await get_task(conn, delayed.task_id)
            assert stored is not None
            assert (
                await conn.execute(
                    text("SELECT available_at > now() FROM fleet_task WHERE task_id = :task_id"),
                    {"task_id": delayed.task_id},
                )
            ).scalar_one()

            ready = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-b",
                project_run_id=run_id,
                stale_after=_FRESH,
            )
            assert ready is not None and ready.dedup_key == "ready-lower-priority"
            assert await finish_task(
                conn,
                task_id=ready.task_id,
                worker_id="worker-b",
                status=FleetTaskStatus.DONE,
            )

            assert (
                await claim_next_task(
                    conn,
                    kind=FleetTaskKind.DRIVE_RUN,
                    worker_id="worker-c",
                    project_run_id=run_id,
                    stale_after=_FRESH,
                )
                is None
            )
            await conn.execute(
                text("UPDATE fleet_task SET available_at = now() WHERE task_id = :task_id"),
                {"task_id": delayed.task_id},
            )
            matured = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-c",
                project_run_id=run_id,
                stale_after=_FRESH,
            )
            assert matured is not None and matured.task_id == delayed.task_id

    run_async(_run())


def test_a_requeue_can_take_back_the_attempt_its_claim_counted() -> None:
    """A claim that bounced off a held lease never ran, so it must not spend an attempt — the
    research and crawl handlers read ``attempts`` as a retry budget."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_id, dedup_key="d"
            )
            for expected in (1, 1, 1):
                claimed = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.DRIVE_RUN,
                    worker_id="worker-a",
                    project_run_id=run_id,
                    stale_after=_FRESH,
                )
                assert claimed is not None and claimed.attempts == expected
                assert await requeue_task(
                    conn, task_id=claimed.task_id, worker_id="worker-a", uncount_attempt=True
                )
                stored = await get_task(conn, claimed.task_id)
                assert stored is not None and stored.attempts == expected - 1

    run_async(_run())


def test_an_offer_for_busy_work_is_refused_until_the_live_task_ends() -> None:
    """``only_if_work_idle``: at most one live (queued or claimed) task of a kind per work id —
    the shape the agent-turn dispatcher already keeps, now available to any offerer."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            work = new_project_run_id()
            other = new_project_run_id()

            async def offer(work_id, key: str) -> bool:
                return await enqueue_task(
                    conn,
                    kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH,
                    project_run_id=work_id,
                    dedup_key=key,
                    only_if_work_idle=True,
                )

            assert await offer(work, "rev-2")
            assert not await offer(work, "rev-3")  # rev-2 is queued
            # Another work id, and another kind on the same work id, are not affected.
            assert await offer(other, "rev-3")
            assert await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=work, dedup_key="rev-3"
            )
            running = await claim_next_task(
                conn,
                kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH,
                worker_id="worker-a",
                project_run_id=work,
                stale_after=_FRESH,
            )
            assert running is not None and running.dedup_key == "rev-2"
            assert not await offer(work, "rev-3")  # rev-2 is claimed
            assert await finish_task(
                conn, task_id=running.task_id, worker_id="worker-a", status=FleetTaskStatus.DONE
            )
            assert await offer(work, "rev-5")  # idle again: the latest revision is offered
            rows = await list_tasks(
                conn, project_run_id=work, kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH
            )
            assert sorted(row.dedup_key for row in rows) == ["rev-2", "rev-5"]

    run_async(_run())


def test_requeue_rejects_negative_delay_before_touching_db() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(ValueError, match="cannot be negative"):
                await requeue_task(
                    conn,
                    task_id=new_project_run_id(),
                    worker_id="worker",
                    delay=timedelta(seconds=-1),
                )

    run_async(_run())


def test_finish_rejects_non_terminal_status() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(ValueError, match="terminal"):
                await finish_task(
                    conn,
                    task_id=new_project_run_id(),  # any uuid — validation fires first
                    worker_id="w",
                    status=FleetTaskStatus.QUEUED,
                )

    run_async(_run())


def test_requeue_failed_is_the_explicit_retry_gate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.ACCOUNT_JOB, project_run_id=run_id, dedup_key="acct"
            )
            task = await claim_next_task(
                conn, kind=FleetTaskKind.ACCOUNT_JOB, worker_id="w", stale_after=_FRESH
            )
            assert task is not None
            await finish_task(
                conn, task_id=task.task_id, worker_id="w", status=FleetTaskStatus.FAILED
            )
            # FAILED is parked: not claimable…
            assert (
                await claim_next_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    worker_id="w",
                    project_run_id=run_id,
                    stale_after=_STALE_NOW,
                )
                is None
            )
            # …until a fresh drive explicitly re-opens it.
            assert (
                await requeue_failed_tasks(
                    conn, kind=FleetTaskKind.ACCOUNT_JOB, project_run_id=run_id
                )
                == 1
            )
            retried = await claim_next_task(
                conn,
                kind=FleetTaskKind.ACCOUNT_JOB,
                worker_id="w",
                project_run_id=run_id,
                stale_after=_FRESH,
            )
            assert retried is not None and retried.attempts == 2

    run_async(_run())


def test_deep_drain_never_double_runs_a_job_whose_claim_went_stale_mid_flight() -> None:
    """The in-flight guard: with an instantly-stale window (the pathological case — every
    claimed row always looks orphaned), sibling drainers keep re-claiming each other's running
    jobs; without the guard each job would execute many times. Uses the real ``DbTaskQueue``
    (committed rows, run-scoped ids) because staleness is DB-clock behavior the fakes don't
    model."""

    async def _run() -> None:
        import asyncio
        from collections import Counter
        from uuid import NAMESPACE_URL, uuid5

        from tests.fleet.conftest import ProcessLocalLockFactory

        from clue_core import EntityId
        from clue_fleet import DbTaskQueue, QueueBackedScheduler
        from clue_research.durable import AccountSpec

        run_id = new_project_run_id()
        specs = [
            AccountSpec(
                entity_id=EntityId(uuid5(NAMESPACE_URL, f"inflight:{run_id}:{i}")), tier="top"
            )
            for i in range(4)
        ]
        executions: Counter[str] = Counter()

        async def run_one(spec: AccountSpec) -> str:
            executions[str(spec.entity_id)] += 1
            await asyncio.sleep(0.05)  # long enough for siblings to re-claim it while running
            return "ok"

        from clue_db import db_lifespan

        async with db_lifespan():
            scheduler = QueueBackedScheduler(
                queue=DbTaskQueue(),
                window=3,
                stale_after=timedelta(0),  # every claim is instantly "stale"
                poll_interval=0.01,
                lock_factory=ProcessLocalLockFactory(),
            )
            results = await scheduler.run_accounts(
                specs, project_run_id=run_id, checkpointer=None, run_one=run_one
            )
        assert results == ["ok"] * 4
        assert all(count == 1 for count in executions.values()), dict(executions)

    run_async(_run())


def test_cross_run_same_entity_is_single_flighted_on_the_real_queue() -> None:
    """The DB-gated twin of the offline single-flight gate: two project runs share one entity on
    the real ``DbTaskQueue`` (committed rows, run-scoped ``uuid5`` entity ids, the real claim
    path), one shared entity-lock factory across both schedulers. Uses the real DB because the
    two runs' account jobs are two distinct committed rows on distinct ``project_run_id``s — the
    single-flight can only be the injected entity lock's doing, not any queue-level dedup — and
    that cross-row concurrency is exactly what the in-memory fake cannot model."""

    async def _run() -> None:
        import asyncio
        from collections import Counter
        from uuid import NAMESPACE_URL, uuid5

        from tests.fleet.conftest import ProcessLocalLockFactory

        from clue_core import EntityId
        from clue_fleet import DbTaskQueue, QueueBackedScheduler
        from clue_research.durable import AccountSpec

        run_a, run_b = new_project_run_id(), new_project_run_id()
        shared = EntityId(uuid5(NAMESPACE_URL, f"single-flight:shared:{run_a}:{run_b}"))
        specs_a = [
            AccountSpec(entity_id=shared, tier="top"),
            AccountSpec(entity_id=EntityId(uuid5(NAMESPACE_URL, f"only-a:{run_a}")), tier="high"),
        ]
        specs_b = [
            AccountSpec(entity_id=shared, tier="top"),
            AccountSpec(entity_id=EntityId(uuid5(NAMESPACE_URL, f"only-b:{run_b}")), tier="high"),
        ]

        in_flight: Counter[str] = Counter()
        peak: Counter[str] = Counter()

        async def run_one(spec: AccountSpec) -> str:
            key = str(spec.entity_id)
            in_flight[key] += 1
            peak[key] = max(peak[key], in_flight[key])
            await asyncio.sleep(0.05)
            in_flight[key] -= 1
            return f"result:{key}"

        from clue_db import db_lifespan

        lock_factory = ProcessLocalLockFactory()  # ONE shared lock across both schedulers

        def _sched() -> QueueBackedScheduler:
            return QueueBackedScheduler(
                queue=DbTaskQueue(), window=3, poll_interval=0.01, lock_factory=lock_factory
            )

        async with db_lifespan():
            results_a, results_b = await asyncio.gather(
                _sched().run_accounts(
                    specs_a, project_run_id=run_a, checkpointer=None, run_one=run_one
                ),
                _sched().run_accounts(
                    specs_b, project_run_id=run_b, checkpointer=None, run_one=run_one
                ),
            )
        # The shared entity was single-flighted across the two committed runs...
        assert peak[str(shared)] == 1, dict(peak)
        # ...and both runs completed with correct, input-ordered results.
        assert results_a == [f"result:{s.entity_id}" for s in specs_a]
        assert results_b == [f"result:{s.entity_id}" for s in specs_b]

    run_async(_run())


def test_heartbeat_death_never_yields_two_concurrent_drivers() -> None:
    """The audit repro (finding #2) inverted into a live gate: worker A's renewal path keeps
    raising while it is mid-*phase* (a long ``advance``); the supervised heartbeat declares the
    lease lost at ``deadline − heartbeat`` and cancels A's phase *before* the TTL lapses, so when
    worker B takes over (only after expiry) the two never ``advance()`` the same run concurrently.
    Real ``DbLeaseStore`` + ``DbTaskQueue``; a shared probe counts in-flight advances and its
    peak. Before the fix, A's heartbeat died silently, A's phase ran on past expiry, B took the
    lease, and peak concurrent drivers hit 2."""

    async def _run() -> None:
        import asyncio

        from tests.fleet.conftest import run_row

        from clue_core import ProjectPhase
        from clue_db import db_lifespan
        from clue_fleet import DbLeaseStore, DbTaskQueue, ProjectRunWorker, enqueue_drive
        from clue_research.durable import ProjectRunStatus

        run_id = new_project_run_id()
        advance_s = 4.0  # far longer than the lease TTL — A must be cancelled mid-flight

        class _Probe:
            def __init__(self) -> None:
                self.in_flight = 0
                self.peak = 0
                self.starts: list[str] = []
                self.completions: list[str] = []

        probe = _Probe()

        class _ProbeDriver:
            def __init__(self, label: str) -> None:
                self.label = label

            async def status(self, project_run_id: object) -> object:
                done = bool(probe.completions)
                return run_row(
                    run_id,
                    phase=ProjectPhase.DEEP,
                    status=ProjectRunStatus.COMPLETED if done else ProjectRunStatus.ACTIVE,
                )

            async def advance(self, project_run_id: object) -> object:
                probe.starts.append(self.label)
                probe.in_flight += 1
                probe.peak = max(probe.peak, probe.in_flight)
                try:
                    await asyncio.sleep(advance_s)
                finally:
                    probe.in_flight -= 1
                probe.completions.append(self.label)
                return run_row(
                    run_id, phase=ProjectPhase.HANDOFF, status=ProjectRunStatus.COMPLETED
                )

        class _RaisingRenewLease:
            """A real ``DbLeaseStore`` whose renew always raises — the audit's exact trigger."""

            def __init__(self, inner: DbLeaseStore) -> None:
                self._inner = inner

            async def acquire(self, **kw: object) -> bool:
                return await self._inner.acquire(**kw)  # type: ignore[arg-type]

            async def renew(self, **kw: object) -> bool:
                raise RuntimeError("simulated renewal fault")

            async def release(self, **kw: object) -> None:
                await self._inner.release(**kw)  # type: ignore[arg-type]

            async def get(self, project_run_id: object) -> object:
                return await self._inner.get(project_run_id)  # type: ignore[arg-type]

        # A short task-stale window lets B reclaim A's drive task while A is still mid-phase, so
        # the LEASE (not the queue) is what must block B: under the old silent-heartbeat-death,
        # A drives on past lease expiry and B takes over → peak 2; with the fix A is cancelled at
        # deadline−heartbeat (~1.2s), strictly before B's acquire at TTL expiry (~1.5s) → peak 1.
        timings = {
            "poll_interval": 0.1,
            "lease_ttl": timedelta(seconds=1.5),
            "heartbeat_interval": 0.3,
            "task_stale_after": timedelta(seconds=0.5),
        }

        async with db_lifespan():
            queue = DbTaskQueue()
            await enqueue_drive(queue, run_id)
            worker_a = ProjectRunWorker(
                driver=_ProbeDriver("A"),  # type: ignore[arg-type]
                queue=queue,
                leases=_RaisingRenewLease(DbLeaseStore()),  # type: ignore[arg-type]
                worker_id="fence-A",
                **timings,  # type: ignore[arg-type]
            )
            worker_b = ProjectRunWorker(
                driver=_ProbeDriver("B"),  # type: ignore[arg-type]
                queue=queue,
                leases=DbLeaseStore(),
                worker_id="fence-B",
                **timings,  # type: ignore[arg-type]
            )

            async def _watch() -> None:
                deadline = asyncio.get_running_loop().time() + 25
                while not probe.completions:
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.1)
                worker_b.stop()

            # A claims + starts its long phase first; B starts polling a beat later.
            a_task = asyncio.create_task(worker_a.drain_once())
            await asyncio.sleep(0.2)
            b_task = asyncio.create_task(worker_b.run())
            watch_task = asyncio.create_task(_watch())
            await asyncio.wait_for(asyncio.gather(a_task, b_task, watch_task), timeout=30)

        assert probe.peak == 1, f"two concurrent drivers: {probe.peak}"
        assert "A" in probe.starts, "worker A should have started its phase"
        assert "A" not in probe.completions, "A's phase must have been cancelled, not completed"
        assert "B" in probe.completions, "worker B should have taken over and completed the run"

    run_async(_run())


def test_claim_scopes_by_run_and_kind() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_a, run_b = new_project_run_id(), new_project_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.ACCOUNT_JOB, project_run_id=run_a, dedup_key="acct-a"
            )
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, project_run_id=run_b, dedup_key=str(run_b)
            )
            # Scoped to run_b's account jobs: nothing (its only task is a drive_run).
            assert (
                await claim_next_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    worker_id="w",
                    project_run_id=run_b,
                    stale_after=_FRESH,
                )
                is None
            )
            # The drive drain sees run_b's drive task (scoped here to stay hermetic against
            # committed rows from other suites; the exit-gate test covers the unscoped drain).
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="w",
                project_run_id=run_b,
                stale_after=_FRESH,
            )
            assert task is not None and task.project_run_id == run_b

    run_async(_run())
