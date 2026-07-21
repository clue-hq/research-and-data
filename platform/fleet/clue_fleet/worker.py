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

**Fencing is supervised-heartbeat + immediate mid-phase cancellation** (spec §2.3, the ruling
that replaces the earlier "cooperative fencing / abort at the next phase boundary" language). The
heartbeat is a *supervised* task, not a fire-and-forget coroutine: a renewal that raises no
longer silently kills it (the audit's finding #2 — a dead heartbeat while the phase runs on past
expiry lets a takeover worker drive the same run). Instead the heartbeat is resilient (a
transient renew fault is logged and retried) and authoritative (it proves lease ownership against
the event loop's monotonic clock and, once it can no longer prove ownership before true expiry,
declares the lease lost). ``_drive_task`` supervises the drive *and* the heartbeat together
(``asyncio.wait(FIRST_COMPLETED)``): the heartbeat finishing first is a fencing event that
**cancels the in-flight phase immediately**, so the zombie window shrinks from "the rest of the
phase" (unbounded) to cancellation latency. Hard fence tokens (a lease token checked on every
durable write) are explicitly **deferred** — they touch ``durable/`` write paths outside B1's
treaty scope and are an integration/Temporal-era follow-up; the residual is that ``advance()``'s
durable writes are still un-fenced during the cancellation-latency window, the same class as the
documented resume-path residual, bounded by the M7 ledgers + the per-entity locks.

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
    step loop — one ``advance`` per phase — so it can heartbeat, honour a graceful stop, and be
    fenced on lease loss. Fencing cancels the in-flight ``advance`` immediately (spec §2.3); the
    between-phase ``lease_lost`` check in :meth:`CampaignRunWorker._drive` is only a cheap belt."""

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
        drive = asyncio.create_task(self._drive(run_id, lease_lost))
        heartbeat = asyncio.create_task(self._heartbeat(run_id, task.task_id, lease_lost))
        outcome: str
        run: CampaignRunRow | None
        try:
            done, _pending = await asyncio.wait(
                {drive, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                # FENCING EVENT: the heartbeat finished before the drive — the lease is gone (or
                # is about to expire). Ensure the flag is set, surface any crash (never silently
                # drop the heartbeat's exception — that was the bug), then cancel the in-flight
                # phase IMMEDIATELY (mid-phase, not at the next boundary — the zombie window is
                # now cancellation latency) and take the lease_lost outcome path.
                lease_lost.set()
                hb_exc = heartbeat.exception()
                if hb_exc is not None:
                    log.error(
                        "worker.heartbeat_crashed",
                        worker_id=self.worker_id,
                        run_id=str(run_id),
                        exc_info=hb_exc,
                    )
                drive.cancel()
                # Suppress ONLY the child's cancellation — a CancelledError aimed at the worker
                # loop itself (from `await asyncio.wait`) is BaseException and still propagates.
                with contextlib.suppress(asyncio.CancelledError):
                    await drive
                outcome, run = "lease_lost", None
            else:
                # The drive finished first — stop heartbeating and read its result.
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                outcome, run = drive.result()
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
            # Neither child may outlive us (e.g. on a worker-level cancellation unwinding here).
            if not drive.done():
                drive.cancel()
            if not heartbeat.done():
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
        observed run row (``None`` only if the first status read raised). Lease loss now fences by
        *cancelling* this coroutine mid-phase (``_drive_task`` supervises the heartbeat); the
        ``lease_lost`` check below is only a cheap between-phase belt, not the real mechanism."""
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
        """The supervised, authoritative lease heartbeat (spec §2.3 — replaces cooperative
        fencing). Renews the lease each beat; when it can no longer prove ownership it sets
        ``lease_lost`` and returns, which ``_drive_task`` reads as a fencing event and uses to
        cancel the in-flight phase immediately (not at the next boundary).

        Resilient to transient faults, authoritative on true loss:

        * ``renew()`` returns ``False`` → the lease is authoritatively gone (expired or taken):
          flag lease-lost and return.
        * ``renew()`` RAISES → a transient fault (a DB blip on the renewal path — the audit's
          exact trigger). Log it (keep the traceback) and keep beating; the coroutine must NOT
          die. But we can only keep driving while we can still prove ownership — ownership is
          tracked against the event loop's monotonic clock (``deadline``, refreshed after every
          successful renew, seeded at start because the acquire just succeeded). Once we are
          within one ``heartbeat_interval`` of true expiry (no beat of safety margin left before
          the lease lapses) we can no longer guarantee a renewal in time, so we declare the lease
          lost and let the supervisor fence the phase.

        ``touch()`` failures (``False`` or exception) are logged and ignored — the drive-task
        claim heartbeat keeps a *live* long drive out of the staleness window, but its churn is
        recoverable and holder-guarded; it is not a fencing matter. (The ``heartbeat_interval <
        lease_ttl`` relation is the existing settings-validation backlog item; not enforced
        here.)"""
        loop = asyncio.get_running_loop()
        # The acquire just succeeded → we own the lease for a full TTL from now.
        deadline = loop.time() + self._lease_ttl.total_seconds()
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                renewed = await self._leases.renew(
                    campaign_run_id=run_id, worker_id=self.worker_id, ttl=self._lease_ttl
                )
            except Exception:
                log.warning(
                    "worker.renew_error",
                    worker_id=self.worker_id,
                    run_id=str(run_id),
                    exc_info=True,
                )
                if loop.time() >= deadline - self._heartbeat_interval:
                    # No safety margin left to land a beat before true expiry — ownership can no
                    # longer be proven; declare it lost so the phase is fenced before takeover.
                    log.warning(
                        "worker.lease_lost_after_renew_errors",
                        worker_id=self.worker_id,
                        run_id=str(run_id),
                    )
                    lease_lost.set()
                    return
                continue
            if not renewed:
                log.warning("worker.lease_lost", worker_id=self.worker_id, run_id=str(run_id))
                lease_lost.set()
                return
            # Renewed → ownership proven for another full TTL from now.
            deadline = loop.time() + self._lease_ttl.total_seconds()
            try:
                await self._queue.touch(task_id=task_id, worker_id=self.worker_id)
            except Exception:
                log.warning(
                    "worker.touch_error",
                    worker_id=self.worker_id,
                    run_id=str(run_id),
                    exc_info=True,
                )

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
