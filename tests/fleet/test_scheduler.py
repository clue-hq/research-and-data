"""Offline tests for the :class:`~clue_fleet.QueueBackedScheduler` (PB-B1).

Fake-queue-driven (no DB): tier-priority order, the concurrency window, input-order results,
the done-replay resume path, failure propagation (task FAILED + the caller-owns-isolation
contract), and structural conformance to the seam the M8A deep handler is typed against."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    QueueBackedScheduler,
    default_tier_priority,
)
from tests.fleet.conftest import FakeTaskQueue

from clue_core import EntityId, new_campaign_run_id
from clue_research.durable import AccountSpec


def _spec(name: str, tier: str) -> AccountSpec:
    from uuid import NAMESPACE_URL, uuid5

    return AccountSpec(entity_id=EntityId(uuid5(NAMESPACE_URL, f"sched-test-{name}")), tier=tier)


def _scheduler(queue: FakeTaskQueue, *, window: int = 2) -> QueueBackedScheduler:
    return QueueBackedScheduler(queue=queue, window=window, poll_interval=0.005)


def test_default_tier_priority_orders_names_and_numbers() -> None:
    assert default_tier_priority("top") < default_tier_priority("high")
    assert default_tier_priority("high") < default_tier_priority("mid")
    assert default_tier_priority("mid") < default_tier_priority("low")
    assert default_tier_priority("1") < default_tier_priority("2")
    assert default_tier_priority("tier_2") == 2
    assert default_tier_priority("Top") == default_tier_priority("top")
    # Unknown tiers go last, never fail.
    assert default_tier_priority("weird") > default_tier_priority("low")


def test_accounts_execute_best_tier_first_and_results_in_input_order() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue = FakeTaskQueue()
        # Input deliberately in worst-first order; execution must be best-first.
        specs = [_spec("c", "low"), _spec("a", "top"), _spec("b", "high")]
        executed: list[str] = []

        async def run_one(spec: AccountSpec) -> str:
            executed.append(spec.tier)
            return f"result:{spec.tier}"

        results = await _scheduler(queue, window=1).run_accounts(
            specs, campaign_run_id=run_id, checkpointer=None, run_one=run_one
        )
        assert executed == ["top", "high", "low"]
        # Results come back in INPUT order (the AccountScheduler contract), not execution order.
        assert results == ["result:low", "result:top", "result:high"]
        rows = await queue.list_tasks(campaign_run_id=run_id, kind=FleetTaskKind.ACCOUNT_JOB)
        assert {row.status for row in rows} == {FleetTaskStatus.DONE}

    asyncio.run(_run())


def test_concurrency_window_bounds_in_flight_jobs() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue = FakeTaskQueue()
        specs = [_spec(f"acct-{i}", "top") for i in range(8)]
        in_flight = 0
        peak = 0

        async def run_one(spec: AccountSpec) -> None:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

        await _scheduler(queue, window=3).run_accounts(
            specs, campaign_run_id=run_id, checkpointer=None, run_one=run_one
        )
        assert peak <= 3

    asyncio.run(_run())


def test_done_jobs_from_a_previous_drive_are_replayed_not_reclaimed() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue = FakeTaskQueue()
        specs = [_spec("done-before", "top"), _spec("fresh", "high")]
        # Simulate a previous (killed) drive having completed the first account.
        await queue.enqueue(
            kind=FleetTaskKind.ACCOUNT_JOB,
            campaign_run_id=run_id,
            dedup_key=str(specs[0].entity_id),
            priority=0,
        )
        queue.mark_done(FleetTaskKind.ACCOUNT_JOB, run_id, str(specs[0].entity_id))

        calls: list[str] = []

        async def run_one(spec: AccountSpec) -> str:
            calls.append(str(spec.entity_id))
            return str(spec.entity_id)

        results = await _scheduler(queue).run_accounts(
            specs, campaign_run_id=run_id, checkpointer=None, run_one=run_one
        )
        # Both specs get a result (replay still invokes run_one — idempotent + spend-free by
        # the account-step ledger), and the done task was not re-claimed.
        assert sorted(calls) == sorted(str(s.entity_id) for s in specs)
        assert results == [str(s.entity_id) for s in specs]
        done_row = queue.row(FleetTaskKind.ACCOUNT_JOB, run_id, str(specs[0].entity_id))
        assert done_row.attempts == 0  # never claimed by this drive

    asyncio.run(_run())


def test_failed_jobs_are_requeued_on_reentry() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue = FakeTaskQueue()
        spec = _spec("flaky", "top")

        attempts = 0

        async def run_one(spec: AccountSpec) -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient account fault")
            return "ok"

        scheduler = _scheduler(queue, window=1)
        with pytest.raises(RuntimeError):
            await scheduler.run_accounts(
                [spec], campaign_run_id=run_id, checkpointer=None, run_one=run_one
            )
        row = queue.row(FleetTaskKind.ACCOUNT_JOB, run_id, str(spec.entity_id))
        assert row.status is FleetTaskStatus.FAILED

        # A fresh drive (phase re-entry) explicitly re-opens FAILED jobs and succeeds.
        results = await scheduler.run_accounts(
            [spec], campaign_run_id=run_id, checkpointer=None, run_one=run_one
        )
        assert results == ["ok"]
        row = queue.row(FleetTaskKind.ACCOUNT_JOB, run_id, str(spec.entity_id))
        assert row.status is FleetTaskStatus.DONE

    asyncio.run(_run())


def test_failure_propagates_without_hanging_sibling_drainers() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue = FakeTaskQueue()
        specs = [_spec(f"n{i}", "top") for i in range(6)]
        bad = str(specs[3].entity_id)

        async def run_one(spec: AccountSpec) -> str:
            await asyncio.sleep(0.005)
            if str(spec.entity_id) == bad:
                raise RuntimeError("account exploded")
            return "ok"

        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                _scheduler(queue, window=3).run_accounts(
                    specs, campaign_run_id=run_id, checkpointer=None, run_one=run_one
                ),
                timeout=5,  # the point: no deadlocked poll loop waiting on the failed key
            )

    asyncio.run(_run())


def test_duplicate_entity_ids_are_rejected() -> None:
    async def _run() -> None:
        queue = FakeTaskQueue()
        spec = _spec("dup", "top")

        async def run_one(spec: AccountSpec) -> None:  # pragma: no cover - never called
            return None

        with pytest.raises(ValueError, match="duplicate entity_id"):
            await _scheduler(queue).run_accounts(
                [spec, spec],
                campaign_run_id=new_campaign_run_id(),
                checkpointer=None,
                run_one=run_one,
            )

    asyncio.run(_run())


def test_empty_specs_is_a_clean_noop() -> None:
    async def _run() -> None:
        async def run_one(spec: AccountSpec) -> None:  # pragma: no cover - never called
            return None

        assert (
            await _scheduler(FakeTaskQueue()).run_accounts(
                [], campaign_run_id=new_campaign_run_id(), checkpointer=None, run_one=run_one
            )
            == []
        )

    asyncio.run(_run())


def test_scheduler_satisfies_the_deep_handler_seam() -> None:
    """The queue-backed scheduler must be a drop-in for ``durable.AccountScheduler`` at the seam
    the M8A deep handler is typed against — the integration swap is then a constructor-argument
    change, zero handler edits (spec §2.1)."""
    from clue_api.deep.handler import DeepAccountScheduler

    scheduler: Any = _scheduler(FakeTaskQueue())
    assert isinstance(scheduler, DeepAccountScheduler)
