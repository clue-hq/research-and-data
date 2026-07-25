"""C5.3 generic leased work-shell characterization."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import JsonValue

from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    LeasedWorkWorker,
    LeaseGeneration,
    WorkContext,
    WorkId,
    WorkLeaseRow,
    WorkLeaseStore,
    WorkQueue,
    WorkResult,
    WorkTaskRow,
)


def _now() -> datetime:
    return datetime.now(UTC)


class _Queue:
    def __init__(self, rows: list[WorkTaskRow]) -> None:
        self.rows = deque(rows)
        self.finished: list[tuple[UUID, FleetTaskStatus, dict[str, JsonValue]]] = []
        self.requeued: list[UUID] = []

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = timedelta(seconds=60),
    ) -> WorkTaskRow | None:
        del work_id, stale_after
        for row in tuple(self.rows):
            if row.kind is kind:
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

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        del worker_id
        self.requeued.append(task_id)
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
