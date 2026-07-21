"""The detached ``CampaignRunWorker`` (PB-B1 — harness build step 0).

The separate process that owns *execution*: chat sessions plan and steer, the worker drives
(harness §6 — "sessions never execute research; the worker owns execution"). Its loop is a task
drain over the durable ``fleet_task`` queue:

    claim a ``drive_run`` task → acquire the run's driver lease → step the run
    (``advance`` per phase, heartbeating the lease concurrently) → finish the task with the
    run's resting state → release the lease.

**Kill-safety is inherited, not invented** (spec §2.3): kill -9 leaves the lease to expire, the
claimed task to go stale, and the run at its last durable checkpoint; the next worker re-owns
both and the M7 replay machinery (``COMMITTED`` short-circuit, phase + account-step idempotency
ledgers) makes the resume exactly-once. **Single-driver is enforced here**: the lease acquire is
the gate M7.3's zero-``stale_after`` phase idempotency was designed to stand behind — a second
worker cannot drive a leased run, and takes over only after expiry.

The worker never composes phase handlers: it drives the injected :class:`RunDriver` seam, which
:class:`~clue_research.durable.CampaignRun` satisfies structurally (asserted below). The
production composition (real handlers, budget engine, ledger) is ``clue_api`` wiring and lands
at integration (treaty §3.4); tests compose stub-handler drivers.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import JsonValue

from clue_core import CampaignRunId
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import DEFAULT_LEASE_TTL, DbLeaseStore, LeaseStore
from clue_fleet.queue import (
    DEFAULT_TASK_STALE_AFTER,
    DbTaskQueue,
    FleetTaskRow,
    TaskQueue,
)
from clue_obs import get_logger
from clue_research.durable import CampaignRun, CampaignRunRow, CampaignRunStatus

log = get_logger("clue_fleet.worker")

# Drive outcomes recorded on the finished task's ``result_ref.outcome`` — the vocabulary the B4
# projections will read. ``completed``/``failed`` mirror the run's terminal status; ``paused`` is
# a suspended run (human gate / budget graceful-stop / client pause — re-driving is a fresh
# enqueue by the resume surface); ``stalled`` is an ACTIVE run that made no progress (awaiting a
# checkpoint submission), mirroring ``run_to_completion``'s no-progress guard.
_TERMINAL_OUTCOMES = {
    CampaignRunStatus.COMPLETED: "completed",
    CampaignRunStatus.FAILED: "failed",
    CampaignRunStatus.PAUSED: "paused",
}


@runtime_checkable
class RunDriver(Protocol):
    """The slice of :class:`~clue_research.durable.CampaignRun` the worker drives (PB-B1).

    A structural seam (conventions §2) so the loop is testable with a fake driver; the real
    state machine satisfies it (asserted at the bottom of this module). The worker owns the
    step loop — one ``advance`` per phase — so it can heartbeat, honour a graceful stop, and
    abort on lease loss *between* phases (phases are the atomic unit, as in M7.3 ``pause``)."""

    async def status(self, campaign_run_id: CampaignRunId) -> CampaignRunRow: ...

    async def advance(self, campaign_run_id: CampaignRunId) -> CampaignRunRow: ...


class CampaignRunWorker:
    """The detached worker process's engine (PB-B1). Construct with the injected collaborators,
    call :meth:`run` in the process's event loop, and :meth:`stop` (e.g. from a SIGTERM handler)
    for a graceful drain — finish the in-flight phase, hand the task back, release the lease."""

    def __init__(
        self,
        *,
        driver: RunDriver,
        queue: TaskQueue | None = None,
        leases: LeaseStore | None = None,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        lease_ttl: timedelta = DEFAULT_LEASE_TTL,
        heartbeat_interval: float = 10.0,
        task_stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> None:
        self._driver = driver
        self._queue: TaskQueue = queue if queue is not None else DbTaskQueue()
        self._leases: LeaseStore = leases if leases is not None else DbLeaseStore()
        self.worker_id = worker_id if worker_id is not None else f"worker:{uuid4()}"
        self._poll_interval = poll_interval
        self._lease_ttl = lease_ttl
        self._heartbeat_interval = heartbeat_interval
        self._task_stale_after = task_stale_after
        self._stop = asyncio.Event()

    def stop(self) -> None:
        """Request a graceful drain: claim nothing further; the in-flight phase finishes, its
        task is requeued, its lease released. Safe from a signal handler."""
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    async def run(self) -> None:
        """The drain loop: claim → drive → finish, until :meth:`stop`."""
        log.info("worker.start", worker_id=self.worker_id)
        while not self._stop.is_set():
            drove = await self.drain_once()
            if not drove:
                await self._sleep(self._poll_interval)
        log.info("worker.stop", worker_id=self.worker_id)

    async def drain_once(self) -> bool:
        """Claim and drive at most one ``drive_run`` task; ``False`` when nothing was claimable
        (the caller polls). Exposed for tests and for single-shot drains."""
        task = await self._queue.claim_next(
            kind=FleetTaskKind.DRIVE_RUN,
            worker_id=self.worker_id,
            stale_after=self._task_stale_after,
        )
        if task is None:
            return False
        await self._drive_task(task)
        return True

    # -- internals --

    async def _drive_task(self, task: FleetTaskRow) -> None:
        run_id = task.campaign_run_id
        acquired = await self._leases.acquire(
            campaign_run_id=run_id, worker_id=self.worker_id, ttl=self._lease_ttl
        )
        if not acquired:
            # Another worker holds this run's lease live — it is the driver, not us. Hand the
            # task back (it will be claimable again once we or another worker retry after the
            # lease state changes) and back off one poll to avoid a tight claim/requeue spin.
            log.info("worker.lease_held_elsewhere", worker_id=self.worker_id, run_id=str(run_id))
            await self._queue.requeue(task_id=task.task_id, worker_id=self.worker_id)
            await self._sleep(self._poll_interval)
            return

        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(run_id, task.task_id, lease_lost))
        try:
            outcome, run = await self._drive(run_id, lease_lost)
        except Exception:
            # One run's fault must not kill the worker (the fleet keeps draining other runs):
            # record the task FAILED — it stays parked until an explicit requeue — and move on.
            log.exception("worker.drive_error", worker_id=self.worker_id, run_id=str(run_id))
            await self._queue.finish(
                task_id=task.task_id,
                worker_id=self.worker_id,
                status=FleetTaskStatus.FAILED,
                result_ref={"outcome": "error"},
            )
            return
        finally:
            heartbeat.cancel()
            # Release only if still ours (holder-guarded); a lost lease belongs to the taker.
            if not lease_lost.is_set():
                await self._leases.release(campaign_run_id=run_id, worker_id=self.worker_id)

        result_ref: dict[str, JsonValue] = {"outcome": outcome}
        if run is not None:
            result_ref["phase"] = run.phase.value
            result_ref["status"] = run.status.value
        log.info("worker.drive_end", worker_id=self.worker_id, run_id=str(run_id), outcome=outcome)
        if outcome in ("stopped", "lease_lost"):
            # Unfinished business: graceful stop hands the run back for any worker to continue;
            # a lost lease means someone else already owns the drive — either way the task goes
            # back to the queue (holder-guarded: a no-op if a stale-reclaim already re-owned it).
            await self._queue.requeue(task_id=task.task_id, worker_id=self.worker_id)
            return
        await self._queue.finish(
            task_id=task.task_id,
            worker_id=self.worker_id,
            status=FleetTaskStatus.DONE,
            result_ref=result_ref,
        )

    async def _drive(
        self, run_id: CampaignRunId, lease_lost: asyncio.Event
    ) -> tuple[str, CampaignRunRow | None]:
        """Advance the run phase-by-phase until it rests. Returns the drive outcome and the last
        observed run row (``None`` only if the first status read raised)."""
        run = await self._driver.status(run_id)
        while True:
            terminal = _TERMINAL_OUTCOMES.get(run.status)
            if terminal is not None:
                return terminal, run
            if self._stop.is_set():
                return "stopped", run
            if lease_lost.is_set():
                return "lease_lost", run
            before = (run.phase, run.status)
            run = await self._driver.advance(run_id)
            resting = _TERMINAL_OUTCOMES.get(run.status)
            if resting is not None:
                return resting, run
            if (run.phase, run.status) == before:
                # ACTIVE but not moving (e.g. awaiting a checkpoint submission) — stop rather
                # than spin; mirrors ``run_to_completion``'s no-progress guard.
                return "stalled", run

    async def _heartbeat(
        self, run_id: CampaignRunId, task_id: UUID, lease_lost: asyncio.Event
    ) -> None:
        """Renew the lease on an interval; on the first failed renewal, flag the drive to abort
        at its next phase boundary (cooperative fencing — spec §2.3). Each beat also re-stamps
        the drive task's claim (``touch``), so a *live* long drive never crosses the task
        staleness window and gets churned between idle workers — only a dead driver's claim goes
        stale."""
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            renewed = await self._leases.renew(
                campaign_run_id=run_id, worker_id=self.worker_id, ttl=self._lease_ttl
            )
            if not renewed:
                log.warning("worker.lease_lost", worker_id=self.worker_id, run_id=str(run_id))
                lease_lost.set()
                return
            await self._queue.touch(task_id=task_id, worker_id=self.worker_id)

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately on :meth:`stop` (a draining worker exits promptly)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)


async def enqueue_drive(
    queue: TaskQueue, campaign_run_id: CampaignRunId, *, priority: int = 0
) -> bool:
    """Offer a run to the fleet: enqueue its ``drive_run`` task (dedup key = the run id — one
    drive task per run at a time; a queued/claimed one is a no-op). ``reopen_terminal``: a
    *finished* drive task (the run paused at the human gate, stalled, or previously failed) is
    re-opened for a fresh drive, so the resume surface can always just call this after
    ``submit_checkpoint``/``resume``; tests call it directly."""
    return await queue.enqueue(
        kind=FleetTaskKind.DRIVE_RUN,
        campaign_run_id=campaign_run_id,
        dedup_key=str(campaign_run_id),
        priority=priority,
        reopen_terminal=True,
    )


# Static conformance (the ``deep/handler.py`` pattern): the real state machine must satisfy the
# seam the worker is typed against, so fake-driven loop tests exercise the surface the
# integration wiring will bind.
_CAMPAIGN_RUN_IS_A_RUN_DRIVER: type[RunDriver] = CampaignRun
