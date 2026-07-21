"""DB-gated tests for the PB-B1 fleet tables — ``run_lease`` + ``fleet_task``.

Need a reachable, migrated Postgres and ``pytest.skip`` without one. Cover: the two enum
parities, the lease's atomic acquire/expiry-takeover/holder-guarded renew+release, and the
queue's idempotent enqueue, priority claim order, holder guards, stale reclaim, and the explicit
FAILED requeue gate. Repo calls run inside a rolled-back transaction, so no committed rows leak.

Postgres ``now()`` is frozen inside one transaction, so expiry/staleness are exercised with
**zero** TTLs/windows (``expires_at <= now()`` / ``claimed_at <= now() - 0`` hold immediately)
rather than sleeps — deterministic, no timing flakes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    acquire_run_lease,
    claim_next_task,
    enqueue_task,
    finish_task,
    get_run_lease,
    get_task,
    list_tasks,
    release_run_lease,
    renew_run_lease,
    requeue_failed_tasks,
    requeue_task,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.fleet.conftest import rollback_conn, run_async

from clue_core import new_campaign_run_id

pytestmark = pytest.mark.usefixtures("require_fleet_db")

_TTL = timedelta(seconds=60)
_EXPIRED = timedelta(0)
_FRESH = timedelta(seconds=60)
_STALE_NOW = timedelta(0)


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
            run_id = new_campaign_run_id()
            assert await acquire_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )
            # The exit-gate property, first half: a second worker may NOT drive a leased run.
            assert not await acquire_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and lease.worker_id == "worker-a" and lease.live

    run_async(_run())


def test_lease_reacquire_by_holder_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            assert await acquire_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )
            assert await acquire_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )

    run_async(_run())


def test_lease_takeover_after_expiry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            # ttl=0 → born expired (kill -9: the holder stops renewing and the TTL lapses).
            assert await acquire_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_EXPIRED
            )
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and not lease.live
            # The exit-gate property, second half: takeover happens only after expiry.
            assert await acquire_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and lease.worker_id == "worker-b" and lease.live

    run_async(_run())


def test_lease_renew_is_holder_guarded_and_dead_after_expiry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            await acquire_run_lease(conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_TTL)
            assert await renew_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_TTL
            )
            # Not the holder → no renewal.
            assert not await renew_run_lease(
                conn, campaign_run_id=run_id, worker_id="worker-b", ttl=_TTL
            )
            # Expired → not renewable even by the old holder (a takeover may be racing): the
            # driver must treat this as lease-lost and abort.
            other = new_campaign_run_id()
            await acquire_run_lease(conn, campaign_run_id=other, worker_id="worker-a", ttl=_EXPIRED)
            assert not await renew_run_lease(
                conn, campaign_run_id=other, worker_id="worker-a", ttl=_TTL
            )

    run_async(_run())


def test_lease_release_is_holder_guarded() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            await acquire_run_lease(conn, campaign_run_id=run_id, worker_id="worker-a", ttl=_TTL)
            # A fenced-out zombie's release is a no-op.
            await release_run_lease(conn, campaign_run_id=run_id, worker_id="worker-b")
            lease = await get_run_lease(conn, run_id)
            assert lease is not None and lease.worker_id == "worker-a"
            # The holder's release frees the run.
            await release_run_lease(conn, campaign_run_id=run_id, worker_id="worker-a")
            assert await get_run_lease(conn, run_id) is None

    run_async(_run())


# --- fleet_task --------------------------------------------------------------


def test_enqueue_is_idempotent_on_dedup_key() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            assert await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                campaign_run_id=run_id,
                dedup_key=str(run_id),
            )
            assert not await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                campaign_run_id=run_id,
                dedup_key=str(run_id),
            )
            rows = await list_tasks(conn, campaign_run_id=run_id, kind=FleetTaskKind.DRIVE_RUN)
            assert len(rows) == 1

    run_async(_run())


def test_enqueue_reopen_terminal_reopens_finished_drive_tasks_only() -> None:
    """The resume path: a paused run's DONE drive task must not block the post-resume re-drive
    (``enqueue_drive`` re-opens it), while the default account-job enqueue never resurrects a
    done row (it is the run's exactly-once completion marker)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, campaign_run_id=run_id, dedup_key=str(run_id)
            )
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="w",
                campaign_run_id=run_id,
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
                conn, kind=FleetTaskKind.DRIVE_RUN, campaign_run_id=run_id, dedup_key=str(run_id)
            )
            # A queued/claimed row is a no-op even with reopen (the work is already offered).
            # A terminal row is re-opened — same task id, clean slate, claimable again.
            assert await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                campaign_run_id=run_id,
                dedup_key=str(run_id),
                reopen_terminal=True,
            )
            reopened = await get_task(conn, task.task_id)
            assert reopened is not None and reopened.status is FleetTaskStatus.QUEUED
            assert reopened.claimed_by is None and reopened.result_ref == {}
            assert not await enqueue_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                campaign_run_id=run_id,
                dedup_key=str(run_id),
                reopen_terminal=True,
            )

    run_async(_run())


def test_claim_order_is_priority_then_fifo() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            for key, priority in (("low-first", 3), ("top", 0), ("high", 1), ("low-second", 3)):
                await enqueue_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    campaign_run_id=run_id,
                    dedup_key=key,
                    priority=priority,
                )
            claimed = []
            while True:
                task = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    worker_id="w",
                    campaign_run_id=run_id,
                    stale_after=_FRESH,
                )
                if task is None:
                    break
                claimed.append(task.dedup_key)
            assert claimed == ["top", "high", "low-first", "low-second"]

    run_async(_run())


def test_claimed_task_is_not_reclaimable_until_stale() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, campaign_run_id=run_id, dedup_key=str(run_id)
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
                    campaign_run_id=run_id,
                    stale_after=_FRESH,
                )
                is None
            )
            # …a stale one (killed holder) is re-owned, attempts counted.
            reclaimed = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-b",
                campaign_run_id=run_id,
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
            run_id = new_campaign_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, campaign_run_id=run_id, dedup_key=str(run_id)
            )
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.DRIVE_RUN,
                worker_id="worker-a",
                campaign_run_id=run_id,
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
            run_id = new_campaign_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, campaign_run_id=run_id, dedup_key=str(run_id)
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


def test_finish_rejects_non_terminal_status() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(ValueError, match="terminal"):
                await finish_task(
                    conn,
                    task_id=new_campaign_run_id(),  # any uuid — validation fires first
                    worker_id="w",
                    status=FleetTaskStatus.QUEUED,
                )

    run_async(_run())


def test_requeue_failed_is_the_explicit_retry_gate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_campaign_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.ACCOUNT_JOB, campaign_run_id=run_id, dedup_key="acct"
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
                    campaign_run_id=run_id,
                    stale_after=_STALE_NOW,
                )
                is None
            )
            # …until a fresh drive explicitly re-opens it.
            assert (
                await requeue_failed_tasks(
                    conn, kind=FleetTaskKind.ACCOUNT_JOB, campaign_run_id=run_id
                )
                == 1
            )
            retried = await claim_next_task(
                conn,
                kind=FleetTaskKind.ACCOUNT_JOB,
                worker_id="w",
                campaign_run_id=run_id,
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

        from clue_fleet import DbTaskQueue, QueueBackedScheduler
        from tests.fleet.conftest import ProcessLocalLockFactory

        from clue_core import EntityId
        from clue_research.durable import AccountSpec

        run_id = new_campaign_run_id()
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
                specs, campaign_run_id=run_id, checkpointer=None, run_one=run_one
            )
        assert results == ["ok"] * 4
        assert all(count == 1 for count in executions.values()), dict(executions)

    run_async(_run())


def test_cross_run_same_entity_is_single_flighted_on_the_real_queue() -> None:
    """The DB-gated twin of the offline single-flight gate: two campaign runs share one entity on
    the real ``DbTaskQueue`` (committed rows, run-scoped ``uuid5`` entity ids, the real claim
    path), one shared entity-lock factory across both schedulers. Uses the real DB because the
    two runs' account jobs are two distinct committed rows on distinct ``campaign_run_id``s — the
    single-flight can only be the injected entity lock's doing, not any queue-level dedup — and
    that cross-row concurrency is exactly what the in-memory fake cannot model."""

    async def _run() -> None:
        import asyncio
        from collections import Counter
        from uuid import NAMESPACE_URL, uuid5

        from clue_fleet import DbTaskQueue, QueueBackedScheduler
        from tests.fleet.conftest import ProcessLocalLockFactory

        from clue_core import EntityId
        from clue_research.durable import AccountSpec

        run_a, run_b = new_campaign_run_id(), new_campaign_run_id()
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
                    specs_a, campaign_run_id=run_a, checkpointer=None, run_one=run_one
                ),
                _sched().run_accounts(
                    specs_b, campaign_run_id=run_b, checkpointer=None, run_one=run_one
                ),
            )
        # The shared entity was single-flighted across the two committed runs...
        assert peak[str(shared)] == 1, dict(peak)
        # ...and both runs completed with correct, input-ordered results.
        assert results_a == [f"result:{s.entity_id}" for s in specs_a]
        assert results_b == [f"result:{s.entity_id}" for s in specs_b]

    run_async(_run())


def test_claim_scopes_by_run_and_kind() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_a, run_b = new_campaign_run_id(), new_campaign_run_id()
            await enqueue_task(
                conn, kind=FleetTaskKind.ACCOUNT_JOB, campaign_run_id=run_a, dedup_key="acct-a"
            )
            await enqueue_task(
                conn, kind=FleetTaskKind.DRIVE_RUN, campaign_run_id=run_b, dedup_key=str(run_b)
            )
            # Scoped to run_b's account jobs: nothing (its only task is a drive_run).
            assert (
                await claim_next_task(
                    conn,
                    kind=FleetTaskKind.ACCOUNT_JOB,
                    worker_id="w",
                    campaign_run_id=run_b,
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
                campaign_run_id=run_b,
                stale_after=_FRESH,
            )
            assert task is not None and task.campaign_run_id == run_b

    run_async(_run())
