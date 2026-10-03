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
from clue_obs import bound_context, get_logger
from clue_obs.otel import CARRIER_KEYS, get_tracer, safe_attributes, task_trace_start
from clue_obs.otel.trace_ids import remember_trace
from clue_obs.sentry import capture

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


#: Payload keys copied into the bound run context for every task, when present and non-empty
#: strings. Every kind's payload names its subject with these keys already; no handler changes.
PAYLOAD_CONTEXT_KEYS: tuple[str, ...] = (
    "workspace_id",
    "project_id",
    "run_id",
    "job_id",
    "turn_id",
    "thread_id",
    "account_id",
)


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
    """Claim any registered work kind and supervise it under a generated lease fence.

    ``concurrency`` (founder ruling 2026-09-10) is how many tasks ONE process drives at once:
    :meth:`run` starts that many independent drain loops ("slots") over the *same* queue,
    leases and handler instances. Nothing about a task changes — each slot claims on its own
    (``FOR UPDATE SKIP LOCKED`` already hands two claimers two different rows), takes its own
    lease generation, and runs its own heartbeat, so a slot's failure is still one task's
    failure. The default of 1 is exactly the single loop this class shipped with.

    Two pieces of state are deliberately shared across slots: the stop event (one ``stop()``
    ends every slot) and ``_next_kind``, the round-robin cursor. Slots racing on the cursor can
    make two of them try the same kind first; the claim is atomic in the database, so they get
    different rows and fairness is unaffected — a lock there would buy nothing.
    """

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
        concurrency: int = 1,
    ) -> None:
        if not handlers:
            raise ValueError("a leased worker requires at least one work handler")
        if concurrency < 1:
            raise ValueError(f"concurrency must be at least 1 (got {concurrency})")
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
        self._concurrency = concurrency
        self._stop = asyncio.Event()
        self._active_work: set[WorkId] = set()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def concurrency(self) -> int:
        """How many drain slots :meth:`run` starts."""
        return self._concurrency

    async def run(self) -> None:
        """Drive ``concurrency`` independent drain slots until :meth:`stop` (or they all die).

        Slot failure policy: a slot that raises is logged at ``worker.slot_crashed`` and left
        dead — its siblings keep draining, because losing one slot must not cost the process
        every other kind of work it is the only drainer for. The process is only *told* once
        there is nothing left: when every slot has ended, ``run`` re-raises the first slot
        failure, which propagates through ``run_worker`` and ``asyncio.run`` to a non-zero exit.
        A supervisor then restarts a worker that is genuinely no longer working, and never one
        that is still draining.
        """
        log.info("worker.start", worker_id=self.worker_id, concurrency=self._concurrency)
        slots = [
            asyncio.create_task(self._drain_loop(slot), name=f"{self.worker_id}:slot-{slot}")
            for slot in range(self._concurrency)
        ]
        outcomes = await asyncio.gather(*slots, return_exceptions=True)
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, BaseException)
            and not isinstance(outcome, asyncio.CancelledError)
        ]
        log.info(
            "worker.stop",
            worker_id=self.worker_id,
            concurrency=self._concurrency,
            slots_failed=len(failures),
        )
        if failures:
            raise failures[0]

    async def _drain_loop(self, slot: int) -> None:
        """One slot: today's claim -> handle -> finish loop, unchanged, with a slot label."""
        log.info("worker.slot_start", worker_id=self.worker_id, slot=slot)
        try:
            while not self._stop.is_set():
                try:
                    drained = await self.drain_once(slot=slot)
                except (InterfaceError, OperationalError):
                    # A cancelled sibling can close asyncpg while SQLAlchemy is returning the
                    # connection. The queue methods are transaction-scoped, so retrying obtains a
                    # fresh, pre-pinged connection; one poisoned checkout must not kill the fleet.
                    log.warning(
                        "worker.drain_db_error",
                        worker_id=self.worker_id,
                        slot=slot,
                        exc_info=True,
                    )
                    await self._sleep(self._poll_interval)
                    continue
                if not drained:
                    await self._sleep(self._poll_interval)
        except asyncio.CancelledError:
            log.info("worker.slot_cancelled", worker_id=self.worker_id, slot=slot)
            raise
        except Exception as exc:
            # Loud here, fatal later: the sibling slots are untouched and keep draining, and
            # ``run`` turns the accumulated failures into the process exit code once they end.
            log.exception("worker.slot_crashed", worker_id=self.worker_id, slot=slot)
            capture(exc)
            raise
        log.info("worker.slot_stop", worker_id=self.worker_id, slot=slot)

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

    async def drain_once(self, *, slot: int | None = None) -> bool:
        """Fair round-robin claim across registered top-level task kinds.

        ``slot`` labels the drain loop this call belongs to, so every log line a concurrent
        process emits names the slot as well as the worker. ``None`` is a direct call (a test,
        or a single-shot drain), which belongs to no slot.
        """
        for offset in range(len(self._kind_order)):
            index = (self._next_kind + offset) % len(self._kind_order)
            kind = self._kind_order[index]
            try:
                capabilities = self._capabilities(kind)
            except Exception:
                log.exception(
                    "worker.capabilities_error",
                    worker_id=self.worker_id,
                    slot=slot,
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
                await self._run_task(task, self._handlers[kind], slot=slot)
                return True
        return False

    async def _handle_in_context(
        self, handler: WorkHandler, context: WorkContext, task: WorkTaskRow
    ) -> WorkResult:
        """Run the handler inside the task's trace and run context (lane 3 slice 2).

        The bound context (task, kind, attempt, worker, and the payload's subject ids) rides onto
        every log line, every span (``RunContextSpanProcessor``) and every Sentry tag for the
        whole handle. The ``fleet.task`` span starts a NEW trace (2026-10-03 agent-scoped tracing
        spec, R3): it links to the span whose ``traceparent`` the enqueue stamped into the
        payload, and that span's trace id is bound as ``launched_by_trace_id``, so one task is one
        trace that still names what launched it. No carrier → no link.
        """
        bound: dict[str, object] = {
            "task_id": str(task.task_id),
            "work_id": str(task.work_id),
            "fleet_kind": task.kind.value,
            "task_attempt": task.attempts,
            "worker_id": self.worker_id,
        }
        for key in PAYLOAD_CONTEXT_KEYS:
            value = task.payload.get(key)
            if isinstance(value, str) and value:
                bound[key] = value
        start = task_trace_start(task.payload)
        if start.launched_by_trace_id is not None:
            bound["launched_by_trace_id"] = start.launched_by_trace_id
        with (
            bound_context(**bound),
            get_tracer().start_as_current_span(
                "fleet.task",
                context=start.context,
                links=start.links,
                attributes=safe_attributes(bound),
            ),
        ):
            try:
                return await handler.handle(context)
            except BaseException as exc:
                # ``worker.work_error`` is logged and reported after this span closes; the
                # exception carries the task's trace there (2026-10-03 spec, R4/R5).
                remember_trace(exc)
                raise

    async def _run_task(
        self, task: WorkTaskRow, handler: WorkHandler, *, slot: int | None = None
    ) -> None:
        # Slots share a worker identity. The DB lease permits same-holder reacquisition, so
        # another slot must not replace the fence of a still-running task for this work ID.
        # Across processes the existing durable lease remains the authority.
        if task.work_id in self._active_work:
            await self._queue.requeue(task_id=task.task_id, worker_id=self.worker_id)
            await self._sleep(self._poll_interval)
            return
        self._active_work.add(task.work_id)
        try:
            await self._run_leased_task(task, handler, slot=slot)
        finally:
            self._active_work.remove(task.work_id)

    async def _run_leased_task(
        self, task: WorkTaskRow, handler: WorkHandler, *, slot: int | None = None
    ) -> None:
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
            # The W3C trace carrier belongs to the QUEUE, not to the work. ``_with_trace_carrier``
            # stamps ``traceparent``/``tracestate`` into every enqueued payload, and a handler
            # whose payload model forbids extra keys (``DesignTurnEnvelope`` is ``extra="forbid"``)
            # therefore refused every QUEUED job it was ever handed — 47 ``design_job.
            # preamble_error`` failures in one lane's logs on 2026-09-17. Stripped HERE and not at
            # the parse: ``_handle_in_context`` reads the carrier off ``task.payload`` (the row, not
            # this context) for the span's link to its launcher, while the handler sees exactly
            # the payload its caller wrote.
            payload={k: v for k, v in task.payload.items() if k not in CARRIER_KEYS},
            stop_requested=self._stop,
            lease_lost=lease_lost,
            task_attempt=task.attempts,
        )
        work = asyncio.create_task(self._handle_in_context(handler, context, task))
        heartbeat = asyncio.create_task(
            self._heartbeat(
                task_id=task.task_id,
                work_id=task.work_id,
                generation=generation,
                lease_lost=lease_lost,
                acquired_at=t_acquire,
                slot=slot,
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
                        slot=slot,
                        work_id=str(task.work_id),
                        exc_info=error,
                    )
                    capture(error)
                work.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await work
                result = WorkResult(outcome="lease_lost", references={}, requeue=True)
        except Exception as exc:
            log.exception(
                "worker.work_error",
                worker_id=self.worker_id,
                slot=slot,
                work_id=str(task.work_id),
                kind=task.kind.value,
            )
            capture(exc)
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
                    slot=slot,
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
        slot: int | None = None,
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
                    slot=slot,
                    work_id=str(work_id),
                    exc_info=True,
                )
                if loop.time() >= deadline - self._heartbeat_interval:
                    lease_lost.set()
                    return
                await self._touch(task_id, work_id, slot=slot)
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
            await self._touch(task_id, work_id, slot=slot)

    async def _touch(self, task_id: UUID, work_id: WorkId, *, slot: int | None = None) -> None:
        try:
            await self._queue.touch(task_id=task_id, worker_id=self.worker_id)
        except Exception:
            log.warning(
                "worker.touch_error",
                worker_id=self.worker_id,
                slot=slot,
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
    "PAYLOAD_CONTEXT_KEYS",
    "CapabilityGated",
    "LeasedWorkWorker",
    "WorkContext",
    "WorkHandler",
    "WorkResult",
    "enqueue_work",
]
