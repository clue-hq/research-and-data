"""C5.3 generic leased work-shell characterization."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import structlog
from pydantic import JsonValue
from sqlalchemy.exc import InterfaceError

from clue_fleet import (
    CapabilityGated,
    FleetTaskKind,
    FleetTaskStatus,
    LeasedWorkWorker,
    LeaseGeneration,
    TaskCapability,
    WorkContext,
    WorkId,
    WorkLeaseRow,
    WorkLeaseStore,
    WorkQueue,
    WorkResult,
    WorkTaskRow,
)
from clue_fleet.queue import payload_is_claimable


def _now() -> datetime:
    return datetime.now(UTC)


def test_slots_cannot_reacquire_their_workers_active_work() -> None:
    async def case():
        task = _task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH)
        following = task.model_copy(update={"task_id": uuid4(), "dedup_key": "next-revision"})
        queue = _Queue([])
        leases = _Leases()
        entered, finish = asyncio.Event(), asyncio.Event()

        class Handler(_Handler):
            async def handle(self, context):
                self.contexts.append(context)
                entered.set()
                await finish.wait()
                return WorkResult(outcome="done", references={})

        handler = Handler(task.kind)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=leases,
            worker_id="shared-worker",
            concurrency=3,
            poll_interval=0.001,
        )
        first = asyncio.create_task(worker._run_task(task, handler, slot=0))
        await entered.wait()
        await worker._run_task(following, handler, slot=1)
        assert len(handler.contexts) == 1
        assert leases.generations[task.work_id] == 1
        # Bounced off its own worker's lease: handed back for later, and the claim never ran.
        assert queue.requeued == [(following.task_id, timedelta(seconds=0.001))]
        assert queue.uncounted == [following.task_id]
        finish.set()
        await first
        await worker._run_task(following, handler, slot=2)
        assert len(handler.contexts) == 2
        assert leases.generations[task.work_id] == 2
        assert not worker._active_work

    asyncio.run(asyncio.wait_for(case(), timeout=5))


class _Queue:
    def __init__(self, rows: list[WorkTaskRow]) -> None:
        self.rows = deque(rows)
        self.finished: list[tuple[UUID, FleetTaskStatus, dict[str, JsonValue]]] = []
        self.requeued: list[tuple[UUID, timedelta | None]] = []
        self.uncounted: list[UUID] = []
        self.claimed_with: dict[FleetTaskKind, tuple[TaskCapability, ...]] = {}

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = timedelta(seconds=60),
        capabilities: tuple[TaskCapability, ...] = (),
    ) -> WorkTaskRow | None:
        del work_id, stale_after
        self.claimed_with[kind] = capabilities
        for row in tuple(self.rows):
            # Same predicate the claim statement evaluates in SQL (R3-B): an unsupported row is
            # left in the queue for a capable worker, never handed over and failed.
            if row.kind is kind and payload_is_claimable(capabilities, row.payload):
                self.rows.remove(row)
                return row.model_copy(
                    update={
                        "status": FleetTaskStatus.CLAIMED,
                        "claimed_by": worker_id,
                        "claimed_at": _now(),
                    }
                )
        return None

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, JsonValue] | None = None,
    ) -> bool:
        del worker_id
        self.finished.append((task_id, status, result_ref or {}))
        return True

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True

    async def requeue(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        delay: timedelta | None = None,
        uncount_attempt: bool = False,
    ) -> bool:
        del worker_id
        self.requeued.append((task_id, delay))
        if uncount_attempt:
            self.uncounted.append(task_id)
        return True

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        work_id: WorkId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, JsonValue] | None = None,
        reopen_terminal: bool = False,
    ) -> bool:
        del kind, work_id, dedup_key, priority, payload, reopen_terminal
        return True


class _Leases:
    def __init__(self) -> None:
        self.generations: dict[WorkId, int] = {}
        self.released: list[tuple[WorkId, int]] = []

    async def acquire(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        ttl: timedelta,
    ) -> WorkLeaseRow:
        generation = self.generations.get(work_id, 0) + 1
        self.generations[work_id] = generation
        now = _now()
        return WorkLeaseRow(
            work_id=work_id,
            worker_id=worker_id,
            generation=generation,
            acquired_at=now,
            renewed_at=now,
            expires_at=now + ttl,
            live=True,
        )

    async def renew(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
        ttl: timedelta,
    ) -> bool:
        del worker_id, ttl
        return self.generations.get(work_id) == generation

    async def release(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
    ) -> None:
        del worker_id
        self.released.append((work_id, generation))

    async def get(self, work_id: WorkId) -> WorkLeaseRow | None:
        del work_id
        return None


class _Handler:
    def __init__(self, kind: FleetTaskKind) -> None:
        self.kind = kind
        self.contexts: list[WorkContext] = []

    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        return WorkResult(
            outcome="done",
            references={
                "generation": context.lease_generation,
                "work_id": str(context.work_id),
            },
        )


class _AtomicallyFinalizingHandler(_Handler):
    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        return WorkResult(
            outcome="waiting_external",
            references={"work_id": str(context.work_id)},
            task_finalized=True,
        )


class _DelayedRequeueHandler(_Handler):
    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        return WorkResult(
            outcome="recovery_pending",
            references={},
            requeue=True,
            requeue_after=timedelta(seconds=17),
        )


class _StoppingHandler(_Handler):
    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        context.stop_requested.set()
        return WorkResult(outcome="done", references={})


class _TransientDbErrorQueue(_Queue):
    def __init__(self, rows: list[WorkTaskRow]) -> None:
        super().__init__(rows)
        self.claim_attempts = 0

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = timedelta(seconds=60),
        capabilities: tuple[TaskCapability, ...] = (),
    ) -> WorkTaskRow | None:
        self.claim_attempts += 1
        if self.claim_attempts == 1:
            raise InterfaceError(
                "SELECT next fleet task",
                {},
                RuntimeError("connection is closed"),
            )
        return await super().claim_next(
            kind=kind,
            worker_id=worker_id,
            work_id=work_id,
            stale_after=stale_after,
            capabilities=capabilities,
        )


def _task(kind: FleetTaskKind) -> WorkTaskRow:
    now = _now()
    work_id = WorkId(uuid4())
    return WorkTaskRow(
        task_id=uuid4(),
        kind=kind,
        work_id=work_id,
        dedup_key=str(work_id),
        priority=0,
        status=FleetTaskStatus.QUEUED,
        attempts=0,
        payload={},
        result_ref={},
        claimed_by=None,
        claimed_at=None,
        available_at=now,
        enqueued_at=now,
        enqueue_seq=1,
        updated_at=now,
    )


def test_one_worker_drains_project_and_graph_handlers_with_generation() -> None:
    async def scenario() -> None:
        drive = _task(FleetTaskKind.DRIVE_RUN)
        graph = _task(FleetTaskKind.EXECUTE_GRAPH)
        queue = _Queue([drive, graph])
        leases = _Leases()
        drive_handler = _Handler(FleetTaskKind.DRIVE_RUN)
        graph_handler = _Handler(FleetTaskKind.EXECUTE_GRAPH)
        worker = LeasedWorkWorker(
            handlers=(drive_handler, graph_handler),
            queue=queue,
            leases=leases,
            worker_id="worker",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        assert await worker.drain_once()
        assert await worker.drain_once()
        assert not await worker.drain_once()
        assert [item.kind for item in (drive_handler, graph_handler)] == [
            FleetTaskKind.DRIVE_RUN,
            FleetTaskKind.EXECUTE_GRAPH,
        ]
        assert drive_handler.contexts[0].lease_generation == LeaseGeneration(1)
        assert graph_handler.contexts[0].lease_generation == LeaseGeneration(1)
        assert [status for _, status, _ in queue.finished] == [
            FleetTaskStatus.DONE,
            FleetTaskStatus.DONE,
        ]
        assert len(leases.released) == 2

        assert isinstance(queue, WorkQueue)
        assert isinstance(leases, WorkLeaseStore)

    asyncio.run(scenario())


def test_domain_atomic_wait_does_not_finish_entity_task_twice() -> None:
    async def scenario() -> None:
        entity_task = _task(FleetTaskKind.ENTITY_RESEARCH_JOB)
        queue = _Queue([entity_task])
        leases = _Leases()
        handler = _AtomicallyFinalizingHandler(FleetTaskKind.ENTITY_RESEARCH_JOB)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=leases,
            worker_id="entity-worker",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        assert await worker.drain_once()
        assert handler.contexts[0].task_id == entity_task.task_id
        # The entity store changed job + task in one transaction; the generic shell must not
        # issue a second, non-atomic finish after the handler returns.
        assert queue.finished == []
        assert len(leases.released) == 1

    asyncio.run(scenario())


def test_delayed_requeue_is_delegated_to_durable_queue_without_sleeping_worker() -> None:
    async def scenario() -> None:
        task = _task(FleetTaskKind.OFFICIAL_SITE_CRAWL).model_copy(update={"attempts": 6})
        queue = _Queue([task])
        leases = _Leases()
        handler = _DelayedRequeueHandler(FleetTaskKind.OFFICIAL_SITE_CRAWL)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=leases,
            worker_id="crawl-worker",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        assert await worker.drain_once()
        assert handler.contexts[0].task_attempt == 6
        assert queue.requeued == [(task.task_id, timedelta(seconds=17))]
        assert len(leases.released) == 1

    asyncio.run(scenario())


class _HeldLeases(_Leases):
    """Another worker holds every lease."""

    async def acquire(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        ttl: timedelta,
    ) -> WorkLeaseRow | None:
        del work_id, worker_id, ttl
        return None


def _bounce_off_held_lease(waited: timedelta) -> tuple[_Queue, _Handler, list[dict]]:
    """Claim one task that has been queued for ``waited`` while its lease is held elsewhere."""
    task = _task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH)
    task = task.model_copy(update={"enqueued_at": task.enqueued_at - waited})
    queue = _Queue([task])
    handler = _Handler(task.kind)
    worker = LeasedWorkWorker(
        handlers=(handler,),
        queue=queue,
        leases=_HeldLeases(),
        worker_id="waiting-worker",
        poll_interval=1.0,
        heartbeat_interval=10,
        lease_ttl=timedelta(seconds=30),
    )
    with structlog.testing.capture_logs() as events:
        assert asyncio.run(worker.drain_once())
    return queue, handler, events


def test_a_held_lease_hands_the_task_back_for_later_without_counting_the_claim() -> None:
    """2026-10-05 (trenton): siblings behind a held lease were re-claimed every poll — one task
    reached 883 attempts in four minutes, none of it logged. The wait now grows with how long
    the task has been queued, and a claim that never ran is not an attempt."""
    queue, handler, events = _bounce_off_held_lease(timedelta(seconds=20))

    assert handler.contexts == []
    assert queue.finished == []
    ((task_id, delay),) = queue.requeued
    assert delay is not None and timedelta(seconds=10) <= delay < timedelta(seconds=11)
    assert queue.uncounted == [task_id]
    (event,) = [e for e in events if e["event"] == "worker.lease_held_requeue"]
    assert event["task_id"] == str(task_id) and event["log_level"] == "debug"


@pytest.mark.parametrize(
    ("waited", "expected"),
    [
        (timedelta(0), timedelta(seconds=1)),  # never less than one poll interval
        (timedelta(minutes=10), timedelta(seconds=30)),  # never more than one lease TTL
    ],
)
def test_the_held_lease_wait_is_bounded(waited: timedelta, expected: timedelta) -> None:
    queue, _, _ = _bounce_off_held_lease(waited)
    ((_, delay),) = queue.requeued
    assert delay is not None and abs(delay - expected) < timedelta(milliseconds=100)


def test_requeue_delay_requires_requeue_and_non_negative_duration() -> None:
    with pytest.raises(ValueError, match="requires requeue"):
        WorkResult(outcome="bad", references={}, requeue_after=timedelta(seconds=1))
    with pytest.raises(ValueError, match="cannot be negative"):
        WorkResult(
            outcome="bad",
            references={},
            requeue=True,
            requeue_after=timedelta(seconds=-1),
        )


# --- R3-B: capability-gated claims -------------------------------------------------------------


class _CapabilityGatedHandler(_Handler):
    """A handler that can run only some of its kind's payloads — the ``design_job`` shape."""

    def __init__(self, kind: FleetTaskKind, supported: frozenset[str]) -> None:
        super().__init__(kind)
        self._supported = supported

    @property
    def task_capabilities(self) -> tuple[TaskCapability, ...]:
        return (TaskCapability(field="ingestion_kind", supported=self._supported),)


def _payload_task(kind: FleetTaskKind, payload: dict[str, JsonValue]) -> WorkTaskRow:
    return _task(kind).model_copy(update={"payload": payload})


def test_a_handler_that_declares_no_capabilities_still_claims_its_whole_kind() -> None:
    """The default is unchanged behaviour: no declaration means "I run everything of my kind"."""

    async def scenario() -> None:
        task = _payload_task(FleetTaskKind.DESIGN_JOB, {"ingestion_kind": "ad_assets"})
        queue = _Queue([task])
        handler = _Handler(FleetTaskKind.DESIGN_JOB)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="ungated",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        assert not isinstance(handler, CapabilityGated)
        assert await worker.drain_once()
        assert queue.claimed_with[FleetTaskKind.DESIGN_JOB] == ()

    asyncio.run(scenario())


def test_a_stale_worker_leaves_a_lane_it_cannot_run_for_the_capable_worker() -> None:
    """The exact R3-B shape, at the claim seam.

    The stale worker's build predates the ``ad_assets`` lane (and its flag is off), so the lane
    is simply not in the capability set it claims with. It must not take that task — not
    take-and-fail it, not take-and-requeue it: it must never see it, so the row keeps its place
    in the queue for a capable worker, which then claims exactly that row.

    The RED case is the shipped defect: without the capability filter the stale worker's first
    drain takes the ``ad_assets`` row (it is first in the queue), and lane onboarding then
    depends on which of the two racing workers won.
    """

    async def scenario() -> None:
        ad_assets = _payload_task(FleetTaskKind.DESIGN_JOB, {"ingestion_kind": "ad_assets"})
        website = _payload_task(FleetTaskKind.DESIGN_JOB, {"ingestion_kind": "website"})
        queue = _Queue([ad_assets, website])

        stale = _CapabilityGatedHandler(
            FleetTaskKind.DESIGN_JOB, frozenset({"website", "pdf", "asset_upload"})
        )
        stale_worker = LeasedWorkWorker(
            handlers=(stale,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:stale",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        # It drains the lane it CAN run, then finds nothing — the ad_assets row is invisible.
        assert await stale_worker.drain_once()
        assert [context.payload for context in stale.contexts] == [{"ingestion_kind": "website"}]
        assert not await stale_worker.drain_once()
        assert [task_id for task_id, _, _ in queue.finished] == [website.task_id]
        assert queue.requeued == []
        assert [row.task_id for row in queue.rows] == [ad_assets.task_id]

        capable = _CapabilityGatedHandler(
            FleetTaskKind.DESIGN_JOB,
            frozenset({"website", "pdf", "asset_upload", "ad_assets"}),
        )
        capable_worker = LeasedWorkWorker(
            handlers=(capable,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:capable",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )
        assert await capable_worker.drain_once()
        assert [context.payload for context in capable.contexts] == [
            {"ingestion_kind": "ad_assets"}
        ]

    asyncio.run(scenario())


def test_a_turn_payload_carries_no_ingestion_discriminant_and_is_never_filtered() -> None:
    """One fleet kind, two payload shapes: the constraint applies only to the shape that
    declares the field, so every worker still claims every design turn."""

    async def scenario() -> None:
        turn = _payload_task(FleetTaskKind.DESIGN_JOB, {"kind": "agent_turn", "run_id": "run_x"})
        queue = _Queue([turn])
        handler = _CapabilityGatedHandler(FleetTaskKind.DESIGN_JOB, frozenset())
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="turns-only",
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        assert await worker.drain_once()
        assert handler.contexts[0].payload == {"kind": "agent_turn", "run_id": "run_x"}

    asyncio.run(scenario())


def test_capability_permits_mirrors_the_sql_predicate_including_the_closed_cases() -> None:
    capability = TaskCapability(field="ingestion_kind", supported=frozenset({"website"}))
    assert capability.permits({"kind": "agent_turn"})
    assert capability.permits({"ingestion_kind": "website"})
    assert not capability.permits({"ingestion_kind": "ad_assets"})
    # Fail-closed on the malformed shapes: a null or non-string discriminant is nobody's work.
    assert not capability.permits({"ingestion_kind": None})
    assert not capability.permits({"ingestion_kind": 7})
    assert payload_is_claimable((), {"ingestion_kind": "anything"})


def test_run_recovers_after_a_transient_closed_database_connection() -> None:
    async def scenario() -> None:
        task = _task(FleetTaskKind.ENTITY_RESEARCH_JOB)
        queue = _TransientDbErrorQueue([task])
        handler = _StoppingHandler(FleetTaskKind.ENTITY_RESEARCH_JOB)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="recovering-worker",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )

        await worker.run()

        assert queue.claim_attempts == 2
        assert [status for _, status, _ in queue.finished] == [FleetTaskStatus.DONE]
        assert len(handler.contexts) == 1

    asyncio.run(scenario())


# --- Task 9d: per-worker concurrency (founder ruling 2026-09-10) --------------------------------


class _BarrierHandler(_Handler):
    """Blocks inside ``handle`` until released, and records how many handles overlapped.

    The overlap counter is the assertion: sequential drains can never lift ``peak`` above 1, so a
    ``peak`` of 3 is proof that three ``handle()`` calls were in flight at the same instant.
    """

    def __init__(self, kind: FleetTaskKind, *, expected: int) -> None:
        super().__init__(kind)
        self.in_flight = 0
        self.peak = 0
        self.expected_reached = asyncio.Event()
        self.entered_once = asyncio.Event()
        self.release = asyncio.Event()
        self._expected = expected

    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.entered_once.set()
        if self.in_flight >= self._expected:
            self.expected_reached.set()
        try:
            await self.release.wait()
        finally:
            self.in_flight -= 1
        return WorkResult(outcome="done", references={"work_id": str(context.work_id)})


class _PoisonedFirstClaimQueue(_Queue):
    """The first claim of the process raises a non-database error; every later claim is normal.

    One slot therefore dies of an unhandled exception while its siblings keep draining — the
    exact shape the sibling-isolation contract is about.
    """

    def __init__(self, rows: list[WorkTaskRow]) -> None:
        super().__init__(rows)
        self.claim_attempts = 0

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = timedelta(seconds=60),
        capabilities: tuple[TaskCapability, ...] = (),
    ) -> WorkTaskRow | None:
        self.claim_attempts += 1
        if self.claim_attempts == 1:
            raise RuntimeError("poisoned claim")
        return await super().claim_next(
            kind=kind,
            worker_id=worker_id,
            work_id=work_id,
            stale_after=stale_after,
            capabilities=capabilities,
        )


class _CountingQueue(_Queue):
    """Counts claim attempts, so "did every slot start?" is a number rather than a sleep."""

    def __init__(self, rows: list[WorkTaskRow]) -> None:
        super().__init__(rows)
        self.claims = 0

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = timedelta(seconds=60),
        capabilities: tuple[TaskCapability, ...] = (),
    ) -> WorkTaskRow | None:
        self.claims += 1
        return await super().claim_next(
            kind=kind,
            worker_id=worker_id,
            work_id=work_id,
            stale_after=stale_after,
            capabilities=capabilities,
        )


async def _spin(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    """Yield to the loop until ``predicate()`` is true — no wall-clock sleeps, no flake."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def test_three_slots_run_three_handles_at_the_same_time() -> None:
    """``CLUE_FLEET_WORKER_CONCURRENCY=3``: one process, three tasks in flight together.

    RED before the change: ``run()`` is one claim→handle→finish loop, so the first ``handle``
    blocks the only loop and ``peak`` never exceeds 1 — the barrier is never reached and the
    test times out.
    """

    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.EXECUTE_GRAPH) for _ in range(3)]
        queue = _Queue(list(tasks))
        handler = _BarrierHandler(FleetTaskKind.EXECUTE_GRAPH, expected=3)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:wide",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=3,
        )
        assert worker.concurrency == 3

        running = asyncio.create_task(worker.run())
        await asyncio.wait_for(handler.expected_reached.wait(), timeout=2.0)
        assert handler.peak == 3
        assert {context.task_id for context in handler.contexts} == {t.task_id for t in tasks}

        handler.release.set()
        worker.stop()
        await asyncio.wait_for(running, timeout=2.0)
        assert [status for _, status, _ in queue.finished] == [FleetTaskStatus.DONE] * 3

    asyncio.run(scenario())


def test_one_slot_is_todays_sequential_drain() -> None:
    """The shipped default (1) must be byte-for-byte today's behaviour: no overlap, ever."""

    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.EXECUTE_GRAPH) for _ in range(3)]
        queue = _Queue(list(tasks))
        handler = _BarrierHandler(FleetTaskKind.EXECUTE_GRAPH, expected=2)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:narrow",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
        )
        assert worker.concurrency == 1

        running = asyncio.create_task(worker.run())
        await asyncio.wait_for(handler.entered_once.wait(), timeout=2.0)
        # Give every other runnable coroutine all the loop turns it could want: with one slot
        # there is nobody else to claim, so a second handle can never start.
        for _ in range(200):
            await asyncio.sleep(0)
        assert handler.peak == 1
        assert not handler.expected_reached.is_set()
        assert len(queue.rows) == 2

        handler.release.set()
        await _spin(lambda: len(queue.finished) == 3)
        worker.stop()
        await asyncio.wait_for(running, timeout=2.0)
        assert handler.peak == 1

    asyncio.run(scenario())


def test_stop_ends_every_slot() -> None:
    async def scenario() -> None:
        queue = _CountingQueue([])
        handler = _Handler(FleetTaskKind.EXECUTE_GRAPH)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:stoppable",
            poll_interval=30.0,  # only ``stop()`` can end the poll sleep this long
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=4,
        )

        running = asyncio.create_task(worker.run())
        # Four slots, an empty queue and a 30s poll: every slot claims exactly once and then
        # parks on the stop event. Four attempts is proof all four loops are alive; ``stop()``
        # then has to end all four, or the wait_for below times out.
        await _spin(lambda: queue.claims >= 4)
        worker.stop()
        await asyncio.wait_for(running, timeout=2.0)
        assert worker.stopping
        assert queue.claims == 4

    asyncio.run(scenario())


def test_a_dead_slot_does_not_kill_its_siblings_and_run_reports_the_failure() -> None:
    """Chosen semantics: a raising slot is logged and left dead; its siblings keep draining; the
    process only exits (non-zero, by re-raise) once EVERY slot has ended."""

    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.EXECUTE_GRAPH) for _ in range(2)]
        queue = _PoisonedFirstClaimQueue(list(tasks))
        handler = _Handler(FleetTaskKind.EXECUTE_GRAPH)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=_Leases(),
            worker_id="worker:poisoned",
            poll_interval=0.001,
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=3,
        )

        running = asyncio.create_task(worker.run())
        # The siblings of the dead slot drain the whole queue — the process is still working.
        await _spin(lambda: len(queue.finished) == 2)
        assert not running.done()

        worker.stop()
        with pytest.raises(RuntimeError, match="poisoned claim"):
            await asyncio.wait_for(running, timeout=2.0)

    asyncio.run(scenario())


def test_concurrency_below_one_is_a_construction_error() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        LeasedWorkWorker(
            handlers=(_Handler(FleetTaskKind.EXECUTE_GRAPH),),
            queue=_Queue([]),
            leases=_Leases(),
            heartbeat_interval=10,
            lease_ttl=timedelta(seconds=30),
            concurrency=0,
        )


# --- per-kind in-flight limit (research slowness fix 2026-10-03) ------------------------------


class _LimitedBarrierHandler(_BarrierHandler):
    def __init__(self, kind: FleetTaskKind, *, expected: int, limit: int) -> None:
        super().__init__(kind, expected=expected)
        self._limit = limit

    @property
    def max_in_flight(self) -> int:
        return self._limit


def _limited_worker(
    name: str, handlers: tuple[object, ...], queue: _Queue, *, concurrency: int
) -> LeasedWorkWorker:
    return LeasedWorkWorker(
        handlers=handlers,  # type: ignore[arg-type]
        queue=queue,
        leases=_Leases(),
        worker_id=name,
        poll_interval=0.001,
        heartbeat_interval=10,
        lease_ttl=timedelta(seconds=30),
        concurrency=concurrency,
    )


async def _shutdown(
    workers: list[LeasedWorkWorker], runs: list[asyncio.Task[None]], *handlers: object
) -> None:
    """Release every barrier and stop every worker, so a failing assertion fails fast."""
    for handler in handlers:
        release = getattr(handler, "release", None)
        if release is not None:
            release.set()
    for worker in workers:
        worker.stop()
    _done, pending = await asyncio.wait(runs, timeout=2.0)
    for task in pending:
        task.cancel()


def test_a_worker_never_claims_past_a_kinds_in_flight_limit() -> None:
    """A worker with 10 slots and a research limit of 4 leaves the other tasks for other workers
    (production: two person jobs sat claimed for 50+ minutes while another worker was idle)."""

    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(6)]
        queue = _Queue(list(tasks))
        handler = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=4, limit=4)
        worker = _limited_worker("worker:limited", (handler,), queue, concurrency=10)
        running = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(handler.expected_reached.wait(), timeout=2.0)
            for _ in range(200):
                await asyncio.sleep(0)
            assert handler.peak == 4
            assert len(queue.rows) == 2  # two tasks stay unclaimed for another worker
        finally:
            await _shutdown([worker], [running], handler)

    asyncio.run(scenario())


def test_a_second_worker_takes_the_overflow() -> None:
    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(6)]
        queue = _Queue(list(tasks))
        first = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=4, limit=4)
        second = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=2, limit=4)
        a = _limited_worker("worker:a", (first,), queue, concurrency=10)
        b = _limited_worker("worker:b", (second,), queue, concurrency=10)
        runs = [asyncio.create_task(a.run())]
        try:
            await asyncio.wait_for(first.expected_reached.wait(), timeout=2.0)
            runs.append(asyncio.create_task(b.run()))
            await asyncio.wait_for(second.expected_reached.wait(), timeout=2.0)
            assert first.peak == 4
            assert second.peak == 2
        finally:
            await _shutdown([a, b], runs, first, second)

    asyncio.run(scenario())


def test_a_kind_at_its_limit_does_not_stop_other_kinds() -> None:
    async def scenario() -> None:
        research = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(2)]
        pages = [_task(FleetTaskKind.ARV2_DISPLAY_PAGE)]
        queue = _Queue(list(research + pages))
        limited = _LimitedBarrierHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH, expected=1, limit=1)
        other = _Handler(FleetTaskKind.ARV2_DISPLAY_PAGE)
        worker = _limited_worker("worker:mixed", (limited, other), queue, concurrency=4)
        running = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(limited.expected_reached.wait(), timeout=2.0)
            await _spin(lambda: len(other.contexts) == 1)
            for _ in range(200):
                await asyncio.sleep(0)
            assert limited.peak == 1
        finally:
            await _shutdown([worker], [running], limited)

    asyncio.run(scenario())


class _FailingLimitedHandler(_Handler):
    def __init__(self, kind: FleetTaskKind) -> None:
        super().__init__(kind)
        self.calls = 0

    @property
    def max_in_flight(self) -> int:
        return 1

    async def handle(self, context: WorkContext) -> WorkResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first task fails")
        return await super().handle(context)


def test_a_failing_task_releases_its_slot() -> None:
    async def scenario() -> None:
        tasks = [_task(FleetTaskKind.ARV2_ACCOUNT_RESEARCH) for _ in range(2)]
        queue = _Queue(list(tasks))
        handler = _FailingLimitedHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH)
        worker = _limited_worker("worker:fail", (handler,), queue, concurrency=3)
        running = asyncio.create_task(worker.run())
        try:
            await _spin(lambda: handler.calls == 2)
        finally:
            await _shutdown([worker], [running])

    asyncio.run(scenario())


# --- site-turn durability, task 1 (2026-10-16): a late beat is not a lost lease ---------------


class _UnreachableThenBackLeases(_Leases):
    """Renew raises (the database is unreachable) until ``back_after`` seconds have passed, then
    answers like the real store: True while the row still names this holder and generation —
    even past expiry, since nobody else took it — and False once ``taken`` is set."""

    def __init__(self, *, back_after: float) -> None:
        super().__init__()
        self._back_after = back_after
        self._started: float | None = None
        self.taken = False
        self.renew_errors = 0
        self.renewed = 0

    async def renew(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
        ttl: timedelta,
    ) -> bool:
        loop = asyncio.get_running_loop()
        if self._started is None:
            self._started = loop.time()
        if loop.time() - self._started < self._back_after:
            self.renew_errors += 1
            raise InterfaceError("UPDATE work_lease", {}, RuntimeError("connection refused"))
        if self.taken:
            return False
        self.renewed += 1
        return await super().renew(
            work_id=work_id, worker_id=worker_id, generation=generation, ttl=ttl
        )


class _SleepingHandler(_Handler):
    def __init__(self, kind: FleetTaskKind, *, seconds: float) -> None:
        super().__init__(kind)
        self._seconds = seconds

    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        await asyncio.sleep(self._seconds)
        return WorkResult(outcome="done", references={})


def test_beats_that_land_after_expiry_keep_the_task_when_nobody_took_the_lease() -> None:
    """The database is unreachable for twice the lease TTL; when it comes back the renew lands
    (nobody claimed the work meanwhile), so the turn carries on and finishes. It used to give up
    at expiry and abandon the turn."""

    async def scenario() -> None:
        task = _task(FleetTaskKind.DESIGN_JOB)
        queue = _Queue([task])
        leases = _UnreachableThenBackLeases(back_after=0.6)
        handler = _SleepingHandler(task.kind, seconds=1.0)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=leases,
            worker_id="slow-worker",
            heartbeat_interval=0.05,
            lease_ttl=timedelta(seconds=0.3),
        )
        assert await worker.drain_once()
        assert leases.renew_errors > 0 and leases.renewed > 0
        assert not handler.contexts[0].lease_lost.is_set()
        assert [status for _, status, _ in queue.finished] == [FleetTaskStatus.DONE]
        assert queue.requeued == []

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_a_renew_that_fails_after_the_database_returns_declares_the_lease_lost() -> None:
    """Same outage, but another worker took the lease meanwhile: the first renew that reaches
    the database fails, and the turn is abandoned and handed back."""

    async def scenario() -> None:
        task = _task(FleetTaskKind.DESIGN_JOB)
        queue = _Queue([task])
        leases = _UnreachableThenBackLeases(back_after=0.6)
        leases.taken = True
        handler = _SleepingHandler(task.kind, seconds=5.0)
        worker = LeasedWorkWorker(
            handlers=(handler,),
            queue=queue,
            leases=leases,
            worker_id="slow-worker",
            heartbeat_interval=0.05,
            lease_ttl=timedelta(seconds=0.3),
        )
        loop = asyncio.get_running_loop()
        started = loop.time()
        assert await worker.drain_once()
        elapsed = loop.time() - started
        assert handler.contexts[0].lease_lost.is_set()
        assert queue.finished == []
        assert [task_id for task_id, _ in queue.requeued] == [task.task_id]
        assert 0.55 < elapsed < 2.0  # stopped when the renew failed, not at expiry or at the end

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))
