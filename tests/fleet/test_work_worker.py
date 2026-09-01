"""C5.3 generic leased work-shell characterization."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
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


class _Queue:
    def __init__(self, rows: list[WorkTaskRow]) -> None:
        self.rows = deque(rows)
        self.finished: list[tuple[UUID, FleetTaskStatus, dict[str, JsonValue]]] = []
        self.requeued: list[tuple[UUID, timedelta | None]] = []
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
        self, *, task_id: UUID, worker_id: str, delay: timedelta | None = None
    ) -> bool:
        del worker_id
        self.requeued.append((task_id, delay))
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
