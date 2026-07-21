"""Offline tests for the :class:`~clue_fleet.QueueBackedScheduler` (PB-B1).

Fake-queue-driven (no DB): tier-priority order, the concurrency window, input-order results,
the done-replay resume path, failure propagation (task FAILED + the caller-owns-isolation
contract), and structural conformance to the seam the M8A deep handler is typed against."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import pytest
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    QueueBackedScheduler,
    default_tier_priority,
)
from tests.fleet.conftest import FakeTaskQueue, ProcessLocalLockFactory

from clue_core import EntityId, new_campaign_run_id
from clue_research.durable import AccountSpec, LockFactory


def _spec(name: str, tier: str) -> AccountSpec:
    from uuid import NAMESPACE_URL, uuid5

    return AccountSpec(entity_id=EntityId(uuid5(NAMESPACE_URL, f"sched-test-{name}")), tier=tier)


def _scheduler(
    queue: FakeTaskQueue, *, window: int = 2, lock_factory: LockFactory | None = None
) -> QueueBackedScheduler:
    return QueueBackedScheduler(
        queue=queue,
        window=window,
        poll_interval=0.005,
        # Each scheduler gets a fresh process-local lock factory by default; tests exercising
        # cross-run single-flight pass one shared factory to both schedulers.
        lock_factory=lock_factory if lock_factory is not None else ProcessLocalLockFactory(),
    )


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
        rows = await queue.list_tasks(project_run_id=run_id, kind=FleetTaskKind.ACCOUNT_JOB)
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
            project_run_id=run_id,
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


# --- audit finding #1: per-entity single-flight across concurrent runs -----------------------
# The QueueBackedScheduler replaces durable.AccountScheduler at the deep seam and must carry the
# SAME Doc C §4 guarantee: two campaign runs never deep-research the same entity at once. The
# queue dedup key is (kind, project_run_id, dedup_key), so two runs holding one entity are two
# distinct rows — the single-flight is the injected entity lock's doing, not the queue's.


def test_cross_run_same_entity_is_single_flighted() -> None:
    """The audit's double-research repro inverted into a gate: two runs sharing one entity, one
    shared lock factory across both schedulers → peak concurrency for the shared entity is 1."""

    async def _run() -> None:
        queue = FakeTaskQueue()  # ONE shared durable queue for both runs
        lock_factory = ProcessLocalLockFactory()  # ONE shared lock across both schedulers
        run_a, run_b = new_campaign_run_id(), new_campaign_run_id()
        shared = _spec("shared", "top")
        # Each run also carries a distinct entity so neither run is degenerate (real parallelism).
        specs_a = [shared, _spec("only-a", "high")]
        specs_b = [shared, _spec("only-b", "high")]

        in_flight: Counter[str] = Counter()
        peak: Counter[str] = Counter()

        async def run_one(spec: AccountSpec) -> str:
            key = str(spec.entity_id)
            in_flight[key] += 1
            peak[key] = max(peak[key], in_flight[key])
            await asyncio.sleep(0.02)
            in_flight[key] -= 1
            return f"result:{key}"

        results_a, results_b = await asyncio.gather(
            _scheduler(queue, lock_factory=lock_factory).run_accounts(
                specs_a, campaign_run_id=run_a, checkpointer=None, run_one=run_one
            ),
            _scheduler(queue, lock_factory=lock_factory).run_accounts(
                specs_b, campaign_run_id=run_b, checkpointer=None, run_one=run_one
            ),
        )

        # The shared entity was never in two runs at once (the single-flight guarantee)...
        assert peak[str(shared.entity_id)] == 1
        # ...and both runs still completed with correct, input-ordered results.
        assert results_a == [f"result:{s.entity_id}" for s in specs_a]
        assert results_b == [f"result:{s.entity_id}" for s in specs_b]

    asyncio.run(_run())


def test_replayed_done_job_acquires_the_entity_lock() -> None:
    """A done-from-a-previous-drive job is replayed through ``run_one`` (idempotent, spend-free),
    and that replay path is covered by the single-flight invariant too — it must acquire the
    entity lock (mirrors ``test_done_jobs_...replayed_not_reclaimed``'s enqueue + mark_done)."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue = FakeTaskQueue()
        lock_factory = ProcessLocalLockFactory()
        specs = [_spec("done-before", "top"), _spec("fresh", "high")]
        # Simulate a previous (killed) drive having completed the first account.
        await queue.enqueue(
            kind=FleetTaskKind.ACCOUNT_JOB,
            project_run_id=run_id,
            dedup_key=str(specs[0].entity_id),
            priority=0,
        )
        queue.mark_done(FleetTaskKind.ACCOUNT_JOB, run_id, str(specs[0].entity_id))

        async def run_one(spec: AccountSpec) -> str:
            return str(spec.entity_id)

        results = await _scheduler(queue, lock_factory=lock_factory).run_accounts(
            specs, campaign_run_id=run_id, checkpointer=None, run_one=run_one
        )
        assert results == [str(s.entity_id) for s in specs]
        # The replayed (done) job acquired the entity lock like any other executed job.
        assert lock_factory.acquired[str(specs[0].entity_id)] == 1

    asyncio.run(_run())


def test_lock_factory_is_required() -> None:
    """The lock factory is a REQUIRED keyword-only arg — a silent omission (as the baseline api
    composition already did for ``AccountScheduler``) becomes a construction-time ``TypeError``
    rather than a runtime double-research."""
    with pytest.raises(TypeError):
        QueueBackedScheduler(queue=FakeTaskQueue())
