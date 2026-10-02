"""Spec §3.3 step 3: drive_batch drives every sibling nobody holds, waits only while a live
foreign lease proves someone else is driving one, and returns when all are terminal."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from clue_api.design_fleet import InlineDesignLaneDriver
from clue_db import db_lifespan, transaction
from clue_design import runs as design_runs
from clue_fleet import WorkId, acquire_work_lease, release_work_lease
from tests.api.test_p34_inline_lane_lease_db import (
    _cleanup_committed_run,
    _seed_committed_run,
    _SlowCompletingHandler,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
)


def test_a_batch_of_three_is_driven_to_terminal_by_one_slot(
    migrated_db: bool,  # noqa: F811
) -> None:
    """The single-slot floor of §3.3: when no other slot ever frees, the chat turn's slot
    acquires every lease itself and drives all N sequentially to terminal."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            envelopes = [await _seed_committed_run(f"batch{i}") for i in range(3)]
            try:
                handler = _SlowCompletingHandler(run_seconds=0.2)
                driver = InlineDesignLaneDriver(
                    handler=handler,
                    lease_ttl=timedelta(seconds=2),
                    join_poll_interval_s=0.1,
                )
                await asyncio.wait_for(driver.drive_batch(envelopes=envelopes), timeout=30.0)
                assert len(handler.contexts) == 3
                async with transaction() as conn:
                    for env in envelopes:
                        run = await design_runs.get_run(
                            conn, workspace_id=env.workspace_id, run_id=env.run_id
                        )
                        assert run is not None and run["status"] == "succeeded"
            finally:
                for env in envelopes:
                    await _cleanup_committed_run(env)

    run_async(scenario())


def test_a_sibling_held_by_a_live_foreign_lease_is_skipped_then_joined(
    migrated_db: bool,  # noqa: F811
) -> None:
    """Run B is held by 'another slot' (a foreign live lease that completes it after a while);
    the driver must drive A itself, never call the handler for B, and return once B is terminal."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            a, b = await _seed_committed_run("held_a"), await _seed_committed_run("held_b")
            try:
                async with transaction() as conn:
                    lease = await acquire_work_lease(
                        conn,
                        work_id=WorkId(b.work_id),
                        worker_id="other-slot",
                        ttl=timedelta(seconds=30),
                    )
                assert lease is not None

                async def other_slot_finishes_b() -> None:
                    await asyncio.sleep(1.0)
                    async with transaction() as conn:
                        await design_runs.set_run_result(
                            conn,
                            workspace_id=b.workspace_id,
                            run_id=b.run_id,
                            status="succeeded",
                            result={"schema_version": 1, "status": "accepted"},
                            expected_generation=int(lease.generation),
                        )
                        await release_work_lease(
                            conn,
                            work_id=WorkId(b.work_id),
                            worker_id="other-slot",
                            generation=lease.generation,
                        )

                handler = _SlowCompletingHandler(run_seconds=0.2)
                driver = InlineDesignLaneDriver(
                    handler=handler,
                    lease_ttl=timedelta(seconds=2),
                    join_poll_interval_s=0.1,
                )
                other = asyncio.create_task(other_slot_finishes_b())
                await asyncio.wait_for(driver.drive_batch(envelopes=[a, b]), timeout=30.0)
                await other
                driven = {str(ctx.payload["run_id"]) for ctx in handler.contexts}
                assert driven == {a.run_id}
            finally:
                await _cleanup_committed_run(a)
                await _cleanup_committed_run(b)

    run_async(scenario())


def test_a_batch_nobody_drives_fails_within_the_progress_window(
    migrated_db: bool,  # noqa: F811
) -> None:
    """A foreign lease that never lapses and never produces a terminal row: the window closes
    join_timeout_s after the last progress, and the driver raises rather than waits forever."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            a = await _seed_committed_run("stuck")
            b = await _seed_committed_run("stuck_sibling")
            try:
                async with transaction() as conn:
                    for env in (a, b):
                        await acquire_work_lease(
                            conn,
                            work_id=WorkId(env.work_id),
                            worker_id="zombie",
                            ttl=timedelta(seconds=120),
                        )
                driver = InlineDesignLaneDriver(
                    handler=_SlowCompletingHandler(run_seconds=0.1),
                    lease_ttl=timedelta(seconds=2),
                    join_poll_interval_s=0.1,
                    join_timeout_s=1.0,
                )
                with pytest.raises(RuntimeError):
                    await asyncio.wait_for(driver.drive_batch(envelopes=[a, b]), timeout=30.0)
            finally:
                await _cleanup_committed_run(a)
                await _cleanup_committed_run(b)

    run_async(scenario())
