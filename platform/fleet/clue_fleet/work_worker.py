"""Generic leased fleet drain shared by project-run and recipe-execution work."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.exc import InterfaceError, OperationalError

from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import (
    DEFAULT_LEASE_TTL,
    DbWorkLeaseStore,
    LeaseGeneration,
    WorkId,
    WorkLeaseStore,
)
from clue_fleet.queue import (
    DEFAULT_TASK_STALE_AFTER,
    DbWorkQueue,
    TaskCapability,
    WorkQueue,
    WorkTaskRow,
)
from clue_obs import get_logger

log = get_logger("clue_fleet.work_worker")


@dataclass(frozen=True, slots=True)
class WorkContext:
    task_id: UUID
    work_id: WorkId
    worker_id: str
    lease_generation: LeaseGeneration
    payload: dict[str, JsonValue]
    stop_requested: asyncio.Event
    lease_lost: asyncio.Event
    task_attempt: int = 1


@dataclass(frozen=True, slots=True)
class WorkResult:
    outcome: str
    references: dict[str, JsonValue]
    requeue: bool = False
    task_finalized: bool = False
    requeue_after: timedelta | None = None

    def __post_init__(self) -> None:
        if self.requeue_after is not None:
            if not self.requeue:
                raise ValueError("requeue_after requires requeue=True")
            if self.requeue_after.total_seconds() < 0:
                raise ValueError("requeue_after cannot be negative")

    def result_ref(self) -> dict[str, JsonValue]:
        return {"outcome": self.outcome, **self.references}


@runtime_checkable
class WorkHandler(Protocol):
    @property
    def kind(self) -> FleetTaskKind: ...

    async def handle(self, context: WorkContext) -> WorkResult: ...


@runtime_checkable
class CapabilityGated(Protocol):
    """Opt-in extension of :class:`WorkHandler` for a kind whose payloads are NOT all runnable
    by every worker (R3-B).

    Most handlers own their whole kind: registering one is a complete statement that this
    process can run every task of it, and they do not implement this. A handler implements it
    when runnability varies *within* the kind — because the payload names a lane this build may
    not contain, or one gated behind a deployment flag. ``design_job`` is the shipped case: one
    fleet kind carries agent turns and brand-kit ingestions of four different
    ``ingestion_kind``s, and ``ad_assets`` needs ``LUMEN_BRAND_AD_ASSETS``.

    The declaration is read **per claim attempt**, not cached at construction, so a capability
    that depends on live configuration reflects the configuration the worker would actually
    execute under.

    A separate protocol rather than an optional member on :class:`WorkHandler` because it is a
    genuinely optional property with a meaningful default ("I can run everything of my kind"),
    and :class:`LeasedWorkWorker` can then establish it with one ``isinstance`` at construction
    instead of every handler restating an empty tuple.
    """

    @property
    def task_capabilities(self) -> tuple[TaskCapability, ...]: ...


class LeasedWorkWorker:
    """Claim any registered work kind and supervise it under a generated lease fence."""

    def __init__(
        self,
        *,
        handlers: tuple[WorkHandler, ...],
        queue: WorkQueue | None = None,
        leases: WorkLeaseStore | None = None,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        lease_ttl: timedelta = DEFAULT_LEASE_TTL,
        heartbeat_interval: float = 10.0,
        task_stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> None:
        if not handlers:
            raise ValueError("a leased worker requires at least one work handler")
        if heartbeat_interval * 2 >= lease_ttl.total_seconds():
            raise ValueError(
                "heartbeat_interval * 2 must be < lease_ttl "
                f"(got heartbeat_interval={heartbeat_interval}s, "
                f"lease_ttl={lease_ttl.total_seconds()}s)"
            )
        by_kind = {handler.kind: handler for handler in handlers}
        if len(by_kind) != len(handlers):
            raise ValueError("only one work handler may own a fleet task kind")
        if FleetTaskKind.ACCOUNT_JOB in by_kind:
            raise ValueError("account_job is a run-internal queue unit, not top-level leased work")
        self._handlers = by_kind
        self._kind_order = tuple(by_kind)
        self._next_kind = 0
        self._queue = queue if queue is not None else DbWorkQueue()
        self._leases = leases if leases is not None else DbWorkLeaseStore()
        self.worker_id = worker_id if worker_id is not None else f"worker:{uuid4()}"
        self._poll_interval = poll_interval
        self._lease_ttl = lease_ttl
        self._heartbeat_interval = heartbeat_interval
        self._task_stale_after = task_stale_after
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    async def run(self) -> None:
        log.info("worker.start", worker_id=self.worker_id)
        while not self._stop.is_set():
            try:
                drained = await self.drain_once()
            except (InterfaceError, OperationalError):
                # A cancelled sibling can close asyncpg while SQLAlchemy is returning the
                # connection. The queue methods are transaction-scoped, so retrying obtains a
                # fresh, pre-pinged connection; one poisoned checkout must not kill the fleet.
                log.warning(
                    "worker.drain_db_error",
                    worker_id=self.worker_id,
                    exc_info=True,
                )
                await self._sleep(self._poll_interval)
                continue
            if not drained:
                await self._sleep(self._poll_interval)
        log.info("worker.stop", worker_id=self.worker_id)

    def _capabilities(self, kind: FleetTaskKind) -> tuple[TaskCapability, ...]:
        """What this worker can run within ``kind`` — empty means "the whole kind" (R3-B).

        Read fresh on every claim attempt: a capability gated on a deployment flag must answer
        for the configuration the worker would execute under right now, not the one it booted
        with. A handler that raises while declaring its capabilities has no claim to make, so
        the failure is loud and the kind is skipped for this pass rather than claimed blind —
        claiming work whose runnability could not be established is exactly the defect this
        mechanism exists to prevent.
        """
        handler = self._handlers[kind]
        if not isinstance(handler, CapabilityGated):
            return ()
        return tuple(handler.task_capabilities)

    async def drain_once(self) -> bool:
        """Fair round-robin claim across registered top-level task kinds."""
        for offset in range(len(self._kind_order)):
            index = (self._next_kind + offset) % len(self._kind_order)
            kind = self._kind_order[index]
            try:
                capabilities = self._capabilities(kind)
            except Exception:
                log.exception(
                    "worker.capabilities_error",
                    worker_id=self.worker_id,
                    kind=kind.value,
                )
                continue
            task = await self._queue.claim_next(
                kind=kind,
                worker_id=self.worker_id,
                stale_after=self._task_stale_after,
                capabilities=capabilities,
            )
            if task is not None:
                self._next_kind = (index + 1) % len(self._kind_order)
                await self._run_task(task, self._handlers[kind])
                return True
        return False

    async def _run_task(self, task: WorkTaskRow, handler: WorkHandler) -> None:
        t_acquire = asyncio.get_running_loop().time()
        lease = await self._leases.acquire(
            work_id=task.work_id,
            worker_id=self.worker_id,
            ttl=self._lease_ttl,
        )
        if lease is None:
            await self._queue.requeue(task_id=task.task_id, worker_id=self.worker_id)
            await self._sleep(self._poll_interval)
            return

        generation = LeaseGeneration(lease.generation)
        lease_lost = asyncio.Event()
        context = WorkContext(
            task_id=task.task_id,
            work_id=task.work_id,
            worker_id=self.worker_id,
            lease_generation=generation,
            payload=task.payload,
            stop_requested=self._stop,
            lease_lost=lease_lost,
            task_attempt=task.attempts,
        )
        work = asyncio.create_task(handler.handle(context))
        heartbeat = asyncio.create_task(
            self._heartbeat(
                task_id=task.task_id,
                work_id=task.work_id,
                generation=generation,
                lease_lost=lease_lost,
                acquired_at=t_acquire,
            )
        )
        result: WorkResult | None = None
        try:
            done, _ = await asyncio.wait(
                {work, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if work in done:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                result = work.result()
            else:
                lease_lost.set()
                error = heartbeat.exception()
                if error is not None:
                    log.error(
                        "worker.heartbeat_crashed",
                        worker_id=self.worker_id,
                        work_id=str(task.work_id),
                        exc_info=error,
                    )
                work.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await work
                result = WorkResult(outcome="lease_lost", references={}, requeue=True)
        except Exception:
            log.exception(
                "worker.work_error",
                worker_id=self.worker_id,
                work_id=str(task.work_id),
                kind=task.kind.value,
            )
            await self._queue.finish(
                task_id=task.task_id,
                worker_id=self.worker_id,
                status=FleetTaskStatus.FAILED,
                result_ref={"outcome": "error"},
            )
            return
        finally:
            if not work.done():
                work.cancel()
            if not heartbeat.done():
                heartbeat.cancel()
            await asyncio.gather(work, heartbeat, return_exceptions=True)
            try:
                await self._leases.release(
                    work_id=task.work_id,
                    worker_id=self.worker_id,
                    generation=generation,
                )
            except Exception:
                log.warning(
                    "worker.release_error",
                    worker_id=self.worker_id,
                    work_id=str(task.work_id),
                    exc_info=True,
                )

        assert result is not None
        if result.requeue:
            await self._queue.requeue(
                task_id=task.task_id,
                worker_id=self.worker_id,
                delay=result.requeue_after,
            )
            return
        if result.task_finalized:
            return
        await self._queue.finish(
            task_id=task.task_id,
            worker_id=self.worker_id,
            status=FleetTaskStatus.DONE,
            result_ref=result.result_ref(),
        )

    async def _heartbeat(
        self,
        *,
        task_id: UUID,
        work_id: WorkId,
        generation: LeaseGeneration,
        lease_lost: asyncio.Event,
        acquired_at: float,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = acquired_at + self._lease_ttl.total_seconds()
        sleep_for = self._heartbeat_interval
        while True:
            await asyncio.sleep(sleep_for)
            t0 = loop.time()
            try:
                renewed = await self._leases.renew(
                    work_id=work_id,
                    worker_id=self.worker_id,
                    generation=generation,
                    ttl=self._lease_ttl,
                )
            except Exception:
                log.warning(
                    "worker.renew_error",
                    worker_id=self.worker_id,
                    work_id=str(work_id),
                    exc_info=True,
                )
                if loop.time() >= deadline - self._heartbeat_interval:
                    lease_lost.set()
                    return
                await self._touch(task_id, work_id)
                sleep_for = min(
                    self._heartbeat_interval,
                    max(0.05, (deadline - loop.time()) / 4),
                )
                continue
            if not renewed:
                lease_lost.set()
                return
            deadline = t0 + self._lease_ttl.total_seconds()
            sleep_for = self._heartbeat_interval
            await self._touch(task_id, work_id)

    async def _touch(self, task_id: UUID, work_id: WorkId) -> None:
        try:
            await self._queue.touch(task_id=task_id, worker_id=self.worker_id)
        except Exception:
            log.warning(
                "worker.touch_error",
                worker_id=self.worker_id,
                work_id=str(work_id),
                exc_info=True,
            )

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)


async def enqueue_work(
    queue: WorkQueue,
    *,
    kind: FleetTaskKind,
    work_id: WorkId,
    priority: int = 0,
    payload: dict[str, JsonValue] | None = None,
) -> bool:
    if kind is FleetTaskKind.ACCOUNT_JOB:
        raise ValueError("account_job must be enqueued through the project-run scheduler")
    return await queue.enqueue(
        kind=kind,
        work_id=work_id,
        dedup_key=str(work_id),
        priority=priority,
        payload=payload,
        reopen_terminal=True,
    )


__all__ = [
    "CapabilityGated",
    "LeasedWorkWorker",
    "WorkContext",
    "WorkHandler",
    "WorkResult",
    "enqueue_work",
]
