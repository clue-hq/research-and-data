"""C5.3 monotone work-lease generation fence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

from clue_core import ProjectRunId
from clue_fleet import (
    FleetTaskKind,
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    get_work_lease,
    release_work_lease,
    renew_work_lease,
)
from clue_fleet.lease import (
    WORK_LEASE_PRUNE,
    prune_released_work_leases,
    prune_released_work_leases_if_due,
    revoke_work_lease,
)
from clue_fleet.queue import claim_next_task, enqueue_task

pytestmark = pytest.mark.usefixtures("require_fleet_db")


def test_takeover_increments_generation_and_fences_old_holder() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            first = await acquire_work_lease(
                conn,
                work_id=work_id,
                worker_id="first",
                ttl=timedelta(0),
            )
            assert first is not None and first.generation == 1
            second = await acquire_work_lease(
                conn,
                work_id=work_id,
                worker_id="second",
                ttl=timedelta(seconds=60),
            )
            assert second is not None and second.generation == 2
            assert not await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="first",
                generation=LeaseGeneration(first.generation),
                ttl=timedelta(seconds=60),
            )
            assert await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="second",
                generation=LeaseGeneration(second.generation),
                ttl=timedelta(seconds=60),
            )

    run_async(scenario())


# --- site-turn durability, task 1 (2026-10-16): generations never repeat ----------------------
#
# Releasing a lease used to DELETE its row, so the next acquire restarted at generation 1 — the
# number the previous holder had — and no fence could tell the old attempt from the new one (the
# same reset broke research resumes on 2026-08-19). Release now ends the lease and keeps the row;
# a renew lands whenever the row still names this worker and this generation, even past expiry,
# because nobody else has claimed it then.


def test_release_then_acquire_by_another_worker_gives_generation_two() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            first = await acquire_work_lease(
                conn, work_id=work_id, worker_id="first", ttl=timedelta(seconds=60)
            )
            assert first is not None and first.generation == 1
            await release_work_lease(
                conn, work_id=work_id, worker_id="first", generation=LeaseGeneration(1)
            )
            released = await get_work_lease(conn, work_id)
            assert released is not None and not released.live  # kept, but ended
            second = await acquire_work_lease(
                conn, work_id=work_id, worker_id="second", ttl=timedelta(seconds=60)
            )
            assert second is not None and second.generation == 2

    run_async(scenario())


def test_the_same_worker_releasing_and_reacquiring_gets_generation_two() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            first = await acquire_work_lease(
                conn, work_id=work_id, worker_id="same", ttl=timedelta(seconds=60)
            )
            assert first is not None and first.generation == 1
            await release_work_lease(
                conn, work_id=work_id, worker_id="same", generation=LeaseGeneration(1)
            )
            again = await acquire_work_lease(
                conn, work_id=work_id, worker_id="same", ttl=timedelta(seconds=60)
            )
            assert again is not None and again.generation == 2

    run_async(scenario())


def test_an_expired_lease_nobody_took_is_renewed_by_its_holder_at_the_same_generation() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            held = await acquire_work_lease(
                conn, work_id=work_id, worker_id="slow", ttl=timedelta(0)
            )
            assert held is not None and held.generation == 1
            lapsed = await get_work_lease(conn, work_id)
            assert lapsed is not None and not lapsed.live  # expired, unclaimed
            assert await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="slow",
                generation=LeaseGeneration(1),
                ttl=timedelta(seconds=60),
            )
            back = await get_work_lease(conn, work_id)
            assert back is not None and back.live
            assert (back.worker_id, back.generation) == ("slow", 1)

    run_async(scenario())


def test_a_lease_retaken_through_a_stale_task_claim_cannot_be_renewed_by_its_old_holder() -> None:
    """The stale-claim interleaving: worker A claims the task and the lease, stops beating (its
    database calls fail), the task goes stale, worker B re-claims the task and acquires the
    expired lease at generation 2. When A's database comes back, its renew must fail."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            assert await enqueue_task(
                conn,
                kind=FleetTaskKind.DESIGN_JOB,
                project_run_id=ProjectRunId(work_id),
                dedup_key=str(work_id),
            )
            claimed_a = await claim_next_task(
                conn,
                kind=FleetTaskKind.DESIGN_JOB,
                worker_id="worker-a",
                project_run_id=ProjectRunId(work_id),
            )
            assert claimed_a is not None
            lease_a = await acquire_work_lease(
                conn, work_id=work_id, worker_id="worker-a", ttl=timedelta(0)
            )
            assert lease_a is not None and lease_a.generation == 1
            # A zero staleness window stands in for fleet_task_stale_after_s having passed (now()
            # is frozen inside this transaction).
            claimed_b = await claim_next_task(
                conn,
                kind=FleetTaskKind.DESIGN_JOB,
                worker_id="worker-b",
                project_run_id=ProjectRunId(work_id),
                stale_after=timedelta(0),
            )
            assert claimed_b is not None and claimed_b.task_id == claimed_a.task_id
            lease_b = await acquire_work_lease(
                conn, work_id=work_id, worker_id="worker-b", ttl=timedelta(seconds=60)
            )
            assert lease_b is not None and lease_b.generation == 2
            assert not await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="worker-a",
                generation=LeaseGeneration(1),
                ttl=timedelta(seconds=60),
            )
            current = await get_work_lease(conn, work_id)
            assert current is not None
            assert (current.worker_id, current.generation, current.live) == ("worker-b", 2, True)

    run_async(scenario())


def test_two_holders_cannot_both_hold_one_live_lease() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            assert await acquire_work_lease(
                conn, work_id=work_id, worker_id="process-1", ttl=timedelta(seconds=60)
            )
            assert (
                await acquire_work_lease(
                    conn, work_id=work_id, worker_id="process-2", ttl=timedelta(seconds=60)
                )
                is None
            )

    run_async(scenario())


def test_a_revoked_lease_fences_its_holder_and_the_next_generation_is_higher() -> None:
    """Revocation (entity-research cancellation) used to DELETE the row too. It now moves the
    generation on, so the resident holder's next renew fails and no later acquire repeats a
    number."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            held = await acquire_work_lease(
                conn, work_id=work_id, worker_id="resident", ttl=timedelta(seconds=60)
            )
            assert held is not None and held.generation == 1
            await revoke_work_lease(conn, work_id=work_id)
            revoked = await get_work_lease(conn, work_id)
            assert revoked is not None and not revoked.live
            assert not await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="resident",
                generation=LeaseGeneration(1),
                ttl=timedelta(seconds=60),
            )
            nxt = await acquire_work_lease(
                conn, work_id=work_id, worker_id="resident", ttl=timedelta(seconds=60)
            )
            assert nxt is not None and nxt.generation > 1

    run_async(scenario())


def test_pruning_drops_only_long_ended_leases_whose_work_has_no_live_task() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            old_done, old_queued, old_bare, recent = (WorkId(uuid4()) for _ in range(4))
            for work_id in (old_done, old_queued, old_bare, recent):
                assert await acquire_work_lease(
                    conn, work_id=work_id, worker_id="w", ttl=timedelta(seconds=60)
                )
                await release_work_lease(
                    conn, work_id=work_id, worker_id="w", generation=LeaseGeneration(1)
                )
            for work_id in (old_done, old_queued):
                assert await enqueue_task(
                    conn,
                    kind=FleetTaskKind.DESIGN_JOB,
                    project_run_id=ProjectRunId(work_id),
                    dedup_key=str(work_id),
                )
            await conn.execute(
                text("UPDATE fleet_task SET status = 'done' WHERE work_id = :w"), {"w": old_done}
            )
            await conn.execute(
                text(
                    "UPDATE work_lease SET expires_at = now() - interval '31 days'"
                    " WHERE work_id = ANY(:ids)"
                ),
                {"ids": [old_done, old_queued, old_bare]},
            )
            await conn.execute(
                text(
                    "UPDATE work_lease SET expires_at = now() - interval '29 days'"
                    " WHERE work_id = :w"
                ),
                {"w": recent},
            )

            pruned = await prune_released_work_leases(conn)

            assert pruned == 2
            assert await get_work_lease(conn, old_done) is None
            assert await get_work_lease(conn, old_bare) is None
            assert await get_work_lease(conn, old_queued) is not None  # work can still run
            assert await get_work_lease(conn, recent) is not None  # not 30 days yet

    run_async(scenario())


def test_the_fleet_prunes_ended_leases_once_per_interval_on_the_maintenance_clock() -> None:
    every = timedelta(days=1)
    t0 = datetime(2026, 10, 16, 12, tzinfo=UTC)

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await conn.execute(
                text("DELETE FROM maintenance_run WHERE name = :n"), {"n": WORK_LEASE_PRUNE}
            )
            stale = WorkId(uuid4())
            assert await acquire_work_lease(
                conn, work_id=stale, worker_id="w", ttl=timedelta(seconds=60)
            )
            await conn.execute(
                text(
                    "UPDATE work_lease SET expires_at = now() - interval '40 days'"
                    " WHERE work_id = :w"
                ),
                {"w": stale},
            )
            first = await prune_released_work_leases_if_due(conn, every=every, now=t0)
            assert first is not None and first >= 1
            assert await get_work_lease(conn, stale) is None
            too_soon = await prune_released_work_leases_if_due(
                conn, every=every, now=t0 + timedelta(hours=1)
            )
            assert too_soon is None
            due = await prune_released_work_leases_if_due(
                conn, every=every, now=t0 + timedelta(hours=25)
            )
            assert due is not None
            last = (
                await conn.execute(
                    text("SELECT last_run_at FROM maintenance_run WHERE name = :n"),
                    {"n": WORK_LEASE_PRUNE},
                )
            ).scalar_one()
            assert last == t0 + timedelta(hours=25)

    run_async(scenario())
